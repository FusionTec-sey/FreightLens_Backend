from decimal import Decimal as D, localcontext
from uuid import uuid4
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from Schema.InventoryPolicySchema import InventoryPolicyConfig
from Services.inventory_unit_service import convert_quantity
from Services.inventory_quantity_service import QuantityBreakdown
from Model.containermgmt.Inventory.StockLedger import StockBalance, StockMovement
from Model.containermgmt.Inventory.PostingOperation import PostingOperation
from tests.test_stock_ledger import stock
from tests.test_inventory_policy_drafts import draft, config
from tests.test_inventory_locations import locations
from auth.policy import AccessPolicy


def policy(**changes):
    return InventoryPolicyConfig(base_unit="PCS", tracking="UNTRACKED", **{
        "quantity_step": "1", "conversions": [{"unit": "BOX", "factor": "12"}], **changes})


def test_conversion_is_exact_and_context_independent():
    with localcontext() as ctx:
        ctx.prec = 3
        assert convert_quantity(policy(), D("0.5"), "box") == 6
        assert convert_quantity(policy(quantity_step="0.000001"), D("999999999999.123456"), "PCS") == D("999999999999.123456")


@pytest.mark.parametrize("amount,unit", [(D("0.1"), "BOX"), (D("1"), "PALLET"),
    (D("NaN"), "PCS"), (D("Infinity"), "PCS"), (D("-1"), "PCS"), (D(0), "PCS"),
    (1.5, "PCS"), (D("0.0000001"), "PCS"), (D("999999999999"), "BOX")])
def test_conversion_never_rounds_or_guesses(amount, unit):
    with pytest.raises(ValueError):
        convert_quantity(policy(), amount, unit)


def test_opening_pins_policy_and_holds_releases_enforce_step(stock):
    f = stock
    with pytest.raises(ValueError, match="increment"):
        f.open(policy=policy(), quantities=QuantityBreakdown(D("10.5")))
    opened = f.open(policy=policy())
    balance = opened.result["balance_id"]
    key = uuid4()
    with pytest.raises(ValueError, match="increment"):
        f.reserve(balance, key, quantity=D("0.5"))
    hold, source = uuid4(), uuid4()
    f.reserve(balance, reservation_key=hold, source_line_key=source)
    with pytest.raises(ValueError, match="increment"):
        f.release(balance, hold, source, quantity=D("0.5"))
    with f.factory() as db:
        row = db.get(StockBalance, balance)
        assert row.policy_config == policy().model_dump(mode="json") and row.quantity_step == 1
        assert row.reserved == 6 and row.version == 2
        assert db.query(PostingOperation).filter_by(org_id=f.orgs[0], operation_key=key).count() == 0
        assert db.query(StockMovement).filter_by(balance_id=balance).count() == 2


@pytest.mark.parametrize("statement", [
    "UPDATE containermgmt.inventory_stock_balances SET base_unit = 'BOX' WHERE id = :id",
    "UPDATE containermgmt.inventory_stock_balances SET policy_config = NULL, quantity_step = NULL WHERE id = :id",
    "UPDATE containermgmt.inventory_stock_balances SET on_hand = 10.5 WHERE id = :id",
    "DELETE FROM containermgmt.inventory_stock_balances WHERE id = :id",
])
def test_database_protects_snapshot_identity_and_increment(stock, statement):
    f = stock
    balance = f.open(policy=policy()).result["balance_id"]
    with f.factory() as db, pytest.raises(DBAPIError):
        db.execute(text(statement), {"id": balance})
        db.commit()


def test_old_balance_is_not_guessed_or_backfilled(stock, monkeypatch, test_engine):
    f = stock
    with f.factory() as db:
        row = StockBalance(org_id=f.orgs[0], branch_id=f.branches[0], location_id=f.locations[0],
            product_id=f.products[0], base_unit="PCS", tracking_policy="UNTRACKED", on_hand=10,
            reserved=0, damaged=0, quarantined=0, version=1, created_by=f.actor)
        db.add(row); db.commit(); balance = row.id
    import Utils.migrate_20261002_stock_unit_policy as migration
    monkeypatch.setattr(migration, "engine", test_engine)
    migration.ensure_stock_unit_policy_schema(); migration.ensure_stock_unit_policy_schema()
    with pytest.raises(ValueError, match="requires review"):
        f.reserve(balance)
    with f.factory() as db:
        row = db.get(StockBalance, balance)
        assert row.policy_config is None and row.quantity_step is None and row.on_hand == 10


def test_unit_preview_uses_unsaved_rules_without_mutation(draft):
    f = draft
    payload = {"config": config(), "quantity": "0.5", "unit": "BOX"}
    result = f.client.post(f.url + "/preview-unit", json=payload)
    assert result.status_code == 200
    assert result.json() == {"base_unit": "PCS", "base_quantity": "6.000000", "quantity_step": "1", "draft_only": True}
    assert f.client.get(f.url).json()["version"] == 0
    f.db.refresh(f.product)
    assert f.product.current_stock == 9
    assert f.client.post(f.url + "/preview-unit", json={**payload, "quantity": "0.1"}).status_code == 422
    assert f.client.post(f.url + "/preview-unit", json={**payload, "quantity": 1.5}).status_code == 422
    assert f.client.post(f.url + "/preview-unit", json={**payload, "config": config(base_unit="M2")}).status_code == 409
    assert f.client.post(f"/inventory/products/{f.foreign_product.id}/inventory-policy-draft/preview-unit", json=payload).status_code == 404


@pytest.mark.parametrize("denial", ["anonymous", "permission", "module"])
def test_preview_access_guards(draft, denial):
    f = draft
    if denial == "anonymous":
        for dependency in f.user_dependencies:
            f.app.dependency_overrides.pop(dependency)
    else:
        f.user.access_policy = AccessPolicy(user=f.user, org_ids=(f.org_a,), field_permissions={},
            permission_names=frozenset() if denial == "permission" else frozenset({"View_Product"}),
            module_names=frozenset({"INVENTORY"}) if denial == "permission" else frozenset())
    assert f.client.post(f.url + "/preview-unit", json={"config": config(), "quantity": "1", "unit": "BOX"}).status_code == (401 if denial == "anonymous" else 403)
