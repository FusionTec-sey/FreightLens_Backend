from uuid import uuid4
import pytest
from auth.policy import AccessPolicy
from Model.containermgmt.Inventory.ProductPolicyActivation import ProductPolicyActivation
from Model.containermgmt.Inventory.ManagerCase import ManagerCaseUse
from tests.test_policy_activation import activation  # noqa: F401
from tests.test_policy_manager_cases import policy_cases, review_payload  # noqa: F401
from tests.test_inventory_policy_drafts import draft, config  # noqa: F401
from tests.test_inventory_locations import locations  # noqa: F401


def prepare_revision(f):
    assert f.client.post(f.activate_url, json=f.payload).status_code == 200
    assert f.client.put(f.url, json={"expected_version": 1, "config": config(quantity_step="0.1")}).status_code == 200
    from Model.Credentials.users import User
    f.user.id = f.db.query(User.id).filter(User.org_id == f.org_a, User.id != f.reviewer).scalar()
    response = f.client.post(f.request_url, json={**f.request_payload,
        "operation_key": str(uuid4()), "expected_source_version": 2})
    assert response.status_code == 200, response.text
    key = response.json()["case_key"]
    f.user.id = f.reviewer
    assert f.client.post(f"/inventory/manager-cases/{key}/review", json=review_payload()).status_code == 200
    return f"/inventory/manager-cases/{key}/activate-policy", {"operation_key": str(uuid4()), "expected_active_version": 1}


def test_reviewed_empty_revision_preserves_history_and_replay(activation):
    f = activation
    url, payload = prepare_revision(f)
    check = f.client.get(f.read_url + "/transition-readiness").json()
    assert check["route"] == "EMPTY_REVISION_REVIEW" and check["changed_fields"] == ["quantity_step"]
    assert check["advisory_only"] and check["active_version"] == 1 and check["draft_version"] == 2
    assert check["active_config"]["quantity_step"] == "1"
    assert check["proposed_config"]["quantity_step"] == "0.1"
    assert check["active_config"]["conversions"][0]["factor"] == "12"
    assert f.client.get("/inventory/manager-cases").json()["items"][0]["expected_active_version"] == 1
    result = f.client.post(url, json=payload)
    assert result.status_code == 200, result.text
    assert result.json()["version"] == 2
    assert f.client.post(url, json=payload).json()["replayed"]
    rows = f.db.query(ProductPolicyActivation).filter_by(org_id=f.org_a).order_by(ProductPolicyActivation.version).all()
    assert [row.config["quantity_step"] for row in rows] == ["1", "0.1"]
    assert f.client.post(url, json={**payload, "operation_key": str(uuid4())}).status_code == 409
    assert f.client.post(f.activate_url, json=f.payload).status_code == 409
    assert f.client.get(f.read_url + "/transition-readiness").json()["route"] == "NO_CHANGE"


def test_barcode_after_approval_blocks_revision_without_consuming_it(activation):
    f = activation; url, payload = prepare_revision(f)
    response = f.client.post(f"/inventory/unit-barcodes/products/{f.product.id}", json={
        "operation_key": str(uuid4()), "expected_policy_version": 1, "barcode": "000-REVIEW", "unit": "BOX"})
    assert response.status_code == 200
    check = f.client.get(f.read_url + "/transition-readiness").json()
    assert check["route"] == "BLOCKED" and any("barcodes" in reason for reason in check["blockers"])
    assert f.client.post(url, json=payload).status_code == 409
    assert f.db.query(ManagerCaseUse).filter_by(org_id=f.org_a).count() == 1
    assert f.client.get(f.read_url).json()["version"] == 1
    assert f.client.get("/inventory/unit-barcodes/resolve?code=000-REVIEW").status_code == 200


def test_revision_expected_version_and_changed_draft_rejected(activation):
    f = activation; url, payload = prepare_revision(f)
    assert f.client.post(url, json={**payload, "expected_active_version": 0}).status_code == 409
    assert f.client.put(f.url, json={"expected_version": 2, "config": config(quantity_step="0.01")}).status_code == 200
    assert f.client.post(url, json=payload).status_code == 409


@pytest.mark.parametrize("denial", ["anonymous", "permission", "module"])
def test_readiness_guards(activation, denial):
    f = activation
    if denial == "anonymous":
        for dependency in f.user_dependencies: f.app.dependency_overrides.pop(dependency)
    else:
        f.user.access_policy = AccessPolicy(user=f.user, org_ids=(f.org_a,), field_permissions={},
            permission_names=frozenset() if denial == "permission" else frozenset({"View_Product"}),
            module_names=frozenset({"INVENTORY"}) if denial == "permission" else frozenset())
    assert f.client.get(f.read_url + "/transition-readiness").status_code == (401 if denial == "anonymous" else 403)


def test_readiness_hides_foreign_shared_deleted_and_handles_missing_draft(draft):
    f = draft
    path = lambda id: f"/inventory/products/{id}/inventory-policy/transition-readiness"
    assert f.client.get(path(f.foreign_product.id)).status_code == 404
    check = f.client.get(path(f.product.id)).json()
    assert check["route"] == "BLOCKED" and len(check["blockers"]) == 2
    assert check["draft_version"] == 0
    assert check["active_config"] is None and check["proposed_config"] is None
    f.product.is_shared = True; f.db.commit()
    assert f.client.get(path(f.product.id)).status_code == 404
    f.product.is_shared = False; f.product.is_deleted = True; f.db.commit()
    assert f.client.get(path(f.product.id)).status_code == 404


def test_initial_readiness_and_inactive_product(activation):
    f = activation
    assert f.client.get(f.read_url + "/transition-readiness").json()["route"] == "INITIAL_REVIEW"
    f.product.status = "inactive"; f.db.commit()
    assert f.client.get(f.read_url + "/transition-readiness").json()["route"] == "BLOCKED"
    assert f.client.post(f.activate_url, json=f.payload).status_code == 404


def test_unchanged_policy_cannot_consume_another_approval(activation):
    f = activation
    assert f.client.post(f.activate_url, json=f.payload).status_code == 200
    from Model.Credentials.users import User
    f.user.id = f.db.query(User.id).filter(User.org_id == f.org_a, User.id != f.reviewer).scalar()
    key = f.client.post(f.request_url, json={**f.request_payload, "operation_key": str(uuid4())}).json()["case_key"]
    f.user.id = f.reviewer
    assert f.client.post(f"/inventory/manager-cases/{key}/review", json=review_payload()).status_code == 200
    response = f.client.post(f"/inventory/manager-cases/{key}/activate-policy", json={
        "operation_key": str(uuid4()), "expected_active_version": 1})
    assert response.status_code == 409 and "already active" in response.text
    assert f.db.query(ManagerCaseUse).filter_by(org_id=f.org_a).count() == 1
