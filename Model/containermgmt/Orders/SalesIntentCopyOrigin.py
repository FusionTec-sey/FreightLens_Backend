"""Immutable provenance for a draft created from one exact sales draft revision."""
from sqlalchemy import (
    CheckConstraint,
    Column,
    DDL,
    ForeignKeyConstraint,
    Integer,
    UniqueConstraint,
    event,
)
from sqlalchemy.dialects.postgresql import UUID

from Model.db import Base
from Model.mixins import AuditMixin, OrgMixin
from Model.containermgmt.Inventory.PostingOperation import PostingOperation  # noqa: F401
from Model.containermgmt.Orders.SalesIntent import (  # noqa: F401
    SalesIntent,
    SalesIntentRevision,
)


class SalesIntentCopyOrigin(OrgMixin, AuditMixin, Base):
    """One immutable source reference for the destination draft's first save."""

    __tablename__ = "sales_intent_copy_origins"
    __table_args__ = (
        UniqueConstraint(
            "org_id", "destination_document_key",
            name="uq_sales_intent_copy_destination",
        ),
        UniqueConstraint(
            "org_id", "operation_key",
            name="uq_sales_intent_copy_operation",
        ),
        ForeignKeyConstraint(
            ["org_id", "destination_document_key"],
            ["containermgmt.sales_intents.org_id",
             "containermgmt.sales_intents.document_key"],
            name="fk_sales_intent_copy_destination",
        ),
        ForeignKeyConstraint(
            ["org_id", "source_document_key", "source_version"],
            ["containermgmt.sales_intent_revisions.org_id",
             "containermgmt.sales_intent_revisions.document_key",
             "containermgmt.sales_intent_revisions.version"],
            name="fk_sales_intent_copy_source",
        ),
        ForeignKeyConstraint(
            ["org_id", "operation_key"],
            ["containermgmt.inventory_posting_operations.org_id",
             "containermgmt.inventory_posting_operations.operation_key"],
            name="fk_sales_intent_copy_operation",
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint(
            "destination_document_key <> source_document_key "
            "AND destination_document_key <> "
            "'00000000-0000-0000-0000-000000000000'::uuid "
            "AND source_document_key <> "
            "'00000000-0000-0000-0000-000000000000'::uuid "
            "AND operation_key <> "
            "'00000000-0000-0000-0000-000000000000'::uuid "
            "AND source_version > 0",
            name="ck_sales_intent_copy_identity",
        ),
        CheckConstraint(
            "created_by IS NOT NULL AND NOT is_deleted AND deleted_at IS NULL",
            name="ck_sales_intent_copy_audit",
        ),
        {"schema": "containermgmt"},
    )

    destination_document_key = Column(UUID(as_uuid=True), primary_key=True)
    source_document_key = Column(UUID(as_uuid=True), nullable=False)
    source_version = Column(Integer, nullable=False)
    operation_key = Column(UUID(as_uuid=True), nullable=False)


IMMUTABLE_FUNCTION = """CREATE OR REPLACE FUNCTION containermgmt.reject_sales_intent_copy_change()
RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
RAISE EXCEPTION 'Sales draft copy provenance is immutable'; END; $$"""

IMMUTABLE_TRIGGER = """CREATE TRIGGER sales_intent_copy_immutable
BEFORE UPDATE OR DELETE ON containermgmt.sales_intent_copy_origins
FOR EACH ROW EXECUTE FUNCTION containermgmt.reject_sales_intent_copy_change()"""

GUARD_FUNCTION = """CREATE OR REPLACE FUNCTION containermgmt.check_sales_intent_copy_origin()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE first_revision record; operation record; reused integer; BEGIN
SELECT operation_key, created_by INTO first_revision
FROM containermgmt.sales_intent_revisions
WHERE org_id=NEW.org_id AND document_key=NEW.destination_document_key AND version=1;
SELECT kind, created_by INTO operation
FROM containermgmt.inventory_posting_operations
WHERE org_id=NEW.org_id AND operation_key=NEW.operation_key;
SELECT COUNT(*) INTO reused
FROM containermgmt.sales_intent_line_revisions destination
JOIN containermgmt.sales_intent_line_revisions source
  ON source.org_id=destination.org_id AND source.line_key=destination.line_key
WHERE destination.org_id=NEW.org_id
  AND destination.document_key=NEW.destination_document_key
  AND destination.version=1
  AND source.document_key=NEW.source_document_key
  AND source.version=NEW.source_version;
IF first_revision IS NULL OR first_revision.operation_key<>NEW.operation_key
 OR first_revision.created_by<>NEW.created_by
 OR operation IS NULL OR operation.kind<>'sales.intent.save.v1'
 OR operation.created_by<>NEW.created_by THEN
 RAISE EXCEPTION 'Copy provenance requires the destination first-save operation'; END IF;
IF reused<>0 THEN
 RAISE EXCEPTION 'Copied draft lines require new identities'; END IF;
RETURN NULL; END; $$"""

GUARD_TRIGGER = """CREATE CONSTRAINT TRIGGER sales_intent_copy_origin_guard
AFTER INSERT ON containermgmt.sales_intent_copy_origins
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
EXECUTE FUNCTION containermgmt.check_sales_intent_copy_origin()"""


event.listen(SalesIntentCopyOrigin.__table__, "after_create", DDL(IMMUTABLE_FUNCTION))
event.listen(SalesIntentCopyOrigin.__table__, "after_create", DDL(IMMUTABLE_TRIGGER))
event.listen(SalesIntentCopyOrigin.__table__, "after_create", DDL(GUARD_FUNCTION))
event.listen(SalesIntentCopyOrigin.__table__, "after_create", DDL(GUARD_TRIGGER))
