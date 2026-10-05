from decimal import Decimal
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from Model.containermgmt.Orders.SalesReturn import (
    ALLOCATION_GUARD_FUNCTION,
    CLAIM_GUARD_FUNCTION,
    CREDIT_GUARD_FUNCTION,
    MONEY_CHILD_GUARD_FUNCTION,
    LINEAGE_GUARD_FUNCTION,
    RETURN_MOVEMENT_GUARD_FUNCTION,
    RETURN_VALUATION_GUARD_FUNCTION,
    SalesCreditNote,
    SalesCreditNoteLine,
)
from Schema.SalesReturnSchema import (
    SalesReturnClaimCreate,
    SalesReturnCreditNoteCreate,
)


def claim_payload():
    return dict(
        return_key=uuid4(),
        operation_key=uuid4(),
        invoice_key=uuid4(),
        expected_invoice_version=1,
        returner_name="Synthetic Customer",
        returner_contact="0000000",
        reason="Synthetic damaged packaging review",
        lines=[dict(
            invoice_line_key=uuid4(),
            handover_allocation_key=uuid4(),
            quantity="1.250000",
            condition="OPENED",
        )],
    )


def test_return_claim_requires_exact_decimal_and_unique_handover():
    payload = claim_payload()
    parsed = SalesReturnClaimCreate(**payload)
    assert parsed.lines[0].quantity == Decimal("1.250000")

    payload["lines"][0]["quantity"] = 1.25
    with pytest.raises(ValidationError, match="exact decimal string"):
        SalesReturnClaimCreate(**payload)

    payload = claim_payload()
    payload["lines"].append(dict(payload["lines"][0]))
    with pytest.raises(ValidationError, match="only once"):
        SalesReturnClaimCreate(**payload)


def test_return_claim_rejects_unknown_condition_and_extra_fields():
    payload = claim_payload()
    payload["lines"][0]["condition"] = "SELLABLE"
    with pytest.raises(ValidationError):
        SalesReturnClaimCreate(**payload)
    payload = claim_payload()
    payload["refund_now"] = True
    with pytest.raises(ValidationError, match="Extra inputs"):
        SalesReturnClaimCreate(**payload)


def test_credit_post_binds_claim_and_processing_fingerprint():
    request = SalesReturnCreditNoteCreate(
        operation_key=uuid4(),
        expected_claim_version=2,
        expected_option_version=1,
        expected_fingerprint="a" * 64,
    )
    assert request.expected_fingerprint == "a" * 64
    with pytest.raises(ValidationError):
        SalesReturnCreditNoteCreate(
            operation_key=uuid4(),
            expected_claim_version=2,
            expected_option_version=1,
            expected_fingerprint="not-a-fingerprint",
        )


def test_return_cost_uses_cumulative_rounding_and_exact_final_residual():
    from Services.inventory_return_movement_service import _proportional_issue_cost

    first = _proportional_issue_cost(
        Decimal("3.000000"), Decimal("1.000000"),
        Decimal("0.000000"), Decimal("0.000000"), Decimal("1.000000"),
    )
    second = _proportional_issue_cost(
        Decimal("3.000000"), Decimal("1.000000"),
        Decimal("1.000000"), first, Decimal("1.000000"),
    )
    final = _proportional_issue_cost(
        Decimal("3.000000"), Decimal("1.000000"),
        Decimal("2.000000"), first + second, Decimal("1.000000"),
    )
    assert (first, second, final) == (
        Decimal("0.333333"), Decimal("0.333334"), Decimal("0.333333"))
    assert first + second + final == Decimal("1.000000")


def test_return_money_rounds_net_and_tax_then_conserves_final_line():
    from Services.sales_return_service import _cumulative_money

    half_net = _cumulative_money(Decimal("0.04"), Decimal("1"), Decimal("2"))
    half_tax = _cumulative_money(Decimal("0.01"), Decimal("1"), Decimal("2"))
    assert (half_net, half_tax, half_net + half_tax) == (
        Decimal("0.02"), Decimal("0.01"), Decimal("0.03"))
    assert _cumulative_money(Decimal("0.04"), Decimal("2"), Decimal("2")) == Decimal("0.04")
    # Two approved physical claims can legitimately split a one-cent line.
    # The first cumulative target is SCR0.01 and the second marginal note is
    # SCR0.00; both remain valid stock/cost reversals.
    first = _cumulative_money(Decimal("0.01"), Decimal("1"), Decimal("2"))
    second = (_cumulative_money(Decimal("0.01"), Decimal("2"), Decimal("2"))
              - first)
    assert (first, second, first + second) == (
        Decimal("0.01"), Decimal("0.00"), Decimal("0.01"))


def test_credit_header_and_physical_lines_may_round_to_zero():
    header = next(constraint for constraint in SalesCreditNote.__table__.constraints
                  if constraint.name == "ck_sales_credit_note_totals")
    line = next(constraint for constraint in SalesCreditNoteLine.__table__.constraints
                if constraint.name == "ck_sales_credit_note_line_values")
    assert "gross_credit_scr >= 0" in str(header.sqltext)
    assert "gross_credit_scr >= 0" in str(line.sqltext)


