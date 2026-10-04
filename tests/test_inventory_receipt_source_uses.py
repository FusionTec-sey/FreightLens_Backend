from uuid import uuid4
import pytest
from sqlalchemy.exc import DBAPIError
from Model.containermgmt.Inventory.ReceiptSourceUse import InventoryReceiptSourceUse
from Services.inventory_posting_service import execute_once, PostingEffect, PostingConflict
from Services.inventory_receipt_source_use_service import check_receipt_source, consume_receipt_source
from Services.inventory_receipt_manifest_store import save_receipt_manifest
from Services.inventory_receipt_review_service import request_receipt_review, review_receipt_manifest
from tests.test_inventory_receipt_manifest import manifest
from tests.test_inventory_receipt_reviews import review  # noqa: F401
from tests.test_inventory_receipt_source import receipt  # noqa: F401
from tests.test_sales_intent_sources import source  # noqa: F401
from tests.test_policy_activation import activation  # noqa: F401
from tests.test_policy_manager_cases import policy_cases  # noqa: F401
from tests.test_inventory_policy_drafts import draft  # noqa: F401
from tests.test_inventory_locations import locations  # noqa: F401


@pytest.fixture
def source_use(review):
    f = review
    # Model is part of Base metadata for the isolated test database. The dedicated
    # migration replay is verified separately against the engine fixture.
    f.db.connection()
    request_receipt_review(f.db, f.context, f.user.id, f.case_key,
        manifest_key=f.manifest_key, reason='Classify synthetic receipt', authorize=lambda db: None)
    f.db.commit(); f.db.connection()
    review_receipt_manifest(f.db, f.context, f.reviewer.id, uuid4(), manifest_key=f.manifest_key,
        case_key=f.case_key, expected_version=1, outcome='APPROVED', reason='Inspected', authorize=lambda db: None)
    f.db.commit()
    return f


def post(f, manifest_key, case_key, operation_key, *, fail=False, authorize=lambda db: None):
    f.db.connection()
    request = {'manifest_key': str(manifest_key), 'case_key': str(case_key)}
    def effect(db):
        row = consume_receipt_source(db, f.context, f.user.id, operation_key,
            manifest_key=manifest_key, case_key=case_key, authorize=authorize)
        if fail: raise RuntimeError('Synthetic downstream failure')
        return PostingEffect({'source_use_id': row.id}, {'kind': 'test.receipt-source-used'})
    return execute_once(f.db, f.context, f.user.id, operation_key,
        'test.receipt-source-use', request, effect,
        authorize=lambda db: check_receipt_source(db, f.context,
            manifest_key=manifest_key, authorize=authorize))


def second_approved_manifest(f):
    manifest_key, case_key = uuid4(), uuid4()
    f.db.connection()
    save_receipt_manifest(f.db, f.context, f.user.id, manifest_key, manifest(f), authorize=lambda db: None)
    f.db.commit(); f.db.connection()
    request_receipt_review(f.db, f.context, f.user.id, case_key, manifest_key=manifest_key,
        reason='Second synthetic classification', authorize=lambda db: None)
    f.db.commit(); f.db.connection()
    review_receipt_manifest(f.db, f.context, f.reviewer.id, uuid4(), manifest_key=manifest_key,
        case_key=case_key, expected_version=1, outcome='APPROVED', reason='Inspected second', authorize=lambda db: None)
    f.db.commit()
    return manifest_key, case_key


def test_approved_manifest_claim_is_atomic_retryable_and_non_posting(source_use):
    f = source_use; operation = uuid4()
    first = post(f, f.manifest_key, f.case_key, operation)
    assert not first.replayed
    assert post(f, f.manifest_key, f.case_key, operation).replayed
    row = f.db.query(InventoryReceiptSourceUse).filter_by(org_id=f.org_a).one()
    assert str(row.quantity) == '24.000000' and row.base_unit == 'PCS'
    assert f.product.current_stock == 0


def test_replay_rechecks_permission_and_current_receipt_source(source_use):
    f = source_use; operation = uuid4(); post(f, f.manifest_key, f.case_key, operation); f.db.commit()
    def denied(db): raise PermissionError('Receipt posting permission revoked')
    with pytest.raises(PermissionError): post(f, f.manifest_key, f.case_key, operation, authorize=denied)
    f.receipt_line.condition_ok = False; f.db.commit()
    with pytest.raises(PostingConflict, match='changed'):
        post(f, f.manifest_key, f.case_key, operation)


def test_other_approved_manifest_cannot_reconsume_full_receipt_line(source_use):
    f = source_use; other_manifest, other_case = second_approved_manifest(f)
    post(f, f.manifest_key, f.case_key, uuid4())
    with pytest.raises(PostingConflict, match='already been consumed'):
        with f.db.begin_nested():
            consume_receipt_source(f.db, f.context, f.user.id, uuid4(),
                manifest_key=other_manifest, case_key=other_case, authorize=lambda db: None)


def test_outer_failure_releases_approval_and_source_capacity(source_use):
    f = source_use
    with pytest.raises(RuntimeError):
        with f.db.begin_nested():
            consume_receipt_source(f.db, f.context, f.user.id, uuid4(),
                manifest_key=f.manifest_key, case_key=f.case_key, authorize=lambda db: None)
            raise RuntimeError('Synthetic downstream failure')
    assert f.db.query(InventoryReceiptSourceUse).filter_by(org_id=f.org_a).count() == 0
    assert not post(f, f.manifest_key, f.case_key, uuid4()).replayed


def test_database_rejects_unapproved_direct_source_use(source_use):
    f = source_use
    with pytest.raises(DBAPIError):
        with f.db.begin_nested():
            f.db.add(InventoryReceiptSourceUse(org_id=f.org_a, operation_key=uuid4(), manifest_key=f.manifest_key,
                receipt_id=f.receipt.id, receipt_item_id=f.receipt_line.id, quantity='24.000000',
                base_unit='PCS', created_by=f.user.id))
            f.db.flush()


def test_foreign_company_never_falls_back(source_use):
    f = source_use
    f.context.current_org_id = f.org_b; f.context.allowed_org_ids = [f.org_a, f.org_b]; f.context.is_root = True
    with pytest.raises(LookupError): post(f, f.manifest_key, f.case_key, uuid4())


def test_receipt_source_use_migration_replays(test_engine, monkeypatch):
    from Utils import migrate_20261004_receipt_source_uses as migration
    monkeypatch.setattr(migration, 'engine', test_engine)
    migration.ensure_receipt_source_uses_schema(); migration.ensure_receipt_source_uses_schema()
