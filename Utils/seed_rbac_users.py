"""
RBAC & User Personas Seeding Script for FreightLens / Seychelles Sahaj
Seeds granular operational permissions, real-world business roles, and standard test accounts.
"""

import logging
from Model.db import SessionLocal
from Model.Credentials.Organisation import Organisation
from Model.Credentials.permissions import Permission
from Model.Credentials.roles import Role
from Model.Credentials.users import User
from auth.security import hash_password

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("seed_rbac")

# 1. Complete Catalog of Granular Operational Permissions
ALL_PERMISSIONS = {
    # ── Financials & Payment Ledger ──────────────────────────────────────────
    "View_Financials": "View confidential unit prices, line totals, advance/balance due, and vendor quotes",
    "Manage_Financials": "Full financial management authority across purchase orders and accounts",
    "Add_Payment": "Record milestone deposits, progress, and balance payments",
    "Edit_Payment": "Modify existing payment records in financial ledger",
    "Delete_Payment": "Void or delete ledger payment entries",
    "Approve_Variance": "Approve proforma invoice price variations against PO baselines",

    # ── Sourcing RFQs & Requisitions ─────────────────────────────────────────
    "View_RFQ": "View sourcing requests and RFQs in lists and detail pages",
    "Add_RFQ": "Create new sourcing requests and material requisitions",
    "Edit_RFQ": "Modify items, quantities, and operational specifications on RFQs",
    "Delete_RFQ": "Cancel or delete sourcing RFQs",

    # ── Purchase Orders ─────────────────────────────────────────────────────
    "View_Order": "View official purchase orders in lists and detail pages",
    "Add_Order": "Create new purchase orders",
    "Edit_Order": "Modify items, quantities, and operational specifications on orders",
    "Delete_Order": "Cancel or delete purchase orders",
    "Send_RFQ": "Dispatch RFQ to suppliers / Send for Quotation",
    "View_VendorQuote": "View vendor quotations and supplier price bids",
    "Add_VendorQuote": "Record supplier quotation bids and lead times",
    "Compare_Quote": "Access side-by-side quote comparison matrix and market rate analysis",
    "Approve_Quote": "Select winning vendor quote and award purchase order",
    "Issue_PO": "Transition approved quotation into an official binding Purchase Order",

    # ── Order Templates ─────────────────────────────────────────────────────
    "View_OrderTemplate": "View pre-defined order and sourcing blueprints/templates",
    "Add_OrderTemplate": "Create reusable order and RFQ templates",
    "Edit_OrderTemplate": "Modify line items, quantities, and vendor defaults in templates",
    "Delete_OrderTemplate": "Remove or archive order templates",

    # ── Logistics, Shipping & Containers ────────────────────────────────────
    "View_Container": "View sea freight containers and tracking milestones",
    "Add_Container": "Create container records for booking and dispatch",
    "Edit_Container": "Update vessel voyages, ETD, ETA, and container tracking statuses",
    "Delete_Container": "Remove container tracking entries",
    "View_BL": "View Bill of Lading (B/L) documents and consignments",
    "Add_BillOfLanding": "Create Bill of Lading entries",
    "Edit_BillOfLanding": "Modify Bill of Lading entries and shipping parameters",
    "Delete_BillOfLanding": "Delete Bill of Lading entries",
    "Add_PackingList": "Pack PO line items into sea containers",
    "Edit_PackingList": "Adjust packed quantities in containers",
    "Delete_PackingList": "Remove packing list assignments",
    "View_Demurrage": "Track port demurrage, free days, and detention fees",

    # ── Warehouse, GRN & Defect Management ──────────────────────────────────
    "View_GoodsReceipt": "View warehouse delivery receipts and goods receipt notes (GRN)",
    "Verify_Receipt": "Inspect dock arrivals against container packing lists",
    "Edit_Receipt": "Record received quantities, tallies, and dock notes",
    "Submit_Receipt": "Finalize Goods Receipt Note into central inventory",
    "Add_Defect": "Log damaged, broken, or missing goods upon dock receipt",
    "Edit_Defect": "Update defect details and photos",
    "Resolve_Defect": "Mark defects resolved, credited, or replaced by vendor",
    "Delete_Defect": "Delete defect records",

    # ── Site & Store Requests ───────────────────────────────────────────────
    "View_StoreRequest": "View site material demands and store requisitions",
    "Add_StoreRequest": "Create new store request for construction site / project",
    "Edit_StoreRequest": "Modify draft store request items and urgency",
    "Submit_StoreRequest": "Submit store request to central procurement for purchasing",
    "Withdraw_StoreRequest": "Withdraw or recall pending store request",
    "Delete_StoreRequest": "Delete draft store request",

    # ── Master Data & Administration ────────────────────────────────────────
    "View_Dashboard": "Access operational dashboard, KPI cards, and charts",
    "View_MasterData": "View currencies, FX rates, payment terms, and supplier profiles",
    "Edit_MasterData": "Configure currencies, exchange rates, payment term templates, and suppliers",
    "View_Supplier": "View supplier profiles and contact details",
    "Edit_Supplier": "Create and edit supplier profiles and attached terms",
    "View_Report": "View logistics, procurement, and inventory reports",
    "Generate_Report": "Export and generate analytical reports (Excel, PDF)",
    "Add_Report": "Create report templates",
    "Edit_Report": "Edit report templates",
    "Delete_Report": "Delete report templates",
    "View_User": "View system user accounts",
    "Add_User": "Create new user accounts",
    "Edit_User": "Update user profiles and password resets",
    "Delete_User": "Deactivate or delete user accounts",
    "View_Role": "View RBAC roles and assigned permission sets",
    "Add_Role": "Create new RBAC roles",
    "Edit_Role": "Modify role permission sets",
    "Delete_Role": "Delete custom roles",
    "View_Setting": "View system settings",
    "Edit_Setting": "Configure system settings",
    "View_TenantConsole": "Access multi-tenant organization console and company administration",
    "Manage_TenantConsole": "Configure organizations, tenant subsidiaries, company prefixes, and cross-tenant modules",

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

# 2. Role Definitions & Exact Permission Sets
ROLE_PERMISSIONS_MATRIX = {
    # ── 1. Super Admin (Global executive) ───────────────────────────────────
    "Super_Admin": list(ALL_PERMISSIONS.keys()),
    "Administrator": list(ALL_PERMISSIONS.keys()),

    # ── 2. Subsidiary / Tenant Admin (Noblecon) ─────────────────────────────
    "Noblecon_Admin": [
        "View_Dashboard",
        "View_RFQ", "Add_RFQ", "Edit_RFQ", "Delete_RFQ",
        "View_Order", "Add_Order", "Edit_Order", "Delete_Order",
        "Send_RFQ", "View_VendorQuote", "Add_VendorQuote", "Compare_Quote", "Approve_Quote", "Issue_PO",
        "View_OrderTemplate", "Add_OrderTemplate", "Edit_OrderTemplate", "Delete_OrderTemplate",
        "View_Financials", "Manage_Financials", "Add_Payment", "Edit_Payment", "Delete_Payment", "Approve_Variance",
        "View_Container", "Add_Container", "Edit_Container", "Delete_Container",
        "View_BL", "Add_BillOfLanding", "Edit_BillOfLanding", "Delete_BillOfLanding",
        "Add_PackingList", "Edit_PackingList", "Delete_PackingList", "View_Demurrage",
        "View_GoodsReceipt", "Verify_Receipt", "Edit_Receipt", "Submit_Receipt",
        "Add_Defect", "Edit_Defect", "Resolve_Defect", "Delete_Defect",
        "View_StoreRequest", "Add_StoreRequest", "Edit_StoreRequest", "Submit_StoreRequest", "Withdraw_StoreRequest", "Delete_StoreRequest",
        "View_MasterData", "Edit_MasterData",
        "View_Report", "Generate_Report", "View_User", "Add_User", "Edit_User", "Delete_User",
        "View_Role", "Add_Role", "Edit_Role", "Delete_Role",
        "View_TenantConsole", "Manage_TenantConsole",
        # Inventory Master
        "View_Product", "Add_Product", "Edit_Product", "Delete_Product",
        "Adjust_Stock", "View_ProductCategory", "Manage_ProductCategory",
        # Dashboard & Reports
        "Customize_Dashboard", "Manage_DashboardTemplate",
        "View_InventoryReport", "Export_Inventory",
    ],

    # ── 3. Procurement Specialist (Buyer / Sourcing) ────────────────────────
    "Procurement_Specialist": [
        "View_Dashboard",
        "View_RFQ", "Add_RFQ", "Edit_RFQ", "Delete_RFQ",
        "View_Order", "Add_Order", "Edit_Order", "Delete_Order",
        "Send_RFQ", "View_VendorQuote", "Add_VendorQuote", "Compare_Quote", "Approve_Quote", "Issue_PO",
        "View_OrderTemplate", "Add_OrderTemplate", "Edit_OrderTemplate", "Delete_OrderTemplate",
        "View_Financials", "Approve_Variance",
        "View_Container", "View_BL",
        "View_StoreRequest",
        "View_Supplier", "Edit_Supplier",
        "View_MasterData", "View_Report", "Generate_Report",
        # Inventory & Dashboard
        "View_Product", "Edit_Product", "View_ProductCategory",
        "Customize_Dashboard", "Export_Inventory",
    ],

    # ── 4. Finance & Accounts Controller ────────────────────────────────────
    "Finance_Controller": [
        "View_Dashboard",
        "View_Order", "View_RFQ", "View_OrderTemplate",
        "View_Financials", "Manage_Financials", "Add_Payment", "Edit_Payment", "Delete_Payment", "Approve_Variance",
        "View_VendorQuote", "Compare_Quote",
        "View_Container", "View_BL", "View_PackingList",
        "View_GoodsReceipt", "View_Defect", "Resolve_Defect",
        "View_MasterData", "Edit_MasterData",
        "View_Supplier",
        "View_Report", "Generate_Report",
        # Inventory & Dashboard
        "View_Product", "View_ProductCategory",
        "Customize_Dashboard", "View_InventoryReport",
    ],
    "Accounts_Finance": [
        "View_Dashboard",
        "View_Order", "View_RFQ", "View_OrderTemplate",
        "View_Financials", "Manage_Financials", "Add_Payment", "Edit_Payment", "Delete_Payment", "Approve_Variance",
        "View_VendorQuote", "Compare_Quote",
        "View_Container", "View_BL", "View_PackingList",
        "View_GoodsReceipt", "View_Defect", "Resolve_Defect",
        "View_MasterData", "Edit_MasterData",
        "View_Supplier",
        "View_Report", "Generate_Report",
        # Inventory & Dashboard
        "View_Product", "View_ProductCategory",
        "Customize_Dashboard", "View_InventoryReport",
    ],

    # ── 5. Logistics & Freight Coordinator ──────────────────────────────────
    # Note: Financials, Pricing, and Vendor Quotes are STRICTLY EXCLUDED
    "Logistics_Coordinator": [
        "View_Dashboard",
        "View_Order", # Operational only (item codes, descriptions, quantities)
        "View_Container", "Add_Container", "Edit_Container", "Delete_Container",
        "View_BL", "Add_BillOfLanding", "Edit_BillOfLanding", "Delete_BillOfLanding",
        "Add_PackingList", "Edit_PackingList", "Delete_PackingList",
        "View_Demurrage",
        "View_GoodsReceipt",
        "View_Supplier",
        "View_Report", "Generate_Report",
        # Inventory & Dashboard
        "View_Product", "View_ProductCategory", "Customize_Dashboard",
    ],
    "Delivery": [
        "View_Dashboard",
        "View_Order",
        "View_Container", "Edit_Container",
        "View_BL", "Add_PackingList", "Edit_PackingList", "View_Demurrage",
        "View_GoodsReceipt", "Verify_Receipt",
        "View_Report",
        # Inventory & Dashboard
        "View_Product", "Customize_Dashboard",
    ],

    # ── 6. Warehouse & Dock Supervisor ──────────────────────────────────────
    # Note: Financials, Pricing, and Vendor Quotes are STRICTLY EXCLUDED
    "Warehouse_Supervisor": [
        "View_Dashboard",
        "View_Order", # Operational item quantities only
        "View_Container", "View_PackingList",
        "View_GoodsReceipt", "Verify_Receipt", "Edit_Receipt", "Submit_Receipt",
        "Add_Defect", "Edit_Defect", "Resolve_Defect",
        "View_Report",
        # Inventory & Dashboard
        "View_Product", "Adjust_Stock", "View_ProductCategory",
        "Customize_Dashboard", "View_InventoryReport",
    ],
    "Warehouse_Operator": [
        "View_Dashboard",
        "View_Container", "View_PackingList",
        "View_GoodsReceipt", "Verify_Receipt", "Edit_Receipt", "Submit_Receipt",
        "Add_Defect", "Edit_Defect",
        # Inventory & Dashboard
        "View_Product", "Adjust_Stock", "Customize_Dashboard",
    ],

    # ── 7. Site Requisitioner / Storekeeper ──────────────────────────────────
    # Put request only: Can create and draft Sourcing RFQs / Store Requests, and use blueprints/templates
    "Site_Requisitioner": [
        "View_Dashboard",
        "View_StoreRequest", "Add_StoreRequest", "Edit_StoreRequest", "Submit_StoreRequest", "Withdraw_StoreRequest",
        "View_RFQ", "Add_RFQ", "Edit_RFQ", # Sourcing requests only
        "View_OrderTemplate", # Can use templates to draft RFQs
        "Add_Defect",
        # Inventory & Dashboard
        "View_Product", "View_ProductCategory", "Customize_Dashboard",
    ],
    "Store_User": [
        "View_Dashboard",
        "View_StoreRequest", "Add_StoreRequest", "Edit_StoreRequest", "Submit_StoreRequest", "Withdraw_StoreRequest",
        "View_RFQ", "Add_RFQ", "Edit_RFQ",
        "View_OrderTemplate",
        "Add_Defect",
        # Inventory & Dashboard
        "View_Product", "View_ProductCategory", "Customize_Dashboard",
    ],

    # ── 8. Auditor / Management Viewer ──────────────────────────────────────
    "Auditor_ReadOnly": [
        "View_Dashboard",
        "View_Order", "View_RFQ", "View_OrderTemplate", "View_Financials", "View_VendorQuote", "Compare_Quote",
        "View_Container", "View_BL", "View_PackingList",
        "View_GoodsReceipt", "View_Defect",
        "View_StoreRequest",
        "View_MasterData", "View_Supplier",
        "View_Report", "Generate_Report",
        "View_User", "View_Role",
        # Inventory & Dashboard
        "View_Product", "View_ProductCategory", "View_InventoryReport", "Customize_Dashboard",
    ],
    "viewer": [
        "View_Dashboard",
        "View_Order", "View_RFQ", "View_OrderTemplate", "View_Financials", "View_VendorQuote", "Compare_Quote",
        "View_Container", "View_BL", "View_PackingList",
        "View_GoodsReceipt", "View_Defect",
        "View_StoreRequest",
        "View_Report",
        # Inventory & Dashboard
        "View_Product", "View_ProductCategory", "Customize_Dashboard",
    ],
}

# 3. Standard Test Accounts with Known Credentials
TEST_USERS = [
    {
        "username": "admin_sahaj",
        "password": "Password@123",
        "role_name": "Super_Admin",
        "org_name": "sahaj",
        "org_id": 1,
        "description": "Root Holding Super Admin - unrestricted cross-tenant and financial authority"
    },
    {
        "username": "admin_noblecon",
        "password": "Password@123",
        "role_name": "Noblecon_Admin",
        "org_name": "noblecon",
        "org_id": 2,
        "description": "Subsidiary Tenant Admin - complete management strictly isolated to Noblecon"
    },
    {
        "username": "buyer_sahaj",
        "password": "Password@123",
        "role_name": "Procurement_Specialist",
        "org_name": "sahaj",
        "org_id": 1,
        "description": "Procurement Buyer - RFQs, quotes, price negotiations, awarding POs (no bank payments)"
    },
    {
        "username": "finance_sahaj",
        "password": "Password@123",
        "role_name": "Finance_Controller",
        "org_name": "sahaj",
        "org_id": 1,
        "description": "Finance Controller - full financial visibility, payment ledger, clearance (no shipping edits)"
    },
    {
        "username": "logistics_sahaj",
        "password": "Password@123",
        "role_name": "Logistics_Coordinator",
        "org_name": "sahaj",
        "org_id": 1,
        "description": "Logistics Officer - container tracking, B/L, sea freight (PRICES & FINANCIALS REDACTED)"
    },
    {
        "username": "warehouse_sahaj",
        "password": "Password@123",
        "role_name": "Warehouse_Supervisor",
        "org_name": "sahaj",
        "org_id": 1,
        "description": "Dock Supervisor - GRN receipts, tallies, defects (PRICES & FINANCIALS REDACTED)"
    },
    {
        "username": "site_engineer",
        "password": "Password@123",
        "role_name": "Site_Requisitioner",
        "org_name": "sahaj",
        "org_id": 1,
        "description": "Site Requisitioner - creates store requests from construction sites (no quotes/costs)"
    },
    {
        "username": "auditor_sahaj",
        "password": "Password@123",
        "role_name": "Auditor_ReadOnly",
        "org_name": "sahaj",
        "org_id": 1,
        "description": "Auditor - read-only oversight across all modules (all edit/add/delete disabled)"
    },
]

# Legacy users mapping
EXISTING_USERS_FIX = {
    "Accounts": {"role": "Finance_Controller", "org_id": 1},
    "Noblecon": {"role": "Noblecon_Admin", "org_id": 2},
    "Delivary": {"role": "Logistics_Coordinator", "org_id": 1},
    "parth": {"role": "Super_Admin", "org_id": 1},
    "noble_admin": {"role": "Noblecon_Admin", "org_id": 2},
}


def seed_rbac():
    db = SessionLocal()
    try:
        logger.info("=== 1. Seeding Granular Permissions ===")
        perm_map = {}
        for perm_name, perm_desc in ALL_PERMISSIONS.items():
            existing = db.query(Permission).filter_by(name=perm_name).first()
            if not existing:
                existing = Permission(name=perm_name, description=perm_desc)
                db.add(existing)
                db.flush()
                logger.info("  [+] Added Permission: %s", perm_name)
            else:
                existing.description = perm_desc
            perm_map[perm_name] = existing
        db.commit()

        logger.info("=== 2. Seeding Roles & Binding Permissions ===")
        role_map = {}
        for role_name, perm_list in ROLE_PERMISSIONS_MATRIX.items():
            role = db.query(Role).filter_by(name=role_name).first()
            if not role:
                role = Role(name=role_name)
                db.add(role)
                db.flush()
                logger.info("  [+] Added Role: %s", role_name)

            # Bind assigned permissions
            bound_perms = [perm_map[p_name] for p_name in perm_list if p_name in perm_map]
            role.permissions = bound_perms
            role_map[role_name] = role
        db.commit()

        logger.info("=== 3. Seeding Test Users (Password: Password@123) ===")
        default_pwd_hash = hash_password("Password@123")

        for u_data in TEST_USERS:
            username = u_data["username"]
            role_name = u_data["role_name"]
            org_id = u_data["org_id"]

            user = db.query(User).filter_by(username=username).first()
            if not user:
                user = User(
                    username=username,
                    password_hash=default_pwd_hash,
                    org_id=org_id,
                )
                db.add(user)
                db.flush()
                logger.info("  [+] Created User: %s (Org ID: %d, Role: %s)", username, org_id, role_name)
            else:
                user.password_hash = default_pwd_hash
                user.org_id = org_id

            # Bind Role
            target_role = role_map.get(role_name)
            if target_role and target_role not in user.roles:
                user.roles = [target_role]
            logger.info("  [*] User %s configured with role %s", username, role_name)

        # Fix legacy users
        logger.info("=== 4. Updating Legacy Users ===")
        for leg_username, leg_config in EXISTING_USERS_FIX.items():
            leg_user = db.query(User).filter_by(username=leg_username).first()
            if leg_user:
                leg_user.org_id = leg_config["org_id"]
                target_role = role_map.get(leg_config["role"])
                if target_role:
                    leg_user.roles = [target_role]
                # Also reset password to Password@123 for testing convenience
                leg_user.password_hash = default_pwd_hash
                logger.info("  [*] Fixed legacy user '%s' -> Role: %s, Org: %d", leg_username, leg_config["role"], leg_config["org_id"])

        db.commit()
        logger.info("=== RBAC & User Seeding Complete! ===")

    except Exception as e:
        db.rollback()
        logger.error("Failed to seed RBAC users: %s", e, exc_info=True)
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed_rbac()
