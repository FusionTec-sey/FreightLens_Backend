from uuid import uuid4
import pytest
from auth.policy import AccessPolicy
from tests.test_inventory_locations import locations  # noqa: F401


@pytest.fixture
def customers(locations, monkeypatch):
    monkeypatch.setattr('Routes.MasterData.CustomerRouter.sync_customer_document', lambda *args: True)
    from Routes.MasterData.CustomerRouter import CustomerRouter
    f = locations
    f.app.include_router(CustomerRouter)
    f.permissions = {'View_Customer', 'Manage_Customer', 'View_Personal_Data'}
    f.user.access_policy = AccessPolicy(user=f.user, org_ids=(f.org_a,),
        permission_names=frozenset(f.permissions), module_names=frozenset(), field_permissions={'PERSONAL': 'View_Personal_Data'})
    f.payload = dict(operation_key=str(uuid4()), expected_version=0, profile=dict(
        name='Synthetic API customer', kind='PERSON', contacts=[dict(kind='PHONE', value='+248 2000000', primary=True)]))
    return f


def test_create_read_paginate_and_retry(customers):
    f = customers
    result = f.client.post('/master-data/customers', json=f.payload)
    assert result.status_code == 200, result.text
    key = result.json()['customer_key']
    assert not result.json()['replayed']
    assert f.client.post('/master-data/customers', json=f.payload).json()['replayed']
    assert f.client.get(f'/master-data/customers/{key}').json()['name'] == 'Synthetic API customer'
    page = f.client.get('/master-data/customers?limit=1').json()
    assert page['total'] == 1 and page['items'][0]['customer_key'] == key
    assert f.client.get('/master-data/customers?page=2&limit=1').json()['items'] == []
    assert f.client.get('/master-data/customers?limit=101').status_code == 422
    f.payload['profile']['name'] = 'Changed'
    assert f.client.post('/master-data/customers', json=f.payload).status_code == 409


@pytest.mark.parametrize('missing', ['View_Customer', 'View_Personal_Data', 'Manage_Customer'])
def test_explicit_permission_denials(customers, missing):
    f = customers
    f.user.access_policy = AccessPolicy(user=f.user, org_ids=(f.org_a,),
        permission_names=frozenset(f.permissions - {missing}), module_names=frozenset(), field_permissions={'PERSONAL': 'View_Personal_Data'})
    assert f.client.post('/master-data/customers', json=f.payload).status_code == 403
    assert f.client.get('/master-data/customers').status_code == (200 if missing == 'Manage_Customer' else 403)


def test_anonymous_denied(customers):
    f = customers
    for dep in f.user_dependencies: f.app.dependency_overrides.pop(dep)
    from auth.policy import get_request_policy
    f.app.dependency_overrides.pop(get_request_policy, None)
    assert f.client.get('/master-data/customers').status_code == 401
    assert f.client.post('/master-data/customers/search', json={'search': 'Demo'}).status_code == 401
    assert f.client.post('/master-data/customers', json=f.payload).status_code == 401


def test_missing_personal_field_mapping_fails_closed(customers):
    f = customers
    from dataclasses import replace
    f.user.access_policy = replace(f.user.access_policy, field_permissions={})
    assert f.client.get('/master-data/customers').status_code == 403
    assert f.client.post('/master-data/customers', json=f.payload).status_code == 403


def test_root_allowed_companies_do_not_widen_reads_or_retry(customers):
    f = customers
    key = f.client.post('/master-data/customers', json=f.payload).json()['customer_key']
    f.context.current_org_id = f.org_b
    f.context.allowed_org_ids = [f.org_a, f.org_b]
    f.context.is_root = True
    assert f.client.get('/master-data/customers').json()['items'] == []
    assert f.client.get(f'/master-data/customers/{key}').status_code == 404


def test_unexpected_financial_fields_and_version_denied(customers):
    f = customers
    f.payload['profile']['credit_limit'] = '20000'
    assert f.client.post('/master-data/customers', json=f.payload).status_code == 422
    del f.payload['profile']['credit_limit']
    f.payload['expected_version'] = 1
    assert f.client.post('/master-data/customers', json=f.payload).status_code == 422


