from sqlalchemy import Column, Integer, BigInteger, String, DateTime, Text, ForeignKey, func
from ..db import Base

# TABLE: Ledger of logins/logouts: who signed in, from where, and whether it worked.
class SessionAudit(Base):
    """
    Central ledger to track user logins, logouts, session information, and IP addresses.
    """
    __tablename__ = "session_audit"
    __table_args__ = {'schema': 'usercredentials'}
    
    # session_id - BIGINT, primary key.
    # Unique session number.
    session_id = Column(BigInteger, primary_key=True, autoincrement=True)
    # user_id - INTEGER, foreign key -> usercredentials.users.id, optional.
    # User who tried to sign in (NULL if the username was unknown).
    user_id = Column(Integer, ForeignKey('usercredentials.users.id'), nullable=True)
    # login_time - TIMESTAMP, optional.
    # When the login happened.
    login_time = Column(DateTime, nullable=True)
    # logout_time - TIMESTAMP, optional.
    # When the user logged out (NULL while still signed in).
    logout_time = Column(DateTime, nullable=True)
    # ip_address - VARCHAR(50), optional.
    # IP address the request came from.
    ip_address = Column(String(50), nullable=True)
    # device_info - TEXT, optional.
    # Browser/device description (user agent).
    device_info = Column(Text, nullable=True)
    # login_status - VARCHAR(20), required.
    # SUCCESS or FAILED.
    login_status = Column(String(20), nullable=False) # e.g., 'SUCCESS', 'FAILED'
    # refresh_token_id - VARCHAR(255), optional.
    # Refresh token issued for this session, so logout can revoke it.
    refresh_token_id = Column(String(255), nullable=True)
    # created_at - TIMESTAMP, required.
    # When the row was created.
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
