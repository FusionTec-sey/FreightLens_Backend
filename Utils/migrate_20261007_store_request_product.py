"""Add optional catalogue-product linkage to store-request items."""
import logging

from sqlalchemy import text

from Model.db import engine

logger = logging.getLogger("containerMgmt.migrate_store_request_product")


def ensure_store_request_product_schema():
    with engine.begin() as conn:
        conn.execute(text("""
            ALTER TABLE containermgmt.store_request_items
            ADD COLUMN IF NOT EXISTS product_id INTEGER
        """))
        conn.execute(text("""
            DO $$ BEGIN
                ALTER TABLE containermgmt.store_request_items
                ADD CONSTRAINT fk_store_request_items_product
                FOREIGN KEY (product_id) REFERENCES containermgmt.products(id)
                ON DELETE SET NULL;
            EXCEPTION WHEN duplicate_object THEN NULL;
            END $$;
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_store_request_items_product_id
            ON containermgmt.store_request_items(product_id)
        """))
    logger.info("containermgmt.store_request_items product linkage verified.")


if __name__ == "__main__":
    ensure_store_request_product_schema()
