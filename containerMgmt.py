import logging
import os
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
# Tests and one-off maintenance commands must not start recurring production work.
scheduler = None
if os.getenv("DISABLE_SCHEDULER", "0") != "1":
    scheduler = create_scheduler()
    scheduler.start()


# ── Lifecycle events ──────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup_event():
    from Model.db import SessionLocal
    from Model.seed import seed_db

    if engine.dialect.name != "postgresql":
        raise RuntimeError("FreightLens requires PostgreSQL")

    logger.info("Initializing database schemas...")
    try:
        with engine.connect() as conn:
            conn.execute(text("CREATE SCHEMA IF NOT EXISTS containermgmt"))
            conn.execute(text("CREATE SCHEMA IF NOT EXISTS usercredentials"))
            conn.commit()
        logger.info("Database schemas are verified/created.")
    except Exception as e:
        logger.error("Failed to check/create database schemas: %s", e)

        # Continue so health diagnostics can report an existing database permission issue.

    from Utils.bootstrap_root_org import ensure_root_organisation
    ensure_root_organisation()

    logger.info("Initializing database tables...")
    from Utils.migrate_20261002_stock_ledger import prepare_product_stock_scope, ensure_stock_ledger_schema
    with engine.begin() as conn:
        prepare_product_stock_scope(conn)
        from Utils.migrate_20261002_stock_serials import prepare_stock_serial_scope
        prepare_stock_serial_scope(conn)
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
    from Utils.migrate_product_packaging_and_warehouse import ensure_packaging_and_warehouse_columns
    ensure_packaging_and_warehouse_columns()
    from Utils.migrate_report_templates import ensure_report_templates_schema
    ensure_report_templates_schema()
    from Utils.migrate_template_activation_and_tabular import ensure_template_activation_and_tabular_schema
    ensure_template_activation_and_tabular_schema()
    from Utils.migrate_sourcing_and_quote_templates import ensure_sourcing_and_quote_templates_schema
    ensure_sourcing_and_quote_templates_schema()
    from Utils.migrate_reporting_foundation import ensure_reporting_foundation_schema
    ensure_reporting_foundation_schema()
    from Utils.migrate_reporting_worker import ensure_reporting_worker_schema
    ensure_reporting_worker_schema()
    from Utils.migrate_20260930_org_id_integrity import ensure_org_id_integrity
    ensure_org_id_integrity()
    logger.info("Database tables are ready.")
    from Utils.migrate_20261002_receipt_posting import ensure_receipt_posting_schema
    ensure_receipt_posting_schema()
    from Utils.migrate_20261002_inventory_locations import ensure_inventory_locations_schema
    ensure_inventory_locations_schema()
    from Utils.migrate_20261002_inventory_cost_pools import ensure_inventory_cost_pools_schema
    ensure_inventory_cost_pools_schema()
    from Utils.migrate_20261002_inventory_posting import ensure_inventory_posting_schema
    ensure_inventory_posting_schema()
    from Utils.migrate_20261003_retail_customers import ensure_retail_customers_schema
    ensure_retail_customers_schema()
    from Utils.migrate_20261002_posting_authority import ensure_posting_authority_schema
    ensure_posting_authority_schema()
    from Utils.migrate_20261003_cost_pool_authority import ensure_cost_pool_authority_schema
    ensure_cost_pool_authority_schema()
    from Utils.migrate_20261002_branch_settings import ensure_branch_settings_schema
    ensure_branch_settings_schema()
    from Utils.migrate_20261002_branch_counters import ensure_branch_counters_schema
    ensure_branch_counters_schema()
    from Utils.migrate_20261003_staff_store_assignments import ensure_staff_store_assignments_schema
    ensure_staff_store_assignments_schema()
    from Utils.migrate_20261002_manager_cases import ensure_manager_cases_schema
    ensure_manager_cases_schema()
    ensure_stock_ledger_schema()
    from Utils.migrate_20261002_stock_unit_policy import ensure_stock_unit_policy_schema
    ensure_stock_unit_policy_schema()
    from Utils.migrate_20261002_stock_batches import ensure_stock_batches_schema
    ensure_stock_batches_schema()
    from Utils.migrate_20261002_stock_serials import ensure_stock_serials_schema
    ensure_stock_serials_schema()
    from Utils.migrate_20261002_inventory_policy_drafts import ensure_inventory_policy_drafts_schema
    ensure_inventory_policy_drafts_schema()
    from Utils.migrate_20261002_policy_activation import ensure_policy_activation_schema
    ensure_policy_activation_schema()
    from Utils.migrate_20261003_sales_intents import ensure_sales_intents_schema
    ensure_sales_intents_schema()
    from Utils.migrate_20261004_customer_profiles import ensure_customer_profiles_schema
    ensure_customer_profiles_schema()
    from Utils.migrate_20261004_sales_pricing import ensure_sales_pricing_schema
    ensure_sales_pricing_schema()
    from Utils.migrate_20261005_payment_methods import ensure_payment_methods_schema
    ensure_payment_methods_schema()
    from Utils.migrate_20261005_branch_receiving_accounts import ensure_branch_receiving_accounts_schema
    ensure_branch_receiving_accounts_schema()
    from Utils.migrate_20261003_sales_reservation_sources import ensure_sales_reservation_sources_schema
    ensure_sales_reservation_sources_schema()
    from Utils.migrate_20261003_reservation_deadlines import ensure_reservation_deadlines_schema
    ensure_reservation_deadlines_schema()
    from Utils.migrate_20261003_reservation_reallocations import ensure_reservation_reallocations_schema
    ensure_reservation_reallocations_schema()
    from Utils.migrate_20261003_reservation_segments import ensure_reservation_segments_schema
    ensure_reservation_segments_schema()
    from Utils.migrate_20261004_cycle_counts import ensure_cycle_counts_schema
    ensure_cycle_counts_schema()
    from Utils.migrate_20261004_count_permissions import ensure_count_permissions
    ensure_count_permissions()
    from Utils.migrate_20261002_unit_barcodes import ensure_unit_barcodes_schema
    ensure_unit_barcodes_schema()
    from Utils.migrate_20261002_barcode_retirements import ensure_barcode_retirements_schema
    ensure_barcode_retirements_schema()
    from Utils.migrate_20261002_stock_reclassification import ensure_stock_reclassification_schema
    ensure_stock_reclassification_schema()
    from Utils.migrate_20261004_receipt_manifests import ensure_receipt_manifest_schema
    ensure_receipt_manifest_schema()
    from Utils.migrate_20261004_receipt_source_uses import ensure_receipt_source_uses_schema
    ensure_receipt_source_uses_schema()
    from Utils.migrate_20261004_receipt_movements import ensure_receipt_movement_schema
    ensure_receipt_movement_schema()
    from Utils.migrate_20261004_stock_adjustments import ensure_stock_adjustment_schema
    ensure_stock_adjustment_schema()
    from Utils.migrate_20261004_stock_adjustment_permissions import ensure_stock_adjustment_permissions
    ensure_stock_adjustment_permissions()
    from Utils.migrate_20261004_receipt_cost_permissions import ensure_receipt_cost_permissions
    ensure_receipt_cost_permissions()
    from Utils.migrate_20261003_inventory_valuation import ensure_inventory_valuation_schema
    ensure_inventory_valuation_schema()
    from Utils.migrate_20261003_valuation_charges import ensure_valuation_charges_schema
    ensure_valuation_charges_schema()
    from Utils.migrate_20261004_receipt_valuation import ensure_receipt_valuation_schema
    ensure_receipt_valuation_schema()
    from Utils.migrate_20261003_cost_allocation import ensure_cost_allocation_schema
    ensure_cost_allocation_schema()
    from Utils.migrate_20261003_cost_charge_uses import ensure_cost_charge_uses_schema
    ensure_cost_charge_uses_schema()
    from Utils.migrate_20261004_cost_reconciliations import ensure_cost_reconciliations_schema
    ensure_cost_reconciliations_schema()
    from Utils.migrate_20261004_cost_reconciliation_permissions import ensure_cost_reconciliation_permissions
    ensure_cost_reconciliation_permissions()

    logger.info("Checking database seeding...")
    db_session = SessionLocal()
    try:
        seed_db(db_session)
        # Roles must exist before this migration grants their default permissions.
        ensure_dashboard_and_inventory_permissions()
        from Utils.migrate_reporting_permissions import run_reporting_permissions_migration
        run_reporting_permissions_migration(db_session)
        from Utils.migrate_reporting_foundation import seed_reporting_foundation
        seed_reporting_foundation(db_session)
    except Exception as e:
        logger.error("Database seeding failed: %s", e)
        raise
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
        from Services.search_service import bulk_index_all_products, bulk_index_all_orders, bulk_index_all_customers
        meili_db = SessionLocal()
        bulk_index_all_products(meili_db)
        bulk_index_all_orders(meili_db)
        bulk_index_all_customers(meili_db)
        from Services.sales_draft_search_projection import bulk_index_sales_drafts
        bulk_index_sales_drafts(meili_db)
        meili_db.close()
    except Exception as e:
        logger.error("Failed to initialize Meilisearch: %s", e)


