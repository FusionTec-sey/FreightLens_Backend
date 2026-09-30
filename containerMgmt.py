import logging
import warnings
from datetime import datetime

import uvicorn
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
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
_cors_origins = [o.strip().rstrip("/") for o in list(settings.ALLOWED_ORIGINS or []) if o.strip()]
for _origin in [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "https://staging.fusiontech.services",
]:
    if _origin not in _cors_origins:
        _cors_origins.append(_origin)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_origin_regex=r"^https?://(.*\.)?fusiontech\.services(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

app.add_middleware(GZipMiddleware, minimum_size=1000)

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
        if engine.dialect.name == "postgresql":
            with engine.connect() as conn:
                conn.execute(text("CREATE SCHEMA IF NOT EXISTS containermgmt"))
                conn.execute(text("CREATE SCHEMA IF NOT EXISTS usercredentials"))
                conn.commit()
        else:
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
    from Utils.migrate_product_master import ensure_product_master_schema
    ensure_product_master_schema()
    from Utils.migrate_logistics_schema import ensure_logistics_tracking_schema
    ensure_logistics_tracking_schema()
    from Utils.migrate_order_templates import ensure_order_templates_schema
    ensure_order_templates_schema()
    from Utils.migrate_po_lifecycle import ensure_po_lifecycle_schema
    ensure_po_lifecycle_schema()
    from Utils.migrate_master_data import ensure_master_data_schema
    ensure_master_data_schema()
    from Utils.migrate_20260930_supplier_scope import ensure_supplier_scope_schema
    ensure_supplier_scope_schema()
    from Utils.migrate_order_documents import ensure_order_documents_schema
    ensure_order_documents_schema()
    from Utils.migrate_order_documents_org import ensure_order_documents_org_schema
    ensure_order_documents_org_schema()
    from Utils.migrate_master_document_types import ensure_master_document_types_schema
    ensure_master_document_types_schema()
    from Utils.migrate_product_suppliers import ensure_product_suppliers_schema
    ensure_product_suppliers_schema()
    from Utils.migrate_material_tracking_and_holds import ensure_material_tracking_and_holds_schema
    ensure_material_tracking_and_holds_schema()
    from Utils.migrate_decouple_financial_status import ensure_decouple_financial_status
    ensure_decouple_financial_status()
    from Utils.migrate_user_allowed_orgs import ensure_user_allowed_orgs_schema
    ensure_user_allowed_orgs_schema()
    from Utils.migrate_dashboard_and_inventory_permissions import ensure_dashboard_and_inventory_permissions
    ensure_dashboard_and_inventory_permissions()
    from Utils.migrate_product_packaging_and_warehouse import ensure_packaging_and_warehouse_columns
    ensure_packaging_and_warehouse_columns()
    from Utils.migrate_report_templates import ensure_report_templates_schema
    ensure_report_templates_schema()
    from Utils.migrate_template_activation_and_tabular import ensure_template_activation_and_tabular_schema
    ensure_template_activation_and_tabular_schema()
    from Utils.migrate_sourcing_and_quote_templates import ensure_sourcing_and_quote_templates_schema
    ensure_sourcing_and_quote_templates_schema()
    logger.info("Database tables are ready.")

    logger.info("Checking database seeding...")
    db_session = SessionLocal()
    try:
        seed_db(db_session)
        from Utils.migrate_reporting_permissions import run_reporting_permissions_migration
        run_reporting_permissions_migration(db_session)
    except Exception as e:
        logger.error("Database seeding failed: %s", e)
    finally:
        db_session.close()

    # ── One-shot status backfill ───────────────────────────────────────────────
    # Corrects any containers entered before auto-status logic existed.
    # Safe to run on every restart — only logs changes, commits only if needed.
    logger.info("Running one-shot container status backfill...")
    backfill_container_statuses()

    # ── Initialize RustFS Object Storage ─────────────────────────────────────
    logger.info("Initializing RustFS Blob Storage...")
    try:
        from Utils.blob_storage import blob_storage
        blob_storage.ensure_bucket_exists()
    except Exception as e:
        logger.error("Failed to initialize RustFS Object Storage: %s", e)

    # ── Initialize Meilisearch Search Engine ─────────────────────────────────
    logger.info("Initializing Meilisearch Indices (Products & Orders)...")
    try:
        from Services.search_service import bulk_index_all_products, bulk_index_all_orders
        meili_db = SessionLocal()
        bulk_index_all_products(meili_db)
        bulk_index_all_orders(meili_db)
        meili_db.close()
    except Exception as e:
        logger.error("Failed to initialize Meilisearch: %s", e)


@app.on_event("shutdown")
def shutdown_event():
    scheduler.shutdown()
    logger.info("Application shutdown complete.")


# ── Health check endpoint ─────────────────────────────────────────────────────
@app.get("/health", tags=["System"])
async def health_check(db: Session = Depends(get_db)):
    """Returns database connectivity and API liveness status."""
    db_status = "connected"
    try:
        db.execute(text("SELECT 1"))
    except Exception as e:
        db_status = f"error: {str(e)}"

    storage_status = "connected"
    try:
        from Utils.blob_storage import blob_storage
        if not blob_storage.ensure_bucket_exists():
            storage_status = "warning: bucket check failed"
    except Exception as se:
        storage_status = f"error: {str(se)}"

    return {
        "status": "ok" if db_status == "connected" else "degraded",
        "database": db_status,
        "object_storage": storage_status,
        "environment": settings.ENVIRONMENT
    }


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
from auth.module_guard import require_module

from LogisticsAPI import logistics_router, logistics_webhook_router

from Routes.Reports.ReportRouter import ReportRouter
from Routes.MasterData.MasterDataRouter import MasterDataRouter
from Routes.Dashboard.DashboardRouter import DashboardRouter

app.include_router(auth_router)
app.include_router(ReportRouter)
app.include_router(Cinfo)
app.include_router(ContainerRouter, dependencies=[Depends(require_module("LOGISTICS"))])
app.include_router(CreadentialsInfo)
app.include_router(TrackingRouter, dependencies=[Depends(require_module("LOGISTICS"))])
app.include_router(logistics_router, dependencies=[Depends(require_module("LOGISTICS"))])
app.include_router(logistics_webhook_router)  # Public webhook for carrier push events
app.include_router(BillOfLandingRouter, dependencies=[Depends(require_module("LOGISTICS"))])
app.include_router(SettingRouter)
app.include_router(OrganisationRouter)
app.include_router(AdminRouter)
app.include_router(OrderTemplateRouter, dependencies=[Depends(require_module("ORDERS"))])
app.include_router(LifecycleRouter, dependencies=[Depends(require_module("ORDERS"))])
app.include_router(OrderRouter, dependencies=[Depends(require_module("ORDERS"))])
app.include_router(StoreRequestRouter, dependencies=[Depends(require_module("ORDERS"))])
app.include_router(PackingListRouter, dependencies=[Depends(require_module("ORDERS"))])
app.include_router(ReceivingRouter, dependencies=[Depends(require_module("ORDERS"))])
app.include_router(DefectRouter, dependencies=[Depends(require_module("ORDERS"))])
app.include_router(DailyWorkRouter, dependencies=[Depends(require_module("ORDERS"))])
app.include_router(InventoryRouter, dependencies=[Depends(require_module("INVENTORY"))])
app.include_router(NotificationRouter)
app.include_router(MasterDataRouter)
app.include_router(BlobRouter)
app.include_router(DashboardRouter)



# ── Entrypoint ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    uvicorn.run(
        "containerMgmt:app",
        host=settings.HOST_IP,
        port=settings.HOST_PORT,
        reload=True,
    )
