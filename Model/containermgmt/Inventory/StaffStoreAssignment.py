"""Append-only working-store assignment; a counter is an optional workstation."""
from sqlalchemy import Column, Integer, Boolean, ForeignKey, ForeignKeyConstraint, UniqueConstraint, CheckConstraint, DDL, event
from sqlalchemy.dialects.postgresql import UUID
from Model.db import Base
from Model.mixins import OrgMixin, AuditMixin


class StaffStoreAssignment(OrgMixin, AuditMixin, Base):
    __tablename__ = 'inventory_staff_store_assignments'
    __table_args__ = (
        UniqueConstraint('org_id', 'user_id', 'version', name='uq_staff_store_version'),
        UniqueConstraint('org_id', 'operation_key', name='uq_staff_store_operation'),
        ForeignKeyConstraint(['branch_id', 'org_id'], ['containermgmt.inventory_branches.id', 'containermgmt.inventory_branches.org_id'], name='fk_staff_store_branch'),
        ForeignKeyConstraint(['counter_id', 'org_id'], ['containermgmt.inventory_branch_counters.id', 'containermgmt.inventory_branch_counters.org_id'], name='fk_staff_store_counter'),
        ForeignKeyConstraint(['org_id', 'operation_key'], ['containermgmt.inventory_posting_operations.org_id', 'containermgmt.inventory_posting_operations.operation_key'], name='fk_staff_store_receipt', deferrable=True, initially='DEFERRED'),
        CheckConstraint('version > 0 AND created_by IS NOT NULL AND NOT is_deleted AND deleted_at IS NULL', name='ck_staff_store_history'),
        {'schema': 'containermgmt'},
    )
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('usercredentials.users.id'), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    operation_key = Column(UUID(as_uuid=True), nullable=False)
    branch_id = Column(Integer, nullable=False, index=True)
    counter_id = Column(Integer, index=True)
    is_enabled = Column(Boolean, nullable=False)


FUNCTION = """CREATE OR REPLACE FUNCTION containermgmt.guard_staff_store_assignment()
RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
IF TG_OP <> 'INSERT' THEN RAISE EXCEPTION 'Staff store assignment history is immutable'; END IF;
IF NEW.counter_id IS NOT NULL AND NOT EXISTS (
 SELECT 1 FROM containermgmt.inventory_branch_counters c
 WHERE c.id=NEW.counter_id AND c.org_id=NEW.org_id AND c.branch_id=NEW.branch_id
) THEN RAISE EXCEPTION 'Usual counter must belong to the assigned store'; END IF;
RETURN NEW; END; $$"""
TRIGGER = """CREATE TRIGGER staff_store_assignment_guard
BEFORE INSERT OR UPDATE OR DELETE ON containermgmt.inventory_staff_store_assignments
FOR EACH ROW EXECUTE FUNCTION containermgmt.guard_staff_store_assignment()"""
for statement in (FUNCTION, TRIGGER):
    event.listen(StaffStoreAssignment.__table__, 'after_create', DDL(statement))
