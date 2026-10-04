"""Phase 0 reproductions against real routers, with an isolated session double.

The original direct-stock regression expectations now pass. PostgreSQL lock,
constraint and rollback verification remains a separate mandatory gate.
"""

import importlib
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.sql import operators

from auth.module_guard import require_module
from auth.policy import AccessPolicy
from Utils.org_filter import OrgContext

receiving = importlib.import_module("Routes.Orders.ReceivingRouter")
inventory = importlib.import_module("Routes.Inventory.InventoryRouter")


def test_receipt_format_exposes_linked_product_without_commercial_fields():
    item = SimpleNamespace(id=2, po_item_id=3, po_item=SimpleNamespace(product_id=7), packing_item_id=None,
        description="Synthetic", expected_quantity=Decimal("2"), received_quantity=Decimal("2"),
        missing_quantity=Decimal("0"), excess_quantity=Decimal("0"), damaged_quantity=Decimal("0"),
        incorrect_quantity=Decimal("0"), unit="BOX", condition_ok=True, notes=None, photo_url=None,
        is_deleted=False)
    receipt = SimpleNamespace(id=1, receipt_number="GRN-1", po_id=4,
        purchase_order=SimpleNamespace(po_number="PO-1"), packing_list_id=None, container_id=None,
        container=None, warehouse_location="Receiving", received_date=None, status="SUBMITTED",
        posting_version=1, has_discrepancies=False, notes=None, submitted_at=None,
        receiver=None, items=[item])
    result = receiving.format_receipt(receipt)
    assert result["items"][0]["product_id"] == 7
    assert "unit_price" not in result["items"][0] and "supplier_id" not in result["items"][0]


def _matches(row, expression):
    """Evaluate only the simple comparisons used by these router queries.

    Unlike a filter-ignoring mock, a future org/parent predicate changes the
    result. Unsupported expressions fail loudly, not as an expected failure.
    """
    key = expression.left.name
    actual = getattr(row, key, None)
    right = expression.right
    visit = getattr(right, "__visit_name__", None)
    expected = {"false": False, "true": True, "null": None}.get(visit)
    if visit not in {"false", "true", "null"}:
        expected = right.value
    operation = expression.operator
    if operation in {operators.eq, operators.is_}:
        return actual == expected
    if operation == operators.in_op:
        return actual in expected
    if operation == operators.ne:
        return actual != expected
    raise NotImplementedError(f"Session double does not support {operation}")


class QueryDouble:
    def __init__(self, rows):
        self.rows = list(rows)

    def filter(self, *criteria):
        return QueryDouble([
            row for row in self.rows
            if all(_matches(row, criterion) for criterion in criteria)
        ])

    def options(self, *args):
        return self

    def with_for_update(self, **kwargs):
        return self

    def populate_existing(self):
        return self

    def order_by(self, *args):
        return self

    def count(self):
        return len(self.rows)

    def offset(self, value):
        return QueryDouble(self.rows[value:])

    def limit(self, value):
        return QueryDouble(self.rows[:value])

    def first(self):
        return self.rows[0] if self.rows else None

    def all(self):
        return self.rows


class SessionDouble:
    def __init__(self, rows):
        self.rows = rows
        self.added = []
        self.commits = 0

    def query(self, model):
        return QueryDouble(self.rows.get(model, []))

    def add(self, row):
        if getattr(row, "id", None) is None:
            row.id = 100 + len(self.added)
        self.added.append(row)

    def flush(self):
        pass

    def commit(self):
        self.commits += 1

    def refresh(self, row):
        pass

    def rollback(self):
        pass  # Rollback semantics are tested separately against PostgreSQL.


