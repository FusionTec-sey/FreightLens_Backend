"""Add immutable opening-policy snapshots without assigning rules to old balances."""
from sqlalchemy import text
from Model.db import engine
from Model.containermgmt.Inventory.StockLedger import (
    POLICY_CHECK, BALANCE_IDENTITY_FUNCTION, BALANCE_IDENTITY_TRIGGER,
)


def prepare_stock_unit_policy(conn):
    if not conn.execute(text("SELECT to_regclass('containermgmt.inventory_stock_balances')")).scalar():
        return
    conn.execute(text("ALTER TABLE containermgmt.inventory_stock_balances ADD COLUMN IF NOT EXISTS policy_config jsonb"))
    conn.execute(text("ALTER TABLE containermgmt.inventory_stock_balances ADD COLUMN IF NOT EXISTS quantity_step numeric(18,6)"))
    if not conn.execute(text("""SELECT 1 FROM pg_constraint
        WHERE conrelid = 'containermgmt.inventory_stock_balances'::regclass
        AND conname = 'ck_stock_balance_unit_policy'""")).scalar():
        conn.execute(text("ALTER TABLE containermgmt.inventory_stock_balances ADD CONSTRAINT ck_stock_balance_unit_policy CHECK (" + POLICY_CHECK + ")"))
    conn.execute(text(BALANCE_IDENTITY_FUNCTION))
    if not conn.execute(text("""SELECT 1 FROM pg_trigger
        WHERE tgrelid = 'containermgmt.inventory_stock_balances'::regclass
        AND tgname = 'stock_balance_identity' AND NOT tgisinternal""")).scalar():
        conn.execute(text(BALANCE_IDENTITY_TRIGGER))


def ensure_stock_unit_policy_schema():
    with engine.begin() as conn:
        prepare_stock_unit_policy(conn)
