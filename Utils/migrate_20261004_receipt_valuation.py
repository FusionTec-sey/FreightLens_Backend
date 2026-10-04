"""Extend the existing valuation stream for exact source-bound receipts."""
from sqlalchemy import text
from sqlalchemy.schema import AddConstraint
from Model.db import engine
from Model.containermgmt.Inventory.Valuation import (
    InventoryValuation, CHARGE_FUNCTION, RECEIPT_FUNCTION, RECEIPT_TRIGGER)


def prepare_receipt_valuation_schema(conn):
    if not conn.execute(text(
            "SELECT to_regclass('containermgmt.inventory_valuations')")).scalar():
        return
    conn.execute(text("SET LOCAL lock_timeout = '5s'"))
    existing = set(conn.execute(text("""SELECT conname FROM pg_constraint
        WHERE conrelid='containermgmt.inventory_valuations'::regclass""")).scalars())
    constraints = {item.name: item for item in InventoryValuation.__table__.constraints}
    for name in ('ck_valuation_quantity_v3', 'ck_valuation_kind_v2'):
        replacement = {
            'ck_valuation_quantity_v3': 'ck_valuation_quantity_v4',
            'ck_valuation_kind_v2': 'ck_valuation_kind_v3',
        }[name]
        current = name if name in constraints else replacement
        if name not in existing and current not in existing:
            conn.execute(AddConstraint(constraints[current]))
    for name in ('ck_valuation_quantity', 'ck_valuation_quantity_v2', 'ck_valuation_kind'):
        if name in existing:
            conn.execute(text(
                f'ALTER TABLE containermgmt.inventory_valuations DROP CONSTRAINT {name}'))
    conn.execute(text('DROP INDEX IF EXISTS containermgmt.uq_valuation_opening_source'))
    next(index for index in InventoryValuation.__table__.indexes
        if index.name == 'uq_valuation_physical_source').create(conn, checkfirst=True)
    # Refresh the existing charge guard as receipts are now valid physical
    # allocation sources in the same ledger.
    conn.execute(text(CHARGE_FUNCTION))
    conn.execute(text(RECEIPT_FUNCTION))
    if not conn.execute(text("""SELECT 1 FROM pg_trigger WHERE
            tgrelid='containermgmt.inventory_valuations'::regclass
            AND tgname='receipt_valuation_guard' AND NOT tgisinternal""")).scalar():
        conn.execute(text(RECEIPT_TRIGGER))


def ensure_receipt_valuation_schema():
    with engine.begin() as conn:
        prepare_receipt_valuation_schema(conn)
