# models/status.py

from sqlalchemy import Column, Integer, String
from ...db import Base  # Adjust the import based on your project structure

from ...mixins import AuditMixin

# TABLE: Lookup list of container/bill statuses (In Transit, On Port, Complete...).
class Status(AuditMixin, Base):
    __tablename__ = "status"
    __table_args__ = {'schema': 'containermgmt'}
    
    # status_id - INTEGER, primary key.
    # Unique status number.
    status_id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    # name - VARCHAR(45), optional.
    # Status name.
    name = Column(String(45), nullable=True)
