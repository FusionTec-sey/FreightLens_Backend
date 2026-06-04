import logging
import warnings
from datetime import datetime

import uvicorn
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session
warnings.filterwarnings("ignore", category=DeprecationWarning)

# ── Logging setup (must be before any module that uses logging) ───────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    handlers=[
        logging.StreamHandler(),                           # Console output
        logging.FileHandler("app.log", encoding="utf-8"), # Persistent log file
    ],
)
logger = logging.getLogger("containerMgmt")

# ── App configuration & models ────────────────────────────────────────────────
from auth.config import settings
from Schema import *
from Model import *
from Model.db import Base, engine, get_db
from ShippingProvider.Shipping import track_and_trace
from auth import auth_router
from Routes import *
from Model.containermgmt.Container.BillOfLanding import BillOfLanding as bl

from limiter import limiter, RATE_LIMIT_AVAILABLE

if RATE_LIMIT_AVAILABLE:
    from slowapi.errors import RateLimitExceeded
    from slowapi import _rate_limit_exceeded_handler



from cron_jobs import create_scheduler, backfill_container_statuses


# ── FastAPI app factory ────────────────────────────────────────────────────────
app = FastAPI(
    title="Container Management API",
    version="1.0.0",
    # Hide Swagger UI and ReDoc in production
    docs_url="/docs" if settings.ENVIRONMENT != "production" else None,
    redoc_url="/redoc" if settings.ENVIRONMENT != "production" else None,
)

# ── Rate limiter state (must be set before routes are registered) ──────────────
if RATE_LIMIT_AVAILABLE:
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── CORS ──────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,  # Read from ALLOWED_ORIGINS in .env
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Background scheduler ──────────────────────────────────────────────────────
scheduler = create_scheduler()
scheduler.start()


# ── Lifecycle events ──────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup_event():
    from sqlalchemy import create_engine
    from Model.db import SessionLocal
    from Model.seed import seed_db

    logger.info("Initializing database schemas...")
    try:
        # Generate a temporary engine that connects directly to the MySQL server without a default schema/DB.
        # This prevents "Unknown database" errors when the schema doesn't exist yet.
        temp_url = engine.url.set(database=None)
        temp_engine = create_engine(temp_url)
        with temp_engine.connect() as conn:
            conn.execute(text("CREATE DATABASE IF NOT EXISTS containermgmt"))
            conn.execute(text("CREATE DATABASE IF NOT EXISTS usercredentials"))
            conn.commit()
        temp_engine.dispose()
        logger.info("Database schemas are verified/created.")
    except Exception as e:
        logger.error("Failed to check/create database schemas: %s", e)
        # Proceed anyway as the database might already exist or the user might not have admin rights to CREATE DATABASE

    logger.info("Initializing database tables...")
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables are ready.")

    logger.info("Checking database seeding...")
    db_session = SessionLocal()
    try:
        seed_db(db_session)
    except Exception as e:
        logger.error("Database seeding failed: %s", e)
    finally:
        db_session.close()

    # ── One-shot status backfill ───────────────────────────────────────────────
    # Corrects any containers entered before auto-status logic existed.
    # Safe to run on every restart — only logs changes, commits only if needed.
    logger.info("Running one-shot container status backfill...")
    backfill_container_statuses()


@app.on_event("shutdown")
def shutdown_event():
    scheduler.shutdown()
    logger.info("Application shutdown complete.")


# ── Health check endpoint ─────────────────────────────────────────────────────
@app.get("/health", tags=["System"])
async def health_check(db: Session = Depends(get_db)):
    """Returns database connectivity and API liveness status."""
    try:
        db.execute(text("SELECT 1"))
        return {"status": "ok", "database": "connected", "environment": settings.ENVIRONMENT}
    except Exception as e:
        logger.error("Health check failed: %s", e)
        raise HTTPException(status_code=503, detail=f"Database unavailable: {str(e)}")


# ── Temporary testing endpoint ────────────────────────────────────────────────
@app.get("/test-connection", tags=["System"])
async def test_connection():
    """Temporary endpoint to test connectivity to remote endpoint http://100.90.45.82:8000/status"""
    import requests
    url = "http://100.90.45.82:8000/status"
    try:
        response = requests.get(url, timeout=10)
        return {
            "status": "connected",
            "remote_status_code": response.status_code,
            "remote_response": response.text[:2000]
        }
    except requests.exceptions.RequestException as e:
        return {
            "status": "failed",
            "error": str(e)
        }


# ── Route registration ────────────────────────────────────────────────────────
app.include_router(auth_router)
app.include_router(Cinfo)
app.include_router(ContainerRouter)
app.include_router(CreadentialsInfo)
app.include_router(TrackingRouter)
app.include_router(BillOfLandingRouter)
app.include_router(SettingRouter)


# ── Entrypoint ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    uvicorn.run(
        "containerMgmt:app",
        host=settings.HOST_IP,
        port=settings.HOST_PORT,
        reload=True,
    )