from uuid import uuid4
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from auth.policy import AccessPolicy
from Model.Credentials.users import User
from Model.containermgmt.Inventory.UnitBarcode import UnitBarcodeRetirement
from tests.test_unit_barcodes import barcodes  # noqa: F401
from tests.test_policy_activation import activation  # noqa: F401
from tests.test_policy_manager_cases import policy_cases, review_payload  # noqa: F401
from tests.test_inventory_policy_drafts import draft  # noqa: F401
from tests.test_inventory_locations import locations  # noqa: F401

BASE = "/inventory/barcode-retirement-cases"
PERMS = {"Request_BarcodeRetirement", "Review_BarcodeRetirement", "Retire_InventoryBarcode"}


@pytest.fixture
def retirement(barcodes):
    f = barcodes
    f.user.access_policy = AccessPolicy(user=f.user, org_ids=(f.org_a,), field_permissions={},
        permission_names=f.user.access_policy.permission_names | PERMS, module_names=frozenset({"INVENTORY"}))
    f.barcode_id = f.client.post(f.barcode_url, json=f.barcode_payload).json()["id"]
    other = User(username="retire-" + uuid4().hex, password_hash="test-only", org_id=f.org_a)
    f.db.add(other); f.db.commit(); f.other_reviewer = other.id
    f.retirement_payload = dict(operation_key=str(uuid4()), barcode_id=f.barcode_id, expected_source_version=1, reason="Wrong label")
    return f


def approved(f):
    response = f.client.post(BASE, json=f.retirement_payload)
    assert response.status_code == 200, response.text
    key = response.json()["case_key"]
    f.user.id = f.other_reviewer
    response = f.client.post(f"{BASE}/{key}/review", json=review_payload())
    assert response.status_code == 200, response.text
    return key


