"""Split future stock buckets by explicit lot. Existing untracked rows stay intact."""
from sqlalchemy import text
from Model.db import engine
from Model.containermgmt.Inventory.StockLedger import (
    StockBatch, StockBalance, StockReservation, BATCH_CONTRACT, BATCH_IMMUTABLE_FUNCTION, BATCH_IMMUTABLE_TRIGGER,
    BALANCE_IDENTITY_FUNCTION,
)


def prepare_stock_batches(conn):
    if not conn.execute(text("SELECT to_regclass('containermgmt.inventory_stock_balances')")).scalar():
        return
    StockBatch.__table__.create(conn, checkfirst=True)
    conn.execute(text("ALTER TABLE containermgmt.inventory_stock_balances ADD COLUMN IF NOT EXISTS batch_key uuid"))
    # Replace the old bucket key atomically with separate NULL/non-NULL unique indexes.
    for index in StockBalance.__table__.indexes:
        if index.name in ("uq_stock_balance_untracked", "uq_stock_balance_batch", "ix_stock_balance_batch_scope"):
            index.create(conn, checkfirst=True)
    conn.execute(text("ALTER TABLE containermgmt.inventory_stock_balances DROP CONSTRAINT IF EXISTS uq_stock_balance_bucket"))
    conn.execute(text("ALTER TABLE containermgmt.inventory_stock_balances DROP CONSTRAINT IF EXISTS ck_stock_balance_contract"))
    constraints = {
        "ck_stock_balance_batch_contract": "CHECK (" + BATCH_CONTRACT + ")",
        "fk_stock_balance_batch_scope": "FOREIGN KEY (batch_key, product_id, org_id) REFERENCES containermgmt.inventory_stock_batches(batch_key, product_id, org_id)",
    }
    for name, definition in constraints.items():
        if not conn.execute(text("""SELECT 1 FROM pg_constraint WHERE
            conrelid = 'containermgmt.inventory_stock_balances'::regclass AND conname = :name"""), {"name": name}).scalar():
            conn.execute(text(f"ALTER TABLE containermgmt.inventory_stock_balances ADD CONSTRAINT {name} {definition}"))
    conn.execute(text(BALANCE_IDENTITY_FUNCTION))
    if conn.execute(text("SELECT to_regclass('containermgmt.inventory_stock_reservations')")).scalar():
        for index in StockReservation.__table__.indexes:
            if index.name == "ix_stock_reservation_source":
                index.create(conn, checkfirst=True)
    conn.execute(text(BATCH_IMMUTABLE_FUNCTION))
    if not conn.execute(text("""SELECT 1 FROM pg_trigger
        WHERE tgrelid = 'containermgmt.inventory_stock_batches'::regclass
        AND tgname = 'stock_batch_immutable' AND NOT tgisinternal""")).scalar():
        conn.execute(text(BATCH_IMMUTABLE_TRIGGER))


def ensure_stock_batches_schema():
    with engine.begin() as conn:
        prepare_stock_batches(conn)
