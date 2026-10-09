from sqlalchemy import Column, ForeignKey, Integer, Table

from ..db import Base

# Which roles are served which menu.
#
# A role may be assigned to at most one menu, enforced by making role_id the
# primary key rather than the pair: with two menus claiming the same role there
# would be no non-arbitrary way to decide what that role sees. Assigning a role
# to a menu therefore moves it, rather than adding a second claim.
#
# A menu with no roles assigned is the organisation-wide one when published.
menu_roles = Table(
    "menu_roles",
    Base.metadata,
    Column(
        "role_id",
        Integer,
        ForeignKey("usercredentials.roles.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "menu_id",
        Integer,
        ForeignKey("usercredentials.menus.id", ondelete="CASCADE"),
        nullable=False,
        # The index is created by Utils/migrate_20261008_menu_roles.py; declaring
        # it here too would make a second index with a different name.
    ),
    schema="usercredentials",
)
