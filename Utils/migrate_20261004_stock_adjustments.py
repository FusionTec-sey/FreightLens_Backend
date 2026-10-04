"""Enable only independently reviewed stock-adjustment movements."""
from sqlalchemy import text

from Model.db import engine
from Model.containermgmt.Inventory.StockLedger import (
    ADJUSTMENT_FUNCTION,
    ADJUSTMENT_TRIGGER,
    MOVEMENT_KIND_CHECK,
)


def prepare_stock_adjustment_schema(conn):
    definition = conn.execute(text("""SELECT pg_get_constraintdef(oid) FROM pg_constraint
        WHERE conrelid='containermgmt.inventory_stock_movements'::regclass
        AND conname='ck_stock_movement_kind'""")).scalar()
    if not definition or "ADJUSTMENT" not in definition:
        conn.execute(text("ALTER TABLE containermgmt.inventory_stock_movements "
                          "DROP CONSTRAINT IF EXISTS ck_stock_movement_kind"))
        conn.execute(text("ALTER TABLE containermgmt.inventory_stock_movements "
                          "ADD CONSTRAINT ck_stock_movement_kind CHECK (" + MOVEMENT_KIND_CHECK + ")"))
    conn.execute(text(ADJUSTMENT_FUNCTION))
    if not conn.execute(text("""SELECT 1 FROM pg_trigger WHERE
        tgrelid='containermgmt.inventory_stock_movements'::regclass
        AND tgname='reviewed_stock_adjustment_guard' AND NOT tgisinternal""")).scalar():
        conn.execute(text(ADJUSTMENT_TRIGGER))


def ensure_stock_adjustment_schema():
    with engine.begin() as conn:
        conn.execute(text("SET LOCAL lock_timeout = '5s'"))
        prepare_stock_adjustment_schema(conn)

