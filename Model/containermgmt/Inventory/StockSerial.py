"""Immutable serial identity, opening position and exact movement history."""
from sqlalchemy import Column, Integer, String, UniqueConstraint, ForeignKey, ForeignKeyConstraint, CheckConstraint, Index, DDL, event
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


class StockSerialMovement(OrgMixin, AuditMixin, Base):
    __tablename__ = "inventory_stock_serial_movements"
    __table_args__ = (
        UniqueConstraint("org_id", "serial_id", "sequence", name="uq_stock_serial_movement_sequence"),
        UniqueConstraint("org_id", "operation_key", "serial_id", name="uq_stock_serial_movement_operation"),
        ForeignKeyConstraint(["serial_id", "product_id", "org_id"],
            ["containermgmt.inventory_stock_serial_identities.id", "containermgmt.inventory_stock_serial_identities.product_id", "containermgmt.inventory_stock_serial_identities.org_id"], name="fk_stock_serial_movement_identity"),
        ForeignKeyConstraint(["from_balance_id", "product_id", "org_id"],
            ["containermgmt.inventory_stock_balances.id", "containermgmt.inventory_stock_balances.product_id", "containermgmt.inventory_stock_balances.org_id"], name="fk_stock_serial_movement_from_balance"),
        ForeignKeyConstraint(["org_id", "operation_key"],
            ["containermgmt.inventory_posting_operations.org_id", "containermgmt.inventory_posting_operations.operation_key"], name="fk_stock_serial_movement_operation", deferrable=True, initially="DEFERRED"),
        CheckConstraint("sequence > 0 AND kind = 'HANDOVER' AND from_balance_id IS NOT NULL "
            "AND to_balance_id IS NULL AND from_condition = 'AVAILABLE' AND to_condition IS NULL",
            name="ck_stock_serial_movement_shape"),
        CheckConstraint("created_by IS NOT NULL AND NOT is_deleted AND deleted_at IS NULL",
            name="ck_stock_serial_movement_audit"),
        Index("ix_stock_serial_movement_current", "org_id", "serial_id", "sequence"),
        Index("ix_stock_serial_movement_stock", "org_id", "stock_movement_id"),
        {"schema": "containermgmt"},
    )
    id = Column(Integer, primary_key=True)
    operation_key = Column(UUID(as_uuid=True), nullable=False)
    stock_movement_id = Column(Integer,
        ForeignKey("containermgmt.inventory_stock_movements.id"), nullable=False)
    serial_id = Column(Integer, nullable=False)
    product_id = Column(Integer, nullable=False)
    sequence = Column(Integer, nullable=False)
    kind = Column(String(20), nullable=False)
    from_balance_id = Column(Integer, nullable=False)
    to_balance_id = Column(Integer)
    from_condition = Column(String(20), nullable=False)
    to_condition = Column(String(20))


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


for model in (StockSerialIdentity, StockSerialPosition, StockSerialMovement):
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

MOVEMENT_SCOPE_FUNCTION = """
CREATE OR REPLACE FUNCTION containermgmt.check_serial_movement_scope()
RETURNS trigger LANGUAGE plpgsql AS $$ DECLARE prior record; opening record; stock record; BEGIN
SELECT id, operation_key, balance_id, kind, on_hand_delta INTO stock
FROM containermgmt.inventory_stock_movements
WHERE id=NEW.stock_movement_id AND org_id=NEW.org_id;
IF stock IS NULL OR stock.operation_key<>NEW.operation_key OR stock.balance_id<>NEW.from_balance_id
 OR stock.kind<>'HANDOVER' OR stock.on_hand_delta>=0 THEN
 RAISE EXCEPTION 'Serial movement requires its exact handover stock movement';
END IF;
SELECT sequence, to_balance_id, to_condition INTO prior
FROM containermgmt.inventory_stock_serial_movements
WHERE org_id=NEW.org_id AND serial_id=NEW.serial_id
ORDER BY sequence DESC LIMIT 1 FOR UPDATE;
IF prior IS NULL THEN
 SELECT balance_id, condition INTO opening
 FROM containermgmt.inventory_stock_serial_positions
 WHERE org_id=NEW.org_id AND serial_id=NEW.serial_id AND product_id=NEW.product_id;
 IF opening IS NULL OR NEW.sequence<>1 OR opening.balance_id<>NEW.from_balance_id
  OR opening.condition<>NEW.from_condition THEN
  RAISE EXCEPTION 'Serial handover must start from its exact current opening position';
 END IF;
ELSIF NEW.sequence<>prior.sequence+1 OR prior.to_balance_id IS DISTINCT FROM NEW.from_balance_id
 OR prior.to_condition IS DISTINCT FROM NEW.from_condition THEN
 RAISE EXCEPTION 'Serial handover does not continue its exact movement history';
END IF;
RETURN NEW; END; $$
"""
MOVEMENT_SCOPE_TRIGGER = """CREATE TRIGGER serial_movement_scope BEFORE INSERT
ON containermgmt.inventory_stock_serial_movements FOR EACH ROW
EXECUTE FUNCTION containermgmt.check_serial_movement_scope()"""
MOVEMENT_TOTAL_FUNCTION = """
CREATE OR REPLACE FUNCTION containermgmt.check_serial_handover_total()
RETURNS trigger LANGUAGE plpgsql AS $$ DECLARE tracking text; actual integer;
stock record; BEGIN
IF TG_TABLE_NAME='inventory_stock_serial_movements' THEN
 SELECT id, org_id, balance_id, kind, on_hand_delta INTO stock
 FROM containermgmt.inventory_stock_movements
 WHERE id=NEW.stock_movement_id AND org_id=NEW.org_id;
ELSE stock=NEW; END IF;
IF stock IS NULL OR stock.kind<>'HANDOVER' THEN RETURN NULL; END IF;
SELECT tracking_policy INTO tracking FROM containermgmt.inventory_stock_balances
WHERE id=stock.balance_id AND org_id=stock.org_id;
IF tracking<>'SERIAL' THEN RETURN NULL; END IF;
SELECT count(*) INTO actual FROM containermgmt.inventory_stock_serial_movements
WHERE org_id=stock.org_id AND stock_movement_id=stock.id AND kind='HANDOVER';
IF actual<>-stock.on_hand_delta THEN
 RAISE EXCEPTION 'Serial handover identities must equal the exact stock quantity';
END IF;
RETURN NULL; END; $$
"""
MOVEMENT_TOTAL_TRIGGER = """CREATE CONSTRAINT TRIGGER serial_handover_total_guard
AFTER INSERT ON containermgmt.inventory_stock_movements DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION containermgmt.check_serial_handover_total()"""
SERIAL_MOVEMENT_TOTAL_TRIGGER = """CREATE CONSTRAINT TRIGGER serial_movement_total_guard
AFTER INSERT ON containermgmt.inventory_stock_serial_movements DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION containermgmt.check_serial_handover_total()"""
event.listen(StockSerialMovement.__table__, "after_create", DDL(MOVEMENT_SCOPE_FUNCTION))
event.listen(StockSerialMovement.__table__, "after_create", DDL(MOVEMENT_SCOPE_TRIGGER))
event.listen(StockSerialMovement.__table__, "after_create", DDL(MOVEMENT_TOTAL_FUNCTION))
event.listen(StockSerialMovement.__table__, "after_create", DDL(MOVEMENT_TOTAL_TRIGGER))
event.listen(StockSerialMovement.__table__, "after_create", DDL(SERIAL_MOVEMENT_TOTAL_TRIGGER))
