"""
Logistics API Engine - CMA CGM Provider Implementation
Implements Track & Trace, Vessel Referential, Demurrage & Detention,
Bill of Lading manifests, and Push Webhook processing for the CMA CGM group
(CMA CGM, ANL, APL, CNC).
"""

import time
import requests
import os
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from ..base import BaseLogisticsProvider
from ..models import (
    FullTrackingResponse,
    MilestoneEvent,
    LocationInfo,
    VesselProfile,
    ContainerTrackingSummary,
    ContainerDnDDetail,
    DnDReport,
    TransportDocumentManifest,
    PartyDetails,
    ManifestCargoItem
)

def _get_setting(key: str, default: str = "") -> str:
    val = os.getenv(key)
    if val:
        return val
    # Robust .env search paths
    for env_path in [".env", "/app/.env", os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))]:
        if os.path.exists(env_path):
            try:
                with open(env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            if k.strip() == key:
                                return v.strip()
            except Exception:
                pass
    return default


class CmaCgmLogisticsProvider(BaseLogisticsProvider):
    """
    Commercial-grade CMA CGM Carrier Provider.
    Supports OAuth2 private endpoints and API Key public referentials.
    """

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        api_key: Optional[str] = None,
        token_url: str = "https://auth.cma-cgm.com/as/token.oauth2",
        tnt_base_url: str = "https://apis.cma-cgm.net/operation/trackandtrace/v1/events",
        vessel_ref_url: str = "https://apis.cma-cgm.net/referential/vessel/v1/vessels",
        bl_base_url: str = "https://apis.cma-cgm.net/shipping/shipment/billoflading/v3/transport-documents",
        dnd_base_url: str = "https://apis.cma-cgm.net/pricing/demurrage-detention/v1/conditions",
    ):
        super().__init__(name="CMA CGM")
        self.client_id = client_id or _get_setting("CMA_CGM_CLIENT_ID", "")
        self.client_secret = client_secret or _get_setting("CMA_CGM_SECRET", "")
        self.api_key = api_key or _get_setting("CMA_CGM_API_KEY", "")
        self.token_url = _get_setting("CMA_CGM_TOKEN_URL", token_url)
        self.tnt_base_url = _get_setting("CMA_CGM_TRACK_AND_TRACE_URL", tnt_base_url)
        self.vessel_ref_url = vessel_ref_url
        self.bl_base_url = _get_setting("CMA_CGM_SHIPEMENTS_URL", bl_base_url)
        self.dnd_base_url = dnd_base_url

        self._token_cache: Dict[str, Any] = {"token": None, "expires_at": 0}
        self._vessel_cache: Dict[str, VesselProfile] = {}

    # ── 1. Authentication ─────────────────────────────────────────────────────

    def _get_access_token(self, scope: str = "tandtcommercial:read:be") -> Optional[str]:
        now = time.time()
        if self._token_cache["token"] and now < self._token_cache["expires_at"]:
            return self._token_cache["token"]

        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Consumer-Key": self.api_key,
        }
        data = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "scope": scope,
        }

        try:
            res = requests.post(self.token_url, headers=headers, data=data, timeout=12)
            if res.status_code == 200:
                res_data = res.json()
                token = res_data.get("access_token")
                expires_in = res_data.get("expires_in", 300)
                self._token_cache["token"] = token
                self._token_cache["expires_at"] = now + expires_in - 30
                return token
            else:
                print(f"[CmaCgmProvider] Token error {res.status_code}: {res.text[:200]}")
        except Exception as err:
            print(f"[CmaCgmProvider] Token exception: {err}")
        return None

    def _get_api_headers(self, scope: str = "tandtcommercial:read:be") -> Dict[str, str]:
        headers = {
            "Consumer-Key": self.api_key,
            "Accept": "application/json",
        }
        token = self._get_access_token(scope)
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    # ── 2. Rich Track & Trace Engine ──────────────────────────────────────────

    def track_shipment(self, reference: str) -> Optional[FullTrackingResponse]:
        """
        Queries CMA CGM Track & Trace events and transforms into rich FullTrackingResponse.
        Accepts either Bill of Lading reference (e.g. GGZ2601947) or container number.
        """
        headers = self._get_api_headers(scope="tandtcommercial:read:be")
        
        # Check if reference is container (4 letters + 7 digits) or B/L
        params: Dict[str, Any] = {"limit": 100}
        clean_ref = reference.strip().upper()
        if len(clean_ref) == 11 and clean_ref[:4].isalpha() and clean_ref[4:].isdigit():
            params["equipmentReference"] = clean_ref
        else:
            params["transportDocumentReference"] = clean_ref

        try:
            res = requests.get(self.tnt_base_url, headers=headers, params=params, timeout=15)
            if res.status_code != 200:
                print(f"[CmaCgmProvider] Track error {res.status_code}: {res.text[:200]}")
                return None
            
            raw_events = res.json()
            if not isinstance(raw_events, list):
                return None

            return self._transform_events_to_response(clean_ref, raw_events)
        except Exception as err:
            print(f"[CmaCgmProvider] Track exception: {err}")
            return None

    def _transform_events_to_response(self, reference: str, raw_events: List[Dict[str, Any]]) -> FullTrackingResponse:
        parsed_milestones: List[MilestoneEvent] = []
        containers_map: Dict[str, Dict[str, Any]] = {}
        vessels_seen: Dict[str, Dict[str, Any]] = {}
        ports_encountered: List[str] = []

        # Sort events chronologically (oldest to newest)
        sorted_events = sorted(
            raw_events,
            key=lambda x: x.get("eventDateTime") or x.get("eventCreatedDateTime") or ""
        )

        for e in sorted_events:
            ev_type = e.get("eventType") or "EQUIPMENT"
            ev_code = e.get("equipmentEventTypeCode") or e.get("transportEventTypeCode") or e.get("shipmentEventTypeCode") or "UNKNOWN"
            carrier_data = e.get("carrierSpecificData") or {}
            ev_label = carrier_data.get("internalEventLabel") or ev_code
            classifier = e.get("eventClassifierCode") or "ACT"
            dt = e.get("eventDateTime")
            phase = carrier_data.get("transportationPhase")
            eq_ref = e.get("equipmentReference")
            iso = e.get("ISOEquipmentCode")
            empty_ind = e.get("emptyIndicatorCode")

            tc = e.get("transportCall") or {}
            loc_data = tc.get("location") or {}
            un_loc = tc.get("UNLocationCode") or loc_data.get("UNLocationCode")
            facility = tc.get("facilityCode")
            loc_name = loc_data.get("locationName") or un_loc
            mode = tc.get("modeOfTransport") or "VESSEL"
            voyage = tc.get("carrierVoyageNumber")

            # Extract Vessel
            vessel_obj = tc.get("vessel") or {}
            ves_name = vessel_obj.get("vesselName")
            ves_imo = vessel_obj.get("vesselIMONumber")
            ves_flag = vessel_obj.get("vesselFlag")

            if un_loc and un_loc not in ports_encountered:
                ports_encountered.append(un_loc)

            if ves_imo and ves_imo not in vessels_seen:
                vessels_seen[ves_imo] = {
                    "imo": ves_imo,
                    "name": ves_name or f"Vessel IMO {ves_imo}",
                    "vessel_flag": ves_flag
                }

            loc_info = LocationInfo(
                un_location_code=un_loc,
                location_name=loc_name,
                facility_code=facility,
                facility_name=loc_data.get("address", {}).get("name"),
                country=loc_data.get("address", {}).get("country"),
                latitude=float(loc_data["latitude"]) if loc_data.get("latitude") else None,
                longitude=float(loc_data["longitude"]) if loc_data.get("longitude") else None,
            )

            milestone = MilestoneEvent(
                event_id=e.get("eventID"),
                event_type=ev_type,
                event_code=ev_code,
                event_label=ev_label,
                classifier=classifier,
                event_datetime=dt,
                transportation_phase=phase,
                equipment_reference=eq_ref,
                iso_equipment_code=iso,
                empty_indicator=empty_ind,
                location=loc_info,
                vessel_name=ves_name,
                vessel_imo=ves_imo,
                voyage_number=voyage,
                mode_of_transport=mode,
            )
            parsed_milestones.append(milestone)

            # Container Status Mapping
            if eq_ref:
                if eq_ref not in containers_map:
                    containers_map[eq_ref] = {
                        "container_number": eq_ref,
                        "iso_code": iso,
                        "status": "In Transit",
                        "last_milestone": ev_label,
                        "last_milestone_date": dt,
                        "last_location": loc_name or un_loc,
                        "is_delivered": False,
                        "is_empty_returned": False,
                    }
                
                # Update latest milestone
                c_item = containers_map[eq_ref]
                c_item["last_milestone"] = ev_label
                c_item["last_milestone_date"] = dt
                c_item["last_location"] = loc_name or un_loc
                if iso:
                    c_item["iso_code"] = iso

                if "gate out" in ev_label.lower():
                    c_item["status"] = "Released to Consignee"
                    c_item["is_delivered"] = True
                elif "empty return" in ev_label.lower() or (ev_code == "GTIN" and empty_ind == "EMPTY"):
                    c_item["status"] = "Empty Container Returned"
                    c_item["is_empty_returned"] = True
                elif ev_code == "DISC" and phase == "Import":
                    c_item["status"] = "Discharged at Destination"
                elif ev_code == "LOAD":
                    c_item["status"] = f"Loaded on {ves_name or 'Vessel'}"

        # Fetch Vessel Master Specs for vessels seen
        vessel_profiles: List[VesselProfile] = []
        for imo, basic_v in vessels_seen.items():
            profile = self.get_vessel_info(imo)
            if profile:
                vessel_profiles.append(profile)
            else:
                vessel_profiles.append(VesselProfile(imo=imo, name=basic_v["name"], vessel_flag=basic_v.get("vessel_flag")))

        # Determine Origin, Destination, Transshipment
        origin_port = ports_encountered[0] if ports_encountered else None
        destination_port = ports_encountered[-1] if len(ports_encountered) > 1 else None
        transshipment_ports = ports_encountered[1:-1] if len(ports_encountered) > 2 else []

        # Find ETA / Destination arrival
        eta_destination = None
        eta_classifier = "ACT"
        for m in reversed(parsed_milestones):
            if m.event_code in ["ARRI", "DISC"] and (m.location and m.location.un_location_code == destination_port or m.transportation_phase == "Import"):
                eta_destination = m.event_datetime
                eta_classifier = m.classifier
                break

        # Compute D&D Report from milestones
        dnd_report = self._compute_dnd_from_milestones(reference, parsed_milestones, containers_map)

        # Global Shipment Status
        all_empty_returned = all(c.get("is_empty_returned") for c in containers_map.values()) if containers_map else False
        any_delivered = any(c.get("is_delivered") for c in containers_map.values()) if containers_map else False
        if all_empty_returned:
            current_status = "COMPLETED_EMPTY_RETURNED"
        elif any_delivered:
            current_status = "CARGO_RELEASED_TO_CONSIGNEE"
        elif any(m.event_code == "DISC" and m.transportation_phase == "Import" for m in parsed_milestones):
            current_status = "DISCHARGED_AT_PORT"
        else:
            current_status = "IN_TRANSIT"

        container_summaries = [
            ContainerTrackingSummary(**c) for c in containers_map.values()
        ]

        return FullTrackingResponse(
            reference=reference,
            carrier=self.name,
            total_milestones=len(parsed_milestones),
            containers=container_summaries,
            vessels=vessel_profiles,
            timeline=list(reversed(parsed_milestones)), # Newest first for UI display
            dnd_summary=dnd_report,
            origin_port=origin_port,
            destination_port=destination_port,
            transshipment_ports=transshipment_ports,
            current_status=current_status,
            eta_destination=eta_destination,
            eta_classifier=eta_classifier,
        )

    # ── 3. Live Vessel Referential Integration ────────────────────────────────

    def get_vessel_info(self, imo: str) -> Optional[VesselProfile]:
        """
        Fetches official vessel master specs from CMA CGM Vessel Referential API.
        Uses in-memory caching to avoid repeat calls for the same ship.
        """
        imo_clean = imo.strip()
        if imo_clean in self._vessel_cache:
            return self._vessel_cache[imo_clean]

        headers = {
            "Consumer-Key": self.api_key,
            "keyId": self.api_key,
            "Accept": "application/json",
        }
        url = f"{self.vessel_ref_url}?imo={imo_clean}"

        try:
            res = requests.get(url, headers=headers, timeout=8)
            if res.status_code == 200:
                data = res.json()
                if isinstance(data, list) and len(data) > 0:
                    v = data[0]
                    profile = VesselProfile(
                        imo=str(v.get("imo") or imo_clean),
                        name=v.get("name") or f"IMO {imo_clean}",
                        vessel_code=v.get("vesselCode"),
                        vessel_flag=v.get("vesselFlag"),
                        call_sign=v.get("callSign"),
                        status=v.get("status"),
                        built_year=v.get("builtYear"),
                        delivery_date=v.get("deliveryDate"),
                        builder_name=v.get("builder", {}).get("name"),
                        classification_society=v.get("classificationSociety"),
                        teu_capacity=v.get("teuCapacity"),
                        reefer_plugs=v.get("reeferPlugs"),
                        deadweight_tonnage=v.get("deadWeight"),
                        gross_tonnage=v.get("grossTonnage"),
                        length_overall_m=v.get("lengthOverall"),
                        beam_m=v.get("beam"),
                        draught_m=v.get("draught"),
                        speed_knots=v.get("speed"),
                        operator_name=v.get("operator", {}).get("name"),
                        cargo_gear=v.get("cargoGear"),
                    )
                    self._vessel_cache[imo_clean] = profile
                    return profile
        except Exception as err:
            print(f"[CmaCgmProvider] Vessel lookup error for {imo_clean}: {err}")
        return None

    # ── 4. Detention & Demurrage (D&D) Engine ─────────────────────────────────

    def get_dnd_status(self, reference: str, default_free_days: int = 10) -> Optional[DnDReport]:
        """
        Retrieves D&D report. Attempts official carrier API first; if unactivated,
        derives exact Demurrage (Port) and Detention (Consignee) days from tracking milestones.
        """
        # 1. Attempt official D&D API call
        headers = self._get_api_headers(scope="demurragedetention:read:be")
        try:
            dnd_res = requests.get(
                f"{self.dnd_base_url}?transportDocumentReference={reference}",
                headers=headers,
                timeout=6
            )
            if dnd_res.status_code == 200:
                official_data = dnd_res.json()
                # If carrier provides official data, parse and return
                return self._parse_official_dnd(reference, official_data)
        except Exception:
            pass

        # 2. Seamless Fallback: Derive from Tracking Milestones
        tracking = self.track_shipment(reference)
        if tracking and tracking.dnd_summary:
            return tracking.dnd_summary

        return DnDReport(reference=reference, carrier=self.name, containers=[])

    def _compute_dnd_from_milestones(
        self,
        reference: str,
        milestones: List[MilestoneEvent],
        containers_map: Dict[str, Any],
        free_days: int = 10
    ) -> DnDReport:
        dnd_containers: List[ContainerDnDDetail] = []
        total_dem_cost = 0.0
        total_det_cost = 0.0
        has_overdue = False
        now_dt = datetime.utcnow()

        for c_num, c_info in containers_map.items():
            c_milestones = [m for m in milestones if m.equipment_reference == c_num]
            
            disc_dt = None
            gate_out_dt = None
            empty_return_dt = None

            for m in c_milestones:
                if m.event_code == "DISC" and m.transportation_phase == "Import":
                    disc_dt = m.event_datetime
                elif "gate out" in m.event_label.lower() or m.event_code == "GTOT" and m.transportation_phase == "Import":
                    gate_out_dt = m.event_datetime
                elif "empty return" in m.event_label.lower() or (m.event_code == "GTIN" and m.empty_indicator == "EMPTY"):
                    empty_return_dt = m.event_datetime

            # Parse datetimes to calculate elapsed days
            dem_days = 0.0
            dem_lfd = None
            dem_exceeded = 0.0
            dem_cost = 0.0
            dem_status = "NOT_STARTED"

            if disc_dt:
                try:
                    disc_time = datetime.fromisoformat(disc_dt.replace("Z", "+00:00")).replace(tzinfo=None)
                    end_dem = datetime.fromisoformat(gate_out_dt.replace("Z", "+00:00")).replace(tzinfo=None) if gate_out_dt else now_dt
                    dem_days = max(0.0, round((end_dem - disc_time).total_seconds() / 86400.0, 1))
                    lfd_time = disc_time + timedelta(days=free_days)
                    dem_lfd = lfd_time.strftime("%Y-%m-%d")
                    
                    if dem_days > free_days:
                        dem_exceeded = round(dem_days - free_days, 1)
                        dem_cost = round(dem_exceeded * 65.0, 2) # Standard avg tier rate $65/day
                        dem_status = "OVERDUE" if not gate_out_dt else "COMPLETED_WITH_PENALTY"
                        has_overdue = True
                    else:
                        dem_status = "COMPLETED" if gate_out_dt else "WITHIN_FREE_TIME"
                except Exception:
                    pass

            det_days = 0.0
            det_lfd = None
            det_exceeded = 0.0
            det_cost = 0.0
            det_status = "NOT_STARTED"

            if gate_out_dt:
                try:
                    gate_time = datetime.fromisoformat(gate_out_dt.replace("Z", "+00:00")).replace(tzinfo=None)
                    end_det = datetime.fromisoformat(empty_return_dt.replace("Z", "+00:00")).replace(tzinfo=None) if empty_return_dt else now_dt
                    det_days = max(0.0, round((end_det - gate_time).total_seconds() / 86400.0, 1))
                    det_lfd_time = gate_time + timedelta(days=free_days)
                    det_lfd = det_lfd_time.strftime("%Y-%m-%d")

                    if det_days > free_days:
                        det_exceeded = round(det_days - free_days, 1)
                        det_cost = round(det_exceeded * 85.0, 2) # Standard avg detention tier rate $85/day
                        det_status = "OVERDUE" if not empty_return_dt else "COMPLETED_WITH_PENALTY"
                        has_overdue = True
                    else:
                        det_status = "COMPLETED" if empty_return_dt else "WITHIN_FREE_TIME"
                except Exception:
                    pass

            total_dem_cost += dem_cost
            total_det_cost += det_cost

            dnd_containers.append(
                ContainerDnDDetail(
                    container_number=c_num,
                    iso_code=c_info.get("iso_code"),
                    discharge_date=disc_dt,
                    gate_out_date=gate_out_dt,
                    empty_return_date=empty_return_dt,
                    demurrage_days_elapsed=dem_days,
                    demurrage_free_days_allowed=free_days,
                    demurrage_last_free_day=dem_lfd,
                    demurrage_exceeded_days=dem_exceeded,
                    demurrage_status=dem_status,
                    demurrage_estimated_cost=dem_cost,
                    detention_days_elapsed=det_days,
                    detention_free_days_allowed=free_days,
                    detention_last_free_day=det_lfd,
                    detention_exceeded_days=det_exceeded,
                    detention_status=det_status,
                    detention_estimated_cost=det_cost,
                    currency="USD",
                    is_official_carrier_data=False
                )
            )

        return DnDReport(
            reference=reference,
            carrier=self.name,
            containers=dnd_containers,
            total_demurrage_cost_est=round(total_dem_cost, 2),
            total_detention_cost_est=round(total_det_cost, 2),
            currency="USD",
            has_active_overdue=has_overdue,
        )

    def _parse_official_dnd(self, reference: str, data: Dict[str, Any]) -> DnDReport:
        # Template parser for official API once carrier approves D&D product
        return DnDReport(
            reference=reference,
            carrier=self.name,
            containers=[],
            currency=data.get("currency", "USD"),
        )

    # ── 5. Bill of Lading Manifest Integration ────────────────────────────────

    def get_transport_document(self, bl_reference: str) -> Optional[TransportDocumentManifest]:
        """
        Retrieves DCSA Transport Document v3 for the Bill of Lading.
        Extracts Shipper, Consignee, gross weight, volume, packages, and seals.
        """
        headers = self._get_api_headers(scope="bldraft:read:be")
        url = f"{self.bl_base_url}/{bl_reference.strip()}"

        try:
            res = requests.get(url, headers=headers, timeout=12)
            if res.status_code == 200:
                doc = res.json()
                parties: List[PartyDetails] = []
                for p in doc.get("parties", []):
                    parties.append(
                        PartyDetails(
                            role=p.get("partyFunction") or "Party",
                            name=p.get("partyName") or "Unknown",
                            address=p.get("address", {}).get("street"),
                            country=p.get("address", {}).get("country"),
                            contact_email=p.get("contactDetails", {}).get("email"),
                            contact_phone=p.get("contactDetails", {}).get("phone"),
                            tax_id=p.get("taxLegalPartner"),
                        )
                    )

                cargo_items: List[ManifestCargoItem] = []
                for item in doc.get("consignmentItems", []):
                    cargo_items.append(
                        ManifestCargoItem(
                            description=item.get("descriptionOfGoods") or "General Cargo",
                            hs_code=item.get("hsCode"),
                            gross_weight_kg=item.get("cargoGrossWeight"),
                            gross_volume_cbm=item.get("cargoGrossVolume"),
                            package_count=item.get("numberOfPackages"),
                            package_type=item.get("packageCode"),
                        )
                    )

                containers = [
                    eq.get("equipmentReference") for eq in doc.get("utilizedTransportEquipments", []) if eq.get("equipmentReference")
                ]

                seals = {
                    eq.get("equipmentReference"): eq.get("sealNumber")
                    for eq in doc.get("utilizedTransportEquipments", [])
                    if eq.get("equipmentReference") and eq.get("sealNumber")
                }

                return TransportDocumentManifest(
                    document_reference=bl_reference,
                    carrier=self.name,
                    status=doc.get("transportDocumentStatus", "ISSUED"),
                    issue_date=doc.get("issueDate"),
                    shipped_on_board_date=doc.get("shippedOnBoardDate"),
                    is_electronic=doc.get("isElectronic", True),
                    inco_terms=doc.get("incoTerms"),
                    parties=parties,
                    cargo_items=cargo_items,
                    containers=containers,
                    seal_numbers=seals,
                )
        except Exception as err:
            print(f"[CmaCgmProvider] Transport document error: {err}")
        return None

    # ── 6. Webhook Inbound Parser ─────────────────────────────────────────────

    def parse_webhook_event(self, raw_payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parses inbound DCSA event payload received from CMA CGM webhook subscription.
        """
        event = raw_payload.get("event") or raw_payload
        ev_type = event.get("eventType")
        code = event.get("equipmentEventTypeCode") or event.get("transportEventTypeCode")
        carrier_data = event.get("carrierSpecificData", {})
        label = carrier_data.get("internalEventLabel") or code
        dt = event.get("eventDateTime")
        eq_ref = event.get("equipmentReference")
        tc = event.get("transportCall", {})

        return {
            "carrier": self.name,
            "equipment_reference": eq_ref,
            "event_type": ev_type,
            "event_code": code,
            "event_label": label,
            "event_datetime": dt,
            "location": tc.get("location", {}).get("locationName") or tc.get("UNLocationCode"),
            "vessel_name": tc.get("vessel", {}).get("vesselName"),
            "vessel_imo": tc.get("vessel", {}).get("vesselIMONumber"),
            "processed_at": datetime.utcnow().isoformat(),
        }
