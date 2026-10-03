"""Add an empty immutable operation/outbox table. No business posting or backfill."""
from sqlalchemy import text
from Model.db import engine
from Model.containermgmt.Inventory.PostingOperation import (
    PostingOperation, IMMUTABLE_FUNCTION, IMMUTABLE_TRIGGER,
)


def ensure_inventory_posting_schema():
    with engine.begin() as conn:
        PostingOperation.__table__.create(conn, checkfirst=True)
        conn.execute(text(IMMUTABLE_FUNCTION))
        exists = conn.execute(text("""
            SELECT 1 FROM pg_trigger
            WHERE tgrelid = 'containermgmt.inventory_posting_operations'::regclass
              AND tgname = 'inventory_posting_immutable' AND NOT tgisinternal
        """)).scalar()
        if not exists:
            conn.execute(text(IMMUTABLE_TRIGGER))
