import logging
from sqlalchemy import text
from Model.db import engine, Base
import Model.containermgmt  # ensure all models are registered in Base.metadata

logger = logging.getLogger("containerMgmt.migrations")

def ensure_material_tracking_and_holds_schema():
    """
    Idempotent schema upgrade for Operational Material Tracking and Holds:
    1. Adds hold_reason, hold_type to containermgmt.purchase_orders
    2. Adds hold_reason, hold_type to containermgmt.store_requests
    3. Disentangles historical orders whose physical status was overwritten with 'PAID'/'PART_PAID'
    """
    try:
        with engine.connect() as conn:
            if engine.dialect.name == "postgresql":
                conn.execute(text("""
                    -- purchase_orders hold additions
                    ALTER TABLE containermgmt.purchase_orders
                    ADD COLUMN IF NOT EXISTS hold_reason VARCHAR(500),
                    ADD COLUMN IF NOT EXISTS hold_type VARCHAR(50);

                    -- store_requests hold additions
                    ALTER TABLE containermgmt.store_requests
                    ADD COLUMN IF NOT EXISTS hold_reason VARCHAR(500),
                    ADD COLUMN IF NOT EXISTS hold_type VARCHAR(50);
                """))
                conn.commit()

                # Restore physical status for orders where payment logic previously overwrote status to PAID or PART_PAID
                conn.execute(text("""
                    UPDATE containermgmt.purchase_orders
                    SET status = CASE
                        WHEN receipt_status = 'RECEIVED' THEN 'RECEIVED'
                        WHEN shipment_status IN ('SHIPPED', 'ARRIVED') THEN 'SHIPPED'
                        WHEN production_status = 'IN_PRODUCTION' THEN 'IN_PRODUCTION'
                        WHEN production_status = 'READY' THEN 'READY'
                        ELSE 'ORDERED'
                    END,
                    status_label = CASE
                        WHEN receipt_status = 'RECEIVED' THEN 'Received'
                        WHEN shipment_status IN ('SHIPPED', 'ARRIVED') THEN 'In Transit'
                        WHEN production_status = 'IN_PRODUCTION' THEN 'In Production'
                        WHEN production_status = 'READY' THEN 'Ready to Load'
                        ELSE 'PO Issued'
                    END
                    WHERE status IN ('PAID', 'PART_PAID');
                """))
                conn.commit()
            else:
                # MySQL / generic fallback
                for q in [
                    "ALTER TABLE containermgmt.purchase_orders ADD COLUMN IF NOT EXISTS hold_reason VARCHAR(500);",
                    "ALTER TABLE containermgmt.purchase_orders ADD COLUMN IF NOT EXISTS hold_type VARCHAR(50);",
                    "ALTER TABLE containermgmt.store_requests ADD COLUMN IF NOT EXISTS hold_reason VARCHAR(500);",
                    "ALTER TABLE containermgmt.store_requests ADD COLUMN IF NOT EXISTS hold_type VARCHAR(50);"
                ]:
                    try:
                        conn.execute(text(q))
                    except Exception as col_err:
                        logger.debug("Column addition notice: %s", col_err)
                conn.commit()

        logger.info("Material tracking and operational hold schema verified successfully.")
    except Exception as e:
        logger.error("Failed to run material tracking migration: %s", e)

if __name__ == "__main__":
    ensure_material_tracking_and_holds_schema()
