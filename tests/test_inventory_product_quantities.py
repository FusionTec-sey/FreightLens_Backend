"""Product quantity summaries use location balances, never legacy product totals."""
from decimal import Decimal as D

from Model.containermgmt.Inventory.Location import StockLocation
from Model.containermgmt.Inventory.StockLedger import StockBalance
from Model.containermgmt.Orders.Product import Product
from Services.inventory_product_quantity_service import product_quantity_totals
from Services.dashboard_registry import calculate_dashboard_data
from tests.test_inventory_locations import locations, site  # noqa: F401


def _balance(f, product, location_id, *, unit="PCS", on_hand="10",
             reserved="2", damaged="1", quarantined="0"):
    f.db.add(StockBalance(org_id=f.org_a, created_by=f.user.id,
        branch_id=f.own, location_id=location_id, product_id=product.id,
        base_unit=unit, tracking_policy="UNTRACKED", on_hand=D(on_hand),
        reserved=D(reserved), damaged=D(damaged), quarantined=D(quarantined),
        version=1))


def test_company_projection_sums_exact_balances_and_ignores_legacy_total(locations):
    f = locations
    first = site(f.client, f.own).json()["id"]
    second = StockLocation(org_id=f.org_a, branch_id=f.own, code="SECOND",
        name="Second", kind="SITE", created_by=f.user.id)
    product = Product(org_id=f.org_a, sku="SUMMARY", name="Summary",
        unit="PCS", current_stock=D("999"), created_by=f.user.id)
    f.db.add_all([second, product]); f.db.flush()
    _balance(f, product, first)
    _balance(f, product, second.id, on_hand="5", reserved="1", damaged="0",
        quarantined="1")
    f.db.commit()
    row = product_quantity_totals(f.db, f.context, [product.id])[product.id]
    assert row == {"status": "AVAILABLE", "base_unit": "PCS",
        "on_hand": "15.000000", "reserved": "3.000000",
        "available": "10.000000", "damaged": "1.000000",
        "quarantined": "1.000000"}


def test_no_balance_and_mixed_units_are_explicit(locations):
    f = locations
    first = site(f.client, f.own).json()["id"]
    second = StockLocation(org_id=f.org_a, branch_id=f.own, code="MIXED",
        name="Mixed", kind="SITE", created_by=f.user.id)
    empty = Product(org_id=f.org_a, sku="EMPTY", name="Empty", unit="PCS",
        current_stock=D("50"), created_by=f.user.id)
    mixed = Product(org_id=f.org_a, sku="MIX", name="Mixed", unit="PCS",
        current_stock=D("50"), created_by=f.user.id)
    f.db.add_all([second, empty, mixed]); f.db.flush()
    _balance(f, mixed, first, unit="PCS")
    _balance(f, mixed, second.id, unit="BOX")
    f.db.commit()
    rows = product_quantity_totals(f.db, f.context, [empty.id, mixed.id])
    assert rows[empty.id]["status"] == "NO_BALANCE"
    assert rows[empty.id]["on_hand"] == "0.000000"
    assert rows[mixed.id] == {"status": "MIXED_UNITS", "base_unit": None,
        "on_hand": None, "reserved": None, "available": None,
        "damaged": None, "quarantined": None}


def test_foreign_product_ids_never_enter_projection(locations):
    f = locations
    foreign = Product(org_id=f.org_b, sku="FOREIGN-SUMMARY", name="Foreign",
        unit="PCS", current_stock=D("999"), created_by=f.user.id)
    f.db.add(foreign); f.db.commit()
    result = product_quantity_totals(f.db, f.context, [foreign.id])
    assert result[foreign.id]["status"] == "NO_BALANCE"


def test_dashboard_uses_authoritative_quantity_and_provisional_valuation(locations, monkeypatch):
    f = locations
    location = site(f.client, f.own).json()["id"]
    low = Product(org_id=f.org_a, sku="DASH-LOW", name="Dashboard low",
        unit="PCS", current_stock=D("999"), min_stock_quantity=D("5"),
        unit_cost=D("999"), created_by=f.user.id)
    mixed = Product(org_id=f.org_a, sku="DASH-MIX", name="Dashboard mixed",
        unit="PCS", current_stock=D("0"), min_stock_quantity=D("100"),
        unit_cost=D("999"), created_by=f.user.id)
    f.db.add_all([low, mixed]); f.db.flush()
    _balance(f, low, location, on_hand="2", reserved="0", damaged="0")
    _balance(f, mixed, location, unit="PCS", on_hand="1", reserved="0", damaged="0")
    second = StockLocation(org_id=f.org_a, branch_id=f.own, code="DASH-MIX",
        name="Dashboard mixed", kind="SITE", created_by=f.user.id)
    f.db.add(second); f.db.flush()
    _balance(f, mixed, second.id, unit="BOX", on_hand="1", reserved="0", damaged="0")
    f.db.commit()
    monkeypatch.setattr("Services.dashboard_registry.is_financial_user", lambda *_: True)

    data = calculate_dashboard_data(f.db, f.user, f.context)

    assert data["inv_low_stock"]["value"] == 1
    assert data["inv_total_valuation"]["value"] == "0.00"
    assert data["inv_total_valuation"]["unit"] == "provisional"
    assert data["inv_total_valuation"]["alert"] is True
    assert "require valuation/reconciliation" in data["inv_total_valuation"]["note"]
