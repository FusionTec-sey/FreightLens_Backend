from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from Model.containermgmt.Inventory.CostReconciliation import InventoryCostReconciliation
from Model.containermgmt.Inventory.ManagerCase import ManagerCaseUse
from Model.containermgmt.Inventory.Location import StockLocation
from Model.Credentials.users import User
from Services.cost_reconciliation_checkpoint_service import (
    close_reconciliation, reconciliation_binding)
from Services.inventory_posting_service import PostingConflict
from Services.inventory_valuation_service import record_opening_value
from Services.manager_case_service import request_case, review_case
from tests.test_inventory_valuation import valued  # noqa: F401
from tests.test_stock_ledger import stock  # noqa: F401


def approved_case(f):
    with f.factory.begin() as db:
        binding = reconciliation_binding(db, f.context, f.pool, f.products[0])
        case_key = uuid4()
        request_case(db, f.context, f.actor, case_key, binding=binding,
            reason="Synthetic reconciliation request",
            load_binding=lambda session: reconciliation_binding(
                session, f.context, f.pool, f.products[0]),
            authorize=lambda session: None)
    with f.factory.begin() as db:
        review_case(db, f.context, f.reviewer, uuid4(), case_key=case_key,
            binding=binding, expected_version=1, outcome="APPROVED",
            reason="Synthetic independent reconciliation review",
            load_binding=lambda session: reconciliation_binding(
                session, f.context, f.pool, f.products[0]),
            authorize=lambda session: None)
    return case_key, binding


@pytest.fixture
def closable(valued):
    f = valued
    f.value()
    with f.factory.begin() as db:
        reviewer = User(username="recon-" + uuid4().hex,
            password_hash="test-only-unusable", org_id=f.orgs[0])
        db.add(reviewer); db.flush(); f.reviewer = reviewer.id
    f.case_key, f.reconciliation = approved_case(f)
    return f


def close(f, **changes):
    return close_reconciliation(changes.pop("db", f.factory), f.context,
        changes.pop("actor", f.reviewer), changes.pop("operation_key", uuid4()),
        case_key=changes.pop("case_key", f.case_key),
        binding=changes.pop("binding", f.reconciliation),
        authority_claim=changes.pop("authority", f.central_claim),
        authorize=changes.pop("authorize", lambda session: None), **changes)


def test_approved_exact_state_closes_once_without_rewriting_valuation(closable):
    f = closable; operation_key = uuid4()
    result = close(f, operation_key=operation_key)
    assert result.result == {
        "checkpoint_key": str(operation_key), "cost_pool_id": f.pool,
        "product_id": f.products[0], "valuation_id": f.value().result["valuation_id"],
        "valuation_version": 1, "pool_quantity": "10.000000",
        "pool_value_scr": "120.000000", "status": "CLOSED"}
    assert close(f, operation_key=operation_key).replayed is True
    with f.factory() as db:
        row = db.query(InventoryCostReconciliation).filter_by(
            checkpoint_key=operation_key, org_id=f.orgs[0]).one()
        assert row.line_count == 1 and row.status == "CLOSED"
        assert db.query(ManagerCaseUse).filter_by(
            operation_key=operation_key, org_id=f.orgs[0]).count() == 1


def test_changed_physical_or_valuation_state_invalidates_approval(closable):
    f = closable
    with f.factory.begin() as db:
        location = StockLocation(org_id=f.orgs[0], branch_id=f.branches[0],
            code="RECON-2", name="Reconciliation second", kind="SITE")
        db.add(location); db.flush(); location_id = location.id
    second = f.open(location_id=location_id, key=uuid4()).result["balance_id"]
    record_opening_value(f.factory, f.context, f.actor, uuid4(), balance_id=second,
        expected_version=1, goods_value_scr=Decimal("50"),
        additional_cost_scr=Decimal("0"), reason="Second opening",
        authority_claim=f.central_claim, authorize=lambda session: None)
    with pytest.raises(PostingConflict, match="changed"):
        close(f)


def test_same_state_cannot_be_closed_by_a_second_case(closable):
    f = closable; close(f)
    second_case, second_binding = approved_case(f)
    with pytest.raises(PostingConflict, match="already reconciled"):
        close(f, case_key=second_case, binding=second_binding)


def test_permission_authority_scope_and_immutability_fail_closed(closable):
    f = closable
    with pytest.raises(PermissionError): close(f, authorize=lambda session: (_ for _ in ()).throw(PermissionError("denied")))
    with pytest.raises(PermissionError): close(f, authority=None)
    checkpoint = close(f).result["checkpoint_key"]
    with f.factory.begin() as db, pytest.raises(DBAPIError):
        db.execute(text("UPDATE containermgmt.inventory_cost_reconciliations SET status='OPEN' WHERE checkpoint_key=:key"), {"key": checkpoint})


def test_migration_replay_preserves_checkpoints(closable, monkeypatch):
    f = closable; operation_key = close(f).operation_key
    from Utils import migrate_20261004_cost_reconciliations as migration
    monkeypatch.setattr(migration, "engine", f.factory.kw["bind"])
    migration.ensure_cost_reconciliations_schema(); migration.ensure_cost_reconciliations_schema()
    with f.factory() as db:
        assert db.query(InventoryCostReconciliation).filter_by(
            org_id=f.orgs[0], checkpoint_key=operation_key).count() == 1
