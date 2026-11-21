from sqlalchemy import Column, String, Integer
from ...db import Base

from ...mixins import AuditMixin

# TABLE: LEGACY list of consignees; nothing reads it now (bills of lading point at organisations).
class Consignee(AuditMixin, Base):
    __tablename__ = 'consignee'
    __table_args__ = {'schema': 'containermgmt'}

    # consignee_id - INTEGER, primary key.
    # Unique consignee number.
    consignee_id = Column(Integer, primary_key=True)
    # consignee_name - VARCHAR(100), optional.
    # Consignee name.
    consignee_name = Column(String(100))
    # org_id - INTEGER, optional.
    # Organisation it was mapped to.
    org_id = Column(Integer, nullable=True)
    # code - VARCHAR(20), optional.
    # Short code.
    code = Column(String(20), nullable=True)

    # The reverse relation to bills of lading is gone: that column now holds an
    # organisation id. This table is retained only as a record of what was once
    # entered, and nothing reads it.
