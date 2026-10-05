"""Add immutable exact serial movement history for T09 handovers."""
from sqlalchemy import text

from Model.db import engine
from Model.containermgmt.Inventory.StockSerial import (
    MOVEMENT_SCOPE_FUNCTION,
    MOVEMENT_SCOPE_TRIGGER,
    MOVEMENT_TOTAL_FUNCTION,
    MOVEMENT_TOTAL_TRIGGER,
    SERIAL_MOVEMENT_TOTAL_TRIGGER,
    SERIAL_FUNCTION,
    StockSerialMovement,
    serial_trigger,
)


def _trigger_exists(conn, table, name):
    return conn.execute(text("""SELECT 1 FROM pg_trigger
        WHERE tgrelid=to_regclass(:table) AND tgname=:name
          AND NOT tgisinternal"""), {"table": table, "name": name}).scalar()


def prepare_stock_serial_handover_schema(conn):
    if not conn.execute(text(
            "SELECT to_regclass('containermgmt.inventory_stock_movements')")).scalar():
        return
    if not conn.execute(text(
            "SELECT to_regclass('containermgmt.inventory_stock_serial_identities')")).scalar():
        return
    conn.execute(text("SET LOCAL lock_timeout = '5s'"))
    StockSerialMovement.__table__.create(conn, checkfirst=True)
    conn.execute(text(SERIAL_FUNCTION))
    if not _trigger_exists(conn,
            "containermgmt.inventory_stock_serial_movements",
            "serial_record_protected"):
        conn.execute(text(serial_trigger("inventory_stock_serial_movements")))
    conn.execute(text(MOVEMENT_SCOPE_FUNCTION))
    if not _trigger_exists(conn,
            "containermgmt.inventory_stock_serial_movements",
            "serial_movement_scope"):
        conn.execute(text(MOVEMENT_SCOPE_TRIGGER))
    conn.execute(text(MOVEMENT_TOTAL_FUNCTION))
    if not _trigger_exists(conn,
            "containermgmt.inventory_stock_movements",
            "serial_handover_total_guard"):
        conn.execute(text(MOVEMENT_TOTAL_TRIGGER))
    if not _trigger_exists(conn,
            "containermgmt.inventory_stock_serial_movements",
            "serial_movement_total_guard"):
        conn.execute(text(SERIAL_MOVEMENT_TOTAL_TRIGGER))


def ensure_stock_serial_handover_schema():
    with engine.begin() as conn:
        prepare_stock_serial_handover_schema(conn)
