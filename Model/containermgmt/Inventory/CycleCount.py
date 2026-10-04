"""Cycle-count planning and blind counting (T33A). Creates count records only.

No stock is posted, frozen, valued or reconciled here. Counted entries and the
provisional discrepancies derived from them are immutable: a correction is a new
recount round, never an edit, so the audit trail of what a counter actually wrote
survives. Movement-aware reconciliation and any adjustment remain T09/T33.
"""
from sqlalchemy import (Column, Integer, String, Date, Numeric, DateTime, UniqueConstraint,
                        ForeignKeyConstraint, CheckConstraint, Index, DDL, event)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from Model.db import Base
from Model.mixins import OrgMixin, AuditMixin

PLAN_STATES = "('DRAFT','ACTIVE','CLOSED')"
SESSION_STATES = "('ASSIGNED','IN_PROGRESS','SUBMITTED','REVIEWED','CANCELLED')"
CADENCES = "('ANNUAL','QUARTERLY','MONTHLY')"


class CountPlan(OrgMixin, AuditMixin, Base):
    """An annual counting programme for one branch."""
    __tablename__ = "inventory_count_plans"
    __table_args__ = (
        ForeignKeyConstraint(["branch_id", "org_id"],
            ["containermgmt.inventory_branches.id", "containermgmt.inventory_branches.org_id"],
            name="fk_count_plan_branch"),
        UniqueConstraint("org_id", "plan_key", name="uq_count_plan_key"),
        UniqueConstraint("org_id", "branch_id", "code", name="uq_count_plan_code"),
        UniqueConstraint("id", "org_id", name="uq_count_plan_id_org"),
        CheckConstraint(f"state IN {PLAN_STATES}", name="ck_count_plan_state"),
        CheckConstraint("year BETWEEN 2000 AND 2100", name="ck_count_plan_year"),
        CheckConstraint("code ~ '^[A-Z0-9][A-Z0-9_-]{0,31}$'", name="ck_count_plan_code"),
        CheckConstraint("created_by IS NOT NULL AND NOT is_deleted AND deleted_at IS NULL", name="ck_count_plan_audit"),
        {"schema": "containermgmt"},
    )
    id = Column(Integer, primary_key=True)
    plan_key = Column(UUID(as_uuid=True), nullable=False)
    branch_id = Column(Integer, nullable=False, index=True)
    code = Column(String(32), nullable=False)
    name = Column(String(160), nullable=False)
    year = Column(Integer, nullable=False)
    state = Column(String(16), nullable=False, default="DRAFT")


class CountScope(OrgMixin, AuditMixin, Base):
    """One product-location line a plan covers, with its due date and cadence."""
    __tablename__ = "inventory_count_scopes"
    __table_args__ = (
        ForeignKeyConstraint(["plan_id", "org_id"],
            ["containermgmt.inventory_count_plans.id", "containermgmt.inventory_count_plans.org_id"],
            name="fk_count_scope_plan"),
        ForeignKeyConstraint(["product_id", "org_id"],
            ["containermgmt.products.id", "containermgmt.products.org_id"], name="fk_count_scope_product"),
        ForeignKeyConstraint(["location_id", "branch_id", "org_id"],
            ["containermgmt.stock_locations.id", "containermgmt.stock_locations.branch_id",
             "containermgmt.stock_locations.org_id"], name="fk_count_scope_location"),
        UniqueConstraint("org_id", "plan_id", "product_id", "location_id", name="uq_count_scope_line"),
        CheckConstraint(f"cadence IN {CADENCES}", name="ck_count_scope_cadence"),
        CheckConstraint("created_by IS NOT NULL AND NOT is_deleted AND deleted_at IS NULL", name="ck_count_scope_audit"),
        Index("ix_count_scope_due", "org_id", "plan_id", "due_on"),
        {"schema": "containermgmt"},
    )
    id = Column(Integer, primary_key=True)
    plan_id = Column(Integer, nullable=False, index=True)
    product_id = Column(Integer, nullable=False)
    branch_id = Column(Integer, nullable=False)
    location_id = Column(Integer, nullable=False)
    cadence = Column(String(16), nullable=False, default="ANNUAL")
    due_on = Column(Date, nullable=False)


