"""Columns for converting a confirmed RFQ straight to a PO.

order_source is RFQ for every existing row, because every existing PO was
reached through an RFQ or entered by hand under the same rules; only the
conversion writes DIRECT. source_template_id is the template an RFQ was made
from, so conversion can find the template's vendor: it is null for every RFQ
that exists today, and those need the vendor chosen at conversion. The two
po_items columns record why a quantity differs from the request.
"""
import logging

from sqlalchemy import text

from Model.db import engine
import Model.containermgmt  # noqa: F401  (order_templates must exist before the foreign key)

logger = logging.getLogger("containerMgmt.migrate_direct_po")


def _column_exists(conn, table: str, column: str) -> bool:
    return bool(conn.execute(text("""
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'containermgmt' AND table_name = :t AND column_name = :c
    """), {"t": table, "c": column}).first())


def ensure_direct_po_schema():
    with engine.begin() as conn:
        if not _column_exists(conn, "purchase_orders", "order_source"):
            conn.execute(text("ALTER TABLE containermgmt.purchase_orders ADD COLUMN order_source VARCHAR(20) NOT NULL DEFAULT 'RFQ'"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_purchase_orders_order_source ON containermgmt.purchase_orders (order_source)"))
        if not _column_exists(conn, "purchase_orders", "source_template_id"):
            conn.execute(text("""
                ALTER TABLE containermgmt.purchase_orders
                ADD COLUMN source_template_id INTEGER
                    REFERENCES containermgmt.order_templates(id) ON DELETE SET NULL
            """))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_purchase_orders_source_template_id ON containermgmt.purchase_orders (source_template_id)"))
        for col, ddl in (
            ("qty_adjust_reason", "VARCHAR(20)"),
            ("qty_adjust_note", "VARCHAR(500)"),
        ):
            if not _column_exists(conn, "po_items", col):
                conn.execute(text(f"ALTER TABLE containermgmt.po_items ADD COLUMN {col} {ddl}"))
        logger.info("Direct-PO columns are in place.")
