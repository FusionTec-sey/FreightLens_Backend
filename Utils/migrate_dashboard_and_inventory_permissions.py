import os
import sys
import logging
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sqlalchemy import text
from Model.db import engine

logger = logging.getLogger("containerMgmt.migrations")

NEW_PERMISSIONS = {
    # ── Inventory & Product Master ───────────────────────────────────────────
    "View_Product": "View product catalog, specifications, stock levels, and category hierarchy",
    "Add_Product": "Register new products in the master catalog",
    "Edit_Product": "Modify product specifications, dimensions, classification, and media",
    "Delete_Product": "Deactivate or permanently delete products from catalog",
    "Adjust_Stock": "Manually adjust product stock levels with reason tracking (receipt, damage, return)",
    "View_ProductCategory": "View product category taxonomy tree and hierarchy",
    "Manage_ProductCategory": "Create, edit, rename, delete, and reorganize product categories",

    # ── Dashboard Personalization & Templates ────────────────────────────────
    "Customize_Dashboard": "Personalize dashboard layout by pinning, unpinning, and reordering stat widgets",
    "Manage_DashboardTemplate": "Create, edit, delete, and assign dashboard templates to roles (admin only)",

    # ── Inventory Reporting & Export ─────────────────────────────────────────
    "View_InventoryReport": "View inventory analytics, stock movement summaries, and reorder reports",
    "Export_Inventory": "Export product catalog and stock data to CSV or Excel",
}

ROLE_NEW_PERMISSIONS = {
    "Super_Admin": list(NEW_PERMISSIONS.keys()),
    "Administrator": list(NEW_PERMISSIONS.keys()),
    "Noblecon_Admin": [
        "View_Product", "Add_Product", "Edit_Product", "Delete_Product",
        "Adjust_Stock", "View_ProductCategory", "Manage_ProductCategory",
        "Customize_Dashboard", "Manage_DashboardTemplate",
        "View_InventoryReport", "Export_Inventory",
    ],
    "Procurement_Specialist": [
        "View_Product", "Edit_Product", "View_ProductCategory",
        "Customize_Dashboard", "Export_Inventory",
    ],
    "Finance_Controller": [
        "View_Product", "View_ProductCategory",
        "Customize_Dashboard", "View_InventoryReport",
    ],
    "Accounts_Finance": [
        "View_Product", "View_ProductCategory",
        "Customize_Dashboard", "View_InventoryReport",
    ],
    "Logistics_Coordinator": [
        "View_Product", "View_ProductCategory", "Customize_Dashboard",
    ],
    "Delivery": [
        "View_Product", "Customize_Dashboard",
    ],
    "Warehouse_Supervisor": [
        "View_Product", "Adjust_Stock", "View_ProductCategory",
        "Customize_Dashboard", "View_InventoryReport",
    ],
    "Warehouse_Operator": [
        "View_Product", "Adjust_Stock", "Customize_Dashboard",
    ],
    "Site_Requisitioner": [
        "View_Product", "View_ProductCategory", "Customize_Dashboard",
    ],
    "Store_User": [
        "View_Product", "View_ProductCategory", "Customize_Dashboard",
    ],
    "Auditor_ReadOnly": [
        "View_Product", "View_ProductCategory", "View_InventoryReport", "Customize_Dashboard",
    ],
    "viewer": [
        "View_Product", "View_ProductCategory", "Customize_Dashboard",
    ],
}

