from sqlalchemy import Boolean, Column, Integer, String, text
from sqlalchemy.dialects.postgresql import ARRAY

from ..db import Base


# TABLE: Registry of every screen in the app (written by code at startup). Menu entries can only point at rows here.
class AppPage(Base):
    """Registry of every navigable screen, owned by developers.

    Rows are written only by ``auth.policy.page_registry.sync_page_registry`` at
    startup, exactly as permissions are synced from the permission catalog. The
    table is global, not tenant-scoped: a route and the permission it needs are
    properties of the application, not of an organisation.

    ``menu_items.page_key`` references this table, so an admin can never point a
    menu entry at a route that does not exist or that carries no permission.
    """

    __tablename__ = "app_pages"
    __table_args__ = {"schema": "usercredentials"}

    # page_key - VARCHAR(60), primary key.
    # Fixed internal name of the screen, e.g. DASHBOARD, ORDERS_LIST. Menus and code refer to
    # the screen by this name, so nothing breaks if its URL (route) is changed later.
    page_key = Column(String(60), primary_key=True)

    # route - VARCHAR(200), unique.
    # The web address of the screen in the frontend, e.g. /dashboard, /purchase-orders.
    # Two screens cannot share the same route.
    route = Column(String(200), nullable=False, unique=True)

    # title - VARCHAR(100).
    # Human-readable name of the screen, e.g. "Dashboard", "Purchase Orders".
    title = Column(String(100), nullable=False)

    # default_icon - VARCHAR(50), optional.
    # Icon shown in the sidebar when the menu entry does not pick its own,
    # e.g. LayoutDashboard, ShoppingBag.
    default_icon = Column(String(50), nullable=True)

    # group_key - VARCHAR(60), optional.
    # Section of the sidebar the screen is normally listed under, e.g. CORE, PROCUREMENT,
    # LOGISTICS, REPORTING, MASTER_DATA, SYSTEM. The menu designer can still move it.
    group_key = Column(String(60), nullable=True)

    # permission_codes - TEXT[] (list of text).
    # Permissions a user needs to open this screen. "Any-of": having just ONE of the listed
    # permissions is enough. An empty list means any logged-in user may open it.
    # Mirrors the PrivateRoute props on the matching frontend route.
    permission_codes = Column(ARRAY(String), nullable=False, server_default="{}")

    # module_codes - TEXT[] (list of text).
    # Modules the company must have switched on (organisations.modules) for the screen to be
    # available, e.g. LOGISTICS, ORDERS, INVENTORY. A company without the module never sees it.
    module_codes = Column(ARRAY(String), nullable=False, server_default="{}")

    # sort_order - INTEGER, default 0.
    # Default position of the screen inside its group; lower numbers are listed first.
    sort_order = Column(Integer, nullable=False, default=0, server_default=text("0"))

    # is_active - BOOLEAN, default true.
    # True = screen is live and can be opened and added to menus.
    # False = screen is switched off (kept in the table, but not navigable).
    is_active = Column(Boolean, nullable=False, default=True, server_default=text("true"))
