"""Developer-owned registry of every navigable screen in the application.

The registry is the join between the React router and the RBAC catalog:

* ``route`` must match a path declared in ``containermgmt/src/component/MainPage.js``.
* ``permission_codes`` / ``module_codes`` must mirror the ``PrivateRoute`` props on
  that same route, so navigation visibility can never be wider than the route guard.
* ``page_key`` is the stable identifier a menu item stores, so a route can be
  renamed in one place without touching any menu row.

This module is the single authoritative list. ``sync_page_registry`` is additive:
retired pages stay in the database as inactive rows so existing menu items keep a
valid foreign key and the audit trail survives.
"""
from dataclasses import dataclass
from typing import Optional, Sequence

from sqlalchemy.orm import Session

from .catalog import PERMISSION_BY_NAME

# Modules a tenant can subscribe to. Mirrors Organisation.modules.
KNOWN_MODULES = frozenset({"LOGISTICS", "ORDERS", "INVENTORY"})


@dataclass(frozen=True)
class PageGroup:
    """A default folder in the sidebar, used until an admin arranges their own."""
    group_key: str
    label: str
    icon: str
    sort_order: int


@dataclass(frozen=True)
class PageSpec:
    page_key: str
    route: str
    title: str
    default_icon: str
    group_key: Optional[str] = None
    # Any-of semantics, exactly like PrivateRoute requiredPermissions.
    # An empty tuple means "authenticated users only".
    permission_codes: tuple[str, ...] = ()
    # Any-of semantics, exactly like PrivateRoute requiredModules.
    module_codes: tuple[str, ...] = ()
    sort_order: int = 0


PAGE_GROUPS = [
    PageGroup("CORE", "Core", "LayoutDashboard", 10),
    PageGroup("PROCUREMENT", "Procurement", "ShoppingBag", 20),
    PageGroup("LOGISTICS", "Logistics & Stock", "Container", 30),
    PageGroup("REPORTING", "Print & Reports", "Printer", 40),
    PageGroup("MASTER_DATA", "Master Data", "Database", 50),
    PageGroup("SYSTEM", "System", "Settings", 60),
]

GROUP_BY_KEY = {group.group_key: group for group in PAGE_GROUPS}

