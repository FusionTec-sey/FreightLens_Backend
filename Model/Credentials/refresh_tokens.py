from sqlalchemy import Column, Integer, String, DateTime, SmallInteger, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from ..db import Base


# TABLE: Stores hashed refresh tokens so logins survive restarts and work across workers.
class RefreshToken(Base):
    """Persists hashed refresh tokens in the database.

    Replaces the old in-memory ``fake_refresh_tokens = {}`` dict in
    ``auth/routes.py``.  Storing tokens in the DB means they survive
    server restarts and work correctly across multiple uvicorn workers.
    """

    __tablename__ = "user_refresh_tokens"
    __table_args__ = {"schema": "usercredentials"}

    # id - INTEGER, primary key.
    # Unique row number.
    id = Column(Integer, primary_key=True, autoincrement=True)
    # user_id - INTEGER, foreign key -> usercredentials.users.id, required.
    # User the token was issued to.
    user_id = Column(
        Integer,
        ForeignKey("usercredentials.users.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Store a SHA-256 hash of the raw token, not the token itself
    # token_hash - VARCHAR(255), required.
    # SHA-256 hash of the token (the raw token is never stored).
    token_hash = Column(String(255), nullable=False)
    # expires_at - TIMESTAMP, required.
    # When the token stops being valid.
    expires_at = Column(DateTime, nullable=False)
    # created_at - TIMESTAMP, optional.
    # When the token was issued.
    created_at = Column(DateTime, default=datetime.utcnow)
    # 0 = active, 1 = revoked (logout / rotation)
    # revoked - SMALLINT, optional, default 0.
    # 0 = active, 1 = revoked (logout or rotation).
    revoked = Column(SmallInteger, default=0)

    user = relationship("User", back_populates="refresh_tokens")
