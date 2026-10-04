"""Append-only profile/contact history; version one stays on RetailCustomer."""
from sqlalchemy import Column, Integer, String, UniqueConstraint, ForeignKeyConstraint, CheckConstraint, DDL, event
from sqlalchemy.dialects.postgresql import UUID, JSONB
from Model.db import Base
from Model.mixins import OrgMixin, AuditMixin
from Model.containermgmt.MasterData.RetailCustomer import RetailCustomer  # noqa: F401


class CustomerProfileRevision(OrgMixin, AuditMixin, Base):
    __tablename__ = 'customer_profile_revisions'
    __table_args__ = (
        UniqueConstraint('org_id', 'customer_key', 'version', name='uq_customer_profile_version'),
        UniqueConstraint('org_id', 'operation_key', name='uq_customer_profile_operation'),
        ForeignKeyConstraint(['customer_key', 'org_id'], ['containermgmt.retail_customers.customer_key', 'containermgmt.retail_customers.org_id']),
        ForeignKeyConstraint(['org_id', 'operation_key'], ['containermgmt.inventory_posting_operations.org_id', 'containermgmt.inventory_posting_operations.operation_key'], deferrable=True, initially='DEFERRED'),
        CheckConstraint("version >= 2 AND jsonb_typeof(profile) = 'object' AND length(trim(reason)) > 0", name='ck_customer_profile_content'),
        CheckConstraint('created_by IS NOT NULL AND NOT is_deleted AND deleted_at IS NULL', name='ck_customer_profile_audit'),
        {'schema': 'containermgmt'},
    )
    customer_key = Column(UUID(as_uuid=True), primary_key=True)
    version = Column(Integer, primary_key=True)
    operation_key = Column(UUID(as_uuid=True), nullable=False)
    profile = Column(JSONB, nullable=False)
    reason = Column(String(500), nullable=False)


FUNCTION = """CREATE OR REPLACE FUNCTION containermgmt.guard_customer_profile_history()
RETURNS trigger LANGUAGE plpgsql AS $$ DECLARE prior integer; BEGIN
IF TG_OP <> 'INSERT' THEN RAISE EXCEPTION 'Customer profile history is immutable'; END IF;
PERFORM 1 FROM containermgmt.retail_customers WHERE customer_key = NEW.customer_key
AND org_id = NEW.org_id FOR UPDATE;
IF NOT FOUND THEN RAISE EXCEPTION 'Customer profile scope unavailable'; END IF;
SELECT COALESCE(MAX(version), 1) INTO prior FROM containermgmt.customer_profile_revisions
WHERE org_id = NEW.org_id AND customer_key = NEW.customer_key;
IF NEW.version <> prior + 1 THEN RAISE EXCEPTION 'Customer profile version must be consecutive'; END IF;
RETURN NEW; END; $$"""
TRIGGER = """CREATE TRIGGER customer_profile_history_guard BEFORE INSERT OR UPDATE OR DELETE
ON containermgmt.customer_profile_revisions FOR EACH ROW
EXECUTE FUNCTION containermgmt.guard_customer_profile_history()"""
event.listen(CustomerProfileRevision.__table__, 'after_create', DDL(FUNCTION))
event.listen(CustomerProfileRevision.__table__, 'after_create', DDL(TRIGGER))
