from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, JSON, func
from ..db import Base

class AuditLog(Base):
    """
    Central ledger to track the historical Before/After snapshots of data modifications.
    """
    __tablename__ = "audit_logs"
    __table_args__ = {'schema': 'containermgmt'}
    
    log_id = Column(Integer, primary_key=True, autoincrement=True)
    table_name = Column(String(100), nullable=False)
    record_id = Column(String(100), nullable=False)  # String to support UUIDs or composite keys
    action = Column(String(20), nullable=False) # 'CREATE', 'UPDATE', 'DELETE'
    old_values = Column(JSON, nullable=True)
    new_values = Column(JSON, nullable=True)
    
    changed_by = Column(Integer, ForeignKey('usercredentials.users.id'), nullable=True)
    changed_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
