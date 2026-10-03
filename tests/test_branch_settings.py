from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4
import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from Model.containermgmt.Inventory.BranchSettings import BranchSettingsRevision
from Schema.BranchSettingsSchema import BranchSettingsSave
from auth.policy import AccessPolicy
from tests.test_inventory_locations import locations  # noqa: F401
from tests.test_stock_ledger import stock  # noqa: F401


def payload(**changes):
    return {"operation_key": str(uuid4()), "expected_version": 0, "config": {
        "timezone_name": "Indian/Mahe", "weekday_cutoff": "04:00", "weekend_cutoff": "06:00",
        "trading_weekdays": [0, 1, 2, 3, 4, 5], "date_overrides": []}, **changes}


def url(f, branch=None):
    return f"/inventory/branches/{branch or f.own}/settings"


def test_empty_incomplete_and_configured_revisions_do_not_activate_checkout(locations):
    f = locations
    initial = f.client.get(url(f)).json()
    assert initial["status"] == "NOT_CONFIGURED" and len(initial["missing_fields"]) == 4
    first = f.client.put(url(f), json=payload(config={}))
    assert first.status_code == 200 and first.json()["status"] == "INCOMPLETE"
    complete = f.client.put(url(f), json=payload(expected_version=1)).json()
    assert complete["status"] == "CONFIGURED" and complete["version"] == 2
    assert not complete["operational_activation"]


def test_stable_retry_key_and_stale_or_changed_intent_conflicts(locations):
    f = locations
    data = payload()
    first = f.client.put(url(f), json=data)
    assert first.status_code == 200
    assert f.client.put(url(f), json=data).json() == first.json()
    assert f.client.put(url(f), json=payload()).status_code == 409
    assert f.client.put(url(f), json={**data, "config": {}}).status_code == 409
    assert f.client.put(url(f), json=payload(expected_version=1)).status_code == 200
    assert f.client.put(url(f), json=data).json()["version"] == 1
    assert f.client.get(url(f)).json()["version"] == 2


@pytest.mark.parametrize("method", ["get", "put"])
@pytest.mark.parametrize("denial", ["anonymous", "permission", "module"])
def test_access_guards(locations, method, denial):
    f = locations
    if denial == "anonymous":
        for dependency in f.user_dependencies:
            f.app.dependency_overrides.pop(dependency)
    else:
        f.user.access_policy = AccessPolicy(user=f.user, org_ids=(f.org_a,), field_permissions={},
            permission_names=frozenset() if denial == "permission" else frozenset({"View_Product", "Manage_BranchSettings"}),
            module_names=frozenset({"INVENTORY"}) if denial == "permission" else frozenset())
    kwargs = {"json": payload()} if method == "put" else {}
    assert getattr(f.client, method)(url(f), **kwargs).status_code == (401 if denial == "anonymous" else 403)


def test_foreign_branch_and_forged_org_are_denied(locations):
    f = locations
    assert f.client.get(url(f, f.foreign)).status_code == 404
    assert f.client.put(url(f, f.foreign), json=payload()).status_code == 404
    assert f.client.put(url(f), json=payload(org_id=f.org_b)).status_code == 422


@pytest.mark.parametrize("config", [{"timezone_name": "Unknown"}, {"weekday_cutoff": "25:00"},
    {"trading_weekdays": [True]}, {"trading_weekdays": [7]}, {"trading_weekdays": [1, 1]},
    {"date_overrides": [{"business_date": "2026-10-04", "is_open": True, "reason": ""}]},
    {"date_overrides": [{"business_date": "2026-10-04", "is_open": True, "reason": "Test"}] * 2}])
def test_invalid_settings_rejected(locations, config):
    assert locations.client.put(url(locations), json=payload(config=config)).status_code == 422


def test_same_operation_key_cannot_move_to_another_branch(locations):
    from Model.containermgmt.Inventory.Location import InventoryBranch
    f = locations
    row = InventoryBranch(org_id=f.org_a, code="SECOND", name="Second", kind="STORE")
    f.db.add(row); f.db.commit()
    data = payload()
    assert f.client.put(url(f), json=data).status_code == 200
    assert f.client.put(url(f, row.id), json=data).status_code == 409


def test_immutable_history_and_replayable_migration(locations, monkeypatch):
    import Utils.migrate_20261002_branch_settings as migration
    f = locations
    assert f.client.put(url(f), json=payload()).status_code == 200
    for sql in ["UPDATE containermgmt.inventory_branch_settings_revisions SET version=99 WHERE branch_id=:id",
                "DELETE FROM containermgmt.inventory_branch_settings_revisions WHERE branch_id=:id"]:
        with pytest.raises(DBAPIError):
            with f.db.begin_nested():
                f.db.execute(text(sql), {"id": f.own})
    # Same transaction connection avoids testing against uncommitted fixture rows.
    from contextlib import contextmanager
    @contextmanager
    def begin():
        with f.db.begin_nested():
            yield f.db.connection()
    monkeypatch.setattr(migration, "engine", SimpleNamespace(begin=begin))
    migration.ensure_branch_settings_schema(); migration.ensure_branch_settings_schema()
    assert f.client.get(url(f)).json()["version"] == 1


def test_real_concurrent_changes_have_one_winner(stock):
    from Routes.Inventory.BranchSettingsRouter import save_settings
    f = stock
    barrier = Barrier(2, timeout=10)
    def run(_):
        with f.factory() as db:
            barrier.wait()
            try:
                return save_settings(f.branches[0], BranchSettingsSave.model_validate(payload()),
                    db, f.context, SimpleNamespace(id=f.actor)).version
            except HTTPException as exc:
                return exc.status_code
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(run, range(2))) == [1, 409]
    with f.factory() as db:
        assert db.query(BranchSettingsRevision).filter_by(org_id=f.orgs[0]).count() == 1
