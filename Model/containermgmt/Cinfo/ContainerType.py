from sqlalchemy import Column, String, Integer

from ...db import Base


from ...mixins import AuditMixin

class ContainerType(AuditMixin, Base):
    __tablename__ = 'container_type'
    __table_args__ = {'schema': 'containermgmt'}

    type_id = Column(Integer, primary_key=True)
    type = Column(String(45))
