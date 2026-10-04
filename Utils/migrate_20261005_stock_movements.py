"""Add the internal reservation handover and matching valuation issue contract."""
from sqlalchemy import text
from sqlalchemy.schema import AddConstraint

from Model.db import engine
from Model.containermgmt.Inventory.StockLedger import (
    HANDOVER_FUNCTION,
    HANDOVER_TRIGGER,
    MOVEMENT_KIND_CHECK,
)
from Model.containermgmt.Inventory.Valuation import (
    ISSUE_FUNCTION,
    ISSUE_TRIGGER,
    InventoryValuation,
)


def prepare_inventory_handover_schema(conn):
    if not conn.execute(text(
            "SELECT to_regclass('containermgmt.inventory_stock_movements')")).scalar():
        return
    conn.execute(text("SET LOCAL lock_timeout = '5s'"))
    movement_definition = conn.execute(text("""SELECT pg_get_constraintdef(oid)
        FROM pg_constraint
        WHERE conrelid='containermgmt.inventory_stock_movements'::regclass
          AND conname='ck_stock_movement_kind'""")).scalar()
    if not movement_definition or "HANDOVER" not in movement_definition:
        conn.execute(text("ALTER TABLE containermgmt.inventory_stock_movements "
                          "DROP CONSTRAINT IF EXISTS ck_stock_movement_kind"))
        conn.execute(text("ALTER TABLE containermgmt.inventory_stock_movements "
                          "ADD CONSTRAINT ck_stock_movement_kind CHECK (" +
                          MOVEMENT_KIND_CHECK + ")"))
    conn.execute(text(HANDOVER_FUNCTION))
    if not conn.execute(text("""SELECT 1 FROM pg_trigger WHERE
        tgrelid='containermgmt.inventory_stock_movements'::regclass
        AND tgname='handover_stock_movement_guard' AND NOT tgisinternal""")).scalar():
        conn.execute(text(HANDOVER_TRIGGER))

    if not conn.execute(text(
            "SELECT to_regclass('containermgmt.inventory_valuations')")).scalar():
        return
    existing = set(conn.execute(text("""SELECT conname FROM pg_constraint
        WHERE conrelid='containermgmt.inventory_valuations'::regclass""")).scalars())
    constraints = {item.name: item for item in InventoryValuation.__table__.constraints}
    for name in ("ck_valuation_quantity_v4", "ck_valuation_kind_v3",
                 "ck_valuation_value_v2"):
        if name not in existing:
            conn.execute(AddConstraint(constraints[name]))
    for name in ("ck_valuation_quantity", "ck_valuation_quantity_v2",
                 "ck_valuation_quantity_v3", "ck_valuation_kind",
                 "ck_valuation_kind_v2", "ck_valuation_value"):
        if name in existing:
            conn.execute(text("ALTER TABLE containermgmt.inventory_valuations "
                              f"DROP CONSTRAINT {name}"))
    index_definition = conn.execute(text("""SELECT pg_get_indexdef(indexrelid)
        FROM pg_index WHERE indexrelid=
        to_regclass('containermgmt.uq_valuation_physical_source')""")).scalar()
    if not index_definition or "ISSUE" not in index_definition:
        conn.execute(text(
            "DROP INDEX IF EXISTS containermgmt.uq_valuation_physical_source"))
        next(index for index in InventoryValuation.__table__.indexes
             if index.name == "uq_valuation_physical_source").create(conn)
    conn.execute(text(ISSUE_FUNCTION))
    if not conn.execute(text("""SELECT 1 FROM pg_trigger WHERE
        tgrelid='containermgmt.inventory_valuations'::regclass
        AND tgname='issue_valuation_guard' AND NOT tgisinternal""")).scalar():
        conn.execute(text(ISSUE_TRIGGER))


def ensure_inventory_handover_schema():
    with engine.begin() as conn:
        prepare_inventory_handover_schema(conn)

