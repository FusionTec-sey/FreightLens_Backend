from sqlalchemy import Table, Column, Integer, ForeignKey
from ..db import Base

user_roles = Table(
    'user_roles',
    Base.metadata,
    Column('user_id', Integer, ForeignKey('usercredentials.users.id'), primary_key=True),
    Column('role_id', Integer, ForeignKey('usercredentials.roles.id'), primary_key=True),
    schema='usercredentials'
)
