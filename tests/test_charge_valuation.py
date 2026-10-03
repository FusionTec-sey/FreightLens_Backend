from decimal import Decimal
from uuid import uuid4
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from Model.containermgmt.Inventory.Valuation import InventoryValuation
from Services.charge_valuation_service import append_allocated_charge_values
from Services.cost_charge_review_service import CHARGE_POSTING_KIND
from Services.cost_charge_use_service import consume_cost_charge
from Services.manager_case_service import consume_case
from Services.inventory_posting_service import execute_once, PostingEffect, PostingConflict
from tests.test_cost_evidence_replay import replay  # noqa: F401
from tests.test_cost_content_reviews import content_review  # noqa: F401
from tests.test_cost_charge_reviews import charge_review, charge, allocation, valued, stock  # noqa: F401


@pytest.fixture
def charge_value(replay):
    f = replay
    def post(*, fail=False, version=1):
        def effect(db):
            consume_cost_charge(db, f.context, f.actor, f.post_key, f.payload.operation_key, f.expected,
                authorize=lambda db: None, load_evidence=lambda db: f.replay_evidence(db))
            consume_case(db, f.context, f.actor, f.post_key, case_key=f.content_case,
                binding=f.content_binding, load_binding=f.content_load, authorize=lambda db: None)
            ids = append_allocated_charge_values(db, f.context, f.actor, f.post_key,
                expected_versions={f.products[0]: version}, authorize=lambda db: None)
            if fail: raise RuntimeError('Synthetic later failure')
            return PostingEffect({'ids': ids}, {'kind': 'test.actual-charge-value'})
        return execute_once(f.factory, f.context, f.actor, f.post_key, CHARGE_POSTING_KIND,
            {'version': version}, effect, authorize=lambda db: f.replay_evidence(db))
    f.post_value = post
    return f


def test_cost_entry_in_same_stream_adds_no_stock_and_replays(charge_value):
    f = charge_value
    result = f.post_value()
    assert f.post_value().replayed
    with f.factory() as db:
        row = db.get(InventoryValuation, result.result['ids'][0])
        source = db.get(InventoryValuation, row.source_valuation_id)
        assert row.kind == 'CHARGE' and source.kind == 'OPENING'
        assert row.quantity == row.goods_value_scr == 0
        assert row.additional_cost_scr == Decimal('12.34')
        assert row.pool_quantity == source.pool_quantity
        assert row.pool_value_scr == source.pool_value_scr + Decimal('12.34')
        assert row.version == 2


def test_all_effects_roll_back_before_retry(charge_value):
    f = charge_value
    with pytest.raises(RuntimeError): f.post_value(fail=True)
    with f.factory() as db:
        assert db.query(InventoryValuation).filter_by(org_id=f.orgs[0], kind='CHARGE').count() == 0
    assert f.content_evidence() == f.expected
    assert not f.post_value().replayed


def test_stale_stream_version_rolls_back_consumption(charge_value):
    f = charge_value
    with pytest.raises(PostingConflict): f.post_value(version=2)
    assert f.content_evidence() == f.expected


def test_changed_physical_stock_requires_reconciliation(charge_value):
    from Model.containermgmt.Inventory.StockLedger import StockBalance
    f = charge_value
    with f.factory.begin() as db:
        source = db.query(InventoryValuation).filter_by(org_id=f.orgs[0], kind='OPENING').first()
        db.get(StockBalance, source.balance_id).on_hand -= Decimal('1')
    with pytest.raises(PostingConflict, match='late-cost reconciliation'):
        f.post_value()
    assert f.content_evidence() == f.expected


def test_migration_replay_preserves_both_entry_types(charge_value, monkeypatch):
    from Utils import migrate_20261003_valuation_charges as migration
    f = charge_value; f.post_value()
    monkeypatch.setattr(migration, 'engine', f.factory.kw['bind'])
    migration.ensure_valuation_charges_schema(); migration.ensure_valuation_charges_schema()
    assert f.post_value().replayed


def test_charge_entries_cannot_be_reallocated(charge_value):
    from Routes.Inventory.CostPoolRouter import preview_cost_allocation
    from Schema.InventoryValuationSchema import CostAllocationPreviewRequest
    from fastapi import HTTPException
    f = charge_value; key = f.post_value().result['ids'][0]
    with f.factory() as db, pytest.raises(HTTPException):
        preview_cost_allocation(f.pool, CostAllocationPreviewRequest(valuation_ids=[key], total_scr='1', basis='GOODS_VALUE'), db=db, context=f.context)


def test_charge_entry_is_immutable(charge_value):
    f = charge_value; key = f.post_value().result['ids'][0]
    with f.factory.begin() as db, pytest.raises(DBAPIError):
        db.execute(text('UPDATE containermgmt.inventory_valuations SET additional_cost_scr=0 WHERE id=:id'), {'id': key})


def test_unapproved_insert_is_rejected_by_database(charge_value):
    f = charge_value; key = f.post_value().result['ids'][0]
    with f.factory.begin() as db, pytest.raises(DBAPIError, match='requires matching'):
        row = db.get(InventoryValuation, key)
        fields = {name: getattr(row, name) for name in ('org_id', 'kind', 'source_valuation_id', 'cost_pool_id',
            'product_id', 'balance_id', 'source_version', 'base_unit', 'quantity', 'goods_value_scr',
            'additional_cost_scr', 'pool_quantity', 'pool_value_scr', 'calculation_policy', 'currency', 'status', 'reason', 'created_by')}
        db.add(InventoryValuation(**fields, operation_key=uuid4(), version=3)); db.flush()


def test_concurrent_charge_posting_has_one_valuation_effect(charge_value):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    f = charge_value; barrier = Barrier(2)
    def run(_):
        barrier.wait(timeout=10)
        return f.post_value().replayed
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(run, range(2))) == [False, True]
    with f.factory() as db:
        assert db.query(InventoryValuation).filter_by(org_id=f.orgs[0], kind='CHARGE').count() == 1