@pytest.fixture
def harness(monkeypatch):
    own_po = SimpleNamespace(id=10, org_id=1001, is_deleted=False, po_number="TEST-A")
    other_po = SimpleNamespace(id=20, org_id=2002, is_deleted=False, po_number="TEST-B")
    own_item = SimpleNamespace(id=11, po_id=10, org_id=1001, is_deleted=False, quantity_received=Decimal("0"))
    wrong_parent_item = SimpleNamespace(id=12, po_id=30, org_id=1001, is_deleted=False, quantity_received=Decimal("0"))
    other_item = SimpleNamespace(id=21, po_id=20, org_id=2002, is_deleted=False, quantity_received=Decimal("0"))
    product = SimpleNamespace(id=1, org_id=1001, is_deleted=False, sku="TEST-STOCK", current_stock=Decimal("5"))
    for item in (own_item, wrong_parent_item, other_item):
        item.item_status, item.unit, item.quantity_ordered = "ACTIVE", "PCS", Decimal("10")
    db = SessionDouble({
        receiving.PurchaseOrder: [own_po, other_po],
        receiving.POItem: [own_item, wrong_parent_item, other_item],
        inventory.Product: [product],
    })
    context = OrgContext(current_org_id=1001, allowed_org_ids=[1001], is_root=False)
    policy = AccessPolicy(
        user=SimpleNamespace(id=1), org_ids=(1001,),
        permission_names=frozenset({"Verify_Receipt", "Edit_Receipt", "Submit_Receipt", "Adjust_Stock", "Edit_Product"}),
        module_names=frozenset({"ORDERS", "INVENTORY"}), field_permissions={},
    )
    user = SimpleNamespace(id=1, org_id=1001, roles=[], access_policy=policy)
    app = FastAPI()
    # Same module registration boundary as containerMgmt, without startup jobs.
    app.include_router(receiving.ReceivingRouter, dependencies=[Depends(require_module("ORDERS"))])
    app.include_router(inventory.InventoryRouter, dependencies=[Depends(require_module("INVENTORY"))])
    # Existing baseline tests reload auth modules during collection. FastAPI
    # retains the original dependency callable on already-imported routers.
    # Override those captured objects, not just the latest module's functions.
    replacements = {
        "get_db": lambda: db,
        "get_current_user": lambda: user,
        "get_org_context": lambda: context,
        "get_request_policy": lambda: user.access_policy,
    }
    user_dependencies = set()

    def override_dependencies(dependant):
        for dependency in dependant.dependencies:
            name = getattr(dependency.call, "__name__", "")
            module = getattr(dependency.call, "__module__", "")
            if name in replacements and module.startswith(("auth.", "Model.db")):
                app.dependency_overrides[dependency.call] = replacements[name]
                if name == "get_current_user":
                    user_dependencies.add(dependency.call)
            override_dependencies(dependency)

    for route in app.routes:
        if hasattr(route, "dependant"):
            override_dependencies(route.dependant)
    # Rendering/search are unrelated external side effects, not access checks.
    monkeypatch.setattr(receiving, "format_receipt", lambda row: {"id": row.id, "status": row.status})
    monkeypatch.setattr(inventory, "product_to_dict", lambda row, **kwargs: {"id": row.id, "current_stock": float(row.current_stock)})
    monkeypatch.setattr(inventory, "product_quantity_totals", lambda db, context, ids: {
        product_id: {"status": "NO_BALANCE", "base_unit": None,
            "on_hand": "0.000000", "reserved": "0.000000",
            "available": "0.000000", "damaged": "0.000000",
            "quarantined": "0.000000"} for product_id in ids})
    monkeypatch.setattr(inventory, "sync_product_document", lambda *args: None)
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, app=app, db=db, user=user, item=own_item, product=product, user_dependencies=user_dependencies)


def _payload(**overrides):
    payload = {
        "po_id": 10, "receipt_number": "TEST-GRN", "received_date": "2026-10-02",
        "status": "DRAFT", "items": [{"po_item_id": 11, "description": "Test goods", "received_quantity": 2}],
    }
    payload.update(overrides)
    return payload


def test_receipt_allows_authenticated_owning_tenant(harness):
    response = harness.client.post("/goods-receiving", json=_payload())
    assert response.status_code == 200
    assert harness.db.added[0].org_id == 1001


def test_receipt_rejects_unauthenticated_request(harness):
    for dependency in harness.user_dependencies:
        harness.app.dependency_overrides.pop(dependency)
    response = harness.client.post("/goods-receiving", json=_payload())
    assert response.status_code == 401
    assert not harness.db.added


def test_receipt_rejects_unsubscribed_module(harness):
    harness.user.access_policy = AccessPolicy(user=harness.user, org_ids=(1001,), permission_names=frozenset(), module_names=frozenset(), field_permissions={})
    response = harness.client.post("/goods-receiving", json=_payload())
    assert response.status_code == 403
    assert not harness.db.added


def test_receipt_missing_po_has_no_side_effect(harness):
    response = harness.client.post("/goods-receiving", json=_payload(po_id=999))
    assert response.status_code == 404
    assert not harness.db.added


