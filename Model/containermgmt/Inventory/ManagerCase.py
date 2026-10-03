"""One reusable immutable request/decision/use history for manager cases."""
from sqlalchemy import Column, Integer, String, UniqueConstraint, ForeignKeyConstraint, CheckConstraint, DDL, event
from sqlalchemy.dialects.postgresql import UUID, JSONB
from Model.db import Base
from Model.mixins import OrgMixin, AuditMixin


class ManagerCase(OrgMixin, AuditMixin, Base):
    __tablename__ = "manager_cases"
    __table_args__ = (
        UniqueConstraint("org_id", "case_key", name="uq_manager_case_key"),
        UniqueConstraint("id", "org_id", name="uq_manager_case_id_org"),
        CheckConstraint("source_version > 0 AND jsonb_typeof(binding) = 'object'", name="ck_manager_case_binding"),
        CheckConstraint("created_by IS NOT NULL AND NOT is_deleted AND deleted_at IS NULL", name="ck_manager_case_audit"),
        {"schema": "containermgmt"},
    )
    id = Column(Integer, primary_key=True)
    case_key = Column(UUID(as_uuid=True), nullable=False)
    action = Column(String(64), nullable=False)
    source_type = Column(String(64), nullable=False)
    source_key = Column(String(100), nullable=False)
    source_version = Column(Integer, nullable=False)
    binding = Column(JSONB, nullable=False)
    reason = Column(String(1000), nullable=False)


class ManagerCaseDecision(OrgMixin, AuditMixin, Base):
    __tablename__ = "manager_case_decisions"
    __table_args__ = (
        ForeignKeyConstraint(["case_id", "org_id"], ["containermgmt.manager_cases.id", "containermgmt.manager_cases.org_id"], name="fk_case_decision_scope"),
        UniqueConstraint("org_id", "case_id", name="uq_case_decision"),
        CheckConstraint("outcome IN ('APPROVED', 'REJECTED')", name="ck_case_decision_outcome"),
        CheckConstraint("created_by IS NOT NULL AND NOT is_deleted AND deleted_at IS NULL", name="ck_case_decision_audit"),
        {"schema": "containermgmt"},
    )
    id = Column(Integer, primary_key=True)
    case_id = Column(Integer, nullable=False, index=True)
    outcome = Column(String(16), nullable=False)
    reason = Column(String(1000), nullable=False)


class ManagerCaseUse(OrgMixin, AuditMixin, Base):
    __tablename__ = "manager_case_uses"
    __table_args__ = (
        ForeignKeyConstraint(["case_id", "org_id"], ["containermgmt.manager_cases.id", "containermgmt.manager_cases.org_id"], name="fk_case_use_scope"),
        ForeignKeyConstraint(["org_id", "operation_key"], ["containermgmt.inventory_posting_operations.org_id", "containermgmt.inventory_posting_operations.operation_key"],
            name="fk_case_use_posting", deferrable=True, initially="DEFERRED"),
        UniqueConstraint("org_id", "case_id", name="uq_case_single_use"),
        CheckConstraint("created_by IS NOT NULL AND NOT is_deleted AND deleted_at IS NULL", name="ck_case_use_audit"),
        {"schema": "containermgmt"},
    )
    id = Column(Integer, primary_key=True)
    case_id = Column(Integer, nullable=False, index=True)
    operation_key = Column(UUID(as_uuid=True), nullable=False, index=True)


IMMUTABLE = """CREATE OR REPLACE FUNCTION containermgmt.reject_manager_case_change()
RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
RAISE EXCEPTION 'Manager case history is immutable'; END; $$"""
REVIEW_CHECK = """CREATE OR REPLACE FUNCTION containermgmt.check_manager_case_review()
RETURNS trigger LANGUAGE plpgsql AS $$ DECLARE requestor integer; BEGIN
SELECT created_by INTO requestor FROM containermgmt.manager_cases
WHERE id=NEW.case_id AND org_id=NEW.org_id FOR UPDATE;
IF requestor IS NULL OR requestor=NEW.created_by THEN
RAISE EXCEPTION 'Manager cases require a different reviewer in the same organisation'; END IF;
RETURN NEW; END; $$"""
REVIEW_TRIGGER = """CREATE TRIGGER manager_case_review_guard BEFORE INSERT ON containermgmt.manager_case_decisions
FOR EACH ROW EXECUTE FUNCTION containermgmt.check_manager_case_review()"""
USE_CHECK = """CREATE OR REPLACE FUNCTION containermgmt.check_manager_case_use()
RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
PERFORM 1 FROM containermgmt.manager_cases WHERE id=NEW.case_id AND org_id=NEW.org_id FOR UPDATE;
IF NOT FOUND OR NOT EXISTS (SELECT 1 FROM containermgmt.manager_case_decisions
WHERE case_id=NEW.case_id AND org_id=NEW.org_id AND outcome='APPROVED') THEN
RAISE EXCEPTION 'Only an approved manager case can be consumed'; END IF;
RETURN NEW; END; $$"""
USE_TRIGGER = """CREATE TRIGGER manager_case_use_guard BEFORE INSERT ON containermgmt.manager_case_uses
FOR EACH ROW EXECUTE FUNCTION containermgmt.check_manager_case_use()"""


def immutable_trigger(table):
    return f"""CREATE TRIGGER manager_case_immutable BEFORE UPDATE OR DELETE ON containermgmt.{table}
    FOR EACH ROW EXECUTE FUNCTION containermgmt.reject_manager_case_change()"""


for model in (ManagerCase, ManagerCaseDecision, ManagerCaseUse):
    event.listen(model.__table__, "after_create", DDL(IMMUTABLE))
    event.listen(model.__table__, "after_create", DDL(immutable_trigger(model.__tablename__)))
event.listen(ManagerCaseDecision.__table__, "after_create", DDL(REVIEW_CHECK))
event.listen(ManagerCaseDecision.__table__, "after_create", DDL(REVIEW_TRIGGER))
event.listen(ManagerCaseUse.__table__, "after_create", DDL(USE_CHECK))
event.listen(ManagerCaseUse.__table__, "after_create", DDL(USE_TRIGGER))