# -- The registry ------------------------------------------------------------
# Permissions and modules below are transcribed from MainPage.js. Where a route
# is currently guarded by authentication alone the tuple is intentionally empty:
# the registry documents today's behaviour and never silently tightens a route.
PAGE_REGISTRY = [
    # Core
    PageSpec("DASHBOARD", "/dashboard", "Dashboard", "LayoutDashboard", "CORE",
             ("View_Dashboard",), (), 10),
    PageSpec("DASHBOARD_TEMPLATES", "/dashboard/templates", "Template Studio", "LayoutTemplate",
             "CORE", ("Manage_DashboardTemplate",), (), 20),

    # Procurement
    PageSpec("SOURCING", "/sourcing", "Requisitions & RFQs", "GitCompare", "PROCUREMENT",
             ("View_RFQ", "View_Order"), ("ORDERS",), 10),
    PageSpec("SOURCING_NEW", "/sourcing/new", "New Requisition", "FilePlus", "PROCUREMENT",
             ("Add_RFQ", "Add_Order"), ("ORDERS",), 20),
    PageSpec("STORE_REQUESTS", "/store-requests", "Store Requests", "ClipboardList", "PROCUREMENT",
             ("View_StoreRequest", "View_Order"), ("ORDERS",), 30),
    PageSpec("ORDERS", "/orders", "Purchase Orders", "ShoppingBag", "PROCUREMENT",
             ("View_Order",), ("ORDERS",), 40),
    PageSpec("ORDER_NEW", "/orders/new", "New Purchase Order", "FilePlus", "PROCUREMENT",
             ("Add_Order", "View_Order"), ("ORDERS",), 50),
    PageSpec("ORDER_QUOTES", "/orders/quotes", "Vendor Quotes & Bidding", "Gavel", "PROCUREMENT",
             ("Compare_Quote", "View_VendorQuote", "Send_RFQ", "View_Order"), ("ORDERS",), 60),
    PageSpec("ORDER_TEMPLATES", "/templates", "Order Templates", "LayoutTemplate", "PROCUREMENT",
             ("View_OrderTemplate", "Edit_OrderTemplate", "Add_OrderTemplate",
              "Delete_OrderTemplate", "View_Order", "Add_RFQ", "View_RFQ"), ("ORDERS",), 70),
    PageSpec("PACKING_LISTS", "/packing-lists", "Packing Lists", "PackageOpen", "PROCUREMENT",
             ("View_PackingList", "View_Order"), ("ORDERS",), 80),
    PageSpec("GOODS_RECEIVING", "/goods-receiving", "Goods Receiving", "PackageCheck", "PROCUREMENT",
             ("View_GoodsReceipt", "View_Order", "Verify_Receipt"), ("ORDERS",), 90),
    PageSpec("DAMAGE_DEFECTS", "/damage-defects", "Damage & Defects", "TriangleAlert", "PROCUREMENT",
             ("View_Defect", "View_Report", "View_Order"), ("LOGISTICS", "ORDERS"), 100),
    PageSpec("DAILY_OPERATIONS", "/daily-operations", "Daily Work & EOD", "CalendarCheck",
             "PROCUREMENT", ("View_DailyWork", "View_Order"), ("ORDERS",), 110),

    # Logistics & stock
    PageSpec("CONTAINER_REGISTER", "/viewContainer", "Container Register", "Container", "LOGISTICS",
             ("View_Container",), ("LOGISTICS",), 10),
    PageSpec("BILLS_OF_LADING", "/BillOfLanding", "Bills of Lading", "FileText", "LOGISTICS",
             ("View_BL",), ("LOGISTICS",), 20),
    PageSpec("CONTAINERS_COMPLETE", "/Complete", "Completed Containers", "PackageCheck", "LOGISTICS",
             ("View_Container",), ("LOGISTICS",), 30),
    PageSpec("INVENTORY_PRODUCTS", "/inventory", "Product Master", "Boxes", "LOGISTICS",
             ("View_Product", "View_Order"), ("INVENTORY",), 40),

    # Reporting
    PageSpec("REPORTS", "/reports", "Print & Reports", "Printer", "REPORTING",
             ("View_Report", "View_Order", "View_Container"), (), 10),
    PageSpec("REPORT_EDITOR_NEW", "/reports/editor/new", "New Report Template", "FilePlus",
             "REPORTING", ("Manage_Report_Template", "View_Report"), (), 20),

    # Master data
    PageSpec("MASTER_SUPPLIERS", "/master-data/suppliers", "Suppliers & Vendors", "Truck",
             "MASTER_DATA", ('View_MasterData', 'View_Order', 'View_Product'), (), 10),
    PageSpec("MASTER_CURRENCIES", "/master-data/currencies", "Currencies & FX Rates", "Coins",
             "MASTER_DATA", ('View_MasterData', 'View_Order', 'View_Product'), (), 20),
    PageSpec("MASTER_PAYMENT_TERMS", "/master-data/payment-terms", "Payment Terms", "Receipt",
             "MASTER_DATA", ('View_MasterData', 'View_Order', 'View_Product'), (), 30),
    PageSpec("MASTER_DOCUMENT_TYPES", "/master-data/document-types", "Document Types", "Files",
             "MASTER_DATA", ('View_MasterData', 'View_Order', 'View_Product'), (), 40),

    # System
    PageSpec("TENANT_CONSOLE", "/admin", "Tenant Console", "Shield", "SYSTEM",
             ("View_TenantConsole", "Manage_TenantConsole"), (), 10),
    PageSpec("SETTINGS_OVERVIEW", "/settings-overview", "Settings Overview", "Settings", "SYSTEM",
             ("View_Setting", "Edit_Setting"), (), 20),
    PageSpec("ORGANIZATION_SETTINGS", "/organization-settings", "Tenant & Org Console", "Building2",
             "SYSTEM", ("View_TenantConsole", "Manage_TenantConsole"), (), 30),
    PageSpec("SETTINGS_USERS", "/settings", "Users & Access", "Users", "SYSTEM",
             ("View_Setting", "Edit_Setting"), (), 40),
    PageSpec("ORDER_SETTINGS", "/order-settings", "Orders & Procurement", "SlidersHorizontal",
             "SYSTEM", ("View_Setting", "Edit_Setting"), ("ORDERS",), 50),
    PageSpec("LOGISTICS_SETTINGS", "/logistics", "Logistics & Demurrage", "Ship", "SYSTEM",
             ("View_Setting", "Edit_Setting"), ("LOGISTICS",), 60),
    PageSpec("REFERENCE_DATA", "/reference-data", "Reference Data", "ListTree", "SYSTEM",
             ("View_Setting", "Edit_Setting"), (), 70),
    PageSpec("MENU_DESIGNER", "/admin/menu", "Menus", "ListTree", "SYSTEM",
             ("View_Menu", "Manage_Menu"), (), 80),
]

