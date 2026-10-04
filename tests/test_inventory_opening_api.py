"""Public reviewed opening/import API over synthetic isolated records."""
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from Model.db import get_db
from Model.containermgmt.Inventory.StockLedger import StockBalance, StockMovement
from Model.containermgmt.Inventory.Valuation import InventoryValuation
from Routes.Inventory.OpeningRouter import OpeningRouter
from auth.dependencies import get_current_user, get_org_context
from auth.policy import AccessPolicy, get_request_policy
from tests.test_inventory_opening_cases import opening  # noqa: F401
from tests.test_policy_activation_concurrency import reviewed  # noqa: F401
from tests.test_stock_ledger import stock  # noqa: F401


@pytest.fixture
def opening_api(opening):
    f = opening
    f.user = SimpleNamespace(id=f.actor, roles=[])
    f.permissions = frozenset({
        'View_Product', 'View_Financials', 'Manage_Financials',
        'Post_InventoryCost', 'Request_InventoryOpening',
        'Review_InventoryOpening', 'Execute_InventoryOpening',
    })
    f.user.access_policy = AccessPolicy(user=f.user,
        org_ids=(f.orgs[0],), permission_names=f.permissions,
        module_names=frozenset({'INVENTORY'}),
        field_permissions={'FINANCIAL': 'View_Financials'})
    f.app = FastAPI()
    f.app.include_router(OpeningRouter)

    def db_dependency():
        with f.factory() as session:
            yield session

    f.app.dependency_overrides.update({
        get_db: db_dependency,
        get_current_user: lambda: f.user,
        get_org_context: lambda: f.context,
        get_request_policy: lambda: f.user.access_policy,
    })
    f.url = '/inventory/opening-cases'
    f.body = {
        'operation_key': str(uuid4()),
        **f.intent.model_dump(mode='json'),
    }
    with TestClient(f.app) as client:
        f.client = client
        yield f


def request_review_execute(f, monkeypatch):
    requested = f.client.post(f.url, json=f.body)
    assert requested.status_code == 200, requested.text
    case_key = requested.json()['case_key']
    assert f.client.post(f.url, json=f.body).json()['replayed'] is True
    review = {'operation_key': str(uuid4()), 'expected_version': 1,
        'outcome': 'APPROVED', 'reason': 'Synthetic independent review'}
    assert f.client.post(f'{f.url}/{case_key}/review', json=review).status_code == 403
    f.user.id = f.reviewer
    reviewed = f.client.post(f'{f.url}/{case_key}/review', json=review)
    assert reviewed.status_code == 200, reviewed.text
    operation_key = str(uuid4())
    monkeypatch.setenv('FREIGHTLENS_CLOUD_STOCK_RUNTIME_NODE_KEY',
        str(f.node_key))
    monkeypatch.setenv('FREIGHTLENS_CLOUD_COST_RUNTIME_NODE_KEY',
        str(f.node_key))
    executed = f.client.post(f'{f.url}/{case_key}/execute',
        json={'operation_key': operation_key})
    assert executed.status_code == 200, executed.text
    return case_key, operation_key, executed.json()


def test_opening_api_request_review_list_execute_and_replay(
        opening_api, monkeypatch):
    f = opening_api
    case_key, operation_key, result = request_review_execute(f, monkeypatch)
    assert result['status'] == 'POSTED_UNRECONCILED'
    assert result['on_hand'] == '10.000000'
    assert result['pool_value_scr'] == '120.000000'
    replay = f.client.post(f'{f.url}/{case_key}/execute',
        json={'operation_key': operation_key})
    assert replay.status_code == 200 and replay.json()['replayed'] is True
    page = f.client.get(f'{f.url}?view=ALL&limit=1')
    assert page.status_code == 200
    assert page.json()['total'] == 2 and len(page.json()['items']) == 1
    with f.factory() as db:
        balance = db.get(StockBalance, result['balance_id'])
        assert balance.on_hand == 10
        assert db.query(StockMovement).filter_by(
            balance_id=balance.id, kind='OPENING').count() == 1
        assert db.query(InventoryValuation).filter_by(
            balance_id=balance.id, kind='OPENING').count() == 1


