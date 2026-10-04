from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from Model.db import get_db
from Model.containermgmt.Inventory.StockLedger import StockReservation
from auth.dependencies import get_current_user, get_org_context
from auth.policy import AccessPolicy, get_request_policy
from tests.test_other_store_fulfilment import fulfilment  # noqa: F401
from tests.test_store_allocation import allocation  # noqa: F401
from tests.test_sales_reservation_sources import demand  # noqa: F401
from tests.test_sales_intent_concurrency import ready  # noqa: F401
from tests.test_stock_ledger import stock  # noqa: F401


@pytest.fixture
def api(fulfilment):
    from Routes.Inventory.OtherStoreFulfilmentRouter import OtherStoreFulfilmentRouter
    f = fulfilment; f.user = SimpleNamespace(id=f.actor, roles=[])
    f.permissions = {'View_SalesDraft', 'View_Product', 'View_Customer', 'View_Personal_Data',
        'Request_OtherStoreFulfilment', 'Review_OtherStoreFulfilment'}
    f.user.access_policy = AccessPolicy(user=f.user, org_ids=(f.orgs[0],), permission_names=frozenset(f.permissions),
        module_names=frozenset({'SALES', 'INVENTORY'}), field_permissions={'PERSONAL': 'View_Personal_Data'})
    f.app = FastAPI(); f.app.include_router(OtherStoreFulfilmentRouter)
    def db():
        with f.factory() as session: yield session
    f.app.dependency_overrides.update({get_db: db, get_current_user: lambda: f.user,
        get_org_context: lambda: f.context, get_request_policy: lambda: f.user.access_policy})
    f.url = '/inventory/other-store-fulfilment-cases'
    f.body = dict(operation_key=str(uuid4()), source=f.source.model_dump(mode='json'), assignment_version=1,
        balance_id=f.other_balance, expected_stock_version=1, quantity='5', input_unit='PCS',
        review_at=f.review_at.isoformat(), reason='Synthetic explicit other-store request')
    with TestClient(f.app) as client:
        f.client = client; yield f


def test_exact_request_review_replay_and_no_stock_effect(api):
    f = api; response = f.client.post(f.url, json=f.body)
    assert response.status_code == 200, response.text
    key = response.json()['case_key']
    assert f.client.post(f.url, json=f.body).json()['replayed'] is True
    row = f.client.get(f.url+'?limit=1').json()['items'][0]
    assert row['source'] == f.body['source']
    assert row['fulfilment_branch_id'] == f.other_branch
    assert row['existing_holds'] == {'count': 0, 'remaining': '0'}
    assert 'assignment_version' not in row
    assert 'digest' not in row['existing_holds']
    review = dict(operation_key=str(uuid4()), expected_version=1, outcome='APPROVED', reason='Independent review')
    assert f.client.post(f'{f.url}/{key}/review', json=review).status_code == 403
    f.user.id = f.reviewer
    reviewed = f.client.post(f'{f.url}/{key}/review', json=review)
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()['status'] == 'APPROVED'
    assert f.client.post(f'{f.url}/{key}/review', json=review).json()['replayed'] is True
    assert f.client.get(f.url+'?page=2&limit=1').json()['items'] == []
    assert f.client.get(f.url+'?limit=101').status_code == 422
    assert f.client.post(f'{f.url}/{key}/apply', json={}).status_code == 404
    with f.factory() as db: assert db.query(StockReservation).filter_by(org_id=f.orgs[0]).count() == 0


@pytest.mark.parametrize('missing', ['Request_OtherStoreFulfilment', 'View_SalesDraft', 'View_Product', 'View_Customer', 'View_Personal_Data'])
def test_missing_permission_denies_request(api, missing):
    f = api; f.user.access_policy = replace(f.user.access_policy, permission_names=frozenset(f.permissions-{missing}))
    assert f.client.post(f.url, json=f.body).status_code == 403


def test_requestor_visibility_and_review_permission(api):
    f = api; key = f.client.post(f.url, json=f.body).json()['case_key']
    f.user.id = f.reviewer
    f.user.access_policy = replace(f.user.access_policy, permission_names=frozenset(f.permissions-{'Review_OtherStoreFulfilment'}))
    assert f.client.get(f.url).json()['items'] == []
    assert f.client.post(f'{f.url}/{key}/review', json=dict(operation_key=str(uuid4()), expected_version=1,
        outcome='APPROVED', reason='Not permitted')).status_code == 403


def test_foreign_and_stale_requests_fail_closed(api):
    f = api; key = f.client.post(f.url, json=f.body).json()['case_key']
    f.body['expected_stock_version'] = 2
    assert f.client.post(f.url, json=f.body).status_code == 409
    f.body['expected_stock_version'] = 1; f.context.current_org_id = f.orgs[1]
    assert f.client.post(f.url, json=f.body).status_code == 404
    assert f.client.get(f.url).json()['items'] == []
    assert f.client.post(f'{f.url}/{key}/review', json=dict(operation_key=str(uuid4()), expected_version=1,
        outcome='APPROVED', reason='Foreign')).status_code == 404


@pytest.mark.parametrize('module', ['SALES', 'INVENTORY'])
def test_module_denial(api, module):
    f = api; f.user.access_policy = replace(f.user.access_policy, module_names=frozenset({'SALES', 'INVENTORY'}-{module}))
    assert f.client.get(f.url).status_code == 403
    assert f.client.post(f.url, json=f.body).status_code == 403


def test_anonymous_and_forged_authority_denied(api):
    f = api
    assert f.client.post(f.url, json={**f.body, 'requestor_id': f.reviewer}).status_code == 422
    assert f.client.post(f.url, json={**f.body, 'authority': {}}).status_code == 422
    f.app.dependency_overrides.pop(get_current_user)
    assert f.client.get(f.url).status_code == 401
    assert f.client.post(f.url, json=f.body).status_code == 401


def test_self_working_store_needs_no_user_directory_permission(api):
    f = api
    response = f.client.get(f.url+'/working-store')
    assert response.status_code == 200, response.text
    assert response.json() == dict(branch_id=f.branches[0], assignment_version=1, counter_id=f.action.counter_id)
    f.user.id = f.reviewer
    assert f.client.get(f.url+'/working-store').status_code == 403
    f.user.id = f.actor; f.context.current_org_id = f.orgs[1]
    assert f.client.get(f.url+'/working-store').status_code == 403


def test_self_working_store_does_not_accept_another_user_identity(api):
    f = api
    assert f.client.get(f.url+'/working-store?user_id='+str(f.reviewer)).json()['branch_id'] == f.branches[0]
    f.user.access_policy = replace(f.user.access_policy, permission_names=frozenset(f.permissions-{'Request_OtherStoreFulfilment'}))
    assert f.client.get(f.url+'/working-store').status_code == 403
