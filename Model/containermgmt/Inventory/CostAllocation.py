"""Immutable cost allocation proposals, never a capitalised charge."""
from sqlalchemy import Column, Integer, ForeignKeyConstraint, CheckConstraint, Index, event, DDL
from sqlalchemy.dialects.postgresql import UUID, JSONB
from Model.db import Base
from Model.mixins import OrgMixin, AuditMixin


class CostAllocationProposal(OrgMixin, AuditMixin, Base):
    __tablename__ = 'inventory_cost_allocation_proposals'
    __table_args__ = (
        ForeignKeyConstraint(['cost_pool_id', 'org_id'], ['containermgmt.inventory_cost_pools.id', 'containermgmt.inventory_cost_pools.org_id'], name='fk_cost_proposal_pool'),
        ForeignKeyConstraint(['org_id', 'proposal_key'], ['containermgmt.inventory_posting_operations.org_id', 'containermgmt.inventory_posting_operations.operation_key'], name='fk_cost_proposal_operation', deferrable=True, initially='DEFERRED'),
        CheckConstraint("jsonb_typeof(manifest) = 'object' AND jsonb_typeof(snapshot) = 'object'", name='ck_cost_proposal_json'),
        CheckConstraint('created_by IS NOT NULL AND NOT is_deleted AND deleted_at IS NULL', name='ck_cost_proposal_audit'),
        Index('ix_cost_proposal_pool', 'org_id', 'cost_pool_id', 'created_at'),
        {'schema': 'containermgmt'},
    )
    proposal_key = Column(UUID(as_uuid=True), primary_key=True)
    cost_pool_id = Column(Integer, nullable=False)
    manifest = Column(JSONB, nullable=False)
    snapshot = Column(JSONB, nullable=False)


FUNCTION = """CREATE OR REPLACE FUNCTION containermgmt.reject_cost_proposal_change()
RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
RAISE EXCEPTION 'Cost allocation proposals are immutable'; END; $$"""
TRIGGER = """CREATE TRIGGER cost_proposal_immutable BEFORE UPDATE OR DELETE
ON containermgmt.inventory_cost_allocation_proposals FOR EACH ROW
EXECUTE FUNCTION containermgmt.reject_cost_proposal_change()"""
event.listen(CostAllocationProposal.__table__, 'after_create', DDL(FUNCTION))
event.listen(CostAllocationProposal.__table__, 'after_create', DDL(TRIGGER))
