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


MOVEMENT_KIND_CHECK = """(kind = 'OPENING' AND reservation_id IS NULL AND version = 1 AND on_hand_delta >= 0
                        AND reserved_delta = 0) OR (kind = 'RECEIPT' AND reservation_id IS NULL
                        AND version >= 1 AND on_hand_delta > 0 AND reserved_delta = 0) OR
                        (kind = 'RESERVE' AND reservation_id IS NOT NULL
                        AND version > 1 AND on_hand_delta = 0 AND reserved_delta > 0) OR
                        (kind = 'RELEASE' AND reservation_id IS NOT NULL AND version > 1
                        AND on_hand_delta = 0 AND reserved_delta < 0) OR
                        (kind = 'HANDOVER' AND reservation_id IS NOT NULL AND version > 1
                        AND on_hand_delta < 0 AND reserved_delta = on_hand_delta) OR
                        (kind = 'RETURN' AND reservation_id IS NULL AND version > 1
                        AND on_hand_delta > 0 AND reserved_delta = 0) OR
                        (kind = 'ADJUSTMENT' AND reservation_id IS NULL AND version > 1
                        AND reserved_delta = 0)"""


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
        CheckConstraint(MOVEMENT_KIND_CHECK, name="ck_stock_movement_kind"),
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

ADJUSTMENT_FUNCTION = """CREATE OR REPLACE FUNCTION containermgmt.guard_reviewed_stock_adjustment()
RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
IF NEW.kind = 'ADJUSTMENT' AND NOT EXISTS (
 SELECT 1 FROM containermgmt.manager_case_uses used
 JOIN containermgmt.manager_cases review ON review.id=used.case_id AND review.org_id=used.org_id
 JOIN containermgmt.manager_case_decisions decision ON decision.case_id=review.id AND decision.org_id=review.org_id
 WHERE used.operation_key=NEW.operation_key AND used.org_id=NEW.org_id
 AND used.created_by=NEW.created_by AND decision.outcome='APPROVED'
 AND review.action='inventory.stock.adjust' AND review.source_type='inventory.stock-balance'
 AND review.source_key=NEW.balance_id::text AND review.source_version=NEW.version-1
 AND (review.binding->'details'->>'balance_id')::integer=NEW.balance_id
 AND (review.binding->'details'->>'target_on_hand')::numeric=NEW.on_hand
 AND (review.binding->'details'->>'reserved')::numeric=NEW.reserved
 AND (review.binding->'details'->>'target_damaged')::numeric=NEW.damaged
 AND (review.binding->'details'->>'target_quarantined')::numeric=NEW.quarantined
) THEN RAISE EXCEPTION 'Stock adjustment requires its exact approved manager case use'; END IF;
RETURN NEW; END; $$"""
ADJUSTMENT_TRIGGER = """CREATE TRIGGER reviewed_stock_adjustment_guard BEFORE INSERT
ON containermgmt.inventory_stock_movements FOR EACH ROW
EXECUTE FUNCTION containermgmt.guard_reviewed_stock_adjustment()"""
event.listen(StockMovement.__table__, "after_create", DDL(ADJUSTMENT_FUNCTION))
event.listen(StockMovement.__table__, "after_create", DDL(ADJUSTMENT_TRIGGER))

