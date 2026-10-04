from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4, UUID
from dataclasses import replace
import pytest
from Services import search_service as search
from tests.test_sales_intent_api import api  # noqa: F401
from tests.test_sales_intent_sources import source  # noqa: F401
from tests.test_policy_activation import activation  # noqa: F401
from tests.test_policy_manager_cases import policy_cases  # noqa: F401
from tests.test_inventory_policy_drafts import draft  # noqa: F401
from tests.test_inventory_locations import locations  # noqa: F401


def test_search_scope_and_page(monkeypatch):
    key = uuid4()
    client = Mock()
    client.index.return_value.search.return_value = {'hits': [
        {'id': str(key), 'org_id': 7, 'branch_id': 2, 'version': 3}], 'totalHits': 1}
    monkeypatch.setattr(search, 'get_meili_client', lambda: client)
    assert search.search_sales_drafts('Private', 7, 2, 10, 2) == ([(key, 3, 2)], 1)
    options = client.index.return_value.search.call_args.args[1]
    assert options['filter'] == 'org_id = 7 AND is_deleted = false AND branch_id = 2'
    assert options['page'] == 2 and options['hitsPerPage'] == 10


@pytest.mark.parametrize('field,value', [('org_id', 8), ('branch_id', 9), ('version', 0), ('id', 'bad')])
def test_invalid_hits_fail_closed(monkeypatch, field, value):
    client = Mock()
    hit = dict(id=str(uuid4()), org_id=7, branch_id=2, version=1)
    hit[field] = value
    client.index.return_value.search.return_value = dict(hits=[hit], totalHits=1)
    monkeypatch.setattr(search, 'get_meili_client', lambda: client)
    with pytest.raises(search.SalesSearchUnavailable):
        search.search_sales_drafts('Private', 7, 1, 25, 2)


@pytest.mark.parametrize('status', ['succeeded', 'failed', 'processing'])
def test_projection_whitelist_and_acknowledgement(monkeypatch, status):
    client = Mock()
    client.index.return_value.add_documents.return_value = SimpleNamespace(task_uid=2)
    client.wait_for_task.return_value = SimpleNamespace(uid=2, index_uid='sales_drafts', status=status)
    monkeypatch.setattr(search, 'get_meili_client', lambda: client)
    assert search.sync_sales_draft_document(dict(id=str(uuid4()), org_id=7, branch_id=2,
        version=1, customer_name='Synthetic', contacts=['Private'], cost=99)) == (status == 'succeeded')
    doc = client.index.return_value.add_documents.call_args.args[0][0]
    assert set(doc) == {'id', 'org_id', 'branch_id', 'version', 'customer_name', 'is_deleted'}


def test_search_unavailable_never_logs_query(monkeypatch, caplog):
    monkeypatch.setattr(search, 'get_meili_client', lambda: None)
    with pytest.raises(search.SalesSearchUnavailable):
        search.search_sales_drafts('Private customer', 7, 1, 25)
    assert 'Private customer' not in caplog.text


def test_search_duplicate_ids_and_malformed_totals_are_rejected(monkeypatch):
    client = Mock()
    monkeypatch.setattr(search, 'get_meili_client', lambda: client)
    hit = dict(id=str(uuid4()), org_id=7, branch_id=2, version=1)
    for result in [dict(hits=[hit, hit], totalHits=2), dict(hits=[hit], totalHits=True),
                   dict(hits=[hit], totalHits=0)]:
        client.index.return_value.search.return_value = result
        with pytest.raises(search.SalesSearchUnavailable):
            search.search_sales_drafts('Private', 7, 1, 25)


