"""Keep the vendor's name on the document, as it stood when the document was raised.

A purchase order stored only supplier_id, and the printed vendor name was
resolved live. A vendor is shared and now editable by any company holding the
permission, so renaming one rewrote every historical order and every reprint --
a March order would print today's name. That is wrong whether or not vendors are
shared; sharing only makes it likelier someone triggers it.

The snapshot is written once, when the document is raised, and never revisited,
so a correction to a vendor reaches new documents only.

Existing rows are backfilled from the vendor they point at. That is the best
available truth: the name today is the only name on record, and leaving them
empty would keep resolving live forever.
"""
import logging

from sqlalchemy import text

from Model.db import engine

logger = logging.getLogger("containerMgmt.migrate_vendor_snapshot")


def _add_column(conn, table: str, column: str, ddl_type: str):
    exists = conn.execute(text("""
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'containermgmt' AND table_name = :t AND column_name = :c
    """), {"t": table, "c": column}).first()
    if exists:
        return False
    conn.execute(text(
        f'ALTER TABLE containermgmt.{table} ADD COLUMN {column} {ddl_type}'
    ))
    return True


def ensure_vendor_snapshot_schema():
    with engine.begin() as conn:
        for table, column, ddl in (
            ("purchase_orders", "supplier_name_at_issue", "VARCHAR(255)"),
            ("purchase_orders", "supplier_address_at_issue", "VARCHAR(500)"),
            ("bill_of_landing", "supplier_name_at_issue", "VARCHAR(255)"),
        ):
            if _add_column(conn, table, column, ddl):
                logger.info("Added %s.%s.", table, column)

        # Backfill only where nothing is recorded yet, so a snapshot already
        # taken is never overwritten by the vendor's current name.
        filled_po = conn.execute(text("""
            UPDATE containermgmt.purchase_orders p
            SET supplier_name_at_issue = s.name,
                supplier_address_at_issue = COALESCE(p.supplier_address_at_issue, s.address)
            FROM containermgmt.supplier s
            WHERE s.supplier_id = p.supplier_id
              AND p.supplier_name_at_issue IS NULL
        """)).rowcount

        # An order with no vendor link keeps whatever free text it carried.
        filled_text = conn.execute(text("""
            UPDATE containermgmt.purchase_orders
            SET supplier_name_at_issue = company
            WHERE supplier_name_at_issue IS NULL
              AND company IS NOT NULL AND trim(company) <> ''
        """)).rowcount

        filled_bl = conn.execute(text("""
            UPDATE containermgmt.bill_of_landing b
            SET supplier_name_at_issue = s.name
            FROM containermgmt.supplier s
            WHERE s.supplier_id = b."Supplier"
              AND b.supplier_name_at_issue IS NULL
        """)).rowcount

        logger.info(
            "Vendor names recorded on documents (%s orders from the vendor, %s from "
            "free text, %s bills of lading).",
            filled_po, filled_text, filled_bl,
        )
