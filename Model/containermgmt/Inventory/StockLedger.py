"""Physical stock foundation, deliberately not wired to legacy stock writers."""
from sqlalchemy import (Column, Integer, String, Numeric, DateTime, Date, UniqueConstraint,
                        ForeignKeyConstraint, CheckConstraint, Index, DDL, event, text)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from Model.db import Base
from Model.mixins import OrgMixin, AuditMixin


def quantity():
    return Column(Numeric(18, 6), nullable=False)


POLICY_CHECK = """(policy_config IS NULL AND quantity_step IS NULL) OR
  (policy_config IS NOT NULL AND quantity_step IS NOT NULL AND COALESCE(
    jsonb_typeof(policy_config) = 'object'
    AND policy_config->>'base_unit' = base_unit
    AND policy_config->>'tracking' = tracking_policy
    AND (policy_config->>'quantity_step')::numeric = quantity_step
    AND quantity_step IN (1, 0.1, 0.01, 0.001, 0.0001, 0.00001, 0.000001)
    AND mod(on_hand, quantity_step) = 0 AND mod(reserved, quantity_step) = 0
    AND mod(damaged, quantity_step) = 0 AND mod(quarantined, quantity_step) = 0, false))"""


BATCH_CONTRACT = """version >= 1 AND length(trim(base_unit)) > 0 AND
    ((tracking_policy = 'UNTRACKED' AND batch_key IS NULL) OR
     (tracking_policy = 'SERIAL' AND batch_key IS NULL AND policy_config IS NOT NULL AND quantity_step = 1) OR
     (tracking_policy = 'BATCH' AND batch_key IS NOT NULL AND policy_config IS NOT NULL))"""


class StockBatch(OrgMixin, AuditMixin, Base):
    __tablename__ = "inventory_stock_batches"
    __table_args__ = (
        UniqueConstraint("batch_key", "product_id", "org_id", name="uq_stock_batch_scope"),
        UniqueConstraint("org_id", "product_id", "code", name="uq_stock_batch_code"),
        ForeignKeyConstraint(["product_id", "org_id"],
            ["containermgmt.products.id", "containermgmt.products.org_id"], name="fk_stock_batch_product_scope"),
        CheckConstraint("batch_key <> '00000000-0000-0000-0000-000000000000'::uuid AND length(trim(code)) > 0 "
            "AND (shade IS NULL OR length(trim(shade)) > 0) AND (calibre IS NULL OR length(trim(calibre)) > 0)",
            name="ck_stock_batch_identity"),
        CheckConstraint("created_by IS NOT NULL AND NOT is_deleted AND deleted_at IS NULL", name="ck_stock_batch_audit"),
        Index("ix_stock_batch_product", "product_id", "org_id"),
        {"schema": "containermgmt"},
    )
    batch_key = Column(UUID(as_uuid=True), primary_key=True)
    product_id = Column(Integer, nullable=False)
    code = Column(String(100), nullable=False)
    shade = Column(String(80))
    calibre = Column(String(80))
    expires_on = Column(Date)


class StockBalance(OrgMixin, AuditMixin, Base):
    __tablename__ = "inventory_stock_balances"
    __table_args__ = (
        Index("uq_stock_balance_untracked", "org_id", "location_id", "product_id", unique=True,
              postgresql_where=text("batch_key IS NULL")),
        Index("uq_stock_balance_batch", "org_id", "location_id", "product_id", "batch_key", unique=True,
              postgresql_where=text("batch_key IS NOT NULL")),
        UniqueConstraint("id", "org_id", name="uq_stock_balance_id_org"),
        UniqueConstraint("id", "product_id", "org_id", name="uq_stock_balance_product_scope"),
        ForeignKeyConstraint(["location_id", "branch_id", "org_id"],
            ["containermgmt.stock_locations.id", "containermgmt.stock_locations.branch_id",
             "containermgmt.stock_locations.org_id"], name="fk_stock_balance_location_scope"),
        ForeignKeyConstraint(["product_id", "org_id"],
            ["containermgmt.products.id", "containermgmt.products.org_id"], name="fk_stock_balance_product_scope"),
        ForeignKeyConstraint(["batch_key", "product_id", "org_id"],
            ["containermgmt.inventory_stock_batches.batch_key", "containermgmt.inventory_stock_batches.product_id",
             "containermgmt.inventory_stock_batches.org_id"], name="fk_stock_balance_batch_scope"),
        CheckConstraint("on_hand >= 0 AND on_hand < 1000000000000 AND reserved >= 0 AND damaged >= 0 "
                        "AND quarantined >= 0 AND reserved + damaged + quarantined <= on_hand",
                        name="ck_stock_balance_quantities"),
        CheckConstraint(BATCH_CONTRACT, name="ck_stock_balance_batch_contract"),
        CheckConstraint("created_by IS NOT NULL AND NOT is_deleted AND deleted_at IS NULL",
                        name="ck_stock_balance_audit"),
        CheckConstraint(POLICY_CHECK, name="ck_stock_balance_unit_policy"),
        Index("ix_stock_balance_location_scope", "location_id", "branch_id", "org_id"),
        Index("ix_stock_balance_product_scope", "product_id", "org_id"),
        Index("ix_stock_balance_branch", "branch_id", "org_id"),
        Index("ix_stock_balance_batch_scope", "batch_key", "product_id", "org_id"),
        {"schema": "containermgmt"},
    )
    id = Column(Integer, primary_key=True)
    branch_id = Column(Integer, nullable=False)
    location_id = Column(Integer, nullable=False)
    product_id = Column(Integer, nullable=False)
    base_unit = Column(String(50), nullable=False)
    tracking_policy = Column(String(20), nullable=False)
    batch_key = Column(UUID(as_uuid=True))
    # NULL identifies pre-policy rows; never infer or backfill historical rules.
    policy_config = Column(JSONB(none_as_null=True))
    quantity_step = Column(Numeric(18, 6))
    on_hand = quantity()
    reserved = quantity()
    damaged = quantity()
    quarantined = quantity()
    version = Column(Integer, nullable=False)


