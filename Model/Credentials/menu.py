from sqlalchemy import Boolean, Column, Integer, String, text

from ..db import Base
from ..mixins import AuditMixin, OrgMixin


class Menu(Base, AuditMixin, OrgMixin):
    """A named navigation layout belonging to one organisation.

    A menu reaches people only through `menu_roles`: whoever holds an assigned
    role is served it, and anyone whose roles have no menu gets no sidebar.
    There is no organisation-wide default.

    A menu belongs to the company that made it unless `is_shared` is set, in
    which case it serves its roles in every company.

    `menu_items` rows belong to a menu, so editing one layout never disturbs
    another.
    """

    __tablename__ = "menus"
    __table_args__ = {"schema": "usercredentials"}

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    description = Column(String(255), nullable=True)

    # A shared menu serves its assigned roles in every company, the way a role
    # with no org_id belongs to every company. org_id still records who made it.
    is_shared = Column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