class CountSession(OrgMixin, AuditMixin, Base):
    """One assignment of a location's scope to a counter, as an immutable round.

    A recount is a new row with round + 1 and parent_session_id set, so earlier
    rounds and their entries are never rewritten.
    """
    __tablename__ = "inventory_count_sessions"
    __table_args__ = (
        ForeignKeyConstraint(["plan_id", "org_id"],
            ["containermgmt.inventory_count_plans.id", "containermgmt.inventory_count_plans.org_id"],
            name="fk_count_session_plan"),
        ForeignKeyConstraint(["location_id", "branch_id", "org_id"],
            ["containermgmt.stock_locations.id", "containermgmt.stock_locations.branch_id",
             "containermgmt.stock_locations.org_id"], name="fk_count_session_location"),
        ForeignKeyConstraint(["parent_session_id", "org_id"],
            ["containermgmt.inventory_count_sessions.id", "containermgmt.inventory_count_sessions.org_id"],
            name="fk_count_session_parent"),
        UniqueConstraint("org_id", "session_key", name="uq_count_session_key"),
        UniqueConstraint("id", "org_id", name="uq_count_session_id_org"),
        CheckConstraint(f"state IN {SESSION_STATES}", name="ck_count_session_state"),
        CheckConstraint("round >= 1", name="ck_count_session_round"),
        CheckConstraint("assignee_id IS NOT NULL", name="ck_count_session_assignee"),
        CheckConstraint("created_by IS NOT NULL AND NOT is_deleted AND deleted_at IS NULL", name="ck_count_session_audit"),
        Index("ix_count_session_assignee", "org_id", "assignee_id", "state"),
        Index("ix_count_session_plan", "org_id", "plan_id", "state"),
        {"schema": "containermgmt"},
    )
    id = Column(Integer, primary_key=True)
    session_key = Column(UUID(as_uuid=True), nullable=False)
    plan_id = Column(Integer, nullable=False)
    branch_id = Column(Integer, nullable=False)
    location_id = Column(Integer, nullable=False)
    assignee_id = Column(Integer, nullable=False)
    state = Column(String(16), nullable=False, default="ASSIGNED")
    round = Column(Integer, nullable=False, default=1)
    parent_session_id = Column(Integer, nullable=True)
    submitted_at = Column(DateTime(timezone=True), nullable=True)


class CountEntry(OrgMixin, AuditMixin, Base):
    """What a counter actually wrote. Immutable; exact decimal quantity and unit."""
    __tablename__ = "inventory_count_entries"
    __table_args__ = (
        ForeignKeyConstraint(["session_id", "org_id"],
            ["containermgmt.inventory_count_sessions.id", "containermgmt.inventory_count_sessions.org_id"],
            name="fk_count_entry_session"),
        ForeignKeyConstraint(["product_id", "org_id"],
            ["containermgmt.products.id", "containermgmt.products.org_id"], name="fk_count_entry_product"),
        ForeignKeyConstraint(["location_id", "branch_id", "org_id"],
            ["containermgmt.stock_locations.id", "containermgmt.stock_locations.branch_id",
             "containermgmt.stock_locations.org_id"], name="fk_count_entry_location"),
        ForeignKeyConstraint(["org_id", "operation_key"],
            ["containermgmt.inventory_posting_operations.org_id", "containermgmt.inventory_posting_operations.operation_key"],
            name="fk_count_entry_operation", deferrable=True, initially="DEFERRED"),
        UniqueConstraint("org_id", "session_id", "product_id", "location_id", name="uq_count_entry_line"),
        CheckConstraint("counted_quantity >= 0 AND base_quantity >= 0", name="ck_count_entry_quantity"),
        CheckConstraint("jsonb_typeof(policy) = 'object'", name="ck_count_entry_policy"),
        CheckConstraint("created_by IS NOT NULL AND NOT is_deleted AND deleted_at IS NULL", name="ck_count_entry_audit"),
        Index("ix_count_entry_session", "org_id", "session_id"),
        Index("ix_count_entry_operation", "org_id", "operation_key"),
        {"schema": "containermgmt"},
    )
    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, nullable=False)
    product_id = Column(Integer, nullable=False)
    branch_id = Column(Integer, nullable=False)
    location_id = Column(Integer, nullable=False)
    counted_quantity = Column(Numeric(18, 6), nullable=False)
    unit = Column(String(50), nullable=False)
    base_quantity = Column(Numeric(18, 6), nullable=False)
    base_unit = Column(String(50), nullable=False)
    policy = Column(JSONB, nullable=False)
    operation_key = Column(UUID(as_uuid=True), nullable=False)


