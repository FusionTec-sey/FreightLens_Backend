"""Synthetic persistence checks for T11; no preview or real prices are touched."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from Model.containermgmt.Inventory.Location import InventoryBranch
from Model.containermgmt.Inventory.PostingOperation import PostingOperation
from Model.containermgmt.Orders.Product import Product
from Model.containermgmt.Orders.SalesPricing import (
    BranchProductPrice, BranchProductPriceRevision, CustomerPriceAgreement,
    CustomerPriceAgreementRevision, ProductTaxAssignment,
    ProductTaxAssignmentRevision, SalesTaxRule, SalesTaxRuleRevision,
)
from Schema.CustomerSchema import CustomerIdentityInput
from Schema.SalesPricingSchema import (
    BranchProductPriceConfig, BranchProductPriceSave, TaxRuleConfig, TaxRuleSave,
    CustomerPriceAgreementConfig, CustomerPriceAgreementSave,
    ProductTaxAssignmentSave,
)
from Services.customer_identity_service import create_customer
from Services.inventory_posting_service import PostingConflict
from Services.sales_pricing_configuration_service import (
    read_branch_product_price, read_tax_rule, save_branch_product_price,
    read_customer_price_agreement, read_product_tax_assignment,
    resolve_pricing_line, save_customer_price_agreement,
    save_product_tax_assignment, save_tax_rule, store_price_candidate,
    tax_snapshot,
)
from Services.sales_pricing_service import calculate_tax_inclusive_invoice
from Utils.org_filter import OrgContext
from tests.test_stock_ledger import stock  # noqa: F401


def tax_payload(*, operation=None, expected=0, rate="0.15",
                treatment="STANDARD", enabled=True, code="VAT15"):
    return TaxRuleSave(operation_key=operation or uuid4(),
        expected_version=expected, code=code,
        config=TaxRuleConfig(name="Synthetic standard VAT",
            treatment=treatment, rate=rate, is_enabled=enabled),
        reason="Synthetic configuration verification")


def price_payload(f, *, operation=None, expected=0, branch=None,
                  amount="115", floor="100", enabled=True, unit="PCS"):
    return BranchProductPriceSave(operation_key=operation or uuid4(),
        expected_version=expected, branch_id=branch or f.branches[0],
        product_id=f.products[0], unit=unit, config=BranchProductPriceConfig(
            gross_unit_scr=amount, floor_gross_unit_scr=floor,
            is_enabled=enabled), reason="Synthetic branch price verification")


def assignment_payload(f, *, operation=None, expected=0, enabled=True,
                       tax_key=None):
    return ProductTaxAssignmentSave(operation_key=operation or uuid4(),
        expected_version=expected, product_id=f.products[0],
        tax_rule_key=tax_key or f.tax_key, is_enabled=enabled,
        reason="Synthetic product tax classification")


def agreement_payload(f, *, operation=None, expected=0, amount="105",
                      valid_from=None, valid_until=None, enabled=True,
                      unit="PCS"):
    start = valid_from or datetime(2026, 1, 1, tzinfo=timezone.utc)
    return CustomerPriceAgreementSave(operation_key=operation or uuid4(),
        expected_version=expected, customer_key=f.customer_key,
        branch_id=f.branches[0], product_id=f.products[0], unit=unit,
        config=CustomerPriceAgreementConfig(gross_unit_scr=amount,
            valid_from=start, valid_until=valid_until,
            terms_reference="Synthetic signed price schedule",
            is_enabled=enabled),
        reason="Synthetic customer agreement verification")


@pytest.fixture
def pricing(stock):
    stock.tax_key = uuid4(); stock.price_key = uuid4()
    stock.assignment_key = uuid4(); stock.agreement_key = uuid4()
    stock.customer_key = uuid4()
    stock.authorize = lambda db: None
    stock.save_tax = lambda payload=None, **changes: save_tax_rule(
        stock.factory, stock.context, stock.actor, stock.tax_key,
        payload or tax_payload(**changes), authorize=stock.authorize)
    stock.save_price = lambda payload=None, key=None, **changes: save_branch_product_price(
        stock.factory, stock.context, stock.actor, key or stock.price_key,
        payload or price_payload(stock, **changes), authorize=stock.authorize)
    stock.save_assignment = lambda payload=None, **changes: save_product_tax_assignment(
        stock.factory, stock.context, stock.actor, stock.assignment_key,
        payload or assignment_payload(stock, **changes), authorize=stock.authorize)
    stock.save_agreement = lambda payload=None, **changes: save_customer_price_agreement(
        stock.factory, stock.context, stock.actor, stock.agreement_key,
        payload or agreement_payload(stock, **changes), authorize=stock.authorize)
    create_customer(stock.factory, stock.context, stock.actor,
        stock.customer_key, CustomerIdentityInput(name="Synthetic price customer",
            kind="BUSINESS", contacts=[dict(kind="PHONE",
                value="+248 2000000", primary=True)]), expected_version=0,
        authorize=stock.authorize)
    with stock.factory.begin() as db:
        second = InventoryBranch(org_id=stock.orgs[0], code="SECOND",
            name="Synthetic second store", kind="STORE", created_by=stock.actor)
        db.add(second); db.flush(); stock.second_branch = second.id
    return stock


def test_tax_rule_history_is_exact_versioned_and_replay_safe(pricing):
    f = pricing; operation = uuid4()
    first = f.save_tax(tax_payload(operation=operation))
    assert not first.replayed and first.result["version"] == 1
    assert f.save_tax(tax_payload(operation=operation)).replayed
    second = f.save_tax(tax_payload(expected=1, rate="0.125"))
    assert second.result["version"] == 2
    with f.factory() as db:
        current = read_tax_rule(db, f.context, f.tax_key,
            authorize=f.authorize)
        assert current.version == 2 and Decimal(current.rate) == Decimal("0.125")
        assert tax_snapshot(current).rate == Decimal("0.125")
        assert [row.version for row in db.query(SalesTaxRuleRevision).filter_by(
            org_id=f.orgs[0], tax_rule_key=f.tax_key).order_by(
                SalesTaxRuleRevision.version).all()] == [1, 2]


def test_same_product_has_independent_branch_prices_and_no_stock_mutation(pricing):
    f = pricing
    f.save_price()
    other_key = uuid4()
    f.save_price(key=other_key, branch=f.second_branch, amount="130", floor="105")
    box_key = uuid4()
    f.save_price(key=box_key, unit="BOX", amount="1200", floor="1000")
    with f.factory() as db:
        one = read_branch_product_price(db, f.context, f.price_key,
            authorize=f.authorize)
        two = read_branch_product_price(db, f.context, other_key,
            authorize=f.authorize)
        box = read_branch_product_price(db, f.context, box_key,
            authorize=f.authorize)
        assert one.branch_id != two.branch_id
        assert one.unit == "PCS" and box.unit == "BOX"
        assert Decimal(one.gross_unit_scr) == Decimal("115")
        assert Decimal(two.gross_unit_scr) == Decimal("130")
        candidate = store_price_candidate(one)
        assert candidate.source == "STORE" and candidate.version == 1
        product = db.get(Product, f.products[0])
        assert product.current_stock == 0 and product.unit_cost is None


def test_tax_is_not_a_branch_price_property(pricing):
    f = pricing; f.save_tax(); f.save_price()
    with f.factory() as db:
        price = db.query(BranchProductPriceRevision).filter_by(
            org_id=f.orgs[0], price_key=f.price_key).one()
        assert not hasattr(price, "tax_rule_key")
        assert db.query(SalesTaxRule).filter_by(org_id=f.orgs[0]).count() == 1


def test_stale_changed_retry_noop_and_immutable_targets_fail_closed(pricing):
    f = pricing; operation = uuid4()
    f.save_price(price_payload(f, operation=operation))
    with pytest.raises(PostingConflict):
        f.save_price(price_payload(f, operation=operation, amount="116"))
    with pytest.raises(PostingConflict):
        f.save_price(price_payload(f, expected=0, operation=uuid4()))
    with pytest.raises(ValueError, match="no changes"):
        f.save_price(price_payload(f, expected=1))
    with pytest.raises(PostingConflict, match="target is immutable"):
        f.save_price(price_payload(f, expected=1, branch=f.second_branch))
    with f.factory() as db:
        assert db.query(BranchProductPriceRevision).filter_by(
            org_id=f.orgs[0], price_key=f.price_key).count() == 1
        assert db.query(PostingOperation).filter_by(
            org_id=f.orgs[0], kind="sales.branch-product-price.save.v1").count() == 1


def test_concurrent_same_expected_price_version_has_one_winner(pricing):
    f = pricing; f.save_price(); barrier = Barrier(2, timeout=10)

    def save(index):
        barrier.wait()
        try:
            return f.save_price(price_payload(f, expected=1,
                amount=str(115 + index), floor="100"))
        except PostingConflict:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(save, (1, 2)))
    assert sum(result is not None for result in results) == 1
    with f.factory() as db:
        assert db.query(BranchProductPriceRevision).filter_by(
            org_id=f.orgs[0], price_key=f.price_key).count() == 2


def test_permission_and_foreign_company_are_rechecked_on_replay(pricing):
    f = pricing; operation = uuid4()
    f.save_price(price_payload(f, operation=operation))

    def denied(db):
        raise PermissionError("Synthetic pricing permission denied")

    f.authorize = denied
    with pytest.raises(PermissionError):
        f.save_price(price_payload(f, operation=operation))
    f.authorize = lambda db: None
    foreign = OrgContext(current_org_id=f.orgs[1],
        allowed_org_ids=f.orgs, is_root=True)
    with f.factory() as db, pytest.raises(LookupError):
        read_branch_product_price(db, foreign, f.price_key,
            authorize=f.authorize)
    foreign_payload = BranchProductPriceSave(operation_key=uuid4(),
        expected_version=0, branch_id=f.branches[0], product_id=f.products[0],
        unit="PCS",
        config=BranchProductPriceConfig(gross_unit_scr="115",
            is_enabled=True), reason="Foreign attempt")
    with pytest.raises(LookupError):
        save_branch_product_price(f.factory, foreign, f.actor, uuid4(),
            foreign_payload, authorize=f.authorize)


@pytest.mark.parametrize("sql", [
    "UPDATE containermgmt.sales_tax_rule_revisions SET rate=0.10 WHERE tax_rule_key=:key",
    "DELETE FROM containermgmt.sales_tax_rule_revisions WHERE tax_rule_key=:key",
    "UPDATE containermgmt.sales_tax_rules SET code='CHANGED' WHERE tax_rule_key=:key",
])
def test_tax_rule_identity_and_history_are_database_immutable(pricing, sql):
    f = pricing; f.save_tax()
    with f.factory.begin() as db, pytest.raises(DBAPIError):
        db.execute(text(sql), {"key": f.tax_key})


def test_price_history_is_database_immutable_and_consecutive(pricing):
    f = pricing; f.save_price()
    with f.factory.begin() as db, pytest.raises(DBAPIError):
        db.execute(text("UPDATE containermgmt.sales_branch_product_price_revisions "
            "SET gross_unit_scr=99 WHERE price_key=:key"), {"key": f.price_key})
    with f.factory.begin() as db, pytest.raises(DBAPIError):
        db.add(BranchProductPriceRevision(org_id=f.orgs[0],
            price_key=f.price_key, version=3, operation_key=uuid4(),
            gross_unit_scr=Decimal("120"), floor_gross_unit_scr=None,
            is_enabled=True, reason="Invalid skipped version", created_by=f.actor))
        db.flush()


def test_configuration_validation_rejects_float_ambiguous_and_inexact_values(pricing):
    with pytest.raises(ValidationError):
        TaxRuleConfig(name="Bad", treatment="STANDARD", rate=0.15,
            is_enabled=True)
    with pytest.raises(ValidationError):
        TaxRuleConfig(name="Bad", treatment="EXEMPT", rate="0.15",
            is_enabled=True)
    with pytest.raises(ValidationError):
        BranchProductPriceConfig(gross_unit_scr="1.0000001", is_enabled=True)
    with pytest.raises(ValidationError):
        BranchProductPriceConfig(gross_unit_scr="10",
            floor_gross_unit_scr="11", is_enabled=True)


def test_product_tax_assignment_and_customer_agreement_resolve_exact_snapshots(pricing):
    f = pricing; f.save_tax(); f.save_price(); f.save_assignment(); f.save_agreement()
    priced_at = datetime(2026, 6, 1, tzinfo=timezone.utc)
    with f.factory() as db:
        assignment = read_product_tax_assignment(db, f.context,
            f.assignment_key, authorize=f.authorize)
        agreement = read_customer_price_agreement(db, f.context,
            f.agreement_key, authorize=f.authorize)
        line = resolve_pricing_line(db, f.context, line_key=uuid4(),
            branch_id=f.branches[0], product_id=f.products[0],
            unit="PCS", quantity=Decimal("2"), priced_at=priced_at,
            customer_key=f.customer_key, authorize=f.authorize)
    assert assignment.tax_rule_key == f.tax_key and assignment.version == 1
    assert agreement.version == 1
    result = calculate_tax_inclusive_invoice([line])
    assert result.lines[0].selected_price.source == "CUSTOMER_AGREEMENT"
    assert result.lines[0].selected_price.gross_unit_scr == Decimal("105")
    assert result.gross_total_scr == Decimal("210.00")
    assert result.lines[0].tax.code == "VAT15"


def test_customer_agreement_only_wins_when_current_eligible_and_better(pricing):
    f = pricing; f.save_tax(); f.save_price(); f.save_assignment()
    f.save_agreement(agreement_payload(f, amount="120"))
    at = datetime(2026, 6, 1, tzinfo=timezone.utc)
    with f.factory() as db:
        higher = resolve_pricing_line(db, f.context, line_key=uuid4(),
            branch_id=f.branches[0], product_id=f.products[0],
            unit="PCS", quantity=Decimal("1"), priced_at=at,
            customer_key=f.customer_key, authorize=f.authorize)
    assert calculate_tax_inclusive_invoice([higher]).lines[0].selected_price.source == "STORE"
    f.save_agreement(agreement_payload(f, expected=1, amount="90"))
    with f.factory() as db:
        lower = resolve_pricing_line(db, f.context, line_key=uuid4(),
            branch_id=f.branches[0], product_id=f.products[0],
            unit="PCS", quantity=Decimal("1"), priced_at=at,
            customer_key=f.customer_key, authorize=f.authorize)
    result = calculate_tax_inclusive_invoice([lower])
    assert result.lines[0].selected_price.source == "CUSTOMER_AGREEMENT"
    assert result.lines[0].requires_floor_approval


def test_expired_disabled_or_missing_configuration_fails_closed(pricing):
    f = pricing; f.save_tax(); f.save_price(); f.save_assignment()
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    f.save_agreement(agreement_payload(f, amount="90", valid_from=start,
        valid_until=start + timedelta(days=1)))
    with f.factory() as db:
        expired = resolve_pricing_line(db, f.context, line_key=uuid4(),
            branch_id=f.branches[0], product_id=f.products[0],
            unit="PCS", quantity=Decimal("1"),
            priced_at=start + timedelta(days=2),
            customer_key=f.customer_key, authorize=f.authorize)
    assert len(expired.eligible_prices) == 1
    f.save_assignment(assignment_payload(f, expected=1, enabled=False))
    with f.factory() as db, pytest.raises(PostingConflict, match="disabled"):
        resolve_pricing_line(db, f.context, line_key=uuid4(),
            branch_id=f.branches[0], product_id=f.products[0],
            unit="PCS", quantity=Decimal("1"), priced_at=start,
            customer_key=None, authorize=f.authorize)


def test_pricing_links_are_append_only_replay_safe_and_do_not_merge_customer(pricing):
    f = pricing; f.save_tax()
    assignment_op = uuid4(); agreement_op = uuid4()
    assert not f.save_assignment(assignment_payload(f,
        operation=assignment_op)).replayed
    assert f.save_assignment(assignment_payload(f,
        operation=assignment_op)).replayed
    assert not f.save_agreement(agreement_payload(f,
        operation=agreement_op)).replayed
    assert f.save_agreement(agreement_payload(f,
        operation=agreement_op)).replayed
    with f.factory() as db:
        assert db.query(ProductTaxAssignment).filter_by(
            org_id=f.orgs[0]).count() == 1
        assert db.query(CustomerPriceAgreement).filter_by(
            org_id=f.orgs[0], customer_key=f.customer_key).count() == 1


def test_concurrent_customer_agreement_update_has_one_winner(pricing):
    f = pricing; f.save_agreement(); barrier = Barrier(2, timeout=10)

    def save(index):
        barrier.wait()
        try:
            return f.save_agreement(agreement_payload(f, expected=1,
                amount=str(100 + index)))
        except PostingConflict:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(save, (1, 2)))
    assert sum(result is not None for result in results) == 1
    with f.factory() as db:
        assert db.query(CustomerPriceAgreementRevision).filter_by(
            org_id=f.orgs[0], agreement_key=f.agreement_key).count() == 2


@pytest.mark.parametrize("table,key_column,key_attribute", [
    ("sales_product_tax_assignment_revisions", "assignment_key", "assignment_key"),
    ("sales_customer_price_agreement_revisions", "agreement_key", "agreement_key"),
])
def test_assignment_and_agreement_revisions_are_database_immutable(
        pricing, table, key_column, key_attribute):
    f = pricing; f.save_tax(); f.save_assignment(); f.save_agreement()
    with f.factory.begin() as db, pytest.raises(DBAPIError):
        db.execute(text(f"DELETE FROM containermgmt.{table} "
            f"WHERE {key_column}=:key"), {"key": getattr(f, key_attribute)})


def test_sales_pricing_migration_replay_preserves_history(pricing, monkeypatch):
    from Utils import migrate_20261004_sales_pricing as migration
    f = pricing; f.save_tax(); f.save_price()
    monkeypatch.setattr(migration, "engine", f.factory.kw["bind"])
    migration.ensure_sales_pricing_schema()
    migration.ensure_sales_pricing_schema()
    with f.factory() as db:
        assert read_tax_rule(db, f.context, f.tax_key,
            authorize=f.authorize).version == 1
        assert read_branch_product_price(db, f.context, f.price_key,
            authorize=f.authorize).version == 1
