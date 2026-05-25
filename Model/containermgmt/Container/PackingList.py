from sqlalchemy import Column, String, Integer

from ...db import Base

from ...mixins import AuditMixin

class PackingList(AuditMixin, Base):
    __tablename__ = 'packing_list'
    __table_args__ = {'schema': 'containermgmt'}

    container_id = Column(Integer, primary_key=True)
    packing_list = Column(String(45))