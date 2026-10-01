from sqlalchemy import Column, ForeignKey, Integer, Table

from ..db import Base


user_org_roles = Table(
    "user_org_roles",
    Base.metadata,
    Column(
        "user_id",
        Integer,
        ForeignKey("usercredentials.users.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "org_id",
        Integer,
        ForeignKey("usercredentials.organisations.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "role_id",
        Integer,
        ForeignKey("usercredentials.roles.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    schema="usercredentials",
)
