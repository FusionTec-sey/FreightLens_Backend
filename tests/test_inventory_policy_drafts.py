from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from Model.containermgmt.Orders.Product import Product
from Model.containermgmt.Inventory.ProductPolicyDraft import ProductPolicyDraft
from Schema.InventoryPolicySchema import InventoryPolicySave
from auth.policy import AccessPolicy
from tests.test_inventory_locations import locations
from tests.test_stock_ledger import stock


def config(**changes):
    return {"base_unit": "PCS", "quantity_step": "1", "tracking": "BATCH", "require_shade": True,
            "conversions": [{"unit": "BOX", "factor": "12"}], **changes}


@pytest.fixture
def draft(locations):
    f = locations
    product = Product(org_id=f.org_a, sku="DRAFT", name="Draft test", unit="PCS", current_stock=9)
    foreign = Product(org_id=f.org_b, sku="OTHER", name="Foreign", unit="PCS")
    f.db.add_all([product, foreign]); f.db.commit()
    f.product = product
    f.foreign_product = foreign
    f.url = f"/inventory/products/{product.id}/inventory-policy-draft"
    return f


def test_save_revision_retry_and_conflict_without_changing_stock(draft):
    f = draft
    initial = f.client.get(f.url).json()
    assert initial["status"] == "NOT_CONFIGURED" and initial["config"] is None
    payload = {"expected_version": 0, "config": config()}
    first = f.client.put(f.url, json=payload)
    assert first.status_code == 200 and first.json()["version"] == 1
    assert first.json()["status"] == "DRAFT"
    assert f.client.put(f.url, json=payload).json() == first.json()
    assert f.client.put(f.url, json={**payload, "config": config(quantity_step="0.1")}).status_code == 409
    second = f.client.put(f.url, json={"expected_version": 1, "config": config(quantity_step="0.1")})
    assert second.status_code == 200 and second.json()["version"] == 2
    assert f.db.query(ProductPolicyDraft).filter_by(product_id=f.product.id).count() == 2
    f.db.refresh(f.product)
    assert f.product.current_stock == 9 and f.product.unit == "PCS"


@pytest.mark.parametrize("method", ["get", "put"])
@pytest.mark.parametrize("denial", ["anonymous", "permission", "module"])
def test_guards(draft, method, denial):
    f = draft
    if denial == "anonymous":
        for dependency in f.user_dependencies:
            f.app.dependency_overrides.pop(dependency)
    else:
        f.user.access_policy = AccessPolicy(user=f.user, org_ids=(f.org_a,), field_permissions={},
            permission_names=frozenset() if denial == "permission" else frozenset({"View_Product", "Edit_Product"}),
            module_names=frozenset({"INVENTORY"}) if denial == "permission" else frozenset())
    kwargs = {"json": {"expected_version": 0, "config": config()}} if method == "put" else {}
    assert getattr(f.client, method)(f.url, **kwargs).status_code == (401 if denial == "anonymous" else 403)


def test_foreign_shared_deleted_and_unit_mismatch(draft):
    f = draft
    foreign_url = f"/inventory/products/{f.foreign_product.id}/inventory-policy-draft"
    for method in ("get", "put"):
        kwargs = {"json": {"expected_version": 0, "config": config()}} if method == "put" else {}
        assert getattr(f.client, method)(foreign_url, **kwargs).status_code == 404
    assert f.client.put(f.url, json={"expected_version": 0, "config": config(base_unit="M2")}).status_code == 409
    f.product.is_shared = True; f.db.commit()
    assert f.client.get(f.url).status_code == 404
    f.product.is_shared = False; f.product.is_deleted = True; f.db.commit()
    assert f.client.get(f.url).status_code == 404


@pytest.mark.parametrize("changes", [
    {"tracking": "SERIAL", "require_shade": False, "quantity_step": "0.1"},
    {"tracking": "UNTRACKED"}, {"tracking": "UNKNOWN"}, {"quantity_step": "0"},
    {"conversions": [{"unit": "pcs", "factor": "1"}]},
    {"conversions": [{"unit": "BOX", "factor": "0"}]},
    {"conversions": [{"unit": "BOX", "factor": "NaN"}]},
    {"conversions": [{"unit": "BOX", "factor": 1.5}]},
    {"conversions": [{"unit": "BOX", "factor": "0.5"}]},
    {"conversions": [{"unit": "BOX", "factor": "12"}, {"unit": "box", "factor": "24"}]},
    {"conversions": [{"unit": str(i), "factor": "1"} for i in range(17)]},
])
def test_invalid_policy_rejected_without_revision(draft, changes):
    f = draft
    assert f.client.put(f.url, json={"expected_version": 0, "config": config(**changes)}).status_code == 422
    assert f.db.query(ProductPolicyDraft).filter_by(product_id=f.product.id).count() == 0


def test_revision_is_immutable_and_migration_replays(draft, monkeypatch, test_engine):
    f = draft
    assert f.client.put(f.url, json={"expected_version": 0, "config": config()}).status_code == 200
    for sql in ["UPDATE containermgmt.inventory_product_policy_drafts SET version = 5 WHERE product_id = :id",
                "DELETE FROM containermgmt.inventory_product_policy_drafts WHERE product_id = :id"]:
        with pytest.raises(DBAPIError):
            with f.db.begin_nested():
                f.db.execute(text(sql), {"id": f.product.id})
    import Utils.migrate_20261002_inventory_policy_drafts as migration
    monkeypatch.setattr(migration, "engine", test_engine)
    migration.ensure_inventory_policy_drafts_schema()
    migration.ensure_inventory_policy_drafts_schema()
    assert f.client.get(f.url).json()["version"] == 1


def test_concurrent_different_drafts_have_one_winner(stock):
    from Routes.Inventory.PolicyDraftRouter import save_policy
    f = stock
    barrier = Barrier(2, timeout=10)
    def save(step):
        with f.factory() as db:
            barrier.wait()
            try:
                return save_policy(f.products[0], InventoryPolicySave(expected_version=0,
                    config=config(quantity_step=step)), db, f.context, SimpleNamespace(id=f.actor)).version
            except HTTPException as exc:
                return exc.status_code
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(save, ["1", "0.1"])) == [1, 409]
