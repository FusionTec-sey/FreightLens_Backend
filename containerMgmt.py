import logging
import warnings
from datetime import datetime

import uvicorn
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session
from apscheduler.schedulers.background import BackgroundScheduler

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



# ── Scheduler job ─────────────────────────────────────────────────────────────
def updateArrivalDate():
    db = next(get_db())
    try:
        records = (
            db.query(bl)
            .filter(bl.ArrivalDate > datetime.now())
            .all()
        )
        for i in records:
            data = track_and_trace(i.BillOfLanding)
            logger.info("Arrival date update | BoL=%s | data=%s", i.BillOfLanding, data)
            if len(data) > 0:
                db.query(bl).filter(bl.BillOfLanding == i.BillOfLanding).update(
                    {
                        bl.ArrivalDate: datetime.fromisoformat(
                            data[0]["eventDateTime"]
                        ).strftime("%Y-%m-%d %H:%M:%S")
                    }
                )
                db.commit()
    except Exception as e:
        logger.exception("Error in updateArrivalDate: %s", e)
    finally:
        db.close()


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
scheduler = BackgroundScheduler()
scheduler.add_job(updateArrivalDate, "cron", hour=15, minute=44)
scheduler.start()


# ── Lifecycle events ──────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup_event():
    logger.info("Initializing database tables...")
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables are ready.")


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