PAGE_BY_KEY = {page.page_key: page for page in PAGE_REGISTRY}
PAGE_BY_ROUTE = {page.route: page for page in PAGE_REGISTRY}

# -- Registry integrity, enforced at import time -----------------------------
if len(PAGE_BY_KEY) != len(PAGE_REGISTRY):
    raise RuntimeError("Page registry contains duplicate page keys")
if len(PAGE_BY_ROUTE) != len(PAGE_REGISTRY):
    raise RuntimeError("Page registry contains duplicate routes")
for _page in PAGE_REGISTRY:
    if _page.group_key and _page.group_key not in GROUP_BY_KEY:
        raise RuntimeError(f"Page {_page.page_key} references unknown group {_page.group_key}")
    for _code in _page.permission_codes:
        if _code not in PERMISSION_BY_NAME:
            raise RuntimeError(
                f"Page {_page.page_key} requires permission '{_code}', "
                "which is not declared in the permission catalog"
            )
    for _module in _page.module_codes:
        if _module not in KNOWN_MODULES:
            raise RuntimeError(f"Page {_page.page_key} references unknown module {_module}")


def _derived_view_names(permission_name: str) -> tuple[str, ...]:
    """Names that imply a ``View_X`` permission, matching the frontend PrivateRoute.

    Only names declared in the permission catalog are returned, so the registry can
    never authorize an undeclared permission string.
    """
    if not permission_name.startswith("View_"):
        return ()
    suffix = permission_name[len("View_"):]
    candidates = (f"Edit_{suffix}", f"Add_{suffix}", f"Delete_{suffix}", suffix)
    return tuple(name for name in candidates if name in PERMISSION_BY_NAME)


def policy_allows_page(policy, page: PageSpec) -> bool:
    """Whether ``policy`` may see the navigation entry for ``page``.

    Visibility only. The route guard and the endpoint's own ``require_permission``
    remain the security boundary; this never widens either.
    """
    if getattr(policy, "is_platform_admin", False):
        return True

    if page.module_codes:
        module_names = getattr(policy, "module_names", frozenset())
        if not any(module in module_names for module in page.module_codes):
            return False

    if not page.permission_codes:
        return True

    for code in page.permission_codes:
        if policy.has(code):
            return True
        derived = _derived_view_names(code)
        if derived and policy.has_any(*derived):
            return True
    return False


def allowed_pages(policy, pages: Optional[Sequence[PageSpec]] = None) -> list[PageSpec]:
    """Every registry page the policy may navigate to, registry order preserved."""
    source = PAGE_REGISTRY if pages is None else pages
    return [page for page in source if policy_allows_page(policy, page)]


def sync_page_registry(db: Session) -> dict:
    """Upsert the registry into ``usercredentials.app_pages``.

    Additive: a page dropped from the registry is deactivated rather than deleted,
    so ``menu_items.page_key`` foreign keys and audit history stay intact.
    """
    from Model.Credentials.app_page import AppPage

    existing = {row.page_key: row for row in db.query(AppPage).all()}
    for page in PAGE_REGISTRY:
        row = existing.get(page.page_key)
        if row is None:
            row = AppPage(page_key=page.page_key)
            db.add(row)
            existing[page.page_key] = row
        row.route = page.route
        row.title = page.title
        row.default_icon = page.default_icon
        row.group_key = page.group_key
        row.permission_codes = list(page.permission_codes)
        row.module_codes = list(page.module_codes)
        row.sort_order = page.sort_order
        row.is_active = True

    for page_key, row in existing.items():
        if page_key not in PAGE_BY_KEY and row.is_active:
            row.is_active = False

    db.flush()
    return {page.page_key: existing[page.page_key] for page in PAGE_REGISTRY}
