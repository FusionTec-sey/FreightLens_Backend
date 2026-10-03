from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4
import pytest
from sqlalchemy.exc import DBAPIError
from Model.containermgmt.Inventory.UnitBarcode import UnitBarcode
from Schema.UnitBarcodeSchema import UnitBarcodeCreate
from Services.unit_barcode_service import register_barcode, barcode_query
from Services.inventory_posting_service import PostingConflict
from Utils.org_filter import OrgContext
from tests.test_policy_activation_concurrency import reviewed  # noqa: F401
from tests.test_stock_ledger import stock  # noqa: F401


def registration(f, key=None, factory=None, code="000-PCS"):
    return register_barcode(factory or f.factory, f.context, f.actor, product_id=f.products[0],
        payload=UnitBarcodeCreate(operation_key=key or uuid4(), expected_policy_version=1, barcode=code, unit="PCS"),
        authorize=lambda db: None)


def test_simultaneous_registration_has_one_identity(reviewed):
    f = reviewed; f.activate(); barrier = Barrier(2, timeout=10)
    def run(_):
        barrier.wait()
        try: registration(f); return "created"
        except PostingConflict: return "conflict"
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(run, range(2))) == ["conflict", "created"]
    with f.factory() as db:
        assert barcode_query(db, f.context).count() == 1


def test_concurrent_same_request_replays_once(reviewed):
    f = reviewed; f.activate(); barrier = Barrier(2, timeout=10); key = uuid4()
    def run(_):
        barrier.wait(); return registration(f, key).replayed
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(run, range(2))) == [False, True]


def test_rollback_does_not_reserve_a_barcode_and_foreign_reads_are_empty(reviewed):
    f = reviewed; f.activate(); key = uuid4()
    with pytest.raises(RuntimeError):
        with f.factory.begin() as db:
            registration(f, key, db)
            raise RuntimeError("Synthetic downstream failure")
    assert not registration(f, key).replayed
    other = OrgContext(current_org_id=f.orgs[1], allowed_org_ids=f.orgs, is_root=True)
    with f.factory() as db:
        assert barcode_query(db, other).count() == 0


def test_database_prevents_foreign_policy_binding_and_duplicate_codes(reviewed):
    f = reviewed; f.activate(); key = uuid4(); registration(f, key)
    for product_id in (f.products[0], f.products[1]):
        with pytest.raises(DBAPIError):
            with f.factory.begin() as db:
                db.add(UnitBarcode(org_id=f.orgs[0], product_id=product_id, policy_version=1,
                    barcode="000-PCS" if product_id == f.products[0] else "FOREIGN", unit="PCS", factor=1,
                    operation_key=uuid4(), created_by=f.actor))
                db.flush()
