from sqlalchemy import Boolean, Column, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import relationship

from ..db import Base
from ..mixins import AuditMixin, OrgMixin


class MenuItem(AuditMixin, OrgMixin, Base):
    """One entry in a named menu layout, arranged in the Menu Designer.

    Tenant-scoped, and owned by a `Menu`: an organisation may keep several
    layouts and publish one. A row with
    ``page_key = NULL`` is a folder; otherwise the row points at an
    ``app_pages`` entry that carries the route and the permissions it needs.

    This table controls what a user *sees*. It never decides what a user may
    *open* -- that stays with the route guard and the endpoint permission check.
    """

    __tablename__ = "menu_items"
    __table_args__ = (
        Index("ix_menu_items_menu_id", "menu_id"),
        Index("ix_menu_items_parent_id", "parent_id"),
        Index("ix_menu_items_page_key", "page_key"),
        {"schema": "usercredentials"},
    )

    id = Column(Integer, primary_key=True)
    menu_id = Column(
        Integer,
        ForeignKey("usercredentials.menus.id", ondelete="CASCADE"),
        nullable=False,
        index=False,
    )
    parent_id = Column(
        Integer,
        ForeignKey("usercredentials.menu_items.id", ondelete="CASCADE"),
        nullable=True,
    )
    label = Column(String(100), nullable=False)
    icon = Column(String(50), nullable=True)
    page_key = Column(
        String(60),
        ForeignKey("usercredentials.app_pages.page_key"),
        nullable=True,
    )
    # A separator is a section heading: a label with no route and no children.
    # Explicit, so headings appear only where an admin asked for one.
    is_separator = Column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    sort_order = Column(Integer, nullable=False, default=0, server_default=text("0"))
    is_active = Column(Boolean, nullable=False, default=True, server_default=text("true"))

    # When the user lacks the page permission: hide the item (default) or show it
    # locked so the user can discover the feature and request access.
    show_when_locked = Column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )

    # The tree is assembled in Python from one flat ordered query, so no
    # self-referential relationship is declared here (avoids per-node lazy loads).
    page = relationship("AppPage", lazy="joined", viewonly=True)