def test_search_rehydrates_owned_rows_and_never_index_profile(customers, monkeypatch):
    from uuid import UUID
    f = customers
    key = UUID(f.client.post('/master-data/customers', json=f.payload).json()['customer_key'])
    seen = []
    def search(term, org, page, limit):
        seen.append((term, org, page, limit))
        return [key], 1
    monkeypatch.setattr('Routes.MasterData.CustomerRouter.search_customers', search)
    response = f.client.post('/master-data/customers/search', json={'search': 'Demo', 'limit': 10})
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store'
    assert response.json()['items'][0]['name'] == 'Synthetic API customer'
    assert seen == [('Demo', f.org_a, 1, 10)]
    f.context.current_org_id = f.org_b
    f.context.allowed_org_ids = [f.org_a, f.org_b]
    f.context.is_root = True
    assert f.client.post('/master-data/customers/search', json={'search': 'Demo'}).status_code == 503


def test_search_failure_is_not_empty_success(customers, monkeypatch):
    from Services.search_service import CustomerSearchUnavailable
    def unavailable(*args): raise CustomerSearchUnavailable('Search unavailable')
    monkeypatch.setattr('Routes.MasterData.CustomerRouter.search_customers', unavailable)
    assert customers.client.post('/master-data/customers/search', json={'search': 'Demo'}).status_code == 503
    assert customers.client.get('/master-data/customers').status_code == 200


def test_search_denied_before_provider_call(customers, monkeypatch):
    from dataclasses import replace
    from unittest.mock import Mock
    provider = Mock()
    monkeypatch.setattr('Routes.MasterData.CustomerRouter.search_customers', provider)
    customers.user.access_policy = replace(customers.user.access_policy, permission_names=frozenset())
    assert customers.client.post('/master-data/customers/search', json={'search': 'Private'}).status_code == 403
    provider.assert_not_called()


def test_search_rejects_url_queries_and_invalid_body(customers):
    assert customers.client.get('/master-data/customers?search=Demo').status_code == 422
    for body in [{'search': ' '}, {'search': 'x', 'limit': 101}, {'search': 'x', 'org_id': 999}, {'search': 'x', 'page': '1'}]:
        assert customers.client.post('/master-data/customers/search', json=body).status_code == 422


def test_index_failure_does_not_undo_customer_and_retry_repairs(customers, monkeypatch):
    f = customers
    monkeypatch.setattr('Routes.MasterData.CustomerRouter.sync_customer_document', lambda *args: False)
    response = f.client.post('/master-data/customers', json=f.payload)
    assert response.status_code == 200
    assert response.json()['search_indexed'] is False
    assert f.client.get('/master-data/customers').json()['total'] == 1
    monkeypatch.setattr('Routes.MasterData.CustomerRouter.sync_customer_document', lambda *args: True)
    replay = f.client.post('/master-data/customers', json=f.payload).json()
    assert replay['replayed'] and replay['search_indexed']
    assert f.client.get('/master-data/customers').json()['total'] == 1


def test_profile_update_exact_history_retry_and_stale_rejection(customers):
    f = customers
    created = f.client.post('/master-data/customers', json=f.payload).json()
    key = created['customer_key']; operation = str(uuid4())
    body = dict(operation_key=operation, expected_version=1,
        profile=dict(name='Updated API customer', kind='BUSINESS', contacts=[
            dict(kind='EMAIL', value='accounts@example.test', label='Accounts', primary=True)]),
        reason='Synthetic verified correction')
    saved = f.client.put(f'/master-data/customers/{key}/profile', json=body)
    assert saved.status_code == 200, saved.text
    assert saved.json()['version'] == 2 and not saved.json()['replayed']
    assert f.client.put(f'/master-data/customers/{key}/profile', json=body).json()['replayed']
    current = f.client.get(f'/master-data/customers/{key}').json()
    original = f.client.get(f'/master-data/customers/{key}?version=1').json()
    assert current['name'] == 'Updated API customer' and current['version'] == 2
    assert original['name'] == 'Synthetic API customer' and original['version'] == 1
    history = f.client.get(f'/master-data/customers/{key}/history?limit=1').json()
    assert history['total'] == 2 and history['items'][0]['version'] == 2
    assert history['items'][0]['reason'] == 'Synthetic verified correction'
    assert f.client.get(f'/master-data/customers/{key}/history?page=2&limit=1').json()['items'][0]['version'] == 1
    stale = {**body, 'operation_key': str(uuid4()), 'profile': {**body['profile'], 'name': 'Stale'}}
    assert f.client.put(f'/master-data/customers/{key}/profile', json=stale).status_code == 409
    assert saved.headers['cache-control'] == 'no-store'


