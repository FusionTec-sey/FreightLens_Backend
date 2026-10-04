"""Immutable receipt-line capacity claims made only inside physical posting."""
from sqlalchemy import (Column, Integer, String, Numeric, ForeignKey, ForeignKeyConstraint,
                        UniqueConstraint, CheckConstraint, Index, event, DDL)
from sqlalchemy.dialects.postgresql import UUID
from Model.db import Base
from Model.mixins import OrgMixin, AuditMixin


class InventoryReceiptSourceUse(OrgMixin, AuditMixin, Base):
    __tablename__ = 'inventory_receipt_source_uses'
    __table_args__ = (
        ForeignKeyConstraint(['org_id', 'operation_key'],
            ['containermgmt.inventory_posting_operations.org_id', 'containermgmt.inventory_posting_operations.operation_key'],
            name='fk_receipt_source_use_operation', deferrable=True, initially='DEFERRED'),
        UniqueConstraint('org_id', 'manifest_key', name='uq_receipt_source_manifest_use'),
        CheckConstraint('quantity > 0', name='ck_receipt_source_use_quantity'),
        CheckConstraint('created_by IS NOT NULL AND NOT is_deleted AND deleted_at IS NULL', name='ck_receipt_source_use_audit'),
        Index('ix_receipt_source_capacity', 'org_id', 'receipt_id', 'receipt_item_id'),
        {'schema': 'containermgmt'},
    )
    id = Column(Integer, primary_key=True)
    operation_key = Column(UUID(as_uuid=True), nullable=False, index=True)
    manifest_key = Column(UUID(as_uuid=True), ForeignKey('containermgmt.inventory_receipt_manifests.manifest_key'), nullable=False, index=True)
    receipt_id = Column(Integer, ForeignKey('containermgmt.goods_receipts.id'), nullable=False)
    receipt_item_id = Column(Integer, ForeignKey('containermgmt.goods_receipt_items.id'), nullable=False)
    quantity = Column(Numeric(24, 6), nullable=False)
    base_unit = Column(String(50), nullable=False)


FUNCTION = """CREATE OR REPLACE FUNCTION containermgmt.guard_receipt_source_use()
RETURNS trigger LANGUAGE plpgsql AS $$ DECLARE expected numeric; consumed numeric; unit_name text; BEGIN
IF TG_OP <> 'INSERT' THEN RAISE EXCEPTION 'Receipt source uses are immutable'; END IF;
PERFORM 1 FROM containermgmt.goods_receipt_items
 WHERE id=NEW.receipt_item_id AND receipt_id=NEW.receipt_id AND NOT is_deleted FOR UPDATE;
IF NOT FOUND THEN RAISE EXCEPTION 'Receipt source line missing'; END IF;
SELECT (m.snapshot->'source'->'base_quantities'->>'received_quantity')::numeric,
       m.snapshot->'source'->>'base_unit'
 INTO expected, unit_name FROM containermgmt.inventory_receipt_manifests m
 WHERE m.manifest_key=NEW.manifest_key AND m.org_id=NEW.org_id
 AND m.receipt_id=NEW.receipt_id AND m.receipt_item_id=NEW.receipt_item_id AND NOT m.is_deleted;
IF expected IS NULL OR unit_name IS NULL OR NEW.quantity <> expected OR NEW.base_unit <> unit_name THEN
 RAISE EXCEPTION 'Receipt source use must match the immutable manifest'; END IF;
IF NOT EXISTS (SELECT 1 FROM containermgmt.manager_cases c
 JOIN containermgmt.manager_case_uses u ON u.case_id=c.id AND u.org_id=c.org_id
 WHERE c.org_id=NEW.org_id AND c.action='inventory.receipt.classify'
 AND c.source_type='inventory.receipt.manifest' AND c.source_key=NEW.manifest_key::text
 AND u.operation_key=NEW.operation_key) THEN
 RAISE EXCEPTION 'Receipt source use requires the matching consumed approval'; END IF;
SELECT COALESCE(sum(quantity),0) INTO consumed FROM containermgmt.inventory_receipt_source_uses
 WHERE org_id=NEW.org_id AND receipt_id=NEW.receipt_id AND receipt_item_id=NEW.receipt_item_id;
IF consumed + NEW.quantity > expected THEN RAISE EXCEPTION 'Receipt source quantity already consumed'; END IF;
RETURN NEW; END; $$"""
TRIGGER = """CREATE TRIGGER receipt_source_use_guard BEFORE INSERT OR UPDATE OR DELETE
ON containermgmt.inventory_receipt_source_uses FOR EACH ROW
EXECUTE FUNCTION containermgmt.guard_receipt_source_use()"""
event.listen(InventoryReceiptSourceUse.__table__, 'after_create', DDL(FUNCTION))
event.listen(InventoryReceiptSourceUse.__table__, 'after_create', DDL(TRIGGER))
