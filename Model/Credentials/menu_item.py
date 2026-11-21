from sqlalchemy import Boolean, Column, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import relationship

from ..db import Base
from ..mixins import AuditMixin, OrgMixin


# TABLE: One entry (folder, separator or screen link) inside a menu. Controls what users SEE, not
#        what they may open.
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

    # id - INTEGER, primary key.
    # Unique row number.
    id = Column(Integer, primary_key=True)
    # menu_id - INTEGER, foreign key -> usercredentials.menus.id, required.
    # Menu this entry belongs to.
    menu_id = Column(
        Integer,
        ForeignKey("usercredentials.menus.id", ondelete="CASCADE"),
        nullable=False,
        index=False,
    )
    # parent_id - INTEGER, foreign key -> usercredentials.menu_items.id, optional.
    # Parent folder entry (NULL = top level).
    parent_id = Column(
        Integer,
        ForeignKey("usercredentials.menu_items.id", ondelete="CASCADE"),
        nullable=True,
    )
    # label - VARCHAR(100), required.
    # Text shown in the sidebar.
    label = Column(String(100), nullable=False)
    # icon - VARCHAR(50), optional.
    # Icon name shown beside the label.
    icon = Column(String(50), nullable=True)
    # page_key - VARCHAR(60), foreign key -> usercredentials.app_pages.page_key, optional.
    # Screen opened by this entry (NULL = folder).
    page_key = Column(
        String(60),
        ForeignKey("usercredentials.app_pages.page_key"),
        nullable=True,
    )
    # A separator is a section heading: a label with no route and no children.
    # Explicit, so headings appear only where an admin asked for one.
    # is_separator - BOOLEAN, required, default false.
    # True = section heading with no link or children.
    is_separator = Column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    # sort_order - INTEGER, required, default 0.
    # Display order; lower numbers appear first.
    sort_order = Column(Integer, nullable=False, default=0, server_default=text("0"))
    # is_active - BOOLEAN, required, default true.
    # False hides the entry.
    is_active = Column(Boolean, nullable=False, default=True, server_default=text("true"))

    # When the user lacks the page permission: hide the item (default) or show it
    # locked so the user can discover the feature and request access.
    # show_when_locked - BOOLEAN, required, default false.
    # True = show greyed-out when the user lacks permission, instead of hiding it.
    show_when_locked = Column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )

    # The tree is assembled in Python from one flat ordered query, so no
    # self-referential relationship is declared here (avoids per-node lazy loads).
    page = relationship("AppPage", lazy="joined", viewonly=True)
