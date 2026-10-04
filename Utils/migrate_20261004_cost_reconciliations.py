"""Create empty immutable cost-reconciliation history; never backfill closes."""
from sqlalchemy import text

from Model.db import engine
from Model.containermgmt.Inventory.CostReconciliation import (
    InventoryCostReconciliation, FUNCTION, TRIGGER)


def ensure_cost_reconciliations_schema():
    with engine.begin() as conn:
        conn.execute(text("SET LOCAL lock_timeout = '5s'"))
        InventoryCostReconciliation.__table__.create(conn, checkfirst=True)
        conn.execute(text(FUNCTION))
        if not conn.execute(text("""SELECT 1 FROM pg_trigger WHERE
            tgrelid='containermgmt.inventory_cost_reconciliations'::regclass
            AND tgname='cost_reconciliation_immutable' AND NOT tgisinternal""")).scalar():
            conn.execute(text(TRIGGER))
