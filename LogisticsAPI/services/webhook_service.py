"""
Logistics API Engine - Inbound Webhook Processing & Auto-Seed Service
Receives real-time push event notifications from shipping lines (DCSA standard),
auto-updates container statuses in the database, and provides automated B/L seeding.
"""

from typing import Dict, Any, Optional, List
from datetime import datetime, date
from ..providers.cma_cgm_provider import CmaCgmLogisticsProvider


def _get_db_session():
    """Safely get DB session from main app if available."""
    try:
        from Model.db import get_db
        return next(get_db())
    except Exception as e:
        print(f"[WebhookService] Database session unavailable: {e}")
        return None


class WebhookService:
    def __init__(self, cma_provider: Optional[CmaCgmLogisticsProvider] = None):
        self.cma_provider = cma_provider or CmaCgmLogisticsProvider()

    def process_cma_webhook(self, raw_payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parses inbound DCSA tracking webhook payload from CMA CGM and auto-updates DB records.
        """
        parsed = self.cma_provider.parse_webhook_event(raw_payload)
        eq_ref = parsed.get("equipment_reference")
        ev_code = parsed.get("event_code")
        label = parsed.get("event_label", "")
        dt_str = parsed.get("event_datetime")
        loc_name = parsed.get("location")

        db_updated = False
        db = _get_db_session()

        if db and eq_ref:
            try:
                from Model import ContainerDetails, BillOfLanding
                # Find container by container_no (case-insensitive)
                container = (
                    db.query(ContainerDetails)
                    .filter(ContainerDetails.container_no.ilike(eq_ref.strip()))
                    .first()
                )

                if container:
                    ev_dt = None
                    if dt_str:
                        try:
                            ev_dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00")).replace(tzinfo=None)
                        except Exception:
                            ev_dt = datetime.utcnow()

                    # Update rich tracking fields on container
                    if hasattr(container, "latest_milestone"):
                        container.latest_milestone = label
                    if loc_name and hasattr(container, "port_of_discharge") and not container.port_of_discharge:
                        container.port_of_discharge = loc_name

                    # 1. Vessel Discharge at Port -> Status 2 (On Port)
                    if ev_code == "DISC":
                        container.status = 2
                        if ev_dt:
                            container.unloaded_at_port = ev_dt.date()
                        db_updated = True

                    # 2. Gate Out to Consignee -> Status 3 (Gate Pass)
                    elif "gate out" in label.lower() or ev_code == "GTOT":
                        container.status = 3
                        if ev_dt:
                            container.out_bound = ev_dt
                        db_updated = True

                    # 3. Empty Container Returned -> Status 4 (Complete)
                    elif "empty return" in label.lower() or (ev_code == "GTIN" and "empty" in label.lower()):
                        container.status = 4
                        if ev_dt:
                            container.empty_date = ev_dt.date()
                        db_updated = True

                    # Also update B/L ArrivalDate if discharge event
                    if ev_code == "DISC" and container.BillOfLanding and ev_dt:
                        bl_record = (
                            db.query(BillOfLanding)
                            .filter(BillOfLanding.BillOfLanding == container.BillOfLanding)
                            .first()
                        )
                        if bl_record:
                            bl_record.ArrivalDate = ev_dt.strftime("%Y-%m-%d %H:%M:%S")

                    db.commit()
                    print(f"[WebhookService] Auto-updated container {eq_ref} -> status {container.status}")
            except Exception as e:
                db.rollback()
                print(f"[WebhookService] Database update error for {eq_ref}: {e}")
            finally:
                db.close()

        return {
            "status": "success",
            "message": "Event processed successfully",
            "db_updated": db_updated,
            "event_summary": parsed,
        }

    def auto_seed_bl_to_db(self, bl_reference: str, org_id: int = 1, user_id: int = 1) -> Dict[str, Any]:
        """
        Auto-seeds a Bill of Lading and all discovered containers into the database
        directly from the carrier tracking response with rich details (seals, ports,
        milestones, D&D, auto-selected consignee, provider, and container types).
        """
        tracking = self.cma_provider.track_shipment(bl_reference)
        if not tracking or tracking.total_milestones == 0:
            return {
                "status": "error",
                "message": f"Carrier returned no tracking records for B/L '{bl_reference}'."
            }

        db = _get_db_session()
        if not db:
            return {"status": "error", "message": "Database session unavailable."}

        created_containers = []
        try:
            from Model import BillOfLanding, ContainerDetails, Vessal, ContainerType, Consignee
            from Model.containermgmt.Cinfo.LogisticsProvider import LogisticsProvider

            # 1. Resolve or Create Vessel
            vessel_id = None
            vessel_name = None
            if tracking.vessels:
                top_vessel = tracking.vessels[0]
                v_name = top_vessel.name.strip()
                ves_record = db.query(Vessal).filter(Vessal.VessalNo.ilike(v_name)).first()
                if not ves_record:
                    ves_record = Vessal(VessalNo=v_name, created_by=user_id, updated_by=user_id)
                    db.add(ves_record)
                    db.flush()
                vessel_id = ves_record.id
                vessel_name = ves_record.VessalNo

            # 2. Resolve Logistics Provider (e.g. CMA CGM -> Provider ID 1)
            provider_id = None
            provider_name = tracking.carrier
            if tracking.carrier:
                prov_record = db.query(LogisticsProvider).filter(
                    LogisticsProvider.Name.ilike(f"%{tracking.carrier}%")
                ).first()
                if prov_record:
                    provider_id = prov_record.Id
                    provider_name = prov_record.Name

            # 3. Resolve / Auto-select Consignee
            consignee_id = None
            consignee_name = None
            all_consignees = db.query(Consignee).filter(Consignee.is_deleted == False).all()
            if all_consignees:
                # Default to primary consignee (e.g. SAHAJANAND / NOBLECON)
                chosen = next((c for c in all_consignees if "SAHAJANAND" in c.consignee_name.upper()), all_consignees[0])
                consignee_id = chosen.consignee_id
                consignee_name = chosen.consignee_name

            # 4. Resolve or Create BillOfLanding with rich manifest data
            bl_record = db.query(BillOfLanding).filter(BillOfLanding.BillOfLanding == bl_reference).first()
            if not bl_record:
                bl_record = BillOfLanding(
                    BillOfLanding=bl_reference,
                    Vessel=vessel_id,
                    Provider=provider_id,
                    Consignee=consignee_id,
                    ArrivalDate=tracking.eta_destination,
                    FreeDays=10,
                    status=1,  # In Transit
                    origin_port=tracking.origin_port,
                    destination_port=tracking.destination_port,
                    transshipment_ports=tracking.transshipment_ports,
                    carrier_name=tracking.carrier,
                    raw_tracking_data=tracking.dict(),
                    created_by=user_id,
                    updated_by=user_id
                )
                if hasattr(bl_record, "org_id"):
                    bl_record.org_id = org_id
                db.add(bl_record)
                db.flush()
            else:
                if tracking.eta_destination:
                    bl_record.ArrivalDate = tracking.eta_destination
                if vessel_id and not bl_record.Vessel:
                    bl_record.Vessel = vessel_id
                if provider_id and not bl_record.Provider:
                    bl_record.Provider = provider_id
                if consignee_id and not bl_record.Consignee:
                    bl_record.Consignee = consignee_id
                bl_record.origin_port = tracking.origin_port
                bl_record.destination_port = tracking.destination_port
                bl_record.transshipment_ports = tracking.transshipment_ports
                bl_record.carrier_name = tracking.carrier
                bl_record.raw_tracking_data = tracking.dict()

            # 5. Create or Update Discovered Containers with full details
            for c_info in tracking.containers:
                c_num = c_info.container_number.strip().upper()
                c_record = (
                    db.query(ContainerDetails)
                    .filter(ContainerDetails.container_no == c_num)
                    .first()
                )

                # Determine status code
                c_status = 1  # In Transit
                if c_info.is_empty_returned:
                    c_status = 4  # Complete
                elif c_info.is_delivered:
                    c_status = 3  # Gate Pass
                elif "discharged" in c_info.status.lower():
                    c_status = 2  # On Port

                # Resolve container type (e.g. 40 High Cube Container, 20 Dry Freight Container)
                type_id = None
                type_name = "Standard"
                if c_info.iso_code:
                    iso = c_info.iso_code.upper()
                    if "45" in iso or "40HC" in iso:
                        search_term = "%40 High Cube%"
                        type_name = "40 High Cube Container"
                    elif "22" in iso or "20" in iso:
                        search_term = "%20 Dry%"
                        type_name = "20 Dry Freight Container"
                    elif "42" in iso:
                        search_term = "%40 Dry%"
                        type_name = "40 Dry Container"
                    else:
                        search_term = "%40 High Cube%" if "4" in iso else "%20 Dry%"
                    t_record = db.query(ContainerType).filter(ContainerType.type.ilike(search_term)).first()
                    if t_record:
                        type_id = t_record.type_id
                        type_name = t_record.type

                # Milestones & D&D for this container
                c_milestones = [m.dict() for m in tracking.timeline if m.equipment_reference == c_num]
                c_dnd = next((d.dict() for d in tracking.dnd_summary.containers if d.container_number == c_num), None) if tracking.dnd_summary else None

                disc_date = None
                gate_out_dt = None
                empty_dt = None
                for m in c_milestones:
                    m_code = m.get("event_code")
                    m_label = (m.get("event_label") or "").lower()
                    m_dt_str = m.get("event_datetime")
                    if m_dt_str:
                        try:
                            p_dt = datetime.fromisoformat(m_dt_str.replace("Z", "+00:00")).replace(tzinfo=None)
                            if m_code == "DISC" and m.get("transportation_phase") == "Import":
                                disc_date = p_dt.date()
                            elif "gate out" in m_label or m_code == "GTOT":
                                gate_out_dt = p_dt
                            elif "empty return" in m_label or (m_code == "GTIN" and m.get("empty_indicator") == "EMPTY"):
                                empty_dt = p_dt.date()
                        except Exception:
                            pass

                if not c_record:
                    c_record = ContainerDetails(
                        container_no=c_num,
                        BillOfLanding=bl_reference,
                        status=c_status,
                        type=type_id,
                        FreeDays=10,
                        port_of_loading=tracking.origin_port,
                        port_of_discharge=tracking.destination_port,
                        transshipment_hub=tracking.transshipment_ports[0] if tracking.transshipment_ports else None,
                        latest_milestone=c_info.last_milestone,
                        tracking_timeline=c_milestones,
                        dnd_report=c_dnd,
                        unloaded_at_port=disc_date,
                        out_bound=gate_out_dt,
                        empty_date=empty_dt,
                        created_by=user_id,
                        updated_by=user_id
                    )
                    if hasattr(c_record, "org_id"):
                        c_record.org_id = org_id
                    db.add(c_record)
                    created_containers.append({
                        "container_no": c_num,
                        "status": c_status,
                        "type_id": type_id,
                        "type_name": type_name,
                        "iso_code": c_info.iso_code,
                        "location": c_info.last_location,
                        "milestone": c_info.last_milestone,
                        "created": True
                    })
                else:
                    c_record.BillOfLanding = bl_reference
                    c_record.status = c_status
                    if type_id and not c_record.type:
                        c_record.type = type_id
                    c_record.port_of_loading = tracking.origin_port
                    c_record.port_of_discharge = tracking.destination_port
                    c_record.transshipment_hub = tracking.transshipment_ports[0] if tracking.transshipment_ports else None
                    c_record.latest_milestone = c_info.last_milestone
                    c_record.tracking_timeline = c_milestones
                    c_record.dnd_report = c_dnd
                    if disc_date:
                        c_record.unloaded_at_port = disc_date
                    if gate_out_dt:
                        c_record.out_bound = gate_out_dt
                    if empty_dt:
                        c_record.empty_date = empty_dt
                    created_containers.append({
                        "container_no": c_num,
                        "status": c_status,
                        "type_id": type_id or c_record.type,
                        "type_name": type_name,
                        "iso_code": c_info.iso_code,
                        "location": c_info.last_location,
                        "milestone": c_info.last_milestone,
                        "created": False
                    })

            db.commit()
            return {
                "status": "success",
                "message": f"Seeded B/L '{bl_reference}' with {len(created_containers)} containers.",
                "billOfLading": bl_reference,
                "consignee_id": consignee_id,
                "consignee_name": consignee_name,
                "provider_id": provider_id,
                "provider_name": provider_name,
                "vessel_id": vessel_id,
                "vessel_name": vessel_name,
                "arrivalDate": tracking.eta_destination,
                "origin_port": tracking.origin_port,
                "destination_port": tracking.destination_port,
                "transshipment_ports": tracking.transshipment_ports,
                "containers": created_containers,
            }
        except Exception as e:
            db.rollback()
            print(f"[WebhookService] Auto-seed error: {e}")
            return {"status": "error", "message": str(e)}
        finally:
            db.close()
