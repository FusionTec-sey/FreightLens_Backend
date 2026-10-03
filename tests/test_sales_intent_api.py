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
def api(source):
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


@pytest.mark.parametrize('missing', ['View_SalesDraft', 'Manage_SalesDraft', 'View_Product', 'View_Customer', 'View_Personal_Data'])
def test_permissions_enforced_on_all_requests(api, missing):
    f = api
    assert f.client.put(f.url, json=f.payload).status_code == 200
    f.user.access_policy = replace(f.user.access_policy, permission_names=frozenset(f.permissions - {missing}))
    assert f.client.put(f.url, json=f.payload).status_code == 403
    expected = 200 if missing == 'Manage_SalesDraft' else 403
    assert f.client.get(f.url).status_code == expected
    assert f.client.get('/sales/drafts').status_code == expected


def test_module_and_personal_field_guards(api):
    f = api; policy = f.user.access_policy
    for changes in [dict(module_names=frozenset()), dict(field_permissions={})]:
        f.user.access_policy = replace(policy, **changes)
        assert f.client.put(f.url, json=f.payload).status_code == 403
        assert f.client.get('/sales/drafts').status_code == 403


def test_anonymous_denied(api):
    from auth.policy import get_request_policy
    f = api
    for dep in f.user_dependencies: f.app.dependency_overrides.pop(dep)
    f.app.dependency_overrides.pop(get_request_policy, None)
    assert f.client.get('/sales/drafts').status_code == 401
    assert f.client.get(f.url).status_code == 401
    assert f.client.put(f.url, json=f.payload).status_code == 401


def test_foreign_company_denied_including_replay(api):
    f = api; assert f.client.put(f.url, json=f.payload).status_code == 200
    f.context.current_org_id = f.org_b; f.context.allowed_org_ids = [f.org_a, f.org_b]; f.context.is_root = True
    assert f.client.get(f.url).status_code == 404
    assert f.client.get('/sales/drafts').json()['items'] == []
    assert f.client.put(f.url, json=f.payload).status_code == 404


def test_stale_version_and_unsafe_extra_fields(api):
    f = api; assert f.client.put(f.url, json=f.payload).status_code == 200
    f.payload['operation_key'] = str(uuid4())
    assert f.client.put(f.url, json=f.payload).status_code == 409
    f.payload['draft']['payment_received'] = True
    assert f.client.put(f.url, json=f.payload).status_code == 422
