"""Create the bounded T18 return, quarantine and credit-note contract."""
from sqlalchemy import text
from sqlalchemy.schema import AddConstraint

from Model.db import engine
from Model.containermgmt.Inventory.StockLedger import MOVEMENT_KIND_CHECK, StockMovement
from Model.containermgmt.Inventory.Valuation import InventoryValuation
from Model.containermgmt.Orders.SalesReturn import (
    ALLOCATION_GUARD_FUNCTION,
    ALLOCATION_GUARD_TRIGGER,
    CLAIM_GUARD_FUNCTION,
    CLAIM_GUARD_TRIGGER,
    CREDIT_GUARD_FUNCTION,
    CREDIT_GUARD_TRIGGER,
    IMMUTABLE_FUNCTION,
    LINEAGE_GUARD_FUNCTION,
    LINEAGE_GUARD_TRIGGER,
    MODELS,
    MONEY_CHILD_GUARD_FUNCTION,
    DEBT_CHILD_GUARD_TRIGGER,
    CREDIT_CHILD_GUARD_TRIGGER,
    RETURN_MOVEMENT_GUARD_FUNCTION,
    RETURN_MOVEMENT_GUARD_TRIGGER,
    RETURN_VALUATION_GUARD_FUNCTION,
    RETURN_VALUATION_GUARD_TRIGGER,
    SalesCreditNote,
    SalesCreditNoteLine,
    SalesInvoiceDebtApplication,
    CustomerCreditLiabilityEntry,
    SalesReturnAllocation,
    SalesReturnClaim,
    immutable_trigger,
)


def _trigger(conn, table: str, name: str, ddl: str) -> None:
    exists = conn.execute(text(
        "SELECT 1 FROM pg_trigger WHERE tgrelid=CAST(:table AS regclass) "
        "AND tgname=:name AND NOT tgisinternal"
    ), {"table": f"containermgmt.{table}", "name": name}).scalar()
    if not exists:
        conn.execute(text(ddl))


def _replace_return_constraints(conn) -> None:
    movement_definition = conn.execute(text("""SELECT pg_get_constraintdef(oid)
        FROM pg_constraint
        WHERE conrelid='containermgmt.inventory_stock_movements'::regclass
          AND conname='ck_stock_movement_kind'""")).scalar()
    if not movement_definition or "RETURN" not in movement_definition:
        conn.execute(text("ALTER TABLE containermgmt.inventory_stock_movements "
                          "DROP CONSTRAINT IF EXISTS ck_stock_movement_kind"))
        conn.execute(text("ALTER TABLE containermgmt.inventory_stock_movements "
                          "ADD CONSTRAINT ck_stock_movement_kind CHECK (" +
                          MOVEMENT_KIND_CHECK + ")"))

    constraints = {item.name: item for item in InventoryValuation.__table__.constraints}
    for name in ("ck_valuation_kind_v3", "ck_valuation_value_v2"):
        definition = conn.execute(text("""SELECT pg_get_constraintdef(oid)
            FROM pg_constraint
            WHERE conrelid='containermgmt.inventory_valuations'::regclass
              AND conname=:name"""), {"name": name}).scalar()
        if not definition or "RETURN" not in definition:
            conn.execute(text("ALTER TABLE containermgmt.inventory_valuations "
                              f"DROP CONSTRAINT IF EXISTS {name}"))
            conn.execute(AddConstraint(constraints[name]))

    index_definition = conn.execute(text("""SELECT pg_get_indexdef(indexrelid)
        FROM pg_index WHERE indexrelid=
        to_regclass('containermgmt.uq_valuation_physical_source')""")).scalar()
    if not index_definition or "RETURN" not in index_definition:
        conn.execute(text(
            "DROP INDEX IF EXISTS containermgmt.uq_valuation_physical_source"))
        next(index for index in InventoryValuation.__table__.indexes
             if index.name == "uq_valuation_physical_source").create(conn)


def ensure_sales_returns_schema() -> None:
    """Replay-safe schema only; creates no claim, stock, credit or financial data."""

    with engine.begin() as conn:
        conn.execute(text("SET LOCAL lock_timeout = '5s'"))
        for model in MODELS:
            model.__table__.create(conn, checkfirst=True)

        _replace_return_constraints(conn)

        conn.execute(text(IMMUTABLE_FUNCTION))
        for model in MODELS:
            _trigger(
                conn,
                model.__tablename__,
                f"{model.__tablename__}_immutable",
                immutable_trigger(model.__tablename__),
            )

        guarded = (
            (SalesReturnClaim.__tablename__, "sales_return_claim_guard",
             CLAIM_GUARD_FUNCTION, CLAIM_GUARD_TRIGGER),
            (SalesReturnAllocation.__tablename__, "sales_return_allocation_guard",
             ALLOCATION_GUARD_FUNCTION, ALLOCATION_GUARD_TRIGGER),
            (SalesCreditNote.__tablename__, "sales_credit_note_guard",
             CREDIT_GUARD_FUNCTION, CREDIT_GUARD_TRIGGER),
            (SalesCreditNoteLine.__tablename__, "sales_return_lineage_guard",
             LINEAGE_GUARD_FUNCTION, LINEAGE_GUARD_TRIGGER),
            (SalesInvoiceDebtApplication.__tablename__, "sales_return_debt_child_guard",
             MONEY_CHILD_GUARD_FUNCTION, DEBT_CHILD_GUARD_TRIGGER),
            (CustomerCreditLiabilityEntry.__tablename__, "customer_credit_return_child_guard",
             MONEY_CHILD_GUARD_FUNCTION, CREDIT_CHILD_GUARD_TRIGGER),
            (StockMovement.__tablename__, "return_stock_movement_guard",
             RETURN_MOVEMENT_GUARD_FUNCTION, RETURN_MOVEMENT_GUARD_TRIGGER),
            (InventoryValuation.__tablename__, "return_valuation_guard",
             RETURN_VALUATION_GUARD_FUNCTION, RETURN_VALUATION_GUARD_TRIGGER),
        )
        for table, name, function, trigger in guarded:
            conn.execute(text(function))
            _trigger(conn, table, name, trigger)
