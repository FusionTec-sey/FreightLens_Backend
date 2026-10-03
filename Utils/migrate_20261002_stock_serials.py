"""Empty serial registry/positions; no serial numbers are inferred or seeded."""
from sqlalchemy import text
from Model.db import engine
from Model.containermgmt.Inventory.StockLedger import BATCH_CONTRACT
from Model.containermgmt.Inventory.StockSerial import (StockSerialIdentity, StockSerialPosition, SERIAL_FUNCTION,
    serial_trigger, POSITION_SCOPE_FUNCTION, POSITION_SCOPE_TRIGGER)


def prepare_stock_serial_scope(conn):
    if not conn.execute(text("SELECT to_regclass('containermgmt.inventory_stock_balances')")).scalar():
        return
    if not conn.execute(text("""SELECT 1 FROM pg_constraint WHERE conrelid = 'containermgmt.inventory_stock_balances'::regclass
        AND conname = 'uq_stock_balance_product_scope'""")).scalar():
        conn.execute(text("ALTER TABLE containermgmt.inventory_stock_balances ADD CONSTRAINT uq_stock_balance_product_scope UNIQUE (id, product_id, org_id)"))


def prepare_stock_serials(conn):
    if not conn.execute(text("SELECT to_regclass('containermgmt.inventory_stock_balances')")).scalar():
        return
    prepare_stock_serial_scope(conn)
    _ensure_tables(conn)


def _ensure_tables(conn):
    definition = conn.execute(text("""SELECT pg_get_constraintdef(oid) FROM pg_constraint
        WHERE conrelid = 'containermgmt.inventory_stock_balances'::regclass
        AND conname = 'ck_stock_balance_batch_contract'""")).scalar()
    if not definition or "SERIAL" not in definition:
        conn.execute(text("ALTER TABLE containermgmt.inventory_stock_balances DROP CONSTRAINT IF EXISTS ck_stock_balance_batch_contract"))
        conn.execute(text("ALTER TABLE containermgmt.inventory_stock_balances ADD CONSTRAINT ck_stock_balance_batch_contract CHECK (" + BATCH_CONTRACT + ")"))
    conn.execute(text(SERIAL_FUNCTION))
    for model in (StockSerialIdentity, StockSerialPosition):
        model.__table__.create(conn, checkfirst=True)
        if not conn.execute(text("SELECT 1 FROM pg_trigger WHERE tgrelid = to_regclass(:table) AND tgname = 'serial_record_protected' AND NOT tgisinternal"),
            {"table": f"containermgmt.{model.__tablename__}"}).scalar():
            conn.execute(text(serial_trigger(model.__tablename__)))
    conn.execute(text(POSITION_SCOPE_FUNCTION))
    if not conn.execute(text("""SELECT 1 FROM pg_trigger WHERE tgrelid = 'containermgmt.inventory_stock_serial_positions'::regclass
        AND tgname = 'serial_position_scope' AND NOT tgisinternal""")).scalar():
        conn.execute(text(POSITION_SCOPE_TRIGGER))


def ensure_stock_serials_schema():
    with engine.begin() as conn:
        prepare_stock_serials(conn)
