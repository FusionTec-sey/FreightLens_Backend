"""Append-only preparation revisions; not an active product or stock policy."""
from sqlalchemy import Column, Integer, UniqueConstraint, ForeignKeyConstraint, CheckConstraint, Index, DDL, event
from sqlalchemy.dialects.postgresql import JSONB
from Model.db import Base
from Model.mixins import OrgMixin, AuditMixin


class ProductPolicyDraft(OrgMixin, AuditMixin, Base):
    __tablename__ = "inventory_product_policy_drafts"
    __table_args__ = (
        ForeignKeyConstraint(["product_id", "org_id"], ["containermgmt.products.id", "containermgmt.products.org_id"], name="fk_policy_draft_product_scope"),
        UniqueConstraint("org_id", "product_id", "version", name="uq_policy_draft_version"),
        CheckConstraint("version > 0 AND jsonb_typeof(config) = 'object'", name="ck_policy_draft_config"),
        CheckConstraint("created_by IS NOT NULL AND NOT is_deleted AND deleted_at IS NULL", name="ck_policy_draft_audit"),
        Index("ix_policy_draft_product_scope", "product_id", "org_id"),
        {"schema": "containermgmt"},
    )
    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, nullable=False)
    version = Column(Integer, nullable=False)
    config = Column(JSONB, nullable=False)


FUNCTION = """CREATE OR REPLACE FUNCTION containermgmt.reject_policy_draft_change()
RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
RAISE EXCEPTION 'Inventory policy revisions are immutable'; END; $$"""
TRIGGER = """CREATE TRIGGER policy_draft_immutable BEFORE UPDATE OR DELETE
ON containermgmt.inventory_product_policy_drafts FOR EACH ROW
EXECUTE FUNCTION containermgmt.reject_policy_draft_change()"""
event.listen(ProductPolicyDraft.__table__, "after_create", DDL(FUNCTION))
event.listen(ProductPolicyDraft.__table__, "after_create", DDL(TRIGGER))
