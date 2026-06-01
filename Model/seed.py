import logging
from sqlalchemy import func as sqlfunc
from sqlalchemy.orm import Session
from Model.Credentials.users import User
from Model.Credentials.roles import Role
from Model.Credentials.permissions import Permission
from Model.containermgmt.Cinfo.Status import Status
from auth.security import hash_password

logger = logging.getLogger("containerMgmt.seed")

# ── Required permissions ───────────────────────────────────────────────────────
# Each entry: (name, description)
# Naming convention: <Action>_<Resource>
DEFAULT_PERMISSIONS = [
    # ── Sidebar / Page views ──────────────────────────────────────────────────
    ("View_Dashboard",   "View dashboard and summary stats"),
    ("View_Container",   "View containers list and sections"),
    ("View_BL",          "View Bills of Lading list"),
    ("View_Report",      "View reports list"),
    ("View_Setting",     "View settings menu and sub-pages"),
    ("View_User",        "View user accounts"),
    ("View_Role",        "View roles and their permissions"),

    # ── Container actions ─────────────────────────────────────────────────────
    ("Add_Container",    "Create a new container"),
    ("Edit_Container",   "Edit an existing container"),
    ("Delete_Container", "Delete a container and its data"),

    # ── Bill of Lading actions ────────────────────────────────────────────────
    ("Add_BillOfLanding",    "Add a new Bill of Lading"),
    ("Edit_BillOfLanding",   "Edit an existing Bill of Lading"),
    ("Delete_BillOfLanding", "Delete a Bill of Lading"),

    # ── Report actions ────────────────────────────────────────────────────────
    ("Add_Report",      "Add a new damage report"),
    ("Edit_Report",     "Edit an existing damage report"),
    ("Delete_Report",   "Delete a damage report"),
    ("Generate_Report", "Generate report files / PDFs"),

    # ── User management ───────────────────────────────────────────────────────
    ("Add_User",    "Create a new user account"),
    ("Edit_User",   "Update an existing user account"),
    ("Delete_User", "Delete a user account"),

    # ── Role management ───────────────────────────────────────────────────────
    ("Add_Role",    "Create a new role"),
    ("Edit_Role",   "Update an existing role"),
    ("Delete_Role", "Delete a role"),

    # ── Settings actions ──────────────────────────────────────────────────────
    ("Edit_Setting", "Update logistics provider settings"),

    # ── Reference data ────────────────────────────────────────────────────────
    ("Add_RefData",    "Add reference data items"),
    ("Edit_RefData",   "Edit reference data items"),
    ("Delete_RefData", "Delete reference data items"),

    # ── Column visibility: Container list ─────────────────────────────────────
    ("View_ContainerId",  "View Container ID column"),
    ("View_Supplier",     "View Supplier column"),
    ("View_ArrivalDate",  "View Arrival Date column"),
    ("View_EmptyAt",      "View Empty At column"),
    ("View_Demurrage",    "View Demurrage column"),
    ("View_Status",       "View Status column"),
    ("View_Material",     "View Materials column"),
    ("View_Consignee",    "View Consignee column"),

    # ── Column visibility: Report list ────────────────────────────────────────
    ("View_ReportId",    "View Report ID column"),
    ("View_ContainerNo", "View Container No column"),

    # ── Column visibility: BL detail ──────────────────────────────────────────
    ("View_container_no", "View Container No in BL"),
    ("View_status",       "View Status in BL"),
    ("View_location",     "View Location in BL"),
    ("View_weight",       "View Weight in BL"),
    ("View_demurrage",    "View Demurrage in BL"),

    # ── Column visibility: BL list ────────────────────────────────────────────
    ("View_BillOfLanding",   "View BL Number column"),
    ("View_vessel_name",     "View Vessel Name column"),
    ("View_consignee_name",  "View Consignee Name column"),
    ("View_arrivalDate",     "View Arrival Date in BL list"),
]

DEFAULT_STATUSES = [
    (1, "In Transit"),
    (2, "On Port"),
    (3, "Gate Pass"),
    (4, "Complete"),
    (6, "Inbound"),
    (7, "Empty"),
    (8, "Unknown")
]