class CountDiscrepancy(OrgMixin, AuditMixin, Base):
    """Provisional difference captured at submission, never shown to the counter.

    expected_base and balance_version are a snapshot taken when the session was
    submitted. Stock can move before review, so this is explicitly provisional
    and is not a reconciliation.
    """
    __tablename__ = "inventory_count_discrepancies"
    __table_args__ = (
        ForeignKeyConstraint(["session_id", "org_id"],
            ["containermgmt.inventory_count_sessions.id", "containermgmt.inventory_count_sessions.org_id"],
            name="fk_count_discrepancy_session"),
        ForeignKeyConstraint(["product_id", "org_id"],
            ["containermgmt.products.id", "containermgmt.products.org_id"], name="fk_count_discrepancy_product"),
        UniqueConstraint("org_id", "session_id", "product_id", "location_id", name="uq_count_discrepancy_line"),
        UniqueConstraint("id", "org_id", name="uq_count_discrepancy_id_org"),
        CheckConstraint("created_by IS NOT NULL AND NOT is_deleted AND deleted_at IS NULL", name="ck_count_discrepancy_audit"),
        Index("ix_count_discrepancy_session", "org_id", "session_id"),
        {"schema": "containermgmt"},
    )
    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, nullable=False)
    product_id = Column(Integer, nullable=False)
    location_id = Column(Integer, nullable=False)
    counted_base = Column(Numeric(18, 6), nullable=False)
    expected_base = Column(Numeric(18, 6), nullable=False)
    difference_base = Column(Numeric(18, 6), nullable=False)
    base_unit = Column(String(50), nullable=False)
    balance_version = Column(Integer, nullable=True)


class CountDiscrepancyReview(OrgMixin, AuditMixin, Base):
    """The recorded decision on one provisional discrepancy.

    Append-only, exactly as manager_case_decisions is to manager_cases, so the
    snapshot stays immutable and reviewed state is derived from this row's
    existence rather than stored on the snapshot. Deciding a discrepancy records
    a judgement only: it authorises no stock adjustment.
    """
    __tablename__ = "inventory_count_discrepancy_reviews"
    __table_args__ = (
        ForeignKeyConstraint(["discrepancy_id", "org_id"],
            ["containermgmt.inventory_count_discrepancies.id", "containermgmt.inventory_count_discrepancies.org_id"],
            name="fk_count_review_discrepancy"),
        ForeignKeyConstraint(["org_id", "case_key"],
            ["containermgmt.manager_cases.org_id", "containermgmt.manager_cases.case_key"],
            name="fk_count_review_case"),
        UniqueConstraint("org_id", "discrepancy_id", name="uq_count_review_once"),
        UniqueConstraint("org_id", "case_key", name="uq_count_review_case"),
        CheckConstraint("outcome IN ('ACCEPTED','RECOUNT_REQUIRED','REJECTED')", name="ck_count_review_outcome"),
        CheckConstraint("created_by IS NOT NULL AND NOT is_deleted AND deleted_at IS NULL", name="ck_count_review_audit"),
        {"schema": "containermgmt"},
    )
    id = Column(Integer, primary_key=True)
    discrepancy_id = Column(Integer, nullable=False, index=True)
    case_key = Column(UUID(as_uuid=True), nullable=False)
    outcome = Column(String(24), nullable=False)
    reason = Column(String(1000), nullable=False)


TABLES = (CountPlan.__table__, CountScope.__table__, CountSession.__table__,
          CountEntry.__table__, CountDiscrepancy.__table__, CountDiscrepancyReview.__table__)

# Counted history is append-only: a correction is a new recount round, and a
# decision is a new review row.
IMMUTABLE_TABLES = ("inventory_count_entries", "inventory_count_discrepancies",
                    "inventory_count_discrepancy_reviews")

FUNCTION = """CREATE OR REPLACE FUNCTION containermgmt.reject_count_history_change()
RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
RAISE EXCEPTION 'Counted history is immutable; open a new recount round'; END; $$"""


def trigger(table):
    return f"""CREATE TRIGGER count_history_immutable BEFORE UPDATE OR DELETE
    ON containermgmt.{table} FOR EACH ROW
    EXECUTE FUNCTION containermgmt.reject_count_history_change()"""


for name in IMMUTABLE_TABLES:
    table = next(item for item in TABLES if item.name == name)
    event.listen(table, "after_create", DDL(FUNCTION))
    event.listen(table, "after_create", DDL(trigger(name)))
