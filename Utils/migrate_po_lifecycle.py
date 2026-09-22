import logging
from sqlalchemy import text
from Model.db import engine, Base
import Model.containermgmt  # ensure all models are registered in Base.metadata

logger = logging.getLogger("containerMgmt.migrations")

def ensure_po_lifecycle_schema():
    """
    Idempotent schema upgrade for Enterprise 7-Stage Procurement Lifecycle.
    1. Creates new tables: vendor_quotes, vendor_quote_items, po_item_history, po_stage_transitions
    2. Adds lifecycle and multi-stage price columns to purchase_orders, po_items, and supplier
    3. Safely backfills existing PO records with initial lifecycle stages
    """
    try:
        # Step 1: Ensure new tables exist
        Base.metadata.create_all(bind=engine)
        logger.info("PO Lifecycle tables verified via metadata create_all.")

        # Step 2: Idempotent ALTER TABLE column additions
        with engine.connect() as conn:
            if engine.dialect.name == "postgresql":
                conn.execute(text("""
                    -- purchase_orders additions
                    ALTER TABLE containermgmt.purchase_orders
                    ADD COLUMN IF NOT EXISTS lifecycle_stage VARCHAR(30) NOT NULL DEFAULT 'DRAFT',
                    ADD COLUMN IF NOT EXISTS stage_version INTEGER NOT NULL DEFAULT 1,
                    ADD COLUMN IF NOT EXISTS lifecycle_version INTEGER NOT NULL DEFAULT 1,
                    ADD COLUMN IF NOT EXISTS lifecycle_locked BOOLEAN NOT NULL DEFAULT FALSE,
                    ADD COLUMN IF NOT EXISTS selected_quote_id INTEGER;

                    -- po_items additions
                    ALTER TABLE containermgmt.po_items
                    ADD COLUMN IF NOT EXISTS draft_unit_price NUMERIC(14,2),
                    ADD COLUMN IF NOT EXISTS approved_unit_price NUMERIC(14,2),
                    ADD COLUMN IF NOT EXISTS po_unit_price NUMERIC(14,2),
                    ADD COLUMN IF NOT EXISTS proforma_unit_price NUMERIC(14,2),
                    ADD COLUMN IF NOT EXISTS item_status VARCHAR(30) NOT NULL DEFAULT 'ACTIVE',
                    ADD COLUMN IF NOT EXISTS removed_at_stage VARCHAR(30),
                    ADD COLUMN IF NOT EXISTS substituted_by_id INTEGER,
                    ADD COLUMN IF NOT EXISTS original_item_id INTEGER;

                    -- supplier additions
                    ALTER TABLE containermgmt.supplier
                    ADD COLUMN IF NOT EXISTS variance_threshold_pct NUMERIC(5,2) DEFAULT 2.0;
                """))
                conn.commit()

                # Step 3: Backfill lifecycle_stage on existing records if still at default or NULL
                conn.execute(text("""
                    UPDATE containermgmt.purchase_orders
                    SET lifecycle_stage = CASE
                        WHEN status IN ('DRAFT') THEN 'DRAFT'
                        WHEN status IN ('SUBMITTED', 'SOURCING') THEN 'CONFIRMED'
                        WHEN status IN ('ORDERED', 'PART_PAID', 'PAID', 'IN_PRODUCTION', 'READY', 'PACKED', 'SHIPPED', 'ARRIVED', 'RECEIVED', 'COMPLETED') THEN 'PO_ISSUED'
                        ELSE 'DRAFT'
                    END
                    WHERE lifecycle_stage = 'DRAFT' AND status NOT IN ('DRAFT');

                    UPDATE containermgmt.po_items
                    SET draft_unit_price = unit_price, po_unit_price = unit_price
                    WHERE draft_unit_price IS NULL AND unit_price IS NOT NULL;
                """))
                conn.commit()
                logger.info("PO Lifecycle schema upgrade and backfill successfully verified.")
            else:
                logger.info(f"Skipping Postgres-specific ALTER TABLE on dialect: {engine.dialect.name}")
    except Exception as e:
        logger.error(f"Failed to ensure PO lifecycle schema: {e}")
