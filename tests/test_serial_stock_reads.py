from uuid import uuid4
import pytest
from sqlalchemy import event
from Model.containermgmt.Orders.Product import Product
from Model.containermgmt.Inventory.StockLedger import StockBalance
from Model.containermgmt.Inventory.StockSerial import StockSerialIdentity, StockSerialPosition
from Schema.InventoryPolicySchema import InventoryPolicyConfig
from auth.policy import AccessPolicy
from tests.test_inventory_locations import locations, site


@pytest.fixture
def register(locations):
    f = locations
    f.location = site(f.client, f.own).json()["id"]
    product = Product(org_id=f.org_a, sku="SERIAL-TEST", name="Serial product", unit="PCS")
    f.db.add(product); f.db.flush(); f.product = product
    policy = InventoryPolicyConfig(base_unit="PCS", quantity_step="1", tracking="SERIAL")
    balance = StockBalance(org_id=f.org_a, branch_id=f.own, location_id=f.location, product_id=product.id,
        base_unit="PCS", tracking_policy="SERIAL", policy_config=policy.model_dump(mode="json"), quantity_step=1,
        on_hand=3, reserved=1, damaged=1, quarantined=0, version=1, created_by=f.user.id)
    f.db.add(balance); f.db.flush(); f.balance = balance
    for number, condition in [("ABC-1", "AVAILABLE"), ("ABC-2", "AVAILABLE"), ("ABC-3", "DAMAGED")]:
        identity = StockSerialIdentity(org_id=f.org_a, product_id=product.id, serial_key=uuid4(), serial_number=number, created_by=f.user.id)
        f.db.add(identity); f.db.flush()
        f.db.add(StockSerialPosition(org_id=f.org_a, product_id=product.id, serial_id=identity.id,
            balance_id=balance.id, condition=condition, created_by=f.user.id))
    f.db.commit()
    f.url = f"/inventory/branches/{f.own}/locations/{f.location}/stock/{balance.id}/serials"
    return f


def test_scoped_paginated_serials_do_not_fetch_supplier_or_cost_data(register):
    f = register; queries = []
    def capture(conn, cursor, statement, parameters, context, executemany): queries.append(statement.lower())
    event.listen(f.db.bind, "before_cursor_execute", capture)
    try:
        response = f.client.get(f.url + "?limit=2")
    finally:
        event.remove(f.db.bind, "before_cursor_execute", capture)
    assert response.status_code == 200
    result = response.json()
    assert result["total"] == 3 and result["pages"] == 2
    assert [row["serial_number"] for row in result["items"]] == ["ABC-1", "ABC-2"]
    assert all(row["condition"] == "AVAILABLE" for row in result["items"])  # no assignment by reservation
    assert not any("supplier" in q or "unit_cost" in q for q in queries)
    assert f.client.get(f.url + "?page=2&limit=2").json()["items"][0]["condition"] == "DAMAGED"
    assert f.client.get(f.url + "?page=3&limit=2").json()["items"] == []
    assert f.client.get(f.url + "?limit=101").status_code == 422
    assert f.client.get(f"/inventory/branches/{f.own}/locations/{f.location}/stock").json()["items"][0]["tracking_policy"] == "SERIAL"


@pytest.mark.parametrize("denial", ["anonymous", "permission", "module"])
def test_serial_read_guards(register, denial):
    f = register
    if denial == "anonymous":
        for dependency in f.user_dependencies: f.app.dependency_overrides.pop(dependency)
    else:
        f.user.access_policy = AccessPolicy(user=f.user, org_ids=(f.org_a,), field_permissions={},
            permission_names=frozenset() if denial == "permission" else frozenset({"View_Product"}),
            module_names=frozenset({"INVENTORY"}) if denial == "permission" else frozenset())
    assert f.client.get(f.url).status_code == (401 if denial == "anonymous" else 403)


def test_foreign_and_wrong_parent_scopes_have_no_fallback(register):
    f = register
    assert f.client.get(f.url.replace(f"branches/{f.own}/", f"branches/{f.foreign}/")).status_code == 404
    other_location = site(f.client, f.own, code="SECOND").json()["id"]
    assert f.client.get(f.url.replace(f"locations/{f.location}/", f"locations/{other_location}/")).status_code == 404
    f.context.current_org_id = f.org_b; f.context.allowed_org_ids = [f.org_b]
    assert f.client.get(f.url).status_code == 404


@pytest.mark.parametrize("field", ["is_shared", "is_deleted"])
def test_hidden_product_hides_serials(register, field):
    f = register
    setattr(f.product, field, True); f.db.commit()
    assert f.client.get(f.url).status_code == 404


def test_inactive_scope_is_reference_only_and_deleted_location_is_hidden(register):
    f = register
    f.product.status = "inactive"; f.db.commit()
    assert f.client.get(f.url).status_code == 200
    from Model.containermgmt.Inventory.Location import StockLocation
    f.db.get(StockLocation, f.location).is_deleted = True; f.db.commit()
    assert f.client.get(f.url).status_code == 404
