"""
Logistics API Engine - Core Data Models
Commercial-grade, carrier-agnostic Pydantic models for tracking,
vessel intelligence, Demurrage & Detention, transport documents, and webhooks.
Designed to run embedded or as an independent standalone microservice.
"""

from typing import Optional, List, Dict, Any, Union
from pydantic import BaseModel, Field
from datetime import datetime


# ── 1. Milestone & Event Models ───────────────────────────────────────────────

class LocationInfo(BaseModel):
    un_location_code: Optional[str] = Field(None, description="5-letter UN/LOCODE (e.g. SCPOV, CNSHK, SGSIN)")
    location_name: Optional[str] = Field(None, description="City / Port name")
    facility_code: Optional[str] = Field(None, description="Terminal / Facility code (SMDG or BIC)")
    facility_name: Optional[str] = Field(None, description="Terminal full name")
    country: Optional[str] = Field(None, description="Country name or ISO-2 code")
    latitude: Optional[float] = Field(None, description="GPS Latitude")
    longitude: Optional[float] = Field(None, description="GPS Longitude")


class MilestoneEvent(BaseModel):
    event_id: Optional[str] = Field(None, description="Unique event identifier")
    event_type: str = Field(..., description="EQUIPMENT, TRANSPORT, or SHIPMENT")
    event_code: str = Field(..., description="Standard DCSA code: LOAD, DISC, GTIN, GTOT, ARRI, DEPA, PICK, DROP, etc.")
    event_label: str = Field(..., description="Human-readable milestone description")
    classifier: str = Field("ACT", description="ACT (Actual), EST (Estimated), or PLN (Planned)")
    event_datetime: Optional[str] = Field(None, description="ISO-8601 timestamp of milestone")
    transportation_phase: Optional[str] = Field(None, description="Export, Transshipment, or Import")
    equipment_reference: Optional[str] = Field(None, description="Container number")
    iso_equipment_code: Optional[str] = Field(None, description="ISO Container size/type (22G1, 45G0, etc.)")
    empty_indicator: Optional[str] = Field(None, description="LADEN or EMPTY")
    location: Optional[LocationInfo] = None
    vessel_name: Optional[str] = None
    vessel_imo: Optional[str] = None
    voyage_number: Optional[str] = None
    mode_of_transport: Optional[str] = Field("VESSEL", description="VESSEL, TRUCK, RAIL, BARGE")
    raw_data: Optional[Dict[str, Any]] = None


# ── 2. Vessel Intelligence Models ────────────────────────────────────────────

class VesselProfile(BaseModel):
    imo: str = Field(..., description="7-digit IMO number")
    name: str = Field(..., description="Vessel name")
    vessel_code: Optional[str] = None
    vessel_flag: Optional[str] = Field(None, description="Country of registration")
    call_sign: Optional[str] = None
    status: Optional[str] = None
    built_year: Optional[int] = None
    delivery_date: Optional[str] = None
    builder_name: Optional[str] = None
    classification_society: Optional[str] = None
    teu_capacity: Optional[int] = Field(None, description="Total container capacity in TEU")
    reefer_plugs: Optional[int] = Field(None, description="Number of refrigerated container plugs")
    deadweight_tonnage: Optional[float] = None
    gross_tonnage: Optional[float] = None
    length_overall_m: Optional[float] = None
    beam_m: Optional[float] = None
    draught_m: Optional[float] = None
    speed_knots: Optional[float] = None
    operator_name: Optional[str] = None
    cargo_gear: Optional[str] = None


# ── 3. Demurrage & Detention (D&D) Models ─────────────────────────────────────

class ContainerDnDDetail(BaseModel):
    container_number: str
    iso_code: Optional[str] = None
    discharge_date: Optional[str] = Field(None, description="Port vessel discharge date")
    gate_out_date: Optional[str] = Field(None, description="Gate out to consignee date")
    empty_return_date: Optional[str] = Field(None, description="Empty container return date")
    
    # Demurrage (Inside Terminal: Discharge -> Gate-out)
    demurrage_days_elapsed: float = 0.0
    demurrage_free_days_allowed: int = 10
    demurrage_last_free_day: Optional[str] = None
    demurrage_exceeded_days: float = 0.0
    demurrage_status: str = Field("WITHIN_FREE_TIME", description="WITHIN_FREE_TIME, CRITICAL, OVERDUE, COMPLETED")
    demurrage_estimated_cost: float = 0.0
    
    # Detention (Outside with Consignee: Gate-out -> Empty Return)
    detention_days_elapsed: float = 0.0
    detention_free_days_allowed: int = 10
    detention_last_free_day: Optional[str] = None
    detention_exceeded_days: float = 0.0
    detention_status: str = Field("NOT_STARTED", description="NOT_STARTED, WITHIN_FREE_TIME, CRITICAL, OVERDUE, COMPLETED")
    detention_estimated_cost: float = 0.0

    currency: str = "USD"
    is_official_carrier_data: bool = False


