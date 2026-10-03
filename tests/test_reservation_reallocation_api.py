from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from Model.db import get_db
from auth.dependencies import get_current_user, get_org_context
from auth.policy import AccessPolicy, get_request_policy
from tests.test_reservation_reallocation import move  # noqa: F401
from tests.test_reservation_release_review import release  # noqa: F401
from tests.test_sales_reservation_sources import demand  # noqa: F401
from tests.test_sales_intent_concurrency import ready  # noqa: F401
from tests.test_stock_ledger import stock  # noqa: F401
from tests.test_reservation_release_api import (test_request_review_queue_and_no_automatic_release,
    test_foreign_sources_and_stale_versions_denied, test_module_and_anonymous_denials)


@pytest.fixture
def api(move):
    from Routes.Inventory.ReservationReallocationRouter import ReservationReallocationRouter
    f = move; f.user = SimpleNamespace(id=f.actor, roles=[]); f.case = f.move_case
    f.permissions = {'View_SalesDraft', 'View_Product', 'View_Customer', 'View_Personal_Data',
                     'Request_ReservationReallocation', 'Review_ReservationReallocation'}
    f.user.access_policy = AccessPolicy(user=f.user, org_ids=(f.orgs[0],), permission_names=frozenset(f.permissions),
        module_names=frozenset({'SALES', 'INVENTORY'}), field_permissions={'PERSONAL': 'View_Personal_Data'})
    f.app = FastAPI(); f.app.include_router(ReservationReallocationRouter)
    def db():
        with f.factory() as session: yield session
    f.app.dependency_overrides.update({get_db: db, get_current_user: lambda: f.user,
        get_org_context: lambda: f.context, get_request_policy: lambda: f.user.access_policy})
    f.url = '/inventory/reservation-reallocation-cases'
    f.body = dict(operation_key=str(uuid4()), reservation_key=str(f.reservation), expected_source_version=1,
        expected_released='0', quantity='5', target=f.target.model_dump(mode='json'),
        review_at=f.target_review.isoformat(), reason='Synthetic reallocation request')
    with TestClient(f.app) as client:
        f.client = client; yield f


@pytest.mark.parametrize('missing', ['Request_ReservationReallocation', 'View_SalesDraft', 'View_Personal_Data', 'View_Product', 'View_Customer'])
def test_request_permission_denial(api, missing):
    f = api; f.user.access_policy = replace(f.user.access_policy, permission_names=frozenset(f.permissions - {missing}))
    assert f.client.post(f.url, json=f.body).status_code == 403


def test_requestors_only_see_own_cases_and_cannot_review(api):
    f = api; f.user.id = f.reviewer
    f.user.access_policy = replace(f.user.access_policy, permission_names=frozenset(f.permissions - {'Review_ReservationReallocation'}))
    assert f.client.get(f.url).json()['items'] == []
    review = dict(operation_key=str(uuid4()), expected_version=1, outcome='APPROVED', reason='Synthetic review')
    assert f.client.post(f'{f.url}/{f.case}/review', json=review).status_code == 403


def test_exact_target_and_bounded_read_contract(api):
    f = api; row = f.client.get(f.url+'?limit=1').json()['items'][0]
    assert row['target'] == f.target.model_dump(mode='json')
    assert Decimal(row['quantity']) == Decimal('5.000000')
    assert row['target_hold_snapshot'] == {'count': 0, 'remaining': '0'}
    assert f.client.get(f.url+'?page=2&limit=1').json()['items'] == []
    assert f.client.get(f.url+'?limit=101').status_code == 422
    f.body['target']['version'] = 2
    assert f.client.post(f.url, json=f.body).status_code == 409
    f.body['target']['version'] = 1; f.body['review_at'] = '2026-10-04T10:00:00'
    assert f.client.post(f.url, json=f.body).status_code == 422
    assert f.client.post(f'{f.url}/{f.case}/apply', json={}).status_code == 404
