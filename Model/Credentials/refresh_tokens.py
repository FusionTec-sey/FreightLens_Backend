from sqlalchemy import Column, Integer, String, DateTime, SmallInteger, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from ..db import Base


class RefreshToken(Base):
    """Persists hashed refresh tokens in the database.

    Replaces the old in-memory ``fake_refresh_tokens = {}`` dict in
    ``auth/routes.py``.  Storing tokens in the DB means they survive
    server restarts and work correctly across multiple uvicorn workers.
    """

    __tablename__ = "user_refresh_tokens"
    __table_args__ = {"schema": "usercredentials"}

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer,
        ForeignKey("usercredentials.users.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Store a SHA-256 hash of the raw token, not the token itself
    token_hash = Column(String(255), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    # 0 = active, 1 = revoked (logout / rotation)
    revoked = Column(SmallInteger, default=0)

    user = relationship("User", back_populates="refresh_tokens")