def test_reviewed_retirement_retains_identity_and_blocks_lookup_and_registration_replay(retirement):
    f = retirement
    key = approved(f)
    assert f.client.get("/inventory/unit-barcodes/resolve?code=000-AbC").status_code == 200
    payload = dict(operation_key=str(uuid4()), expected_source_version=1)
    url = f"{BASE}/{key}/retire"
    response = f.client.post(url, json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["retired"]
    assert f.client.post(url, json=payload).json()["replayed"]
    assert f.client.post(url, json={**payload, "operation_key": str(uuid4())}).status_code == 409
    assert f.client.get("/inventory/unit-barcodes/resolve?code=000-AbC").status_code == 409
    historical = f.client.get(f.barcode_url).json()["items"][0]
    assert historical["retired"] and not historical["eligible"] and historical["base_quantity"] == "12.00000000"
    assert f.client.post(f.barcode_url, json=f.barcode_payload).status_code == 409
    assert f.client.post(f.barcode_url, json={**f.barcode_payload, "operation_key": str(uuid4())}).status_code == 409
    assert f.client.get(BASE).json()["items"][0]["status"] == "CONSUMED"
    assert f.client.get(BASE + "?view=NEEDS_MY_REVIEW").json()["total"] == 0
    assert f.client.post(BASE, json={**f.retirement_payload, "operation_key": str(uuid4())}).status_code == 409
    with pytest.raises(DBAPIError):
        with f.db.begin_nested():
            f.db.execute(text("DELETE FROM containermgmt.inventory_unit_barcode_retirements WHERE org_id=:org"), {"org": f.org_a})


def test_readiness_requires_completed_retirement_not_approval_alone(retirement):
    from tests.test_inventory_policy_drafts import config
    f = retirement
    assert f.client.put(f.url, json={"expected_version": 1, "config": config(quantity_step="0.1")}).status_code == 200
    path = f.read_url + "/transition-readiness"
    assert f.client.get(path).json()["route"] == "BLOCKED"
    key = approved(f)
    assert f.client.get(path).json()["route"] == "BLOCKED"
    assert f.client.post(f"{BASE}/{key}/retire", json={"operation_key": str(uuid4()), "expected_source_version": 1}).status_code == 200
    response = f.client.get(path)
    assert response.status_code == 200
    assert response.json()["route"] == "EMPTY_REVISION_REVIEW"
    assert response.json()["advisory_only"]
    assert f.client.get(f.read_url).json()["version"] == 1


def test_unapproved_rejected_and_self_review_are_blocked(retirement):
    f = retirement
    response = f.client.post(BASE, json=f.retirement_payload)
    key = response.json()["case_key"]
    assert f.client.post(BASE, json=f.retirement_payload).json()["replayed"]
    assert f.client.post(f"{BASE}/{key}/review", json=review_payload()).status_code == 403
    payload = dict(operation_key=str(uuid4()), expected_source_version=1)
    assert f.client.post(f"{BASE}/{key}/retire", json=payload).status_code == 403
    f.user.id = f.other_reviewer
    assert f.client.post(f"{BASE}/{key}/review", json=review_payload(outcome="REJECTED")).status_code == 200
    assert f.client.post(f"{BASE}/{key}/retire", json=payload).status_code == 403
    assert f.db.query(UnitBarcodeRetirement).filter_by(org_id=f.org_a).count() == 0


@pytest.mark.parametrize("route", ["request", "list", "review", "retire"])
@pytest.mark.parametrize("denial", ["anonymous", "permission", "module"])
def test_retirement_endpoint_guards(retirement, route, denial):
    f = retirement
    if denial == "anonymous":
        for dependency in f.user_dependencies: f.app.dependency_overrides.pop(dependency)
    else:
        f.user.access_policy = AccessPolicy(user=f.user, org_ids=(f.org_a,), field_permissions={},
            permission_names=frozenset() if denial == "permission" else frozenset(PERMS),
            module_names=frozenset({"INVENTORY"}) if denial == "permission" else frozenset())
    if route == "request": response = f.client.post(BASE, json=f.retirement_payload)
    elif route == "list": response = f.client.get(BASE)
    elif route == "review": response = f.client.post(f"{BASE}/{uuid4()}/review", json=review_payload())
    else: response = f.client.post(f"{BASE}/{uuid4()}/retire", json=dict(operation_key=str(uuid4()), expected_source_version=1))
    assert response.status_code == (401 if denial == "anonymous" else 403)


def test_retirement_foreign_scope_and_wrong_case_kind(retirement):
    f = retirement; key = approved(f)
    payload = dict(operation_key=str(uuid4()), expected_source_version=1)
    assert f.client.post(f"{BASE}/{f.case}/retire", json=payload).status_code == 404
    f.context.is_root = True; f.context.allowed_org_ids = [f.org_a, f.org_b]; f.context.selected_org_id = f.org_b
    assert f.client.get(BASE).json()["total"] == 0
    assert f.client.post(BASE, json=f.retirement_payload).status_code == 404
    assert f.client.post(f"{BASE}/{key}/review", json=review_payload()).status_code == 404
    assert f.client.post(f"{BASE}/{key}/retire", json=payload).status_code == 404


def test_migration_replay_and_unapproved_sql_insert(retirement, test_engine, monkeypatch):
    import Utils.migrate_20261002_barcode_retirements as migration
    monkeypatch.setattr(migration, "engine", test_engine)
    migration.ensure_barcode_retirements_schema(); migration.ensure_barcode_retirements_schema()
    f = retirement
    from Model.containermgmt.Inventory.ManagerCase import ManagerCase
    case = f.db.query(ManagerCase).filter_by(org_id=f.org_a).first()
    with pytest.raises(DBAPIError):
        with f.db.begin_nested():
            f.db.add(UnitBarcodeRetirement(org_id=f.org_a, barcode_id=f.barcode_id,
                case_id=case.id, operation_key=uuid4(), created_by=f.user.id)); f.db.flush()
