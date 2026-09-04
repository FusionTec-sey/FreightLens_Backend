from sqlalchemy import Column, Integer, BigInteger, String, DateTime, Text, ForeignKey, func
from ..db import Base

class SessionAudit(Base):
    """
    Central ledger to track user logins, logouts, session information, and IP addresses.
    """
    __tablename__ = "session_audit"
    __table_args__ = {'schema': 'usercredentials'}
    
    session_id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('usercredentials.users.id'), nullable=True)
    login_time = Column(DateTime, nullable=True)
    logout_time = Column(DateTime, nullable=True)
    ip_address = Column(String(50), nullable=True)
    device_info = Column(Text, nullable=True)
    login_status = Column(String(20), nullable=False) # e.g., 'SUCCESS', 'FAILED'
    refresh_token_id = Column(String(255), nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
