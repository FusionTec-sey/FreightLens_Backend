from uuid import uuid4
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from Model.containermgmt.Inventory.ProductPolicyActivation import ProductPolicyActivation
from Model.containermgmt.Inventory.ManagerCase import ManagerCaseUse
from auth.policy import AccessPolicy
from tests.test_policy_manager_cases import policy_cases, review_payload  # noqa: F401
from tests.test_inventory_policy_drafts import draft, config  # noqa: F401
from tests.test_inventory_locations import locations  # noqa: F401


@pytest.fixture
def activation(policy_cases):
    f = policy_cases
    # Explicit synthetic zero, not a migration of legacy preview quantities.
    f.product.current_stock = 0; f.db.commit()
    f.case = f.client.post(f.request_url, json=f.request_payload).json()["case_key"]
    f.user.id = f.reviewer
    assert f.client.post(f"/inventory/manager-cases/{f.case}/review", json=review_payload()).status_code == 200
    f.activate_url = f"/inventory/manager-cases/{f.case}/activate-policy"
    f.read_url = f"/inventory/products/{f.product.id}/inventory-policy"
    f.payload = {"operation_key": str(uuid4()), "expected_active_version": 0}
    return f


def test_approved_initial_activation_is_immutable_and_replay_safe(activation):
    f = activation
    assert f.client.get(f.read_url).json()["status"] == "NOT_ACTIVE"
    response = f.client.post(f.activate_url, json=f.payload)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "ACTIVE"
    assert f.client.post(f.activate_url, json=f.payload).json()["replayed"]
    assert f.client.get(f.read_url).json()["config"] == config(require_expiry=False, require_calibre=False)
    assert f.client.get("/inventory/manager-cases").json()["items"][0]["status"] == "CONSUMED"
    assert f.client.post(f.activate_url, json={**f.payload, "operation_key": str(uuid4())}).status_code == 409
    for table in ("inventory_product_policy_activations",):
        with pytest.raises(DBAPIError):
            with f.db.begin_nested():
                f.db.execute(text(f"DELETE FROM containermgmt.{table} WHERE org_id=:org"), {"org": f.org_a})


@pytest.mark.parametrize("quantity", [9, -1])
def test_legacy_stock_blocks_without_consuming_case(activation, quantity):
    f = activation; f.product.current_stock = quantity; f.db.commit()
    response = f.client.post(f.activate_url, json=f.payload)
    assert response.status_code == 409 and "reconciliation" in response.text
    assert f.db.query(ManagerCaseUse).filter_by(org_id=f.org_a).count() == 0
    assert f.db.query(ProductPolicyActivation).filter_by(org_id=f.org_a).count() == 0


def test_changed_draft_invalidates_activation_and_historical_retry(activation):
    f = activation
    assert f.client.post(f.activate_url, json=f.payload).status_code == 200
    assert f.client.put(f.url, json={"expected_version": 1, "config": config(quantity_step="0.1")}).status_code == 200
    assert f.client.post(f.activate_url, json=f.payload).status_code == 409
    # Historical activation remains unchanged, not overwritten by a new draft.
    assert f.client.get(f.read_url).json()["config"]["quantity_step"] == "1"


@pytest.mark.parametrize("route", ["read", "activate"])
@pytest.mark.parametrize("denial", ["anonymous", "permission", "module"])
def test_activation_route_guards(activation, route, denial):
    f = activation
    if denial == "anonymous":
        for dependency in f.user_dependencies: f.app.dependency_overrides.pop(dependency)
    else:
        f.user.access_policy = AccessPolicy(user=f.user, org_ids=(f.org_a,), field_permissions={},
            permission_names=frozenset() if denial == "permission" else frozenset({"View_Product", "Activate_InventoryPolicy"}),
            module_names=frozenset({"INVENTORY"}) if denial == "permission" else frozenset())
    response = f.client.get(f.read_url) if route == "read" else f.client.post(f.activate_url, json=f.payload)
    assert response.status_code == (401 if denial == "anonymous" else 403)


def test_foreign_and_unknown_sources_hidden(activation):
    f = activation
    assert f.client.get(f"/inventory/products/{f.foreign_product.id}/inventory-policy").status_code == 404
    assert f.client.post(f"/inventory/manager-cases/{uuid4()}/activate-policy", json=f.payload).status_code == 404


def test_unreviewed_case_cannot_activate(policy_cases):
    f = policy_cases; f.product.current_stock = 0; f.db.commit()
    case = f.client.post(f.request_url, json=f.request_payload).json()["case_key"]
    response = f.client.post(f"/inventory/manager-cases/{case}/activate-policy",
        json={"operation_key": str(uuid4()), "expected_active_version": 0})
    assert response.status_code == 403
    assert f.db.query(ProductPolicyActivation).filter_by(org_id=f.org_a).count() == 0


def test_activation_migration_replay(activation, monkeypatch, test_engine):
    import Utils.migrate_20261002_policy_activation as migration
    monkeypatch.setattr(migration, "engine", test_engine)
    migration.ensure_policy_activation_schema(); migration.ensure_policy_activation_schema()
    assert activation.client.post(activation.activate_url, json=activation.payload).status_code == 200


@pytest.mark.parametrize("value", [False, "0", -1])
def test_initial_activation_requires_exact_expected_version(activation, value):
    f = activation
    assert f.client.post(f.activate_url, json={**f.payload, "expected_active_version": value}).status_code == 422


def test_catalogue_guard_rejects_changed_units_or_totals_but_allows_same_values(activation):
    from types import SimpleNamespace
    from Services.policy_activation_service import require_catalogue_update_compatible
    from Services.inventory_posting_service import PostingConflict
    f = activation
    assert f.client.post(f.activate_url, json=f.payload).status_code == 200
    for change in ({"unit": "BOX"}, {"current_stock": 1}):
        with pytest.raises(PostingConflict):
            require_catalogue_update_compatible(f.db, f.context, f.product, SimpleNamespace(**change))
    require_catalogue_update_compatible(f.db, f.context, f.product, SimpleNamespace(unit="PCS", current_stock=0))


@pytest.mark.parametrize("assignment", ["unit='BOX'", "current_stock=10", "is_shared=true"])
def test_legacy_writers_cannot_override_activated_rules(activation, monkeypatch, test_engine, assignment):
    import Utils.migrate_20261002_policy_activation as migration
    monkeypatch.setattr(migration, "engine", test_engine)
    migration.ensure_policy_activation_schema()
    f = activation
    assert f.client.post(f.activate_url, json=f.payload).status_code == 200
    with pytest.raises(DBAPIError, match="Activated inventory requires"):
        with f.db.begin_nested():
            f.db.execute(text(f"UPDATE containermgmt.products SET {assignment} WHERE id=:id"), {"id": f.product.id})
