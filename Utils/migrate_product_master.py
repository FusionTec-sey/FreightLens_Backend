import logging
from sqlalchemy import text
from Model.db import engine, Base
from Model.containermgmt import Product, ProductCategory, ProductLink

logger = logging.getLogger("containerMgmt.migrations")

def ensure_product_master_schema():
    """
    Idempotent schema upgrade for Product Master (Phase 2).
    Ensures containermgmt.product_links is created and all Phase 2 columns
    exist on products and product_categories.
    """
    try:
        # 1. Create any missing tables registered in Base.metadata
        Base.metadata.create_all(bind=engine)

        # 2. Add missing columns to existing tables
        with engine.connect() as conn:
            if engine.dialect.name == "postgresql":
                conn.execute(text("""
                    ALTER TABLE containermgmt.product_categories
                    ADD COLUMN IF NOT EXISTS parent_id INTEGER REFERENCES containermgmt.product_categories(id) ON DELETE SET NULL,
                    ADD COLUMN IF NOT EXISTS is_subcategory BOOLEAN DEFAULT FALSE,
                    ADD COLUMN IF NOT EXISTS images JSON,
                    ADD COLUMN IF NOT EXISTS attachments JSON;

                    ALTER TABLE containermgmt.products
                    ADD COLUMN IF NOT EXISTS code VARCHAR(100),
                    ADD COLUMN IF NOT EXISTS description_quick VARCHAR(500),
                    ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'active',
                    ADD COLUMN IF NOT EXISTS model_number VARCHAR(100),
                    ADD COLUMN IF NOT EXISTS series VARCHAR(100),
                    ADD COLUMN IF NOT EXISTS country_of_origin VARCHAR(2),
                    ADD COLUMN IF NOT EXISTS barcode VARCHAR(100),
                    ADD COLUMN IF NOT EXISTS hs_code VARCHAR(20),
                    ADD COLUMN IF NOT EXISTS duty_rate NUMERIC(5,2),
                    ADD COLUMN IF NOT EXISTS tags JSON,
                    ADD COLUMN IF NOT EXISTS length NUMERIC(10,4),
                    ADD COLUMN IF NOT EXISTS width NUMERIC(10,4),
                    ADD COLUMN IF NOT EXISTS height NUMERIC(10,4),
                    ADD COLUMN IF NOT EXISTS weight_per_unit NUMERIC(10,4),
                    ADD COLUMN IF NOT EXISTS dimension_unit VARCHAR(10) DEFAULT 'mm',
                    ADD COLUMN IF NOT EXISTS weight_unit VARCHAR(10) DEFAULT 'kg',
                    ADD COLUMN IF NOT EXISTS units_per_box NUMERIC(12,4),
                    ADD COLUMN IF NOT EXISTS box_weight NUMERIC(10,4),
                    ADD COLUMN IF NOT EXISTS min_stock_quantity NUMERIC(12,2) DEFAULT 0.0,
                    ADD COLUMN IF NOT EXISTS max_stock_quantity NUMERIC(12,2),
                    ADD COLUMN IF NOT EXISTS order_threshold_qty NUMERIC(12,2),
                    ADD COLUMN IF NOT EXISTS threshold_qty NUMERIC(12,2),
                    ADD COLUMN IF NOT EXISTS min_quantity_order NUMERIC(12,2),
                    ADD COLUMN IF NOT EXISTS lead_time_days INTEGER,
                    ADD COLUMN IF NOT EXISTS images JSON,
                    ADD COLUMN IF NOT EXISTS attachment JSON,
                    ADD COLUMN IF NOT EXISTS is_consumable BOOLEAN DEFAULT FALSE,
                    ADD COLUMN IF NOT EXISTS is_hazardous BOOLEAN DEFAULT FALSE,
                    ADD COLUMN IF NOT EXISTS is_perishable BOOLEAN DEFAULT FALSE,
                    ADD COLUMN IF NOT EXISTS expiry_days INTEGER,
                    ADD COLUMN IF NOT EXISTS is_returnable BOOLEAN DEFAULT TRUE,
                    ADD COLUMN IF NOT EXISTS warranty_days INTEGER;

                    UPDATE containermgmt.products
                    SET status = 'active'
                    WHERE status IS NULL;
                """))
                conn.commit()
            logger.info("Product master schema upgrade verified.")
    except Exception as e:
        logger.error(f"Error ensuring product master schema: {e}")
