"""Immutable physical receipt proposals, not source consumption or stock."""
from sqlalchemy import Column, Integer, ForeignKey, ForeignKeyConstraint, CheckConstraint, Index, DDL, event
from sqlalchemy.dialects.postgresql import UUID, JSONB
from Model.db import Base
from Model.mixins import OrgMixin, AuditMixin


class InventoryReceiptManifestRecord(OrgMixin, AuditMixin, Base):
    __tablename__ = 'inventory_receipt_manifests'
    __table_args__ = (
        ForeignKeyConstraint(['org_id', 'manifest_key'],
            ['containermgmt.inventory_posting_operations.org_id', 'containermgmt.inventory_posting_operations.operation_key'],
            name='fk_receipt_manifest_operation', deferrable=True, initially='DEFERRED'),
        CheckConstraint("jsonb_typeof(snapshot) = 'object' AND snapshot ? 'source' AND snapshot ? 'manifest'", name='ck_receipt_manifest_snapshot'),
        CheckConstraint('created_by IS NOT NULL AND NOT is_deleted AND deleted_at IS NULL', name='ck_receipt_manifest_audit'),
        Index('ix_receipt_manifest_source', 'org_id', 'receipt_id', 'receipt_item_id'),
        {'schema': 'containermgmt'},
    )
    manifest_key = Column(UUID(as_uuid=True), primary_key=True)
    receipt_id = Column(Integer, ForeignKey('containermgmt.goods_receipts.id'), nullable=False, index=True)
    receipt_item_id = Column(Integer, ForeignKey('containermgmt.goods_receipt_items.id'), nullable=False, index=True)
    snapshot = Column(JSONB, nullable=False)


IMMUTABLE_FUNCTION = """CREATE OR REPLACE FUNCTION containermgmt.reject_receipt_manifest_change()
RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
RAISE EXCEPTION 'Receipt manifests are immutable'; END; $$"""
IMMUTABLE_TRIGGER = """CREATE TRIGGER receipt_manifest_immutable BEFORE UPDATE OR DELETE
ON containermgmt.inventory_receipt_manifests FOR EACH ROW
EXECUTE FUNCTION containermgmt.reject_receipt_manifest_change()"""
SOURCE_FUNCTION = """CREATE OR REPLACE FUNCTION containermgmt.guard_receipt_manifest_source()
RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
IF NOT EXISTS (SELECT 1 FROM containermgmt.goods_receipts r
 JOIN containermgmt.goods_receipt_items i ON i.receipt_id=r.id
 JOIN containermgmt.purchase_orders p ON p.id=r.po_id AND p.org_id=r.org_id
 JOIN containermgmt.po_items l ON l.id=i.po_item_id AND l.po_id=p.id AND l.org_id=r.org_id
 WHERE r.id=NEW.receipt_id AND i.id=NEW.receipt_item_id AND r.org_id=NEW.org_id
 AND NOT r.is_deleted AND NOT i.is_deleted AND NOT p.is_deleted AND NOT l.is_deleted
 AND (NEW.snapshot->'source'->>'org_id')::integer=NEW.org_id
 AND (NEW.snapshot->'source'->>'receipt_id')::integer=r.id
 AND (NEW.snapshot->'source'->>'receipt_item_id')::integer=i.id
) THEN RAISE EXCEPTION 'Receipt manifest source must belong to its company and parent'; END IF;
RETURN NEW; END; $$"""
SOURCE_TRIGGER = """CREATE TRIGGER receipt_manifest_source BEFORE INSERT
ON containermgmt.inventory_receipt_manifests FOR EACH ROW
EXECUTE FUNCTION containermgmt.guard_receipt_manifest_source()"""
for statement in (IMMUTABLE_FUNCTION, IMMUTABLE_TRIGGER, SOURCE_FUNCTION, SOURCE_TRIGGER):
    event.listen(InventoryReceiptManifestRecord.__table__, 'after_create', DDL(statement))
