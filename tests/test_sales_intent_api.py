from dataclasses import replace
from uuid import uuid4
import pytest
from auth.policy import AccessPolicy
from Schema.SalesIntentSchema import SalesIntentInput
from tests.test_sales_intent_sources import source  # noqa: F401
from tests.test_policy_activation import activation  # noqa: F401
from tests.test_policy_manager_cases import policy_cases  # noqa: F401
from tests.test_inventory_policy_drafts import draft  # noqa: F401
from tests.test_inventory_locations import locations  # noqa: F401


@pytest.fixture
def api(source, monkeypatch):
    monkeypatch.setattr('Services.sales_draft_search_projection.sync_sales_draft_document', lambda document: True)
    from Routes.Orders.SalesIntentRouter import SalesIntentRouter
    f = source; f.app.include_router(SalesIntentRouter)
    f.permissions = {'View_SalesDraft', 'Manage_SalesDraft', 'View_Product', 'View_Customer', 'View_Personal_Data'}
    f.user.access_policy = AccessPolicy(user=f.user, org_ids=(f.org_a,),
        permission_names=frozenset(f.permissions), module_names=frozenset({'SALES'}),
        field_permissions={'PERSONAL': 'View_Personal_Data'})
    f.url = f'/sales/drafts/{uuid4()}'
    f.payload = dict(operation_key=str(uuid4()), expected_version=0,
        draft=SalesIntentInput(**f.data).model_dump(mode='json'))
    return f


def test_save_reopen_revision_and_paginated_register(api):
    f = api; response = f.client.put(f.url, json=f.payload)
    assert response.status_code == 200, response.text
    assert f.client.put(f.url, json=f.payload).json()['replayed']
    read = f.client.get(f.url)
    assert read.status_code == 200 and read.json()['lines'][0]['base_quantity'] == '24.000000'
    assert read.headers['cache-control'] == 'no-store'
    f.payload.update(operation_key=str(uuid4()), expected_version=1)
    f.payload['draft']['lines'][0]['quantity'] = '4'
    assert f.client.put(f.url, json=f.payload).json()['version'] == 2
    page = f.client.get('/sales/drafts?limit=1').json()
    assert page['total'] == 1 and page['items'][0]['version'] == 2
    assert f.client.get('/sales/drafts?page=2&limit=1').json()['items'] == []
    assert f.client.get('/sales/drafts?limit=101').status_code == 422


def test_detail_revision_metadata_and_current_branch_label_are_scoped(api):
    from Model.containermgmt.Inventory.Location import InventoryBranch
    from Services.sales_intent_service import sales_branch_labels
    f = api
    assert f.client.put(f.url, json=f.payload).status_code == 200
    branch_id = f.payload['draft']['branch_id']
    branch = f.db.query(InventoryBranch).filter_by(id=branch_id).one()
    branch.name = 'Renamed synthetic store'
    f.db.commit()
    data = f.client.get(f.url).json()
    assert data['branch_name'] == 'Renamed synthetic store'
    assert data['created_by'] == f.user.id and data['created_at']
    history = f.client.get(f'{f.url}/history/1').json()
    assert history['created_at'] == data['created_at']
    assert history['branch_name'] == 'Renamed synthetic store'
    foreign = f.db.query(InventoryBranch).filter_by(org_id=f.org_b).first()
    assert sales_branch_labels(f.db, f.context, [foreign.id]) == {}
    branch.is_deleted = True
    f.db.commit()
    assert f.client.get(f.url).json()['branch_name'] is None
    assert f.client.get(f.url).json()['branch_id'] == branch_id
    with pytest.raises(ValueError):
        sales_branch_labels(f.db, f.context, range(101))


def test_historical_lines_retain_saved_units_without_current_reservations(api, monkeypatch):
    f = api
    assert f.client.put(f.url, json=f.payload).status_code == 200
    original = f.client.get(f.url).json()
    f.payload.update(operation_key=str(uuid4()), expected_version=1)
    f.payload['draft']['lines'][0]['quantity'] = '4'
    assert f.client.put(f.url, json=f.payload).status_code == 200
    def forbidden(*args):
        raise AssertionError('Historical reads must not query current holds')
    monkeypatch.setattr('Services.sales_intent_service.active_demand_holds', forbidden)
    old = f.client.get(f'{f.url}/history/1')
    assert old.status_code == 200, old.text
    data = old.json()
    assert data['lines'][0]['quantity'] == original['lines'][0]['quantity']
    assert data['lines'][0]['base_quantity'] == '24.000000'
    assert data['lines'][0]['unit'] == original['lines'][0]['unit']
    assert 'reserved_quantity' not in data['lines'][0]
    assert 'expected_customer_version' not in data
    assert data['read_only'] and data['catalogue_labels_current']
    assert old.headers['cache-control'] == 'no-store'
    assert f.client.get(f'{f.url}/history/2').json()['lines'][0]['quantity'] == '4.000000'
    assert f.client.get(f'{f.url}/history/3').status_code == 404
    assert f.client.get(f'{f.url}/history/0').status_code == 422
    assert f.client.put(f'{f.url}/history/1', json=f.payload).status_code == 405


@pytest.mark.parametrize('missing', ['View_SalesDraft', 'Manage_SalesDraft', 'View_Product', 'View_Customer', 'View_Personal_Data'])
def test_permissions_enforced_on_all_requests(api, missing):
    f = api
    assert f.client.put(f.url, json=f.payload).status_code == 200
    f.user.access_policy = replace(f.user.access_policy, permission_names=frozenset(f.permissions - {missing}))
    assert f.client.put(f.url, json=f.payload).status_code == 403
    expected = 200 if missing == 'Manage_SalesDraft' else 403
    assert f.client.get(f.url).status_code == expected
    assert f.client.get('/sales/drafts').status_code == expected
    assert f.client.get(f'{f.url}/history').status_code == expected
    assert f.client.get(f'{f.url}/history/1').status_code == expected


