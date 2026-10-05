"""Immutable, handover-linked sales returns and customer credit notes.

Return requests are immutable claims reviewed through the shared manager-case
engine.  Rejected claims stop consuming eligibility; requested, approved and
credited claims remain part of the cumulative cap.  Accepted goods are restored
to the exact handed-over balance in quarantine and never reopen a reservation.
"""
from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    DDL,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    event,
    func,
)
from sqlalchemy.dialects.postgresql import UUID

from Model.db import Base
from Model.mixins import AuditMixin, OrgMixin
from Model.containermgmt.Inventory.ManagerCase import ManagerCase  # noqa: F401
from Model.containermgmt.Inventory.PostingOperation import PostingOperation  # noqa: F401
from Model.containermgmt.Inventory.StockLedger import StockBalance, StockMovement  # noqa: F401
from Model.containermgmt.Inventory.Valuation import InventoryValuation  # noqa: F401
from Model.containermgmt.MasterData.RetailCustomer import RetailCustomer  # noqa: F401
from Model.containermgmt.Orders.SalesCollection import (  # noqa: F401
    SalesCollection,
    SalesCollectionAllocation,
)
from Model.containermgmt.Orders.SalesPosting import (  # noqa: F401
    SalesInvoice,
    SalesInvoiceLine,
)


NONZERO_UUID = "<> '00000000-0000-0000-0000-000000000000'::uuid"
AUDIT_CHECK = "created_by IS NOT NULL AND NOT is_deleted AND deleted_at IS NULL"


