from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from decimal import Decimal as D
from threading import Barrier
from uuid import uuid4
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker
from Model.db import Base
from Model.Credentials.Organisation import Organisation
from Model.Credentials.users import User
from Model.containermgmt.Inventory.CostPool import InventoryCostPool, BranchCostPool
from Model.containermgmt.Inventory.PostingAuthority import (
    StoreNode, BranchAuthorityEpoch, CostPoolAuthorityEpoch)
from Model.containermgmt.Inventory.Location import InventoryBranch, StockLocation
from Model.containermgmt.Inventory.ProductPolicyDraft import ProductPolicyDraft
from Model.containermgmt.Inventory.ProductPolicyActivation import ProductPolicyActivation
from Model.containermgmt.Inventory.ManagerCase import ManagerCase
from Model.containermgmt.Inventory.StockLedger import StockBalance, StockMovement
from Model.containermgmt.Inventory.Valuation import InventoryValuation
from Model.containermgmt.Inventory.PostingOperation import PostingOperation
from Model.containermgmt.Orders.Product import Product
from Model.containermgmt.Orders.PurchaseOrder import PurchaseOrder
from Model.containermgmt.Orders.POItem import POItem
from Model.containermgmt.Orders.GoodsReceipt import GoodsReceipt, ReceiptItem
from Services.inventory_posting_service import PostingConflict
from Services.inventory_receipt_posting_service import post_receipt_value_internal
from Services.inventory_receipt_manifest_store import save_receipt_manifest
from Services.inventory_receipt_review_service import (
    request_receipt_review, review_receipt_manifest)
from Services.posting_authority_service import AuthorityClaim, CostPoolAuthorityClaim
from Schema.InventoryPolicySchema import InventoryPolicyConfig
from Schema.InventoryReceiptSchema import InventoryReceiptManifest, InventoryReceiptSource
from Utils.org_filter import OrgContext
from tests.test_inventory_receipt_movements import movement  # noqa: F401
from tests.test_inventory_receipt_source_uses import source_use  # noqa: F401
from tests.test_inventory_receipt_reviews import review  # noqa: F401
from tests.test_inventory_receipt_source import receipt  # noqa: F401
from tests.test_sales_intent_sources import source  # noqa: F401
from tests.test_policy_activation import activation  # noqa: F401
from tests.test_policy_manager_cases import policy_cases  # noqa: F401
from tests.test_inventory_policy_drafts import draft  # noqa: F401
from tests.test_inventory_locations import locations  # noqa: F401


@pytest.fixture
def receipt_value(movement):
    from Utils.migrate_20261004_receipt_valuation import prepare_receipt_valuation_schema
    f = movement
    prepare_receipt_valuation_schema(f.db.connection())
    node = f.db.query(StoreNode).filter_by(
        org_id=f.org_a, node_key=f.authority.node_key).one()
    pool = InventoryCostPool(org_id=f.org_a, code='RECEIPT',
        name='Synthetic receipt pool', created_by=f.user.id)
    f.db.add(pool); f.db.flush()
    f.db.add_all([
        BranchCostPool(org_id=f.org_a, branch_id=f.own,
            cost_pool_id=pool.id, created_by=f.user.id),
        CostPoolAuthorityEpoch(org_id=f.org_a, cost_pool_id=pool.id,
            node_id=node.id, epoch=1, state='ACTIVE',
            reason='Synthetic receipt value authority', created_by=f.user.id),
    ])
    f.db.commit()
    f.pool = pool.id
    f.cost_authority = CostPoolAuthorityClaim(
        f.org_a, pool.id, node.node_key, 1)
    return f


def post_value(f, operation, *, expected_version=0, goods_value=D('240.000000'),
        cost_authority=None, authorize=lambda db: None):
    f.db.connection(); cost_authority = cost_authority or f.cost_authority
    return post_receipt_value_internal(f.db, f.context, f.user.id, operation,
        manifest_key=f.manifest_key, classification_case_key=f.case_key,
        expected_valuation_version=expected_version,
        reviewed_goods_value_scr=goods_value,
        reason='Synthetic reviewed receipt cost',
        stock_authority=f.authority, cost_authority=cost_authority,
        authorize_stock=authorize, authorize_cost=authorize)


