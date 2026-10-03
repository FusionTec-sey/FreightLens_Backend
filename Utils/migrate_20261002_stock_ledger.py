"""Empty physical ledger; no legacy quantities or reservations are imported."""
from sqlalchemy import text
from Model.db import engine
from Model.containermgmt.Inventory.StockLedger import (
    StockBatch, StockBalance, StockReservation, StockMovement, IMMUTABLE_FUNCTION, IMMUTABLE_TRIGGER,
)


def prepare_product_stock_scope(connection):
    """Run before create_all: an existing products table needs the FK target key."""
    connection.execute(text("""
        DO $$ BEGIN
          IF to_regclass('containermgmt.products') IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM pg_constraint WHERE conrelid = to_regclass('containermgmt.products')
              AND conname = 'uq_product_id_org'
          ) THEN
            ALTER TABLE containermgmt.products ADD CONSTRAINT uq_product_id_org UNIQUE (id, org_id);
          END IF;
        END $$;
    """))


def ensure_stock_ledger_schema():
    with engine.begin() as conn:
        prepare_product_stock_scope(conn)
        for model in (StockBatch, StockBalance, StockReservation, StockMovement):
            model.__table__.create(conn, checkfirst=True)
        conn.execute(text("""
            DO $$ BEGIN
              IF NOT EXISTS (SELECT 1 FROM pg_constraint
                WHERE conrelid = 'containermgmt.inventory_stock_movements'::regclass
                  AND conname = 'ck_stock_movement_finite_deltas') THEN
                ALTER TABLE containermgmt.inventory_stock_movements
                  ADD CONSTRAINT ck_stock_movement_finite_deltas
                  CHECK (abs(on_hand_delta) < 1000000000000 AND abs(reserved_delta) < 1000000000000);
              END IF;
            END $$;
        """))
        conn.execute(text(IMMUTABLE_FUNCTION))
        exists = conn.execute(text("""
            SELECT 1 FROM pg_trigger WHERE tgrelid = 'containermgmt.inventory_stock_movements'::regclass
              AND tgname = 'stock_movement_immutable' AND NOT tgisinternal
        """)).scalar()
        if not exists:
            conn.execute(text(IMMUTABLE_TRIGGER))
