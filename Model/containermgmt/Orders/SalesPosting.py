"""Immutable sales-posting inputs and financial/commitment results.

An attempt is an exact, append-only request envelope.  Card outcomes are recorded
separately so an unknown external outcome never requires editing or repeating the
attempt.  A posted invoice is immutable and does not represent physical handover.
"""
from sqlalchemy import (
    CheckConstraint,
    Column,
    Date,
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
from sqlalchemy.dialects.postgresql import JSONB, UUID

from Model.db import Base
from Model.mixins import AuditMixin, OrgMixin
from Model.containermgmt.Inventory.Location import InventoryBranch  # noqa: F401
from Model.containermgmt.Inventory.BranchCounter import BranchCounter  # noqa: F401
from Model.containermgmt.Inventory.PostingOperation import PostingOperation  # noqa: F401
from Model.containermgmt.Inventory.SalesReservationSource import SalesReservationSource  # noqa: F401
from Model.containermgmt.Inventory.StockLedger import StockReservation  # noqa: F401
from Model.containermgmt.MasterData.RetailCustomer import RetailCustomer  # noqa: F401
from Model.containermgmt.Orders.PaymentConfiguration import (  # noqa: F401
    BranchReceivingAccountRevision,
    PaymentMethodRevision,
)
from Model.containermgmt.Orders.SalesIntent import (  # noqa: F401
    SalesIntentLineRevision,
    SalesIntentRevision,
)
from Model.containermgmt.Orders.SalesPricing import SalesTransactionPricing  # noqa: F401


NONZERO_UUID = "<> '00000000-0000-0000-0000-000000000000'::uuid"
AUDIT_CHECK = "created_by IS NOT NULL AND NOT is_deleted AND deleted_at IS NULL"


class SalesPostingAttempt(OrgMixin, AuditMixin, Base):
    """Exact request envelope; presence alone never confirms a sale."""

    __tablename__ = "sales_posting_attempts"
    __table_args__ = (
        UniqueConstraint("attempt_key", "org_id", name="uq_sales_post_attempt_scope"),
        UniqueConstraint("org_id", "operation_key", name="uq_sales_post_attempt_operation"),
        UniqueConstraint("org_id", "document_key", "draft_version",
                         name="uq_sales_post_attempt_draft"),
        UniqueConstraint("org_id", "pricing_snapshot_key",
                         name="uq_sales_post_attempt_pricing"),
        ForeignKeyConstraint(
            ["org_id", "document_key", "draft_version"],
            ["containermgmt.sales_intent_revisions.org_id",
             "containermgmt.sales_intent_revisions.document_key",
             "containermgmt.sales_intent_revisions.version"],
            name="fk_sales_post_attempt_draft",
        ),
        ForeignKeyConstraint(
            ["pricing_snapshot_key", "org_id"],
            ["containermgmt.sales_transaction_pricing.pricing_snapshot_key",
             "containermgmt.sales_transaction_pricing.org_id"],
            name="fk_sales_post_attempt_pricing",
        ),
        ForeignKeyConstraint(
            ["branch_id", "org_id"],
            ["containermgmt.inventory_branches.id",
             "containermgmt.inventory_branches.org_id"],
            name="fk_sales_post_attempt_branch",
        ),
        ForeignKeyConstraint(
            ["counter_id", "org_id"],
            ["containermgmt.inventory_branch_counters.id",
             "containermgmt.inventory_branch_counters.org_id"],
            name="fk_sales_post_attempt_counter",
        ),
        ForeignKeyConstraint(
            ["customer_key", "org_id"],
            ["containermgmt.retail_customers.customer_key",
             "containermgmt.retail_customers.org_id"],
            name="fk_sales_post_attempt_customer",
        ),
        CheckConstraint(
            f"attempt_key {NONZERO_UUID} AND operation_key {NONZERO_UUID} "
            "AND draft_version > 0 AND customer_version > 0 "
            "AND branch_settings_version > 0 AND counter_settings_version > 0 "
            "AND assignment_version > 0",
            name="ck_sales_post_attempt_identity",
        ),
        CheckConstraint(
            "request_digest ~ '^[0-9a-f]{64}$' AND "
            "pricing_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_sales_post_attempt_digests",
        ),
        CheckConstraint("currency = 'SCR'", name="ck_sales_post_attempt_currency"),
        CheckConstraint(
            "gross_total_scr > 0 AND net_total_scr >= 0 AND tax_total_scr >= 0 "
            "AND gross_total_scr = net_total_scr + tax_total_scr",
            name="ck_sales_post_attempt_totals",
        ),
        CheckConstraint(AUDIT_CHECK, name="ck_sales_post_attempt_audit"),
        Index("ix_sales_post_attempt_draft", "org_id", "document_key", "draft_version"),
        {"schema": "containermgmt"},
    )
    attempt_key = Column(UUID(as_uuid=True), primary_key=True)
    operation_key = Column(UUID(as_uuid=True), nullable=False)
    request_digest = Column(String(64), nullable=False)
    document_key = Column(UUID(as_uuid=True), nullable=False)
    draft_version = Column(Integer, nullable=False)
    pricing_snapshot_key = Column(UUID(as_uuid=True), nullable=False, index=True)
    pricing_fingerprint = Column(String(64), nullable=False)
    branch_id = Column(Integer, nullable=False, index=True)
    counter_id = Column(Integer, nullable=False)
    counter_key = Column(UUID(as_uuid=True), nullable=False)
    branch_settings_version = Column(Integer, nullable=False)
    counter_settings_version = Column(Integer, nullable=False)
    assignment_version = Column(Integer, nullable=False)
    business_date = Column(Date, nullable=False)
    customer_key = Column(UUID(as_uuid=True), nullable=False, index=True)
    customer_version = Column(Integer, nullable=False)
    currency = Column(String(3), nullable=False)
    gross_total_scr = Column(Numeric(24, 2), nullable=False)
    net_total_scr = Column(Numeric(24, 2), nullable=False)
    tax_total_scr = Column(Numeric(24, 2), nullable=False)


class SalesPostingTender(OrgMixin, AuditMixin, Base):
    """Immutable exact payment plan owned by an attempt."""

    __tablename__ = "sales_posting_tenders"
    __table_args__ = (
        UniqueConstraint("org_id", "attempt_key", "tender_key",
                         name="uq_sales_post_tender_scope"),
        ForeignKeyConstraint(
            ["attempt_key", "org_id"],
            ["containermgmt.sales_posting_attempts.attempt_key",
             "containermgmt.sales_posting_attempts.org_id"],
            name="fk_sales_post_tender_attempt",
        ),
        ForeignKeyConstraint(
            ["org_id", "method_key", "method_version"],
            ["containermgmt.payment_method_revisions.org_id",
             "containermgmt.payment_method_revisions.method_key",
             "containermgmt.payment_method_revisions.version"],
            name="fk_sales_post_tender_method",
        ),
        ForeignKeyConstraint(
            ["org_id", "mapping_key", "mapping_version"],
            ["containermgmt.branch_receiving_account_revisions.org_id",
             "containermgmt.branch_receiving_account_revisions.mapping_key",
             "containermgmt.branch_receiving_account_revisions.version"],
            name="fk_sales_post_tender_mapping",
        ),
        CheckConstraint(
            f"tender_key {NONZERO_UUID} AND method_key {NONZERO_UUID} "
            f"AND mapping_key {NONZERO_UUID} AND method_version > 0 "
            "AND mapping_version > 0",
            name="ck_sales_post_tender_identity",
        ),
        CheckConstraint("kind IN ('CASH', 'CARD')", name="ck_sales_post_tender_kind"),
        CheckConstraint("amount_scr > 0", name="ck_sales_post_tender_amount"),
        CheckConstraint(
            "account_ref ~ '^[A-Z0-9][A-Z0-9_.:-]{0,63}$'",
            name="ck_sales_post_tender_account",
        ),
        CheckConstraint(AUDIT_CHECK, name="ck_sales_post_tender_audit"),
        Index("ix_sales_post_tender_attempt", "org_id", "attempt_key"),
        {"schema": "containermgmt"},
    )
    tender_key = Column(UUID(as_uuid=True), primary_key=True)
    attempt_key = Column(UUID(as_uuid=True), nullable=False)
    method_key = Column(UUID(as_uuid=True), nullable=False)
    method_version = Column(Integer, nullable=False)
    mapping_key = Column(UUID(as_uuid=True), nullable=False)
    mapping_version = Column(Integer, nullable=False)
    kind = Column(String(12), nullable=False)
    account_ref = Column(String(64), nullable=False)
    amount_scr = Column(Numeric(24, 2), nullable=False)


class SalesCardConfirmation(OrgMixin, AuditMixin, Base):
    """Append-only external card observation; never stores PAN or provider secrets."""

    __tablename__ = "sales_card_confirmations"
    __table_args__ = (
        UniqueConstraint("confirmation_key", "org_id", name="uq_sales_card_confirm_scope"),
        UniqueConstraint("org_id", "attempt_key", "tender_key", "sequence",
                         name="uq_sales_card_confirm_sequence"),
        UniqueConstraint("org_id", "provider_reference_hash",
                         name="uq_sales_card_confirm_reference"),
        ForeignKeyConstraint(
            ["org_id", "attempt_key", "tender_key"],
            ["containermgmt.sales_posting_tenders.org_id",
             "containermgmt.sales_posting_tenders.attempt_key",
             "containermgmt.sales_posting_tenders.tender_key"],
            name="fk_sales_card_confirm_tender",
        ),
        CheckConstraint(
            f"confirmation_key {NONZERO_UUID} AND sequence > 0",
            name="ck_sales_card_confirm_identity",
        ),
        CheckConstraint(
            "request_digest ~ '^[0-9a-f]{64}$'",
            name="ck_sales_card_confirm_digest",
        ),
        CheckConstraint(
            "outcome IN ('UNKNOWN', 'CONFIRMED', 'DECLINED')",
            name="ck_sales_card_confirm_outcome",
        ),
        CheckConstraint(
            "(outcome = 'CONFIRMED' AND provider_reference_hash ~ '^[0-9a-f]{64}$') "
            "OR (outcome <> 'CONFIRMED' AND provider_reference_hash IS NULL)",
            name="ck_sales_card_confirm_evidence",
        ),
        CheckConstraint(AUDIT_CHECK, name="ck_sales_card_confirm_audit"),
        Index("ix_sales_card_confirm_tender", "org_id", "attempt_key", "tender_key"),
        {"schema": "containermgmt"},
    )
    confirmation_key = Column(UUID(as_uuid=True), primary_key=True)
    attempt_key = Column(UUID(as_uuid=True), nullable=False)
    tender_key = Column(UUID(as_uuid=True), nullable=False)
    sequence = Column(Integer, nullable=False)
    request_digest = Column(String(64), nullable=False)
    outcome = Column(String(12), nullable=False)
    provider_reference_hash = Column(String(64), nullable=True)
    observed_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SalesInvoice(OrgMixin, AuditMixin, Base):
    """Immutable posted financial document; fulfilment is separate T16 history."""

    __tablename__ = "sales_invoices"
    __table_args__ = (
        UniqueConstraint("invoice_key", "org_id", name="uq_sales_invoice_scope"),
        UniqueConstraint("org_id", "invoice_number", name="uq_sales_invoice_number"),
        UniqueConstraint("org_id", "attempt_key", name="uq_sales_invoice_attempt"),
        UniqueConstraint("org_id", "operation_key", name="uq_sales_invoice_operation"),
        UniqueConstraint("org_id", "document_key", "draft_version",
                         name="uq_sales_invoice_draft"),
        ForeignKeyConstraint(
            ["attempt_key", "org_id"],
            ["containermgmt.sales_posting_attempts.attempt_key",
             "containermgmt.sales_posting_attempts.org_id"],
            name="fk_sales_invoice_attempt",
        ),
        ForeignKeyConstraint(
            ["org_id", "operation_key"],
            ["containermgmt.inventory_posting_operations.org_id",
             "containermgmt.inventory_posting_operations.operation_key"],
            name="fk_sales_invoice_operation",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["org_id", "document_key", "draft_version"],
            ["containermgmt.sales_intent_revisions.org_id",
             "containermgmt.sales_intent_revisions.document_key",
             "containermgmt.sales_intent_revisions.version"],
            name="fk_sales_invoice_draft",
        ),
        ForeignKeyConstraint(
            ["branch_id", "org_id"],
            ["containermgmt.inventory_branches.id",
             "containermgmt.inventory_branches.org_id"],
            name="fk_sales_invoice_branch",
        ),
        ForeignKeyConstraint(
            ["counter_id", "org_id"],
            ["containermgmt.inventory_branch_counters.id",
             "containermgmt.inventory_branch_counters.org_id"],
            name="fk_sales_invoice_counter",
        ),
        ForeignKeyConstraint(
            ["customer_key", "org_id"],
            ["containermgmt.retail_customers.customer_key",
             "containermgmt.retail_customers.org_id"],
            name="fk_sales_invoice_customer",
        ),
        CheckConstraint(
            f"invoice_key {NONZERO_UUID} AND operation_key {NONZERO_UUID} "
            f"AND document_key {NONZERO_UUID} AND draft_version > 0 "
            "AND length(trim(invoice_number)) > 0 AND customer_version > 0 "
            "AND branch_settings_version > 0 AND counter_settings_version > 0 "
            "AND assignment_version > 0",
            name="ck_sales_invoice_identity",
        ),
        CheckConstraint("currency = 'SCR'", name="ck_sales_invoice_currency"),
        CheckConstraint(
            "gross_total_scr > 0 AND net_total_scr >= 0 AND tax_total_scr >= 0 "
            "AND gross_total_scr = net_total_scr + tax_total_scr",
            name="ck_sales_invoice_totals",
        ),
        CheckConstraint(AUDIT_CHECK, name="ck_sales_invoice_audit"),
        CheckConstraint(
            "jsonb_typeof(customer_snapshot) = 'object' AND "
            "jsonb_typeof(branch_snapshot) = 'object'",
            name="ck_sales_invoice_snapshots",
        ),
        Index("ix_sales_invoice_branch_date", "org_id", "branch_id", "business_date"),
        Index("ix_sales_invoice_customer", "org_id", "customer_key", "issued_at"),
        {"schema": "containermgmt"},
    )
    invoice_key = Column(UUID(as_uuid=True), primary_key=True)
    attempt_key = Column(UUID(as_uuid=True), nullable=False)
    operation_key = Column(UUID(as_uuid=True), nullable=False)
    invoice_number = Column(String(64), nullable=False)
    document_key = Column(UUID(as_uuid=True), nullable=False)
    draft_version = Column(Integer, nullable=False)
    branch_id = Column(Integer, nullable=False)
    counter_id = Column(Integer, nullable=False)
    branch_settings_version = Column(Integer, nullable=False)
    counter_settings_version = Column(Integer, nullable=False)
    assignment_version = Column(Integer, nullable=False)
    customer_key = Column(UUID(as_uuid=True), nullable=False)
    customer_version = Column(Integer, nullable=False)
    customer_snapshot = Column(JSONB, nullable=False)
    branch_snapshot = Column(JSONB, nullable=False)
    business_date = Column(Date, nullable=False)
    issued_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    currency = Column(String(3), nullable=False)
    gross_total_scr = Column(Numeric(24, 2), nullable=False)
    net_total_scr = Column(Numeric(24, 2), nullable=False)
    tax_total_scr = Column(Numeric(24, 2), nullable=False)


class SalesInvoiceLine(OrgMixin, AuditMixin, Base):
    __tablename__ = "sales_invoice_lines"
    __table_args__ = (
        UniqueConstraint("org_id", "invoice_key", "line_key",
                         name="uq_sales_invoice_line_scope"),
        UniqueConstraint("org_id", "invoice_key", "position",
                         name="uq_sales_invoice_line_position"),
        UniqueConstraint("org_id", "invoice_key", "source_line_key",
                         name="uq_sales_invoice_line_source"),
        ForeignKeyConstraint(
            ["invoice_key", "org_id"],
            ["containermgmt.sales_invoices.invoice_key",
             "containermgmt.sales_invoices.org_id"],
            name="fk_sales_invoice_line_invoice",
        ),
        ForeignKeyConstraint(
            ["org_id", "document_key", "draft_version", "source_line_key"],
            ["containermgmt.sales_intent_line_revisions.org_id",
             "containermgmt.sales_intent_line_revisions.document_key",
             "containermgmt.sales_intent_line_revisions.version",
             "containermgmt.sales_intent_line_revisions.line_key"],
            name="fk_sales_invoice_line_source",
        ),
        CheckConstraint(
            f"line_key {NONZERO_UUID} AND source_line_key {NONZERO_UUID} "
            "AND draft_version > 0 AND position BETWEEN 1 AND 100",
            name="ck_sales_invoice_line_identity",
        ),
        CheckConstraint(
            "quantity > 0 AND base_quantity > 0 AND "
            "length(trim(unit)) > 0 AND length(trim(base_unit)) > 0",
            name="ck_sales_invoice_line_quantity",
        ),
        CheckConstraint(
            "gross_unit_scr > 0 AND gross_total_scr > 0 AND net_total_scr >= 0 "
            "AND tax_total_scr >= 0 AND gross_total_scr = net_total_scr + tax_total_scr",
            name="ck_sales_invoice_line_totals",
        ),
        CheckConstraint(
            "tax_treatment IN ('STANDARD', 'ZERO_RATED', 'EXEMPT') AND tax_rate >= 0",
            name="ck_sales_invoice_line_tax",
        ),
        CheckConstraint(
            "jsonb_typeof(pricing_snapshot) = 'object'",
            name="ck_sales_invoice_line_pricing",
        ),
        CheckConstraint(AUDIT_CHECK, name="ck_sales_invoice_line_audit"),
        Index("ix_sales_invoice_line_source", "org_id", "document_key",
              "draft_version", "source_line_key"),
        {"schema": "containermgmt"},
    )
    line_key = Column(UUID(as_uuid=True), primary_key=True)
    invoice_key = Column(UUID(as_uuid=True), nullable=False)
    position = Column(Integer, nullable=False)
    document_key = Column(UUID(as_uuid=True), nullable=False)
    draft_version = Column(Integer, nullable=False)
    source_line_key = Column(UUID(as_uuid=True), nullable=False)
    product_id = Column(Integer, nullable=False)
    product_name = Column(String(255), nullable=False)
    sku = Column(String(100), nullable=False)
    policy_version = Column(Integer, nullable=False)
    quantity = Column(Numeric(18, 6), nullable=False)
    unit = Column(String(50), nullable=False)
    base_quantity = Column(Numeric(18, 6), nullable=False)
    base_unit = Column(String(50), nullable=False)
    gross_unit_scr = Column(Numeric(24, 6), nullable=False)
    gross_total_scr = Column(Numeric(24, 2), nullable=False)
    net_total_scr = Column(Numeric(24, 2), nullable=False)
    tax_total_scr = Column(Numeric(24, 2), nullable=False)
    tax_treatment = Column(String(20), nullable=False)
    tax_rate = Column(Numeric(12, 8), nullable=False)
    pricing_snapshot = Column(JSONB, nullable=False)


class SalesInvoicePayment(OrgMixin, AuditMixin, Base):
    __tablename__ = "sales_invoice_payments"
    __table_args__ = (
        UniqueConstraint("payment_key", "org_id", name="uq_sales_invoice_payment_scope"),
        UniqueConstraint("org_id", "invoice_key", "tender_key",
                         name="uq_sales_invoice_payment_tender"),
        ForeignKeyConstraint(
            ["invoice_key", "org_id"],
            ["containermgmt.sales_invoices.invoice_key",
             "containermgmt.sales_invoices.org_id"],
            name="fk_sales_invoice_payment_invoice",
        ),
        ForeignKeyConstraint(
            ["org_id", "attempt_key", "tender_key"],
            ["containermgmt.sales_posting_tenders.org_id",
             "containermgmt.sales_posting_tenders.attempt_key",
             "containermgmt.sales_posting_tenders.tender_key"],
            name="fk_sales_invoice_payment_tender",
        ),
        ForeignKeyConstraint(
            ["confirmation_key", "org_id"],
            ["containermgmt.sales_card_confirmations.confirmation_key",
             "containermgmt.sales_card_confirmations.org_id"],
            name="fk_sales_invoice_payment_card",
        ),
        CheckConstraint(
            f"payment_key {NONZERO_UUID} AND amount_scr > 0",
            name="ck_sales_invoice_payment_identity",
        ),
        CheckConstraint("kind IN ('CASH', 'CARD')", name="ck_sales_invoice_payment_kind"),
        CheckConstraint(
            "(kind = 'CASH' AND confirmation_key IS NULL) OR "
            "(kind = 'CARD' AND confirmation_key IS NOT NULL)",
            name="ck_sales_invoice_payment_card",
        ),
        CheckConstraint(
            "account_ref ~ '^[A-Z0-9][A-Z0-9_.:-]{0,63}$'",
            name="ck_sales_invoice_payment_account",
        ),
        CheckConstraint(AUDIT_CHECK, name="ck_sales_invoice_payment_audit"),
        Index("ix_sales_invoice_payment_invoice", "org_id", "invoice_key"),
        {"schema": "containermgmt"},
    )
    payment_key = Column(UUID(as_uuid=True), primary_key=True)
    invoice_key = Column(UUID(as_uuid=True), nullable=False)
    attempt_key = Column(UUID(as_uuid=True), nullable=False)
    tender_key = Column(UUID(as_uuid=True), nullable=False)
    kind = Column(String(12), nullable=False)
    account_ref = Column(String(64), nullable=False)
    amount_scr = Column(Numeric(24, 2), nullable=False)
    confirmation_key = Column(UUID(as_uuid=True), nullable=True)


class SalesInvoiceReservation(OrgMixin, AuditMixin, Base):
    """Exact reservation commitment; it is not a physical collection record."""

    __tablename__ = "sales_invoice_reservations"
    __table_args__ = (
        UniqueConstraint("org_id", "invoice_key", "line_key", "reservation_key",
                         name="uq_sales_invoice_reservation_scope"),
        UniqueConstraint("org_id", "reservation_key",
                         name="uq_sales_invoice_reservation_once"),
        ForeignKeyConstraint(
            ["org_id", "invoice_key", "line_key"],
            ["containermgmt.sales_invoice_lines.org_id",
             "containermgmt.sales_invoice_lines.invoice_key",
             "containermgmt.sales_invoice_lines.line_key"],
            name="fk_sales_invoice_reservation_line",
        ),
        ForeignKeyConstraint(
            ["org_id", "reservation_key"],
            ["containermgmt.inventory_stock_reservations.org_id",
             "containermgmt.inventory_stock_reservations.reservation_key"],
            name="fk_sales_invoice_reservation_stock",
        ),
        CheckConstraint(
            f"reservation_key {NONZERO_UUID} AND quantity > 0",
            name="ck_sales_invoice_reservation_quantity",
        ),
        CheckConstraint(AUDIT_CHECK, name="ck_sales_invoice_reservation_audit"),
        Index("ix_sales_invoice_reservation_line", "org_id", "invoice_key", "line_key"),
        {"schema": "containermgmt"},
    )
    id = Column(Integer, primary_key=True)
    invoice_key = Column(UUID(as_uuid=True), nullable=False)
    line_key = Column(UUID(as_uuid=True), nullable=False)
    reservation_key = Column(UUID(as_uuid=True), nullable=False)
    quantity = Column(Numeric(18, 6), nullable=False)


MODELS = (
    SalesPostingAttempt,
    SalesPostingTender,
    SalesCardConfirmation,
    SalesInvoice,
    SalesInvoiceLine,
    SalesInvoicePayment,
    SalesInvoiceReservation,
)


IMMUTABLE_FUNCTION = """CREATE OR REPLACE FUNCTION containermgmt.reject_sales_posting_change()
RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
RAISE EXCEPTION 'Sales posting history is immutable'; END; $$"""


def immutable_trigger(table):
    return f"""CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE
ON containermgmt.{table} FOR EACH ROW
EXECUTE FUNCTION containermgmt.reject_sales_posting_change()"""


ATTEMPT_GUARD_FUNCTION = """CREATE OR REPLACE FUNCTION containermgmt.guard_sales_post_attempt()
RETURNS trigger LANGUAGE plpgsql AS $$ DECLARE draft record; price record; BEGIN
SELECT customer_key, customer_version, branch_id INTO draft
FROM containermgmt.sales_intent_revisions
WHERE org_id=NEW.org_id AND document_key=NEW.document_key
AND version=NEW.draft_version;
IF draft IS NULL OR draft.customer_key<>NEW.customer_key
 OR draft.customer_version<>NEW.customer_version OR draft.branch_id<>NEW.branch_id THEN
 RAISE EXCEPTION 'Sales posting attempt does not match the exact draft'; END IF;
SELECT document_key, draft_version, pricing_fingerprint, currency,
 gross_total_scr, net_total_scr, tax_total_scr INTO price
FROM containermgmt.sales_transaction_pricing
WHERE org_id=NEW.org_id AND pricing_snapshot_key=NEW.pricing_snapshot_key;
IF price IS NULL OR price.document_key<>NEW.document_key
 OR price.draft_version<>NEW.draft_version
 OR price.pricing_fingerprint<>NEW.pricing_fingerprint
 OR price.currency<>NEW.currency OR price.gross_total_scr<>NEW.gross_total_scr
 OR price.net_total_scr<>NEW.net_total_scr OR price.tax_total_scr<>NEW.tax_total_scr THEN
 RAISE EXCEPTION 'Sales posting attempt does not match the exact pricing snapshot'; END IF;
RETURN NEW; END; $$"""
ATTEMPT_GUARD_TRIGGER = """CREATE TRIGGER sales_post_attempt_guard BEFORE INSERT
ON containermgmt.sales_posting_attempts FOR EACH ROW
EXECUTE FUNCTION containermgmt.guard_sales_post_attempt()"""


TENDER_GUARD_FUNCTION = """CREATE OR REPLACE FUNCTION containermgmt.guard_sales_post_tender()
RETURNS trigger LANGUAGE plpgsql AS $$ DECLARE attempt_branch integer; method record; mapping record; BEGIN
SELECT branch_id INTO attempt_branch FROM containermgmt.sales_posting_attempts
WHERE org_id=NEW.org_id AND attempt_key=NEW.attempt_key FOR UPDATE;
SELECT kind, is_enabled INTO method FROM containermgmt.payment_method_revisions
WHERE org_id=NEW.org_id AND method_key=NEW.method_key AND version=NEW.method_version;
SELECT root.branch_id, root.method_key, rev.account_ref, rev.is_enabled INTO mapping
FROM containermgmt.branch_receiving_accounts root
JOIN containermgmt.branch_receiving_account_revisions rev
 ON rev.org_id=root.org_id AND rev.mapping_key=root.mapping_key
WHERE root.org_id=NEW.org_id AND root.mapping_key=NEW.mapping_key
AND rev.version=NEW.mapping_version;
IF attempt_branch IS NULL OR method IS NULL OR mapping IS NULL
 OR NOT method.is_enabled OR NOT mapping.is_enabled
 OR method.kind<>NEW.kind OR mapping.method_key<>NEW.method_key
 OR mapping.branch_id<>attempt_branch OR mapping.account_ref<>NEW.account_ref THEN
 RAISE EXCEPTION 'Tender requires exact enabled branch payment configuration'; END IF;
RETURN NEW; END; $$"""
TENDER_GUARD_TRIGGER = """CREATE TRIGGER sales_post_tender_guard BEFORE INSERT
ON containermgmt.sales_posting_tenders FOR EACH ROW
EXECUTE FUNCTION containermgmt.guard_sales_post_tender()"""


CARD_GUARD_FUNCTION = """CREATE OR REPLACE FUNCTION containermgmt.guard_sales_card_confirmation()
RETURNS trigger LANGUAGE plpgsql AS $$ DECLARE tender_kind text; prior integer; terminal integer; BEGIN
SELECT kind INTO tender_kind FROM containermgmt.sales_posting_tenders
WHERE org_id=NEW.org_id AND attempt_key=NEW.attempt_key
AND tender_key=NEW.tender_key FOR UPDATE;
IF tender_kind IS DISTINCT FROM 'CARD' THEN
 RAISE EXCEPTION 'Card confirmation requires an exact card tender'; END IF;
SELECT COALESCE(MAX(sequence),0), COUNT(*) FILTER (WHERE outcome = 'CONFIRMED')
INTO prior, terminal FROM containermgmt.sales_card_confirmations
WHERE org_id=NEW.org_id AND attempt_key=NEW.attempt_key
AND tender_key=NEW.tender_key;
IF terminal<>0 THEN RAISE EXCEPTION 'Confirmed card outcome is already terminal'; END IF;
IF NEW.sequence<>prior+1 THEN RAISE EXCEPTION 'Card outcome sequence must be consecutive'; END IF;
RETURN NEW; END; $$"""
CARD_GUARD_TRIGGER = """CREATE TRIGGER sales_card_confirmation_guard BEFORE INSERT
ON containermgmt.sales_card_confirmations FOR EACH ROW
EXECUTE FUNCTION containermgmt.guard_sales_card_confirmation()"""


INVOICE_GUARD_FUNCTION = """CREATE OR REPLACE FUNCTION containermgmt.guard_sales_invoice()
RETURNS trigger LANGUAGE plpgsql AS $$ DECLARE attempt record; BEGIN
SELECT operation_key, document_key, draft_version, branch_id, counter_id,
 branch_settings_version, counter_settings_version, assignment_version,
 business_date, customer_key, customer_version, currency, gross_total_scr,
 net_total_scr, tax_total_scr INTO attempt
FROM containermgmt.sales_posting_attempts
WHERE org_id=NEW.org_id AND attempt_key=NEW.attempt_key FOR UPDATE;
IF attempt IS NULL OR attempt.operation_key<>NEW.operation_key
 OR attempt.document_key<>NEW.document_key OR attempt.draft_version<>NEW.draft_version
 OR attempt.branch_id<>NEW.branch_id OR attempt.counter_id<>NEW.counter_id
 OR attempt.branch_settings_version<>NEW.branch_settings_version
 OR attempt.counter_settings_version<>NEW.counter_settings_version
 OR attempt.assignment_version<>NEW.assignment_version
 OR attempt.business_date<>NEW.business_date
 OR attempt.customer_key<>NEW.customer_key
 OR attempt.customer_version<>NEW.customer_version
 OR attempt.currency<>NEW.currency OR attempt.gross_total_scr<>NEW.gross_total_scr
 OR attempt.net_total_scr<>NEW.net_total_scr OR attempt.tax_total_scr<>NEW.tax_total_scr THEN
 RAISE EXCEPTION 'Invoice must finalize its exact posting attempt'; END IF;
RETURN NEW; END; $$"""
INVOICE_GUARD_TRIGGER = """CREATE TRIGGER sales_invoice_guard BEFORE INSERT
ON containermgmt.sales_invoices FOR EACH ROW
EXECUTE FUNCTION containermgmt.guard_sales_invoice()"""


LINE_GUARD_FUNCTION = """CREATE OR REPLACE FUNCTION containermgmt.guard_sales_invoice_line()
RETURNS trigger LANGUAGE plpgsql AS $$ DECLARE source record; attempt record; BEGIN
SELECT a.document_key, a.draft_version INTO attempt
FROM containermgmt.sales_invoices i JOIN containermgmt.sales_posting_attempts a
 ON a.org_id=i.org_id AND a.attempt_key=i.attempt_key
WHERE i.org_id=NEW.org_id AND i.invoice_key=NEW.invoice_key;
SELECT product_id, policy_version, quantity, unit, base_quantity, base_unit INTO source
FROM containermgmt.sales_intent_line_revisions
WHERE org_id=NEW.org_id AND document_key=NEW.document_key
AND version=NEW.draft_version AND line_key=NEW.source_line_key;
IF attempt IS NULL OR source IS NULL OR attempt.document_key<>NEW.document_key
 OR attempt.draft_version<>NEW.draft_version OR source.product_id<>NEW.product_id
 OR source.policy_version<>NEW.policy_version OR source.quantity<>NEW.quantity
 OR source.unit<>NEW.unit OR source.base_quantity<>NEW.base_quantity
 OR source.base_unit<>NEW.base_unit THEN
 RAISE EXCEPTION 'Invoice line must snapshot its exact draft line'; END IF;
RETURN NEW; END; $$"""
LINE_GUARD_TRIGGER = """CREATE TRIGGER sales_invoice_line_guard BEFORE INSERT
ON containermgmt.sales_invoice_lines FOR EACH ROW
EXECUTE FUNCTION containermgmt.guard_sales_invoice_line()"""


PAYMENT_GUARD_FUNCTION = """CREATE OR REPLACE FUNCTION containermgmt.guard_sales_invoice_payment()
RETURNS trigger LANGUAGE plpgsql AS $$ DECLARE invoice_attempt uuid; tender record; card record; BEGIN
SELECT attempt_key INTO invoice_attempt FROM containermgmt.sales_invoices
WHERE org_id=NEW.org_id AND invoice_key=NEW.invoice_key;
SELECT kind, account_ref, amount_scr INTO tender
FROM containermgmt.sales_posting_tenders WHERE org_id=NEW.org_id
AND attempt_key=NEW.attempt_key AND tender_key=NEW.tender_key;
IF invoice_attempt IS NULL OR invoice_attempt<>NEW.attempt_key OR tender IS NULL
 OR tender.kind<>NEW.kind OR tender.account_ref<>NEW.account_ref
 OR tender.amount_scr<>NEW.amount_scr THEN
 RAISE EXCEPTION 'Invoice payment must copy its exact attempt tender'; END IF;
IF NEW.kind='CARD' THEN
 SELECT attempt_key, tender_key, outcome INTO card
 FROM containermgmt.sales_card_confirmations
 WHERE org_id=NEW.org_id AND confirmation_key=NEW.confirmation_key;
 IF card IS NULL OR card.attempt_key<>NEW.attempt_key
  OR card.tender_key<>NEW.tender_key OR card.outcome<>'CONFIRMED' THEN
  RAISE EXCEPTION 'Card payment requires exact confirmed evidence'; END IF;
END IF;
RETURN NEW; END; $$"""
PAYMENT_GUARD_TRIGGER = """CREATE TRIGGER sales_invoice_payment_guard BEFORE INSERT
ON containermgmt.sales_invoice_payments FOR EACH ROW
EXECUTE FUNCTION containermgmt.guard_sales_invoice_payment()"""


RESERVATION_GUARD_FUNCTION = """CREATE OR REPLACE FUNCTION containermgmt.guard_sales_invoice_reservation()
RETURNS trigger LANGUAGE plpgsql AS $$ DECLARE line record; source record; stock record; BEGIN
SELECT document_key, draft_version, source_line_key INTO line
FROM containermgmt.sales_invoice_lines
WHERE org_id=NEW.org_id AND invoice_key=NEW.invoice_key AND line_key=NEW.line_key;
SELECT document_key, version, line_key INTO source
FROM containermgmt.sales_reservation_sources
WHERE org_id=NEW.org_id AND reservation_key=NEW.reservation_key;
SELECT quantity, released INTO stock
FROM containermgmt.inventory_stock_reservations
WHERE org_id=NEW.org_id AND reservation_key=NEW.reservation_key FOR UPDATE;
IF line IS NULL OR source IS NULL OR stock IS NULL
 OR source.document_key<>line.document_key OR source.version<>line.draft_version
 OR source.line_key<>line.source_line_key OR stock.quantity-stock.released<>NEW.quantity THEN
 RAISE EXCEPTION 'Invoice reservation must bind exact active draft demand'; END IF;
RETURN NEW; END; $$"""
RESERVATION_GUARD_TRIGGER = """CREATE TRIGGER sales_invoice_reservation_guard BEFORE INSERT
ON containermgmt.sales_invoice_reservations FOR EACH ROW
EXECUTE FUNCTION containermgmt.guard_sales_invoice_reservation()"""


COMMITTED_RELEASE_FUNCTION = """CREATE OR REPLACE FUNCTION containermgmt.guard_posted_sale_reservation_release()
RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
IF NEW.kind='RELEASE' AND EXISTS (
 SELECT 1 FROM containermgmt.inventory_stock_reservations hold
 JOIN containermgmt.sales_invoice_reservations committed
   ON committed.org_id=hold.org_id AND committed.reservation_key=hold.reservation_key
 WHERE hold.org_id=NEW.org_id AND hold.id=NEW.reservation_id
) THEN RAISE EXCEPTION 'Posted-sale stock cannot be released; use collection or return workflow'; END IF;
RETURN NEW; END; $$"""
COMMITTED_RELEASE_TRIGGER = """CREATE TRIGGER posted_sale_reservation_release_guard BEFORE INSERT
ON containermgmt.inventory_stock_movements FOR EACH ROW
EXECUTE FUNCTION containermgmt.guard_posted_sale_reservation_release()"""


COMMITTED_RESERVATION_UPDATE_FUNCTION = """CREATE OR REPLACE FUNCTION containermgmt.guard_posted_sale_reservation_update()
RETURNS trigger LANGUAGE plpgsql AS $$ DECLARE committed numeric; issued_at timestamptz;
handed_over numeric; BEGIN
IF NEW.released <= OLD.released THEN RETURN NULL; END IF;
SELECT binding.quantity, invoice.issued_at INTO committed, issued_at
FROM containermgmt.sales_invoice_reservations binding
JOIN containermgmt.sales_invoices invoice
 ON invoice.org_id=binding.org_id AND invoice.invoice_key=binding.invoice_key
WHERE binding.org_id=NEW.org_id AND binding.reservation_key=NEW.reservation_key;
IF committed IS NULL THEN RETURN NULL; END IF;
SELECT COALESCE(SUM(-movement.on_hand_delta),0) INTO handed_over
FROM containermgmt.inventory_stock_movements movement
WHERE movement.org_id=NEW.org_id AND movement.reservation_id=NEW.id
AND movement.balance_id=NEW.balance_id AND movement.kind='HANDOVER'
AND movement.created_at >= issued_at;
IF NEW.released <> NEW.quantity-committed+handed_over THEN
 RAISE EXCEPTION 'Posted-sale reservation changes require exact cumulative handover history'; END IF;
RETURN NULL; END; $$"""
COMMITTED_RESERVATION_UPDATE_TRIGGER = """CREATE CONSTRAINT TRIGGER posted_sale_reservation_update_guard
AFTER UPDATE OF released ON containermgmt.inventory_stock_reservations
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
EXECUTE FUNCTION containermgmt.guard_posted_sale_reservation_update()"""


TOTALS_FUNCTION = """CREATE OR REPLACE FUNCTION containermgmt.check_sales_posting_totals()
RETURNS trigger LANGUAGE plpgsql AS $$ DECLARE key uuid; company integer; attempt uuid;
expected record; lines record; paid numeric; reserved_bad integer; tendered numeric; BEGIN
company=NEW.org_id;
IF TG_TABLE_NAME IN ('sales_posting_attempts','sales_posting_tenders') THEN
 attempt=NEW.attempt_key;
 SELECT gross_total_scr INTO expected FROM containermgmt.sales_posting_attempts
 WHERE org_id=company AND attempt_key=attempt;
 SELECT COALESCE(SUM(amount_scr),0) INTO tendered
 FROM containermgmt.sales_posting_tenders WHERE org_id=company AND attempt_key=attempt;
 IF expected IS NULL OR tendered<>expected.gross_total_scr THEN
  RAISE EXCEPTION 'Attempt tenders must equal the exact invoice total'; END IF;
 RETURN NULL;
END IF;
key=NEW.invoice_key;
SELECT gross_total_scr, net_total_scr, tax_total_scr INTO expected
FROM containermgmt.sales_invoices WHERE org_id=company AND invoice_key=key;
SELECT COALESCE(SUM(gross_total_scr),0) gross, COALESCE(SUM(net_total_scr),0) net,
 COALESCE(SUM(tax_total_scr),0) tax INTO lines
FROM containermgmt.sales_invoice_lines WHERE org_id=company AND invoice_key=key;
SELECT COALESCE(SUM(amount_scr),0) INTO paid FROM containermgmt.sales_invoice_payments
WHERE org_id=company AND invoice_key=key;
SELECT COUNT(*) INTO reserved_bad FROM containermgmt.sales_invoice_lines line
WHERE line.org_id=company AND line.invoice_key=key AND line.base_quantity<>(
 SELECT COALESCE(SUM(binding.quantity),0)
 FROM containermgmt.sales_invoice_reservations binding
 WHERE binding.org_id=line.org_id AND binding.invoice_key=line.invoice_key
 AND binding.line_key=line.line_key);
IF expected IS NULL OR lines.gross<>expected.gross_total_scr
 OR lines.net<>expected.net_total_scr OR lines.tax<>expected.tax_total_scr
 OR paid<>expected.gross_total_scr OR reserved_bad<>0 THEN
 RAISE EXCEPTION 'Invoice lines, payments and reservations must exactly reconcile'; END IF;
RETURN NULL; END; $$"""


def totals_trigger(table):
    return f"""CREATE CONSTRAINT TRIGGER {table}_totals_guard AFTER INSERT
ON containermgmt.{table} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
EXECUTE FUNCTION containermgmt.check_sales_posting_totals()"""


for model in MODELS:
    event.listen(model.__table__, "after_create", DDL(IMMUTABLE_FUNCTION))
    event.listen(model.__table__, "after_create", DDL(immutable_trigger(model.__tablename__)))

for model, function, trigger in (
    (SalesPostingAttempt, ATTEMPT_GUARD_FUNCTION, ATTEMPT_GUARD_TRIGGER),
    (SalesPostingTender, TENDER_GUARD_FUNCTION, TENDER_GUARD_TRIGGER),
    (SalesCardConfirmation, CARD_GUARD_FUNCTION, CARD_GUARD_TRIGGER),
    (SalesInvoice, INVOICE_GUARD_FUNCTION, INVOICE_GUARD_TRIGGER),
    (SalesInvoiceLine, LINE_GUARD_FUNCTION, LINE_GUARD_TRIGGER),
    (SalesInvoicePayment, PAYMENT_GUARD_FUNCTION, PAYMENT_GUARD_TRIGGER),
    (SalesInvoiceReservation, RESERVATION_GUARD_FUNCTION, RESERVATION_GUARD_TRIGGER),
):
    event.listen(model.__table__, "after_create", DDL(function))
    event.listen(model.__table__, "after_create", DDL(trigger))

for model in (SalesPostingAttempt, SalesPostingTender, SalesInvoice,
              SalesInvoiceLine, SalesInvoicePayment, SalesInvoiceReservation):
    event.listen(model.__table__, "after_create", DDL(TOTALS_FUNCTION))
    event.listen(model.__table__, "after_create", DDL(totals_trigger(model.__tablename__)))

event.listen(SalesInvoiceReservation.__table__, "after_create", DDL(COMMITTED_RELEASE_FUNCTION))
event.listen(SalesInvoiceReservation.__table__, "after_create", DDL(COMMITTED_RELEASE_TRIGGER))
event.listen(SalesInvoiceReservation.__table__, "after_create",
             DDL(COMMITTED_RESERVATION_UPDATE_FUNCTION))
event.listen(SalesInvoiceReservation.__table__, "after_create",
             DDL(COMMITTED_RESERVATION_UPDATE_TRIGGER))
