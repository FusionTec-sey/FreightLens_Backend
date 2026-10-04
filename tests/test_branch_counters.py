from datetime import datetime, timezone
from uuid import uuid4
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from auth.policy import AccessPolicy
from Services.branch_action_context_service import require_branch_action_context
from tests.test_inventory_locations import locations  # noqa: F401
from tests.test_branch_settings import payload as settings_payload
from tests.test_stock_ledger import stock  # noqa: F401


def payload(**changes):
    return {"code": "TILL1", "expected_version": 0, "operation_key": str(uuid4()),
            "config": {"name": "Synthetic counter", "purpose": "BOTH", "is_enabled": False}, **changes}


def base(f, branch=None):
    return f"/inventory/branches/{branch or f.own}/counters"


def test_counter_default_area_is_scoped_versioned_and_never_falls_back(locations):
    from Model.containermgmt.Inventory.Location import StockLocation
    from Services.branch_action_context_service import BranchActionContext
    from Services.default_stock_area_service import require_default_stock_area
    from Services.branch_business_date_service import MissingBranchConfiguration
    from datetime import date
    f = locations
    own = StockLocation(org_id=f.org_a, branch_id=f.own, code='AREA', name='Synthetic work area', kind='SITE')
    foreign = StockLocation(org_id=f.org_b, branch_id=f.foreign, code='AREA', name='Foreign area', kind='SITE')
    f.db.add_all([own, foreign]); f.db.commit()
    key = uuid4(); body = payload(); body['config']['default_stock_location_id'] = foreign.id
    assert f.client.put(f'{base(f)}/{key}', json=body).status_code == 404
    body['config']['default_stock_location_id'] = own.id
    first = f.client.put(f'{base(f)}/{key}', json=body)
    assert first.status_code == 200, first.text
    assert first.json()['config']['default_stock_location_id'] == own.id
    assert f.client.put(f'{base(f)}/{key}', json=body).json() == first.json()
    second = payload(expected_version=1, config={**body['config'], 'is_enabled': True})
    assert f.client.put(f'{base(f)}/{key}', json=second).status_code == 200
    context = BranchActionContext(f.own, first.json()['id'], 1, 2, date(2026, 10, 3), 'CHECKOUT')
    with f.db.begin_nested():
        assert require_default_stock_area(f.db, f.context, context).id == own.id
    cleared = payload(expected_version=2, config={**second['config'], 'default_stock_location_id': None})
    assert f.client.put(f'{base(f)}/{key}', json=cleared).status_code == 200
    with f.db.begin_nested(), pytest.raises(MissingBranchConfiguration, match='changed'):
        require_default_stock_area(f.db, f.context, context)
    from dataclasses import replace
    with f.db.begin_nested():
        assert require_default_stock_area(f.db, f.context, replace(context, counter_settings_version=3)) is None


def test_counter_identity_revisions_retry_and_pagination(locations):
    f = locations
    key = uuid4(); data = payload(); url = f"{base(f)}/{key}"
    first = f.client.put(url, json=data)
    assert first.status_code == 200 and first.json()["version"] == 1
    assert not first.json()["operational_activation"]
    assert f.client.put(url, json=data).json() == first.json()
    assert f.client.put(url, json=payload()).status_code == 409
    assert f.client.put(url, json=payload(expected_version=1, code="CHANGED")).status_code == 409
    updated = payload(expected_version=1, config={"name": "Renamed", "purpose": "COLLECTION"})
    assert f.client.put(url, json=updated).json()["version"] == 2
    assert f.client.put(f"{base(f)}/{uuid4()}", json=payload(code="TILL2")).status_code == 200
    page = f.client.get(base(f), params={"page": 1, "limit": 1}).json()
    assert page["total"] == 2 and page["pages"] == 2 and page["items"][0]["config"]["name"] == "Renamed"


@pytest.mark.parametrize("method", ["get", "put"])
@pytest.mark.parametrize("denial", ["anonymous", "permission", "module"])
def test_counter_guards(locations, method, denial):
    f = locations
    if denial == "anonymous":
        for dependency in f.user_dependencies:
            f.app.dependency_overrides.pop(dependency)
    else:
        f.user.access_policy = AccessPolicy(user=f.user, org_ids=(f.org_a,), field_permissions={},
            permission_names=frozenset() if denial == "permission" else frozenset({"View_Product", "Manage_BranchSettings"}),
            module_names=frozenset({"INVENTORY"}) if denial == "permission" else frozenset())
    url = base(f) + (f"/{uuid4()}" if method == "put" else "")
    assert getattr(f.client, method)(url, **({"json": payload()} if method == "put" else {})).status_code == (401 if denial == "anonymous" else 403)


