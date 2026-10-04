"""Stable sales-pricing identities with immutable, consecutive revisions."""
from sqlalchemy import (
    Boolean, CheckConstraint, Column, DDL, ForeignKeyConstraint, Integer,
    DateTime, Numeric, String, UniqueConstraint, event,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from Model.db import Base
from Model.mixins import AuditMixin, OrgMixin
from Model.containermgmt.Inventory.ManagerCase import ManagerCase  # noqa: F401 - register referenced table
from Model.containermgmt.Orders.SalesIntent import SalesIntentRevision  # noqa: F401 - register referenced table


class SalesTaxRule(OrgMixin, AuditMixin, Base):
    __tablename__ = "sales_tax_rules"
    __table_args__ = (
        UniqueConstraint("tax_rule_key", "org_id", name="uq_sales_tax_rule_scope"),
        UniqueConstraint("org_id", "code", name="uq_sales_tax_rule_code"),
        ForeignKeyConstraint(
            ["org_id", "creation_operation_key"],
            ["containermgmt.inventory_posting_operations.org_id",
             "containermgmt.inventory_posting_operations.operation_key"],
            name="fk_sales_tax_rule_creation", deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint(
            "code ~ '^[A-Z0-9][A-Z0-9_-]{0,31}$'",
            name="ck_sales_tax_rule_code",
        ),
        CheckConstraint(
            "created_by IS NOT NULL AND NOT is_deleted AND deleted_at IS NULL",
            name="ck_sales_tax_rule_audit",
        ),
        {"schema": "containermgmt"},
    )
    tax_rule_key = Column(UUID(as_uuid=True), primary_key=True)
    code = Column(String(32), nullable=False)
    creation_operation_key = Column(UUID(as_uuid=True), nullable=False)


class SalesTaxRuleRevision(OrgMixin, AuditMixin, Base):
    __tablename__ = "sales_tax_rule_revisions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tax_rule_key", "org_id"],
            ["containermgmt.sales_tax_rules.tax_rule_key",
             "containermgmt.sales_tax_rules.org_id"],
            name="fk_sales_tax_revision_scope",
        ),
        ForeignKeyConstraint(
            ["org_id", "operation_key"],
            ["containermgmt.inventory_posting_operations.org_id",
             "containermgmt.inventory_posting_operations.operation_key"],
            name="fk_sales_tax_revision_operation", deferrable=True,
            initially="DEFERRED",
        ),
        UniqueConstraint(
            "org_id", "tax_rule_key", "version",
            name="uq_sales_tax_revision_version",
        ),
        UniqueConstraint(
            "org_id", "operation_key", name="uq_sales_tax_revision_operation",
        ),
        CheckConstraint("version > 0", name="ck_sales_tax_revision_version"),
        CheckConstraint(
            "treatment IN ('STANDARD', 'ZERO_RATED', 'EXEMPT')",
            name="ck_sales_tax_revision_treatment",
        ),
        CheckConstraint(
            "(treatment = 'STANDARD' AND rate > 0 AND rate < 10) OR "
            "(treatment IN ('ZERO_RATED', 'EXEMPT') AND rate = 0)",
            name="ck_sales_tax_revision_rate",
        ),
        CheckConstraint(
            "length(trim(name)) > 0 AND length(trim(reason)) > 0",
            name="ck_sales_tax_revision_text",
        ),
        CheckConstraint(
            "created_by IS NOT NULL AND NOT is_deleted AND deleted_at IS NULL",
            name="ck_sales_tax_revision_audit",
        ),
        {"schema": "containermgmt"},
    )
    id = Column(Integer, primary_key=True)
    tax_rule_key = Column(UUID(as_uuid=True), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    operation_key = Column(UUID(as_uuid=True), nullable=False)
    name = Column(String(120), nullable=False)
    treatment = Column(String(20), nullable=False)
    rate = Column(Numeric(12, 8), nullable=False)
    is_enabled = Column(Boolean, nullable=False)
    reason = Column(String(500), nullable=False)


class BranchProductPrice(OrgMixin, AuditMixin, Base):
    __tablename__ = "sales_branch_product_prices"
    __table_args__ = (
        UniqueConstraint("price_key", "org_id", name="uq_branch_product_price_scope"),
        UniqueConstraint(
            "org_id", "branch_id", "product_id", "unit",
            name="uq_branch_product_price_target",
        ),
        ForeignKeyConstraint(
            ["branch_id", "org_id"],
            ["containermgmt.inventory_branches.id",
             "containermgmt.inventory_branches.org_id"],
            name="fk_branch_product_price_branch",
        ),
        ForeignKeyConstraint(
            ["product_id", "org_id"],
            ["containermgmt.products.id", "containermgmt.products.org_id"],
            name="fk_branch_product_price_product",
        ),
        ForeignKeyConstraint(
            ["org_id", "creation_operation_key"],
            ["containermgmt.inventory_posting_operations.org_id",
             "containermgmt.inventory_posting_operations.operation_key"],
            name="fk_branch_product_price_creation", deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint(
            "created_by IS NOT NULL AND NOT is_deleted AND deleted_at IS NULL",
            name="ck_branch_product_price_audit",
        ),
        CheckConstraint("length(trim(unit)) > 0", name="ck_branch_product_price_unit"),
        {"schema": "containermgmt"},
    )
    price_key = Column(UUID(as_uuid=True), primary_key=True)
    branch_id = Column(Integer, nullable=False, index=True)
    product_id = Column(Integer, nullable=False, index=True)
    unit = Column(String(50), nullable=False)
    creation_operation_key = Column(UUID(as_uuid=True), nullable=False)


class BranchProductPriceRevision(OrgMixin, AuditMixin, Base):
    __tablename__ = "sales_branch_product_price_revisions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["price_key", "org_id"],
            ["containermgmt.sales_branch_product_prices.price_key",
             "containermgmt.sales_branch_product_prices.org_id"],
            name="fk_branch_product_price_revision_scope",
        ),
        ForeignKeyConstraint(
            ["org_id", "operation_key"],
            ["containermgmt.inventory_posting_operations.org_id",
             "containermgmt.inventory_posting_operations.operation_key"],
            name="fk_branch_product_price_revision_operation", deferrable=True,
            initially="DEFERRED",
        ),
        UniqueConstraint(
            "org_id", "price_key", "version",
            name="uq_branch_product_price_revision_version",
        ),
        UniqueConstraint(
            "org_id", "operation_key",
            name="uq_branch_product_price_revision_operation",
        ),
        CheckConstraint("version > 0", name="ck_branch_product_price_revision_version"),
        CheckConstraint(
            "gross_unit_scr > 0 AND gross_unit_scr < 1000000000000000000",
            name="ck_branch_product_price_revision_gross",
        ),
        CheckConstraint(
            "floor_gross_unit_scr IS NULL OR "
            "(floor_gross_unit_scr >= 0 AND floor_gross_unit_scr <= gross_unit_scr)",
            name="ck_branch_product_price_revision_floor",
        ),
        CheckConstraint("length(trim(reason)) > 0", name="ck_branch_product_price_revision_reason"),
        CheckConstraint(
            "created_by IS NOT NULL AND NOT is_deleted AND deleted_at IS NULL",
            name="ck_branch_product_price_revision_audit",
        ),
        {"schema": "containermgmt"},
    )
    id = Column(Integer, primary_key=True)
    price_key = Column(UUID(as_uuid=True), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    operation_key = Column(UUID(as_uuid=True), nullable=False)
    gross_unit_scr = Column(Numeric(24, 6), nullable=False)
    floor_gross_unit_scr = Column(Numeric(24, 6), nullable=True)
    is_enabled = Column(Boolean, nullable=False)
    reason = Column(String(500), nullable=False)


class ProductTaxAssignment(OrgMixin, AuditMixin, Base):
    __tablename__ = "sales_product_tax_assignments"
    __table_args__ = (
        UniqueConstraint("assignment_key", "org_id", name="uq_product_tax_assignment_scope"),
        UniqueConstraint("org_id", "product_id", name="uq_product_tax_assignment_target"),
        ForeignKeyConstraint(
            ["product_id", "org_id"],
            ["containermgmt.products.id", "containermgmt.products.org_id"],
            name="fk_product_tax_assignment_product",
        ),
        ForeignKeyConstraint(
            ["org_id", "creation_operation_key"],
            ["containermgmt.inventory_posting_operations.org_id",
             "containermgmt.inventory_posting_operations.operation_key"],
            name="fk_product_tax_assignment_creation", deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint(
            "created_by IS NOT NULL AND NOT is_deleted AND deleted_at IS NULL",
            name="ck_product_tax_assignment_audit",
        ),
        {"schema": "containermgmt"},
    )
    assignment_key = Column(UUID(as_uuid=True), primary_key=True)
    product_id = Column(Integer, nullable=False, index=True)
    creation_operation_key = Column(UUID(as_uuid=True), nullable=False)


class ProductTaxAssignmentRevision(OrgMixin, AuditMixin, Base):
    __tablename__ = "sales_product_tax_assignment_revisions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["assignment_key", "org_id"],
            ["containermgmt.sales_product_tax_assignments.assignment_key",
             "containermgmt.sales_product_tax_assignments.org_id"],
            name="fk_product_tax_assignment_revision_scope",
        ),
        ForeignKeyConstraint(
            ["tax_rule_key", "org_id"],
            ["containermgmt.sales_tax_rules.tax_rule_key",
             "containermgmt.sales_tax_rules.org_id"],
            name="fk_product_tax_assignment_revision_tax",
        ),
        ForeignKeyConstraint(
            ["org_id", "operation_key"],
            ["containermgmt.inventory_posting_operations.org_id",
             "containermgmt.inventory_posting_operations.operation_key"],
            name="fk_product_tax_assignment_revision_operation", deferrable=True,
            initially="DEFERRED",
        ),
        UniqueConstraint(
            "org_id", "assignment_key", "version",
            name="uq_product_tax_assignment_revision_version",
        ),
        UniqueConstraint(
            "org_id", "operation_key",
            name="uq_product_tax_assignment_revision_operation",
        ),
        CheckConstraint("version > 0", name="ck_product_tax_assignment_revision_version"),
        CheckConstraint("length(trim(reason)) > 0", name="ck_product_tax_assignment_revision_reason"),
        CheckConstraint(
            "created_by IS NOT NULL AND NOT is_deleted AND deleted_at IS NULL",
            name="ck_product_tax_assignment_revision_audit",
        ),
        {"schema": "containermgmt"},
    )
    id = Column(Integer, primary_key=True)
    assignment_key = Column(UUID(as_uuid=True), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    operation_key = Column(UUID(as_uuid=True), nullable=False)
    tax_rule_key = Column(UUID(as_uuid=True), nullable=False, index=True)
    is_enabled = Column(Boolean, nullable=False)
    reason = Column(String(500), nullable=False)


class CustomerPriceAgreement(OrgMixin, AuditMixin, Base):
    __tablename__ = "sales_customer_price_agreements"
    __table_args__ = (
        UniqueConstraint("agreement_key", "org_id", name="uq_customer_price_agreement_scope"),
        UniqueConstraint(
            "org_id", "customer_key", "branch_id", "product_id", "unit",
            name="uq_customer_price_agreement_target",
        ),
        ForeignKeyConstraint(
            ["customer_key", "org_id"],
            ["containermgmt.retail_customers.customer_key",
             "containermgmt.retail_customers.org_id"],
            name="fk_customer_price_agreement_customer",
        ),
        ForeignKeyConstraint(
            ["branch_id", "org_id"],
            ["containermgmt.inventory_branches.id",
             "containermgmt.inventory_branches.org_id"],
            name="fk_customer_price_agreement_branch",
        ),
        ForeignKeyConstraint(
            ["product_id", "org_id"],
            ["containermgmt.products.id", "containermgmt.products.org_id"],
            name="fk_customer_price_agreement_product",
        ),
        ForeignKeyConstraint(
            ["org_id", "creation_operation_key"],
            ["containermgmt.inventory_posting_operations.org_id",
             "containermgmt.inventory_posting_operations.operation_key"],
            name="fk_customer_price_agreement_creation", deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint(
            "created_by IS NOT NULL AND NOT is_deleted AND deleted_at IS NULL",
            name="ck_customer_price_agreement_audit",
        ),
        CheckConstraint("length(trim(unit)) > 0", name="ck_customer_price_agreement_unit"),
        {"schema": "containermgmt"},
    )
    agreement_key = Column(UUID(as_uuid=True), primary_key=True)
    customer_key = Column(UUID(as_uuid=True), nullable=False, index=True)
    branch_id = Column(Integer, nullable=False, index=True)
    product_id = Column(Integer, nullable=False, index=True)
    unit = Column(String(50), nullable=False)
    creation_operation_key = Column(UUID(as_uuid=True), nullable=False)


class CustomerPriceAgreementRevision(OrgMixin, AuditMixin, Base):
    __tablename__ = "sales_customer_price_agreement_revisions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["agreement_key", "org_id"],
            ["containermgmt.sales_customer_price_agreements.agreement_key",
             "containermgmt.sales_customer_price_agreements.org_id"],
            name="fk_customer_price_agreement_revision_scope",
        ),
        ForeignKeyConstraint(
            ["org_id", "operation_key"],
            ["containermgmt.inventory_posting_operations.org_id",
             "containermgmt.inventory_posting_operations.operation_key"],
            name="fk_customer_price_agreement_revision_operation", deferrable=True,
            initially="DEFERRED",
        ),
        UniqueConstraint(
            "org_id", "agreement_key", "version",
            name="uq_customer_price_agreement_revision_version",
        ),
        UniqueConstraint(
            "org_id", "operation_key",
            name="uq_customer_price_agreement_revision_operation",
        ),
        CheckConstraint("version > 0", name="ck_customer_price_agreement_revision_version"),
        CheckConstraint(
            "gross_unit_scr > 0 AND gross_unit_scr < 1000000000000000000",
            name="ck_customer_price_agreement_revision_gross",
        ),
        CheckConstraint(
            "valid_until IS NULL OR valid_until > valid_from",
            name="ck_customer_price_agreement_revision_period",
        ),
        CheckConstraint(
            "length(trim(terms_reference)) > 0 AND length(trim(reason)) > 0",
            name="ck_customer_price_agreement_revision_text",
        ),
        CheckConstraint(
            "created_by IS NOT NULL AND NOT is_deleted AND deleted_at IS NULL",
            name="ck_customer_price_agreement_revision_audit",
        ),
        {"schema": "containermgmt"},
    )
    id = Column(Integer, primary_key=True)
    agreement_key = Column(UUID(as_uuid=True), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    operation_key = Column(UUID(as_uuid=True), nullable=False)
    gross_unit_scr = Column(Numeric(24, 6), nullable=False)
    valid_from = Column(DateTime(timezone=True), nullable=False)
    valid_until = Column(DateTime(timezone=True), nullable=True)
    terms_reference = Column(String(200), nullable=False)
    is_enabled = Column(Boolean, nullable=False)
    reason = Column(String(500), nullable=False)


class SalesTransactionPricing(OrgMixin, AuditMixin, Base):
    """Immutable, explicitly selected pricing input for a future sale posting.

    This record is not an invoice and has no payment, stock or approval-consumption
    effect. T13 must name one exact snapshot and revalidate/consume any referenced
    floor case inside the eventual atomic sale transaction.
    """
    __tablename__ = "sales_transaction_pricing"
    __table_args__ = (
        UniqueConstraint(
            "pricing_snapshot_key", "org_id",
            name="uq_sales_transaction_pricing_scope",
        ),
        UniqueConstraint(
            "org_id", "operation_key",
            name="uq_sales_transaction_pricing_operation",
        ),
        ForeignKeyConstraint(
            ["org_id", "document_key", "draft_version"],
            ["containermgmt.sales_intent_revisions.org_id",
             "containermgmt.sales_intent_revisions.document_key",
             "containermgmt.sales_intent_revisions.version"],
            name="fk_sales_transaction_pricing_draft",
        ),
        ForeignKeyConstraint(
            ["org_id", "operation_key"],
            ["containermgmt.inventory_posting_operations.org_id",
             "containermgmt.inventory_posting_operations.operation_key"],
            name="fk_sales_transaction_pricing_operation",
            deferrable=True, initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["org_id", "floor_case_key"],
            ["containermgmt.manager_cases.org_id",
             "containermgmt.manager_cases.case_key"],
            name="fk_sales_transaction_pricing_floor_case",
        ),
        CheckConstraint(
            "pricing_snapshot_key <> '00000000-0000-0000-0000-000000000000'::uuid "
            "AND draft_version > 0",
            name="ck_sales_transaction_pricing_identity",
        ),
        CheckConstraint(
            "currency = 'SCR' AND length(trim(policy)) > 0",
            name="ck_sales_transaction_pricing_policy",
        ),
        CheckConstraint(
            "jsonb_typeof(pricing) = 'object' AND "
            "pricing_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_sales_transaction_pricing_payload",
        ),
        CheckConstraint(
            "gross_total_scr >= 0 AND net_total_scr >= 0 AND tax_total_scr >= 0 "
            "AND gross_total_scr = net_total_scr + tax_total_scr",
            name="ck_sales_transaction_pricing_totals",
        ),
        CheckConstraint(
            "requires_floor_approval = (floor_case_key IS NOT NULL)",
            name="ck_sales_transaction_pricing_floor_case",
        ),
        CheckConstraint(
            "created_by IS NOT NULL AND NOT is_deleted AND deleted_at IS NULL",
            name="ck_sales_transaction_pricing_audit",
        ),
        {"schema": "containermgmt"},
    )
    pricing_snapshot_key = Column(UUID(as_uuid=True), primary_key=True)
    document_key = Column(UUID(as_uuid=True), nullable=False, index=True)
    draft_version = Column(Integer, nullable=False)
    operation_key = Column(UUID(as_uuid=True), nullable=False)
    priced_at = Column(DateTime(timezone=True), nullable=False)
    currency = Column(String(3), nullable=False)
    policy = Column(String(64), nullable=False)
    pricing = Column(JSONB, nullable=False)
    pricing_fingerprint = Column(String(64), nullable=False)
    gross_total_scr = Column(Numeric(24, 2), nullable=False)
    net_total_scr = Column(Numeric(24, 2), nullable=False)
    tax_total_scr = Column(Numeric(24, 2), nullable=False)
    requires_floor_approval = Column(Boolean, nullable=False)
    floor_case_key = Column(UUID(as_uuid=True), nullable=True)


IMMUTABLE_FUNCTION = """CREATE OR REPLACE FUNCTION containermgmt.reject_sales_pricing_change()
RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
RAISE EXCEPTION 'Sales pricing identities and revisions are immutable'; END; $$"""


def immutable_trigger(table):
    return f"""CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE
ON containermgmt.{table} FOR EACH ROW
EXECUTE FUNCTION containermgmt.reject_sales_pricing_change()"""


TAX_REVISION_FUNCTION = """CREATE OR REPLACE FUNCTION containermgmt.guard_sales_tax_revision()
RETURNS trigger LANGUAGE plpgsql AS $$ DECLARE prior integer; BEGIN
PERFORM 1 FROM containermgmt.sales_tax_rules
WHERE org_id = NEW.org_id AND tax_rule_key = NEW.tax_rule_key FOR UPDATE;
IF NOT FOUND THEN RAISE EXCEPTION 'Sales tax rule scope unavailable'; END IF;
SELECT COALESCE(MAX(version), 0) INTO prior
FROM containermgmt.sales_tax_rule_revisions
WHERE org_id = NEW.org_id AND tax_rule_key = NEW.tax_rule_key;
IF NEW.version <> prior + 1 THEN
RAISE EXCEPTION 'Sales tax rule version must be consecutive'; END IF;
RETURN NEW; END; $$"""
TAX_REVISION_TRIGGER = """CREATE TRIGGER sales_tax_revision_guard BEFORE INSERT
ON containermgmt.sales_tax_rule_revisions FOR EACH ROW
EXECUTE FUNCTION containermgmt.guard_sales_tax_revision()"""


PRICE_REVISION_FUNCTION = """CREATE OR REPLACE FUNCTION containermgmt.guard_branch_product_price_revision()
RETURNS trigger LANGUAGE plpgsql AS $$ DECLARE prior integer; BEGIN
PERFORM 1 FROM containermgmt.sales_branch_product_prices
WHERE org_id = NEW.org_id AND price_key = NEW.price_key FOR UPDATE;
IF NOT FOUND THEN RAISE EXCEPTION 'Branch product price scope unavailable'; END IF;
SELECT COALESCE(MAX(version), 0) INTO prior
FROM containermgmt.sales_branch_product_price_revisions
WHERE org_id = NEW.org_id AND price_key = NEW.price_key;
IF NEW.version <> prior + 1 THEN
RAISE EXCEPTION 'Branch product price version must be consecutive'; END IF;
RETURN NEW; END; $$"""
PRICE_REVISION_TRIGGER = """CREATE TRIGGER branch_product_price_revision_guard BEFORE INSERT
ON containermgmt.sales_branch_product_price_revisions FOR EACH ROW
EXECUTE FUNCTION containermgmt.guard_branch_product_price_revision()"""


PRODUCT_TAX_REVISION_FUNCTION = """CREATE OR REPLACE FUNCTION containermgmt.guard_product_tax_assignment_revision()
RETURNS trigger LANGUAGE plpgsql AS $$ DECLARE prior integer; BEGIN
PERFORM 1 FROM containermgmt.sales_product_tax_assignments
WHERE org_id = NEW.org_id AND assignment_key = NEW.assignment_key FOR UPDATE;
IF NOT FOUND THEN RAISE EXCEPTION 'Product tax assignment scope unavailable'; END IF;
SELECT COALESCE(MAX(version), 0) INTO prior
FROM containermgmt.sales_product_tax_assignment_revisions
WHERE org_id = NEW.org_id AND assignment_key = NEW.assignment_key;
IF NEW.version <> prior + 1 THEN
RAISE EXCEPTION 'Product tax assignment version must be consecutive'; END IF;
RETURN NEW; END; $$"""
PRODUCT_TAX_REVISION_TRIGGER = """CREATE TRIGGER product_tax_assignment_revision_guard BEFORE INSERT
ON containermgmt.sales_product_tax_assignment_revisions FOR EACH ROW
EXECUTE FUNCTION containermgmt.guard_product_tax_assignment_revision()"""


AGREEMENT_REVISION_FUNCTION = """CREATE OR REPLACE FUNCTION containermgmt.guard_customer_price_agreement_revision()
RETURNS trigger LANGUAGE plpgsql AS $$ DECLARE prior integer; BEGIN
PERFORM 1 FROM containermgmt.sales_customer_price_agreements
WHERE org_id = NEW.org_id AND agreement_key = NEW.agreement_key FOR UPDATE;
IF NOT FOUND THEN RAISE EXCEPTION 'Customer price agreement scope unavailable'; END IF;
SELECT COALESCE(MAX(version), 0) INTO prior
FROM containermgmt.sales_customer_price_agreement_revisions
WHERE org_id = NEW.org_id AND agreement_key = NEW.agreement_key;
IF NEW.version <> prior + 1 THEN
RAISE EXCEPTION 'Customer price agreement version must be consecutive'; END IF;
RETURN NEW; END; $$"""
AGREEMENT_REVISION_TRIGGER = """CREATE TRIGGER customer_price_agreement_revision_guard BEFORE INSERT
ON containermgmt.sales_customer_price_agreement_revisions FOR EACH ROW
EXECUTE FUNCTION containermgmt.guard_customer_price_agreement_revision()"""


for model in (SalesTaxRule, SalesTaxRuleRevision, BranchProductPrice,
              BranchProductPriceRevision, ProductTaxAssignment,
              ProductTaxAssignmentRevision, CustomerPriceAgreement,
              CustomerPriceAgreementRevision, SalesTransactionPricing):
    event.listen(model.__table__, "after_create", DDL(IMMUTABLE_FUNCTION))
    event.listen(model.__table__, "after_create", DDL(immutable_trigger(model.__tablename__)))
event.listen(SalesTaxRuleRevision.__table__, "after_create", DDL(TAX_REVISION_FUNCTION))
event.listen(SalesTaxRuleRevision.__table__, "after_create", DDL(TAX_REVISION_TRIGGER))
event.listen(BranchProductPriceRevision.__table__, "after_create", DDL(PRICE_REVISION_FUNCTION))
event.listen(BranchProductPriceRevision.__table__, "after_create", DDL(PRICE_REVISION_TRIGGER))
event.listen(ProductTaxAssignmentRevision.__table__, "after_create", DDL(PRODUCT_TAX_REVISION_FUNCTION))
event.listen(ProductTaxAssignmentRevision.__table__, "after_create", DDL(PRODUCT_TAX_REVISION_TRIGGER))
event.listen(CustomerPriceAgreementRevision.__table__, "after_create", DDL(AGREEMENT_REVISION_FUNCTION))
event.listen(CustomerPriceAgreementRevision.__table__, "after_create", DDL(AGREEMENT_REVISION_TRIGGER))
