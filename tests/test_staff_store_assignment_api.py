from dataclasses import replace
from uuid import uuid4
import pytest
from fastapi import Depends
from Routes.Inventory.StaffStoreAssignmentRouter import StaffStoreAssignmentRouter
from auth.module_guard import require_module
from tests.test_inventory_locations import locations  # noqa: F401


@pytest.fixture
def staff_api(locations):
    f = locations
    f.app.include_router(StaffStoreAssignmentRouter, dependencies=[Depends(require_module('INVENTORY'))])
    f.user.access_policy = replace(f.user.access_policy,
        permission_names=f.user.access_policy.permission_names | {'View_User', 'Edit_User'})
    f.url = f'/inventory/branches/{f.own}/staff-assignments'
    f.body = dict(operation_key=str(uuid4()), expected_version=0, config=dict(branch_id=f.own, counter_id=None, is_enabled=True))
    return f


def test_paginated_members_and_exact_save_retry(staff_api):
    f = staff_api
    response = f.client.get(f.url+'?limit=1')
    assert response.status_code == 200, response.text
    data = response.json(); assert data['total'] == 1 and data['items'][0]['version'] == 0
    assert set(data['items'][0]) == {'user_id', 'username', 'version', 'config', 'branch_name'}
    saved = f.client.put(f'{f.url}/{f.user.id}', json=f.body)
    assert saved.status_code == 200, saved.text
    assert saved.json()['version'] == 1
    assert f.client.put(f'{f.url}/{f.user.id}', json=f.body).json() == saved.json()
    assert f.client.get(f.url).json()['items'][0]['config']['branch_id'] == f.own
    assert f.client.get(f.url+'?limit=101').status_code == 422


@pytest.mark.parametrize('method', ['get', 'put'])
@pytest.mark.parametrize('denial', ['anonymous', 'permission', 'module', 'foreign'])
def test_assignment_access_boundaries(staff_api, method, denial):
    f = staff_api
    if denial == 'anonymous':
        for dependency in f.user_dependencies: f.app.dependency_overrides.pop(dependency)
    elif denial == 'foreign': f.context.current_org_id = f.org_b
    else: f.user.access_policy = replace(f.user.access_policy,
        **({'permission_names':frozenset()} if denial == 'permission' else {'module_names':frozenset()}))
    response = f.client.get(f.url) if method == 'get' else f.client.put(f'{f.url}/{f.user.id}', json=f.body)
    assert response.status_code in ([401] if denial == 'anonymous' else [403,404] if denial == 'foreign' else [403]), response.text


def test_settings_permission_alone_cannot_assign_staff(staff_api):
    f = staff_api
    f.user.access_policy = replace(f.user.access_policy, permission_names=f.user.access_policy.permission_names - {'Edit_User'})
    assert f.client.get(f.url).status_code == 200
    assert f.client.put(f'{f.url}/{f.user.id}', json=f.body).status_code == 403
