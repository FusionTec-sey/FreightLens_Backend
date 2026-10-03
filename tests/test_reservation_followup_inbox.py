from dataclasses import replace
from datetime import datetime, timezone, timedelta
from uuid import uuid4
import pytest
from tests.test_reservation_deadline_api import endpoint  # noqa: F401
from tests.test_reservation_release_api import api  # noqa: F401
from tests.test_reservation_release_review import release  # noqa: F401
from tests.test_sales_reservation_sources import demand  # noqa: F401
from tests.test_sales_intent_concurrency import ready  # noqa: F401
from tests.test_stock_ledger import stock as future_stock  # noqa: F401
from auth.dependencies import get_current_user
from auth.policy import get_request_policy


@pytest.fixture
def stock(future_stock):
    # Original synthetic creation date, never editing an existing hold's history.
    future_stock.review_at = datetime.now(timezone.utc) - timedelta(days=1)
    return future_stock


def test_due_inbox_is_paginated_scoped_and_does_not_release(endpoint):
    f = endpoint; url = f.deadline_url+'/due'
    result = f.client.get(url+'?limit=1')
    assert result.status_code == 200, result.text
    page = result.json(); assert page['total'] == 1
    row = page['items'][0]
    assert row['document_key'] == str(f.document) and row['review_due']
    assert row['remaining_quantity'] == '20.000000' and row['branch_id'] == f.branches[0]
    assert row['product_name'] and row['location_name'] and row['branch_name']
    assert f.client.get(url+'?limit=1&page=2').json()['items'] == []
    assert f.client.get(url+f'?branch_id={f.branches[1]}').json()['items'] == []
    assert f.client.get(url+'?limit=101').status_code == 422
    f.context.current_org_id = f.orgs[1]
    assert f.client.get(url).json()['items'] == []


def test_scheduling_future_followup_removes_it_from_due_not_from_stock(endpoint):
    f = endpoint; url = f.deadline_url+'/due'
    key = f.client.post(f.deadline_url, json=f.deadline_body).json()['case_key']
    f.user.id = f.reviewer
    decision = dict(operation_key=str(uuid4()), expected_version=1, outcome='APPROVED', reason='Agreed synthetic follow-up')
    assert f.client.post(f'{f.deadline_url}/{key}/review', json=decision).status_code == 200
    assert f.client.get(url).json()['total'] == 1  # Approval alone changes nothing.
    assert f.client.post(f'{f.deadline_url}/{key}/schedule', json=dict(operation_key=str(uuid4()))).status_code == 200
    assert f.client.get(url).json()['total'] == 0
    holds = f.client.get(f'{f.url}/sources/{f.document}').json()['items']
    assert holds[0]['remaining_quantity'] == '20.000000' and holds[0]['deadline_version'] == 1


def test_fully_released_hold_is_not_a_due_followup(endpoint):
    f = endpoint
    from decimal import Decimal
    from Services.reservation_release_service import load_release_binding
    from Services.manager_case_service import request_case, review_case
    from Services.stock_ledger_service import release_stock
    load = lambda db: load_release_binding(db, f.context, f.reservation, Decimal('20'))
    with f.factory.begin() as db: binding = load(db)
    case = uuid4()
    request_case(f.factory, f.context, f.actor, case, binding=binding, reason='Synthetic complete release', load_binding=load, authorize=lambda db: None)
    review_case(f.factory, f.context, f.reviewer, uuid4(), case_key=case, binding=binding, expected_version=1, outcome='APPROVED', reason='Synthetic review', load_binding=load, authorize=lambda db: None)
    release_stock(f.factory, f.context, f.actor, uuid4(), balance_id=f.balance, reservation_key=f.reservation,
        source_line_key=f.source.stock_source_key(), quantity=Decimal('20'), reason='Synthetic release', authority=f.claim,
        authorize=lambda db: None, case_key=case, release_binding=binding)
    assert f.client.get(f.deadline_url+'/due').json()['items'] == []


def test_due_inbox_manager_permissions_modules_and_anonymous_denied(endpoint):
    f = endpoint; url = f.deadline_url+'/due'; policy = f.user.access_policy
    f.user.access_policy = replace(policy, permission_names=frozenset(f.permissions-{'Review_ReservationDeadline', 'Schedule_ReservationReview'}))
    assert f.client.get(url).status_code == 403
    f.user.access_policy = replace(policy, module_names=frozenset({'SALES'}))
    assert f.client.get(url).status_code == 403
    f.app.dependency_overrides.pop(get_current_user); f.app.dependency_overrides.pop(get_request_policy)
    assert f.client.get(url).status_code == 401
