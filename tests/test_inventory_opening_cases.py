"""Reviewed opening/import composition over the authoritative ledgers."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from decimal import Decimal
from threading import Barrier
from uuid import uuid4

import pytest

from Model.containermgmt.Inventory.CostPool import BranchCostPool, InventoryCostPool
from Model.containermgmt.Inventory.ManagerCase import ManagerCaseUse
from Model.containermgmt.Inventory.PostingAuthority import CostPoolAuthorityEpoch
from Model.containermgmt.Inventory.PostingOperation import PostingOperation
from Model.containermgmt.Inventory.StockLedger import StockBalance, StockMovement
from Model.containermgmt.Inventory.Valuation import InventoryValuation
from Schema.InventoryOpeningSchema import InventoryOpeningInput
from Services.inventory_opening_case_service import (
    execute_reviewed_opening, opening_binding, opening_value_operation)
from Services.inventory_posting_service import PostingConflict
from Services.manager_case_service import request_case, review_case
from Services.posting_authority_service import CostPoolAuthorityClaim
from Utils.org_filter import OrgContext
from tests.test_policy_activation_concurrency import reviewed  # noqa: F401
from tests.test_stock_ledger import stock  # noqa: F401


@pytest.fixture
def opening(reviewed):
    f = reviewed
    f.activate()
    with f.factory.begin() as db:
        pool = InventoryCostPool(org_id=f.orgs[0], code='OPENING',
            name='Synthetic opening pool', created_by=f.actor)
        db.add(pool)
        db.flush()
        f.pool = pool.id
        db.add(BranchCostPool(org_id=f.orgs[0],
            branch_id=f.branches[0], cost_pool_id=pool.id,
            created_by=f.actor))
        db.add(CostPoolAuthorityEpoch(org_id=f.orgs[0],
            cost_pool_id=pool.id, node_id=f.node_id, epoch=1,
            state='ACTIVE', reason='Synthetic opening authority',
            created_by=f.actor))
    f.cost_claim = CostPoolAuthorityClaim(
        f.orgs[0], f.pool, f.node_key, 1)
    f.intent = InventoryOpeningInput(source_key=uuid4(),
        branch_id=f.branches[0], location_id=f.locations[0],
        product_id=f.products[0], expected_policy_version=1,
        expected_valuation_version=0, on_hand='10', damaged='1',
        quarantined='1', goods_value_scr='100',
        additional_cost_scr='20', reason='Synthetic reviewed opening')
    with f.factory.begin() as db:
        f.opening_binding = opening_binding(db, f.context, f.intent)
    f.opening_case = uuid4()
    request_case(f.factory, f.context, f.actor, f.opening_case,
        binding=f.opening_binding, reason=f.intent.reason,
        load_binding=lambda db: opening_binding(db, f.context, f.intent),
        authorize=lambda db: None)
    review_case(f.factory, f.context, f.reviewer, uuid4(),
        case_key=f.opening_case, binding=f.opening_binding,
        expected_version=1, outcome='APPROVED',
        reason='Synthetic independent review',
        load_binding=lambda db: opening_binding(db, f.context, f.intent),
        authorize=lambda db: None)
    f.opening_operation = uuid4()

    def execute(**kwargs):
        factory = kwargs.pop('factory', f.factory)
        context = kwargs.pop('context', f.context)
        arguments = dict(case_key=kwargs.pop('case_key', f.opening_case),
            binding=kwargs.pop('binding', f.opening_binding),
            stock_authority=kwargs.pop('stock_authority', f.claim),
            cost_authority=kwargs.pop('cost_authority', f.cost_claim),
            authorize_stock=kwargs.pop('authorize_stock', lambda db: None),
            authorize_cost=kwargs.pop('authorize_cost', lambda db: None),
            **kwargs)
        operation_key = arguments.pop('operation_key', f.opening_operation)
        if hasattr(factory, 'in_transaction'):
            return execute_reviewed_opening(factory, context, f.actor,
                operation_key, **arguments)
        with factory.begin() as db:
            return execute_reviewed_opening(db, context, f.actor,
                operation_key, **arguments)

    f.execute_opening = execute
    return f


def test_reviewed_opening_commits_stock_value_and_case_once(opening):
    f = opening
    first = f.execute_opening()
    replay = f.execute_opening()
    assert not first.replayed
    assert replay.replayed
    assert replay.result == first.result
    assert first.result == {
        'status': 'POSTED_UNRECONCILED',
        'balance_id': first.result['balance_id'],
        'balance_version': 1,
        'valuation_id': first.result['valuation_id'],
        'valuation_version': 1,
        'cost_pool_id': f.pool,
        'product_id': f.products[0],
        'on_hand': '10.000000',
        'available': '8.000000',
        'damaged': '1.000000',
        'quarantined': '1.000000',
        'pool_quantity': '10.000000',
        'pool_value_scr': '120.000000',
        'average_cost_scr': '12.000000',
    }
    with f.factory() as db:
        balance = db.get(StockBalance, first.result['balance_id'])
        movement = db.query(StockMovement).filter_by(
            org_id=f.orgs[0], operation_key=f.opening_operation).one()
        valuation = db.query(InventoryValuation).filter_by(
            org_id=f.orgs[0],
            operation_key=opening_value_operation(f.opening_operation)).one()
        assert balance.on_hand == Decimal('10')
        assert movement.kind == valuation.kind == 'OPENING'
        assert valuation.balance_id == balance.id
        assert db.query(ManagerCaseUse).filter_by(
            org_id=f.orgs[0], operation_key=f.opening_operation).count() == 1
        assert db.query(PostingOperation).filter_by(
            org_id=f.orgs[0]).count() == 7


def test_opening_rollback_restores_approval_and_both_ledgers(opening):
    f = opening
    with pytest.raises(RuntimeError):
        with f.factory.begin() as db:
            f.execute_opening(factory=db)
            raise RuntimeError('Synthetic downstream failure')
    with f.factory() as db:
        assert db.query(StockBalance).filter_by(org_id=f.orgs[0]).count() == 0
        assert db.query(InventoryValuation).filter_by(org_id=f.orgs[0]).count() == 0
        assert db.query(ManagerCaseUse).filter_by(org_id=f.orgs[0]).count() == 1
        # The only retained use is the earlier policy-activation approval.
    assert not f.execute_opening().replayed


def test_opening_rejects_changed_intent_and_reused_case(opening):
    f = opening
    f.execute_opening()
    with pytest.raises(PostingConflict):
        f.execute_opening(operation_key=uuid4())
    changed = replace(f.opening_binding,
        details={**f.opening_binding.details, 'goods_value_scr': '101.000000'})
    with pytest.raises((PostingConflict, ValueError, PermissionError)):
        f.execute_opening(binding=changed)


def test_opening_rechecks_permissions_and_authorities_on_replay(opening):
    f = opening
    f.execute_opening()

    def deny(db):
        raise PermissionError('Synthetic denial')

    with pytest.raises(PermissionError, match='Synthetic denial'):
        f.execute_opening(authorize_stock=deny)
    with pytest.raises((PermissionError, ValueError)):
        f.execute_opening(stock_authority=None)
    with pytest.raises(PermissionError):
        f.execute_opening(cost_authority=replace(f.cost_claim,
            cost_pool_id=f.pool + 1))


def test_foreign_company_cannot_request_or_execute_opening(opening):
    f = opening
    foreign = OrgContext(current_org_id=f.orgs[1],
        allowed_org_ids=f.orgs, is_root=True)
    with f.factory.begin() as db, pytest.raises(
            (LookupError, PermissionError, PostingConflict, ValueError)):
        opening_binding(db, foreign, f.intent)
    with pytest.raises((LookupError, PermissionError, PostingConflict, ValueError)):
        f.execute_opening(context=foreign)


def test_concurrent_opening_execution_has_one_business_effect(opening):
    f = opening
    barrier = Barrier(2, timeout=10)

    def run(_):
        barrier.wait()
        return f.execute_opening()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(run, range(2)))
    assert sorted(result.replayed for result in results) == [False, True]
    with f.factory() as db:
        assert db.query(StockMovement).filter_by(
            org_id=f.orgs[0], kind='OPENING').count() == 1
        assert db.query(InventoryValuation).filter_by(
            org_id=f.orgs[0], kind='OPENING').count() == 1


@pytest.mark.parametrize('change, message', [
    ({'damaged': '11'}, 'unavailable'),
    ({'batch': {'batch_key': str(uuid4()), 'code': 'B1'}}, 'Untracked'),
])
def test_opening_intent_validates_condition_and_tracking_contract(
        opening, change, message):
    f = opening
    intent = f.intent.model_copy(update=change)
    with f.factory.begin() as db, pytest.raises(ValueError, match=message):
        opening_binding(db, f.context, intent)
