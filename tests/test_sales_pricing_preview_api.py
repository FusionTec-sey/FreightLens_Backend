"""Sales-facing price preview uses current T11 configuration and posts nothing."""
from dataclasses import replace
from datetime import datetime, timezone
from uuid import uuid4

from Schema.SalesPricingSchema import (
    BranchProductPriceConfig, BranchProductPriceSave,
    CustomerPriceAgreementConfig, CustomerPriceAgreementSave,
    ProductTaxAssignmentSave, TaxRuleConfig, TaxRuleSave,
)
from Services.sales_pricing_configuration_service import (
    save_branch_product_price, save_customer_price_agreement,
    save_product_tax_assignment, save_tax_rule,
)
from tests.test_sales_intent_api import api  # noqa: F401
from tests.test_sales_intent_sources import source  # noqa: F401
from tests.test_policy_activation import activation  # noqa: F401
from tests.test_policy_manager_cases import policy_cases  # noqa: F401
from tests.test_inventory_policy_drafts import draft  # noqa: F401
from tests.test_inventory_locations import locations  # noqa: F401


def configured_preview(f):
    authorize = lambda db: None
    tax_key, assignment_key, price_key, agreement_key = (
        uuid4(), uuid4(), uuid4(), uuid4())
    calls = [
        lambda: save_tax_rule(f.db, f.context, f.user.id, tax_key,
            TaxRuleSave(operation_key=uuid4(), expected_version=0,
                code="VAT15", config=TaxRuleConfig(name="Synthetic VAT",
                    treatment="STANDARD", rate="0.15", is_enabled=True),
                reason="Synthetic preview tax"), authorize=authorize),
        lambda: save_product_tax_assignment(f.db, f.context, f.user.id,
            assignment_key, ProductTaxAssignmentSave(operation_key=uuid4(),
                expected_version=0, product_id=f.product.id,
                tax_rule_key=tax_key, is_enabled=True,
                reason="Synthetic preview classification"),
            authorize=authorize),
        lambda: save_branch_product_price(f.db, f.context, f.user.id,
            price_key, BranchProductPriceSave(operation_key=uuid4(),
                expected_version=0, branch_id=f.own,
                product_id=f.product.id, unit="BOX",
                config=BranchProductPriceConfig(gross_unit_scr="1200",
                    floor_gross_unit_scr="1150", is_enabled=True),
                reason="Synthetic BOX store price"), authorize=authorize),
        lambda: save_customer_price_agreement(f.db, f.context, f.user.id,
            agreement_key, CustomerPriceAgreementSave(operation_key=uuid4(),
                expected_version=0, customer_key=f.customer_key,
                branch_id=f.own, product_id=f.product.id, unit="BOX",
                config=CustomerPriceAgreementConfig(gross_unit_scr="1100",
                    valid_from=datetime(2020, 1, 1, tzinfo=timezone.utc),
                    terms_reference="Synthetic signed schedule",
                    is_enabled=True), reason="Synthetic customer price"),
            authorize=authorize),
    ]
    for call in calls:
        f.db.connection(); call(); f.db.commit()


def test_missing_price_configuration_blocks_preview_without_blocking_draft(api):
    f = api
    assert f.client.put(f.url, json=f.payload).status_code == 200
    response = f.client.get(f"{f.url}/pricing-preview")
    assert response.status_code == 409
    assert response.json()["detail"].startswith("Pricing configuration incomplete:")
    assert f.client.get(f.url).status_code == 200


def test_preview_resolves_unit_store_customer_tax_and_floor_without_posting(api):
    from Model.containermgmt.Inventory.PostingOperation import PostingOperation
    f = api
    assert f.client.put(f.url, json=f.payload).status_code == 200
    configured_preview(f)
    before = f.db.query(PostingOperation).filter_by(org_id=f.org_a).count()
    response = f.client.get(f"{f.url}/pricing-preview")
    assert response.status_code == 200, response.text
    data = response.json(); line = data["lines"][0]
    assert data["status"] == "READY" and data["currency"] == "SCR"
    assert data["gross_total_scr"] == "2200.00"
    assert data["tax_total_scr"] == "286.96"
    assert data["posting_enabled"] is False
    assert line["quantity"] == "2.000000"
    assert line["selected_source"] == "CUSTOMER_AGREEMENT"
    assert line["gross_unit_scr"] == "1100.000000"
    assert line["store_gross_unit_scr"] == "1200.000000"
    assert line["tax_code"] == "VAT15"
    assert line["requires_floor_approval"] is True
    f.db.expire_all()
    assert f.db.query(PostingOperation).filter_by(org_id=f.org_a).count() == before


def test_preview_enforces_existing_sales_access_and_tenant_scope(api):
    f = api
    assert f.client.put(f.url, json=f.payload).status_code == 200
    configured_preview(f)
    policy = f.user.access_policy
    f.user.access_policy = replace(policy,
        permission_names=frozenset(f.permissions - {"View_Product"}))
    assert f.client.get(f"{f.url}/pricing-preview").status_code == 403
    f.user.access_policy = policy
    f.context.current_org_id = f.org_b
    f.context.allowed_org_ids = [f.org_a, f.org_b]
    f.context.is_root = True
    assert f.client.get(f"{f.url}/pricing-preview").status_code == 404