def test_receipt_value_is_source_linked_exact_and_replayable(receipt_value):
    f = receipt_value; operation = uuid4()
    first = post_value(f, operation)
    assert not first.replayed
    assert first.result['status'] == 'POSTED_UNRECONCILED'
    assert first.result['pool_quantity'] == '24.000000'
    assert first.result['pool_value_scr'] == '240.000000'
    assert first.result['average_cost_scr'] == '10.000000'
    f.db.commit()
    assert post_value(f, operation).replayed
    value = f.db.query(InventoryValuation).filter_by(
        org_id=f.org_a, kind='RECEIPT').one()
    receipt = f.db.query(PostingOperation).filter_by(
        org_id=f.org_a, operation_key=operation).one()
    movement = f.db.query(StockMovement).filter_by(
        org_id=f.org_a, kind='RECEIPT').one()
    assert value.balance_id == movement.balance_id
    assert value.source_version == movement.version
    assert value.quantity == movement.on_hand_delta == D('24.000000')
    assert value.goods_value_scr == D('240.000000')
    assert receipt.event_payload['kind'] == 'inventory.receipt.posted'
    assert receipt.event_payload['valuation_ids'] == [value.id]


def test_receipt_value_is_an_eligible_additional_cost_source(receipt_value):
    from Routes.Inventory.CostPoolRouter import preview_cost_allocation
    from Schema.InventoryValuationSchema import CostAllocationPreviewRequest
    f = receipt_value; post_value(f, uuid4()); f.db.commit()
    value = f.db.query(InventoryValuation).filter_by(
        org_id=f.org_a, kind='RECEIPT').one()
    preview = preview_cost_allocation(f.pool,
        CostAllocationPreviewRequest(valuation_ids=[value.id],
            total_scr='24', basis='BASE_QUANTITY'),
        db=f.db, context=f.context, user=None)
    assert preview['lines'][0]['valuation_id'] == value.id
    assert preview['lines'][0]['basis_value'] == '24.000000'
    assert preview['lines'][0]['allocated_scr'] == '24.000000'


def test_receipt_value_rolls_back_with_complete_outer_effect(receipt_value):
    f = receipt_value; operation = uuid4()
    with pytest.raises(RuntimeError):
        with f.db.begin_nested():
            post_value(f, operation)
            raise RuntimeError('Synthetic outbox failure')
    assert f.db.query(InventoryValuation).filter_by(org_id=f.org_a).count() == 0
    assert f.db.query(StockMovement).filter_by(org_id=f.org_a).count() == 0
    assert not post_value(f, operation).replayed


def test_receipt_value_replay_rechecks_permission_and_central_authority(receipt_value):
    f = receipt_value; operation = uuid4(); post_value(f, operation); f.db.commit()
    def denied(db): raise PermissionError('Cost permission revoked')
    with pytest.raises(PermissionError):
        post_value(f, operation, authorize=denied)
    with pytest.raises(PermissionError):
        post_value(f, operation, cost_authority=CostPoolAuthorityClaim(
            f.org_a, f.pool, f.cost_authority.node_key, 2))


def test_receipt_value_changed_intent_and_stale_stream_are_rejected(receipt_value):
    f = receipt_value; operation = uuid4(); post_value(f, operation); f.db.commit()
    with pytest.raises(PostingConflict):
        post_value(f, operation, goods_value=D('241.000000'))
    with pytest.raises(PostingConflict):
        post_value(f, uuid4(), expected_version=0)


def test_direct_receipt_value_without_matching_movement_is_rejected(receipt_value):
    f = receipt_value; post_value(f, uuid4()); f.db.commit()
    balance = f.db.query(StockBalance).filter_by(
        org_id=f.org_a, product_id=f.product.id).one()
    latest = f.db.query(InventoryValuation).filter_by(
        org_id=f.org_a, product_id=f.product.id).one()
    with pytest.raises(DBAPIError):
        with f.db.begin_nested():
            f.db.add(InventoryValuation(org_id=f.org_a, kind='RECEIPT',
                operation_key=uuid4(), cost_pool_id=f.pool,
                product_id=f.product.id, balance_id=balance.id,
                source_version=balance.version + 1, version=latest.version + 1,
                base_unit='PCS', quantity=D('1'), goods_value_scr=D('10'),
                additional_cost_scr=D('0'), pool_quantity=latest.pool_quantity + 1,
                pool_value_scr=latest.pool_value_scr + 10,
                calculation_policy='pool-wac-v2', currency='SCR',
                status='UNRECONCILED', reason='Bypass', created_by=f.user.id))
            f.db.flush()


