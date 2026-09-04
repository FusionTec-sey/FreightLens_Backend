import logging
from sqlalchemy import text
from Model.db import engine, Base

logger = logging.getLogger("containerMgmt.migrations")

def ensure_logistics_tracking_schema():
    """
    Idempotent schema upgrade for rich logistics tracking.
    Adds seal numbers, weights, ports, milestones, and D&D fields.
    """
    try:
        with engine.connect() as conn:
            if engine.dialect.name == "postgresql":
                conn.execute(text("""
                    ALTER TABLE containermgmt.container_details
                    ADD COLUMN IF NOT EXISTS seal_number VARCHAR(50),
                    ADD COLUMN IF NOT EXISTS gross_weight_kg NUMERIC(12,2),
                    ADD COLUMN IF NOT EXISTS gross_volume_cbm NUMERIC(10,3),
                    ADD COLUMN IF NOT EXISTS port_of_loading VARCHAR(100),
                    ADD COLUMN IF NOT EXISTS port_of_discharge VARCHAR(100),
                    ADD COLUMN IF NOT EXISTS transshipment_hub VARCHAR(100),
                    ADD COLUMN IF NOT EXISTS latest_milestone VARCHAR(255),
                    ADD COLUMN IF NOT EXISTS tracking_timeline JSON,
                    ADD COLUMN IF NOT EXISTS dnd_report JSON;

                    ALTER TABLE containermgmt.bill_of_landing
                    ADD COLUMN IF NOT EXISTS origin_port VARCHAR(100),
                    ADD COLUMN IF NOT EXISTS destination_port VARCHAR(100),
                    ADD COLUMN IF NOT EXISTS transshipment_ports JSON,
                    ADD COLUMN IF NOT EXISTS carrier_name VARCHAR(100),
                    ADD COLUMN IF NOT EXISTS shipped_on_board_date TIMESTAMP,
                    ADD COLUMN IF NOT EXISTS raw_tracking_data JSON;
                """))
                conn.commit()
                logger.info("Logistics tracking schema upgrade verified.")
    except Exception as e:
        logger.error(f"Failed to ensure logistics tracking schema: {e}")
