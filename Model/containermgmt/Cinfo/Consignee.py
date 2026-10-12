from sqlalchemy import Column, String, Integer
from ...db import Base

from ...mixins import AuditMixin

class Consignee(AuditMixin, Base):
    __tablename__ = 'consignee'
    __table_args__ = {'schema': 'containermgmt'}

    consignee_id = Column(Integer, primary_key=True)
    consignee_name = Column(String(100))
    org_id = Column(Integer, nullable=True)
    code = Column(String(20), nullable=True)

    # The reverse relation to bills of lading is gone: that column now holds an
    # organisation id. This table is retained only as a record of what was once
    # entered, and nothing reads it.
