from sqlalchemy import Table, Column, Integer, ForeignKey
from ..db import Base

role_permissions = Table(
    'role_permissions',
    Base.metadata,
    Column('role_id', Integer, ForeignKey('usercredentials.roles.id'), primary_key=True),
    Column('permission_id', Integer, ForeignKey('usercredentials.permissions.id'), primary_key=True),
    schema='usercredentials'
)
