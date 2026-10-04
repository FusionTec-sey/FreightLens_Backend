from uuid import uuid4
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from Model.containermgmt.Inventory.PostingAuthority import StoreNode, BranchAuthorityEpoch
from Model.containermgmt.Inventory.StockLedger import StockBalance, StockMovement
from Services.posting_authority_service import AuthorityClaim
from Services.inventory_posting_service import execute_once, PostingEffect, PostingConflict
from Services.inventory_receipt_source_use_service import consume_receipt_source
from Services.inventory_receipt_movement_service import check_receipt_stock, append_receipt_stock
from tests.test_inventory_receipt_source_uses import source_use  # noqa: F401
from tests.test_inventory_receipt_reviews import review  # noqa: F401
from tests.test_inventory_receipt_source import receipt  # noqa: F401
from tests.test_sales_intent_sources import source  # noqa: F401
from tests.test_policy_activation import activation  # noqa: F401
from tests.test_policy_manager_cases import policy_cases  # noqa: F401
from tests.test_inventory_policy_drafts import draft  # noqa: F401
from tests.test_inventory_locations import locations  # noqa: F401


@pytest.fixture
def movement(source_use):
    from Utils.migrate_20261004_receipt_movements import prepare_receipt_movement_schema
    f = source_use
    prepare_receipt_movement_schema(f.db.connection())
    node = StoreNode(org_id=f.org_a, node_key=uuid4(), created_by=f.user.id)
    f.db.add(node); f.db.flush()
    f.db.add(BranchAuthorityEpoch(org_id=f.org_a, branch_id=f.own, node_id=node.id,
        epoch=1, state='ACTIVE', reason='Synthetic receipt authority', created_by=f.user.id))
    f.db.commit()
    f.authority = AuthorityClaim(f.org_a, f.own, node.node_key, 1)
    return f


def post(movement, operation, *, authority=None, authorize=lambda db: None):
    f = movement; f.db.connection(); authority = authority or f.authority
    request = {'manifest_key': str(f.manifest_key), 'case_key': str(f.case_key),
        'authority': {'branch_id': authority.branch_id, 'node_key': str(authority.node_key), 'epoch': authority.epoch}}
    def guard(db):
        check_receipt_stock(db, f.context, manifest_key=f.manifest_key,
            authority=authority, authorize=authorize)
    def effect(db):
        consume_receipt_source(db, f.context, f.user.id, operation,
            manifest_key=f.manifest_key, case_key=f.case_key, authorize=authorize)
        rows = append_receipt_stock(db, f.context, f.user.id, operation,
            manifest_key=f.manifest_key, authority=authority, authorize=authorize)
        return PostingEffect({'movements': rows}, {'kind': 'test.receipt-moved'})
    return execute_once(f.db, f.context, f.user.id, operation, 'test.receipt-movement',
        request, effect, authorize=guard)


def test_approved_batch_receipt_creates_exact_location_stock_and_replays(movement):
    f = movement; operation = uuid4()
    result = post(f, operation)
    assert not result.replayed and len(result.result['movements']) == 1
    f.db.commit()
    assert post(f, operation).replayed
    balance = f.db.query(StockBalance).filter_by(org_id=f.org_a, product_id=f.product.id).one()
    movement_row = f.db.query(StockMovement).filter_by(org_id=f.org_a, balance_id=balance.id).one()
    assert str(balance.on_hand) == '24.000000' and balance.tracking_policy == 'BATCH'
    assert str(movement_row.on_hand_delta) == '24.000000' and movement_row.kind == 'RECEIPT'
    assert f.product.current_stock == 0


def test_receipt_movement_rolls_back_with_later_outer_failure(movement):
    f = movement; operation = uuid4(); f.db.connection()
    with pytest.raises(RuntimeError):
        with f.db.begin_nested():
            consume_receipt_source(f.db, f.context, f.user.id, operation,
                manifest_key=f.manifest_key, case_key=f.case_key, authorize=lambda db: None)
            append_receipt_stock(f.db, f.context, f.user.id, operation,
                manifest_key=f.manifest_key, authority=f.authority, authorize=lambda db: None)
            raise RuntimeError('Synthetic valuation failure')
    assert f.db.query(StockMovement).filter_by(org_id=f.org_a).count() == 0
    assert not post(f, operation).replayed


def test_replay_rechecks_permission_and_node_authority(movement):
    f = movement; operation = uuid4(); post(f, operation); f.db.commit()
    def denied(db): raise PermissionError('Receipt permission revoked')
    with pytest.raises(PermissionError): post(f, operation, authorize=denied)
    with pytest.raises(PermissionError): post(f, operation,
        authority=AuthorityClaim(f.org_a, f.own, f.authority.node_key, 2))


def test_authority_is_rejected_before_receipt_source_is_revalidated(movement, monkeypatch):
    f = movement
    touched = []
    monkeypatch.setattr('Services.inventory_receipt_movement_service.check_receipt_source',
        lambda *args, **kwargs: touched.append(True))
    with pytest.raises(PermissionError):
        check_receipt_stock(f.db, f.context, manifest_key=f.manifest_key,
            authority=AuthorityClaim(f.org_a, f.own, f.authority.node_key, 2),
            authorize=lambda db: None)
    assert touched == []


def test_direct_receipt_movement_without_consumed_source_is_rejected(movement):
    f = movement; post(f, uuid4()); f.db.commit()
    balance = f.db.query(StockBalance).filter_by(org_id=f.org_a, product_id=f.product.id).one()
    with pytest.raises(DBAPIError):
        with f.db.begin_nested():
            balance.on_hand += 24
            balance.version += 1
            balance.updated_by = f.user.id
            f.db.flush()
            f.db.add(StockMovement(org_id=f.org_a, balance_id=balance.id, operation_key=uuid4(),
                version=balance.version, kind='RECEIPT', reason='Bypass', on_hand_delta=24,
                reserved_delta=0, on_hand=balance.on_hand, reserved=balance.reserved,
                damaged=balance.damaged, quarantined=balance.quarantined, created_by=f.user.id))
            f.db.flush()


def test_receipt_movement_migration_replays(test_engine, monkeypatch):
    from Utils import migrate_20261004_receipt_movements as migration
    monkeypatch.setattr(migration, 'engine', test_engine)
    migration.ensure_receipt_movement_schema(); migration.ensure_receipt_movement_schema()
    with test_engine.connect() as conn:
        definition = conn.execute(text("""SELECT pg_get_constraintdef(oid) FROM pg_constraint
            WHERE conrelid='containermgmt.inventory_stock_movements'::regclass
            AND conname='ck_stock_movement_kind'""")).scalar()
        assert 'RECEIPT' in definition
