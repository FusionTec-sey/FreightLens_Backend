"""Scoped setup contracts; no production stock data is used or posted."""
import pytest
from sqlalchemy.exc import IntegrityError
from Model.containermgmt.Inventory.CostPool import InventoryCostPool, BranchCostPool
from auth.policy import AccessPolicy
from tests.test_inventory_locations import locations


def pool(f, code="MAHE"):
    response = f.client.post("/inventory/cost-pools", json={"code": code, "name": "Test pool"})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_pool_create_normalization_pagination_and_scope(locations):
    f = locations
    own = pool(f, " mahe ")
    foreign = InventoryCostPool(org_id=f.org_b, code="FOREIGN", name="Foreign")
    f.db.add(foreign); f.db.commit()
    result = f.client.get("/inventory/cost-pools?limit=1").json()
    assert result["total"] == 1 and result["items"][0]["code"] == "MAHE"
    assert result["items"][0]["org_id"] == f.org_a
    assert f.db.get(InventoryCostPool, own).created_by == f.user.id
    assert f.client.get("/inventory/cost-pools?page=2&limit=1").json()["items"] == []
    assert f.client.get("/inventory/cost-pools?limit=101").status_code == 422
    assert f.client.post("/inventory/cost-pools", json={"code": "MAHE", "name": "Duplicate"}).status_code == 409
    assert f.client.post("/inventory/cost-pools", json={"code": "X", "name": "X", "org_id": f.org_b}).status_code == 422


def test_initial_assignment_same_retry_and_no_reassignment(locations):
    f = locations
    a, b = pool(f), pool(f, "PRASLIN")
    url = f"/inventory/branches/{f.own}/cost-pool"
    assert f.client.get(url).json() is None
    first = f.client.put(url, json={"cost_pool_id": a})
    assert first.status_code == 200
    assert f.client.put(url, json={"cost_pool_id": a}).json() == first.json()
    assert f.client.put(url, json={"cost_pool_id": b}).status_code == 409
    assert f.client.get(url).json()["cost_pool_id"] == a
    assert f.db.query(BranchCostPool).filter_by(branch_id=f.own).count() == 1


def test_pool_page_shows_latest_authority_without_private_node_data(locations):
    from uuid import uuid4
    from Model.containermgmt.Inventory.PostingAuthority import StoreNode, CostPoolAuthorityEpoch
    f = locations; key = pool(f)
    initial = f.client.get('/inventory/cost-pools').json()['items'][0]
    assert initial['central_authority_state'] == 'NOT_CONFIGURED'
    assert initial['central_authority_epoch'] is None
    node = StoreNode(org_id=f.org_a, node_key=uuid4(), created_by=f.user.id)
    f.db.add(node); f.db.flush()
    for epoch, state in [(1, 'ACTIVE'), (2, 'SUSPENDED')]:
        f.db.add(CostPoolAuthorityEpoch(org_id=f.org_a, cost_pool_id=key, node_id=node.id,
            epoch=epoch, state=state, reason='Private synthetic reason', created_by=f.user.id))
        f.db.commit()
        response = f.client.get('/inventory/cost-pools?limit=1')
        result = response.json()['items'][0]
        assert result['central_authority_state'] == state
        assert result['central_authority_epoch'] == epoch
        assert 'node_key' not in result and 'node_id' not in result and 'reason' not in result
        assert 'Private synthetic reason' not in response.text
    assert f.client.get('/inventory/cost-pools?page=2&limit=1').json()['items'] == []


def test_multiple_branches_can_share_pool(locations):
    f = locations
    p = pool(f)
    branch = f.client.post("/inventory/branches", json={"code": "SECOND", "name": "Second", "kind": "WAREHOUSE"}).json()["id"]
    for b in [f.own, branch]:
        assert f.client.put(f"/inventory/branches/{b}/cost-pool", json={"cost_pool_id": p}).status_code == 200


def test_foreign_branch_and_foreign_pool_are_hidden_even_with_both_orgs_allowed(locations):
    f = locations
    p = pool(f)
    foreign = InventoryCostPool(org_id=f.org_b, code="FOREIGN", name="Foreign")
    f.db.add(foreign); f.db.commit()
    foreign_id = foreign.id
    assert f.client.get(f"/inventory/branches/{f.foreign}/cost-pool").status_code == 404
    assert f.client.put(f"/inventory/branches/{f.foreign}/cost-pool", json={"cost_pool_id": p}).status_code == 404
    f.context.allowed_org_ids.append(f.org_b)
    assert f.client.put(f"/inventory/branches/{f.own}/cost-pool", json={"cost_pool_id": foreign_id}).status_code == 404


@pytest.mark.parametrize("method,path,payload", [
    ("get", "/inventory/cost-pools", None),
    ("post", "/inventory/cost-pools", {"code": "NEW", "name": "New"}),
    ("get", "/inventory/branches/{id}/cost-pool", None),
    ("put", "/inventory/branches/{id}/cost-pool", {"cost_pool_id": 1}),
])
@pytest.mark.parametrize("denial", ["anonymous", "permission", "module"])
def test_all_routes_deny_missing_access(locations, method, path, payload, denial):
    f = locations
    if denial == "anonymous":
        for dep in f.user_dependencies:
            f.app.dependency_overrides.pop(dep)
    else:
        f.user.access_policy = AccessPolicy(user=f.user, org_ids=(f.org_a,),
            permission_names=frozenset() if denial == "permission" else frozenset({"View_Product", "Manage_InventoryCostPool"}),
            module_names=frozenset({"INVENTORY"}) if denial == "permission" else frozenset(), field_permissions={})
    response = getattr(f.client, method)(path.format(id=f.own), **({"json": payload} if payload else {}))
    assert response.status_code == (401 if denial == "anonymous" else 403)