class StockReservation(OrgMixin, AuditMixin, Base):
    __tablename__ = "inventory_stock_reservations"
    __table_args__ = (
        UniqueConstraint("org_id", "reservation_key", name="uq_stock_reservation_key"),
        # A reviewed reallocation may append another segment; its deferred
        # approval/paired-movement guard replaces the old one-hold uniqueness.
        UniqueConstraint("id", "balance_id", "org_id", name="uq_stock_reservation_scope"),
        ForeignKeyConstraint(["balance_id", "org_id"],
            ["containermgmt.inventory_stock_balances.id", "containermgmt.inventory_stock_balances.org_id"],
            name="fk_stock_reservation_balance_scope"),
        CheckConstraint("quantity > 0 AND quantity < 1000000000000 AND released >= 0 AND released <= quantity",
                        name="ck_stock_reservation_quantities"),
        CheckConstraint("created_by IS NOT NULL AND NOT is_deleted AND deleted_at IS NULL",
                        name="ck_stock_reservation_audit"),
        Index("ix_stock_reservation_balance", "balance_id", "org_id"),
        Index("ix_stock_reservation_source", "org_id", "source_line_key"),
        Index("ix_stock_reservation_review", "org_id", "review_at", "id"),
        {"schema": "containermgmt"},
    )
    id = Column(Integer, primary_key=True)
    reservation_key = Column(UUID(as_uuid=True), nullable=False)
    balance_id = Column(Integer, nullable=False)
    # Trusted integration reference, not yet an FK to a retail sales document.
    source_line_key = Column(UUID(as_uuid=True), nullable=False)
    quantity = quantity()
    released = Column(Numeric(18, 6), nullable=False)
    review_at = Column(DateTime(timezone=True), nullable=False)


class StockMovement(OrgMixin, AuditMixin, Base):
    __tablename__ = "inventory_stock_movements"
    __table_args__ = (
        UniqueConstraint("balance_id", "version", name="uq_stock_movement_version"),
        UniqueConstraint("org_id", "operation_key", "balance_id", name="uq_stock_movement_operation"),
        ForeignKeyConstraint(["balance_id", "org_id"],
            ["containermgmt.inventory_stock_balances.id", "containermgmt.inventory_stock_balances.org_id"],
            name="fk_stock_movement_balance_scope"),
        ForeignKeyConstraint(["reservation_id", "balance_id", "org_id"],
            ["containermgmt.inventory_stock_reservations.id", "containermgmt.inventory_stock_reservations.balance_id",
             "containermgmt.inventory_stock_reservations.org_id"], name="fk_stock_movement_reservation_scope"),
        ForeignKeyConstraint(["org_id", "operation_key"],
            ["containermgmt.inventory_posting_operations.org_id", "containermgmt.inventory_posting_operations.operation_key"],
            name="fk_stock_movement_operation", deferrable=True, initially="DEFERRED"),
        CheckConstraint("(kind = 'OPENING' AND reservation_id IS NULL AND version = 1 AND on_hand_delta >= 0 "
                        "AND reserved_delta = 0) OR (kind = 'RESERVE' AND reservation_id IS NOT NULL "
                        "AND version > 1 AND on_hand_delta = 0 AND reserved_delta > 0) OR "
                        "(kind = 'RELEASE' AND reservation_id IS NOT NULL AND version > 1 "
                        "AND on_hand_delta = 0 AND reserved_delta < 0)", name="ck_stock_movement_kind"),
        CheckConstraint("on_hand >= 0 AND on_hand < 1000000000000 AND reserved >= 0 AND damaged >= 0 "
                        "AND quarantined >= 0 AND reserved + damaged + quarantined <= on_hand",
                        name="ck_stock_movement_quantities"),
        CheckConstraint("abs(on_hand_delta) < 1000000000000 AND abs(reserved_delta) < 1000000000000",
                        name="ck_stock_movement_finite_deltas"),
        CheckConstraint("created_by IS NOT NULL AND NOT is_deleted AND deleted_at IS NULL AND length(trim(reason)) > 0",
                        name="ck_stock_movement_audit"),
        Index("ix_stock_movement_reservation", "reservation_id", "balance_id", "org_id"),
        {"schema": "containermgmt"},
    )
    id = Column(Integer, primary_key=True)
    balance_id = Column(Integer, nullable=False)
    reservation_id = Column(Integer)
    operation_key = Column(UUID(as_uuid=True), nullable=False)
    version = Column(Integer, nullable=False)
    kind = Column(String(20), nullable=False)
    reason = Column(String(500), nullable=False)
    on_hand_delta = quantity()
    reserved_delta = quantity()
    on_hand = quantity()
    reserved = quantity()
    damaged = quantity()
    quarantined = quantity()


