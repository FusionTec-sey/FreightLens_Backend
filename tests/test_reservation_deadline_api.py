from dataclasses import replace
from datetime import timedelta
from uuid import uuid4
import pytest
from auth.dependencies import get_current_user
from auth.policy import get_request_policy
from tests.test_reservation_release_api import api  # noqa: F401
from tests.test_reservation_release_review import release  # noqa: F401
from tests.test_sales_reservation_sources import demand  # noqa: F401
from tests.test_sales_intent_concurrency import ready  # noqa: F401
from tests.test_stock_ledger import stock  # noqa: F401


@pytest.fixture
def endpoint(api):
    from Routes.Inventory.ReservationDeadlineRouter import ReservationDeadlineRouter
    f = api; f.app.include_router(ReservationDeadlineRouter)
    f.permissions |= {'Request_ReservationDeadline', 'Review_ReservationDeadline', 'Schedule_ReservationReview'}
    f.user.access_policy = replace(f.user.access_policy, permission_names=frozenset(f.permissions))
    f.deadline_url = '/inventory/reservation-deadline-cases'
    f.deadline_body = dict(operation_key=str(uuid4()), reservation_key=str(f.reservation), expected_source_version=1,
        expected_deadline_version=0, expected_released='0', next_review_at=(f.review_at+timedelta(days=3)).isoformat(),
        reason='Synthetic customer-agreed follow-up')
    return f


def test_request_review_then_explicit_schedule_updates_read_projection(endpoint):
    f = endpoint
    requested = f.client.post(f.deadline_url, json=f.deadline_body)
    assert requested.status_code == 200, requested.text
    key = requested.json()['case_key']
    assert f.client.post(f.deadline_url, json=f.deadline_body).json()['replayed']
    decision = dict(operation_key=str(uuid4()), expected_version=1, outcome='APPROVED', reason='Reviewed customer timeline')
    schedule = dict(operation_key=str(uuid4()))
    assert f.client.post(f'{f.deadline_url}/{key}/schedule', json=schedule).status_code == 403
    assert f.client.post(f'{f.deadline_url}/{key}/review', json=decision).status_code == 403
    f.user.id = f.reviewer
    assert f.client.get(f.deadline_url+'?view=NEEDS_MY_REVIEW').json()['total'] == 1
    assert f.client.post(f'{f.deadline_url}/{key}/review', json=decision).status_code == 200
    before = f.client.get(f'{f.url}/sources/{f.document}').json()['items'][0]
    assert before['deadline_version'] == 0
    response = f.client.post(f'{f.deadline_url}/{key}/schedule', json=schedule)
    assert response.status_code == 200, response.text
    assert f.client.post(f'{f.deadline_url}/{key}/schedule', json=schedule).json()['replayed']
    after = f.client.get(f'{f.url}/sources/{f.document}').json()['items'][0]
    assert after['deadline_version'] == 1 and after['remaining_quantity'] == before['remaining_quantity']
    assert not after['review_due'] and after['review_at'] != before['review_at']
    assert f.client.get(f.deadline_url).json()['items'][0]['status'] == 'CONSUMED'


@pytest.mark.parametrize('permission,path', [('Request_ReservationDeadline',''), ('Review_ReservationDeadline','/review'), ('Schedule_ReservationReview','/schedule')])
def test_deadline_action_permissions(endpoint, permission, path):
    f = endpoint; f.user.access_policy = replace(f.user.access_policy, permission_names=frozenset(f.permissions-{permission}))
    url = f.deadline_url + (f'/{f.case}{path}' if path else '')
    body = f.deadline_body if not path else dict(operation_key=str(uuid4()), **(dict(expected_version=1, outcome='APPROVED', reason='Synthetic') if path == '/review' else {}))
    assert f.client.post(url, json=body).status_code == 403


def test_stale_foreign_module_and_anonymous_deadline_access(endpoint):
    f = endpoint; f.deadline_body['expected_deadline_version'] = 5
    assert f.client.post(f.deadline_url, json=f.deadline_body).status_code == 409
    f.context.current_org_id = f.orgs[1]
    assert f.client.post(f.deadline_url, json=f.deadline_body).status_code == 404
    assert f.client.get(f.deadline_url).json()['items'] == []
    f.user.access_policy = replace(f.user.access_policy, module_names=frozenset({'SALES'}))
    assert f.client.get(f.deadline_url).status_code == 403
    f.app.dependency_overrides.pop(get_current_user); f.app.dependency_overrides.pop(get_request_policy)
    assert f.client.get(f.deadline_url).status_code == 401


def test_schedule_rejects_other_case_type_and_naive_dates(endpoint):
    f = endpoint
    assert f.client.post(f'{f.deadline_url}/{f.case}/schedule', json=dict(operation_key=str(uuid4()))).status_code == 404
    f.deadline_body['next_review_at'] = '2026-12-01T12:00:00'
    assert f.client.post(f.deadline_url, json=f.deadline_body).status_code == 422
