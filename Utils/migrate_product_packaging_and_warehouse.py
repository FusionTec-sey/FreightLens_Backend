"""
Migration: Add Multi-Tier Packaging, Container Capacity, and Warehouse Location columns
to containermgmt.products table.
Supports:
1. Retail packaging tier
2. Wholesale / inner packaging tier
3. Import / master shipping packaging tier
4. Palletization specs & editable container capacity estimates (20ft / 40ft HC)
5. Warehouse & Bin coordinates (preparing for future WMS module)
6. Extensible packaging_specs JSONB
"""

import os
import sys
import logging
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sqlalchemy import text
from Model.db import engine

logger = logging.getLogger("containerMgmt.migrations")

PACKAGING_COLUMNS = [
    # Retail / Primary Packaging
    ("retail_packaging_type", "VARCHAR(100)"),
    ("gross_weight_per_unit", "NUMERIC(10, 4)"),
    
    # Wholesale / Inner Packaging
    ("wholesale_packaging_type", "VARCHAR(100)"),
    ("units_per_inner", "NUMERIC(12, 4)"),
    ("inner_length", "NUMERIC(10, 4)"),
    ("inner_width", "NUMERIC(10, 4)"),
    ("inner_height", "NUMERIC(10, 4)"),
    ("inner_weight", "NUMERIC(10, 4)"),
    
    # Import / Master Shipping Packaging
    ("import_packaging_type", "VARCHAR(100)"),
    ("master_length", "NUMERIC(10, 4)"),
    ("master_width", "NUMERIC(10, 4)"),
    ("master_height", "NUMERIC(10, 4)"),
    ("master_tare_weight", "NUMERIC(10, 4)"),
    
    # Palletization & Container Loading Specs
    ("pallet_type", "VARCHAR(100)"),
    ("cartons_per_layer", "INTEGER"),
    ("layers_per_pallet", "INTEGER"),
    ("total_cartons_per_pallet", "INTEGER"),
    ("max_stacking_layers", "INTEGER"),
    ("est_qty_20ft", "NUMERIC(12, 2)"),
    ("est_qty_40hc", "NUMERIC(12, 2)"),
    
    # Warehouse & Bin Coordinates (WMS Preparation)
    ("warehouse_location", "VARCHAR(150)"),
    ("default_bin", "VARCHAR(100)"),
    
    # Extensible JSON metadata
    ("packaging_specs", "JSONB" if engine.dialect.name == "postgresql" else "JSON"),
]

def ensure_packaging_and_warehouse_columns():
    """Idempotently adds packaging and warehouse columns to containermgmt.products."""
    try:
        with engine.connect() as conn:
            is_postgres = (engine.dialect.name == "postgresql")
            biz_schema = "containermgmt." if is_postgres else ""
            schema_clause = "AND table_schema = 'containermgmt'" if is_postgres else ""

            # Check if table exists
            table_check = conn.execute(text(f"""
                SELECT 1 FROM information_schema.tables 
                WHERE table_name = 'products' {schema_clause};
            """)).scalar()

            if not table_check:
                logger.warning("containermgmt.products table not found, skipping packaging migration.")
                return

            for col_name, col_type in PACKAGING_COLUMNS:
                col_exists = conn.execute(text(f"""
                    SELECT 1 FROM information_schema.columns 
                    WHERE table_name = 'products' AND column_name = :col_name {schema_clause};
                """), {"col_name": col_name}).scalar()

                if not col_exists:
                    logger.info(f"Adding column {col_name} ({col_type}) to {biz_schema}products")
                    conn.execute(text(f"""
                        ALTER TABLE {biz_schema}products 
                        ADD COLUMN IF NOT EXISTS {col_name} {col_type};
                    """))
                    conn.commit()

            logger.info("Multi-tier packaging, container estimates, and warehouse columns verified successfully.")

    except Exception as e:
        logger.error(f"Error migrating packaging and warehouse columns: {e}", exc_info=True)


if __name__ == "__main__":
    ensure_packaging_and_warehouse_columns()
