from types import SimpleNamespace
from dataclasses import replace
from uuid import uuid4
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from Model.db import get_db
from auth.dependencies import get_current_user, get_org_context
from auth.policy import AccessPolicy, get_request_policy
from tests.test_reservation_release_review import release  # noqa: F401
from tests.test_sales_reservation_sources import demand  # noqa: F401
from tests.test_sales_intent_concurrency import ready  # noqa: F401
from tests.test_stock_ledger import stock  # noqa: F401


@pytest.fixture
def api(release):
    from Routes.Inventory.ReservationReleaseCaseRouter import ReservationReleaseCaseRouter
    f = release; f.user = SimpleNamespace(id=f.actor, roles=[])
    f.permissions = {'View_SalesDraft', 'View_Product', 'View_Customer', 'View_Personal_Data',
                     'Request_ReservationRelease', 'Review_ReservationRelease'}
    f.user.access_policy = AccessPolicy(user=f.user, org_ids=(f.orgs[0],),
        permission_names=frozenset(f.permissions), module_names=frozenset({'SALES', 'INVENTORY'}),
        field_permissions={'PERSONAL': 'View_Personal_Data'})
    f.app = FastAPI(); f.app.include_router(ReservationReleaseCaseRouter)
    def db():
        with f.factory() as session: yield session
    f.app.dependency_overrides.update({get_db: db, get_current_user: lambda: f.user,
        get_org_context: lambda: f.context, get_request_policy: lambda: f.user.access_policy})
    f.url = '/inventory/reservation-release-cases'
    f.body = dict(operation_key=str(uuid4()), reservation_key=str(f.reservation),
        expected_source_version=1, expected_released='0', quantity='5', reason='Synthetic request')
    with TestClient(f.app) as client:
        f.client = client; yield f


def test_request_review_queue_and_no_automatic_release(api):
    f = api; result = f.client.post(f.url, json=f.body)
    assert result.status_code == 200, result.text
    key = result.json()['case_key']; assert f.client.post(f.url, json=f.body).json()['replayed']
    review = dict(operation_key=str(uuid4()), expected_version=1, outcome='APPROVED', reason='Synthetic review')
    assert f.client.post(f'{f.url}/{key}/review', json=review).status_code == 403
    f.user.id = f.reviewer
    assert f.client.get(f.url + '?view=NEEDS_MY_REVIEW&limit=1').json()['total'] == 2
    result = f.client.post(f'{f.url}/{key}/review', json=review)
    assert result.status_code == 200, result.text
    assert f.client.post(f'{f.url}/{key}/review', json=review).json()['replayed']
    with f.factory.begin() as db: assert f.load_release(db).details['released_before'] == '0.000000'


@pytest.mark.parametrize('missing', ['Request_ReservationRelease', 'View_SalesDraft', 'View_Personal_Data'])
def test_request_permission_denial(api, missing):
    f = api; f.user.access_policy = replace(f.user.access_policy, permission_names=frozenset(f.permissions - {missing}))
    assert f.client.post(f.url, json=f.body).status_code == 403


def test_foreign_sources_and_stale_versions_denied(api):
    f = api; f.body['expected_source_version'] = 2
    assert f.client.post(f.url, json=f.body).status_code == 409
    f.body['expected_source_version'] = 1; f.context.current_org_id = f.orgs[1]
    assert f.client.post(f.url, json=f.body).status_code == 404
    assert f.client.get(f.url).json()['items'] == []
    assert f.client.post(f'{f.url}/{f.case}/review', json=dict(operation_key=str(uuid4()), expected_version=1, outcome='APPROVED', reason='Synthetic')).status_code == 404


def test_module_and_anonymous_denials(api):
    f = api; policy = f.user.access_policy
    f.user.access_policy = replace(policy, module_names=frozenset({'SALES'}))
    assert f.client.get(f.url).status_code == 403
    f.user.access_policy = policy
    f.app.dependency_overrides.pop(get_current_user); f.app.dependency_overrides.pop(get_request_policy)
    assert f.client.get(f.url).status_code == 401
    assert f.client.post(f.url, json=f.body).status_code == 401


def test_requestor_without_review_right_cannot_see_others_cases(api):
    f = api; f.user.id = f.reviewer
    f.user.access_policy = replace(f.user.access_policy, permission_names=frozenset(f.permissions - {'Review_ReservationRelease'}))
    assert f.client.get(f.url).json()['items'] == []
    assert f.client.post(f'{f.url}/{f.case}/review', json=dict(operation_key=str(uuid4()), expected_version=1, outcome='APPROVED', reason='Synthetic')).status_code == 403


