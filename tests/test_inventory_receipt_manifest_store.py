from uuid import uuid4
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from Model.containermgmt.Inventory.ReceiptManifest import InventoryReceiptManifestRecord
from Services.inventory_receipt_manifest_store import save_receipt_manifest
from Services.inventory_posting_service import PostingConflict
from tests.test_inventory_receipt_manifest import manifest
from tests.test_inventory_receipt_source import receipt  # noqa: F401
from tests.test_sales_intent_sources import source  # noqa: F401
from tests.test_policy_activation import activation  # noqa: F401
from tests.test_policy_manager_cases import policy_cases  # noqa: F401
from tests.test_inventory_policy_drafts import draft  # noqa: F401
from tests.test_inventory_locations import locations  # noqa: F401


def save(f, key, payload, authorize=lambda db: None):
    f.db.connection()
    return save_receipt_manifest(f.db, f.context, f.user.id, key, payload, authorize=authorize)


def test_manifest_save_replay_and_database_immutability(receipt):
    f = receipt; key = uuid4(); payload = manifest(f)
    first = save(f, key, payload)
    assert first.result['status'] == 'SAVED' and not first.result['physical_posting_enabled']
    assert save(f, key, payload).replayed
    assert f.db.query(InventoryReceiptManifestRecord).filter_by(manifest_key=key).count() == 1
    row = f.db.get(InventoryReceiptManifestRecord, key)
    assert row.snapshot['source']['receipt_item_id'] == f.receipt_line.id
    for statement in ('UPDATE containermgmt.inventory_receipt_manifests SET is_deleted=true WHERE manifest_key=:key',
                      'DELETE FROM containermgmt.inventory_receipt_manifests WHERE manifest_key=:key'):
        with pytest.raises(DBAPIError):
            with f.db.begin_nested(): f.db.execute(text(statement), {'key': key})


def test_replay_rechecks_source_and_permission(receipt):
    f = receipt; key = uuid4(); payload = manifest(f)
    save(f, key, payload)
    f.db.commit()
    def denied(db): raise PermissionError('No receipt access')
    with pytest.raises(PermissionError): save(f, key, payload, denied)
    f.receipt_line.condition_ok = False; f.db.flush()
    with pytest.raises(PostingConflict): save(f, key, payload)


def test_manifest_save_rolls_back_with_caller_and_denies_foreign_scope(receipt):
    f = receipt; key = uuid4(); payload = manifest(f)
    with pytest.raises(RuntimeError):
        with f.db.begin_nested():
            save(f, key, payload)
            raise RuntimeError('Later composition failed')
    assert f.db.get(InventoryReceiptManifestRecord, key) is None
    f.context.current_org_id = f.org_b
    f.context.allowed_org_ids = [f.org_a, f.org_b]; f.context.is_root = True
    with pytest.raises(LookupError): save(f, key, payload)


def test_manifest_parent_guard_rejects_foreign_company(receipt):
    f = receipt; key = uuid4()
    save(f, key, manifest(f))
    row = f.db.get(InventoryReceiptManifestRecord, key)
    with pytest.raises(DBAPIError):
        with f.db.begin_nested():
            f.db.add(InventoryReceiptManifestRecord(manifest_key=uuid4(), org_id=f.org_b,
                receipt_id=f.receipt.id, receipt_item_id=f.receipt_line.id,
                snapshot=row.snapshot, created_by=f.user.id))
            f.db.flush()


def test_receipt_manifest_migration_replays(test_engine, monkeypatch):
    from Utils import migrate_20261004_receipt_manifests as migration
    monkeypatch.setattr(migration, 'engine', test_engine)
    migration.ensure_receipt_manifest_schema()
    migration.ensure_receipt_manifest_schema()
    with test_engine.connect() as conn:
        count = conn.execute(text("""SELECT count(*) FROM pg_trigger
            WHERE tgrelid='containermgmt.inventory_receipt_manifests'::regclass
            AND NOT tgisinternal""")).scalar()
        assert count == 2
