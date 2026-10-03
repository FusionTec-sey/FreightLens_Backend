from uuid import uuid4
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from auth.policy import AccessPolicy
from tests.test_policy_activation import activation  # noqa: F401
from tests.test_policy_manager_cases import policy_cases  # noqa: F401
from tests.test_inventory_policy_drafts import draft  # noqa: F401
from tests.test_inventory_locations import locations  # noqa: F401


@pytest.fixture
def barcodes(activation):
    f = activation
    assert f.client.post(f.activate_url, json=f.payload).status_code == 200
    f.barcode_url = f"/inventory/unit-barcodes/products/{f.product.id}"
    f.barcode_payload = {"operation_key": str(uuid4()), "expected_policy_version": 1, "barcode": "000-AbC", "unit": "BOX"}
    return f


def test_register_list_resolve_and_retry_preserve_exact_unit(barcodes):
    f = barcodes
    first = f.client.post(f.barcode_url, json=f.barcode_payload)
    assert first.status_code == 200, first.text
    data = first.json()
    assert data["barcode"] == "000-AbC" and data["base_quantity"] == "12.00000000" and data["unit"] == "BOX"
    assert f.client.post(f.barcode_url, json=f.barcode_payload).json()["replayed"]
    assert f.client.get(f.barcode_url).json()["total"] == 1
    assert f.client.get("/inventory/unit-barcodes/resolve", params={"code": "000-AbC"}).json()["id"] == data["id"]
    assert f.client.get("/inventory/unit-barcodes/resolve", params={"code": "000-abc"}).status_code == 404
    assert f.client.post(f.barcode_url, json={**f.barcode_payload, "operation_key": str(uuid4())}).status_code == 409


@pytest.mark.parametrize("route", ["create", "list", "resolve"])
@pytest.mark.parametrize("denial", ["anonymous", "permission", "module"])
def test_barcode_route_guards(barcodes, route, denial):
    f = barcodes
    if denial == "anonymous":
        for dependency in f.user_dependencies: f.app.dependency_overrides.pop(dependency)
    else:
        f.user.access_policy = AccessPolicy(user=f.user, org_ids=(f.org_a,), field_permissions={},
            permission_names=frozenset() if denial == "permission" else frozenset({"View_Product", "Manage_InventoryBarcode"}),
            module_names=frozenset({"INVENTORY"}) if denial == "permission" else frozenset())
    if route == "create": response = f.client.post(f.barcode_url, json=f.barcode_payload)
    elif route == "list": response = f.client.get(f.barcode_url)
    else: response = f.client.get("/inventory/unit-barcodes/resolve?code=000-AbC")
    assert response.status_code == (401 if denial == "anonymous" else 403)


def test_scope_and_legacy_barcode_never_fall_back(barcodes):
    f = barcodes
    foreign = f"/inventory/unit-barcodes/products/{f.foreign_product.id}"
    assert f.client.post(foreign, json=f.barcode_payload).status_code == 404
    assert f.client.get(foreign).status_code == 404
    f.product.barcode = "OLD-CATALOGUE"; f.db.commit()
    assert f.client.get("/inventory/unit-barcodes/resolve?code=OLD-CATALOGUE").status_code == 404


@pytest.mark.parametrize("patch,status", [({"unit": "PALLET"}, 422), ({"expected_policy_version": 2}, 409),
    ({"expected_policy_version": True}, 422), ({"barcode": "bad code"}, 422), ({"barcode": "bad\ncode"}, 422),
    ({"operation_key": "00000000-0000-0000-0000-000000000000"}, 422)])
def test_invalid_registration_does_not_create_rows(barcodes, patch, status):
    f = barcodes
    assert f.client.post(f.barcode_url, json={**f.barcode_payload, **patch}).status_code == status
    assert f.client.get(f.barcode_url).json()["total"] == 0


def test_no_policy_and_inactive_product_fail_closed(activation):
    f = activation
    url = f"/inventory/unit-barcodes/products/{f.product.id}"
    payload = {"operation_key": str(uuid4()), "expected_policy_version": 1, "barcode": "ZERO", "unit": "PCS"}
    assert f.client.post(url, json=payload).status_code == 409
    assert f.client.post(f.activate_url, json=f.payload).status_code == 200
    assert f.client.post(url, json=payload).status_code == 200
    f.product.status = "inactive"; f.db.commit()
    assert f.client.post(url, json=payload).status_code == 409
    assert not f.client.get(url).json()["items"][0]["eligible"]
    assert f.client.get("/inventory/unit-barcodes/resolve?code=ZERO").status_code == 409