def test_receipt_valuation_migration_replays(test_engine, monkeypatch):
    from Utils import migrate_20261004_receipt_valuation as migration
    monkeypatch.setattr(migration, 'engine', test_engine)
    migration.ensure_receipt_valuation_schema()
    migration.ensure_receipt_valuation_schema()
    with test_engine.connect() as conn:
        definition = conn.execute(text("""SELECT pg_get_constraintdef(oid)
            FROM pg_constraint WHERE
            conrelid='containermgmt.inventory_valuations'::regclass
            AND conname IN ('ck_valuation_kind_v3', 'ck_valuation_kind_v2')
            ORDER BY CASE WHEN conname='ck_valuation_kind_v3' THEN 0 ELSE 1 END
            LIMIT 1""")).scalar()
        assert 'RECEIPT' in definition


def _committed_receipt(test_engine):
    from Utils.migrate_20261004_receipt_movements import prepare_receipt_movement_schema
    from Utils.migrate_20261004_receipt_valuation import prepare_receipt_valuation_schema
    with test_engine.begin() as conn:
        conn.execute(text('CREATE SCHEMA IF NOT EXISTS usercredentials'))
        conn.execute(text('CREATE SCHEMA IF NOT EXISTS containermgmt'))
        Base.metadata.create_all(conn)
        prepare_receipt_movement_schema(conn)
        prepare_receipt_valuation_schema(conn)
    factory = sessionmaker(test_engine)
    token = uuid4().hex
    policy = InventoryPolicyConfig(base_unit='PCS', quantity_step='1',
        tracking='BATCH', conversions=[dict(unit='BOX', factor='12')])
    activation_case, activation_operation = uuid4(), uuid4()
    with factory.begin() as db:
        org = Organisation(name='Committed receipt ' + token)
        db.add(org); db.flush()
        actor = User(org_id=org.id, username='receipt-' + token,
            password_hash='unusable-test-only')
        reviewer = User(org_id=org.id, username='review-' + token,
            password_hash='unusable-test-only')
        db.add_all([actor, reviewer]); db.flush()
        branch = InventoryBranch(org_id=org.id, code='STORE' + token[:8].upper(),
            name='Synthetic store', kind='STORE', created_by=actor.id)
        product = Product(org_id=org.id, sku='SKU-' + token, name='Synthetic batch',
            unit='PCS', current_stock=0, status='active', is_shared=False,
            created_by=actor.id)
        db.add_all([branch, product]); db.flush()
        location = StockLocation(org_id=org.id, branch_id=branch.id,
            code='RECEIVE', name='Receiving', kind='SITE', created_by=actor.id)
        draft = ProductPolicyDraft(org_id=org.id, product_id=product.id,
            version=1, config=policy.model_dump(mode='json'), created_by=actor.id)
        activation = ManagerCase(org_id=org.id, case_key=activation_case,
            action='inventory.policy.activate', source_type='product.policy',
            source_key=str(product.id), source_version=1,
            binding={'synthetic_setup': True}, reason='Synthetic setup',
            created_by=actor.id)
        activation_receipt = PostingOperation(org_id=org.id,
            operation_key=activation_operation, kind='test.policy.seed',
            request_digest='0' * 64, result={}, event_payload={}, created_by=actor.id)
        db.add_all([location, draft, activation, activation_receipt]); db.flush()
        db.add(ProductPolicyActivation(org_id=org.id, product_id=product.id,
            version=1, draft_version=1, case_key=activation_case,
            operation_key=activation_operation, config=policy.model_dump(mode='json'),
            created_by=actor.id))
        po = PurchaseOrder(org_id=org.id, po_number='PO-' + token,
            doc_type='PO', created_by=actor.id)
        db.add(po); db.flush()
        po_item = POItem(org_id=org.id, po_id=po.id, product_id=product.id,
            description='Synthetic batch', quantity_ordered=D('10'), unit='BOX',
            created_by=actor.id)
        receipt = GoodsReceipt(org_id=org.id, po_id=po.id,
            receipt_number='GR-' + token, received_date=date(2026, 10, 4),
            status='SUBMITTED', posting_version=1,
            submitted_at=datetime.now(timezone.utc), created_by=actor.id)
        db.add_all([po_item, receipt]); db.flush()
        line = ReceiptItem(receipt_id=receipt.id, po_item_id=po_item.id,
            description='Synthetic batch', unit='BOX', received_quantity=D('2'),
            damaged_quantity=D('0'), incorrect_quantity=D('0'),
            condition_ok=True, created_by=actor.id)
        node = StoreNode(org_id=org.id, node_key=uuid4(), created_by=actor.id)
        pool = InventoryCostPool(org_id=org.id, code='POOL' + token[:8].upper(),
            name='Synthetic pool', created_by=actor.id)
        db.add_all([line, node, pool]); db.flush()
        db.add_all([
            BranchAuthorityEpoch(org_id=org.id, branch_id=branch.id,
                node_id=node.id, epoch=1, state='ACTIVE', reason='Synthetic',
                created_by=actor.id),
            BranchCostPool(org_id=org.id, branch_id=branch.id,
                cost_pool_id=pool.id, created_by=actor.id),
            CostPoolAuthorityEpoch(org_id=org.id, cost_pool_id=pool.id,
                node_id=node.id, epoch=1, state='ACTIVE', reason='Synthetic',
                created_by=actor.id),
        ])
        ids = dict(org=org.id, actor=actor.id, reviewer=reviewer.id,
            branch=branch.id, location=location.id, product=product.id,
            receipt=receipt.id, line=line.id, pool=pool.id, node_key=node.node_key)
    context = OrgContext(current_org_id=ids['org'], allowed_org_ids=[ids['org']],
        is_root=False)
    manifest_key, case_key = uuid4(), uuid4()
    source = InventoryReceiptSource(receipt_id=ids['receipt'],
        receipt_item_id=ids['line'], branch_id=ids['branch'],
        location_id=ids['location'], expected_policy_version=1)
    manifest = InventoryReceiptManifest(source=source, on_hand='24', damaged='0',
        quarantined='0', reason='Synthetic classification', batches=[dict(
            identity=dict(batch_key=uuid4(), code='LOT-' + token[:8],
                shade='A', calibre='1'), on_hand='24', damaged='0',
            quarantined='0')])
    save_receipt_manifest(factory, context, ids['actor'], manifest_key, manifest,
        authorize=lambda db: None)
    with factory.begin() as db:
        request_receipt_review(db, context, ids['actor'], case_key,
            manifest_key=manifest_key, reason='Synthetic review',
            authorize=lambda db: None)
    with factory.begin() as db:
        review_receipt_manifest(db, context, ids['reviewer'], uuid4(),
            manifest_key=manifest_key, case_key=case_key, expected_version=1,
            outcome='APPROVED', reason='Inspected', authorize=lambda db: None)
    return dict(factory=factory, context=context, ids=ids,
        manifest_key=manifest_key, case_key=case_key,
        stock_authority=AuthorityClaim(ids['org'], ids['branch'], ids['node_key'], 1),
        cost_authority=CostPoolAuthorityClaim(ids['org'], ids['pool'], ids['node_key'], 1))


