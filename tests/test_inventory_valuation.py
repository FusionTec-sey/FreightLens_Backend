from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from decimal import Decimal as D
from uuid import uuid4
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from Model.containermgmt.Inventory.CostPool import InventoryCostPool, BranchCostPool
from Model.containermgmt.Inventory.Valuation import InventoryValuation
from Model.containermgmt.Inventory.StockLedger import StockBalance
from Model.containermgmt.Inventory.Location import StockLocation
from Services.inventory_valuation_service import record_opening_value
from Services.inventory_posting_service import PostingConflict
from Utils.org_filter import OrgContext
from tests.test_stock_ledger import stock  # noqa: F401


@pytest.fixture
def valued(stock):
    f = stock
    f.balance = f.open().result['balance_id']
    with f.factory.begin() as db:
        pool = InventoryCostPool(org_id=f.orgs[0], code='TEST', name='Test pool', created_by=f.actor)
        db.add(pool); db.flush(); f.pool = pool.id
        db.add(BranchCostPool(org_id=f.orgs[0], branch_id=f.branches[0], cost_pool_id=pool.id, created_by=f.actor))
    f.key = uuid4()
    def post(**kw):
        return record_opening_value(kw.pop('factory', f.factory), kw.pop('context', f.context), f.actor,
            kw.pop('key', f.key), balance_id=f.balance, expected_version=kw.pop('expected_version', 0),
            goods_value_scr=kw.pop('goods_value_scr', D('100')), additional_cost_scr=D('20'),
            reason='Synthetic approved opening cost', authorize=kw.pop('authorize', lambda db: None), **kw)
    f.value = post
    return f


def test_opening_is_source_linked_exact_and_repeatable(valued):
    f = valued
    result = f.value()
    assert result.result['pool_quantity'] == '10.000000'
    assert result.result['pool_value_scr'] == '120.000000'
    assert result.result['average_cost_scr'] == '12.000000'
    assert result.result['status'] == 'UNRECONCILED'
    assert f.value().replayed
    with f.factory() as db:
        assert db.query(InventoryValuation).filter_by(org_id=f.orgs[0]).count() == 1
        assert db.get(StockBalance, f.balance).version == 1


def test_new_key_cannot_value_same_source_twice(valued):
    f = valued; f.value()
    with pytest.raises(PostingConflict, match='already has'):
        f.value(key=uuid4(), expected_version=1)


def test_multiple_location_openings_share_one_weighted_pool(valued):
    f = valued; f.value()
    with f.factory.begin() as db:
        location = StockLocation(org_id=f.orgs[0], branch_id=f.branches[0], code='SECOND', name='Second', kind='SITE')
        db.add(location); db.flush(); location_id = location.id
    second = f.open(location_id=location_id).result['balance_id']
    result = record_opening_value(f.factory, f.context, f.actor, uuid4(), balance_id=second,
        expected_version=1, goods_value_scr=D('80'), additional_cost_scr=D('0'), reason='Second source', authorize=lambda db: None)
    assert result.result['pool_quantity'] == '20.000000'
    assert result.result['pool_value_scr'] == '200.000000'
    assert result.result['average_cost_scr'] == '10.000000'
    with pytest.raises(PostingConflict): f.value()  # old intent cannot masquerade as current snapshot


def test_changed_intent_and_stale_version_rejected(valued):
    f = valued; f.value()
    with pytest.raises(PostingConflict): f.value(goods_value_scr=D('101'))
    with pytest.raises(PostingConflict): f.value(key=uuid4())


def test_missing_pool_never_guesses_mapping(stock):
    f = stock; balance = f.open().result['balance_id']
    with pytest.raises(ValueError, match='mapping'):
        record_opening_value(f.factory, f.context, f.actor, uuid4(), balance_id=balance,
            expected_version=0, goods_value_scr=D('10'), additional_cost_scr=D('0'), reason='Test', authorize=lambda db: None)


def test_permission_is_checked_on_replay_and_foreign_scope_denied(valued):
    f = valued; f.value()
    def deny(db): raise PermissionError('denied')
    with pytest.raises(PermissionError): f.value(authorize=deny)
    with pytest.raises(ValueError): f.value(authorize=None)
    foreign = OrgContext(current_org_id=f.orgs[1], allowed_org_ids=f.orgs, is_root=True)
    with pytest.raises(LookupError): f.value(context=foreign)


def test_outer_rollback_removes_value_and_receipt(valued):
    f = valued
    with pytest.raises(RuntimeError):
        with f.factory.begin() as db:
            f.value(factory=db)
            raise RuntimeError('downstream failure')
    assert not f.value().replayed


@pytest.mark.parametrize('same_key', [True, False])
def test_concurrent_opening_values_have_one_effect(valued, same_key):
    f = valued; barrier = Barrier(2)
    def run(key):
        barrier.wait(timeout=10)
        try: return f.value(key=key)
        except PostingConflict: return None
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(run, [f.key, f.key if same_key else uuid4()]))
    assert sum(r is None for r in results) == (0 if same_key else 1)
    with f.factory() as db:
        assert db.query(InventoryValuation).filter_by(org_id=f.orgs[0]).count() == 1


@pytest.mark.parametrize('sql', ['UPDATE containermgmt.inventory_valuations SET reason = :reason WHERE id = :id',
                                'DELETE FROM containermgmt.inventory_valuations WHERE id = :id'])
def test_history_is_immutable(valued, sql):
    f = valued; key = f.value().result['valuation_id']
    with f.factory.begin() as db, pytest.raises(DBAPIError):
        db.execute(text(sql), {'id': key, 'reason': 'changed'})


def test_migration_replay_preserves_history(valued, monkeypatch):
    from Utils import migrate_20261003_inventory_valuation as migration
    f = valued; f.value()
    monkeypatch.setattr(migration, 'engine', f.factory.kw['bind'])
    migration.ensure_inventory_valuation_schema(); migration.ensure_inventory_valuation_schema()
    assert f.value().replayed
