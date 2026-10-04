"""Immutable reviewed inventory-cost reconciliation checkpoints."""
from sqlalchemy import (Column, Integer, String, Numeric, ForeignKeyConstraint,
                        UniqueConstraint, CheckConstraint, Index, DDL, event, text)
from sqlalchemy.dialects.postgresql import UUID, JSONB

from Model.db import Base
from Model.mixins import OrgMixin, AuditMixin


class InventoryCostReconciliation(OrgMixin, AuditMixin, Base):
    __tablename__ = "inventory_cost_reconciliations"
    __table_args__ = (
        UniqueConstraint("org_id", "checkpoint_key", name="uq_cost_reconciliation_key"),
        UniqueConstraint("org_id", "cost_pool_id", "product_id", "source_digest",
                         name="uq_cost_reconciliation_source"),
        ForeignKeyConstraint(["cost_pool_id", "org_id"],
            ["containermgmt.inventory_cost_pools.id", "containermgmt.inventory_cost_pools.org_id"],
            name="fk_cost_reconciliation_pool"),
        ForeignKeyConstraint(["product_id", "org_id"],
            ["containermgmt.products.id", "containermgmt.products.org_id"],
            name="fk_cost_reconciliation_product"),
        ForeignKeyConstraint(["valuation_id", "org_id"],
            ["containermgmt.inventory_valuations.id", "containermgmt.inventory_valuations.org_id"],
            name="fk_cost_reconciliation_valuation"),
        ForeignKeyConstraint(["org_id", "checkpoint_key"],
            ["containermgmt.inventory_posting_operations.org_id", "containermgmt.inventory_posting_operations.operation_key"],
            name="fk_cost_reconciliation_operation", deferrable=True, initially="DEFERRED"),
        CheckConstraint("valuation_version > 0 AND line_count > 0", name="ck_cost_reconciliation_versions"),
        CheckConstraint("source_digest ~ '^[0-9a-f]{64}$' AND status = 'CLOSED'", name="ck_cost_reconciliation_contract"),
        CheckConstraint("pool_quantity >= 0 AND pool_value_scr >= 0", name="ck_cost_reconciliation_values"),
        CheckConstraint("jsonb_typeof(snapshot) = 'object'", name="ck_cost_reconciliation_snapshot"),
        CheckConstraint("created_by IS NOT NULL AND NOT is_deleted AND deleted_at IS NULL", name="ck_cost_reconciliation_audit"),
        Index("ix_cost_reconciliation_pool_product", "org_id", "cost_pool_id", "product_id", "created_at"),
        {"schema": "containermgmt"},
    )
    id = Column(Integer, primary_key=True)
    checkpoint_key = Column(UUID(as_uuid=True), nullable=False)
    cost_pool_id = Column(Integer, nullable=False)
    product_id = Column(Integer, nullable=False)
    valuation_id = Column(Integer, nullable=False)
    valuation_version = Column(Integer, nullable=False)
    line_count = Column(Integer, nullable=False)
    base_unit = Column(String(50), nullable=False)
    pool_quantity = Column(Numeric(18, 6), nullable=False)
    pool_value_scr = Column(Numeric(24, 6), nullable=False)
    source_digest = Column(String(64), nullable=False)
    snapshot = Column(JSONB, nullable=False)
    status = Column(String(20), nullable=False, server_default="CLOSED")


FUNCTION = """CREATE OR REPLACE FUNCTION containermgmt.reject_cost_reconciliation_change()
RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
RAISE EXCEPTION 'Inventory cost reconciliation checkpoints are immutable'; END; $$"""
TRIGGER = """CREATE TRIGGER cost_reconciliation_immutable BEFORE UPDATE OR DELETE
ON containermgmt.inventory_cost_reconciliations FOR EACH ROW
EXECUTE FUNCTION containermgmt.reject_cost_reconciliation_change()"""
event.listen(InventoryCostReconciliation.__table__, "after_create", DDL(FUNCTION))
event.listen(InventoryCostReconciliation.__table__, "after_create", DDL(TRIGGER))
