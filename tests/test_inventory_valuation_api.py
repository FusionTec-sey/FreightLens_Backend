import pytest
from auth.policy import AccessPolicy
from Model.containermgmt.Inventory.CostPool import InventoryCostPool
from tests.test_inventory_locations import locations  # noqa: F401
from tests.test_inventory_valuation import valued  # noqa: F401
from tests.test_stock_ledger import stock  # noqa: F401


def grant(f, permissions=('View_Product', 'View_Financials'), modules=('INVENTORY',)):
    f.user.access_policy = AccessPolicy(user=f.user, org_ids=(f.org_a,),
        permission_names=frozenset(permissions), module_names=frozenset(modules), field_permissions={})


@pytest.mark.parametrize('action', ['save', 'list', 'detail'])
@pytest.mark.parametrize('denial', ['anonymous', 'financial', 'product', 'module'])
def test_proposal_routes_require_access(locations, action, denial):
    from uuid import uuid4
    f = locations
    names = {'View_Product', 'View_Financials', 'Manage_Financials'}
    if denial == 'financial': names.remove('View_Financials')
    if denial == 'product': names.remove('View_Product')
    grant(f, permissions=names, modules=() if denial == 'module' else ('INVENTORY',))
    if denial == 'anonymous':
        for dependency in f.user_dependencies: f.app.dependency_overrides.pop(dependency)
    url = '/inventory/cost-pools/1/allocation-proposals'
    response = f.client.post(url, json={'operation_key': str(uuid4()), 'valuation_ids': [1], 'total_scr': '1',
        'basis': 'GOODS_VALUE', 'charge_reference': 'Test', 'reason': 'Test'}) if action == 'save' else f.client.get(url + ('/' + str(uuid4()) if action == 'detail' else ''))
    assert response.status_code == (401 if denial == 'anonymous' else 403)


def test_view_financials_does_not_grant_saving(locations):
    from uuid import uuid4
    f = locations; grant(f)
    response = f.client.post('/inventory/cost-pools/1/allocation-proposals', json={'operation_key': str(uuid4()),
        'valuation_ids': [1], 'total_scr': '1', 'basis': 'GOODS_VALUE', 'charge_reference': 'Test', 'reason': 'Test'})
    assert response.status_code == 403


@pytest.mark.parametrize('action', ['request-review', 'cases', 'review'])
@pytest.mark.parametrize('denial', ['anonymous', 'financial', 'product', 'module', 'manage'])
def test_cost_review_routes_require_access(locations, action, denial):
    from uuid import uuid4
    f = locations; names = {'View_Product', 'View_Financials', 'Manage_Financials'}
    missing = {'financial': 'View_Financials', 'product': 'View_Product', 'manage': 'Manage_Financials'}
    if denial in missing: names.remove(missing[denial])
    grant(f, permissions=names, modules=() if denial == 'module' else ('INVENTORY',))
    if denial == 'anonymous':
        for dependency in f.user_dependencies: f.app.dependency_overrides.pop(dependency)
    url = '/inventory/cost-pools/1/allocation-proposals/' + str(uuid4())
    payload = {'operation_key': str(uuid4()), 'reason': 'Synthetic review'}
    if action == 'review':
        url += '/cases/' + str(uuid4()) + '/review'; payload.update(expected_version=1, outcome='APPROVED')
    else: url += '/' + action
    response = f.client.get(url) if action == 'cases' else f.client.post(url, json=payload)
    assert response.status_code == (401 if denial == 'anonymous' else 404 if action == 'cases' and denial == 'manage' else 403)


def test_scoped_empty_register_and_pagination(locations):
    f = locations
    pool = InventoryCostPool(org_id=f.org_a, code='VAL', name='Test')
    foreign = InventoryCostPool(org_id=f.org_b, code='VAL', name='Foreign')
    f.db.add_all([pool, foreign]); f.db.commit(); grant(f)
    assert f.client.get(f'/inventory/cost-pools/{pool.id}/valuations').json()['items'] == []
    assert f.client.get(f'/inventory/cost-pools/{pool.id}/valuations?limit=101').status_code == 422
    f.context.allowed_org_ids.append(f.org_b)
    assert f.client.get(f'/inventory/cost-pools/{foreign.id}/valuations').status_code == 404


def test_populated_read_serializes_exact_values_and_source(valued):
    from Routes.Inventory.CostPoolRouter import list_valuations
    from Schema.InventoryLocationSchema import LocationPage
    from Schema.InventoryValuationSchema import InventoryValuationRead
    f = valued; f.value()
    with f.factory() as db:
        response = list_valuations(f.pool, page=1, limit=1, db=db, context=f.context, user=object())
        body = LocationPage[InventoryValuationRead](**response).model_dump(mode='json')
        assert body['total'] == 1 and body['items'][0]['balance_id'] == f.balance
        assert body['items'][0]['pool_value_scr'] == '120.000000'
        assert body['items'][0]['status'] == 'UNRECONCILED'
        assert list_valuations(f.pool, page=2, limit=1, db=db, context=f.context, user=object())['items'] == []


