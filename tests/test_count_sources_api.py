from dataclasses import replace
import pytest
from tests.test_inventory_locations import locations  # noqa: F401


@pytest.fixture
def counts(locations):
    from Routes.Inventory.CycleCountRouter import CycleCountRouter
    f = locations
    f.app.include_router(CycleCountRouter)
    f.user.access_policy = replace(f.user.access_policy,
        permission_names=frozenset({'Manage_CountPlan'}), module_names=frozenset({'INVENTORY'}))
    return f


def test_inventory_only_planner_can_select_warehouse_without_sales_personal_access(counts):
    f = counts
    response = f.client.get('/inventory/counts/sources/branches?limit=1')
    assert response.status_code == 200, response.text
    assert response.json()['total'] == 1
    assert response.json()['items'][0]['id'] == f.own
    assert f.client.get('/inventory/counts/sources/branches?limit=1&page=2').json()['items'] == []
    assert f.client.get(f'/inventory/counts/sources/branches/{f.foreign}/locations').status_code == 404
    assert f.client.get('/inventory/counts/sources/products').status_code == 200


def test_count_sources_require_permission_and_inventory_module(counts):
    f = counts; original = f.user.access_policy
    for changes in [dict(permission_names=frozenset()), dict(module_names=frozenset())]:
        f.user.access_policy = replace(original, **changes)
        for path in ['branches', 'products', f'branches/{f.own}/locations']:
            assert f.client.get('/inventory/counts/sources/' + path).status_code == 403


def test_count_sources_deny_anonymous(counts):
    from auth.policy import get_request_policy
    f = counts
    for dependency in f.user_dependencies: f.app.dependency_overrides.pop(dependency, None)
    f.app.dependency_overrides.pop(get_request_policy, None)
    assert f.client.get('/inventory/counts/sources/branches').status_code == 401