def test_foreign_scope_code_conflict_and_invalid_configuration(locations):
    f = locations
    assert f.client.get(base(f, f.foreign)).status_code == 404
    assert f.client.put(f"{base(f, f.foreign)}/{uuid4()}", json=payload()).status_code == 404
    assert f.client.put(f"{base(f)}/{uuid4()}", json=payload()).status_code == 200
    assert f.client.put(f"{base(f)}/{uuid4()}", json=payload()).status_code == 409
    assert f.client.put(f"{base(f)}/{uuid4()}", json=payload(config={"name": "X", "purpose": "UNKNOWN"})).status_code == 422


def test_counter_history_is_immutable(locations):
    f = locations
    assert f.client.put(f"{base(f)}/{uuid4()}", json=payload()).status_code == 200
    for table in ("inventory_branch_counters", "inventory_counter_settings_revisions"):
        with pytest.raises(DBAPIError):
            with f.db.begin_nested():
                f.db.execute(text(f"UPDATE containermgmt.{table} SET is_deleted=true WHERE org_id=:org"), {"org": f.org_a})


@pytest.mark.parametrize("same_key", [True, False])
def test_competing_counter_creation_and_migration_replay(stock, test_engine, monkeypatch, same_key):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from types import SimpleNamespace
    from fastapi import HTTPException
    from Routes.Inventory.BranchCounterRouter import save_counter
    from Schema.BranchCounterSchema import CounterSave
    from Model.containermgmt.Inventory.BranchCounter import BranchCounter, CounterSettingsRevision
    import Utils.migrate_20261002_branch_counters as migration
    f = stock
    key = uuid4(); first = payload()
    requests = [first, first if same_key else payload()]
    barrier = Barrier(2, timeout=10)
    def run(data):
        with f.factory() as db:
            barrier.wait()
            try:
                return save_counter(f.branches[0], key, CounterSave.model_validate(data), db,
                                    f.context, SimpleNamespace(id=f.actor)).version
            except HTTPException as exc:
                return exc.status_code
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(run, requests)) == ([1, 1] if same_key else [1, 409])
    monkeypatch.setattr(migration, "engine", test_engine)
    migration.ensure_branch_counters_schema(); migration.ensure_branch_counters_schema()
    with f.factory() as db:
        assert db.query(BranchCounter).filter_by(org_id=f.orgs[0]).count() == 1
        assert db.query(CounterSettingsRevision).filter_by(org_id=f.orgs[0]).count() == 1


@pytest.mark.parametrize("failure", [None, "disabled", "purpose", "branch_version", "counter_version", "closed", "collection_closed", "missing"])
def test_action_context_uses_versioned_settings_and_separate_collection_rules(locations, failure):
    f = locations
    settings = settings_payload()
    if failure in ("closed", "collection_closed"):
        settings["config"]["trading_weekdays"] = []
    if failure == "missing":
        settings["config"] = {}
    assert f.client.put(f"/inventory/branches/{f.own}/settings", json=settings).status_code == 200
    key = uuid4()
    counter = payload(config={"name": "Counter", "purpose": "COLLECTION" if failure == "purpose" else "BOTH",
                              "is_enabled": failure != "disabled"})
    assert f.client.put(f"{base(f)}/{key}", json=counter).status_code == 200
    def run():
        with f.db.begin_nested():
            return require_branch_action_context(f.db, f.context, branch_id=f.own, counter_key=key,
                branch_version=2 if failure == "branch_version" else 1,
                counter_version=2 if failure == "counter_version" else 1,
                instant=datetime(2026, 10, 3, 8, tzinfo=timezone.utc),
                action="COLLECTION" if failure == "collection_closed" else "CHECKOUT", authorize=lambda db: None)
    if failure not in (None, "collection_closed"):
        with pytest.raises((ValueError, PermissionError)):
            run()
    else:
        assert run().business_date.isoformat() == "2026-10-03"
