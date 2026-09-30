"""
Logistics API Engine - Master FastAPI Router
Exposes dedicated, commercial-grade endpoints under `/api/logistics`.
Can be mounted directly into FastAPI or run independently as a standalone microservice.
"""

import hmac

from fastapi import APIRouter, Query, HTTPException, Request, Header, status
from typing import Optional, Dict, Any
from auth.config import settings
from .services import (
    TrackingService,
    VesselService,
    DemurrageDetentionEngine,
    WebhookService,
    BookingEngine
)
from .models import (
    FullTrackingResponse,
    VesselProfile,
    DnDReport,
    TransportDocumentManifest,
    BookingRequestPayload,
    BookingConfirmation
)

# Main router for logistics consumers (authenticated in main app, or token-protected in standalone)
logistics_router = APIRouter(prefix="/api/logistics", tags=["Logistics Engine"])

# Dedicated carrier router authenticated with a per-environment shared secret.
logistics_webhook_router = APIRouter(prefix="/api/logistics/webhook", tags=["Logistics Webhooks"])

# Service singletons
_tracking_service = TrackingService()
_vessel_service = VesselService()
_dnd_engine = DemurrageDetentionEngine()
_webhook_service = WebhookService()
_booking_engine = BookingEngine()


# ── 1. Unified Track & Trace ──────────────────────────────────────────────────

@logistics_router.get(
    "/track",
    response_model=FullTrackingResponse,
    summary="Track shipment across ocean carriers",
    description="Returns complete 28+ milestone timeline, container statuses, vessel master details, and D&D report."
)
def track_shipment(
    ref: str = Query(..., description="Bill of Lading or Container number (e.g. GGZ2601947, CAAU2824554)"),
    carrier: Optional[str] = Query(None, description="Optional carrier filter: CMA CGM, Maersk")
):
    result = _tracking_service.track(reference=ref, carrier=carrier)
    if not result:
        raise HTTPException(
            status_code=404,
            detail=f"No tracking events found for reference '{ref}'. Verify reference number."
        )
    return result


# ── 2. Vessel Intelligence (Live API) ─────────────────────────────────────────

@logistics_router.get(
    "/vessels/{imo}",
    response_model=VesselProfile,
    summary="Get vessel technical specifications",
    description="Queries live CMA CGM Vessel Referential API for vessel capacity, speed, flag, and dimensions."
)
def get_vessel_specs(imo: str):
    profile = _vessel_service.get_vessel_specs(imo=imo)
    if not profile:
        raise HTTPException(
            status_code=404,
            detail=f"Vessel with IMO '{imo}' not found in carrier registry."
        )
    return profile


# ── 3. Demurrage & Detention (D&D) Engine ─────────────────────────────────────

@logistics_router.get(
    "/dnd/{reference}",
    response_model=DnDReport,
    summary="Get Demurrage & Detention countdown and cost report",
    description="Calculates port terminal dwell days (Demurrage) and consignee possession days (Detention)."
)
def get_dnd_status(
    reference: str,
    free_days: int = Query(10, description="Agreed free calendar days per container (default 10)")
):
    report = _dnd_engine.evaluate_dnd(reference=reference, default_free_days=free_days)
    if not report:
        raise HTTPException(status_code=404, detail=f"No D&D data found for '{reference}'.")
    return report


# ── 4. Transport Document & Auto-Seed Manifest ───────────────────────────────

@logistics_router.post(
    "/seed/{bl_reference}",
    summary="Auto-seed Bill of Lading and Containers into Database",
    description="Fetches containers and vessel from carrier API and automatically populates the database."
)
def auto_seed_shipment(bl_reference: str):
    res = _webhook_service.auto_seed_bl_to_db(bl_reference=bl_reference.strip().upper())
    if res.get("status") == "error":
        raise HTTPException(status_code=400, detail=res.get("message"))
    return res


@logistics_router.get(
    "/documents/{bl_reference}",
    response_model=TransportDocumentManifest,
    summary="Get Bill of Lading manifest data",
    description="Retrieves Shipper, Consignee, Notify Party, gross weight, CBM volume, package count, and seals."
)
def get_transport_document(bl_reference: str):
    provider = _tracking_service.providers[0] # Default to CMA CGM
    doc = provider.get_transport_document(bl_reference=bl_reference)
    if not doc:
        raise HTTPException(
            status_code=404,
            detail=f"Transport document not accessible or not found for '{bl_reference}'."
        )
    return doc


# ── 5. Instant Freight Quotation (Commercial Stub) ────────────────────────────

@logistics_router.get(
    "/quotes",
    summary="Request instant freight quotation",
    description="Commercial module to quote spot ocean freight between ports."
)
def get_freight_quote(
    origin: str = Query(..., description="Origin port UN/LOCODE (e.g. CNSHK)"),
    destination: str = Query(..., description="Destination port UN/LOCODE (e.g. SCPOV)"),
    container_type: str = Query("40HC", description="20GP, 40GP, 40HC, 40REEF")
):
    return _booking_engine.request_quote(origin=origin, destination=destination, container_type=container_type)


@logistics_router.post(
    "/bookings",
    response_model=BookingConfirmation,
    summary="Create container booking request",
    description="Commercial module to submit booking requests to ocean carrier."
)
def create_booking(payload: BookingRequestPayload):
    return _booking_engine.submit_booking(payload)


# ── 6. Inbound Webhook Listener (Push Notification Receiver) ──────────────────

def _verify_cma_webhook_secret(provided_secret: Optional[str]) -> None:
    configured_secret = settings.CMA_CGM_WEBHOOK_SECRET
    if not configured_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Carrier webhook authentication is not configured",
        )
    if not provided_secret or not hmac.compare_digest(provided_secret, configured_secret):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid carrier webhook credentials",
        )

@logistics_webhook_router.post(
    "/cma-cgm",
    summary="CMA CGM Inbound Webhook Receiver",
    description="Receives real-time DCSA event push notifications from CMA CGM without consuming polling API quota."
)
async def receive_cma_cgm_webhook(
    request: Request,
    x_webhook_secret: Optional[str] = Header(None, alias="X-Webhook-Secret"),
):
    _verify_cma_webhook_secret(x_webhook_secret)
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Webhook payload must be valid JSON")

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Webhook payload must be a JSON object")
    
    return _webhook_service.process_cma_webhook(raw_payload=payload)