def test_receipt_denies_user_without_receiving_permission(harness):
    harness.user.access_policy = AccessPolicy(user=harness.user, org_ids=(1001,), permission_names=frozenset(), module_names=frozenset({"ORDERS"}), field_permissions={})
    response = harness.client.post("/goods-receiving", json=_payload())
    assert response.status_code == 403
    assert not harness.db.added


def test_receipt_hides_foreign_tenant_po(harness):
    response = harness.client.post("/goods-receiving", json=_payload(po_id=20))
    assert response.status_code == 404
    assert not harness.db.added


@pytest.mark.parametrize("item_id", [12, 21], ids=["same-tenant-wrong-po", "foreign-tenant-item"])
def test_receipt_rejects_item_outside_its_po(harness, item_id):
    response = harness.client.post("/goods-receiving", json=_payload(items=[{"po_item_id": item_id, "description": "Wrong parent", "received_quantity": 2}]))
    assert response.status_code in {400, 404, 422}
    assert not harness.db.added


def test_draft_does_not_increase_received_quantity(harness):
    response = harness.client.post("/goods-receiving", json=_payload())
    assert response.status_code == 200
    assert harness.item.quantity_received == Decimal("0")


def test_receipt_rejects_negative_quantity(harness):
    response = harness.client.post("/goods-receiving", json=_payload(items=[{"po_item_id": 11, "description": "Negative", "received_quantity": -2}]))
    assert response.status_code in {400, 422}
    assert not harness.db.added


@pytest.mark.parametrize("quantity", ["NaN", "Infinity", "0.001", "10000000000"])
def test_receipt_rejects_unrepresentable_quantity(harness, quantity):
    response = harness.client.post("/goods-receiving", json=_payload(items=[{
        "po_item_id": 11, "description": "Invalid", "received_quantity": quantity,
    }]))
    assert response.status_code == 422
    assert not harness.db.added


@pytest.mark.parametrize("overrides", [
    {"status": "VERIFIED"}, {"items": []}, {"received_date": "not-a-date"},
    {"items": _payload()["items"] * 2},
    {"items": [{"description": "Unlinked goods", "received_quantity": 1}]},
])
def test_receipt_rejects_invalid_input(harness, overrides):
    assert harness.client.post("/goods-receiving", json=_payload(**overrides)).status_code == 422
    assert not harness.db.added


@pytest.mark.parametrize("overrides", [
    {"packing_list_id": 999}, {"container_id": 999},
    {"items": [{"po_item_id": 11, "packing_item_id": 999, "description": "Invalid", "received_quantity": 1}]},
    {"items": [{"po_item_id": 11, "unit": "BOX", "description": "Invalid", "received_quantity": 1}]},
])
def test_receipt_rejects_invalid_references_before_writing(harness, overrides):
    assert harness.client.post("/goods-receiving", json=_payload(**overrides)).status_code == 400
    assert not harness.db.added


def test_create_submitted_requires_submit_permission(harness):
    harness.user.access_policy = AccessPolicy(user=harness.user, org_ids=(1001,),
        permission_names=frozenset({"Verify_Receipt"}), module_names=frozenset({"ORDERS"}), field_permissions={})
    assert harness.client.post("/goods-receiving", json=_payload(status="SUBMITTED")).status_code == 403
    assert not harness.db.added


@pytest.mark.parametrize("method,path", [("get", "/goods-receiving"), ("get", "/goods-receiving/1"), ("post", "/goods-receiving/1/submit")])
def test_receipt_routes_reject_missing_permission(harness, method, path):
    harness.user.access_policy = AccessPolicy(user=harness.user, org_ids=(1001,),
        permission_names=frozenset(), module_names=frozenset({"ORDERS"}), field_permissions={})
    assert getattr(harness.client, method)(path).status_code == 403


@pytest.mark.parametrize("method,path", [("get", "/goods-receiving"), ("get", "/goods-receiving/1"), ("post", "/goods-receiving/1/submit")])
def test_receipt_routes_reject_missing_authentication(harness, method, path):
    for dependency in harness.user_dependencies:
        harness.app.dependency_overrides.pop(dependency)
    assert getattr(harness.client, method)(path).status_code == 401


