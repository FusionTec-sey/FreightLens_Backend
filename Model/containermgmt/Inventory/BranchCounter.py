"""Stable branch-owned counter identities and immutable configuration revisions."""
from sqlalchemy import Column, Integer, String, UniqueConstraint, ForeignKeyConstraint, CheckConstraint, DDL, event
from sqlalchemy.dialects.postgresql import JSONB, UUID
from Model.db import Base
from Model.mixins import OrgMixin, AuditMixin


class BranchCounter(OrgMixin, AuditMixin, Base):
    __tablename__ = "inventory_branch_counters"
    __table_args__ = (
        ForeignKeyConstraint(["branch_id", "org_id"], ["containermgmt.inventory_branches.id", "containermgmt.inventory_branches.org_id"], name="fk_counter_branch_scope"),
        UniqueConstraint("org_id", "counter_key", name="uq_counter_org_key"),
        UniqueConstraint("org_id", "branch_id", "code", name="uq_counter_branch_code"),
        UniqueConstraint("id", "org_id", name="uq_counter_id_org"),
        CheckConstraint("code ~ '^[A-Z0-9][A-Z0-9_-]{0,31}$'", name="ck_counter_code"),
        CheckConstraint("created_by IS NOT NULL AND NOT is_deleted AND deleted_at IS NULL", name="ck_counter_audit"),
        {"schema": "containermgmt"},
    )
    id = Column(Integer, primary_key=True)
    branch_id = Column(Integer, nullable=False, index=True)
    counter_key = Column(UUID(as_uuid=True), nullable=False)
    code = Column(String(32), nullable=False)


class CounterSettingsRevision(OrgMixin, AuditMixin, Base):
    __tablename__ = "inventory_counter_settings_revisions"
    __table_args__ = (
        ForeignKeyConstraint(["counter_id", "org_id"], ["containermgmt.inventory_branch_counters.id", "containermgmt.inventory_branch_counters.org_id"], name="fk_counter_revision_scope"),
        UniqueConstraint("org_id", "counter_id", "version", name="uq_counter_revision_version"),
        UniqueConstraint("org_id", "operation_key", name="uq_counter_revision_operation"),
        CheckConstraint("version > 0 AND jsonb_typeof(config) = 'object'", name="ck_counter_revision_config"),
        CheckConstraint("created_by IS NOT NULL AND NOT is_deleted AND deleted_at IS NULL", name="ck_counter_revision_audit"),
        {"schema": "containermgmt"},
    )
    id = Column(Integer, primary_key=True)
    counter_id = Column(Integer, nullable=False, index=True)
    version = Column(Integer, nullable=False)
    operation_key = Column(UUID(as_uuid=True), nullable=False)
    config = Column(JSONB, nullable=False)


FUNCTION = """CREATE OR REPLACE FUNCTION containermgmt.reject_counter_change()
RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
RAISE EXCEPTION 'Counter identities and revisions are immutable'; END; $$"""


def trigger(table):
    return f"""CREATE TRIGGER counter_immutable BEFORE UPDATE OR DELETE ON containermgmt.{table}
    FOR EACH ROW EXECUTE FUNCTION containermgmt.reject_counter_change()"""


for model in (BranchCounter, CounterSettingsRevision):
    event.listen(model.__table__, "after_create", DDL(FUNCTION))
    event.listen(model.__table__, "after_create", DDL(trigger(model.__tablename__)))