def test_search_api_pagination_and_empty_pages(api, monkeypatch):
    provider = Mock(return_value=([], 26))
    monkeypatch.setattr('Routes.Orders.SalesIntentRouter.search_sales_drafts', provider)
    result = api.client.get('/sales/drafts?search=Synthetic&page=3&limit=25')
    assert result.status_code == 200
    assert result.json() == dict(items=[], total=26, page=3, limit=25, pages=2)
    provider.assert_called_once_with('Synthetic', api.org_a, 3, 25, None)
    assert api.client.get('/sales/drafts', params={'search': 'a' * 161}).status_code == 422


def test_anonymous_search_never_reaches_provider(api, monkeypatch):
    from auth.policy import get_request_policy
    provider = Mock()
    monkeypatch.setattr('Routes.Orders.SalesIntentRouter.search_sales_drafts', provider)
    for dep in api.user_dependencies:
        api.app.dependency_overrides.pop(dep)
    api.app.dependency_overrides.pop(get_request_policy, None)
    assert api.client.get('/sales/drafts?search=Synthetic').status_code == 401
    provider.assert_not_called()


def test_search_api_rehydrates_current_scope_and_preserves_rank(api, monkeypatch):
    f = api
    assert f.client.put(f.url, json=f.payload).status_code == 200
    key = UUID(f.url.rsplit('/', 1)[1])
    branch = f.payload['draft']['branch_id']
    provider = Mock(return_value=([(key, 1, branch)], 1))
    monkeypatch.setattr('Routes.Orders.SalesIntentRouter.search_sales_drafts', provider)
    response = f.client.get('/sales/drafts', params={'search': '  Synthetic ', 'branch_id': branch})
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store'
    assert response.json()['items'][0]['document_key'] == str(key)
    provider.assert_called_once_with('Synthetic', f.org_a, 1, 25, branch)
    provider.return_value = ([(key, 2, branch)], 1)
    assert f.client.get('/sales/drafts?search=Synthetic').status_code == 503
    # Even a provider hit for a real foreign draft is never returned.
    f.context.current_org_id = f.org_b
    f.context.allowed_org_ids = [f.org_a, f.org_b]
    f.context.is_root = True
    assert f.client.get('/sales/drafts?search=Synthetic').status_code == 503


def test_search_failure_and_permissions_do_not_bypass_provider(api, monkeypatch):
    provider = Mock(side_effect=search.SalesSearchUnavailable('Search unavailable'))
    monkeypatch.setattr('Routes.Orders.SalesIntentRouter.search_sales_drafts', provider)
    assert api.client.get('/sales/drafts?search=test').status_code == 503
    assert api.client.get('/sales/drafts?search=%20%20').status_code == 200
    provider.reset_mock()
    api.user.access_policy = replace(api.user.access_policy, permission_names=frozenset())
    assert api.client.get('/sales/drafts?search=test').status_code == 403
    provider.assert_not_called()


def test_search_failure_does_not_make_saved_draft_uncertain(api, monkeypatch):
    monkeypatch.setattr('Services.sales_draft_search_projection.sync_sales_draft_document', lambda document: False)
    response = api.client.put(api.url, json=api.payload)
    assert response.status_code == 200 and response.json()['search_indexed'] is False
    assert api.client.get(api.url).json()['version'] == 1
    retry = api.client.put(api.url, json=api.payload)
    assert retry.json()['replayed'] is True and retry.json()['version'] == 1


def test_projection_uses_saved_customer_version_and_latest_draft_on_replay(api, monkeypatch):
    documents = []
    monkeypatch.setattr('Services.sales_draft_search_projection.sync_sales_draft_document', lambda doc: documents.append(doc) or True)
    assert api.client.put(api.url, json=api.payload).status_code == 200
    old = dict(api.payload)
    api.payload = dict(api.payload, operation_key=str(uuid4()), expected_version=1)
    assert api.client.put(api.url, json=api.payload).status_code == 200
    assert api.client.put(api.url, json=old).json()['replayed']
    assert [doc['version'] for doc in documents] == [1, 2, 2]
    assert documents[-1]['customer_name'] == api.client.get(api.url).json()['customer_name']
