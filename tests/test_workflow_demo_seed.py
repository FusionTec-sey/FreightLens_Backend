from types import SimpleNamespace
import pytest
from Model.Credentials.Organisation import Organisation
from Model.containermgmt.Inventory.CycleCount import CountPlan, CountSession, CountDiscrepancy
from Model.containermgmt.Inventory.StockLedger import StockBalance, StockMovement
from Model.containermgmt.Orders.SalesIntent import SalesIntent, SalesIntentRevision
from Model.containermgmt.MasterData.RetailCustomer import RetailCustomer
from Services.count_session_service import blind_sheet
from Utils.org_filter import OrgContext
from Utils.seed_t05_demo import seed_demo
from Utils.seed_workflow_demo import seed_workflows
from tests.test_stock_ledger import stock  # noqa: F401


def test_workflow_examples_are_repeatable_scoped_blind_and_do_not_post_stock(stock):
    with stock.factory() as db:
        org_id, _ = seed_demo(db, [stock.actor])
        before_stock = db.query(StockBalance.id, StockBalance.on_hand, StockBalance.reserved, StockBalance.version).order_by(StockBalance.id).all()
        before_moves = db.query(StockMovement).count()
        result = seed_workflows(db, stock.actor)
        assert result['created']
        assert not seed_workflows(db, stock.actor)['created']
        assert db.query(SalesIntent).filter_by(org_id=org_id).count() == 3
        assert db.query(SalesIntentRevision).filter_by(org_id=org_id).count() == 4
        assert db.query(RetailCustomer).filter_by(org_id=org_id).count() == 2
        assert db.query(CountPlan).filter_by(org_id=org_id).count() == 3
        assert db.query(CountSession).filter_by(org_id=org_id).count() == 2
        assert db.query(CountDiscrepancy).filter_by(org_id=org_id).count() == 2
        assert db.query(StockMovement).count() == before_moves
        assert db.query(StockBalance.id, StockBalance.on_hand, StockBalance.reserved, StockBalance.version).order_by(StockBalance.id).all() == before_stock
        context = OrgContext(current_org_id=org_id, allowed_org_ids=[org_id], selected_org_id=org_id, is_root=False)
        sheet = blind_sheet(db, context, result['open_round'], stock.actor, authorize=lambda session: None)
        assert len(sheet['lines']) == 2
        assert all('expected_base' not in line and 'counted_quantity' not in line for line in sheet['lines'])
        assert db.query(SalesIntent).filter(SalesIntent.org_id.in_(stock.orgs)).count() == 0
        db.rollback()
    with stock.factory() as db:
        assert db.query(CountPlan).filter_by(org_id=org_id).count() == 0
        assert db.query(Organisation).filter_by(id=org_id).count() == 0


@pytest.mark.parametrize('environment,database', [('production', 'isolated_test'), ('test', 'business'), ('test', '')])
def test_workflow_seed_rejects_other_database(environment, database, monkeypatch):
    monkeypatch.setenv('ENVIRONMENT', environment)
    db = SimpleNamespace(bind=SimpleNamespace(url=SimpleNamespace(database=database)))
    with pytest.raises(ValueError, match='local preview or isolated test'):
        seed_workflows(db, 1)