@app.on_event("shutdown")
def shutdown_event():
    if scheduler is not None and scheduler.running:
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


# ── Route registration ────────────────────────────────────────────────────────
from auth.module_guard import require_module
from auth.policy import get_request_policy
from auth.security_guards import require_root_admin

from LogisticsAPI import logistics_router, logistics_webhook_router

from Routes.Reports.ReportRouter import ReportRouter
from Routes.MasterData.MasterDataRouter import MasterDataRouter
from Routes.Dashboard.DashboardRouter import DashboardRouter

app.include_router(auth_router)
app.include_router(ReportRouter)
app.include_router(Cinfo)
app.include_router(ContainerRouter, dependencies=[Depends(require_module("LOGISTICS"))])
app.include_router(CreadentialsInfo, dependencies=[Depends(get_request_policy)])
app.include_router(TrackingRouter, dependencies=[Depends(require_module("LOGISTICS"))])
app.include_router(logistics_router, dependencies=[Depends(require_module("LOGISTICS"))])
app.include_router(logistics_webhook_router)  # Carrier-authenticated push events
app.include_router(BillOfLandingRouter, dependencies=[Depends(require_module("LOGISTICS"))])
app.include_router(SettingRouter, dependencies=[Depends(require_module("LOGISTICS"))])
app.include_router(OrganisationRouter)
app.include_router(AdminRouter, dependencies=[Depends(require_root_admin)])
app.include_router(OrderTemplateRouter, dependencies=[Depends(require_module("ORDERS"))])
app.include_router(LifecycleRouter, dependencies=[Depends(require_module("ORDERS"))])
app.include_router(OrderRouter, dependencies=[Depends(require_module("ORDERS"))])
app.include_router(StoreRequestRouter, dependencies=[Depends(require_module("ORDERS"))])
app.include_router(PackingListRouter, dependencies=[Depends(require_module("ORDERS"))])
app.include_router(ReceivingRouter, dependencies=[Depends(require_module("ORDERS"))])
app.include_router(DefectRouter, dependencies=[Depends(require_module("ORDERS"))])
app.include_router(DailyWorkRouter, dependencies=[Depends(require_module("ORDERS"))])
app.include_router(InventoryRouter, dependencies=[Depends(require_module("INVENTORY"))])
app.include_router(LocationRouter, dependencies=[Depends(require_module("INVENTORY"))])
app.include_router(CostPoolRouter, dependencies=[Depends(require_module("INVENTORY"))])
app.include_router(CostEvidenceRouter)
app.include_router(PolicyDraftRouter, dependencies=[Depends(require_module("INVENTORY"))])
app.include_router(BranchSettingsRouter, dependencies=[Depends(require_module("INVENTORY"))])
app.include_router(BranchCounterRouter, dependencies=[Depends(require_module("INVENTORY"))])
app.include_router(StaffStoreAssignmentRouter, dependencies=[Depends(require_module("INVENTORY"))])
app.include_router(ManagerCaseRouter, dependencies=[Depends(require_module("INVENTORY"))])
app.include_router(ReclassificationProposalRouter, dependencies=[Depends(require_module("INVENTORY"))])
app.include_router(ReceiptManifestRouter)
app.include_router(StockAdjustmentRouter)
app.include_router(OpeningRouter)
from Routes.Inventory.CostReconciliationRouter import CostReconciliationRouter
app.include_router(CostReconciliationRouter)
app.include_router(UnitBarcodeRouter, dependencies=[Depends(require_module("INVENTORY"))])
app.include_router(BarcodeRetirementRouter, dependencies=[Depends(require_module("INVENTORY"))])
app.include_router(NotificationRouter, dependencies=[Depends(require_module("ORDERS"))])
app.include_router(MasterDataRouter)
from Routes.MasterData.CustomerRouter import CustomerRouter
app.include_router(CustomerRouter)
from Routes.Orders.SalesIntentRouter import SalesIntentRouter
app.include_router(SalesIntentRouter)
from Routes.Orders.SalesPricingRouter import SalesPricingRouter
app.include_router(SalesPricingRouter)
from Routes.Orders.PaymentConfigurationRouter import PaymentConfigurationRouter
app.include_router(PaymentConfigurationRouter)
from Routes.Orders.SalesSourceRouter import SalesSourceRouter
app.include_router(SalesSourceRouter)
from Routes.Inventory.ReservationReleaseCaseRouter import ReservationReleaseCaseRouter
app.include_router(ReservationReleaseCaseRouter)
from Routes.Inventory.ReservationReallocationRouter import ReservationReallocationRouter
app.include_router(ReservationReallocationRouter)
from Routes.Inventory.OtherStoreFulfilmentRouter import OtherStoreFulfilmentRouter
app.include_router(OtherStoreFulfilmentRouter)
from Routes.Orders.StoreAllocationRouter import StoreAllocationRouter
app.include_router(StoreAllocationRouter)
from Routes.Inventory.ReservationDeadlineRouter import ReservationDeadlineRouter
app.include_router(ReservationDeadlineRouter)
from Routes.Inventory.CycleCountRouter import CycleCountRouter
app.include_router(CycleCountRouter)
app.include_router(BlobRouter)
app.include_router(DashboardRouter, dependencies=[Depends(get_request_policy)])



# ── Entrypoint ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    uvicorn.run(
        "containerMgmt:app",
        host=settings.HOST_IP,
        port=settings.HOST_PORT,
        reload=True,
    )
