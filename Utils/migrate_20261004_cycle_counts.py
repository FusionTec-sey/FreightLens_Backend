"""Empty cycle-count planning and blind-count tables. No stock or value effect."""
from sqlalchemy import text
from Model.db import engine
from Model.containermgmt.Inventory.CycleCount import TABLES, IMMUTABLE_TABLES, FUNCTION, trigger


def ensure_cycle_counts_schema():
    with engine.begin() as conn:
        conn.execute(text("SET LOCAL lock_timeout = '5s'"))
        for table in TABLES:
            table.create(conn, checkfirst=True)
        conn.execute(text(FUNCTION))
        for name in IMMUTABLE_TABLES:
            installed = conn.execute(text(
                "SELECT 1 FROM pg_trigger WHERE tgrelid = CAST(:name AS regclass) "
                "AND tgname = 'count_history_immutable' AND NOT tgisinternal"),
                {"name": f"containermgmt.{name}"}).scalar()
            if not installed:
                conn.execute(text(trigger(name)))
        # Entries of one save share its posting operation; the old per-entry
        # unique constraint made that impossible.
        conn.execute(text('ALTER TABLE containermgmt.inventory_count_entries '
                          'DROP CONSTRAINT IF EXISTS uq_count_entry_operation'))
