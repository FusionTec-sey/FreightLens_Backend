"""Versioned retail demand; these records never prove payment or stock authority."""
from sqlalchemy import Column, Integer, String, Numeric, UniqueConstraint, ForeignKeyConstraint, CheckConstraint, Index, DDL, event
from sqlalchemy.dialects.postgresql import UUID, JSONB
from Model.db import Base
from Model.mixins import OrgMixin, AuditMixin
from Model.containermgmt.MasterData.RetailCustomer import RetailCustomer  # noqa: F401 - register referenced table for isolated imports
from Model.containermgmt.MasterData.CustomerProfileRevision import CustomerProfileRevision


class SalesIntent(OrgMixin, AuditMixin, Base):
    __tablename__ = 'sales_intents'
    __table_args__ = (
        UniqueConstraint('org_id', 'document_key', name='uq_sales_intent_scope'),
        CheckConstraint("document_key <> '00000000-0000-0000-0000-000000000000'::uuid", name='ck_sales_intent_key'),
        CheckConstraint('created_by IS NOT NULL AND NOT is_deleted', name='ck_sales_intent_audit'),
        {'schema': 'containermgmt'},
    )
    document_key = Column(UUID(as_uuid=True), primary_key=True)


class SalesIntentRevision(OrgMixin, AuditMixin, Base):
    __tablename__ = 'sales_intent_revisions'
    __table_args__ = (
        UniqueConstraint('org_id', 'document_key', 'version', name='uq_sales_revision_scope'),
        UniqueConstraint('org_id', 'operation_key', name='uq_sales_revision_operation'),
        ForeignKeyConstraint(['org_id', 'document_key'], ['containermgmt.sales_intents.org_id', 'containermgmt.sales_intents.document_key']),
        ForeignKeyConstraint(['customer_key', 'org_id'], ['containermgmt.retail_customers.customer_key', 'containermgmt.retail_customers.org_id']),
        ForeignKeyConstraint(['branch_id', 'org_id'], ['containermgmt.inventory_branches.id', 'containermgmt.inventory_branches.org_id']),
        ForeignKeyConstraint(['org_id', 'operation_key'], ['containermgmt.inventory_posting_operations.org_id', 'containermgmt.inventory_posting_operations.operation_key'], deferrable=True, initially='DEFERRED'),
        CheckConstraint("version > 0 AND customer_version > 0 AND status = 'DRAFT'", name='ck_sales_revision_state'),
        CheckConstraint('created_by IS NOT NULL AND NOT is_deleted', name='ck_sales_revision_audit'),
        Index('ix_sales_revision_customer', 'org_id', 'customer_key'),
        Index('ix_sales_revision_branch', 'org_id', 'branch_id'),
        {'schema': 'containermgmt'},
    )
    document_key = Column(UUID(as_uuid=True), primary_key=True)
    version = Column(Integer, primary_key=True)
    operation_key = Column(UUID(as_uuid=True), nullable=False)
    customer_key = Column(UUID(as_uuid=True), nullable=False)
    customer_version = Column(Integer, nullable=False)
    branch_id = Column(Integer, nullable=False)
    status = Column(String(16), nullable=False, default='DRAFT')


class SalesIntentLineRevision(OrgMixin, AuditMixin, Base):
    __tablename__ = 'sales_intent_line_revisions'
    __table_args__ = (
        ForeignKeyConstraint(['org_id', 'document_key', 'version'], ['containermgmt.sales_intent_revisions.org_id', 'containermgmt.sales_intent_revisions.document_key', 'containermgmt.sales_intent_revisions.version']),
        ForeignKeyConstraint(['org_id', 'product_id', 'policy_version'], ['containermgmt.inventory_product_policy_activations.org_id', 'containermgmt.inventory_product_policy_activations.product_id', 'containermgmt.inventory_product_policy_activations.version']),
        UniqueConstraint('org_id', 'document_key', 'version', 'line_key', name='uq_sales_line_revision_scope'),
        UniqueConstraint('document_key', 'version', 'position', name='uq_sales_line_position'),
        CheckConstraint("quantity > 0 AND base_quantity > 0 AND position BETWEEN 1 AND 100 AND jsonb_typeof(policy) = 'object'", name='ck_sales_line_quantity'),
        CheckConstraint("line_key <> '00000000-0000-0000-0000-000000000000'::uuid AND created_by IS NOT NULL AND NOT is_deleted", name='ck_sales_line_identity'),
        Index('ix_sales_line_policy', 'org_id', 'product_id', 'policy_version'),
        {'schema': 'containermgmt'},
    )
    document_key = Column(UUID(as_uuid=True), primary_key=True)
    version = Column(Integer, primary_key=True)
    line_key = Column(UUID(as_uuid=True), primary_key=True)
    position = Column(Integer, nullable=False)
    product_id = Column(Integer, nullable=False)
    policy_version = Column(Integer, nullable=False)
    quantity = Column(Numeric(18, 6), nullable=False)
    unit = Column(String(50), nullable=False)
    base_quantity = Column(Numeric(18, 6), nullable=False)
    base_unit = Column(String(50), nullable=False)
    policy = Column(JSONB, nullable=False)


TABLES = (SalesIntent.__table__, SalesIntentRevision.__table__, SalesIntentLineRevision.__table__)
FUNCTION = """CREATE OR REPLACE FUNCTION containermgmt.reject_sales_intent_history_change()
RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
RAISE EXCEPTION 'Sales intent history is immutable; append a new revision'; END; $$"""


def trigger(table):
    return f"""CREATE TRIGGER sales_intent_immutable BEFORE UPDATE OR DELETE
    ON containermgmt.{table.name} FOR EACH ROW
    EXECUTE FUNCTION containermgmt.reject_sales_intent_history_change()"""


for table in TABLES:
    event.listen(table, 'after_create', DDL(FUNCTION))
    event.listen(table, 'after_create', DDL(trigger(table)))


PROFILE_FUNCTION = """CREATE OR REPLACE FUNCTION containermgmt.guard_sales_customer_profile()
RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
IF NEW.customer_version > 1 AND NOT EXISTS (
  SELECT 1 FROM containermgmt.customer_profile_revisions WHERE org_id = NEW.org_id
  AND customer_key = NEW.customer_key AND version = NEW.customer_version)
THEN RAISE EXCEPTION 'Referenced customer profile version unavailable'; END IF;
RETURN NEW; END; $$"""
PROFILE_TRIGGER = """CREATE TRIGGER sales_customer_profile_guard BEFORE INSERT
ON containermgmt.sales_intent_revisions FOR EACH ROW
EXECUTE FUNCTION containermgmt.guard_sales_customer_profile()"""
SalesIntentRevision.__table__.add_is_dependent_on(CustomerProfileRevision.__table__)
event.listen(SalesIntentRevision.__table__, 'after_create', DDL(PROFILE_FUNCTION))
event.listen(SalesIntentRevision.__table__, 'after_create', DDL(PROFILE_TRIGGER))