@pytest.mark.parametrize('same_key', [False, True])
def test_competing_committed_receipt_operations_have_one_business_effect(test_engine, same_key):
    f = _committed_receipt(test_engine)
    barrier = Barrier(2, timeout=10)
    def run(operation):
        barrier.wait()
        try:
            return post_receipt_value_internal(f['factory'], f['context'], f['ids']['actor'],
                operation, manifest_key=f['manifest_key'],
                classification_case_key=f['case_key'],
                expected_valuation_version=0,
                reviewed_goods_value_scr=D('240.000000'),
                reason='Synthetic reviewed receipt cost',
                stock_authority=f['stock_authority'],
                cost_authority=f['cost_authority'],
                authorize_stock=lambda db: None, authorize_cost=lambda db: None)
        except PostingConflict:
            return None
    first = uuid4()
    operations = (first, first if same_key else uuid4())
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(run, operations))
    if same_key:
        assert sorted(result.replayed for result in results) == [False, True]
    else:
        assert sum(result is not None for result in results) == 1
    with f['factory']() as db:
        assert db.query(StockMovement).filter_by(
            org_id=f['ids']['org'], kind='RECEIPT').count() == 1
        assert db.query(InventoryValuation).filter_by(
            org_id=f['ids']['org'], kind='RECEIPT').count() == 1
        assert db.query(PostingOperation).filter_by(
            org_id=f['ids']['org'], kind='inventory.receipt.post-value.v1').count() == 1
        assert db.get(Product, f['ids']['product']).current_stock == 0
