"""Actual router and PostgreSQL constraints, all inside rollback-only test data."""
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import Model
from Model.db import Base
from Model.Credentials.Organisation import Organisation
from Model.Credentials.users import User
from Model.containermgmt.Inventory.Location import InventoryBranch, StockLocation
from Utils.org_filter import OrgContext
from auth.module_guard import require_module
from auth.policy import AccessPolicy


@pytest.fixture
def locations(test_engine, monkeypatch):
    # Legacy tests temporarily stub auth modules during collection; defer router
    # import until collection has restored their real dependency implementations.
    from Routes.Inventory.LocationRouter import LocationRouter
    from Routes.Inventory.CostPoolRouter import CostPoolRouter
    from Routes.Inventory.CostEvidenceRouter import CostEvidenceRouter
    from Routes.Inventory.PolicyDraftRouter import PolicyDraftRouter
    from Routes.Inventory.BranchSettingsRouter import BranchSettingsRouter
    from Routes.Inventory.BranchCounterRouter import BranchCounterRouter
    from Routes.Inventory.ManagerCaseRouter import ManagerCaseRouter
    from Routes.Inventory.UnitBarcodeRouter import UnitBarcodeRouter
    from Routes.Inventory.BarcodeRetirementRouter import BarcodeRetirementRouter
    with test_engine.begin() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS usercredentials"))
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS containermgmt"))
        Base.metadata.create_all(conn)
    # Upgrade pre-existing isolated databases before opening rollback-only DML.
    # CREATE TRIGGER needs a table lock and must not race this fixture's writes.
    import Utils.migrate_20261002_policy_activation as activation_migration
    monkeypatch.setattr(activation_migration, "engine", test_engine)
    activation_migration.ensure_policy_activation_schema()
    connection = test_engine.connect()
    transaction = connection.begin()
    db = Session(bind=connection, join_transaction_mode="create_savepoint")
    key = uuid4().hex
    a, b = Organisation(name="Locations A " + key), Organisation(name="Locations B " + key)
    db.add_all([a, b])
    db.flush()
    user_record = User(username="loc-" + key, password_hash="test-only-unusable", org_id=a.id)
    db.add(user_record)
    db.flush()
    own = InventoryBranch(org_id=a.id, code="MAIN", name="Main", kind="WAREHOUSE")
    foreign = InventoryBranch(org_id=b.id, code="OTHER", name="Other", kind="STORE")
    db.add_all([own, foreign])
    db.flush()
    # Release the seed savepoint inside the outer rollback-only transaction.
    # A rejected endpoint must not roll back the test fixture itself.
    db.commit()
    ctx = OrgContext(current_org_id=a.id, allowed_org_ids=[a.id], is_root=False)
    user = SimpleNamespace(id=user_record.id, roles=[])
    user.access_policy = AccessPolicy(user=user, org_ids=(a.id,),
        permission_names=frozenset({"View_Product", "Edit_Product", "Manage_InventoryLocation", "Manage_InventoryCostPool", "Manage_BranchSettings", "Request_InventoryReview", "Review_InventoryPolicy", "Activate_InventoryPolicy", "Manage_InventoryBarcode"}),
        module_names=frozenset({"INVENTORY"}), field_permissions={})
    app = FastAPI()
    app.include_router(LocationRouter, dependencies=[Depends(require_module("INVENTORY"))])
    app.include_router(CostPoolRouter, dependencies=[Depends(require_module("INVENTORY"))])
    app.include_router(CostEvidenceRouter)
    app.include_router(PolicyDraftRouter, dependencies=[Depends(require_module("INVENTORY"))])
    app.include_router(BranchSettingsRouter, dependencies=[Depends(require_module("INVENTORY"))])
    app.include_router(BranchCounterRouter, dependencies=[Depends(require_module("INVENTORY"))])
    app.include_router(ManagerCaseRouter, dependencies=[Depends(require_module("INVENTORY"))])
    app.include_router(UnitBarcodeRouter, dependencies=[Depends(require_module("INVENTORY"))])
    app.include_router(BarcodeRetirementRouter, dependencies=[Depends(require_module("INVENTORY"))])
    replacements = {"get_db": lambda: db, "get_current_user": lambda: user,
        "get_org_context": lambda: ctx, "get_request_policy": lambda: user.access_policy}
    user_dependencies = set()

    def override(dependant):
        for dependency in dependant.dependencies:
            name = getattr(dependency.call, "__name__", "")
            if name in replacements and getattr(dependency.call, "__module__", "").startswith(("auth.", "Model.db")):
                app.dependency_overrides[dependency.call] = replacements[name]
                if name == "get_current_user":
                    user_dependencies.add(dependency.call)
            override(dependency)

    for route in app.routes:
        if hasattr(route, "dependant"):
            override(route.dependant)
    fixture = SimpleNamespace(db=db, context=ctx, user=user, own=own.id, foreign=foreign.id,
        org_a=a.id, org_b=b.id, app=app, user_dependencies=user_dependencies)
    try:
        with TestClient(app) as client:
            fixture.client = client
            yield fixture
    finally:
        db.close()
        transaction.rollback()
        connection.close()


def site(client, branch, code="SITE"):
    return client.post(f"/inventory/branches/{branch}/locations", json={"code": code, "name": "Test site", "kind": "SITE"})


