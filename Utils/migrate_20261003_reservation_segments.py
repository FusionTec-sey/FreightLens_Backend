"""Append reviewed hold segments without rewriting historical quantities."""
from sqlalchemy import text
from Model.db import engine
from Model.containermgmt.Inventory.ReservationSegmentGuard import FUNCTION, TRIGGER, IDENTITY_FUNCTION, IDENTITY_TRIGGER


def ensure_reservation_segments_schema():
    with engine.begin() as conn:
        conn.execute(text("SET LOCAL lock_timeout = '5s'"))
        conn.execute(text(FUNCTION))
        conn.execute(text(IDENTITY_FUNCTION))
        if not conn.execute(text("SELECT 1 FROM pg_trigger WHERE tgrelid='containermgmt.inventory_stock_reservations'::regclass "
            "AND tgname='reservation_segment_guard' AND NOT tgisinternal")).scalar():
            conn.execute(text(TRIGGER))
        if not conn.execute(text("SELECT 1 FROM pg_trigger WHERE tgrelid='containermgmt.inventory_stock_reservations'::regclass "
            "AND tgname='reservation_segment_identity' AND NOT tgisinternal")).scalar():
            conn.execute(text(IDENTITY_TRIGGER))
        # Existing source lookup index (org_id, source_line_key) remains. Remove
        # only the obsolete constraint after its replacement guard is installed.
        conn.execute(text('ALTER TABLE containermgmt.inventory_stock_reservations DROP CONSTRAINT IF EXISTS uq_stock_reservation_source'))