def test_pagination_changed_intent_and_immutable_history(barcodes, monkeypatch, test_engine):
    import Utils.migrate_20261002_unit_barcodes as migration
    monkeypatch.setattr(migration, "engine", test_engine)
    migration.ensure_unit_barcodes_schema(); migration.ensure_unit_barcodes_schema()
    f = barcodes
    assert f.client.post(f.barcode_url, json=f.barcode_payload).status_code == 200
    assert f.client.post(f.barcode_url, json={**f.barcode_payload, "unit": "PCS"}).status_code == 409
    assert f.client.post(f.barcode_url, json={**f.barcode_payload, "operation_key": str(uuid4()), "barcode": "SECOND", "unit": "pcs"}).json()["base_quantity"] == "1.00000000"
    page = f.client.get(f.barcode_url + "?page=2&limit=1").json()
    assert page["total"] == 2 and len(page["items"]) == 1 and page["pages"] == 2
    with pytest.raises(DBAPIError):
        with f.db.begin_nested():
            f.db.execute(text("DELETE FROM containermgmt.inventory_unit_barcodes WHERE org_id=:org"), {"org": f.org_a})


def test_new_active_policy_never_silently_reinterprets_a_barcode(barcodes, monkeypatch):
    from types import SimpleNamespace
    import importlib
    router = importlib.import_module("Routes.Inventory.UnitBarcodeRouter")
    f = barcodes
    assert f.client.post(f.barcode_url, json=f.barcode_payload).status_code == 200
    monkeypatch.setattr(router, "active_policy", lambda *args: SimpleNamespace(version=2, config={"base_unit": "PCS"}))
    assert f.client.get("/inventory/unit-barcodes/resolve?code=000-AbC").status_code == 409
    historical = f.client.get(f.barcode_url).json()["items"][0]
    assert not historical["eligible"] and historical["base_quantity"] == "12.00000000"


def test_reviewed_extension_keeps_original_barcode_identity_and_factor(barcodes):
    from tests.test_inventory_policy_drafts import config
    from tests.test_policy_manager_cases import review_payload
    from Model.Credentials.users import User
    f = barcodes
    first = f.client.post(f.barcode_url, json=f.barcode_payload).json()
    proposed = config(conversions=[{"unit": "BOX", "factor": "12"}, {"unit": "PALLET", "factor": "144"}])
    assert f.client.put(f.url, json={"expected_version": 1, "config": proposed}).status_code == 200
    readiness = f.client.get(f.read_url + "/transition-readiness").json()
    assert readiness["route"] == "COMPATIBLE_REVISION_REVIEW"
    f.user.id = f.db.query(User.id).filter(User.org_id == f.org_a, User.id != f.reviewer).scalar()
    request = f.client.post(f.request_url, json={**f.request_payload, "operation_key": str(uuid4()), "expected_source_version": 2})
    assert request.status_code == 200, request.text
    key = request.json()["case_key"]
    f.user.id = f.reviewer
    assert f.client.post(f"/inventory/manager-cases/{key}/review", json=review_payload()).status_code == 200
    cases = f.client.get("/inventory/manager-cases").json()["items"]
    assert next(row for row in cases if row["case_key"] == key)["transition"] == "EXTEND_UNITS"
    payload = {"operation_key": str(uuid4()), "expected_active_version": 1}
    url = f"/inventory/manager-cases/{key}/activate-policy"
    assert f.client.post(url, json=payload).status_code == 200
    assert f.client.post(url, json=payload).json()["replayed"]
    resolved = f.client.get("/inventory/unit-barcodes/resolve?code=000-AbC").json()
    assert resolved["id"] == first["id"] and resolved["policy_version"] == 1
    assert resolved["eligible"] and resolved["base_quantity"] == "12.00000000"
    assert f.client.get(f.barcode_url).json()["items"][0]["eligible"]