def ensure_dashboard_and_inventory_permissions():
    """
    Idempotent migration to:
    1. Seed new granular permissions for Inventory & Dashboard systems into usercredentials.permissions
    2. Map new permissions to existing roles in usercredentials.role_permissions
    3. Ensure containermgmt.dashboard_templates and usercredentials.user_dashboard_configs tables exist
    """
    try:
        with engine.connect() as conn:
            is_postgres = (engine.dialect.name == "postgresql")
            user_schema = "usercredentials." if is_postgres else ""
            biz_schema = "containermgmt." if is_postgres else ""
            schema_perm_clause = "AND table_schema = 'usercredentials'" if is_postgres else ""
            schema_dt_clause = "AND table_schema = 'containermgmt'" if is_postgres else ""
            schema_udc_clause = "AND table_schema = 'usercredentials'" if is_postgres else ""

            # Check if permissions table exists
            table_check = conn.execute(text(f"""
                SELECT 1 FROM information_schema.tables 
                WHERE table_name = 'permissions' {schema_perm_clause};
            """)).scalar()

            if not table_check:
                logger.warning("usercredentials.permissions table not found, skipping permission seeding.")
                return

            # 1. Insert permissions
            for perm_name, perm_desc in NEW_PERMISSIONS.items():
                existing_perm = conn.execute(text(f"""
                    SELECT id FROM {user_schema}permissions WHERE name = :name
                """), {"name": perm_name}).scalar()

                if not existing_perm:
                    logger.info(f"Inserting new permission: {perm_name}")
                    conn.execute(text(f"""
                        INSERT INTO {user_schema}permissions (name, description)
                        VALUES (:name, :description)
                    """), {"name": perm_name, "description": perm_desc})
                    conn.commit()

            # Cache permission IDs
            perm_rows = conn.execute(text(f"SELECT id, name FROM {user_schema}permissions")).fetchall()
            perm_map = {row[1]: row[0] for row in perm_rows}

            # Cache role IDs
            role_rows = conn.execute(text(f"SELECT id, name FROM {user_schema}roles")).fetchall()
            role_map = {row[1]: row[0] for row in role_rows}

            # 2. Bind permissions to roles
            for role_name, perms in ROLE_NEW_PERMISSIONS.items():
                role_id = role_map.get(role_name)
                if not role_id:
                    continue

                for p_name in perms:
                    p_id = perm_map.get(p_name)
                    if not p_id:
                        continue

                    exists = conn.execute(text(f"""
                        SELECT 1 FROM {user_schema}role_permissions 
                        WHERE role_id = :role_id AND permission_id = :permission_id
                    """), {"role_id": role_id, "permission_id": p_id}).scalar()

                    if not exists:
                        conn.execute(text(f"""
                            INSERT INTO {user_schema}role_permissions (role_id, permission_id)
                            VALUES (:role_id, :permission_id)
                        """), {"role_id": role_id, "permission_id": p_id})
                        conn.commit()

            logger.info("New inventory and dashboard permissions verified & mapped.")

            # 3. Create dashboard_templates table
            dt_table_check = conn.execute(text(f"""
                SELECT 1 FROM information_schema.tables 
                WHERE table_name = 'dashboard_templates' {schema_dt_clause};
            """)).scalar()

            if not dt_table_check:
                logger.info("Creating containermgmt.dashboard_templates table...")
                conn.execute(text(f"""
                    CREATE TABLE IF NOT EXISTS {biz_schema}dashboard_templates (
                        id SERIAL PRIMARY KEY,
                        org_id INTEGER NOT NULL REFERENCES {user_schema}organisations(id),
                        name VARCHAR(100) NOT NULL,
                        role_name VARCHAR(100),
                        description TEXT,
                        is_default BOOLEAN DEFAULT FALSE,
                        widgets JSONB DEFAULT '[]'::jsonb,
                        is_deleted BOOLEAN DEFAULT FALSE,
                        deleted_at TIMESTAMP WITH TIME ZONE,
                        created_by INTEGER REFERENCES {user_schema}users(id),
                        updated_by INTEGER REFERENCES {user_schema}users(id),
                        deleted_by INTEGER REFERENCES {user_schema}users(id),
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                    );
                    CREATE INDEX IF NOT EXISTS ix_dashboard_templates_org_id ON {biz_schema}dashboard_templates(org_id);
                    CREATE INDEX IF NOT EXISTS ix_dashboard_templates_role_name ON {biz_schema}dashboard_templates(role_name);
                """))
                conn.commit()
                logger.info("containermgmt.dashboard_templates table created.")

            conn.execute(text(f"""
                ALTER TABLE {biz_schema}dashboard_templates
                    ADD COLUMN IF NOT EXISTS role_id INTEGER
                        REFERENCES {user_schema}roles(id);
                UPDATE {biz_schema}dashboard_templates AS template
                SET role_id = role.id
                FROM {user_schema}roles AS role
                WHERE template.role_id IS NULL
                  AND lower(role.name) = lower(template.role_name)
                  AND (role.org_id IS NULL OR role.org_id = template.org_id);
                CREATE INDEX IF NOT EXISTS ix_dashboard_templates_role_id
                    ON {biz_schema}dashboard_templates(role_id);
            """))
            conn.commit()

            # 4. Create user_dashboard_configs table
            udc_table_check = conn.execute(text(f"""
                SELECT 1 FROM information_schema.tables 
                WHERE table_name = 'user_dashboard_configs' {schema_udc_clause};
            """)).scalar()

            if not udc_table_check:
                logger.info("Creating usercredentials.user_dashboard_configs table...")
                conn.execute(text(f"""
                    CREATE TABLE IF NOT EXISTS {user_schema}user_dashboard_configs (
                        id SERIAL PRIMARY KEY,
                        user_id INTEGER NOT NULL REFERENCES {user_schema}users(id),
                        org_id INTEGER NOT NULL REFERENCES {user_schema}organisations(id),
                        template_id INTEGER REFERENCES {biz_schema}dashboard_templates(id),
                        widgets JSONB DEFAULT '[]'::jsonb,
                        layout_mode VARCHAR(50) DEFAULT 'grid',
                        is_deleted BOOLEAN DEFAULT FALSE,
                        deleted_at TIMESTAMP WITH TIME ZONE,
                        created_by INTEGER REFERENCES {user_schema}users(id),
                        updated_by INTEGER REFERENCES {user_schema}users(id),
                        deleted_by INTEGER REFERENCES {user_schema}users(id),
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                    );
                    CREATE INDEX IF NOT EXISTS ix_user_dashboard_configs_user_org ON {user_schema}user_dashboard_configs(user_id, org_id);
                """))
                conn.commit()
                logger.info("usercredentials.user_dashboard_configs table created.")

    except Exception as e:
        logger.error(f"Failed to migrate dashboard and inventory permissions: {e}")
        raise

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    ensure_dashboard_and_inventory_permissions()
