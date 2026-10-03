"""Immutable proposals; saving is not approval or physical stock posting."""
from sqlalchemy import Column, Integer, CheckConstraint, ForeignKeyConstraint, Index, DDL, event
from sqlalchemy.dialects.postgresql import UUID, JSONB
from Model.db import Base
from Model.mixins import OrgMixin, AuditMixin


class StockReclassificationProposal(OrgMixin, AuditMixin, Base):
    __tablename__ = "inventory_stock_reclassification_proposals"
    __table_args__ = (
        ForeignKeyConstraint(["balance_id", "org_id"],
            ["containermgmt.inventory_stock_balances.id", "containermgmt.inventory_stock_balances.org_id"],
            name="fk_reclass_proposal_balance"),
        ForeignKeyConstraint(["org_id", "proposal_key"],
            ["containermgmt.inventory_posting_operations.org_id", "containermgmt.inventory_posting_operations.operation_key"],
            name="fk_reclass_proposal_operation", deferrable=True, initially="DEFERRED"),
        CheckConstraint("jsonb_typeof(snapshot) = 'object' AND jsonb_typeof(manifest) = 'object'",
            name="ck_reclass_proposal_json"),
        CheckConstraint("created_by IS NOT NULL AND NOT is_deleted AND deleted_at IS NULL",
            name="ck_reclass_proposal_audit"),
        Index("ix_reclass_proposal_balance", "org_id", "balance_id"),
        {"schema": "containermgmt"},
    )
    proposal_key = Column(UUID(as_uuid=True), primary_key=True)
    balance_id = Column(Integer, nullable=False)
    snapshot = Column(JSONB, nullable=False)
    manifest = Column(JSONB, nullable=False)


FUNCTION = """CREATE OR REPLACE FUNCTION containermgmt.reject_reclassification_proposal_change()
RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
RAISE EXCEPTION 'Stock reclassification proposals are immutable'; END; $$"""
TRIGGER = """CREATE TRIGGER reclassification_proposal_immutable BEFORE UPDATE OR DELETE
ON containermgmt.inventory_stock_reclassification_proposals FOR EACH ROW
EXECUTE FUNCTION containermgmt.reject_reclassification_proposal_change()"""
event.listen(StockReclassificationProposal.__table__, "after_create", DDL(FUNCTION))
event.listen(StockReclassificationProposal.__table__, "after_create", DDL(TRIGGER))
