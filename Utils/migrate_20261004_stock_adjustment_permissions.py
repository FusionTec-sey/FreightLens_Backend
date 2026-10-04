"""Separate request, independent review and execution of exact stock adjustments."""
import logging

from sqlalchemy import text

from Model.db import engine

logger = logging.getLogger("containerMgmt.migrations")

NEW_PERMISSIONS = {
    "Request_StockAdjustment": "Request review of an exact location stock correction",
    "Review_StockAdjustment": "Independently approve or reject an exact location stock correction",
    "Execute_StockAdjustment": "Execute an exact approved location stock correction",
}

ROLE_NEW_PERMISSIONS = {
    "Super_Admin": list(NEW_PERMISSIONS),
    "Administrator": list(NEW_PERMISSIONS),
    "Tenant_Admin": list(NEW_PERMISSIONS),
    "Warehouse_Supervisor": ["Request_StockAdjustment"],
}


def ensure_stock_adjustment_permissions():
    with engine.begin() as conn:
        conn.execute(text("SET LOCAL lock_timeout = '5s'"))
        if not conn.execute(text("""SELECT 1 FROM information_schema.tables
            WHERE table_schema='usercredentials' AND table_name='permissions'""")).scalar():
            logger.warning("usercredentials.permissions missing; skipping stock-adjustment permissions")
            return
        for name, description in NEW_PERMISSIONS.items():
            conn.execute(text("""INSERT INTO usercredentials.permissions (name, description)
                VALUES (:name, :description) ON CONFLICT (name) DO NOTHING"""),
                {"name": name, "description": description})
        permissions = {name: key for key, name in conn.execute(
            text("SELECT id, name FROM usercredentials.permissions")).fetchall()}
        roles = {name: key for key, name in conn.execute(
            text("SELECT id, name FROM usercredentials.roles")).fetchall()}
        for role_name, names in ROLE_NEW_PERMISSIONS.items():
            role_id = roles.get(role_name)
            if role_id is None:
                continue
            for name in names:
                permission_id = permissions.get(name)
                if permission_id is not None:
                    conn.execute(text("""INSERT INTO usercredentials.role_permissions
                        (role_id, permission_id) VALUES (:role_id, :permission_id)
                        ON CONFLICT DO NOTHING"""),
                        {"role_id": role_id, "permission_id": permission_id})