@pytest.mark.parametrize("inactive", ["branch", "pool", "deleted_pool"])
def test_inactive_or_deleted_records_cannot_be_assigned(locations, inactive):
    from Model.containermgmt.Inventory.Location import InventoryBranch
    f = locations
    p = pool(f)
    if inactive == "branch":
        f.db.get(InventoryBranch, f.own).is_active = False
    elif inactive == "pool":
        f.db.get(InventoryCostPool, p).is_active = False
    else:
        f.db.get(InventoryCostPool, p).is_deleted = True
    f.db.commit()
    assert f.client.put(f"/inventory/branches/{f.own}/cost-pool", json={"cost_pool_id": p}).status_code == (404 if inactive == "deleted_pool" else 409)


def test_database_rejects_cross_org_binding_and_second_pool(locations):
    f = locations
    foreign = InventoryCostPool(org_id=f.org_b, code="FOREIGN", name="Foreign")
    f.db.add(foreign); f.db.commit()
    foreign_id = foreign.id
    with pytest.raises(IntegrityError):
        with f.db.begin_nested():
            f.db.add(BranchCostPool(org_id=f.org_a, branch_id=f.own, cost_pool_id=foreign_id)); f.db.flush()
    p = pool(f)
    with pytest.raises(IntegrityError):
        with f.db.begin_nested():
            f.db.add(BranchCostPool(org_id=f.org_b, branch_id=f.own, cost_pool_id=foreign_id)); f.db.flush()
    assert f.client.put(f"/inventory/branches/{f.own}/cost-pool", json={"cost_pool_id": p}).status_code == 200
    with pytest.raises(IntegrityError):
        with f.db.begin_nested():
            f.db.add(BranchCostPool(org_id=f.org_a, branch_id=f.own, cost_pool_id=p)); f.db.flush()


def test_migration_replay_preserves_bindings(locations, monkeypatch):
    import Utils.migrate_20261002_inventory_cost_pools as migration
    from contextlib import contextmanager
    from types import SimpleNamespace
    f = locations
    p = pool(f)
    f.client.put(f"/inventory/branches/{f.own}/cost-pool", json={"cost_pool_id": p})
    @contextmanager
    def begin():
        yield f.db.connection()
    monkeypatch.setattr(migration, "engine", SimpleNamespace(begin=begin))
    migration.ensure_inventory_cost_pools_schema(); migration.ensure_inventory_cost_pools_schema()
    assert f.client.get(f"/inventory/branches/{f.own}/cost-pool").json()["cost_pool_id"] == p


@pytest.mark.parametrize("same_pool", [True, False])
def test_concurrent_initial_assignment_serializes(test_engine, same_pool):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from uuid import uuid4
    from types import SimpleNamespace
    from fastapi import HTTPException
    from sqlalchemy.orm import Session
    from Model.db import Base
    from Model.Credentials.Organisation import Organisation
    from Model.Credentials.users import User
    from Model.containermgmt.Inventory.Location import InventoryBranch
    from Schema.InventoryCostPoolSchema import BranchCostPoolAssign
    from Routes.Inventory.CostPoolRouter import assign_branch_cost_pool
    from Utils.org_filter import OrgContext
    # Synthetic committed rows in the dedicated test database permit two actual
    # connections. No business records or schemas are reset or deleted.
    with test_engine.begin() as conn:
        Base.metadata.create_all(conn)
    with Session(test_engine) as db:
        key = uuid4().hex
        org = Organisation(name="Pool concurrency " + key)
        db.add(org); db.flush()
        user = User(username="pool-" + key, password_hash="test-only-unusable", org_id=org.id)
        branch = InventoryBranch(org_id=org.id, code="MAIN", name="Main", kind="WAREHOUSE")
        pools = [InventoryCostPool(org_id=org.id, code=code, name=code) for code in ["A", "B"]]
        db.add_all([user, branch, *pools]); db.commit()
        org_id, branch_id, user_id = org.id, branch.id, user.id
        ids = [pools[0].id, pools[0 if same_pool else 1].id]
    barrier = Barrier(2, timeout=10)
    def assign(pool_id):
        with Session(test_engine) as db:
            barrier.wait()
            try:
                result = assign_branch_cost_pool(branch_id, BranchCostPoolAssign(cost_pool_id=pool_id), db,
                    OrgContext(current_org_id=org_id, allowed_org_ids=[org_id], is_root=False), SimpleNamespace(id=user_id))
                return 200, result.id
            except HTTPException as error:
                return error.status_code, None
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(assign, ids))
    assert sorted(status for status, _ in results) == ([200, 200] if same_pool else [200, 409])
    if same_pool:
        assert results[0][1] == results[1][1]
    with Session(test_engine) as db:
        assert db.query(BranchCostPool).filter_by(branch_id=branch_id).count() == 1
