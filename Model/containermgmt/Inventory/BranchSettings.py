"""Immutable branch configuration revisions; no real operational defaults."""
from sqlalchemy import Column, Integer, UniqueConstraint, ForeignKeyConstraint, CheckConstraint, DDL, event
from sqlalchemy.dialects.postgresql import JSONB, UUID
from Model.db import Base
from Model.mixins import OrgMixin, AuditMixin


class BranchSettingsRevision(OrgMixin, AuditMixin, Base):
    __tablename__ = "inventory_branch_settings_revisions"
    __table_args__ = (
        ForeignKeyConstraint(["branch_id", "org_id"],
            ["containermgmt.inventory_branches.id", "containermgmt.inventory_branches.org_id"],
            name="fk_branch_settings_scope"),
        UniqueConstraint("org_id", "branch_id", "version", name="uq_branch_settings_version"),
        UniqueConstraint("org_id", "operation_key", name="uq_branch_settings_operation"),
        CheckConstraint("version > 0 AND jsonb_typeof(config) = 'object'", name="ck_branch_settings_config"),
        CheckConstraint("created_by IS NOT NULL AND NOT is_deleted AND deleted_at IS NULL", name="ck_branch_settings_audit"),
        {"schema": "containermgmt"},
    )
    id = Column(Integer, primary_key=True)
    branch_id = Column(Integer, nullable=False, index=True)
    version = Column(Integer, nullable=False)
    operation_key = Column(UUID(as_uuid=True), nullable=False)
    config = Column(JSONB, nullable=False)


FUNCTION = """CREATE OR REPLACE FUNCTION containermgmt.reject_branch_settings_change()
RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
RAISE EXCEPTION 'Branch settings revisions are immutable'; END; $$"""
TRIGGER = """CREATE TRIGGER branch_settings_immutable BEFORE UPDATE OR DELETE
ON containermgmt.inventory_branch_settings_revisions FOR EACH ROW
EXECUTE FUNCTION containermgmt.reject_branch_settings_change()"""
event.listen(BranchSettingsRevision.__table__, "after_create", DDL(FUNCTION))
event.listen(BranchSettingsRevision.__table__, "after_create", DDL(TRIGGER))
