from dataclasses import replace
from unittest.mock import Mock
import pytest
from tests.test_sales_intent_api import api  # noqa: F401
from tests.test_sales_intent_sources import source  # noqa: F401
from tests.test_policy_activation import activation  # noqa: F401
from tests.test_policy_manager_cases import policy_cases  # noqa: F401
from tests.test_inventory_policy_drafts import draft  # noqa: F401
from tests.test_inventory_locations import locations  # noqa: F401


@pytest.fixture
def choices(api):
    from Routes.Orders.SalesSourceRouter import SalesSourceRouter
    api.app.include_router(SalesSourceRouter)
    return api


def test_browse_scoped_branches_and_reviewed_units(choices):
    f = choices
    branches = f.client.get('/sales/draft-sources/branches?limit=1').json()
    assert branches['total'] == 1 and branches['items'][0]['id'] == f.own
    products = f.client.get('/sales/draft-sources/products?limit=1').json()
    assert products['total'] == 1 and products['items'][0]['units'] == ['PCS', 'BOX']
    assert set(products['items'][0]) == {'id', 'sku', 'name', 'policy_version', 'base_unit', 'units', 'quantity_step'}
    assert f.client.get('/sales/draft-sources/products?page=2&limit=1').json()['items'] == []
    assert f.client.get('/sales/draft-sources/products?limit=101').status_code == 422


@pytest.mark.parametrize('path', ['branches', 'products'])
def test_sources_require_permissions_module_and_auth(choices, path):
    f = choices; url = '/sales/draft-sources/' + path; policy = f.user.access_policy
    f.user.access_policy = replace(policy, permission_names=frozenset())
    assert f.client.get(url).status_code == 403
    f.user.access_policy = replace(policy, module_names=frozenset())
    assert f.client.get(url).status_code == 403
    from auth.policy import get_request_policy
    for dep in f.user_dependencies: f.app.dependency_overrides.pop(dep)
    f.app.dependency_overrides.pop(get_request_policy, None)
    assert f.client.get(url).status_code == 401


def test_search_is_rehydrated_and_foreign_or_failed_search_is_not_empty_success(choices, monkeypatch):
    f = choices; name = 'Routes.Orders.SalesSourceRouter.search_products_with_total'
    search = Mock(return_value=([dict(id=f.product.id, org_id=f.org_a, name='untrusted')], 1))
    monkeypatch.setattr(name, search)
    result = f.client.get('/sales/draft-sources/products?search=tile')
    assert result.status_code == 200 and result.json()['items'][0]['name'] == f.product.name
    assert search.call_args.kwargs['strict_public'] is True
    search.return_value = ([dict(id=f.foreign_product.id, org_id=f.org_b)], 1)
    assert f.client.get('/sales/draft-sources/products?search=tile').status_code == 503
    search.side_effect = RuntimeError('unavailable')
    assert f.client.get('/sales/draft-sources/products?search=tile').status_code == 503


def test_strict_public_search_limits_matching_and_propagates_failure(monkeypatch):
    from Services.search_service import search_products_with_total
    client = Mock(); monkeypatch.setattr('Services.search_service.get_meili_client', lambda: client)
    client.index.return_value.search.return_value = {'hits': [], 'estimatedTotalHits': 0}
    assert search_products_with_total('tile', strict_public=True) == ([], 0)
    params = client.index.return_value.search.call_args.args[1]
    assert params['attributesToSearchOn'] == ['name', 'sku']
    assert params['attributesToRetrieve'] == ['id', 'org_id']
    client.index.return_value.search.side_effect = RuntimeError('private provider details')
    with pytest.raises(RuntimeError, match='Product search unavailable'):
        search_products_with_total('tile', strict_public=True)
