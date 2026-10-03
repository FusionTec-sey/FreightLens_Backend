"""Immutable reviewed policy activation; existing stock is never reinterpreted."""
from sqlalchemy import Column, Integer, UniqueConstraint, ForeignKeyConstraint, CheckConstraint, DDL, event
from sqlalchemy.dialects.postgresql import UUID, JSONB
from Model.db import Base
from Model.mixins import OrgMixin, AuditMixin


class ProductPolicyActivation(OrgMixin, AuditMixin, Base):
    __tablename__ = "inventory_product_policy_activations"
    __table_args__ = (
        ForeignKeyConstraint(["org_id", "product_id", "draft_version"],
            ["containermgmt.inventory_product_policy_drafts.org_id", "containermgmt.inventory_product_policy_drafts.product_id",
             "containermgmt.inventory_product_policy_drafts.version"], name="fk_policy_activation_draft"),
        ForeignKeyConstraint(["org_id", "case_key"],
            ["containermgmt.manager_cases.org_id", "containermgmt.manager_cases.case_key"], name="fk_policy_activation_case"),
        ForeignKeyConstraint(["org_id", "operation_key"],
            ["containermgmt.inventory_posting_operations.org_id", "containermgmt.inventory_posting_operations.operation_key"],
            name="fk_policy_activation_posting", deferrable=True, initially="DEFERRED"),
        UniqueConstraint("org_id", "product_id", "version", name="uq_policy_activation_version"),
        UniqueConstraint("org_id", "case_key", name="uq_policy_activation_case"),
        UniqueConstraint("org_id", "operation_key", name="uq_policy_activation_operation"),
        CheckConstraint("version > 0 AND draft_version > 0 AND jsonb_typeof(config) = 'object'", name="ck_policy_activation_config"),
        CheckConstraint("created_by IS NOT NULL AND NOT is_deleted AND deleted_at IS NULL", name="ck_policy_activation_audit"),
        {"schema": "containermgmt"},
    )
    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, nullable=False, index=True)
    version = Column(Integer, nullable=False)
    draft_version = Column(Integer, nullable=False)
    case_key = Column(UUID(as_uuid=True), nullable=False)
    operation_key = Column(UUID(as_uuid=True), nullable=False)
    config = Column(JSONB, nullable=False)


FUNCTION = """CREATE OR REPLACE FUNCTION containermgmt.reject_policy_activation_change()
RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
RAISE EXCEPTION 'Activated policy history is immutable'; END; $$"""
TRIGGER = """CREATE TRIGGER policy_activation_immutable BEFORE UPDATE OR DELETE
ON containermgmt.inventory_product_policy_activations FOR EACH ROW
EXECUTE FUNCTION containermgmt.reject_policy_activation_change()"""
event.listen(ProductPolicyActivation.__table__, "after_create", DDL(FUNCTION))
event.listen(ProductPolicyActivation.__table__, "after_create", DDL(TRIGGER))

# Legacy catalogue writers must not bypass activation by editing stock totals or
# the policy's unit/scope. Their full Inventory routing remains the T08 task.
PRODUCT_GUARD = """CREATE OR REPLACE FUNCTION containermgmt.guard_activated_product()
RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
IF (NEW.unit IS DISTINCT FROM OLD.unit OR NEW.current_stock IS DISTINCT FROM OLD.current_stock
    OR NEW.is_shared IS DISTINCT FROM OLD.is_shared OR NEW.org_id IS DISTINCT FROM OLD.org_id)
AND EXISTS (SELECT 1 FROM containermgmt.inventory_product_policy_activations
    WHERE product_id=OLD.id AND org_id=OLD.org_id) THEN
RAISE EXCEPTION 'Activated inventory requires reviewed transitions and Inventory stock posting';
END IF; RETURN NEW; END; $$"""
PRODUCT_TRIGGER = """CREATE TRIGGER activated_product_guard BEFORE UPDATE ON containermgmt.products
FOR EACH ROW EXECUTE FUNCTION containermgmt.guard_activated_product()"""
event.listen(ProductPolicyActivation.__table__, "after_create", DDL(PRODUCT_GUARD))
event.listen(ProductPolicyActivation.__table__, "after_create", DDL(PRODUCT_TRIGGER))