def test_module_and_personal_field_guards(api):
    f = api; policy = f.user.access_policy
    for changes in [dict(module_names=frozenset()), dict(field_permissions={})]:
        f.user.access_policy = replace(policy, **changes)
        assert f.client.put(f.url, json=f.payload).status_code == 403
        assert f.client.get('/sales/drafts').status_code == 403
        assert f.client.get(f'{f.url}/history').status_code == 403
        assert f.client.get(f'{f.url}/history/1').status_code == 403


def test_anonymous_denied(api):
    from auth.policy import get_request_policy
    f = api
    for dep in f.user_dependencies: f.app.dependency_overrides.pop(dep)
    f.app.dependency_overrides.pop(get_request_policy, None)
    assert f.client.get('/sales/drafts').status_code == 401
    assert f.client.get(f.url).status_code == 401
    assert f.client.get(f'{f.url}/history').status_code == 401
    assert f.client.get(f'{f.url}/history/1').status_code == 401
    assert f.client.put(f.url, json=f.payload).status_code == 401


def test_foreign_company_denied_including_replay(api):
    f = api; assert f.client.put(f.url, json=f.payload).status_code == 200
    f.context.current_org_id = f.org_b; f.context.allowed_org_ids = [f.org_a, f.org_b]; f.context.is_root = True
    assert f.client.get(f.url).status_code == 404
    assert f.client.get(f'{f.url}/history').status_code == 404
    assert f.client.get(f'{f.url}/history/1').status_code == 404
    assert f.client.get('/sales/drafts').json()['items'] == []
    assert f.client.put(f.url, json=f.payload).status_code == 404


def test_stale_version_and_unsafe_extra_fields(api):
    f = api; assert f.client.put(f.url, json=f.payload).status_code == 200
    f.payload['operation_key'] = str(uuid4())
    assert f.client.put(f.url, json=f.payload).status_code == 409
    f.payload['draft']['payment_received'] = True
    assert f.client.put(f.url, json=f.payload).status_code == 422


def test_history_is_paginated_immutable_revision_metadata(api):
    f = api
    assert f.client.get(f'{f.url}/history').status_code == 404
    assert f.client.put(f.url, json=f.payload).status_code == 200
    f.payload.update(operation_key=str(uuid4()), expected_version=1)
    f.payload['draft']['lines'][0]['quantity'] = '4'
    assert f.client.put(f.url, json=f.payload).status_code == 200
    response = f.client.get(f'{f.url}/history?limit=1')
    assert response.status_code == 200, response.text
    assert response.headers['cache-control'] == 'no-store'
    data = response.json()
    assert data['total'] == 2 and data['pages'] == 2
    row = data['items'][0]
    assert row['version'] == 2 and row['created_by'] == f.user.id
    assert row['customer_version'] == f.payload['draft']['expected_customer_version']
    assert row['created_at'] and row['status'] == 'DRAFT'
    assert 'operation_key' not in row and 'payments' not in row and 'contacts' not in row
    assert f.client.get(f'{f.url}/history?limit=1&page=2').json()['items'][0]['version'] == 1
    assert f.client.get(f'{f.url}/history?limit=1&page=3').json()['items'] == []
    assert f.client.get(f'{f.url}/history?limit=101').status_code == 422
    assert f.client.get(f'{f.url}/history?page=0').status_code == 422


def test_store_filter_is_scoped_and_applied_before_pagination(api):
    f = api
    assert f.client.put(f.url, json=f.payload).status_code == 200
    branch = f.payload['draft']['branch_id']
    matching = f.client.get('/sales/drafts', params={'branch_id': branch, 'limit': 1})
    assert matching.status_code == 200
    assert matching.json()['total'] == 1
    assert matching.json()['items'][0]['branch_id'] == branch
    assert 'branch_name' in matching.json()['items'][0]
    assert f.client.get('/sales/drafts', params={'branch_id': branch, 'page': 2, 'limit': 1}).json()['items'] == []
    assert f.client.get('/sales/drafts?branch_id=0').status_code == 422
    f.context.current_org_id = f.org_b
    f.context.allowed_org_ids = [f.org_a, f.org_b]
    f.context.is_root = True
    foreign = f.client.get('/sales/drafts', params={'branch_id': branch}).json()
    assert foreign['items'] == [] and foreign['total'] == 0


def test_customer_name_uses_saved_profile_not_latest(api):
    from tests.test_customer_identity import profile
    from Schema.CustomerSchema import CustomerProfileUpdate
    from Services.customer_profile_service import update_customer_profile, historical_names_for_page
    f = api
    assert f.client.put(f.url, json=f.payload).status_code == 200
    original_name = profile().name
    changed = profile().model_copy(update={'name': 'Synthetic revised name'})
    f.db.connection()  # This service deliberately requires a caller-owned transaction.
    update_customer_profile(f.db, f.context, f.user.id, f.customer_key,
        CustomerProfileUpdate(operation_key=uuid4(), expected_version=1,
            profile=changed, reason='Synthetic name correction'), authorize=lambda db: None)
    f.db.commit()
    assert f.client.get(f.url).json()['customer_name'] == original_name
    assert f.client.get('/sales/drafts').json()['items'][0]['customer_name'] == original_name
    names = historical_names_for_page(f.db, f.context,
        [(f.customer_key, 1), (f.customer_key, 2), (f.customer_key, 99)], authorize=lambda db: None)
    assert names[(f.customer_key, 1)] == original_name
    assert names[(f.customer_key, 2)] == 'Synthetic revised name'
    assert (f.customer_key, 99) not in names
