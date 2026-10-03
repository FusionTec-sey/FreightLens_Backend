"""Stable customer identity and original profile, not freight consignees."""
from sqlalchemy import Column, CheckConstraint, UniqueConstraint, ForeignKeyConstraint, DDL, event
from sqlalchemy.dialects.postgresql import UUID, JSONB
from Model.db import Base
from Model.mixins import OrgMixin, AuditMixin


class RetailCustomer(OrgMixin, AuditMixin, Base):
    __tablename__ = 'retail_customers'
    __table_args__ = (
        UniqueConstraint('customer_key', 'org_id', name='uq_retail_customer_scope'),
        ForeignKeyConstraint(['org_id', 'customer_key'],
            ['containermgmt.inventory_posting_operations.org_id', 'containermgmt.inventory_posting_operations.operation_key'],
            name='fk_customer_creation_receipt', deferrable=True, initially='DEFERRED'),
        CheckConstraint("customer_key <> '00000000-0000-0000-0000-000000000000'::uuid", name='ck_customer_key'),
        CheckConstraint("jsonb_typeof(initial_profile) = 'object'", name='ck_customer_profile'),
        CheckConstraint('created_by IS NOT NULL AND NOT is_deleted AND deleted_at IS NULL', name='ck_customer_audit'),
        {'schema': 'containermgmt'},
    )
    customer_key = Column(UUID(as_uuid=True), primary_key=True)
    initial_profile = Column(JSONB, nullable=False)


FUNCTION = """CREATE OR REPLACE FUNCTION containermgmt.reject_customer_identity_change()
RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
RAISE EXCEPTION 'Customer identity and original profile are immutable; use reviewed revisions';
END; $$"""
TRIGGER = """CREATE TRIGGER customer_identity_immutable BEFORE UPDATE OR DELETE
ON containermgmt.retail_customers FOR EACH ROW
EXECUTE FUNCTION containermgmt.reject_customer_identity_change()"""
event.listen(RetailCustomer.__table__, 'after_create', DDL(FUNCTION))
event.listen(RetailCustomer.__table__, 'after_create', DDL(TRIGGER))