@pytest.mark.parametrize('permission', [
    'Request_InventoryOpening', 'Review_InventoryOpening',
    'Execute_InventoryOpening',
])
def test_opening_write_permissions_are_independent(
        opening_api, monkeypatch, permission):
    f = opening_api
    if permission == 'Request_InventoryOpening':
        f.user.access_policy = replace(f.user.access_policy,
            permission_names=f.permissions - {permission})
        assert f.client.post(f.url, json=f.body).status_code == 403
        return
    requested = f.client.post(f.url, json=f.body)
    case_key = requested.json()['case_key']
    f.user.id = f.reviewer
    if permission == 'Review_InventoryOpening':
        f.user.access_policy = replace(f.user.access_policy,
            permission_names=f.permissions - {permission})
        denied = f.client.post(f'{f.url}/{case_key}/review', json={
            'operation_key': str(uuid4()), 'expected_version': 1,
            'outcome': 'APPROVED', 'reason': 'Synthetic review'})
        assert denied.status_code == 403
        return
    review = f.client.post(f'{f.url}/{case_key}/review', json={
        'operation_key': str(uuid4()), 'expected_version': 1,
        'outcome': 'APPROVED', 'reason': 'Synthetic review'})
    assert review.status_code == 200
    f.user.access_policy = replace(f.user.access_policy,
        permission_names=f.permissions - {permission})
    monkeypatch.setenv('FREIGHTLENS_CLOUD_STOCK_RUNTIME_NODE_KEY',
        str(f.node_key))
    monkeypatch.setenv('FREIGHTLENS_CLOUD_COST_RUNTIME_NODE_KEY',
        str(f.node_key))
    assert f.client.post(f'{f.url}/{case_key}/execute', json={
        'operation_key': str(uuid4())}).status_code == 403


def test_opening_api_financial_module_runtime_and_tenant_fail_closed(
        opening_api, monkeypatch):
    f = opening_api
    financial = f.user.access_policy
    f.user.access_policy = replace(financial, field_permissions={})
    assert f.client.get(f.url).status_code == 403
    f.user.access_policy = replace(financial, module_names=frozenset())
    assert f.client.get(f.url).status_code == 403
    f.user.access_policy = financial
    requested = f.client.post(f.url, json=f.body).json()
    f.user.id = f.reviewer
    assert f.client.post(f"{f.url}/{requested['case_key']}/review", json={
        'operation_key': str(uuid4()), 'expected_version': 1,
        'outcome': 'APPROVED', 'reason': 'Synthetic review'}).status_code == 200
    monkeypatch.delenv('FREIGHTLENS_CLOUD_STOCK_RUNTIME_NODE_KEY', raising=False)
    monkeypatch.delenv('FREIGHTLENS_CLOUD_COST_RUNTIME_NODE_KEY', raising=False)
    assert f.client.post(f"{f.url}/{requested['case_key']}/execute", json={
        'operation_key': str(uuid4())}).status_code == 503
    f.context.current_org_id = f.orgs[1]
    assert f.client.get(f.url).json()['items'] == []
    assert f.client.post(f.url, json={**f.body,
        'operation_key': str(uuid4())}).status_code == 404


def test_opening_api_rejects_client_authority_and_anonymous_access(opening_api):
    f = opening_api
    assert f.client.post(f.url, json={**f.body, 'authority': {}}).status_code == 422
    f.app.dependency_overrides.pop(get_current_user)
    f.app.dependency_overrides.pop(get_request_policy)
    assert f.client.get(f.url).status_code == 401
    assert f.client.post(f.url, json=f.body).status_code == 401