RECEIPT_FUNCTION = """CREATE OR REPLACE FUNCTION containermgmt.guard_receipt_stock_movement()
RETURNS trigger LANGUAGE plpgsql AS $$ DECLARE manifest jsonb; tracking text; lot uuid;
expected_on numeric; expected_damaged numeric; expected_quarantined numeric;
prior_damaged numeric; prior_quarantined numeric; matches integer; BEGIN
IF NEW.kind <> 'RECEIPT' THEN RETURN NEW; END IF;
SELECT m.snapshot->'manifest', b.tracking_policy, b.batch_key
INTO manifest, tracking, lot
FROM containermgmt.inventory_receipt_source_uses u
JOIN containermgmt.inventory_receipt_manifests m ON m.manifest_key=u.manifest_key AND m.org_id=u.org_id
JOIN containermgmt.inventory_stock_balances b ON b.id=NEW.balance_id AND b.org_id=NEW.org_id
WHERE u.operation_key=NEW.operation_key AND u.org_id=NEW.org_id
AND (m.snapshot->'source'->>'branch_id')::integer=b.branch_id
AND (m.snapshot->'source'->>'location_id')::integer=b.location_id
AND (m.snapshot->'source'->>'product_id')::integer=b.product_id
AND m.snapshot->'source'->>'base_unit'=b.base_unit;
IF manifest IS NULL THEN RAISE EXCEPTION 'Receipt movement requires matching consumed source and stock scope'; END IF;
IF tracking='BATCH' THEN
 SELECT count(*), max((row->>'on_hand')::numeric), max((row->>'damaged')::numeric),
        max((row->>'quarantined')::numeric)
 INTO matches, expected_on, expected_damaged, expected_quarantined
 FROM jsonb_array_elements(manifest->'batches') row
 WHERE (row->'identity'->>'batch_key')::uuid=lot;
 IF matches <> 1 THEN RAISE EXCEPTION 'Receipt batch movement requires one manifest identity'; END IF;
ELSIF tracking IN ('UNTRACKED','SERIAL') THEN
 expected_on=(manifest->>'on_hand')::numeric;
 expected_damaged=(manifest->>'damaged')::numeric;
 expected_quarantined=(manifest->>'quarantined')::numeric;
 IF tracking='UNTRACKED' AND (jsonb_array_length(manifest->'batches') <> 0 OR manifest->'serials' <> 'null'::jsonb) THEN
  RAISE EXCEPTION 'Untracked receipt movement cannot carry identities'; END IF;
 IF tracking='SERIAL' AND manifest->'serials' = 'null'::jsonb THEN
  RAISE EXCEPTION 'Serial receipt movement requires identities'; END IF;
ELSE RAISE EXCEPTION 'Unsupported receipt tracking policy'; END IF;
IF NEW.version=1 THEN prior_damaged=0; prior_quarantined=0;
ELSE
 SELECT damaged, quarantined INTO prior_damaged, prior_quarantined
 FROM containermgmt.inventory_stock_movements
 WHERE balance_id=NEW.balance_id AND org_id=NEW.org_id AND version=NEW.version-1;
 IF prior_damaged IS NULL THEN RAISE EXCEPTION 'Receipt movement predecessor missing'; END IF;
END IF;
IF NEW.on_hand_delta <> expected_on OR NEW.damaged-prior_damaged <> expected_damaged
 OR NEW.quarantined-prior_quarantined <> expected_quarantined THEN
 RAISE EXCEPTION 'Receipt movement does not conserve manifest conditions'; END IF;
RETURN NEW; END; $$"""
RECEIPT_TRIGGER = """CREATE TRIGGER receipt_stock_movement_guard BEFORE INSERT
ON containermgmt.inventory_stock_movements FOR EACH ROW
EXECUTE FUNCTION containermgmt.guard_receipt_stock_movement()"""
RECEIPT_TOTAL_FUNCTION = """CREATE OR REPLACE FUNCTION containermgmt.check_receipt_stock_total()
RETURNS trigger LANGUAGE plpgsql AS $$ DECLARE expected numeric; actual numeric; BEGIN
IF NEW.kind <> 'RECEIPT' THEN RETURN NULL; END IF;
SELECT quantity INTO expected FROM containermgmt.inventory_receipt_source_uses
 WHERE operation_key=NEW.operation_key AND org_id=NEW.org_id;
SELECT COALESCE(sum(on_hand_delta),0) INTO actual FROM containermgmt.inventory_stock_movements
 WHERE operation_key=NEW.operation_key AND org_id=NEW.org_id AND kind='RECEIPT';
IF expected IS NULL OR actual <> expected THEN RAISE EXCEPTION 'Receipt movements must consume the complete source quantity'; END IF;
RETURN NULL; END; $$"""
RECEIPT_TOTAL_TRIGGER = """CREATE CONSTRAINT TRIGGER receipt_stock_total_guard AFTER INSERT
ON containermgmt.inventory_stock_movements DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
EXECUTE FUNCTION containermgmt.check_receipt_stock_total()"""
event.listen(StockMovement.__table__, 'after_create', DDL(RECEIPT_FUNCTION))
event.listen(StockMovement.__table__, 'after_create', DDL(RECEIPT_TRIGGER))
event.listen(StockMovement.__table__, 'after_create', DDL(RECEIPT_TOTAL_FUNCTION))
event.listen(StockMovement.__table__, 'after_create', DDL(RECEIPT_TOTAL_TRIGGER))

HANDOVER_FUNCTION = """CREATE OR REPLACE FUNCTION containermgmt.guard_handover_stock_movement()
RETURNS trigger LANGUAGE plpgsql AS $$ DECLARE prior record; BEGIN
IF NEW.kind <> 'HANDOVER' THEN RETURN NEW; END IF;
SELECT on_hand, reserved, damaged, quarantined INTO prior
FROM containermgmt.inventory_stock_movements
WHERE balance_id=NEW.balance_id AND org_id=NEW.org_id AND version=NEW.version-1;
IF prior IS NULL OR NEW.on_hand_delta >= 0 OR NEW.reserved_delta <> NEW.on_hand_delta
 OR NEW.on_hand <> prior.on_hand + NEW.on_hand_delta
 OR NEW.reserved <> prior.reserved + NEW.reserved_delta
 OR NEW.damaged <> prior.damaged OR NEW.quarantined <> prior.quarantined
 OR NOT EXISTS (
   SELECT 1 FROM containermgmt.inventory_stock_reservations reservation
   WHERE reservation.id=NEW.reservation_id AND reservation.balance_id=NEW.balance_id
   AND reservation.org_id=NEW.org_id AND NOT reservation.is_deleted
 ) THEN RAISE EXCEPTION 'Handover movement must consume its exact reservation and predecessor'; END IF;
RETURN NEW; END; $$"""
HANDOVER_TRIGGER = """CREATE TRIGGER handover_stock_movement_guard BEFORE INSERT
ON containermgmt.inventory_stock_movements FOR EACH ROW
EXECUTE FUNCTION containermgmt.guard_handover_stock_movement()"""
event.listen(StockMovement.__table__, 'after_create', DDL(HANDOVER_FUNCTION))
event.listen(StockMovement.__table__, 'after_create', DDL(HANDOVER_TRIGGER))

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
