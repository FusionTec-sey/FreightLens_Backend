from sqlalchemy import Boolean, Column, Integer, String, text
from sqlalchemy.dialects.postgresql import ARRAY

from ..db import Base


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

    page_key = Column(String(60), primary_key=True)
    route = Column(String(200), nullable=False, unique=True)
    title = Column(String(100), nullable=False)
    default_icon = Column(String(50), nullable=True)
    group_key = Column(String(60), nullable=True)

    # Any-of semantics, mirroring the PrivateRoute props on the matching route.
    # Empty array means the route is guarded by authentication alone.
    permission_codes = Column(ARRAY(String), nullable=False, server_default="{}")
    module_codes = Column(ARRAY(String), nullable=False, server_default="{}")

    sort_order = Column(Integer, nullable=False, default=0, server_default=text("0"))
    is_active = Column(Boolean, nullable=False, default=True, server_default=text("true"))
