from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from Schema.CostAllocationSchema import CostAllocationSave
from Model.containermgmt.Inventory.CostAllocation import CostAllocationProposal
from Services.cost_allocation_proposal_service import save_allocation_proposal
from Services.inventory_posting_service import PostingConflict
from tests.test_inventory_valuation import valued  # noqa: F401
from tests.test_stock_ledger import stock  # noqa: F401


@pytest.fixture
def allocation(valued):
    from Routes.Inventory.CostPoolRouter import preview_cost_allocation
    f = valued; source = f.value().result['valuation_id']
    f.payload = CostAllocationSave(operation_key=uuid4(), valuation_ids=[source], total_scr='12.34',
        basis='GOODS_VALUE', charge_reference='SYNTHETIC-INVOICE', reason='Synthetic freight allocation')
    def save(payload=None, factory=None, authorize=lambda db: None):
        p = payload or f.payload
        return save_allocation_proposal(factory or f.factory, f.context, f.actor, f.pool, p,
            authorize=authorize, load_snapshot=lambda db: preview_cost_allocation(f.pool, p, db=db, context=f.context, user=object()))
    f.save_proposal = save
    return f


def test_save_replay_and_historical_read_without_posting(allocation):
    from Routes.Inventory.CostPoolRouter import list_cost_allocations, read_cost_allocation, save_cost_allocation
    from types import SimpleNamespace
    f = allocation
    with f.factory() as db:
        assert not save_cost_allocation(f.pool, f.payload, db=db, context=f.context, user=SimpleNamespace(id=f.actor)).replayed
    assert f.save_proposal().replayed
    with f.factory() as db:
        page = list_cost_allocations(f.pool, page=1, limit=1, db=db, context=f.context, user=object())
        assert page['total'] == 1 and page['items'][0]['total_scr'] == '12.340000'
        row = read_cost_allocation(f.pool, f.payload.operation_key, db=db, context=f.context, user=object())
        assert row['snapshot']['posting_enabled'] is False
        assert row['snapshot']['lines'][0]['allocated_scr'] == '12.340000'


def test_changed_intent_and_denied_retry(allocation):
    f = allocation; f.save_proposal()
    with pytest.raises(PostingConflict): f.save_proposal(f.payload.model_copy(update={'charge_reference': 'DIFFERENT'}))
    def deny(db): raise PermissionError('denied')
    with pytest.raises(PermissionError): f.save_proposal(authorize=deny)
    with pytest.raises(ValueError): f.save_proposal(authorize=None)


def test_failed_outer_transaction_does_not_leave_proposal(allocation):
    f = allocation
    with pytest.raises(RuntimeError):
        with f.factory.begin() as db:
            f.save_proposal(factory=db)
            raise RuntimeError('Synthetic failure')
    assert not f.save_proposal().replayed


def test_concurrent_retry_creates_one_proposal(allocation):
    f = allocation; barrier = Barrier(2)
    def save(_):
        barrier.wait(timeout=10); return f.save_proposal()
    with ThreadPoolExecutor(max_workers=2) as executor: outcomes = list(executor.map(save, range(2)))
    assert sorted(row.replayed for row in outcomes) == [False, True]
    with f.factory() as db: assert db.query(CostAllocationProposal).filter_by(org_id=f.orgs[0]).count() == 1


@pytest.mark.parametrize('operation', ['UPDATE containermgmt.inventory_cost_allocation_proposals SET snapshot = snapshot',
                                        'DELETE FROM containermgmt.inventory_cost_allocation_proposals'])
def test_database_blocks_history_changes(allocation, operation):
    f = allocation; f.save_proposal()
    with f.factory.begin() as db, pytest.raises(DBAPIError):
        db.execute(text(operation + ' WHERE proposal_key = :key'), {'key': f.payload.operation_key})


def test_migration_replay_and_foreign_read(allocation, monkeypatch):
    from Utils import migrate_20261003_cost_allocation as migration
    from Routes.Inventory.CostPoolRouter import read_cost_allocation
    from Utils.org_filter import OrgContext
    from fastapi import HTTPException
    f = allocation; f.save_proposal()
    monkeypatch.setattr(migration, 'engine', f.factory.kw['bind'])
    migration.ensure_cost_allocation_schema(); migration.ensure_cost_allocation_schema()
    foreign = OrgContext(current_org_id=f.orgs[1], allowed_org_ids=f.orgs, is_root=True)
    with f.factory() as db, pytest.raises(HTTPException) as error:
        read_cost_allocation(f.pool, f.payload.operation_key, db=db, context=foreign, user=object())
    assert error.value.status_code == 404
