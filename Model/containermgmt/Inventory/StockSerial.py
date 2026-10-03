"""Immutable serial identity, separate physical position; no handover writer yet."""
from sqlalchemy import Column, Integer, String, UniqueConstraint, ForeignKeyConstraint, CheckConstraint, Index, DDL, event
from sqlalchemy.dialects.postgresql import UUID
from Model.db import Base
from Model.mixins import OrgMixin, AuditMixin


class StockSerialIdentity(OrgMixin, AuditMixin, Base):
    __tablename__ = "inventory_stock_serial_identities"
    __table_args__ = (
        UniqueConstraint("org_id", "serial_key", name="uq_stock_serial_key"),
        UniqueConstraint("org_id", "product_id", "serial_number", name="uq_stock_serial_number"),
        UniqueConstraint("id", "product_id", "org_id", name="uq_stock_serial_scope"),
        ForeignKeyConstraint(["product_id", "org_id"], ["containermgmt.products.id", "containermgmt.products.org_id"], name="fk_stock_serial_product"),
        CheckConstraint("serial_key <> '00000000-0000-0000-0000-000000000000'::uuid AND length(trim(serial_number)) > 0", name="ck_stock_serial_identity"),
        CheckConstraint("created_by IS NOT NULL AND NOT is_deleted AND deleted_at IS NULL", name="ck_stock_serial_audit"),
        Index("ix_stock_serial_product", "product_id", "org_id"),
        {"schema": "containermgmt"},
    )
    id = Column(Integer, primary_key=True)
    serial_key = Column(UUID(as_uuid=True), nullable=False)
    product_id = Column(Integer, nullable=False)
    serial_number = Column(String(100), nullable=False)


class StockSerialPosition(OrgMixin, AuditMixin, Base):
    __tablename__ = "inventory_stock_serial_positions"
    __table_args__ = (
        ForeignKeyConstraint(["serial_id", "product_id", "org_id"],
            ["containermgmt.inventory_stock_serial_identities.id", "containermgmt.inventory_stock_serial_identities.product_id", "containermgmt.inventory_stock_serial_identities.org_id"], name="fk_stock_serial_position_identity"),
        ForeignKeyConstraint(["balance_id", "product_id", "org_id"],
            ["containermgmt.inventory_stock_balances.id", "containermgmt.inventory_stock_balances.product_id", "containermgmt.inventory_stock_balances.org_id"], name="fk_stock_serial_position_balance"),
        CheckConstraint("condition IN ('AVAILABLE', 'DAMAGED', 'QUARANTINED')", name="ck_stock_serial_condition"),
        CheckConstraint("created_by IS NOT NULL AND NOT is_deleted AND deleted_at IS NULL", name="ck_stock_serial_position_audit"),
        Index("ix_stock_serial_position_balance", "balance_id", "org_id", "condition", "serial_id"),
        Index("ix_stock_serial_position_product", "product_id", "org_id"),
        {"schema": "containermgmt"},
    )
    serial_id = Column(Integer, primary_key=True)
    product_id = Column(Integer, nullable=False)
    balance_id = Column(Integer, nullable=False)
    condition = Column(String(20), nullable=False)


SERIAL_FUNCTION = """
CREATE OR REPLACE FUNCTION containermgmt.protect_stock_serial_records()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Serial identity is immutable; position changes require a future audited movement gateway';
END;
$$
"""

def serial_trigger(table):
    return f"CREATE TRIGGER serial_record_protected BEFORE UPDATE OR DELETE ON containermgmt.{table} FOR EACH ROW EXECUTE FUNCTION containermgmt.protect_stock_serial_records()"


for model in (StockSerialIdentity, StockSerialPosition):
    event.listen(model.__table__, "after_create", DDL(SERIAL_FUNCTION))
    event.listen(model.__table__, "after_create", DDL(serial_trigger(model.__tablename__)))

POSITION_SCOPE_FUNCTION = """
CREATE OR REPLACE FUNCTION containermgmt.check_serial_position_scope()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    PERFORM 1 FROM containermgmt.inventory_stock_balances
    WHERE id = NEW.balance_id AND org_id = NEW.org_id AND product_id = NEW.product_id
      AND tracking_policy = 'SERIAL' AND NOT is_deleted FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'Serial position requires an owning serial-tracked balance'; END IF;
    RETURN NEW;
END;
$$
"""
POSITION_SCOPE_TRIGGER = """
CREATE TRIGGER serial_position_scope BEFORE INSERT ON containermgmt.inventory_stock_serial_positions
FOR EACH ROW EXECUTE FUNCTION containermgmt.check_serial_position_scope()
"""
event.listen(StockSerialPosition.__table__, "after_create", DDL(POSITION_SCOPE_FUNCTION))
event.listen(StockSerialPosition.__table__, "after_create", DDL(POSITION_SCOPE_TRIGGER))
