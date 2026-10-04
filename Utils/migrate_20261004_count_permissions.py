"""Cycle-count permissions (T33A). Idempotent; grants no stock posting rights.

Enter_CountResult deliberately carries no visibility of expected stock, earlier
rounds or values: blind counting is enforced by giving the counter only this
permission, and by the backend projections that serve it.
"""
import logging

from sqlalchemy import text
from Model.db import engine

logger = logging.getLogger("containerMgmt.migrations")

NEW_PERMISSIONS = {
    "View_CountPlan": "View cycle-count plans, their product-location scope and annual coverage",
    "Manage_CountPlan": "Create and activate cycle-count plans and their product-location scope",
    "Assign_CountSession": "Assign counters to count sessions, cancel them and open recount rounds",
    "Enter_CountResult": "Enter and submit blind counted quantities for own assigned sessions",
    "View_CountDiscrepancy": "View provisional count discrepancies and their recorded decisions",
    "Review_CountDiscrepancy": "Decide a provisional count discrepancy; authorises no stock adjustment",
}

# Managers plan, assign and review. Counting itself is also granted to the
# warehouse roles that do the work on the floor.
ROLE_NEW_PERMISSIONS = {
    "Super_Admin": list(NEW_PERMISSIONS),
    "Administrator": list(NEW_PERMISSIONS),
    "Tenant_Admin": list(NEW_PERMISSIONS),
    "Warehouse_Supervisor": ["View_CountPlan", "Assign_CountSession", "Enter_CountResult",
                             "View_CountDiscrepancy"],
    "Warehouse_Operator": ["Enter_CountResult"],
    "Auditor_ReadOnly": ["View_CountPlan", "View_CountDiscrepancy"],
}


def ensure_count_permissions():
    with engine.begin() as conn:
        conn.execute(text("SET LOCAL lock_timeout = '5s'"))
        exists = conn.execute(text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_name = 'permissions' AND table_schema = 'usercredentials'")).scalar()
        if not exists:
            logger.warning("usercredentials.permissions missing; skipping count permission seeding")
            return

        for name, description in NEW_PERMISSIONS.items():
            conn.execute(text(
                "INSERT INTO usercredentials.permissions (name, description) VALUES (:name, :description) "
                "ON CONFLICT (name) DO NOTHING"), {"name": name, "description": description})

        permissions = {row[1]: row[0] for row in conn.execute(text(
            "SELECT id, name FROM usercredentials.permissions")).fetchall()}
        roles = {row[1]: row[0] for row in conn.execute(text(
            "SELECT id, name FROM usercredentials.roles")).fetchall()}

        linked = 0
        for role_name, names in ROLE_NEW_PERMISSIONS.items():
            role_id = roles.get(role_name)
            if role_id is None:
                continue
            for name in names:
                permission_id = permissions.get(name)
                if permission_id is None:
                    continue
                result = conn.execute(text(
                    "INSERT INTO usercredentials.role_permissions (role_id, permission_id) "
                    "VALUES (:role_id, :permission_id) ON CONFLICT DO NOTHING"),
                    {"role_id": role_id, "permission_id": permission_id})
                linked += result.rowcount or 0
        if linked:
            logger.info("Linked %d cycle-count permission grants", linked)