def test_linked_sources_page_and_request_contract(api):
    f = api; url = f'{f.url}/sources/{f.document}'
    result = f.client.get(url + '?limit=1')
    assert result.status_code == 200, result.text
    body = result.json(); assert body['total'] == 1
    row = body['items'][0]
    assert row['reservation_key'] == str(f.reservation)
    assert row['remaining_quantity'] == '20.000000'
    assert row['base_unit'] == 'PCS'
    assert f.client.get(url + '?limit=1&page=2').json()['items'] == []
    f.body.update(expected_source_version=row['source_version'], expected_released=row['released_before'])
    assert f.client.post(f.url, json=f.body).status_code == 200
    assert f.client.get(url + '?limit=101').status_code == 422
    f.context.current_org_id = f.orgs[1]
    assert f.client.get(url).status_code == 404


def test_linked_sources_access_boundaries(api):
    f = api; url = f'{f.url}/sources/{f.document}'
    policy = f.user.access_policy
    f.user.access_policy = replace(policy, permission_names=frozenset(f.permissions - {'Request_ReservationRelease', 'Review_ReservationRelease'}))
    assert f.client.get(url).status_code == 403
    f.user.access_policy = replace(policy, module_names=frozenset({'SALES'}))
    assert f.client.get(url).status_code == 403
    f.app.dependency_overrides.pop(get_current_user); f.app.dependency_overrides.pop(get_request_policy)
    assert f.client.get(url).status_code == 401


def execution(f, monkeypatch):
    from tests.test_stock_runtime import config
    monkeypatch.setenv('FREIGHTLENS_LOCAL_STOCK_RUNTIME_JSON', config(f))
    f.user.access_policy = replace(f.user.access_policy,
        permission_names=f.user.access_policy.permission_names | {'Execute_ReservationRelease'})
    return f'{f.url}/{f.case}/execute', dict(operation_key=str(uuid4()))


def test_runtime_release_is_separate_from_review_and_replays_once(api, monkeypatch):
    f = api; url, body = execution(f, monkeypatch)
    assert f.client.post(url, json=body).status_code == 403
    f.review()
    result = f.client.post(url, json=body)
    assert result.status_code == 200, result.text
    assert result.json()['reservation_remaining'] == '15.000000'
    assert result.json()['status'] == 'CONSUMED'
    assert f.client.post(url, json=body).json()['replayed']
    assert f.client.post(url, json=dict(operation_key=str(uuid4()))).status_code == 409


def test_release_execution_permission_and_tenant_boundaries(api, monkeypatch):
    f = api; url, body = execution(f, monkeypatch); f.review()
    policy = f.user.access_policy
    f.user.access_policy = replace(policy, permission_names=frozenset(f.permissions))
    assert f.client.post(url, json=body).status_code == 403
    f.user.access_policy = policy; f.context.current_org_id = f.orgs[1]
    assert f.client.post(url, json=body).status_code == 404
    f.context.current_org_id = f.orgs[0]
    f.user.access_policy = replace(policy, module_names=frozenset({'SALES'}))
    assert f.client.post(url, json=body).status_code == 403
    f.app.dependency_overrides.pop(get_current_user); f.app.dependency_overrides.pop(get_request_policy)
    assert f.client.post(url, json=body).status_code == 401


def test_release_runtime_disabled_stale_and_client_authority_denied(api, monkeypatch):
    from tests.test_posting_authority import append_epoch
    f = api; url, body = execution(f, monkeypatch); f.review()
    assert f.client.post(url, json={**body, 'authority': {}}).status_code == 422
    monkeypatch.delenv('FREIGHTLENS_LOCAL_STOCK_RUNTIME_JSON')
    assert f.client.post(url, json=body).status_code == 503
    execution(f, monkeypatch)
    append_epoch(f, 2, 'ACTIVE')
    assert f.client.post(url, json=body).status_code == 403
    with f.factory.begin() as db: assert f.load_release(db).details['released_before'] == '0.000000'


def test_execute_only_role_can_inspect_but_not_review(api, monkeypatch):
    f = api; execution(f, monkeypatch)
    f.user.id = f.reviewer
    f.user.access_policy = replace(f.user.access_policy, permission_names=frozenset(
        (f.permissions - {'Request_ReservationRelease', 'Review_ReservationRelease'}) | {'Execute_ReservationRelease'}))
    assert f.client.get(f.url).json()['total'] == 1
    assert f.client.get(f'{f.url}/sources/{f.document}').status_code == 200
    assert f.client.post(f'{f.url}/{f.case}/review', json=dict(operation_key=str(uuid4()),
        expected_version=1, outcome='APPROVED', reason='Synthetic')).status_code == 403


def test_cloud_runtime_executes_reviewed_release_without_client_authority(api, monkeypatch):
    f = api
    monkeypatch.delenv('FREIGHTLENS_LOCAL_STOCK_RUNTIME_JSON', raising=False)
    monkeypatch.setenv('FREIGHTLENS_CLOUD_STOCK_RUNTIME_NODE_KEY', str(f.node_key))
    f.user.access_policy = replace(f.user.access_policy,
        permission_names=f.user.access_policy.permission_names | {'Execute_ReservationRelease'})
    f.review()
    response = f.client.post(f'{f.url}/{f.case}/execute', json={
        'operation_key': str(uuid4())})
    assert response.status_code == 200, response.text
    assert response.json()['status'] == 'CONSUMED'
