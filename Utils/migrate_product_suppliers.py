"""
Migration script for containermgmt.product_suppliers.
Creates the table for multi-vendor relationships with factory codes and backfills
existing default_supplier_id associations from containermgmt.products.
"""
import logging
from sqlalchemy import text
from Model.db import engine

logger = logging.getLogger("containerMgmt.migrate_product_suppliers")

def ensure_product_suppliers_schema():
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS containermgmt.product_suppliers (
                id SERIAL PRIMARY KEY,
                org_id INTEGER NOT NULL REFERENCES usercredentials.organisations(id) ON DELETE CASCADE,
                product_id INTEGER NOT NULL REFERENCES containermgmt.products(id) ON DELETE CASCADE,
                supplier_id INTEGER NOT NULL REFERENCES containermgmt.supplier(supplier_id) ON DELETE CASCADE,
                factory_code VARCHAR(100),
                vendor_product_name VARCHAR(255),
                unit_cost NUMERIC(14, 2),
                currency VARCHAR(10) NOT NULL DEFAULT 'USD',
                min_order_qty NUMERIC(12, 2),
                lead_time_days INTEGER,
                is_default BOOLEAN NOT NULL DEFAULT FALSE,
                notes TEXT,
                is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
                deleted_at TIMESTAMP WITHOUT TIME ZONE,
                created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT (NOW() AT TIME ZONE 'utc'),
                updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT (NOW() AT TIME ZONE 'utc'),
                created_by INTEGER,
                updated_by INTEGER,
                deleted_by INTEGER
            );

            CREATE INDEX IF NOT EXISTS idx_product_suppliers_prod_supp 
                ON containermgmt.product_suppliers(product_id, supplier_id);
            CREATE INDEX IF NOT EXISTS idx_product_suppliers_factory_code 
                ON containermgmt.product_suppliers(factory_code);
            CREATE INDEX IF NOT EXISTS idx_product_suppliers_default 
                ON containermgmt.product_suppliers(product_id, is_default) WHERE is_default = TRUE;
            CREATE INDEX IF NOT EXISTS idx_product_suppliers_org 
                ON containermgmt.product_suppliers(org_id);
        """))

        # Backfill existing products that have default_supplier_id but no row in product_suppliers
        conn.execute(text("""
            INSERT INTO containermgmt.product_suppliers (
                org_id, product_id, supplier_id, factory_code, unit_cost, currency,
                lead_time_days, is_default, is_deleted, created_at, updated_at
            )
            SELECT 
                p.org_id, 
                p.id, 
                p.default_supplier_id, 
                p.sku, 
                p.unit_cost, 
                COALESCE(p.currency, 'USD'),
                p.lead_time_days, 
                TRUE, 
                FALSE, 
                NOW() AT TIME ZONE 'utc', 
                NOW() AT TIME ZONE 'utc'
            FROM containermgmt.products p
            WHERE p.default_supplier_id IS NOT NULL 
              AND p.is_deleted = FALSE
              AND NOT EXISTS (
                  SELECT 1 FROM containermgmt.product_suppliers ps 
                  WHERE ps.product_id = p.id AND ps.supplier_id = p.default_supplier_id
              );
        """))

    logger.info("containermgmt.product_suppliers table verified and existing supplier links backfilled.")

if __name__ == "__main__":
    ensure_product_suppliers_schema()
    print("Migration and backfill of containermgmt.product_suppliers completed successfully.")
