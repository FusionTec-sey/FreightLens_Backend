"""Keep what was asked for beside what was agreed, on every order line.

A vendor rarely answers the question exactly as it was put. A minimum order
quantity, a carton multiple or a substitute all mean the awarded line differs
from the requested one, and until now the award simply dropped the difference:
it copied the vendor's price onto the line and left the requested quantity in
place, so a quote for 5 at $10 became a purchase order for 3 at $10 -- $50
agreed, $30 ordered, with nobody told.

quantity_requested holds the request so that accepting the vendor's number does
not erase it. Existing rows are backfilled from quantity_ordered, which is the
only truth on record for them: before this column, the two were the same thing
by definition.
"""
import logging

from sqlalchemy import text

from Model.db import engine

logger = logging.getLogger("containerMgmt.migrate_award_deviations")


def _column_exists(conn, table: str, column: str) -> bool:
    return bool(conn.execute(text("""
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'containermgmt' AND table_name = :t AND column_name = :c
    """), {"t": table, "c": column}).first())


def ensure_award_deviation_schema():
    with engine.begin() as conn:
        if not _column_exists(conn, "po_items", "quantity_requested"):
            conn.execute(text("""
                ALTER TABLE containermgmt.po_items
                ADD COLUMN quantity_requested NUMERIC(12,2)
            """))
            filled = conn.execute(text("""
                UPDATE containermgmt.po_items
                SET quantity_requested = quantity_ordered
                WHERE quantity_requested IS NULL
            """)).rowcount
            logger.info(
                "Added po_items.quantity_requested and backfilled %s line(s) from "
                "quantity_ordered.", filled,
            )

        deviating = conn.execute(text("""
            SELECT count(*) FROM containermgmt.po_items
            WHERE is_deleted = FALSE
              AND quantity_requested IS NOT NULL
              AND quantity_requested <> quantity_ordered
        """)).scalar()
        logger.info("Order lines where the agreed quantity differs from the request: %s.", deviating)
