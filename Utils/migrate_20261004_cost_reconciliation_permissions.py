"""Add separate cost-reconciliation request, review and close permissions."""
import logging
from sqlalchemy import text

from Model.db import engine

logger = logging.getLogger("containerMgmt.migrations")
NEW_PERMISSIONS = {
    "Request_CostReconciliation": "Request review of an exact product and cost-pool reconciliation state",
    "Review_CostReconciliation": "Independently review an exact inventory-cost reconciliation state",
    "Execute_CostReconciliation": "Close an independently approved inventory-cost reconciliation checkpoint",
}
ROLE_NEW_PERMISSIONS = {name: list(NEW_PERMISSIONS) for name in
    ("Super_Admin", "Administrator", "Tenant_Admin")}


def ensure_cost_reconciliation_permissions():
    with engine.begin() as conn:
        conn.execute(text("SET LOCAL lock_timeout = '5s'"))
        if not conn.execute(text("""SELECT 1 FROM information_schema.tables
            WHERE table_schema='usercredentials' AND table_name='permissions'""")).scalar():
            logger.warning("permissions table missing; skipping cost-reconciliation permissions")
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
            if role_id is None: continue
            for name in names:
                permission_id = permissions.get(name)
                if permission_id is not None:
                    conn.execute(text("""INSERT INTO usercredentials.role_permissions
                        (role_id, permission_id) VALUES (:role_id, :permission_id)
                        ON CONFLICT DO NOTHING"""),
                        {"role_id": role_id, "permission_id": permission_id})
