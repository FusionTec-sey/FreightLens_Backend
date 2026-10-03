"""Immutable attribution of a stock reservation to an actual saved demand line."""
from sqlalchemy import Column, Integer, ForeignKeyConstraint, CheckConstraint, Index, DDL, event
from sqlalchemy.dialects.postgresql import UUID
from Model.db import Base
from Model.mixins import OrgMixin, AuditMixin


class SalesReservationSource(OrgMixin, AuditMixin, Base):
    __tablename__ = 'sales_reservation_sources'
    __table_args__ = (
        ForeignKeyConstraint(['org_id', 'reservation_key'], ['containermgmt.inventory_stock_reservations.org_id', 'containermgmt.inventory_stock_reservations.reservation_key']),
        ForeignKeyConstraint(['org_id', 'document_key', 'version', 'line_key'], ['containermgmt.sales_intent_line_revisions.org_id', 'containermgmt.sales_intent_line_revisions.document_key', 'containermgmt.sales_intent_line_revisions.version', 'containermgmt.sales_intent_line_revisions.line_key']),
        CheckConstraint('created_by IS NOT NULL AND NOT is_deleted AND deleted_at IS NULL', name='ck_sales_reservation_source_audit'),
        Index('ix_sales_reservation_demand', 'org_id', 'document_key', 'line_key', 'version'),
        {'schema': 'containermgmt'},
    )
    reservation_key = Column(UUID(as_uuid=True), primary_key=True)
    document_key = Column(UUID(as_uuid=True), nullable=False)
    version = Column(Integer, nullable=False)
    line_key = Column(UUID(as_uuid=True), nullable=False)


FUNCTION = """CREATE OR REPLACE FUNCTION containermgmt.reject_sales_reservation_source_change()
RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
RAISE EXCEPTION 'Reservation source history is immutable'; END; $$"""
TRIGGER = """CREATE TRIGGER sales_reservation_source_immutable BEFORE UPDATE OR DELETE
ON containermgmt.sales_reservation_sources FOR EACH ROW
EXECUTE FUNCTION containermgmt.reject_sales_reservation_source_change()"""
event.listen(SalesReservationSource.__table__, 'after_create', DDL(FUNCTION))
event.listen(SalesReservationSource.__table__, 'after_create', DDL(TRIGGER))
