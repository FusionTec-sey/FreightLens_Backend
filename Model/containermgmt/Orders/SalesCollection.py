"""Immutable, invoice-bound physical collection history.

Each collection records one stable business operation at one fulfilment branch.
Allocations bind invoice reservations to the unique T09 ``HANDOVER`` movement
identified by company, balance and handover operation.  The database validates
that linkage at transaction end because movement and collection history are
created atomically.  Serial-tracked collection is excluded from this first slice.
"""
from sqlalchemy import (
    CheckConstraint,
    Column,
    Date,
    DateTime,
    DDL,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    event,
    func,
)
from sqlalchemy.dialects.postgresql import UUID

from Model.db import Base
from Model.mixins import AuditMixin, OrgMixin
from Model.containermgmt.Inventory.BranchCounter import (  # noqa: F401
    BranchCounter,
    CounterSettingsRevision,
)
from Model.containermgmt.Inventory.BranchSettings import BranchSettingsRevision  # noqa: F401
from Model.containermgmt.Inventory.Location import InventoryBranch, StockLocation  # noqa: F401
from Model.containermgmt.Inventory.PostingOperation import PostingOperation  # noqa: F401
from Model.containermgmt.Inventory.StaffStoreAssignment import StaffStoreAssignment  # noqa: F401
from Model.containermgmt.Inventory.StockLedger import (  # noqa: F401
    StockBalance,
    StockMovement,
    StockReservation,
)
from Model.containermgmt.Orders.SalesPosting import (  # noqa: F401
    SalesInvoice,
    SalesInvoiceLine,
    SalesInvoiceReservation,
)


NONZERO_UUID = "<> '00000000-0000-0000-0000-000000000000'::uuid"
AUDIT_CHECK = "created_by IS NOT NULL AND NOT is_deleted AND deleted_at IS NULL"


