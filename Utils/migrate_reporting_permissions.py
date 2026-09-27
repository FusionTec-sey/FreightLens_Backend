"""
Utils/migrate_reporting_permissions.py
Idempotent migration script to seed granular Reporting, Operational Register,
Tabular Designer, and Contextual Print permissions into containermgmt.permissions
and assign them to Administrator/Admin and operational roles.
"""
import logging
from sqlalchemy.orm import Session
from sqlalchemy import func as sqlfunc
from Model.Credentials.permissions import Permission
from Model.Credentials.roles import Role

logger = logging.getLogger("containerMgmt.migration")

NEW_REPORTING_PERMISSIONS = [
    ("View_Report", "View reporting catalog, document templates, and operational registers"),
    ("Manage_Report_Template", "Create, edit, version, and publish HTML/CSS document print templates"),
    ("Toggle_Report_Template", "Activate or deactivate report templates for organization print menus"),
    ("View_Operational_Register", "View parametric operational registers catalog"),
    ("Run_Operational_Register", "Execute operational registers, view interactive grids, and export to Excel/PDF"),
    ("Manage_Operational_Template", "Visually design, customize columns/groupings/geometry, and save tabular templates"),
    ("Print_PurchaseOrder", "Access contextual print modal and print Purchase Orders"),
    ("Print_Container", "Access contextual print modal and print Container gate passes / delivery notes"),
    ("Print_BillOfLanding", "Access contextual print modal and print Bill of Lading manifests"),
]


def run_reporting_permissions_migration(db: Session):
    """Ensures all 9 granular reporting permissions exist and are linked to Admin roles."""
    created_count = 0
    perm_objs = []

    for name, desc in NEW_REPORTING_PERMISSIONS:
        perm = db.query(Permission).filter(Permission.name == name).first()
        if not perm:
            perm = Permission(name=name, description=desc)
            db.add(perm)
            db.flush()
            created_count += 1
            logger.info("Migrated new permission: %s", name)
        else:
            if perm.description != desc:
                perm.description = desc
        perm_objs.append(perm)

    db.commit()

    # Link to admin roles
    admin_roles = db.query(Role).filter(
        (sqlfunc.lower(Role.name).in_(["admin", "administrator", "super_admin"])) &
        (Role.is_deleted == False)
    ).all()

    for r in admin_roles:
        existing_ids = {p.id for p in r.permissions}
        to_add = [p for p in perm_objs if p.id not in existing_ids]
        if to_add:
            r.permissions.extend(to_add)
            logger.info("Linked %d reporting permission(s) to role '%s'", len(to_add), r.name)

    db.commit()
    logger.info("Reporting permissions migration completed (Created: %d).", created_count)


if __name__ == "__main__":
    from Model.db import SessionLocal
    with SessionLocal() as session:
        run_reporting_permissions_migration(session)
