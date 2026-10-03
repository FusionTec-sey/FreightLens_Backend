"""Immutable linkage of one approved reallocation and its paired stock operations."""
from sqlalchemy import Column, Numeric, UniqueConstraint, ForeignKeyConstraint, CheckConstraint, DDL, event
from sqlalchemy.dialects.postgresql import UUID
from Model.db import Base
from Model.mixins import OrgMixin, AuditMixin


class ReservationReallocation(OrgMixin, AuditMixin, Base):
    __tablename__ = 'reservation_reallocations'
    __table_args__ = (
        UniqueConstraint('org_id', 'case_key', name='uq_reservation_reallocation_case'),
        UniqueConstraint('org_id', 'release_operation', name='uq_reallocation_release_operation'),
        UniqueConstraint('org_id', 'reserve_operation', name='uq_reallocation_reserve_operation'),
        ForeignKeyConstraint(['org_id', 'source_key'], ['containermgmt.inventory_stock_reservations.org_id', 'containermgmt.inventory_stock_reservations.reservation_key']),
        ForeignKeyConstraint(['org_id', 'target_key'], ['containermgmt.inventory_stock_reservations.org_id', 'containermgmt.inventory_stock_reservations.reservation_key']),
        ForeignKeyConstraint(['org_id', 'case_key'], ['containermgmt.manager_cases.org_id', 'containermgmt.manager_cases.case_key']),
        ForeignKeyConstraint(['org_id', 'operation_key'], ['containermgmt.inventory_posting_operations.org_id', 'containermgmt.inventory_posting_operations.operation_key'], deferrable=True, initially='DEFERRED'),
        ForeignKeyConstraint(['org_id', 'release_operation'], ['containermgmt.inventory_posting_operations.org_id', 'containermgmt.inventory_posting_operations.operation_key'], deferrable=True, initially='DEFERRED'),
        ForeignKeyConstraint(['org_id', 'reserve_operation'], ['containermgmt.inventory_posting_operations.org_id', 'containermgmt.inventory_posting_operations.operation_key'], deferrable=True, initially='DEFERRED'),
        CheckConstraint('quantity > 0 AND source_key <> target_key AND release_operation <> reserve_operation AND operation_key <> release_operation AND operation_key <> reserve_operation', name='ck_reallocation_identity'),
        CheckConstraint('created_by IS NOT NULL AND NOT is_deleted AND deleted_at IS NULL', name='ck_reallocation_audit'),
        {'schema': 'containermgmt'},
    )
    operation_key = Column(UUID(as_uuid=True), primary_key=True)
    case_key = Column(UUID(as_uuid=True), nullable=False)
    source_key = Column(UUID(as_uuid=True), nullable=False, index=True)
    target_key = Column(UUID(as_uuid=True), nullable=False, index=True)
    release_operation = Column(UUID(as_uuid=True), nullable=False)
    reserve_operation = Column(UUID(as_uuid=True), nullable=False)
    quantity = Column(Numeric(18, 6), nullable=False)


FUNCTION = """CREATE OR REPLACE FUNCTION containermgmt.guard_reservation_reallocation()
RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
IF TG_OP <> 'INSERT' THEN RAISE EXCEPTION 'Reservation reallocation history is immutable'; END IF;
IF NOT EXISTS (SELECT 1 FROM containermgmt.inventory_stock_reservations s
JOIN containermgmt.inventory_stock_reservations t ON t.org_id=s.org_id AND t.balance_id=s.balance_id
JOIN containermgmt.inventory_stock_movements r ON r.org_id=s.org_id AND r.reservation_id=s.id AND r.balance_id=s.balance_id
JOIN containermgmt.inventory_stock_movements a ON a.org_id=t.org_id AND a.reservation_id=t.id AND a.balance_id=t.balance_id
WHERE s.org_id=NEW.org_id AND s.reservation_key=NEW.source_key AND t.reservation_key=NEW.target_key
AND r.operation_key=NEW.release_operation AND a.operation_key=NEW.reserve_operation
AND r.kind='RELEASE' AND a.kind='RESERVE' AND r.reserved_delta=-NEW.quantity AND a.reserved_delta=NEW.quantity
AND r.on_hand_delta=0 AND a.on_hand_delta=0) THEN
RAISE EXCEPTION 'Exact same-bucket release and reserve movements required'; END IF;
IF NOT EXISTS (SELECT 1 FROM containermgmt.manager_cases c JOIN containermgmt.manager_case_uses u ON u.case_id=c.id AND u.org_id=c.org_id
JOIN containermgmt.sales_reservation_sources target ON target.org_id=c.org_id AND target.reservation_key=NEW.target_key
WHERE c.org_id=NEW.org_id AND c.case_key=NEW.case_key AND c.action='inventory.reservation.reallocate'
AND c.source_key=NEW.source_key::text AND (c.binding->'details'->>'quantity')::numeric=NEW.quantity
AND c.binding->'details'->'target'->>'document_key'=target.document_key::text
AND c.binding->'details'->'target'->>'line_key'=target.line_key::text
AND (c.binding->'details'->'target'->>'version')::integer=target.version
AND u.operation_key=NEW.operation_key AND u.created_by=NEW.created_by) THEN
RAISE EXCEPTION 'Approved reallocation use required'; END IF;
RETURN NEW; END; $$"""
TRIGGER = """CREATE TRIGGER reservation_reallocation_guard BEFORE INSERT OR UPDATE OR DELETE
ON containermgmt.reservation_reallocations FOR EACH ROW
EXECUTE FUNCTION containermgmt.guard_reservation_reallocation()"""
event.listen(ReservationReallocation.__table__, 'after_create', DDL(FUNCTION))
event.listen(ReservationReallocation.__table__, 'after_create', DDL(TRIGGER))