def test_profile_write_permission_is_separate_from_private_read(customers):
    f = customers; key = f.client.post('/master-data/customers', json=f.payload).json()['customer_key']
    f.user.access_policy = AccessPolicy(user=f.user, org_ids=(f.org_a,),
        permission_names=frozenset({'View_Customer', 'View_Personal_Data'}),
        module_names=frozenset(), field_permissions={'PERSONAL': 'View_Personal_Data'})
    body = dict(operation_key=str(uuid4()), expected_version=1,
        profile=f.payload['profile'], reason='Denied change')
    assert f.client.get(f'/master-data/customers/{key}/history').status_code == 200
    assert f.client.put(f'/master-data/customers/{key}/profile', json=body).status_code == 403


def test_duplicate_review_routes_assess_only_and_never_merge(customers):
    from Model.Credentials.users import User
    from Model.containermgmt.MasterData.RetailCustomer import RetailCustomer
    f = customers
    permissions = f.permissions | {'Request_CustomerDuplicate', 'Review_CustomerDuplicate'}
    f.user.access_policy = AccessPolicy(user=f.user, org_ids=(f.org_a,),
        permission_names=frozenset(permissions), module_names=frozenset(),
        field_permissions={'PERSONAL': 'View_Personal_Data'})
    first = f.client.post('/master-data/customers', json=f.payload).json()
    second_payload = {**f.payload, 'operation_key': str(uuid4()),
        'profile': {**f.payload['profile'], 'name': 'Possible duplicate'}}
    second = f.client.post('/master-data/customers', json=second_payload).json()
    case_key = str(uuid4())
    request = dict(operation_key=case_key, customer_key=first['customer_key'],
        other_customer_key=second['customer_key'], expected_customer_version=1,
        expected_other_version=1, assessment='SAME_CUSTOMER',
        reason='Synthetic possible duplicate')
    response = f.client.post('/master-data/customers/duplicates/cases', json=request)
    assert response.status_code == 200, response.text
    cases = f.client.get('/master-data/customers/duplicates/cases').json()
    assert cases['items'][0]['merge_authorized'] is False
    assert cases['items'][0]['customers'][0]['version'] == 1
    self_review = f.client.post(
        f'/master-data/customers/duplicates/cases/{case_key}/review',
        json=dict(operation_key=str(uuid4()), expected_version=1,
            outcome='APPROVED', reason='Self review'))
    assert self_review.status_code == 403
    reviewer = User(org_id=f.org_a, username='api-review-' + uuid4().hex[:20],
        password_hash='unusable-test-only')
    f.db.add(reviewer); f.db.commit()
    original_id = f.user.id; f.user.id = reviewer.id
    try:
        approved = f.client.post(
            f'/master-data/customers/duplicates/cases/{case_key}/review',
            json=dict(operation_key=str(uuid4()), expected_version=1,
                outcome='APPROVED', reason='Profiles reviewed'))
        assert approved.status_code == 200, approved.text
        assert approved.json()['status'] == 'APPROVED'
    finally:
        f.user.id = original_id
    assert f.db.query(RetailCustomer).filter_by(org_id=f.org_a).count() == 2


@pytest.mark.parametrize('permission', ['Request_CustomerDuplicate', 'Review_CustomerDuplicate'])
def test_duplicate_actions_require_their_specific_permission(customers, permission):
    f = customers
    f.user.access_policy = AccessPolicy(user=f.user, org_ids=(f.org_a,),
        permission_names=frozenset(f.permissions | ({permission} if permission == 'Request_CustomerDuplicate' else set())),
        module_names=frozenset(), field_permissions={'PERSONAL': 'View_Personal_Data'})
    if permission == 'Request_CustomerDuplicate':
        response = f.client.post('/master-data/customers/duplicates/cases/' + str(uuid4()) + '/review',
            json=dict(operation_key=str(uuid4()), expected_version=1,
                outcome='APPROVED', reason='Denied'))
    else:
        response = f.client.post('/master-data/customers/duplicates/cases', json=dict(
            operation_key=str(uuid4()), customer_key=str(uuid4()),
            other_customer_key=str(uuid4()), expected_customer_version=1,
            expected_other_version=1, assessment='DISTINCT_CUSTOMERS', reason='Denied'))
    assert response.status_code == 403