def test_create_branch_is_owned_by_active_context(locations):
    f = locations
    response = f.client.post("/inventory/branches", json={"code": " praslin ", "name": "Praslin", "kind": "STORE"})
    assert response.status_code == 201
    assert response.json()["code"] == "PRASLIN" and response.json()["org_id"] == f.org_a
    row = f.db.get(InventoryBranch, response.json()["id"])
    assert row.created_by == f.user.id


def test_paginated_branches_never_return_foreign_org(locations):
    f = locations
    response = f.client.get("/inventory/branches?limit=1")
    assert response.status_code == 200 and response.json()["total"] == 1
    assert response.json()["items"][0]["id"] == f.own
    assert f.client.get("/inventory/branches?page=2&limit=1").json()["items"] == []


def test_site_zone_bin_creation_and_pagination(locations):
    f = locations
    root = site(f.client, f.own)
    assert root.status_code == 201
    parent = root.json()["id"]
    for code, kind in [("Z1", "ZONE"), ("B1", "BIN")]:
        response = f.client.post(f"/inventory/branches/{f.own}/locations", json={
            "code": code, "name": code, "kind": kind, "parent_id": parent})
        assert response.status_code == 201
        parent = response.json()["id"]
    response = f.client.get(f"/inventory/branches/{f.own}/locations?limit=2")
    assert response.json()["total"] == 3 and response.json()["pages"] == 2
    assert len(response.json()["items"]) == 2


@pytest.mark.parametrize("method,suffix", [("get", ""), ("post", ""), ("get", "/{id}/locations"), ("post", "/{id}/locations")])
@pytest.mark.parametrize("denial", ["anonymous", "permission", "module"])
def test_every_route_enforces_access(locations, method, suffix, denial):
    f = locations
    if denial == "anonymous":
        for dependency in f.user_dependencies:
            f.app.dependency_overrides.pop(dependency)
    else:
        f.user.access_policy = AccessPolicy(user=f.user, org_ids=(f.org_a,),
            permission_names=frozenset() if denial == "permission" else frozenset({"View_Product", "Manage_InventoryLocation"}),
            module_names=frozenset({"INVENTORY"}) if denial == "permission" else frozenset(), field_permissions={})
    path = "/inventory/branches" + suffix.format(id=f.own)
    kwargs = {"json": {"code": "X", "name": "X", "kind": "SITE" if suffix else "STORE"}} if method == "post" else {}
    assert getattr(f.client, method)(path, **kwargs).status_code == (401 if denial == "anonymous" else 403)


def test_foreign_branch_hidden_for_read_and_write(locations):
    f = locations
    assert f.client.get(f"/inventory/branches/{f.foreign}/locations").status_code == 404
    assert site(f.client, f.foreign).status_code == 404


def test_org_spoofing_and_duplicate_code_are_rejected(locations):
    f = locations
    payload = {"code": "MAIN", "name": "Duplicate", "kind": "STORE"}
    assert f.client.post("/inventory/branches", json={**payload, "org_id": f.org_b}).status_code == 422
    assert f.client.post("/inventory/branches", json=payload).status_code == 409
    assert site(f.client, f.own).status_code == 201
    assert site(f.client, f.own, "site").status_code == 409


def test_parent_cannot_be_from_other_branch_even_with_multi_org_access(locations):
    f = locations
    foreign = StockLocation(org_id=f.org_b, branch_id=f.foreign, code="SITE", name="Foreign", kind="SITE")
    f.db.add(foreign)
    f.db.flush()
    f.context.allowed_org_ids = [f.org_a, f.org_b]
    response = f.client.post(f"/inventory/branches/{f.own}/locations", json={
        "code": "ZONE", "name": "Wrong parent", "kind": "ZONE", "parent_id": foreign.id})
    assert response.status_code == 404


def test_database_rejects_cross_org_branch_fk(locations):
    f = locations
    with pytest.raises(IntegrityError), f.db.begin_nested():
        f.db.add(StockLocation(org_id=f.org_b, branch_id=f.own, code="BAD", name="Invalid", kind="SITE"))
        f.db.flush()


def test_database_rejects_cross_branch_parent_fk(locations):
    f = locations
    parent = StockLocation(org_id=f.org_a, branch_id=f.own, code="SITE", name="Own", kind="SITE")
    f.db.add(parent)
    f.db.flush()
    with pytest.raises(IntegrityError), f.db.begin_nested():
        f.db.add(StockLocation(org_id=f.org_b, branch_id=f.foreign, parent_id=parent.id, code="BAD", name="Invalid", kind="ZONE"))
        f.db.flush()


def test_hierarchy_and_inactive_parent_are_rejected(locations):
    f = locations
    root = site(f.client, f.own).json()
    url = f"/inventory/branches/{f.own}/locations"
    assert f.client.post(url, json={"code": "BIN", "name": "Invalid", "kind": "BIN", "parent_id": root["id"]}).status_code == 409
    assert f.client.post(url, json={"code": "ZONE", "name": "Invalid", "kind": "ZONE"}).status_code == 422
    f.db.get(StockLocation, root["id"]).is_active = False
    f.db.flush()
    assert f.client.post(url, json={"code": "ZONE", "name": "Invalid", "kind": "ZONE", "parent_id": root["id"]}).status_code == 409


def test_migration_replay_preserves_master_rows(locations, monkeypatch, test_engine):
    from Utils import migrate_20261002_inventory_locations as migration
    monkeypatch.setattr(migration, "engine", test_engine)
    migration.ensure_inventory_locations_schema()
    migration.ensure_inventory_locations_schema()
    assert locations.db.get(InventoryBranch, locations.own).code == "MAIN"
