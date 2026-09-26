import os
import sys
import logging
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sqlalchemy import text
from Model.db import engine

logger = logging.getLogger("containerMgmt.migrations")

def ensure_order_documents_org_schema():
    """
    Idempotent schema migration to ensure multi-tenant row isolation (org_id)
    on containermgmt.order_documents and related order child tables:
    - order_documents
    - order_payments
    - po_items
    - order_shipments
    - order_packing_lists
    - order_status_history
    - po_stage_transitions
    
    Backfills org_id from parent purchase_orders where available, default 1.
    """
    try:
        with engine.connect() as conn:
            if engine.dialect.name == "postgresql":
                tables_to_migrate = [
                    "order_documents",
                    "order_payments",
                    "po_items",
                    "order_shipments",
                    "order_packing_lists",
                    "order_status_history",
                    "po_stage_transitions",
                ]

                for table in tables_to_migrate:
                    # Check if table exists
                    table_exists = conn.execute(text(f"""
                        SELECT 1 FROM information_schema.tables 
                        WHERE table_schema = 'containermgmt' AND table_name = '{table}';
                    """)).scalar()

                    if not table_exists:
                        continue

                    # Check if org_id column exists
                    has_org_col = conn.execute(text(f"""
                        SELECT 1 FROM information_schema.columns 
                        WHERE table_schema = 'containermgmt' 
                          AND table_name = '{table}' 
                          AND column_name = 'org_id';
                    """)).scalar()

                    if not has_org_col:
                        logger.info(f"Adding org_id column to containermgmt.{table}...")
                        conn.execute(text(f"""
                            ALTER TABLE containermgmt.{table} 
                            ADD COLUMN IF NOT EXISTS org_id INTEGER 
                            REFERENCES usercredentials.organisations(id) DEFAULT 1;
                        """))
                        conn.execute(text(f"""
                            CREATE INDEX IF NOT EXISTS idx_{table}_org_id 
                            ON containermgmt.{table}(org_id);
                        """))

                        # Backfill org_id from parent purchase_orders if po_id exists
                        has_po_id = conn.execute(text(f"""
                            SELECT 1 FROM information_schema.columns 
                            WHERE table_schema = 'containermgmt' 
                              AND table_name = '{table}' 
                              AND column_name = 'po_id';
                        """)).scalar()

                        if has_po_id:
                            conn.execute(text(f"""
                                UPDATE containermgmt.{table} child
                                SET org_id = po.org_id
                                FROM containermgmt.purchase_orders po
                                WHERE child.po_id = po.id 
                                  AND po.org_id IS NOT NULL 
                                  AND (child.org_id IS NULL OR child.org_id = 1);
                            """))

                        conn.commit()
                        logger.info(f"Successfully added org_id and backfilled for containermgmt.{table}.")
                    else:
                        logger.info(f"Table containermgmt.{table} already has org_id column.")
            else:
                logger.info(f"Skipping Postgres-specific migration on dialect {engine.dialect.name}")
    except Exception as e:
        logger.error("Failed to migrate order documents and child tables org_id: %s", e)
        raise

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    ensure_order_documents_org_schema()
