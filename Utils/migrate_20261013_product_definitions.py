"""Create the group product dictionary, and link products to it.

A product row carries universal facts (name, specs, dimensions, HS code) in the
same record as company facts (internal code, unit cost, stock, default
supplier). Sharing the row would mean cutting it in half; copying the whole
thing per company would recreate the duplicate problem the vendor master had.

So the universal half lives here, once for the group, and a company adopting a
product copies it into a row of its own and records where it came from. The link
is what keeps the copies attributable -- without it they are anonymous
duplicates, which is exactly the state the vendor master was in.

products.is_shared is dropped: it existed, nothing ever read it, and a flag that
looks like a feature and does nothing is what kept the category sharing bug
invisible. Dropping it is safe only because it is unread, which was checked
across both the backend and the frontend before this was written.
"""
import logging

from sqlalchemy import text

from Model.db import engine

logger = logging.getLogger("containerMgmt.migrate_product_definitions")


def _column_exists(conn, table: str, column: str) -> bool:
    return bool(conn.execute(text("""
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'containermgmt' AND table_name = :t AND column_name = :c
    """), {"t": table, "c": column}).first())


def ensure_product_definitions_schema():
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS containermgmt.product_definitions (
                id SERIAL PRIMARY KEY,
                sku VARCHAR(100) NOT NULL,
                sku_key VARCHAR(100) NOT NULL,
                name VARCHAR(255) NOT NULL,
                description TEXT,
                brand VARCHAR(100),
                model_number VARCHAR(100),
                series VARCHAR(100),
                country_of_origin VARCHAR(100),
                barcode VARCHAR(100),
                hs_code VARCHAR(20),
                unit VARCHAR(50) DEFAULT 'PCS',
                length NUMERIC(10,4),
                width NUMERIC(10,4),
                height NUMERIC(10,4),
                weight_per_unit NUMERIC(10,4),
                dimension_unit VARCHAR(10),
                weight_unit VARCHAR(10),
                suggested_category_id INTEGER
                    REFERENCES containermgmt.product_categories(id) ON DELETE SET NULL,
                source_org_id INTEGER,
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
                deleted_at TIMESTAMPTZ,
                created_by INTEGER REFERENCES usercredentials.users(id),
                updated_by INTEGER REFERENCES usercredentials.users(id),
                deleted_by INTEGER REFERENCES usercredentials.users(id)
            )
        """))

        # One entry per SKU, normalised, so the dictionary cannot accumulate the
        # case-and-spacing duplicates that had to be merged out of the vendors.
        conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS ix_product_definitions_sku_unique
            ON containermgmt.product_definitions (sku_key)
            WHERE is_deleted = FALSE
        """))

        if not _column_exists(conn, "products", "definition_id"):
            conn.execute(text("""
                ALTER TABLE containermgmt.products
                ADD COLUMN definition_id INTEGER
                REFERENCES containermgmt.product_definitions(id) ON DELETE SET NULL
            """))
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS ix_products_definition_id
                ON containermgmt.products (definition_id)
            """))
            logger.info("Added products.definition_id.")

        # A flag that looks like a feature and does nothing is worse than no
        # flag. Verified unread in the backend and the frontend before dropping.
        if _column_exists(conn, "products", "is_shared"):
            conn.execute(text("ALTER TABLE containermgmt.products DROP COLUMN is_shared"))
            logger.info("Dropped products.is_shared; nothing read it.")

        entries = conn.execute(text(
            "SELECT count(*) FROM containermgmt.product_definitions WHERE is_deleted = FALSE"
        )).scalar()
        logger.info("Group product dictionary is ready (%s entries).", entries)