def seed_db(db: Session):
    try:
        logger.info("Checking database seeding...")

        # ── 1. Seed / backfill Permissions ────────────────────────────────────
        # Always upsert — this ensures new permissions added to DEFAULT_PERMISSIONS
        # are created even on an existing database.
        permissions_map = {}
        new_perm_count = 0
        for perm_name, perm_desc in DEFAULT_PERMISSIONS:
            perm = db.query(Permission).filter(Permission.name == perm_name).first()
            if not perm:
                perm = Permission(name=perm_name, description=perm_desc)
                db.add(perm)
                db.flush()
                new_perm_count += 1
                logger.info("Seeded NEW permission: %s", perm_name)
            permissions_map[perm_name] = perm

        if new_perm_count:
            logger.info("Added %d new permission(s) to the database.", new_perm_count)
        else:
            logger.info("All permissions are already present — no new permissions added.")

        # ── 2. Seed Statuses ──────────────────────────────────────────────────
        for status_id, status_name in DEFAULT_STATUSES:
            status = db.query(Status).filter(Status.status_id == status_id).first()
            if not status:
                status = Status(status_id=status_id, name=status_name)
                db.add(status)
                logger.info("Seeded status: %d - %s", status_id, status_name)

        db.flush()

        # ── 3. Seed / sync Roles ──────────────────────────────────────────────
        all_perms = db.query(Permission).all()

        # Admin role: owns every permission (including newly added ones)
        admin_role = db.query(Role).filter(Role.name == "admin").first()
        if not admin_role:
            admin_role = Role(name="admin")
            db.add(admin_role)
            db.flush()
            logger.info("Seeded role: admin")

        # Always sync — guarantees new permissions are bound to admin
        existing_admin_perm_ids = {p.id for p in admin_role.permissions}
        new_admin_perms = [p for p in all_perms if p.id not in existing_admin_perm_ids]
        if new_admin_perms:
            admin_role.permissions.extend(new_admin_perms)
            logger.info(
                "Linked %d new permission(s) to admin role: %s",
                len(new_admin_perms),
                [p.name for p in new_admin_perms],
            )

        # ── Sync existing "Administrator" role (created outside of seed) ──────
        # Finds any role whose name is "Administrator" (case-insensitive) and
        # ensures it holds every permission — without creating a new role.
        administrator_role = (
            db.query(Role)
            .filter(sqlfunc.lower(Role.name) == "administrator", Role.is_deleted == False)
            .first()
        )
        if administrator_role:
            existing_ids = {p.id for p in administrator_role.permissions}
            missing = [p for p in all_perms if p.id not in existing_ids]
            if missing:
                administrator_role.permissions.extend(missing)
                logger.info(
                    "Linked %d missing permission(s) to 'Administrator' role: %s",
                    len(missing),
                    [p.name for p in missing],
                )
            else:
                logger.info("'Administrator' role already has all permissions.")
        else:
            logger.info("No 'Administrator' role found in DB — skipping.")

        # Viewer role: view-only permissions
        viewer_role = db.query(Role).filter(Role.name == "viewer").first()
        if not viewer_role:
            viewer_role = Role(name="viewer")
            db.add(viewer_role)
            db.flush()
            logger.info("Seeded role: viewer")

        view_perms = [p for p in all_perms if p.name.startswith("View_")]
        existing_viewer_perm_ids = {p.id for p in viewer_role.permissions}
        new_viewer_perms = [p for p in view_perms if p.id not in existing_viewer_perm_ids]
        if new_viewer_perms:
            viewer_role.permissions.extend(new_viewer_perms)
            logger.info(
                "Linked %d new View_* permission(s) to viewer role: %s",
                len(new_viewer_perms),
                [p.name for p in new_viewer_perms],
            )

        db.flush()

        # ── 4. Seed default Admin User if no users exist ─────────────────────
        user_count = db.query(User).count()
        if user_count == 0:
            admin_user = User(
                username="admin",
                password_hash=hash_password("admin123")
            )
            admin_user.roles = [admin_role]
            db.add(admin_user)
            logger.info("Seeded default admin user: admin / admin123")

        db.commit()
        logger.info("Database seeding checked and completed successfully.")

    except Exception as e:
        db.rollback()
        logger.exception("Error during database seeding: %s", e)
        raise e
