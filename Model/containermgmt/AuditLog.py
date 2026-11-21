from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, JSON, func
from ..db import Base

# TABLE: Generic before/after ledger of data changes on any table.
class AuditLog(Base):
    """
    Central ledger to track the historical Before/After snapshots of data modifications.
    """
    __tablename__ = "audit_logs"
    __table_args__ = {'schema': 'containermgmt'}
    
    # log_id - INTEGER, primary key.
    # Unique log number.
    log_id = Column(Integer, primary_key=True, autoincrement=True)
    # table_name - VARCHAR(100), required.
    # Table that was changed.
    table_name = Column(String(100), nullable=False)
    # record_id - VARCHAR(100), required.
    # Key of the changed row (text, so UUIDs/composite keys fit).
    record_id = Column(String(100), nullable=False)  # String to support UUIDs or composite keys
    # action - VARCHAR(20), required.
    # CREATE, UPDATE or DELETE.
    action = Column(String(20), nullable=False) # 'CREATE', 'UPDATE', 'DELETE'
    # old_values - JSON, optional.
    # Row contents before the change (JSON).
    old_values = Column(JSON, nullable=True)
    # new_values - JSON, optional.
    # Row contents after the change (JSON).
    new_values = Column(JSON, nullable=True)
    
    # changed_by - INTEGER, foreign key -> usercredentials.users.id, optional.
    # User who made the change.
    changed_by = Column(Integer, ForeignKey('usercredentials.users.id'), nullable=True)
    # changed_at - TIMESTAMP WITH TIME ZONE, required.
    # When the change was made.
    changed_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