class SalesCollection(OrgMixin, AuditMixin, Base):
    """One completed physical handover command for one posted invoice."""

    __tablename__ = "sales_collections"
    __table_args__ = (
        UniqueConstraint("collection_key", "org_id", name="uq_sales_collection_scope"),
        UniqueConstraint("org_id", "operation_key", name="uq_sales_collection_operation"),
        UniqueConstraint(
            "org_id", "collection_key", "branch_id",
            name="uq_sales_collection_branch_scope",
        ),
        ForeignKeyConstraint(
            ["invoice_key", "org_id"],
            ["containermgmt.sales_invoices.invoice_key", "containermgmt.sales_invoices.org_id"],
            name="fk_sales_collection_invoice",
        ),
        ForeignKeyConstraint(
            ["branch_id", "org_id"],
            ["containermgmt.inventory_branches.id", "containermgmt.inventory_branches.org_id"],
            name="fk_sales_collection_branch",
        ),
        ForeignKeyConstraint(
            ["counter_id", "org_id"],
            ["containermgmt.inventory_branch_counters.id",
             "containermgmt.inventory_branch_counters.org_id"],
            name="fk_sales_collection_counter",
        ),
        ForeignKeyConstraint(
            ["org_id", "branch_id", "branch_settings_version"],
            ["containermgmt.inventory_branch_settings_revisions.org_id",
             "containermgmt.inventory_branch_settings_revisions.branch_id",
             "containermgmt.inventory_branch_settings_revisions.version"],
            name="fk_sales_collection_branch_settings",
        ),
        ForeignKeyConstraint(
            ["org_id", "counter_id", "counter_settings_version"],
            ["containermgmt.inventory_counter_settings_revisions.org_id",
             "containermgmt.inventory_counter_settings_revisions.counter_id",
             "containermgmt.inventory_counter_settings_revisions.version"],
            name="fk_sales_collection_counter_settings",
        ),
        ForeignKeyConstraint(
            ["org_id", "created_by", "assignment_version"],
            ["containermgmt.inventory_staff_store_assignments.org_id",
             "containermgmt.inventory_staff_store_assignments.user_id",
             "containermgmt.inventory_staff_store_assignments.version"],
            name="fk_sales_collection_assignment",
        ),
        ForeignKeyConstraint(
            ["org_id", "operation_key"],
            ["containermgmt.inventory_posting_operations.org_id",
             "containermgmt.inventory_posting_operations.operation_key"],
            name="fk_sales_collection_operation",
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint(
            f"collection_key {NONZERO_UUID} AND operation_key {NONZERO_UUID} "
            "AND branch_settings_version > 0 AND counter_settings_version > 0 "
            "AND assignment_version > 0",
            name="ck_sales_collection_identity",
        ),
        CheckConstraint(
            "length(trim(collector_name)) BETWEEN 1 AND 150 "
            "AND length(trim(collector_contact)) BETWEEN 1 AND 50",
            name="ck_sales_collection_collector",
        ),
        CheckConstraint(AUDIT_CHECK, name="ck_sales_collection_audit"),
        Index("ix_sales_collection_invoice", "org_id", "invoice_key", "collected_at"),
        Index("ix_sales_collection_branch", "org_id", "branch_id", "collected_at"),
        {"schema": "containermgmt"},
    )
    collection_key = Column(UUID(as_uuid=True), primary_key=True)
    operation_key = Column(UUID(as_uuid=True), nullable=False)
    invoice_key = Column(UUID(as_uuid=True), nullable=False)
    branch_id = Column(Integer, nullable=False)
    counter_id = Column(Integer, nullable=False)
    branch_settings_version = Column(Integer, nullable=False)
    counter_settings_version = Column(Integer, nullable=False)
    assignment_version = Column(Integer, nullable=False)
    business_date = Column(Date, nullable=False)
    collector_name = Column(String(150), nullable=False)
    collector_contact = Column(String(50), nullable=False)
    collected_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SalesCollectionAllocation(OrgMixin, AuditMixin, Base):
    """One exact invoice/reservation quantity linked to one T09 movement."""

    __tablename__ = "sales_collection_allocations"
    __table_args__ = (
        UniqueConstraint(
            "org_id", "collection_key", "line_key", "reservation_key",
            name="uq_sales_collection_allocation_scope",
        ),
        UniqueConstraint(
            "org_id", "handover_operation_key",
            name="uq_sales_collection_handover_operation",
        ),
        ForeignKeyConstraint(
            ["collection_key", "org_id"],
            ["containermgmt.sales_collections.collection_key",
             "containermgmt.sales_collections.org_id"],
            name="fk_sales_collection_allocation_header",
        ),
        ForeignKeyConstraint(
            ["org_id", "invoice_key", "line_key"],
            ["containermgmt.sales_invoice_lines.org_id",
             "containermgmt.sales_invoice_lines.invoice_key",
             "containermgmt.sales_invoice_lines.line_key"],
            name="fk_sales_collection_allocation_line",
        ),
        ForeignKeyConstraint(
            ["org_id", "invoice_key", "line_key", "reservation_key"],
            ["containermgmt.sales_invoice_reservations.org_id",
             "containermgmt.sales_invoice_reservations.invoice_key",
             "containermgmt.sales_invoice_reservations.line_key",
             "containermgmt.sales_invoice_reservations.reservation_key"],
            name="fk_sales_collection_allocation_reservation",
        ),
        ForeignKeyConstraint(
            ["balance_id", "org_id"],
            ["containermgmt.inventory_stock_balances.id",
             "containermgmt.inventory_stock_balances.org_id"],
            name="fk_sales_collection_allocation_balance",
        ),
        ForeignKeyConstraint(
            ["org_id", "handover_operation_key"],
            ["containermgmt.inventory_posting_operations.org_id",
             "containermgmt.inventory_posting_operations.operation_key"],
            name="fk_sales_collection_handover_operation",
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint(
            f"reservation_key {NONZERO_UUID} "
            f"AND handover_operation_key {NONZERO_UUID}",
            name="ck_sales_collection_allocation_identity",
        ),
        CheckConstraint(
            "quantity > 0 AND quantity < 1000000000000 "
            "AND length(trim(base_unit)) BETWEEN 1 AND 50",
            name="ck_sales_collection_allocation_quantity",
        ),
        CheckConstraint(AUDIT_CHECK, name="ck_sales_collection_allocation_audit"),
        Index("ix_sales_collection_allocation_line", "org_id", "invoice_key", "line_key"),
        Index(
            "ix_sales_collection_allocation_collection",
            "org_id", "collection_key", "id",
        ),
        {"schema": "containermgmt"},
    )
    id = Column(Integer, primary_key=True)
    collection_key = Column(UUID(as_uuid=True), nullable=False)
    invoice_key = Column(UUID(as_uuid=True), nullable=False)
    line_key = Column(UUID(as_uuid=True), nullable=False)
    reservation_key = Column(UUID(as_uuid=True), nullable=False)
    balance_id = Column(Integer, nullable=False)
    location_id = Column(Integer, nullable=False)
    batch_key = Column(UUID(as_uuid=True), nullable=True)
    handover_operation_key = Column(UUID(as_uuid=True), nullable=False)
    quantity = Column(Numeric(18, 6), nullable=False)
    base_unit = Column(String(50), nullable=False)


MODELS = (SalesCollection, SalesCollectionAllocation)


IMMUTABLE_FUNCTION = """CREATE OR REPLACE FUNCTION containermgmt.reject_sales_collection_change()
RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
RAISE EXCEPTION 'Sales collection history is immutable'; END; $$"""


def immutable_trigger(table: str) -> str:
    return f"""CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE
ON containermgmt.{table} FOR EACH ROW
EXECUTE FUNCTION containermgmt.reject_sales_collection_change()"""


HEADER_GUARD_FUNCTION = """CREATE OR REPLACE FUNCTION containermgmt.check_sales_collection_header()
RETURNS trigger LANGUAGE plpgsql AS $$ DECLARE operation record; invoice_branch integer;
counter_branch integer; assignment record; allocation_count integer; BEGIN
SELECT kind, created_by INTO operation
FROM containermgmt.inventory_posting_operations
WHERE org_id=NEW.org_id AND operation_key=NEW.operation_key;
SELECT branch_id INTO invoice_branch FROM containermgmt.sales_invoices
WHERE org_id=NEW.org_id AND invoice_key=NEW.invoice_key;
SELECT branch_id INTO counter_branch FROM containermgmt.inventory_branch_counters
WHERE org_id=NEW.org_id AND id=NEW.counter_id AND NOT is_deleted;
SELECT branch_id, is_enabled INTO assignment
FROM containermgmt.inventory_staff_store_assignments
WHERE org_id=NEW.org_id AND user_id=NEW.created_by AND version=NEW.assignment_version;
SELECT COUNT(*) INTO allocation_count
FROM containermgmt.sales_collection_allocations
WHERE org_id=NEW.org_id AND collection_key=NEW.collection_key;
IF operation IS NULL OR operation.kind<>'sales.collection.post.v1'
 OR operation.created_by<>NEW.created_by THEN
 RAISE EXCEPTION 'Collection requires its exact stable posting operation'; END IF;
IF invoice_branch IS NULL OR invoice_branch<>NEW.branch_id
 OR counter_branch IS NULL OR counter_branch<>NEW.branch_id
 OR assignment IS NULL OR assignment.branch_id<>NEW.branch_id
 OR NOT assignment.is_enabled THEN
 RAISE EXCEPTION 'Collection branch, counter and staff assignment must remain exact'; END IF;
IF allocation_count < 1 THEN
 RAISE EXCEPTION 'Collection requires at least one exact allocation'; END IF;
RETURN NULL; END; $$"""
HEADER_GUARD_TRIGGER = """CREATE CONSTRAINT TRIGGER sales_collection_header_guard
AFTER INSERT ON containermgmt.sales_collections DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION containermgmt.check_sales_collection_header()"""


ALLOCATION_GUARD_FUNCTION = """CREATE OR REPLACE FUNCTION containermgmt.check_sales_collection_allocation()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE header record; invoice record; line record; binding record; hold record;
balance record; movement record; handover_operation record;
line_collected numeric; reservation_collected numeric;
BEGIN
-- Lock invoice line then reservation consistently to serialize cumulative caps.
PERFORM 1 FROM containermgmt.sales_invoice_lines
 WHERE org_id=NEW.org_id AND invoice_key=NEW.invoice_key AND line_key=NEW.line_key
 FOR UPDATE;
PERFORM 1 FROM containermgmt.sales_invoice_reservations
 WHERE org_id=NEW.org_id AND invoice_key=NEW.invoice_key AND line_key=NEW.line_key
 AND reservation_key=NEW.reservation_key FOR UPDATE;

SELECT invoice_key, branch_id, created_by INTO header
FROM containermgmt.sales_collections
WHERE org_id=NEW.org_id AND collection_key=NEW.collection_key;
SELECT invoice_key INTO invoice FROM containermgmt.sales_invoices
WHERE org_id=NEW.org_id AND invoice_key=NEW.invoice_key;
SELECT product_id, base_quantity, base_unit INTO line
FROM containermgmt.sales_invoice_lines
WHERE org_id=NEW.org_id AND invoice_key=NEW.invoice_key AND line_key=NEW.line_key;
SELECT quantity INTO binding FROM containermgmt.sales_invoice_reservations
WHERE org_id=NEW.org_id AND invoice_key=NEW.invoice_key AND line_key=NEW.line_key
AND reservation_key=NEW.reservation_key;
SELECT reservation.id, reservation.balance_id INTO hold
FROM containermgmt.inventory_stock_reservations reservation
WHERE reservation.org_id=NEW.org_id AND reservation.reservation_key=NEW.reservation_key;
SELECT branch_id, location_id, product_id, base_unit, tracking_policy, batch_key INTO balance
FROM containermgmt.inventory_stock_balances
WHERE org_id=NEW.org_id AND id=NEW.balance_id;
SELECT balance_id, reservation_id, operation_key, kind, on_hand_delta,
 reserved_delta, created_by INTO movement
FROM containermgmt.inventory_stock_movements
WHERE org_id=NEW.org_id AND balance_id=NEW.balance_id
AND operation_key=NEW.handover_operation_key;
SELECT kind, created_by INTO handover_operation
FROM containermgmt.inventory_posting_operations
WHERE org_id=NEW.org_id AND operation_key=NEW.handover_operation_key;

IF header IS NULL OR header.invoice_key<>NEW.invoice_key
 OR invoice IS NULL OR line IS NULL OR binding IS NULL OR hold IS NULL
 OR balance IS NULL OR movement IS NULL OR handover_operation IS NULL THEN
 RAISE EXCEPTION 'Collection allocation scope is unavailable'; END IF;
IF balance.branch_id<>header.branch_id OR balance.location_id<>NEW.location_id
 OR balance.product_id<>line.product_id OR balance.base_unit<>NEW.base_unit
 OR line.base_unit<>NEW.base_unit OR balance.batch_key IS DISTINCT FROM NEW.batch_key
 OR balance.tracking_policy='SERIAL' THEN
 RAISE EXCEPTION 'Collection allocation must use compatible non-serial branch stock'; END IF;
IF hold.balance_id<>NEW.balance_id OR movement.reservation_id<>hold.id
 OR movement.kind<>'HANDOVER' OR movement.on_hand_delta<>-NEW.quantity
 OR movement.reserved_delta<>-NEW.quantity
 OR movement.created_by<>header.created_by
 OR handover_operation.kind<>'inventory.handover.issue.v1'
 OR handover_operation.created_by<>header.created_by THEN
 RAISE EXCEPTION 'Collection allocation requires its exact HANDOVER movement'; END IF;

SELECT COALESCE(SUM(quantity),0) INTO line_collected
FROM containermgmt.sales_collection_allocations
WHERE org_id=NEW.org_id AND invoice_key=NEW.invoice_key AND line_key=NEW.line_key;
SELECT COALESCE(SUM(quantity),0) INTO reservation_collected
FROM containermgmt.sales_collection_allocations
WHERE org_id=NEW.org_id AND invoice_key=NEW.invoice_key
AND line_key=NEW.line_key AND reservation_key=NEW.reservation_key;
IF line_collected>line.base_quantity OR reservation_collected>binding.quantity THEN
 RAISE EXCEPTION 'Collection allocation exceeds eligible invoice or reservation quantity'; END IF;
RETURN NULL; END; $$"""
ALLOCATION_GUARD_TRIGGER = """CREATE CONSTRAINT TRIGGER sales_collection_allocation_guard
AFTER INSERT ON containermgmt.sales_collection_allocations DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION containermgmt.check_sales_collection_allocation()"""


COMMITTED_HANDOVER_FUNCTION = """CREATE OR REPLACE FUNCTION containermgmt.check_posted_sale_handover_collection()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE reservation uuid; committed boolean; matches integer; BEGIN
IF NEW.kind<>'HANDOVER' THEN RETURN NULL; END IF;
SELECT reservation_key INTO reservation
FROM containermgmt.inventory_stock_reservations
WHERE org_id=NEW.org_id AND id=NEW.reservation_id AND balance_id=NEW.balance_id;
IF reservation IS NULL THEN RETURN NULL; END IF;
SELECT EXISTS (SELECT 1 FROM containermgmt.sales_invoice_reservations
 WHERE org_id=NEW.org_id AND reservation_key=reservation) INTO committed;
IF NOT committed THEN RETURN NULL; END IF;
SELECT COUNT(*) INTO matches FROM containermgmt.sales_collection_allocations
WHERE org_id=NEW.org_id AND reservation_key=reservation
AND balance_id=NEW.balance_id AND handover_operation_key=NEW.operation_key
AND quantity=-NEW.on_hand_delta;
IF matches<>1 THEN
 RAISE EXCEPTION 'Posted-sale HANDOVER requires one exact collection allocation'; END IF;
RETURN NULL; END; $$"""
COMMITTED_HANDOVER_TRIGGER = """CREATE CONSTRAINT TRIGGER posted_sale_handover_collection_guard
AFTER INSERT ON containermgmt.inventory_stock_movements DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION containermgmt.check_posted_sale_handover_collection()"""


event.listen(SalesCollection.__table__, "after_create", DDL(IMMUTABLE_FUNCTION))
event.listen(SalesCollection.__table__, "after_create", DDL(immutable_trigger("sales_collections")))
event.listen(SalesCollection.__table__, "after_create", DDL(HEADER_GUARD_FUNCTION))
event.listen(SalesCollection.__table__, "after_create", DDL(HEADER_GUARD_TRIGGER))
event.listen(SalesCollectionAllocation.__table__, "after_create", DDL(IMMUTABLE_FUNCTION))
event.listen(
    SalesCollectionAllocation.__table__,
    "after_create",
    DDL(immutable_trigger("sales_collection_allocations")),
)
event.listen(SalesCollectionAllocation.__table__, "after_create", DDL(ALLOCATION_GUARD_FUNCTION))
event.listen(SalesCollectionAllocation.__table__, "after_create", DDL(ALLOCATION_GUARD_TRIGGER))
event.listen(StockMovement.__table__, "after_create", DDL(COMMITTED_HANDOVER_FUNCTION))
event.listen(StockMovement.__table__, "after_create", DDL(COMMITTED_HANDOVER_TRIGGER))
