"""Extend the one valuation stream without rewriting historical financial values."""
from sqlalchemy import text
from sqlalchemy.schema import AddConstraint
from Model.db import engine
from Model.containermgmt.Inventory.Valuation import InventoryValuation, CHARGE_FUNCTION, CHARGE_TRIGGER


def prepare_valuation_charges(conn):
    if not conn.execute(text("SELECT to_regclass('containermgmt.inventory_valuations')")).scalar(): return
    conn.execute(text("SET LOCAL lock_timeout = '5s'"))
    conn.execute(text("ALTER TABLE containermgmt.inventory_valuations ADD COLUMN IF NOT EXISTS kind varchar(20) NOT NULL DEFAULT 'OPENING', ADD COLUMN IF NOT EXISTS source_valuation_id integer"))
    existing = set(conn.execute(text("SELECT conname FROM pg_constraint WHERE conrelid='containermgmt.inventory_valuations'::regclass")).scalars())
    wanted = ['uq_valuation_id_org', 'uq_valuation_operation_line', 'ck_valuation_quantity_v2', 'ck_valuation_kind', 'fk_valuation_charge_source']
    constraints = {item.name: item for item in InventoryValuation.__table__.constraints}
    for name in wanted:
        if name not in existing: conn.execute(AddConstraint(constraints[name]))
    for index in InventoryValuation.__table__.indexes:
        if index.name in ('uq_valuation_opening_source', 'ix_containermgmt_inventory_valuations_source_valuation_id'):
            index.create(conn, checkfirst=True)
    # Replacement constraints/index are in place before removing old restrictions.
    for name in ('uq_valuation_stock_source', 'uq_valuation_operation', 'ck_valuation_quantity'):
        if name in existing:
            conn.execute(text(f'ALTER TABLE containermgmt.inventory_valuations DROP CONSTRAINT {name}'))
    conn.execute(text(CHARGE_FUNCTION))
    if not conn.execute(text("SELECT 1 FROM pg_trigger WHERE tgrelid='containermgmt.inventory_valuations'::regclass AND tgname='charge_valuation_guard' AND NOT tgisinternal")).scalar():
        conn.execute(text(CHARGE_TRIGGER))


def ensure_valuation_charges_schema():
    with engine.begin() as conn: prepare_valuation_charges(conn)
