"""Approved follow-up schedule history, never an expiry/cancellation instruction."""
from sqlalchemy import Column, Integer, DateTime, ForeignKeyConstraint, UniqueConstraint, CheckConstraint, DDL, event
from sqlalchemy.dialects.postgresql import UUID
from Model.db import Base
from Model.mixins import OrgMixin, AuditMixin


class ReservationDeadline(OrgMixin, AuditMixin, Base):
    __tablename__ = 'reservation_deadline_revisions'
    __table_args__ = (
        UniqueConstraint('org_id', 'reservation_key', 'version', name='uq_reservation_deadline_version'),
        UniqueConstraint('org_id', 'case_key', name='uq_reservation_deadline_case'),
        UniqueConstraint('org_id', 'operation_key', name='uq_reservation_deadline_operation'),
        ForeignKeyConstraint(['org_id', 'reservation_key'], ['containermgmt.inventory_stock_reservations.org_id', 'containermgmt.inventory_stock_reservations.reservation_key']),
        ForeignKeyConstraint(['org_id', 'case_key'], ['containermgmt.manager_cases.org_id', 'containermgmt.manager_cases.case_key']),
        ForeignKeyConstraint(['org_id', 'operation_key'], ['containermgmt.inventory_posting_operations.org_id', 'containermgmt.inventory_posting_operations.operation_key'], deferrable=True, initially='DEFERRED'),
        CheckConstraint('version > 0 AND review_at > previous_review_at', name='ck_reservation_deadline_forward'),
        CheckConstraint('created_by IS NOT NULL AND NOT is_deleted AND deleted_at IS NULL', name='ck_reservation_deadline_audit'),
        {'schema': 'containermgmt'},
    )
    id = Column(Integer, primary_key=True)
    reservation_key = Column(UUID(as_uuid=True), nullable=False)
    case_key = Column(UUID(as_uuid=True), nullable=False)
    operation_key = Column(UUID(as_uuid=True), nullable=False)
    version = Column(Integer, nullable=False)
    previous_review_at = Column(DateTime(timezone=True), nullable=False)
    review_at = Column(DateTime(timezone=True), nullable=False)


FUNCTION = """CREATE OR REPLACE FUNCTION containermgmt.guard_reservation_deadline()
RETURNS trigger LANGUAGE plpgsql AS $$ DECLARE previous_version integer; previous_date timestamptz; BEGIN
IF TG_OP <> 'INSERT' THEN RAISE EXCEPTION 'Reservation deadline history is immutable'; END IF;
SELECT review_at INTO previous_date FROM containermgmt.inventory_stock_reservations
WHERE org_id=NEW.org_id AND reservation_key=NEW.reservation_key AND quantity>released FOR UPDATE;
IF NOT FOUND THEN RAISE EXCEPTION 'An active reservation is required'; END IF;
SELECT version, review_at INTO previous_version, previous_date
FROM containermgmt.reservation_deadline_revisions
WHERE org_id=NEW.org_id AND reservation_key=NEW.reservation_key ORDER BY version DESC LIMIT 1;
IF previous_version IS NULL THEN
previous_version := 0;
SELECT review_at INTO previous_date FROM containermgmt.inventory_stock_reservations
WHERE org_id=NEW.org_id AND reservation_key=NEW.reservation_key;
END IF;
IF NEW.version <> previous_version+1 OR NEW.previous_review_at <> previous_date THEN
RAISE EXCEPTION 'Reservation deadline history must be consecutive'; END IF;
IF NOT EXISTS (SELECT 1 FROM containermgmt.manager_cases c
JOIN containermgmt.manager_case_uses u ON u.case_id=c.id AND u.org_id=c.org_id
WHERE c.org_id=NEW.org_id AND c.case_key=NEW.case_key AND u.operation_key=NEW.operation_key
AND u.created_by=NEW.created_by
AND c.action='inventory.reservation.review-deadline' AND c.source_type='sales.reservation'
AND c.source_key=NEW.reservation_key::text
AND (c.binding->'details'->>'deadline_version')::integer=previous_version
AND (c.binding->'details'->>'review_at')::timestamptz=previous_date
AND (c.binding->'details'->>'next_review_at')::timestamptz=NEW.review_at) THEN
RAISE EXCEPTION 'Exact approved deadline use is required'; END IF;
RETURN NEW; END; $$"""
TRIGGER = """CREATE TRIGGER reservation_deadline_guard BEFORE INSERT OR UPDATE OR DELETE
ON containermgmt.reservation_deadline_revisions FOR EACH ROW
EXECUTE FUNCTION containermgmt.guard_reservation_deadline()"""
event.listen(ReservationDeadline.__table__, 'after_create', DDL(FUNCTION))
event.listen(ReservationDeadline.__table__, 'after_create', DDL(TRIGGER))
