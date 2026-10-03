"""Empty immutable valuation history; never infer opening values from prices."""
from sqlalchemy import text
from Model.db import engine
from Model.containermgmt.Inventory.Valuation import InventoryValuation, FUNCTION, TRIGGER


def ensure_inventory_valuation_schema():
    with engine.begin() as conn:
        conn.execute(text("SET LOCAL lock_timeout = '5s'"))
        InventoryValuation.__table__.create(conn, checkfirst=True)
        conn.execute(text(FUNCTION))
        if not conn.execute(text("""SELECT 1 FROM pg_trigger WHERE
            tgrelid = 'containermgmt.inventory_valuations'::regclass
            AND tgname = 'valuation_immutable' AND NOT tgisinternal""")).scalar():
            conn.execute(text(TRIGGER))
