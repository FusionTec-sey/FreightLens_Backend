"""Durable receipt of an internal posting and its transactional outbox envelope."""
from sqlalchemy import Column, Integer, String, UniqueConstraint, CheckConstraint, Index, DDL, event
from sqlalchemy.dialects.postgresql import UUID, JSONB
from Model.db import Base
from Model.mixins import OrgMixin, AuditMixin


class PostingOperation(OrgMixin, AuditMixin, Base):
    __tablename__ = "inventory_posting_operations"
    __table_args__ = (
        UniqueConstraint("org_id", "operation_key", name="uq_inventory_posting_operation_key"),
        CheckConstraint("kind ~ '^[a-z][a-z0-9_.-]{0,63}$'", name="ck_inventory_posting_kind"),
        CheckConstraint("request_digest ~ '^[0-9a-f]{64}$'", name="ck_inventory_posting_digest"),
        CheckConstraint("jsonb_typeof(result) = 'object' AND jsonb_typeof(event_payload) = 'object'",
                        name="ck_inventory_posting_objects"),
        CheckConstraint("created_by IS NOT NULL AND NOT is_deleted AND deleted_at IS NULL",
                        name="ck_inventory_posting_audit"),
        Index("ix_inventory_posting_org_id_order", "org_id", "id"),
        {"schema": "containermgmt"},
    )
    id = Column(Integer, primary_key=True)
    operation_key = Column(UUID(as_uuid=True), nullable=False)
    kind = Column(String(64), nullable=False)
    request_digest = Column(String(64), nullable=False)
    result = Column(JSONB, nullable=False)
    event_payload = Column(JSONB, nullable=False)


# A posting receipt must not be edited, soft-deleted or recycled on retry.
# Delivery acknowledgements will be separate records, never edits to this outbox.
IMMUTABLE_FUNCTION = """
CREATE OR REPLACE FUNCTION containermgmt.reject_inventory_posting_change()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Committed inventory posting receipts are immutable';
END;
$$
"""
IMMUTABLE_TRIGGER = """
CREATE TRIGGER inventory_posting_immutable
BEFORE UPDATE OR DELETE ON containermgmt.inventory_posting_operations
FOR EACH ROW EXECUTE FUNCTION containermgmt.reject_inventory_posting_change()
"""
event.listen(PostingOperation.__table__, "after_create", DDL(IMMUTABLE_FUNCTION))
event.listen(PostingOperation.__table__, "after_create", DDL(IMMUTABLE_TRIGGER))