def test_credit_operation_effect_is_json_safe_for_replay():
    from Services.sales_return_service import _credit_effect_snapshot

    keys = [uuid4() for _ in range(5)]
    snapshot = _credit_effect_snapshot(dict(
        credit_note_key=keys[0],
        credit_note_number="CN-TEST-0001",
        return_key=keys[1],
        invoice_key=keys[2],
        invoice_number="INV-TEST-0001",
        branch_id=1,
        customer_key=keys[3],
        currency="SCR",
        gross_credit_scr="0.00",
        net_credit_scr="0.00",
        tax_credit_scr="0.00",
        invoice_debt_applied_scr="0.00",
        customer_credit_scr="0.00",
        issued_at=datetime(2026, 10, 5, 1, 2, 3, tzinfo=timezone.utc),
        issued_by=7,
        lines=[dict(
            invoice_line_key=keys[4],
            handover_allocation_key=uuid4(),
            quantity="1.000000",
            base_unit="EA",
            gross_credit_scr="0.00",
            net_credit_scr="0.00",
            tax_credit_scr="0.00",
        )],
    ))

    assert snapshot["credit_note_key"] == str(keys[0])
    assert snapshot["issued_at"] == "2026-10-05T01:02:03Z"
    assert isinstance(snapshot["lines"][0]["invoice_line_key"], str)
    assert not any(isinstance(value, UUID) for value in snapshot.values())


def test_return_database_guards_bind_review_stock_value_and_credit():
    assert "sales.return.claim" in CLAIM_GUARD_FUNCTION
    assert "branch_id<>NEW.branch_id" in CLAIM_GUARD_FUNCTION
    assert "customer_key<>NEW.customer_key" in CLAIM_GUARD_FUNCTION
    assert "sales.return.credit.v1" in CREDIT_GUARD_FUNCTION
    assert "manager_case_uses" in CREDIT_GUARD_FUNCTION
    assert "binding_matches<>1" in ALLOCATION_GUARD_FUNCTION
    assert "claim.created_by<>NEW.created_by" in ALLOCATION_GUARD_FUNCTION
    assert "debt before customer credit" in MONEY_CHILD_GUARD_FUNCTION
    assert "NEW.invoice_key<>credit.invoice_key" in MONEY_CHILD_GUARD_FUNCTION
    assert "NEW.customer_key<>credit.customer_key" in MONEY_CHILD_GUARD_FUNCTION
    assert "credit.created_by<>NEW.created_by" in MONEY_CHILD_GUARD_FUNCTION
    assert "inventory.return.receive.v1" in RETURN_MOVEMENT_GUARD_FUNCTION
    assert "matches<>1" in RETURN_MOVEMENT_GUARD_FUNCTION
    assert "inventory_stock_balances" in RETURN_MOVEMENT_GUARD_FUNCTION
    assert "balance.version<>NEW.version" in RETURN_MOVEMENT_GUARD_FUNCTION
    assert "inventory.return.receive.v1" in RETURN_VALUATION_GUARD_FUNCTION
    assert "matches<>1" in RETURN_VALUATION_GUARD_FUNCTION
    assert "Cumulative restored cost" in LINEAGE_GUARD_FUNCTION
    assert "issue.operation_key<>NEW.handover_allocation_key" in LINEAGE_GUARD_FUNCTION
    assert "issue.balance_id<>NEW.balance_id" in LINEAGE_GUARD_FUNCTION
    assert "id=NEW.source_issue_valuation_id FOR UPDATE" in LINEAGE_GUARD_FUNCTION
    assert "credit.return_key<>allocation.return_key" in LINEAGE_GUARD_FUNCTION
    assert "line_totals.gross<>credit.gross_credit_scr" in LINEAGE_GUARD_FUNCTION
    assert "line_cumulative.quantity>invoice_line.base_quantity" in LINEAGE_GUARD_FUNCTION
    assert "Cumulative credit must remain proportional" in LINEAGE_GUARD_FUNCTION
    assert "line_key=NEW.invoice_line_key FOR UPDATE" in LINEAGE_GUARD_FUNCTION


def test_return_router_uses_one_sales_return_contract():
    from Routes.Orders.SalesReturnRouter import SalesReturnRouter

    paths = {route.path for route in SalesReturnRouter.routes}
    assert paths == {
        "/sales/invoices/{invoice_key}/return-options",
        "/sales/drafts/{document_key}/posted-invoice",
        "/sales/returns/{return_key}",
        "/sales/returns/{return_key}/review",
        "/sales/returns/{return_key}/processing-options",
        "/sales/returns/{return_key}/credit-note",
        "/sales/invoices/{invoice_key}/returns",
        "/sales/invoices/{invoice_key}/credit-notes",
        "/sales/credit-notes/{credit_note_key}",
    }
