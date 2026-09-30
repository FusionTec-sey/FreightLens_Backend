# db.py
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy import event
import os
from dotenv import load_dotenv

if not os.getenv("DATABASE_URL"):
    load_dotenv()

Base = declarative_base()

DATABASE_URL = os.getenv("DATABASE_URL")  # or your actual DB URL

engine = create_engine(
    DATABASE_URL,
    pool_size=20,         # 20 persistent connections in pool (up from default 5)
    max_overflow=20,      # Up to 20 additional burst connections (up from default 10)
    pool_timeout=30,      # Wait up to 30s before timing out
    pool_pre_ping=True,   # Test connection health before use (prevents stale connection errors)
    pool_recycle=1800,    # Recycle connections every 30 min
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _reject_missing_org_ids(session, flush_context, instances):
    """Reject new tenant-owned rows that were not assigned an organisation."""
    from Model.mixins import OrgMixin

    missing = [
        type(obj).__name__
        for obj in session.new
        if isinstance(obj, OrgMixin) and getattr(obj, "org_id", None) is None
    ]
    if missing:
        model_names = ", ".join(sorted(set(missing)))
        raise ValueError(f"org_id is required for tenant-owned models: {model_names}")


event.listen(Session, "before_flush", _reject_missing_org_ids)

# Dependency for FastAPI
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
