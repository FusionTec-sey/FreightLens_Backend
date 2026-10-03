"""One immutable use of a supplier charge; not an invoice or financial journal."""
from sqlalchemy import Column, Integer, String, Numeric, ForeignKey, ForeignKeyConstraint, UniqueConstraint, CheckConstraint, event, DDL
from sqlalchemy.dialects.postgresql import UUID, JSONB
from Model.db import Base
from Model.mixins import OrgMixin, AuditMixin


class CostChargeUse(OrgMixin, AuditMixin, Base):
    __tablename__ = 'inventory_cost_charge_uses'
    __table_args__ = (
        UniqueConstraint('org_id', 'supplier_id', 'invoice_identity', name='uq_cost_charge_supplier_invoice'),
        UniqueConstraint('org_id', 'proposal_key', name='uq_cost_charge_proposal'),
        UniqueConstraint('org_id', 'document_id', name='uq_cost_charge_document'),
        ForeignKeyConstraint(['org_id', 'operation_key'], ['containermgmt.inventory_posting_operations.org_id',
            'containermgmt.inventory_posting_operations.operation_key'], name='fk_cost_charge_operation', deferrable=True, initially='DEFERRED'),
        CheckConstraint("invoice_identity ~ '^[A-Z0-9]{1,160}$'", name='ck_cost_charge_identity'),
        CheckConstraint("amount_scr > 0 AND jsonb_typeof(evidence) = 'object'", name='ck_cost_charge_evidence'),
        CheckConstraint("evidence ?& ARRAY['supplier_id','invoice_reference','document_id','amount_scr','source_fingerprint'] AND "
            "(evidence->>'supplier_id')::integer = supplier_id AND (evidence->>'document_id')::uuid = document_id AND "
            "(evidence->>'amount_scr')::numeric = amount_scr AND "
            "invoice_identity = regexp_replace(upper(btrim(evidence->>'invoice_reference')), '[ ./_-]', '', 'g')",
            name='ck_cost_charge_snapshot'),
        CheckConstraint("jsonb_typeof(evidence->'supplier_id') = 'number' AND "
            "jsonb_typeof(evidence->'invoice_reference') = 'string' AND "
            "jsonb_typeof(evidence->'document_id') = 'string' AND "
            "jsonb_typeof(evidence->'amount_scr') = 'string' AND "
            "jsonb_typeof(evidence->'source_fingerprint') = 'string' AND "
            "evidence->>'source_fingerprint' ~ '^[a-f0-9]{64}$'", name='ck_cost_charge_required'),
        CheckConstraint('created_by IS NOT NULL AND NOT is_deleted AND deleted_at IS NULL', name='ck_cost_charge_audit'),
        {'schema': 'containermgmt'},
    )
    operation_key = Column(UUID(as_uuid=True), primary_key=True)
    supplier_id = Column(Integer, ForeignKey('containermgmt.supplier.supplier_id'), nullable=False, index=True)
    invoice_identity = Column(String(160), nullable=False)
    document_id = Column(UUID(as_uuid=False), ForeignKey('containermgmt.order_documents.id'), nullable=False, index=True)
    proposal_key = Column(UUID(as_uuid=True), ForeignKey('containermgmt.inventory_cost_allocation_proposals.proposal_key'), nullable=False, index=True)
    amount_scr = Column(Numeric(24, 6), nullable=False)
    evidence = Column(JSONB, nullable=False)


FUNCTION = """CREATE OR REPLACE FUNCTION containermgmt.guard_cost_charge_use()
RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
IF TG_OP <> 'INSERT' THEN RAISE EXCEPTION 'Cost charge uses are immutable'; END IF;
IF NOT EXISTS (SELECT 1 FROM containermgmt.inventory_cost_allocation_proposals p
    WHERE p.proposal_key = NEW.proposal_key AND p.org_id = NEW.org_id AND NOT p.is_deleted
    AND (p.snapshot->>'total_scr')::numeric = NEW.amount_scr)
OR NOT EXISTS (SELECT 1 FROM containermgmt.order_documents d
    WHERE d.id = NEW.document_id AND d.org_id = NEW.org_id AND NOT d.is_deleted)
OR NOT EXISTS (SELECT 1 FROM containermgmt.supplier s WHERE s.supplier_id = NEW.supplier_id
    AND NOT s.is_deleted AND s.is_active AND
    ((NOT s.is_shared AND s.org_id = NEW.org_id) OR (s.is_shared AND s.org_id IS NULL)))
THEN RAISE EXCEPTION 'Cost charge source ownership or amount mismatch'; END IF;
RETURN NEW; END; $$"""
TRIGGER = """CREATE TRIGGER cost_charge_use_guard BEFORE INSERT OR UPDATE OR DELETE
ON containermgmt.inventory_cost_charge_uses FOR EACH ROW
EXECUTE FUNCTION containermgmt.guard_cost_charge_use()"""
event.listen(CostChargeUse.__table__, 'after_create', DDL(FUNCTION))
event.listen(CostChargeUse.__table__, 'after_create', DDL(TRIGGER))