@pytest.mark.parametrize("method,path", [("get", "/goods-receiving/1"), ("post", "/goods-receiving/1/submit")])
def test_receipt_routes_hide_foreign_record(harness, method, path):
    harness.user.access_policy = AccessPolicy(user=harness.user, org_ids=(1001,),
        permission_names=frozenset({"View_GoodsReceipt", "Submit_Receipt"}), module_names=frozenset({"ORDERS"}), field_permissions={})
    harness.db.rows[receiving.GoodsReceipt] = [SimpleNamespace(id=1, org_id=2002, is_deleted=False)]
    assert getattr(harness.client, method)(path).status_code == 404


def test_receipt_read_and_list_owning_tenant(harness):
    harness.user.access_policy = AccessPolicy(user=harness.user, org_ids=(1001,),
        permission_names=frozenset({"View_GoodsReceipt"}), module_names=frozenset({"ORDERS"}), field_permissions={})
    harness.db.rows[receiving.GoodsReceipt] = [
        SimpleNamespace(id=1, org_id=1001, is_deleted=False, status="DRAFT"),
        SimpleNamespace(id=2, org_id=2002, is_deleted=False, status="DRAFT"),
    ]
    assert harness.client.get("/goods-receiving/1").status_code == 200
    response = harness.client.get("/goods-receiving")
    assert response.status_code == 200
    assert response.json()["items"] == [{"id": 1, "status": "DRAFT"}]


def test_authorized_submit_endpoint_posts_own_receipt(harness):
    line = SimpleNamespace(**receiving.ReceiptLineCreate(
        po_item_id=11, description="Test", received_quantity="2.25"
    ).model_dump(), is_deleted=False)
    receipt = SimpleNamespace(id=1, po_id=10, org_id=1001, is_deleted=False,
        status="DRAFT", posting_version=1, packing_list_id=None, container_id=None,
        receipt_number="TEST", items=[line])
    harness.db.rows[receiving.GoodsReceipt] = [receipt]
    response = harness.client.post("/goods-receiving/1/submit")
    assert response.status_code == 200
    assert response.json()["status"] == "SUBMITTED"
    assert harness.item.quantity_received == Decimal("2.25")


def test_authorized_create_submitted_posts_once(harness):
    response = harness.client.post("/goods-receiving", json=_payload(status="SUBMITTED"))
    assert response.status_code == 200
    assert harness.item.quantity_received == Decimal("2")
    assert harness.db.commits == 1


def test_stock_adjustment_rejects_insufficient_stock(harness):
    response = harness.client.post("/inventory/products/1/adjust-stock", json={"quantity_delta": -6, "reason": "test"})
    assert response.status_code == 400
    assert harness.product.current_stock == Decimal("5")
    assert harness.db.commits == 0


@pytest.mark.parametrize('replacement', [999, 5, 0, -1])
def test_product_edit_cannot_replace_stock(harness, replacement):
    response = harness.client.put("/inventory/products/1", json={"current_stock": replacement})
    assert response.status_code in {400, 422}
    assert harness.product.current_stock == Decimal("5")
    assert harness.db.commits == 0


@pytest.mark.parametrize('opening', [1, -1, '0.000001', 'NaN', 'Infinity'])
def test_catalogue_creation_cannot_open_stock(harness, opening):
    from dataclasses import replace
    harness.user.access_policy = replace(harness.user.access_policy,
        permission_names=frozenset({'Add_Product'}))
    response = harness.client.post('/inventory/products', json={
        'name': 'Synthetic catalogue only', 'sku': 'NEW-CATALOGUE', 'current_stock': opening})
    assert response.status_code in {400, 422}
    assert not harness.db.added and harness.db.commits == 0


@pytest.mark.parametrize('fields', [{}, {'current_stock': 0}, {'current_stock': None}])
def test_catalogue_creation_retains_zero_stock_compatibility(harness, fields):
    from dataclasses import replace
    harness.user.access_policy = replace(harness.user.access_policy,
        permission_names=frozenset({'Add_Product'}))
    response = harness.client.post('/inventory/products', json={
        'name': 'Synthetic catalogue only', 'sku': 'NEW-CATALOGUE', **fields})
    assert response.status_code == 200, response.text
    assert response.json()['current_stock'] == 0
    assert harness.db.added[0].current_stock == 0


def test_catalogue_stock_rejection_does_not_bypass_permission(harness):
    response = harness.client.post('/inventory/products', json={
        'name': 'Synthetic catalogue only', 'current_stock': 10})
    assert response.status_code == 403
    assert not harness.db.added and harness.db.commits == 0
