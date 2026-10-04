from dataclasses import replace
from datetime import date
from uuid import uuid4
import pytest
from Model.containermgmt.Inventory.Location import InventoryBranch, StockLocation
from Services.branch_action_context_service import BranchActionContext
from Services.default_stock_area_service import require_default_stock_area
from tests.test_inventory_locations import locations  # noqa: F401
from tests.test_branch_counters import payload, base
from tests.test_stock_ledger import stock  # noqa: F401


@pytest.fixture
def area(locations):
    f = locations
    def add(code, kind, parent=None, active=True, branch=None, org=None):
        row = StockLocation(org_id=org or f.org_a, branch_id=branch or f.own,
            code=code, name='Synthetic '+code, kind=kind, parent_id=parent, is_active=active)
        f.db.add(row); f.db.flush(); return row
    f.root = add('ROOT', 'SITE')
    f.zone = add('ZONE', 'ZONE', f.root.id)
    f.bin = add('BIN', 'BIN', f.zone.id)
    hidden = add('HIDDEN', 'ZONE', f.root.id, active=False)
    add('HIDDEN_BIN', 'BIN', hidden.id)
    add('SIBLING', 'SITE')
    add('FOREIGN', 'SITE', branch=f.foreign, org=f.org_b)
    f.db.commit()
    f.key = uuid4()
    f.config = dict(name='Synthetic counter', purpose='BOTH', is_enabled=True, default_stock_location_id=f.root.id)
    created = f.client.put(f'{base(f)}/{f.key}', json=payload(config=f.config))
    assert created.status_code == 200, created.text
    f.counter = created.json()
    f.area_url = f'{base(f)}/{f.key}/stock-area'
    f.action = BranchActionContext(f.own, f.counter['id'], 1, 1, date(2026,10,3), 'CHECKOUT')
    return f


def test_area_scope_pagination_and_no_stock_claim(area):
    f = area
    response = f.client.get(f.area_url, params=dict(expected_version=1, limit=1))
    assert response.status_code == 200, response.text
    data = response.json()
    assert data['total'] == 3 and data['pages'] == 3 and len(data['items']) == 1
    assert data['root']['id'] == f.root.id and not data['operational_activation']
    assert {r['id'] for r in f.client.get(f.area_url+'?expected_version=1').json()['items']} == {f.root.id, f.zone.id, f.bin.id}
    assert f.client.get(f.area_url+'?expected_version=1&limit=101').status_code == 422
    assert f.client.get(f.area_url+'?expected_version=2').status_code == 409
    assert f.client.get(f.area_url).status_code == 422


def test_unset_preference_is_a_successful_empty_inspection(area):
    f = area
    assert f.client.put(f'{base(f)}/{f.key}', json=payload(expected_version=1,
        config={**f.config, 'default_stock_location_id': None})).status_code == 200
    response = f.client.get(f.area_url+'?expected_version=2')
    assert response.status_code == 200
    assert response.json()['root'] is None and response.json()['items'] == []
    with f.db.begin_nested():
        assert require_default_stock_area(f.db, f.context, replace(f.action, counter_settings_version=2)) is None


@pytest.mark.parametrize('kind', ['ZONE','BIN'])
def test_narrower_roots_do_not_expand_to_siblings(area, kind):
    f = area; root = f.zone if kind == 'ZONE' else f.bin
    assert f.client.put(f'{base(f)}/{f.key}', json=payload(expected_version=1,
        config={**f.config, 'default_stock_location_id':root.id})).status_code == 200
    data = f.client.get(f.area_url+'?expected_version=2').json()
    assert {row['id'] for row in data['items']} == ({f.zone.id,f.bin.id} if kind == 'ZONE' else {f.bin.id})
    f.root.is_active = False; f.db.commit()
    assert f.client.get(f.area_url+'?expected_version=2').status_code == 404
    assert f.client.put(f'{base(f)}/{f.key}', json=payload(expected_version=2,
        config={**f.config, 'default_stock_location_id':root.id})).status_code == 404


def test_resolver_rechecks_counter_branch_purpose_and_ancestry(area):
    f = area
    other = InventoryBranch(org_id=f.org_a, code='OTHER_AREA', name='Synthetic', kind='STORE')
    f.db.add(other); f.db.commit()
    with f.db.begin_nested(), pytest.raises(LookupError):
        require_default_stock_area(f.db, f.context, replace(f.action, branch_id=other.id))
    with f.db.begin_nested(), pytest.raises(PermissionError):
        require_default_stock_area(f.db, f.context, replace(f.action, action='COLLECTION'))
    assert f.client.put(f'{base(f)}/{f.key}', json=payload(expected_version=1,
        config={**f.config, 'purpose':'COLLECTION'})).status_code == 200
    with f.db.begin_nested(), pytest.raises(PermissionError):
        require_default_stock_area(f.db, f.context, replace(f.action,counter_settings_version=2))


@pytest.mark.parametrize('denial', ['anonymous','permission','module','foreign'])
def test_area_read_access_boundaries(area, denial):
    f = area
    if denial == 'anonymous':
        for dependency in f.user_dependencies: f.app.dependency_overrides.pop(dependency)
    elif denial == 'foreign': f.context.current_org_id = f.org_b
    else:
        f.user.access_policy = replace(f.user.access_policy,
            **({'permission_names':frozenset()} if denial == 'permission' else {'module_names':frozenset()}))
    assert f.client.get(f.area_url+'?expected_version=1').status_code == (401 if denial == 'anonymous' else 404 if denial == 'foreign' else 403)


def test_resolved_area_holds_branch_version_lock_until_transaction_ends(stock):
    from types import SimpleNamespace
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError
    from Routes.Inventory.BranchCounterRouter import save_counter
    from Schema.BranchCounterSchema import CounterSave
    from Services.default_stock_area_service import counter_stock_area
    f = stock; key = uuid4()
    config = dict(name='Synthetic', purpose='BOTH', is_enabled=True, default_stock_location_id=f.locations[0])
    with f.factory() as db:
        counter = save_counter(f.branches[0], key, CounterSave.model_validate(payload(config=config)),
            db, f.context, SimpleNamespace(id=f.actor))
    with f.factory.begin() as reader:
        assert counter_stock_area(reader, f.context, branch_id=f.branches[0],
            counter_id=counter.id, expected_version=1)[0].id == f.locations[0]
        with f.factory.begin() as writer:
            writer.execute(text("SET LOCAL lock_timeout = '150ms'"))
            with pytest.raises(DBAPIError) as failed:
                writer.query(InventoryBranch).filter_by(id=f.branches[0]).with_for_update().one()
            assert failed.value.orig.pgcode == '55P03'
            writer.rollback()
    with f.factory() as writer:
        updated = save_counter(f.branches[0], key,
            CounterSave.model_validate(payload(expected_version=1, config={**config, 'is_enabled':False})),
            writer, f.context, SimpleNamespace(id=f.actor))
        assert updated.version == 2
