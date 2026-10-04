"""Enable source-bound receipt movements without importing legacy totals."""
from sqlalchemy import text
from Model.db import engine
from Model.containermgmt.Inventory.StockLedger import (MOVEMENT_KIND_CHECK, RECEIPT_FUNCTION,
    RECEIPT_TRIGGER, RECEIPT_TOTAL_FUNCTION, RECEIPT_TOTAL_TRIGGER)


def prepare_receipt_movement_schema(conn):
    definition = conn.execute(text("""SELECT pg_get_constraintdef(oid) FROM pg_constraint
            WHERE conrelid='containermgmt.inventory_stock_movements'::regclass
            AND conname='ck_stock_movement_kind'""")).scalar()
    if not definition or 'RECEIPT' not in definition:
        conn.execute(text('ALTER TABLE containermgmt.inventory_stock_movements DROP CONSTRAINT IF EXISTS ck_stock_movement_kind'))
        conn.execute(text('ALTER TABLE containermgmt.inventory_stock_movements ADD CONSTRAINT ck_stock_movement_kind CHECK (' + MOVEMENT_KIND_CHECK + ')'))
    for function, trigger, name in ((RECEIPT_FUNCTION, RECEIPT_TRIGGER, 'receipt_stock_movement_guard'),
            (RECEIPT_TOTAL_FUNCTION, RECEIPT_TOTAL_TRIGGER, 'receipt_stock_total_guard')):
        conn.execute(text(function))
        if not conn.execute(text("""SELECT 1 FROM pg_trigger WHERE
            tgrelid='containermgmt.inventory_stock_movements'::regclass
            AND tgname=:name AND NOT tgisinternal"""), {'name': name}).scalar():
            conn.execute(text(trigger))


def ensure_receipt_movement_schema():
    with engine.begin() as conn:
        conn.execute(text("SET LOCAL lock_timeout = '5s'"))
        prepare_receipt_movement_schema(conn)
