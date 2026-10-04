from decimal import Decimal as D
import pytest
from sqlalchemy import event
from auth.policy import AccessPolicy
from Model.containermgmt.Inventory.Location import StockLocation
from Model.containermgmt.Inventory.StockLedger import StockBalance, StockBatch
from Schema.InventoryPolicySchema import InventoryPolicyConfig
from datetime import date
from uuid import uuid4
from Model.containermgmt.Orders.Product import Product
from tests.test_inventory_locations import locations, site


def path(f, location):
    return f"/inventory/branches/{f.own}/locations/{location}/stock"


def seed(f, location, sku="TEST"):
    product = Product(org_id=f.org_a, sku=sku, name="Test product", unit="PCS", current_stock=D("999"))
    f.db.add(product); f.db.flush()
    balance = StockBalance(org_id=f.org_a, created_by=f.user.id, branch_id=f.own,
        location_id=location, product_id=product.id, base_unit="PCS", tracking_policy="UNTRACKED",
        on_hand=D("10.123456"), reserved=D("2"), damaged=D("1"), quarantined=D("0.123456"), version=1)
    f.db.add(balance); f.db.commit()
    return product


def test_scoped_exact_breakdown_pagination_and_no_sensitive_queries(locations):
    f = locations
    location = site(f.client, f.own).json()["id"]
    seed(f, location)
    seed(f, location, "SECOND")
    queries = []
    def capture(conn, cursor, statement, parameters, context, executemany):
        queries.append(statement.lower())
    event.listen(f.db.bind, "before_cursor_execute", capture)
    try:
        response = f.client.get(path(f, location) + "?limit=1")
    finally:
        event.remove(f.db.bind, "before_cursor_execute", capture)
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2 and data["pages"] == 2 and len(data["items"]) == 1
    row = data["items"][0]
    assert row["quantity_step"] is None and row["unit_policy_status"] == "REVIEW_REQUIRED"
    assert [row[k] for k in ("on_hand", "reserved", "available", "damaged", "quarantined")] == [
        "10.123456", "2.000000", "7.000000", "1.000000", "0.123456"]
    assert not any("supplier" in q or "unit_cost" in q or "current_stock" in q for q in queries)
    assert "org_id" not in row and "unit_cost" not in row
    assert f.client.get(path(f, location) + "?page=2&limit=1").json()["items"][0]["sku"] == "SECOND"
    assert f.client.get(path(f, location) + "?page=3&limit=1").json()["items"] == []
    assert f.client.get(path(f, location) + "?limit=101").status_code == 422


def test_batch_details_are_scoped_and_separate_per_lot(locations):
    f = locations
    location = site(f.client, f.own).json()["id"]
    product = Product(org_id=f.org_a, sku="LOTS", name="Synthetic tiles", unit="PCS")
    f.db.add(product); f.db.flush()
    rules = InventoryPolicyConfig(base_unit="PCS", quantity_step="1", tracking="BATCH", require_shade=True)
    for code, shade, qty in [("LOT-A", "A", 10), ("LOT-B", "B", 5)]:
        batch = StockBatch(batch_key=uuid4(), org_id=f.org_a, product_id=product.id, code=code,
            shade=shade, calibre="600", expires_on=date(2027, 1, 1), created_by=f.user.id)
        f.db.add(batch); f.db.flush()
        f.db.add(StockBalance(org_id=f.org_a, branch_id=f.own, location_id=location, product_id=product.id,
            base_unit="PCS", tracking_policy="BATCH", batch_key=batch.batch_key,
            policy_config=rules.model_dump(mode="json"), quantity_step=1,
            on_hand=qty, reserved=0, damaged=0, quarantined=0, version=1, created_by=f.user.id))
    f.db.commit()
    result = f.client.get(path(f, location)).json()
    assert result["total"] == 2
    assert [(row["batch_code"], row["batch_shade"], row["available"]) for row in result["items"]] == [
        ("LOT-A", "A", "10.000000"), ("LOT-B", "B", "5.000000")]
    for row in result["items"]:
        assert row["unit_policy_status"] == "SNAPSHOTTED" and row["quantity_step"] == "1.000000"
        assert row["expires_on"] == "2027-01-01" and row["batch_calibre"] == "600"


def test_product_filter_precedes_pagination(locations):
    f = locations; location = site(f.client, f.own).json()['id']
    first = seed(f, location); second = seed(f, location, 'SECOND')
    data = f.client.get(path(f, location)+f'?product_id={second.id}&limit=1').json()
    assert data['total'] == 1 and data['pages'] == 1
    assert data['items'][0]['product_id'] == second.id
    assert f.client.get(path(f, location)+f'?product_id={first.id}&page=2&limit=1').json()['items'] == []
    assert f.client.get(path(f, location)+'?product_id=0').status_code == 422


@pytest.mark.parametrize("denial", ["anonymous", "permission", "module"])
def test_stock_read_access_guards(locations, denial):
    f = locations
    location = site(f.client, f.own).json()["id"]
    if denial == "anonymous":
        for dependency in f.user_dependencies:
            f.app.dependency_overrides.pop(dependency)
    else:
        f.user.access_policy = AccessPolicy(user=f.user, org_ids=(f.org_a,), field_permissions={},
            permission_names=frozenset() if denial == "permission" else frozenset({"View_Product"}),
            module_names=frozenset({"INVENTORY"}) if denial == "permission" else frozenset())
    assert f.client.get(path(f, location)).status_code == (401 if denial == "anonymous" else 403)


def test_foreign_or_wrong_parent_location_is_hidden(locations):
    f = locations
    other = StockLocation(org_id=f.org_b, branch_id=f.foreign, code="SITE", name="Foreign", kind="SITE")
    f.db.add(other); f.db.commit()
    assert f.client.get(path(f, other.id)).status_code == 404
    assert f.client.get(f"/inventory/branches/{f.foreign}/locations/{other.id}/stock").status_code == 404
    f.context.allowed_org_ids = [f.org_a, f.org_b]
    assert f.client.get(path(f, other.id)).status_code == 404


def test_empty_parent_does_not_roll_up_child_or_legacy_stock(locations):
    f = locations
    parent = site(f.client, f.own).json()["id"]
    child = StockLocation(org_id=f.org_a, branch_id=f.own, code="CHILD", name="Child",
                          kind="ZONE", parent_id=parent)
    f.db.add(child); f.db.commit()
    seed(f, child.id)
    assert f.client.get(path(f, parent)).json()["total"] == 0
    assert f.client.get(path(f, child.id)).json()["total"] == 1
    child.is_deleted = True; f.db.commit()
    assert f.client.get(path(f, child.id)).status_code == 404


def test_zero_balance_is_distinct_from_no_record_and_inactive_is_visible(locations):
    f = locations
    location = site(f.client, f.own).json()["id"]
    product = seed(f, location)
    product.status = "inactive"
    balance = f.db.query(StockBalance).filter_by(location_id=location).one()
    balance.on_hand = balance.reserved = balance.damaged = balance.quarantined = D("0")
    f.db.commit()
    row = f.client.get(path(f, location)).json()["items"][0]
    assert row["available"] == "0.000000" and row["product_status"] == "inactive"
    product.is_deleted = True; f.db.commit()
    assert f.client.get(path(f, location)).json()["total"] == 0
