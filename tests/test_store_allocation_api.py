from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from Model.db import get_db
from auth.dependencies import get_current_user, get_org_context
from auth.policy import AccessPolicy, get_request_policy
from tests.test_store_allocation import allocation  # noqa: F401
from tests.test_sales_reservation_sources import demand  # noqa: F401
from tests.test_sales_intent_concurrency import ready  # noqa: F401
from tests.test_stock_ledger import stock  # noqa: F401
from tests.test_stock_runtime import config


@pytest.fixture
def api(allocation, monkeypatch):
    from Routes.Orders.StoreAllocationRouter import StoreAllocationRouter
    from Routes.Inventory.BranchSettingsRouter import save_settings
    from Schema.BranchSettingsSchema import BranchSettingsSave
    f = allocation; f.user = SimpleNamespace(id=f.actor, roles=[])
    f.permissions = {'View_SalesDraft', 'View_Product', 'View_Customer', 'View_Personal_Data', 'Allocate_SalesDraftStock'}
    f.user.access_policy = AccessPolicy(user=f.user, org_ids=(f.orgs[0],), permission_names=frozenset(f.permissions),
        module_names=frozenset({'SALES', 'INVENTORY'}), field_permissions={'PERSONAL': 'View_Personal_Data'})
    with f.factory() as db:
        save_settings(f.branches[0], BranchSettingsSave(operation_key=uuid4(), expected_version=0,
            config=dict(timezone_name='Indian/Mahe', weekday_cutoff='00:00', weekend_cutoff='00:00', trading_weekdays=list(range(7)))),
            db, f.context, f.user)
    monkeypatch.setenv('FREIGHTLENS_LOCAL_STOCK_RUNTIME_JSON', config(f))
    f.app = FastAPI(); f.app.include_router(StoreAllocationRouter)
    def db():
        with f.factory() as session: yield session
    f.app.dependency_overrides.update({get_db: db, get_current_user: lambda: f.user,
        get_org_context: lambda: f.context, get_request_policy: lambda: f.user.access_policy})
    f.body = dict(operation_key=str(uuid4()), source=f.source.model_dump(mode='json'), counter_key=str(f.counter_key),
        branch_version=1, counter_version=1, assignment_version=1, quantity='20', input_unit='PCS',
        review_at=f.review_at.isoformat(), reason='Synthetic same-store allocation')
    f.url = '/sales/draft-allocations'
    with TestClient(f.app) as client:
        f.client = client; yield f


def test_runtime_allocation_splits_and_retries_without_duplicate_holds(api):
    f = api; response = f.client.post(f.url, json=f.body)
    assert response.status_code == 200, response.text
    assert len(response.json()['reservations']) == 2
    assert response.json()['branch_id'] == f.branches[0]
    replay = f.client.post(f.url, json=f.body)
    assert replay.status_code == 200, replay.text
    assert replay.json()['replayed'] is True
    assert replay.json()['reservations'] == response.json()['reservations']


@pytest.mark.parametrize('missing', ['Allocate_SalesDraftStock', 'View_Product', 'View_SalesDraft', 'View_Customer', 'View_Personal_Data'])
def test_permissions_guard_allocation(api, missing):
    f = api; f.user.access_policy = replace(f.user.access_policy, permission_names=frozenset(f.permissions-{missing}))
    assert f.client.post(f.url, json=f.body).status_code == 403


@pytest.mark.parametrize('field', ['authority', 'business_date', 'branch_id', 'node_key'])
def test_client_cannot_inject_runtime_identity_or_business_date(api, field):
    assert api.client.post(api.url, json={**api.body, field: 'forged'}).status_code == 422


def test_missing_runtime_and_stale_settings_fail_closed(api, monkeypatch):
    f = api; monkeypatch.delenv('FREIGHTLENS_LOCAL_STOCK_RUNTIME_JSON')
    assert f.client.post(f.url, json=f.body).status_code == 503
    monkeypatch.setenv('FREIGHTLENS_LOCAL_STOCK_RUNTIME_JSON', config(f))
    assert f.client.post(f.url, json={**f.body, 'counter_version': 2}).status_code == 422
    assert f.client.post(f.url, json={**f.body, 'assignment_version': 2}).status_code == 403


def test_foreign_source_module_and_anonymous_denied(api):
    f = api; f.context.current_org_id = f.orgs[1]
    assert f.client.post(f.url, json=f.body).status_code == 404
    f.context.current_org_id = f.orgs[0]
    f.user.access_policy = replace(f.user.access_policy, module_names=frozenset({'SALES'}))
    assert f.client.post(f.url, json=f.body).status_code == 403
    f.app.dependency_overrides.pop(get_current_user)
    assert f.client.post(f.url, json=f.body).status_code == 401