class SalesReturnClaim(OrgMixin, AuditMixin, Base):
    __tablename__ = "sales_return_claims"
    __table_args__ = (
        UniqueConstraint("return_key", "org_id", name="uq_sales_return_claim_scope"),
        UniqueConstraint("org_id", "operation_key", name="uq_sales_return_request_operation"),
        ForeignKeyConstraint(
            ["invoice_key", "org_id"],
            ["containermgmt.sales_invoices.invoice_key", "containermgmt.sales_invoices.org_id"],
            name="fk_sales_return_invoice",
        ),
        ForeignKeyConstraint(
            ["customer_key", "org_id"],
            ["containermgmt.retail_customers.customer_key", "containermgmt.retail_customers.org_id"],
            name="fk_sales_return_customer",
        ),
        ForeignKeyConstraint(
            ["org_id", "operation_key"],
            ["containermgmt.inventory_posting_operations.org_id",
             "containermgmt.inventory_posting_operations.operation_key"],
            name="fk_sales_return_request_operation",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["org_id", "return_key"],
            ["containermgmt.manager_cases.org_id", "containermgmt.manager_cases.case_key"],
            name="fk_sales_return_manager_case",
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint(
            f"return_key {NONZERO_UUID} AND operation_key {NONZERO_UUID} "
            "AND invoice_version = 1 AND length(trim(returner_name)) BETWEEN 1 AND 150 "
            "AND length(trim(returner_contact)) BETWEEN 1 AND 50 "
            "AND length(trim(reason)) BETWEEN 1 AND 1000",
            name="ck_sales_return_claim_identity",
        ),
        CheckConstraint(AUDIT_CHECK, name="ck_sales_return_claim_audit"),
        Index("ix_sales_return_claim_invoice", "org_id", "invoice_key", "requested_at"),
        Index("ix_sales_return_claim_customer", "org_id", "customer_key", "requested_at"),
        {"schema": "containermgmt"},
    )
    return_key = Column(UUID(as_uuid=True), primary_key=True)
    operation_key = Column(UUID(as_uuid=True), nullable=False)
    invoice_key = Column(UUID(as_uuid=True), nullable=False)
    invoice_version = Column(Integer, nullable=False)
    branch_id = Column(Integer, nullable=False)
    customer_key = Column(UUID(as_uuid=True), nullable=False)
    returner_name = Column(String(150), nullable=False)
    returner_contact = Column(String(50), nullable=False)
    reason = Column(String(1000), nullable=False)
    requested_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SalesReturnAllocation(OrgMixin, AuditMixin, Base):
    """One exact claimed quantity from one immutable T16 handover allocation."""

    __tablename__ = "sales_return_allocations"
    __table_args__ = (
        UniqueConstraint("id", "org_id", name="uq_sales_return_allocation_id_org"),
        UniqueConstraint(
            "org_id", "return_key", "handover_allocation_key",
            name="uq_sales_return_claim_handover",
        ),
        ForeignKeyConstraint(
            ["return_key", "org_id"],
            ["containermgmt.sales_return_claims.return_key",
             "containermgmt.sales_return_claims.org_id"],
            name="fk_sales_return_allocation_claim",
        ),
        ForeignKeyConstraint(
            ["org_id", "invoice_key", "invoice_line_key"],
            ["containermgmt.sales_invoice_lines.org_id",
             "containermgmt.sales_invoice_lines.invoice_key",
             "containermgmt.sales_invoice_lines.line_key"],
            name="fk_sales_return_allocation_invoice_line",
        ),
        ForeignKeyConstraint(
            ["collection_key", "org_id"],
            ["containermgmt.sales_collections.collection_key",
             "containermgmt.sales_collections.org_id"],
            name="fk_sales_return_allocation_collection",
        ),
        ForeignKeyConstraint(
            ["balance_id", "org_id"],
            ["containermgmt.inventory_stock_balances.id",
             "containermgmt.inventory_stock_balances.org_id"],
            name="fk_sales_return_allocation_balance",
        ),
        CheckConstraint(
            f"handover_allocation_key {NONZERO_UUID} AND quantity > 0 "
            "AND quantity < 1000000000000 AND length(trim(base_unit)) BETWEEN 1 AND 50",
            name="ck_sales_return_allocation_quantity",
        ),
        CheckConstraint(
            "condition IN ('UNOPENED','OPENED','DAMAGED','UNKNOWN')",
            name="ck_sales_return_allocation_condition",
        ),
        CheckConstraint(AUDIT_CHECK, name="ck_sales_return_allocation_audit"),
        Index("ix_sales_return_allocation_line", "org_id", "invoice_key", "invoice_line_key"),
        Index("ix_sales_return_allocation_handover", "org_id", "handover_allocation_key"),
        {"schema": "containermgmt"},
    )
    id = Column(Integer, primary_key=True)
    return_key = Column(UUID(as_uuid=True), nullable=False)
    invoice_key = Column(UUID(as_uuid=True), nullable=False)
    invoice_line_key = Column(UUID(as_uuid=True), nullable=False)
    handover_allocation_key = Column(UUID(as_uuid=True), nullable=False)
    collection_key = Column(UUID(as_uuid=True), nullable=False)
    balance_id = Column(Integer, nullable=False)
    location_id = Column(Integer, nullable=False)
    batch_key = Column(UUID(as_uuid=True), nullable=True)
    quantity = Column(Numeric(18, 6), nullable=False)
    base_unit = Column(String(50), nullable=False)
    condition = Column(String(16), nullable=False)


class SalesCreditNote(OrgMixin, AuditMixin, Base):
    __tablename__ = "sales_credit_notes"
    __table_args__ = (
        UniqueConstraint("credit_note_key", "org_id", name="uq_sales_credit_note_scope"),
        UniqueConstraint("org_id", "credit_note_number", name="uq_sales_credit_note_number"),
        UniqueConstraint("org_id", "return_key", name="uq_sales_credit_note_return"),
        UniqueConstraint("org_id", "operation_key", name="uq_sales_credit_note_operation"),
        ForeignKeyConstraint(
            ["return_key", "org_id"],
            ["containermgmt.sales_return_claims.return_key",
             "containermgmt.sales_return_claims.org_id"],
            name="fk_sales_credit_note_return",
        ),
        ForeignKeyConstraint(
            ["invoice_key", "org_id"],
            ["containermgmt.sales_invoices.invoice_key", "containermgmt.sales_invoices.org_id"],
            name="fk_sales_credit_note_invoice",
        ),
        ForeignKeyConstraint(
            ["customer_key", "org_id"],
            ["containermgmt.retail_customers.customer_key", "containermgmt.retail_customers.org_id"],
            name="fk_sales_credit_note_customer",
        ),
        ForeignKeyConstraint(
            ["org_id", "operation_key"],
            ["containermgmt.inventory_posting_operations.org_id",
             "containermgmt.inventory_posting_operations.operation_key"],
            name="fk_sales_credit_note_operation",
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint(
            f"credit_note_key {NONZERO_UUID} AND operation_key {NONZERO_UUID} "
            "AND length(trim(credit_note_number)) BETWEEN 1 AND 64 "
            "AND processing_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_sales_credit_note_identity",
        ),
        CheckConstraint(
            "currency = 'SCR' AND gross_credit_scr >= 0 "
            "AND net_credit_scr >= 0 AND tax_credit_scr >= 0 "
            "AND gross_credit_scr = net_credit_scr + tax_credit_scr",
            name="ck_sales_credit_note_totals",
        ),
        CheckConstraint(AUDIT_CHECK, name="ck_sales_credit_note_audit"),
        Index("ix_sales_credit_note_invoice", "org_id", "invoice_key", "issued_at"),
        Index("ix_sales_credit_note_customer", "org_id", "customer_key", "issued_at"),
        {"schema": "containermgmt"},
    )
    credit_note_key = Column(UUID(as_uuid=True), primary_key=True)
    credit_note_number = Column(String(64), nullable=False)
    return_key = Column(UUID(as_uuid=True), nullable=False)
    operation_key = Column(UUID(as_uuid=True), nullable=False)
    processing_fingerprint = Column(String(64), nullable=False)
    invoice_key = Column(UUID(as_uuid=True), nullable=False)
    invoice_number = Column(String(64), nullable=False)
    branch_id = Column(Integer, nullable=False)
    customer_key = Column(UUID(as_uuid=True), nullable=False)
    currency = Column(String(3), nullable=False)
    gross_credit_scr = Column(Numeric(24, 2), nullable=False)
    net_credit_scr = Column(Numeric(24, 2), nullable=False)
    tax_credit_scr = Column(Numeric(24, 2), nullable=False)
    issued_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SalesCreditNoteLine(OrgMixin, AuditMixin, Base):
    __tablename__ = "sales_credit_note_lines"
    __table_args__ = (
        UniqueConstraint("id", "org_id", name="uq_sales_credit_note_line_id_org"),
        UniqueConstraint(
            "org_id", "credit_note_key", "return_allocation_id",
            name="uq_sales_credit_note_return_allocation",
        ),
        UniqueConstraint(
            "org_id", "return_operation_key",
            name="uq_sales_credit_note_return_operation",
        ),
        ForeignKeyConstraint(
            ["credit_note_key", "org_id"],
            ["containermgmt.sales_credit_notes.credit_note_key",
             "containermgmt.sales_credit_notes.org_id"],
            name="fk_sales_credit_note_line_header",
        ),
        ForeignKeyConstraint(
            ["return_allocation_id", "org_id"],
            ["containermgmt.sales_return_allocations.id",
             "containermgmt.sales_return_allocations.org_id"],
            name="fk_sales_credit_note_line_return_allocation",
        ),
        ForeignKeyConstraint(
            ["org_id", "invoice_key", "invoice_line_key"],
            ["containermgmt.sales_invoice_lines.org_id",
             "containermgmt.sales_invoice_lines.invoice_key",
             "containermgmt.sales_invoice_lines.line_key"],
            name="fk_sales_credit_note_line_invoice_line",
        ),
        ForeignKeyConstraint(
            ["org_id", "return_operation_key"],
            ["containermgmt.inventory_posting_operations.org_id",
             "containermgmt.inventory_posting_operations.operation_key"],
            name="fk_sales_credit_note_line_return_operation",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["source_issue_valuation_id", "org_id"],
            ["containermgmt.inventory_valuations.id", "containermgmt.inventory_valuations.org_id"],
            name="fk_sales_credit_note_line_source_issue",
        ),
        ForeignKeyConstraint(
            ["return_valuation_id", "org_id"],
            ["containermgmt.inventory_valuations.id", "containermgmt.inventory_valuations.org_id"],
            name="fk_sales_credit_note_line_return_value",
        ),
        CheckConstraint(
            f"handover_allocation_key {NONZERO_UUID} "
            f"AND return_operation_key {NONZERO_UUID} "
            "AND quantity > 0 AND quantity < 1000000000000 "
            "AND source_issue_valuation_id > 0 AND return_valuation_id > 0",
            name="ck_sales_credit_note_line_identity",
        ),
        CheckConstraint(
            "gross_credit_scr >= 0 AND net_credit_scr >= 0 AND tax_credit_scr >= 0 "
            "AND gross_credit_scr = net_credit_scr + tax_credit_scr "
            "AND restored_cost_scr >= 0",
            name="ck_sales_credit_note_line_values",
        ),
        CheckConstraint(AUDIT_CHECK, name="ck_sales_credit_note_line_audit"),
        Index("ix_sales_credit_note_line_invoice", "org_id", "invoice_key", "invoice_line_key"),
        {"schema": "containermgmt"},
    )
    id = Column(Integer, primary_key=True)
    credit_note_key = Column(UUID(as_uuid=True), nullable=False)
    return_allocation_id = Column(Integer, nullable=False)
    invoice_key = Column(UUID(as_uuid=True), nullable=False)
    invoice_line_key = Column(UUID(as_uuid=True), nullable=False)
    handover_allocation_key = Column(UUID(as_uuid=True), nullable=False)
    balance_id = Column(Integer, nullable=False)
    return_operation_key = Column(UUID(as_uuid=True), nullable=False)
    source_issue_valuation_id = Column(Integer, nullable=False)
    return_valuation_id = Column(Integer, nullable=False)
    quantity = Column(Numeric(18, 6), nullable=False)
    base_unit = Column(String(50), nullable=False)
    gross_credit_scr = Column(Numeric(24, 2), nullable=False)
    net_credit_scr = Column(Numeric(24, 2), nullable=False)
    tax_credit_scr = Column(Numeric(24, 2), nullable=False)
    restored_cost_scr = Column(Numeric(24, 6), nullable=False)


class SalesInvoiceDebtApplication(OrgMixin, AuditMixin, Base):
    """Credit-note value applied to unpaid invoice debt before surplus credit."""

    __tablename__ = "sales_invoice_debt_applications"
    __table_args__ = (
        UniqueConstraint("org_id", "credit_note_key", name="uq_sales_return_debt_credit_note"),
        ForeignKeyConstraint(
            ["credit_note_key", "org_id"],
            ["containermgmt.sales_credit_notes.credit_note_key",
             "containermgmt.sales_credit_notes.org_id"],
            name="fk_sales_return_debt_credit_note",
        ),
        ForeignKeyConstraint(
            ["invoice_key", "org_id"],
            ["containermgmt.sales_invoices.invoice_key", "containermgmt.sales_invoices.org_id"],
            name="fk_sales_return_debt_invoice",
        ),
        CheckConstraint("amount_scr > 0", name="ck_sales_return_debt_amount"),
        CheckConstraint(AUDIT_CHECK, name="ck_sales_return_debt_audit"),
        Index("ix_sales_return_debt_invoice", "org_id", "invoice_key", "id"),
        {"schema": "containermgmt"},
    )
    id = Column(Integer, primary_key=True)
    credit_note_key = Column(UUID(as_uuid=True), nullable=False)
    invoice_key = Column(UUID(as_uuid=True), nullable=False)
    amount_scr = Column(Numeric(24, 2), nullable=False)


class CustomerCreditLiabilityEntry(OrgMixin, AuditMixin, Base):
    """Append-only non-expiring customer credit; redemption is deliberately absent."""

    __tablename__ = "customer_credit_liability_entries"
    __table_args__ = (
        UniqueConstraint("entry_key", "org_id", name="uq_customer_credit_entry_scope"),
        UniqueConstraint("org_id", "credit_note_key", name="uq_customer_credit_note_liability"),
        ForeignKeyConstraint(
            ["credit_note_key", "org_id"],
            ["containermgmt.sales_credit_notes.credit_note_key",
             "containermgmt.sales_credit_notes.org_id"],
            name="fk_customer_credit_note_liability",
        ),
        ForeignKeyConstraint(
            ["customer_key", "org_id"],
            ["containermgmt.retail_customers.customer_key",
             "containermgmt.retail_customers.org_id"],
            name="fk_customer_credit_customer",
        ),
        CheckConstraint(
            f"entry_key {NONZERO_UUID} AND kind = 'RETURN_SURPLUS' "
            "AND currency = 'SCR' AND amount_scr > 0",
            name="ck_customer_credit_liability",
        ),
        CheckConstraint(AUDIT_CHECK, name="ck_customer_credit_audit"),
        Index("ix_customer_credit_customer", "org_id", "customer_key", "created_at"),
        {"schema": "containermgmt"},
    )
    entry_key = Column(UUID(as_uuid=True), primary_key=True)
    credit_note_key = Column(UUID(as_uuid=True), nullable=False)
    customer_key = Column(UUID(as_uuid=True), nullable=False)
    kind = Column(String(24), nullable=False)
    currency = Column(String(3), nullable=False)
    amount_scr = Column(Numeric(24, 2), nullable=False)


MODELS = (
    SalesReturnClaim,
    SalesReturnAllocation,
    SalesCreditNote,
    SalesCreditNoteLine,
    SalesInvoiceDebtApplication,
    CustomerCreditLiabilityEntry,
)


IMMUTABLE_FUNCTION = """CREATE OR REPLACE FUNCTION containermgmt.reject_sales_return_change()
RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
RAISE EXCEPTION 'Sales return and credit history is immutable'; END; $$"""


def immutable_trigger(table: str) -> str:
    return f"""CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE
ON containermgmt.{table} FOR EACH ROW
EXECUTE FUNCTION containermgmt.reject_sales_return_change()"""


CLAIM_GUARD_FUNCTION = """CREATE OR REPLACE FUNCTION containermgmt.check_sales_return_claim()
RETURNS trigger LANGUAGE plpgsql AS $$ DECLARE operation record; review record; invoice record; line_count integer; BEGIN
SELECT kind, created_by INTO operation FROM containermgmt.inventory_posting_operations
 WHERE org_id=NEW.org_id AND operation_key=NEW.operation_key;
SELECT action, source_type, source_key, source_version, created_by INTO review
 FROM containermgmt.manager_cases
 WHERE org_id=NEW.org_id AND case_key=NEW.return_key;
SELECT branch_id, customer_key INTO invoice FROM containermgmt.sales_invoices
 WHERE org_id=NEW.org_id AND invoice_key=NEW.invoice_key;
SELECT COUNT(*) INTO line_count FROM containermgmt.sales_return_allocations
 WHERE org_id=NEW.org_id AND return_key=NEW.return_key;
IF operation IS NULL OR operation.kind<>'sales.return.request.v1'
 OR operation.created_by<>NEW.created_by THEN
 RAISE EXCEPTION 'Return claim requires its exact request operation'; END IF;
IF review IS NULL OR review.action<>'sales.return.claim'
 OR review.source_type<>'sales.return' OR review.source_key<>NEW.return_key::text
 OR review.source_version<>1 OR review.created_by<>NEW.created_by THEN
 RAISE EXCEPTION 'Return claim requires its exact manager case'; END IF;
IF invoice IS NULL OR invoice.branch_id<>NEW.branch_id
 OR invoice.customer_key<>NEW.customer_key THEN
 RAISE EXCEPTION 'Return claim must preserve invoice store and customer'; END IF;
IF line_count<1 THEN RAISE EXCEPTION 'Return claim requires an exact handover allocation'; END IF;
RETURN NULL; END; $$"""
CLAIM_GUARD_TRIGGER = """CREATE CONSTRAINT TRIGGER sales_return_claim_guard
AFTER INSERT ON containermgmt.sales_return_claims DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION containermgmt.check_sales_return_claim()"""


ALLOCATION_GUARD_FUNCTION = """CREATE OR REPLACE FUNCTION containermgmt.check_sales_return_allocation()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE claim record; handed record; active_claimed numeric; binding_matches integer; BEGIN
SELECT invoice_key, branch_id, created_by INTO claim
 FROM containermgmt.sales_return_claims
 WHERE org_id=NEW.org_id AND return_key=NEW.return_key;
SELECT a.collection_key, a.invoice_key, a.line_key, a.balance_id, a.location_id,
 a.batch_key, a.quantity, a.base_unit, c.branch_id
 INTO handed
 FROM containermgmt.sales_collection_allocations a
 JOIN containermgmt.sales_collections c
   ON c.org_id=a.org_id AND c.collection_key=a.collection_key
 WHERE a.org_id=NEW.org_id AND a.handover_operation_key=NEW.handover_allocation_key
 FOR UPDATE OF a;
IF claim IS NULL OR handed IS NULL OR claim.invoice_key<>NEW.invoice_key
 OR claim.invoice_key<>handed.invoice_key OR claim.branch_id<>handed.branch_id
 OR NEW.collection_key<>handed.collection_key OR NEW.invoice_line_key<>handed.line_key
 OR NEW.balance_id<>handed.balance_id OR NEW.location_id<>handed.location_id
 OR NEW.batch_key IS DISTINCT FROM handed.batch_key OR NEW.base_unit<>handed.base_unit THEN
 RAISE EXCEPTION 'Return allocation must match one exact invoice handover'; END IF;
IF claim.created_by<>NEW.created_by THEN
 RAISE EXCEPTION 'Return allocation must share its exact claim actor'; END IF;
SELECT COUNT(*) INTO binding_matches
 FROM containermgmt.manager_cases m
 CROSS JOIN LATERAL jsonb_array_elements(m.binding->'details'->'lines') line
 WHERE m.org_id=NEW.org_id AND m.case_key=NEW.return_key
 AND m.created_by=NEW.created_by
 AND line->>'invoice_line_key'=NEW.invoice_line_key::text
 AND line->>'handover_allocation_key'=NEW.handover_allocation_key::text
 AND line->>'collection_key'=NEW.collection_key::text
 AND (line->>'balance_id')::integer=NEW.balance_id
 AND (line->>'location_id')::integer=NEW.location_id
 AND (line->>'batch_key')::uuid IS NOT DISTINCT FROM NEW.batch_key
 AND (line->>'quantity')::numeric=NEW.quantity
 AND line->>'base_unit'=NEW.base_unit AND line->>'condition'=NEW.condition;
IF binding_matches<>1 THEN
 RAISE EXCEPTION 'Return allocation must appear once in its immutable review binding'; END IF;
SELECT COALESCE(SUM(a.quantity),0) INTO active_claimed
 FROM containermgmt.sales_return_allocations a
 JOIN containermgmt.sales_return_claims h ON h.org_id=a.org_id AND h.return_key=a.return_key
 JOIN containermgmt.manager_cases m ON m.org_id=h.org_id AND m.case_key=h.return_key
 LEFT JOIN containermgmt.manager_case_decisions d ON d.org_id=m.org_id AND d.case_id=m.id
 WHERE a.org_id=NEW.org_id AND a.handover_allocation_key=NEW.handover_allocation_key
 AND (d.id IS NULL OR d.outcome='APPROVED');
IF active_claimed>handed.quantity THEN
 RAISE EXCEPTION 'Pending and accepted returns exceed the exact handover'; END IF;
RETURN NULL; END; $$"""
ALLOCATION_GUARD_TRIGGER = """CREATE CONSTRAINT TRIGGER sales_return_allocation_guard
AFTER INSERT ON containermgmt.sales_return_allocations DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION containermgmt.check_sales_return_allocation()"""


CREDIT_GUARD_FUNCTION = """CREATE OR REPLACE FUNCTION containermgmt.check_sales_credit_note()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE claim record; operation record; line_totals record; debt numeric; credit numeric; BEGIN
SELECT invoice_key, branch_id, customer_key INTO claim
 FROM containermgmt.sales_return_claims
 WHERE org_id=NEW.org_id AND return_key=NEW.return_key;
SELECT COALESCE(SUM(gross_credit_scr),0) gross,
 COALESCE(SUM(net_credit_scr),0) net, COALESCE(SUM(tax_credit_scr),0) tax
 INTO line_totals FROM containermgmt.sales_credit_note_lines
 WHERE org_id=NEW.org_id AND credit_note_key=NEW.credit_note_key;
SELECT COALESCE(SUM(amount_scr),0) INTO debt
 FROM containermgmt.sales_invoice_debt_applications
 WHERE org_id=NEW.org_id AND credit_note_key=NEW.credit_note_key;
SELECT COALESCE(SUM(amount_scr),0) INTO credit
 FROM containermgmt.customer_credit_liability_entries
 WHERE org_id=NEW.org_id AND credit_note_key=NEW.credit_note_key;
SELECT kind, created_by INTO operation FROM containermgmt.inventory_posting_operations
 WHERE org_id=NEW.org_id AND operation_key=NEW.operation_key;
IF claim IS NULL OR claim.invoice_key<>NEW.invoice_key OR claim.branch_id<>NEW.branch_id
 OR claim.customer_key<>NEW.customer_key THEN
 RAISE EXCEPTION 'Credit note scope must match its exact return claim'; END IF;
IF line_totals.gross<>NEW.gross_credit_scr OR line_totals.net<>NEW.net_credit_scr
 OR line_totals.tax<>NEW.tax_credit_scr OR debt+credit<>NEW.gross_credit_scr THEN
 RAISE EXCEPTION 'Credit note lines and debt-first allocation must conserve value'; END IF;
IF operation IS NULL OR operation.kind<>'sales.return.credit.v1'
 OR operation.created_by<>NEW.created_by THEN
 RAISE EXCEPTION 'Credit note requires its exact stable posting operation'; END IF;
IF NOT EXISTS (
 SELECT 1 FROM containermgmt.manager_case_uses u
 JOIN containermgmt.manager_cases m ON m.id=u.case_id AND m.org_id=u.org_id
 JOIN containermgmt.manager_case_decisions d ON d.case_id=m.id AND d.org_id=m.org_id
 WHERE u.org_id=NEW.org_id AND u.operation_key=NEW.operation_key
 AND u.created_by=NEW.created_by AND m.case_key=NEW.return_key
 AND m.action='sales.return.claim' AND d.outcome='APPROVED'
) THEN RAISE EXCEPTION 'Credit note requires its exact approved return case use'; END IF;
RETURN NULL; END; $$"""
CREDIT_GUARD_TRIGGER = """CREATE CONSTRAINT TRIGGER sales_credit_note_guard
AFTER INSERT ON containermgmt.sales_credit_notes DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION containermgmt.check_sales_credit_note()"""


MONEY_CHILD_GUARD_FUNCTION = """CREATE OR REPLACE FUNCTION containermgmt.check_sales_return_money_child()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE credit record; invoice record; paid numeric; prior_debt numeric;
debt numeric; liability numeric; expected_debt numeric; BEGIN
SELECT invoice_key, customer_key, gross_credit_scr, created_by INTO credit
 FROM containermgmt.sales_credit_notes
 WHERE org_id=NEW.org_id AND credit_note_key=NEW.credit_note_key;
IF credit IS NULL OR credit.created_by<>NEW.created_by THEN
 RAISE EXCEPTION 'Return money entry must share its exact credit-note actor'; END IF;
IF TG_TABLE_NAME='sales_invoice_debt_applications' THEN
 IF NEW.invoice_key<>credit.invoice_key THEN
  RAISE EXCEPTION 'Return debt application must target its credit-note invoice'; END IF;
ELSIF TG_TABLE_NAME='customer_credit_liability_entries' THEN
 IF NEW.customer_key<>credit.customer_key THEN
  RAISE EXCEPTION 'Return liability must target its credit-note customer'; END IF;
ELSE
 RAISE EXCEPTION 'Unsupported return money child table %', TG_TABLE_NAME;
END IF;
SELECT gross_total_scr INTO invoice FROM containermgmt.sales_invoices
 WHERE org_id=NEW.org_id AND invoice_key=credit.invoice_key FOR UPDATE;
SELECT COALESCE(SUM(amount_scr),0) INTO paid
 FROM containermgmt.sales_invoice_payments
 WHERE org_id=NEW.org_id AND invoice_key=credit.invoice_key;
SELECT COALESCE(SUM(amount_scr),0) INTO prior_debt
 FROM containermgmt.sales_invoice_debt_applications
 WHERE org_id=NEW.org_id AND invoice_key=credit.invoice_key
 AND credit_note_key<>NEW.credit_note_key;
SELECT COALESCE(SUM(amount_scr),0) INTO debt
 FROM containermgmt.sales_invoice_debt_applications
 WHERE org_id=NEW.org_id AND credit_note_key=NEW.credit_note_key;
SELECT COALESCE(SUM(amount_scr),0) INTO liability
 FROM containermgmt.customer_credit_liability_entries
 WHERE org_id=NEW.org_id AND credit_note_key=NEW.credit_note_key;
expected_debt=LEAST(credit.gross_credit_scr,
 GREATEST(invoice.gross_total_scr-paid-prior_debt,0));
IF debt<>expected_debt OR debt+liability<>credit.gross_credit_scr THEN
 RAISE EXCEPTION 'Return value must reduce exact invoice debt before customer credit'; END IF;
RETURN NULL; END; $$"""
DEBT_CHILD_GUARD_TRIGGER = """CREATE CONSTRAINT TRIGGER sales_return_debt_child_guard
AFTER INSERT ON containermgmt.sales_invoice_debt_applications DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION containermgmt.check_sales_return_money_child()"""
CREDIT_CHILD_GUARD_TRIGGER = """CREATE CONSTRAINT TRIGGER customer_credit_return_child_guard
AFTER INSERT ON containermgmt.customer_credit_liability_entries DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION containermgmt.check_sales_return_money_child()"""


LINEAGE_GUARD_FUNCTION = """CREATE OR REPLACE FUNCTION containermgmt.check_sales_return_lineage()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE allocation record; credit record; line_totals record; movement record;
invoice_line record; line_cumulative record; issue record; returned record;
cumulative_quantity numeric; cumulative_value numeric; expected_value numeric;
expected_gross numeric; expected_net numeric; expected_tax numeric; BEGIN
SELECT return_key, invoice_key, invoice_line_key, handover_allocation_key,
 balance_id, quantity, base_unit INTO allocation
 FROM containermgmt.sales_return_allocations
 WHERE org_id=NEW.org_id AND id=NEW.return_allocation_id;
SELECT return_key, invoice_key, gross_credit_scr, net_credit_scr,
 tax_credit_scr, created_by INTO credit
 FROM containermgmt.sales_credit_notes
 WHERE org_id=NEW.org_id AND credit_note_key=NEW.credit_note_key;
SELECT COALESCE(SUM(gross_credit_scr),0) gross,
 COALESCE(SUM(net_credit_scr),0) net, COALESCE(SUM(tax_credit_scr),0) tax
 INTO line_totals FROM containermgmt.sales_credit_note_lines
 WHERE org_id=NEW.org_id AND credit_note_key=NEW.credit_note_key;
SELECT base_quantity, gross_total_scr, net_total_scr, tax_total_scr INTO invoice_line
 FROM containermgmt.sales_invoice_lines
 WHERE org_id=NEW.org_id AND invoice_key=NEW.invoice_key
 AND line_key=NEW.invoice_line_key FOR UPDATE;
SELECT COALESCE(SUM(quantity),0) quantity,
 COALESCE(SUM(gross_credit_scr),0) gross,
 COALESCE(SUM(net_credit_scr),0) net,
 COALESCE(SUM(tax_credit_scr),0) tax INTO line_cumulative
 FROM containermgmt.sales_credit_note_lines
 WHERE org_id=NEW.org_id AND invoice_key=NEW.invoice_key
 AND invoice_line_key=NEW.invoice_line_key;
SELECT kind, balance_id, version, on_hand_delta, reserved_delta, quarantined
 INTO movement FROM containermgmt.inventory_stock_movements
 WHERE org_id=NEW.org_id AND operation_key=NEW.return_operation_key
 AND balance_id=NEW.balance_id;
SELECT id, operation_key, kind, balance_id, quantity, goods_value_scr INTO issue
 FROM containermgmt.inventory_valuations
 WHERE org_id=NEW.org_id AND id=NEW.source_issue_valuation_id FOR UPDATE;
SELECT id, operation_key, kind, balance_id, quantity, goods_value_scr
 INTO returned FROM containermgmt.inventory_valuations
 WHERE org_id=NEW.org_id AND id=NEW.return_valuation_id;
IF allocation IS NULL OR credit IS NULL OR invoice_line IS NULL
 OR movement IS NULL OR issue IS NULL OR returned IS NULL
 OR credit.return_key<>allocation.return_key OR credit.invoice_key<>NEW.invoice_key
 OR credit.created_by<>NEW.created_by
 OR allocation.invoice_key<>NEW.invoice_key
 OR allocation.invoice_line_key<>NEW.invoice_line_key
 OR allocation.handover_allocation_key<>NEW.handover_allocation_key
 OR allocation.balance_id<>NEW.balance_id OR allocation.quantity<>NEW.quantity
 OR allocation.base_unit<>NEW.base_unit THEN
 RAISE EXCEPTION 'Credit line must preserve exact return allocation lineage'; END IF;
IF line_totals.gross<>credit.gross_credit_scr OR line_totals.net<>credit.net_credit_scr
 OR line_totals.tax<>credit.tax_credit_scr THEN
 RAISE EXCEPTION 'Credit-note line totals must remain exact and immutable'; END IF;
IF line_cumulative.quantity=invoice_line.base_quantity THEN
 expected_net=invoice_line.net_total_scr;
 expected_tax=invoice_line.tax_total_scr;
ELSE
 expected_net=round(invoice_line.net_total_scr*line_cumulative.quantity/invoice_line.base_quantity,2);
 expected_tax=round(invoice_line.tax_total_scr*line_cumulative.quantity/invoice_line.base_quantity,2);
END IF;
expected_gross=expected_net+expected_tax;
IF line_cumulative.quantity>invoice_line.base_quantity
 OR line_cumulative.gross<>expected_gross OR line_cumulative.net<>expected_net
 OR line_cumulative.tax<>expected_tax THEN
 RAISE EXCEPTION 'Cumulative credit must remain proportional to the original invoice line'; END IF;
IF issue.kind<>'ISSUE' OR issue.operation_key<>NEW.handover_allocation_key
 OR issue.balance_id<>NEW.balance_id OR issue.quantity<NEW.quantity THEN
 RAISE EXCEPTION 'Return cost must reference the original exact issue'; END IF;
IF movement.kind<>'RETURN' OR movement.on_hand_delta<>NEW.quantity
 OR movement.reserved_delta<>0 OR returned.kind<>'RETURN'
 OR returned.operation_key<>NEW.return_operation_key
 OR returned.balance_id<>NEW.balance_id OR returned.quantity<>NEW.quantity
 OR returned.goods_value_scr<>NEW.restored_cost_scr THEN
 RAISE EXCEPTION 'Credit line must match its quarantined return movement and value'; END IF;
SELECT SUM(quantity), SUM(restored_cost_scr) INTO cumulative_quantity, cumulative_value
 FROM containermgmt.sales_credit_note_lines
 WHERE org_id=NEW.org_id AND source_issue_valuation_id=NEW.source_issue_valuation_id;
IF cumulative_quantity=issue.quantity THEN expected_value=issue.goods_value_scr;
ELSE expected_value=round(issue.goods_value_scr*cumulative_quantity/issue.quantity,6); END IF;
IF cumulative_quantity>issue.quantity OR cumulative_value<>expected_value THEN
 RAISE EXCEPTION 'Cumulative restored cost must remain proportional to the original issue'; END IF;
RETURN NULL; END; $$"""
LINEAGE_GUARD_TRIGGER = """CREATE CONSTRAINT TRIGGER sales_return_lineage_guard
AFTER INSERT ON containermgmt.sales_credit_note_lines DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION containermgmt.check_sales_return_lineage()"""


RETURN_MOVEMENT_GUARD_FUNCTION = """CREATE OR REPLACE FUNCTION containermgmt.guard_return_stock_movement()
RETURNS trigger LANGUAGE plpgsql AS $$ DECLARE prior record; balance record;
operation record; matches integer; latest_version integer; BEGIN
IF NEW.kind<>'RETURN' THEN RETURN NULL; END IF;
SELECT on_hand, reserved, damaged, quarantined INTO prior
 FROM containermgmt.inventory_stock_movements
 WHERE org_id=NEW.org_id AND balance_id=NEW.balance_id AND version=NEW.version-1;
SELECT version, on_hand, reserved, damaged, quarantined INTO balance
 FROM containermgmt.inventory_stock_balances
 WHERE org_id=NEW.org_id AND id=NEW.balance_id FOR UPDATE;
SELECT MAX(version) INTO latest_version FROM containermgmt.inventory_stock_movements
 WHERE org_id=NEW.org_id AND balance_id=NEW.balance_id;
SELECT kind, created_by INTO operation FROM containermgmt.inventory_posting_operations
 WHERE org_id=NEW.org_id AND operation_key=NEW.operation_key;
SELECT COUNT(*) INTO matches FROM containermgmt.sales_credit_note_lines
 WHERE org_id=NEW.org_id AND return_operation_key=NEW.operation_key
 AND balance_id=NEW.balance_id AND quantity=NEW.on_hand_delta
 AND created_by=NEW.created_by;
IF prior IS NULL OR NEW.reservation_id IS NOT NULL OR NEW.on_hand_delta<=0
 OR NEW.reserved_delta<>0 OR NEW.on_hand<>prior.on_hand+NEW.on_hand_delta
 OR NEW.reserved<>prior.reserved OR NEW.damaged<>prior.damaged
 OR NEW.quarantined<>prior.quarantined+NEW.on_hand_delta
 OR operation IS NULL OR operation.kind<>'inventory.return.receive.v1'
 OR operation.created_by<>NEW.created_by OR matches<>1 THEN
 RAISE EXCEPTION 'Returned stock must restore the exact balance in quarantine'; END IF;
IF NEW.version=latest_version AND (balance IS NULL OR balance.version<>NEW.version
 OR balance.on_hand<>NEW.on_hand OR balance.reserved<>NEW.reserved
 OR balance.damaged<>NEW.damaged OR balance.quarantined<>NEW.quarantined) THEN
 RAISE EXCEPTION 'Latest return movement must equal the locked physical balance'; END IF;
RETURN NULL; END; $$"""
RETURN_MOVEMENT_GUARD_TRIGGER = """CREATE CONSTRAINT TRIGGER return_stock_movement_guard
AFTER INSERT ON containermgmt.inventory_stock_movements DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION containermgmt.guard_return_stock_movement()"""


RETURN_VALUATION_GUARD_FUNCTION = """CREATE OR REPLACE FUNCTION containermgmt.guard_return_valuation()
RETURNS trigger LANGUAGE plpgsql AS $$ DECLARE prior record; operation record; matches integer; BEGIN
IF NEW.kind<>'RETURN' THEN RETURN NULL; END IF;
SELECT id, version, cost_pool_id, product_id, base_unit, pool_quantity, pool_value_scr
 INTO prior FROM containermgmt.inventory_valuations
 WHERE org_id=NEW.org_id AND id=NEW.source_valuation_id;
SELECT kind, created_by INTO operation FROM containermgmt.inventory_posting_operations
 WHERE org_id=NEW.org_id AND operation_key=NEW.operation_key;
SELECT COUNT(*) INTO matches FROM containermgmt.sales_credit_note_lines
 WHERE org_id=NEW.org_id AND return_operation_key=NEW.operation_key
 AND return_valuation_id=NEW.id AND balance_id=NEW.balance_id
 AND quantity=NEW.quantity AND restored_cost_scr=NEW.goods_value_scr
 AND created_by=NEW.created_by;
IF prior IS NULL OR NEW.version<>prior.version+1
 OR NEW.cost_pool_id<>prior.cost_pool_id OR NEW.product_id<>prior.product_id
 OR NEW.base_unit<>prior.base_unit OR NEW.pool_quantity<>prior.pool_quantity+NEW.quantity
 OR NEW.pool_value_scr<>prior.pool_value_scr+NEW.goods_value_scr
 OR NEW.additional_cost_scr<>0 OR operation IS NULL
 OR operation.kind<>'inventory.return.receive.v1'
 OR operation.created_by<>NEW.created_by OR matches<>1 OR NOT EXISTS (
  SELECT 1 FROM containermgmt.inventory_stock_movements m
  WHERE m.org_id=NEW.org_id AND m.operation_key=NEW.operation_key
  AND m.balance_id=NEW.balance_id AND m.version=NEW.source_version
  AND m.kind='RETURN' AND m.on_hand_delta=NEW.quantity
 ) THEN RAISE EXCEPTION 'Return value must extend the current pool head and exact movement'; END IF;
RETURN NULL; END; $$"""
RETURN_VALUATION_GUARD_TRIGGER = """CREATE CONSTRAINT TRIGGER return_valuation_guard
AFTER INSERT ON containermgmt.inventory_valuations DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION containermgmt.guard_return_valuation()"""


for model in MODELS:
    event.listen(model.__table__, "after_create", DDL(IMMUTABLE_FUNCTION))
    event.listen(model.__table__, "after_create", DDL(immutable_trigger(model.__tablename__)))
event.listen(SalesReturnClaim.__table__, "after_create", DDL(CLAIM_GUARD_FUNCTION))
event.listen(SalesReturnClaim.__table__, "after_create", DDL(CLAIM_GUARD_TRIGGER))
event.listen(SalesReturnAllocation.__table__, "after_create", DDL(ALLOCATION_GUARD_FUNCTION))
event.listen(SalesReturnAllocation.__table__, "after_create", DDL(ALLOCATION_GUARD_TRIGGER))
event.listen(SalesCreditNote.__table__, "after_create", DDL(CREDIT_GUARD_FUNCTION))
event.listen(SalesCreditNote.__table__, "after_create", DDL(CREDIT_GUARD_TRIGGER))
event.listen(SalesInvoiceDebtApplication.__table__, "after_create", DDL(MONEY_CHILD_GUARD_FUNCTION))
event.listen(SalesInvoiceDebtApplication.__table__, "after_create", DDL(DEBT_CHILD_GUARD_TRIGGER))
event.listen(CustomerCreditLiabilityEntry.__table__, "after_create", DDL(MONEY_CHILD_GUARD_FUNCTION))
event.listen(CustomerCreditLiabilityEntry.__table__, "after_create", DDL(CREDIT_CHILD_GUARD_TRIGGER))
event.listen(SalesCreditNoteLine.__table__, "after_create", DDL(LINEAGE_GUARD_FUNCTION))
event.listen(SalesCreditNoteLine.__table__, "after_create", DDL(LINEAGE_GUARD_TRIGGER))
event.listen(StockMovement.__table__, "after_create", DDL(RETURN_MOVEMENT_GUARD_FUNCTION))
event.listen(StockMovement.__table__, "after_create", DDL(RETURN_MOVEMENT_GUARD_TRIGGER))
event.listen(InventoryValuation.__table__, "after_create", DDL(RETURN_VALUATION_GUARD_FUNCTION))
event.listen(InventoryValuation.__table__, "after_create", DDL(RETURN_VALUATION_GUARD_TRIGGER))