@pytest.mark.parametrize('denial', ['anonymous', 'financial', 'product', 'module'])
@pytest.mark.parametrize('preview', [False, True])
def test_values_require_financial_and_product_access(locations, denial, preview):
    f = locations
    grant(f, permissions=('View_Product',) if denial == 'financial' else ('View_Financials',) if denial == 'product'
          else ('View_Product', 'View_Financials'), modules=() if denial == 'module' else ('INVENTORY',))
    if denial == 'anonymous':
        for dependency in f.user_dependencies: f.app.dependency_overrides.pop(dependency)
    response = f.client.post('/inventory/cost-pools/1/allocate-cost-preview', json={'valuation_ids': [1], 'total_scr': '1', 'basis': 'GOODS_VALUE'}) if preview else f.client.get('/inventory/cost-pools/1/valuations')
    assert response.status_code == (401 if denial == 'anonymous' else 403)


def test_allocation_preview_uses_original_source_and_never_posts(valued):
    from Routes.Inventory.CostPoolRouter import preview_cost_allocation
    from Schema.InventoryValuationSchema import CostAllocationPreviewRequest, CostAllocationPreview
    from Model.containermgmt.Inventory.Valuation import InventoryValuation
    from fastapi import HTTPException
    f = valued; row = f.value().result['valuation_id']
    payload = CostAllocationPreviewRequest(valuation_ids=[row], total_scr='0.000001', basis='GOODS_VALUE')
    with f.factory() as db:
        before = db.query(InventoryValuation).filter_by(org_id=f.orgs[0]).count()
        data = CostAllocationPreview(**preview_cost_allocation(f.pool, payload, db=db, context=f.context, user=object()))
        assert data.lines[0].allocated_scr == '0.000001'
        assert data.lines[0].basis_value == '100.000000'  # not the pool value including freight
        assert data.posting_enabled is False
        assert db.query(InventoryValuation).filter_by(org_id=f.orgs[0]).count() == before
        with pytest.raises(HTTPException) as error:
            preview_cost_allocation(f.pool, payload.model_copy(update={'valuation_ids': [row, 2147483647]}), db=db, context=f.context, user=object())
        assert error.value.status_code == 404


def test_zero_goods_value_requires_a_different_basis(valued):
    from Routes.Inventory.CostPoolRouter import preview_cost_allocation
    from Schema.InventoryValuationSchema import CostAllocationPreviewRequest
    from decimal import Decimal
    from fastapi import HTTPException
    f = valued; row = f.value(goods_value_scr=Decimal('0')).result['valuation_id']
    payload = CostAllocationPreviewRequest(valuation_ids=[row], total_scr='10', basis='GOODS_VALUE')
    with f.factory() as db:
        with pytest.raises(HTTPException) as error:
            preview_cost_allocation(f.pool, payload, db=db, context=f.context, user=object())
        assert error.value.status_code == 422
        result = preview_cost_allocation(f.pool, payload.model_copy(update={'basis': 'BASE_QUANTITY'}), db=db, context=f.context, user=object())
        assert result['lines'][0]['allocated_scr'] == '10.000000'


def test_mixed_units_rejected_but_value_basis_conserves_exact_total(valued):
    from Routes.Inventory.CostPoolRouter import preview_cost_allocation
    from Schema.InventoryValuationSchema import CostAllocationPreviewRequest
    from Model.containermgmt.Orders.Product import Product
    from Schema.InventoryPolicySchema import InventoryPolicyConfig
    from Services.inventory_valuation_service import record_opening_value
    from decimal import Decimal
    from uuid import uuid4
    from fastapi import HTTPException
    f = valued; first = f.value().result['valuation_id']
    with f.factory.begin() as db:
        product = Product(org_id=f.orgs[0], sku='MIXED', name='Mixed unit source', unit='M2')
        db.add(product); db.flush(); product_id = product.id
    balance = f.open(product_id=product_id, base_unit='M2', policy=InventoryPolicyConfig(base_unit='M2', tracking='UNTRACKED', quantity_step='0.01')).result['balance_id']
    second = record_opening_value(f.factory, f.context, f.actor, uuid4(), balance_id=balance, expected_version=0,
        goods_value_scr=Decimal('100'), additional_cost_scr=Decimal('0'), reason='Synthetic mixed unit', authorize=lambda db: None).result['valuation_id']
    payload = CostAllocationPreviewRequest(valuation_ids=[second, first], total_scr='0.000001', basis='BASE_QUANTITY')
    with f.factory() as db:
        with pytest.raises(HTTPException) as error:
            preview_cost_allocation(f.pool, payload, db=db, context=f.context, user=object())
        assert error.value.status_code == 422
        payload = payload.model_copy(update={'basis': 'GOODS_VALUE'})
        one = preview_cost_allocation(f.pool, payload, db=db, context=f.context, user=object())
        two = preview_cost_allocation(f.pool, payload.model_copy(update={'valuation_ids': [first, second]}), db=db, context=f.context, user=object())
        assert one == two
        assert sum(Decimal(line['allocated_scr']) for line in one['lines']) == Decimal('0.000001')


@pytest.mark.parametrize('change', [{'valuation_ids': [1, 1]}, {'valuation_ids': [True]}, {'valuation_ids': list(range(1, 102))},
    {'total_scr': '1.0000001'}, {'total_scr': 'NaN'}, {'total_scr': '-1'}, {'total_scr': 1.1}])
def test_allocation_inputs_are_bounded_and_exact(change):
    from Schema.InventoryValuationSchema import CostAllocationPreviewRequest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        CostAllocationPreviewRequest(**{'valuation_ids': [1], 'total_scr': '1', 'basis': 'GOODS_VALUE', **change})
