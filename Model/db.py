# db.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm import declarative_base
import os
from dotenv import load_dotenv

if not os.getenv("DATABASE_URL"):
    load_dotenv()

Base = declarative_base()

DATABASE_URL = os.getenv("DATABASE_URL")  # or your actual DB URL

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,   # Test connection health before use (prevents stale connection errors)
    pool_recycle=1800,    # Recycle connections every 30 min (before MySQL drops them at 8h)
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Dependency for FastAPI
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
