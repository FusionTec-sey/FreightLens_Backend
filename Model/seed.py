import logging
from datetime import date
from sqlalchemy import func as sqlfunc
from sqlalchemy.orm import Session
from Model.Credentials.users import User
from Model.Credentials.roles import Role
from Model.Credentials.permissions import Permission
from Model.containermgmt.Cinfo.Status import Status
from Model.containermgmt.Orders.OrderStatus import OrderStatus
from Model.containermgmt.Orders.PurchaseOrder import PurchaseOrder
from auth.security import hash_password

logger = logging.getLogger("containerMgmt.seed")

# ── Required permissions ───────────────────────────────────────────────────────
# Each entry: (name, description)
# Naming convention: <Action>_<Resource>
DEFAULT_PERMISSIONS = [
    # ── Sidebar / Page views ──────────────────────────────────────────────────
    ("View_Dashboard",       "View dashboard and summary stats"),
    ("View_Container",       "View containers list and sections"),
    ("View_BL",              "View Bills of Lading list"),
    ("View_Report",          "View reports list"),
    ("View_Order",           "View Purchase Orders list and tracking"),
    ("View_StoreRequest",    "View Store Requests list"),
    ("View_PackingList",     "View Packing Lists"),
    ("View_GoodsReceipt",    "View Goods Receiving and receipts"),
    ("View_Defect",          "View Damage & Defects reports"),
    ("View_OrderDocument",   "View central document manager"),
    ("View_DailyWork",       "View daily operations work queue"),
    ("View_EODReport",       "View and export End-of-Day management reports"),
    ("View_Setting",         "View settings menu and sub-pages"),
    ("View_User",            "View user accounts"),
    ("View_Role",            "View roles and their permissions"),

    # ── Store Request actions ─────────────────────────────────────────────────
    ("Add_StoreRequest",     "Create a new store request draft"),
    ("Edit_StoreRequest",    "Edit an existing store request draft"),
    ("Submit_StoreRequest",  "Submit a store request for sourcing"),
    ("Withdraw_StoreRequest","Withdraw a store request before PO"),
    ("Delete_StoreRequest",  "Delete a store request draft"),

    # ── Purchase Order actions ────────────────────────────────────────────────
    ("Add_Order",            "Create and generate a purchase order"),
    ("Edit_Order",           "Edit an existing purchase order"),
    ("Delete_Order",         "Delete a purchase order"),
    ("Manage_Financials",    "View and edit confidential pricing and payment terms"),

    # ── Payment actions ───────────────────────────────────────────────────────
    ("Add_Payment",          "Record advance, progress, or balance payments"),
    ("Edit_Payment",         "Edit payment records"),
    ("Delete_Payment",       "Delete payment records"),

    # ── Packing List actions ──────────────────────────────────────────────────
    ("Add_PackingList",      "Create or import a supplier packing list"),
    ("Edit_PackingList",     "Edit a packing list"),
    ("Delete_PackingList",   "Delete a packing list"),

    # ── Goods Receiving actions ───────────────────────────────────────────────
    ("Verify_Receipt",       "Perform warehouse verification and receiving"),
    ("Edit_Receipt",         "Edit receiving drafts"),
    ("Submit_Receipt",       "Submit finalized goods receipt"),

    # ── Damage & Defects actions ──────────────────────────────────────────────
    ("Add_Defect",           "Report a receiving defect or container damage"),
    ("Edit_Defect",          "Edit defect report"),
    ("Resolve_Defect",       "Mark defect as resolved / closed with resolution type"),
    ("Delete_Defect",        "Delete a defect report"),

    # ── Order Documents ───────────────────────────────────────────────────────
    ("Upload_Document",      "Upload supporting documents to requests/POs"),
    ("Delete_Document",      "Delete supporting documents"),

    # ── Container actions ─────────────────────────────────────────────────────
    ("Add_Container",        "Create a new container"),
    ("Edit_Container",       "Edit an existing container"),
    ("Delete_Container",     "Delete a container and its data"),

    # ── Bill of Lading actions ────────────────────────────────────────────────
    ("Add_BillOfLanding",    "Add a new Bill of Lading"),
    ("Edit_BillOfLanding",   "Edit an existing Bill of Lading"),
    ("Delete_BillOfLanding", "Delete a Bill of Lading"),

    # ── Report actions ────────────────────────────────────────────────────────
    ("Add_Report",           "Add a new damage report"),
    ("Edit_Report",          "Edit an existing damage report"),
    ("Delete_Report",        "Delete a damage report"),
    ("Generate_Report",      "Generate report files / PDFs"),

    # ── User management ───────────────────────────────────────────────────────
    ("Add_User",             "Create a new user account"),
    ("Edit_User",            "Update an existing user account"),
    ("Delete_User",          "Delete a user account"),

    # ── Role management ───────────────────────────────────────────────────────
    ("Add_Role",             "Create a new role"),
    ("Edit_Role",            "Update an existing role"),
    ("Delete_Role",          "Delete a role"),

    # ── Settings actions ──────────────────────────────────────────────────────
    ("Edit_Setting",         "Update logistics provider settings"),

    # ── Reference data ────────────────────────────────────────────────────────
    ("Add_RefData",          "Add reference data items"),
    ("Edit_RefData",         "Edit reference data items"),
    ("Delete_RefData",       "Delete reference data items"),

    # ── Column visibility: Container list ─────────────────────────────────────
    ("View_ContainerId",     "View Container ID column"),
    ("View_Supplier",        "View Supplier column"),
    ("View_ArrivalDate",     "View Arrival Date column"),
    ("View_EmptyAt",         "View Empty At column"),
    ("View_Demurrage",       "View Demurrage column"),
    ("View_Status",          "View Status column"),
    ("View_Material",        "View Materials column"),
    ("View_Consignee",       "View Consignee column"),

    # ── Column visibility: Report list ────────────────────────────────────────
    ("View_ReportId",        "View Report ID column"),
    ("View_ContainerNo",     "View Container No column"),

    # ── Column visibility: BL detail ──────────────────────────────────────────
    ("View_container_no",    "View Container No in BL"),
    ("View_status",          "View Status in BL"),
    ("View_location",        "View Location in BL"),
    ("View_weight",          "View Weight in BL"),
    ("View_demurrage",       "View Demurrage in BL"),

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

# ── Agreed 14 (+1 Defect/Reopened) Procurement Lifecycle Statuses ─────────────
DEFAULT_ORDER_STATUSES = [
    (1,  "Draft",             "DRAFT",           1,  5,   "bg-slate-400",  "bg-slate-100 text-slate-700 border-slate-300"),
    (2,  "Submitted",         "SUBMITTED",       2,  10,  "bg-blue-400",   "bg-blue-100 text-blue-700 border-blue-300"),
    (3,  "Sourcing",          "SOURCING",        3,  20,  "bg-indigo-400", "bg-indigo-100 text-indigo-700 border-indigo-300"),
    (4,  "Ordered",           "ORDERED",         4,  30,  "bg-purple-500", "bg-purple-100 text-purple-700 border-purple-300"),
    (5,  "Part Paid",         "PART_PAID",       5,  40,  "bg-amber-500",  "bg-amber-100 text-amber-800 border-amber-300"),
    (6,  "Paid",              "PAID",            6,  50,  "bg-teal-500",   "bg-teal-100 text-teal-800 border-teal-300"),
    (7,  "In Production",     "IN_PRODUCTION",   7,  60,  "bg-orange-500", "bg-orange-100 text-orange-800 border-orange-300"),
    (8,  "Ready",             "READY",           8,  70,  "bg-yellow-500", "bg-yellow-100 text-yellow-800 border-yellow-300"),
    (9,  "Packed",            "PACKED",          9,  75,  "bg-lime-500",   "bg-lime-100 text-lime-800 border-lime-300"),
    (10, "Shipped",           "SHIPPED",         10, 85,  "bg-cyan-500",   "bg-cyan-100 text-cyan-800 border-cyan-300"),
    (11, "Arrived",           "ARRIVED",         11, 92,  "bg-blue-600",   "bg-blue-100 text-blue-800 border-blue-300"),
    (12, "Received",          "RECEIVED",        12, 96,  "bg-emerald-500","bg-emerald-100 text-emerald-800 border-emerald-300"),
    (13, "Completed",         "COMPLETED",       13, 100, "bg-emerald-600","bg-emerald-100 text-emerald-800 border-emerald-300"),
    (14, "Cancelled",         "CANCELLED",       14, 0,   "bg-red-500",    "bg-red-100 text-red-800 border-red-300"),
    (15, "Defect / Reopened", "DEFECT_REOPENED", 15, 95,  "bg-rose-500",   "bg-rose-100 text-rose-800 border-rose-300"),
]

def seed_db(db: Session):
    try:
        logger.info("Checking database seeding...")

        # ── 1. Seed / backfill Permissions ────────────────────────────────────
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

        # ── 2. Seed Container Statuses ─────────────────────────────────────────
        for status_id, status_name in DEFAULT_STATUSES:
            status = db.query(Status).filter(Status.status_id == status_id).first()
            if not status:
                status = Status(status_id=status_id, name=status_name)
                db.add(status)
                logger.info("Seeded container status: %d - %s", status_id, status_name)

        db.flush()

        # ── 3. Seed / Update Order Workflow Statuses ──────────────────────────
        for status_id, name, code, seq, progress, color, badge_color in DEFAULT_ORDER_STATUSES:
            order_st = db.query(OrderStatus).filter(
                (OrderStatus.code == code) | (OrderStatus.name == name)
            ).first()
            if not order_st:
                order_st = OrderStatus(
                    name=name,
                    code=code,
                    sequence_order=seq,
                    progress=progress,
                    color=color,
                    badge_color=badge_color,
                    is_active=True
                )
                db.add(order_st)
                logger.info("Seeded new order workflow status: %s (%s)", name, code)
            else:
                # Update attributes if existing
                order_st.name = name
                order_st.code = code
                order_st.sequence_order = seq
                order_st.progress = progress
                order_st.color = color
                order_st.badge_color = badge_color
                order_st.is_active = True

        db.flush()

        # ── 4. Seed / sync Roles ──────────────────────────────────────────────
        all_perms = db.query(Permission).all()

        # Admin role: owns every permission (including newly added ones)
        admin_role = db.query(Role).filter(Role.name == "admin").first()
        if not admin_role:
            admin_role = Role(name="admin")
            db.add(admin_role)
            db.flush()
            logger.info("Seeded role: admin")

        existing_admin_perm_ids = {p.id for p in admin_role.permissions}
        new_admin_perms = [p for p in all_perms if p.id not in existing_admin_perm_ids]
        if new_admin_perms:
            admin_role.permissions.extend(new_admin_perms)
            logger.info("Linked %d new permission(s) to admin role", len(new_admin_perms))

        # Sync existing "Administrator" role
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
                logger.info("Linked %d missing permission(s) to 'Administrator' role", len(missing))

        # Accounts / Finance role
        accounts_role = db.query(Role).filter(Role.name == "Accounts_Finance").first()
        if not accounts_role:
            accounts_role = Role(name="Accounts_Finance")
            db.add(accounts_role)
            db.flush()
            logger.info("Seeded role: Accounts_Finance")

        accounts_perm_names = [
            "View_Dashboard", "View_Order", "Add_Order", "Edit_Order", "Manage_Financials",
            "Add_Payment", "Edit_Payment", "View_OrderPayment", "View_PackingList", "Add_PackingList",
            "Edit_PackingList", "View_GoodsReceipt", "View_Defect", "Resolve_Defect",
            "View_OrderDocument", "Upload_Document", "Delete_Document", "View_DailyWork", "View_EODReport",
            "View_Container", "View_BL", "View_Report"
        ]
        accounts_perms = [p for p in all_perms if p.name in accounts_perm_names]
        accounts_role.permissions = accounts_perms

        # Store User role (Store requests only, NO supplier info, NO prices/payments)
        store_role = db.query(Role).filter(Role.name == "Store_User").first()
        if not store_role:
            store_role = Role(name="Store_User")
            db.add(store_role)
            db.flush()
            logger.info("Seeded role: Store_User")

        store_perm_names = [
            "View_Dashboard", "View_StoreRequest", "Add_StoreRequest", "Edit_StoreRequest",
            "Submit_StoreRequest", "Withdraw_StoreRequest", "View_Order", "View_Defect", "Add_Defect"
        ]
        store_perms = [p for p in all_perms if p.name in store_perm_names]
        store_role.permissions = store_perms

        # Warehouse Operator role (Receipt verification, packing lists, defect reporting)
        warehouse_role = db.query(Role).filter(Role.name == "Warehouse_Operator").first()
        if not warehouse_role:
            warehouse_role = Role(name="Warehouse_Operator")
            db.add(warehouse_role)
            db.flush()
            logger.info("Seeded role: Warehouse_Operator")

        warehouse_perm_names = [
            "View_Dashboard", "View_Container", "View_GoodsReceipt", "Verify_Receipt",
            "Edit_Receipt", "Submit_Receipt", "View_PackingList", "View_Defect", "Add_Defect", "Edit_Defect"
        ]
        warehouse_perms = [p for p in all_perms if p.name in warehouse_perm_names]
        warehouse_role.permissions = warehouse_perms

        # Viewer role: view-only permissions
        viewer_role = db.query(Role).filter(Role.name == "viewer").first()
        if not viewer_role:
            viewer_role = Role(name="viewer")
            db.add(viewer_role)
            db.flush()
            logger.info("Seeded role: viewer")

        view_perms = [p for p in all_perms if p.name.startswith("View_")]
        viewer_role.permissions = view_perms

        db.flush()

        # ── 5. Seed default Admin User if no users exist ─────────────────────
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