IMMUTABLE_FUNCTION = """
CREATE OR REPLACE FUNCTION containermgmt.reject_stock_movement_change()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Physical stock movements are immutable';
END;
$$
"""
IMMUTABLE_TRIGGER = """
CREATE TRIGGER stock_movement_immutable
BEFORE UPDATE OR DELETE ON containermgmt.inventory_stock_movements
FOR EACH ROW EXECUTE FUNCTION containermgmt.reject_stock_movement_change()
"""
event.listen(StockMovement.__table__, "after_create", DDL(IMMUTABLE_FUNCTION))
event.listen(StockMovement.__table__, "after_create", DDL(IMMUTABLE_TRIGGER))

BALANCE_IDENTITY_FUNCTION = """
CREATE OR REPLACE FUNCTION containermgmt.protect_stock_balance_identity()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Stock balances cannot be deleted';
    END IF;
    IF ROW(NEW.id, NEW.org_id, NEW.branch_id, NEW.location_id, NEW.product_id,
           NEW.base_unit, NEW.tracking_policy, NEW.policy_config, NEW.quantity_step, NEW.batch_key)
       IS DISTINCT FROM
       ROW(OLD.id, OLD.org_id, OLD.branch_id, OLD.location_id, OLD.product_id,
           OLD.base_unit, OLD.tracking_policy, OLD.policy_config, OLD.quantity_step, OLD.batch_key) THEN
        RAISE EXCEPTION 'Stock identity and unit policy are immutable';
    END IF;
    RETURN NEW;
END;
$$
"""
BALANCE_IDENTITY_TRIGGER = """
CREATE TRIGGER stock_balance_identity
BEFORE UPDATE OR DELETE ON containermgmt.inventory_stock_balances
FOR EACH ROW EXECUTE FUNCTION containermgmt.protect_stock_balance_identity()
"""
event.listen(StockBalance.__table__, "after_create", DDL(BALANCE_IDENTITY_FUNCTION))
event.listen(StockBalance.__table__, "after_create", DDL(BALANCE_IDENTITY_TRIGGER))

BATCH_IMMUTABLE_FUNCTION = """
CREATE OR REPLACE FUNCTION containermgmt.reject_stock_batch_change()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Stock batch identities are immutable';
END;
$$
"""
BATCH_IMMUTABLE_TRIGGER = """
CREATE TRIGGER stock_batch_immutable
BEFORE UPDATE OR DELETE ON containermgmt.inventory_stock_batches
FOR EACH ROW EXECUTE FUNCTION containermgmt.reject_stock_batch_change()
"""
event.listen(StockBatch.__table__, "after_create", DDL(BATCH_IMMUTABLE_FUNCTION))
event.listen(StockBatch.__table__, "after_create", DDL(BATCH_IMMUTABLE_TRIGGER))

from Model.containermgmt.Inventory.ReservationSegmentGuard import FUNCTION as SEGMENT_FUNCTION, TRIGGER as SEGMENT_TRIGGER, IDENTITY_FUNCTION as RESERVATION_IDENTITY_FUNCTION, IDENTITY_TRIGGER as RESERVATION_IDENTITY_TRIGGER
for statement in (SEGMENT_FUNCTION, SEGMENT_TRIGGER, RESERVATION_IDENTITY_FUNCTION, RESERVATION_IDENTITY_TRIGGER):
    event.listen(StockReservation.__table__, 'after_create', DDL(statement))