class DnDReport(BaseModel):
    reference: str = Field(..., description="B/L or Container reference")
    carrier: str = "CMA CGM"
    containers: List[ContainerDnDDetail] = []
    total_demurrage_cost_est: float = 0.0
    total_detention_cost_est: float = 0.0
    currency: str = "USD"
    has_active_overdue: bool = False
    generated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


# ── 4. Transport Document / Manifest Models ───────────────────────────────────

class PartyDetails(BaseModel):
    role: str = Field(..., description="Shipper, Consignee, NotifyParty, etc.")
    name: str
    address: Optional[str] = None
    country: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    tax_id: Optional[str] = None


class ManifestCargoItem(BaseModel):
    description: str
    hs_code: Optional[str] = None
    gross_weight_kg: Optional[float] = None
    gross_volume_cbm: Optional[float] = None
    package_count: Optional[int] = None
    package_type: Optional[str] = None


class TransportDocumentManifest(BaseModel):
    document_reference: str = Field(..., description="Bill of Lading reference")
    carrier: str
    status: str = Field("ISSUED", description="DRAFT, ISSUED, SURRENDERED, etc.")
    issue_date: Optional[str] = None
    shipped_on_board_date: Optional[str] = None
    is_electronic: bool = True
    inco_terms: Optional[str] = None
    parties: List[PartyDetails] = []
    cargo_items: List[ManifestCargoItem] = []
    containers: List[str] = []
    seal_numbers: Dict[str, str] = {}


# ── 5. Full Tracking Response (Comprehensive Tracking Report) ─────────────────

class ContainerTrackingSummary(BaseModel):
    container_number: str
    iso_code: Optional[str] = None
    status: str
    last_milestone: str
    last_milestone_date: Optional[str] = None
    last_location: Optional[str] = None
    is_delivered: bool = False
    is_empty_returned: bool = False


class FullTrackingResponse(BaseModel):
    reference: str = Field(..., description="B/L or Container reference queried")
    carrier: str
    query_timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    total_milestones: int = 0
    containers: List[ContainerTrackingSummary] = []
    vessels: List[VesselProfile] = []
    timeline: List[MilestoneEvent] = []
    dnd_summary: Optional[DnDReport] = None
    origin_port: Optional[str] = None
    destination_port: Optional[str] = None
    transshipment_ports: List[str] = []
    current_status: str = "IN_TRANSIT"
    eta_destination: Optional[str] = None
    eta_classifier: Optional[str] = "ACT"


# ── 6. Inbound Webhook Payload ────────────────────────────────────────────────

class WebhookEventPayload(BaseModel):
    subscription_id: Optional[str] = None
    carrier: str = "CMA CGM"
    event: Dict[str, Any] = {}
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


# ── 7. Booking & Quotation Models ─────────────────────────────────────────────

class BookingRequestPayload(BaseModel):
    carrier: str = "CMA CGM"
    origin_port: str = Field(..., description="UN/LOCODE of origin (e.g. CNSHK, INNSA)")
    destination_port: str = Field(..., description="UN/LOCODE of destination (e.g. SCPOV)")
    container_type: str = Field("40HC", description="20GP, 40GP, 40HC, 40REEF")
    quantity: int = 1
    commodity_description: str
    target_departure_date: Optional[str] = None
    shipper_name: Optional[str] = None
    consignee_name: Optional[str] = None


class BookingConfirmation(BaseModel):
    booking_reference: str
    carrier: str
    status: str = "PENDING_ALLOCATION"
    vessel_name: Optional[str] = None
    voyage_number: Optional[str] = None
    estimated_departure: Optional[str] = None
    estimated_arrival: Optional[str] = None
    total_freight_quote: Optional[float] = None
    currency: str = "USD"

