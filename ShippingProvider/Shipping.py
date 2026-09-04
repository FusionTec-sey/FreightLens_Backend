
    
# from ShippingProvider import Maersk, CMACGM
from .CMACGM_New.CmaCgm import CMACGM
from .Mearsk_New.MearskApi import Maersk
from auth.config import settings
import ast
from arrange import extract_values

def get_eta_data(events_data):
    """
    Returns discharge events at final destination port with vessel IMO number.
    Looks for DISC events with transportationPhase: 'Import'.
    """
    discharge_events = []
    processed_containers = set()
    
    for event in events_data:
        # Look for IMPORT discharge events (final destination arrival)
        if (event.get('eventType') in ['EQUIPMENT', 'EQUIPMENT'] and
            event.get('equipmentReference') and
            event.get('equipmentEventTypeCode') == 'DISC' and
            event.get('eventDateTime') and
            event.get('carrierSpecificData', {}).get('transportationPhase') == 'Import'):
            
            container_no = event['equipmentReference']
            event_datetime = event['eventDateTime']
            
            # Get vessel IMO and Name from transportCall
            vessel_imo = None
            vessel_name = None
            transport_call = event.get('transportCall', {})
            vessel_info = transport_call.get('vessel', {})
            if vessel_info:
                vessel_imo = vessel_info.get('vesselIMONumber')
                vessel_name = vessel_info.get('vesselName')
            if not vessel_name and str(vessel_imo) == "9261918":
                vessel_name = "CMA CGM NANSHA"
            
            # Only add if we haven't processed this container yet
            if container_no not in processed_containers:
                discharge_events.append({
                    'eventDateTime': event_datetime,
                    'vesselIMONumber': vessel_imo,
                    'vesselName': vessel_name,
                    'containerNo': container_no
                })
                processed_containers.add(container_no)
    
    return discharge_events

def get_container_vessel_arrival_date(data, target_location_code=["SCVIC", "SCPOV"]):
    if isinstance(target_location_code, str):
        target_codes = {target_location_code}
    else:
        target_codes = set(target_location_code)
        
    for event in data.get("events", []):
        tc = event.get("transportCall") or {}
        if tc.get("UNLocationCode") in target_codes:
            vessel = tc.get("vessel") or {}
            v_imo = vessel.get("vesselIMONumber")
            v_name = vessel.get("vesselName")
            if not v_name and str(v_imo) == "9261918":
                v_name = "CMA CGM NANSHA"
            return {
                "eventDateTime": event.get("eventDateTime"),
                "vesselIMONumber": v_imo,
                "vesselName": v_name
            }
    return None

maersk = Maersk(
    client_id=settings.MEARSK_CLIENT_ID,
    client_secret=settings.MEARSK_SECRET,
    token_url=settings.MEARSK_TOKEN_URL

    )

CmaCgm = CMACGM(
    client_id=settings.CMA_CGM_CLIENT_ID,
    client_secret=settings.CMA_CGM_SECRET,
    token_url=settings.CMA_CGM_TOKEN_URL,
    api_key=settings.CMA_CGM_API_KEY,
    )


def track_and_trace(transportDocumentReference):
    """
    Unified Track & Trace entrypoint.
    Executes commercial LogisticsAPI engine:
    1. Fetches multi-carrier tracking, vessels, and D&D.
    2. Seeds / updates all rich data in the background into PostgreSQL.
    3. Returns rich container records with auto-selected consignee, provider, and container types.
    """
    clean_ref = str(transportDocumentReference).strip().upper()
    try:
        from LogisticsAPI.services.webhook_service import WebhookService
        svc = WebhookService()
        seed_res = svc.auto_seed_bl_to_db(clean_ref)
        if seed_res.get("status") == "success" and seed_res.get("containers"):
            results = []
            for c in seed_res["containers"]:
                c_num = c.get("container_no")
                results.append({
                    "containerNo": c_num,
                    "container_no": c_num,
                    "eventDateTime": seed_res.get("arrivalDate"),
                    "provider": seed_res.get("provider_name") or "CMA CGM",
                    "provider_id": seed_res.get("provider_id"),
                    "consignee_id": seed_res.get("consignee_id"),
                    "consignee_name": seed_res.get("consignee_name"),
                    "vessel_id": seed_res.get("vessel_id"),
                    "vesselName": seed_res.get("vessel_name"),
                    "type_id": c.get("type_id"),
                    "type_name": c.get("type_name"),
                    "iso_code": c.get("iso_code"),
                    "state": c.get("milestone") or "In Transit",
                    "status": "Completed" if c.get("status") == 4 else "Gate Pass" if c.get("status") == 3 else "On Port" if c.get("status") == 2 else "In Transit",
                    "location": c.get("location") or seed_res.get("destination_port") or "",
                    "origin_port": seed_res.get("origin_port"),
                    "destination_port": seed_res.get("destination_port"),
                    "transshipment_ports": seed_res.get("transshipment_ports") or [],
                })
            if results:
                return results
    except Exception as err:
        print(f"[ShippingProvider] LogisticsAPI auto-seed fallback: {err}")

    # Legacy fallback loop if needed
    providers = [maersk, CmaCgm]
    content = []
    containers = []
    for provider in providers:
        try:
            content = provider.track_and_trace(transportDocumentReference=transportDocumentReference)
            if provider.__class__.__name__ == "CMACGM":
                content = {'events': content}
                containers = get_eta_data(content.get('events'))
                if not containers:
                    c_list = list(set(extract_values(content, "equipmentReference")))
                    arrival_info = get_container_vessel_arrival_date(content)
                    if arrival_info:
                        for container in c_list:
                            containers.append({
                                "eventDateTime": arrival_info["eventDateTime"],
                                "vesselIMONumber": arrival_info["vesselIMONumber"],
                                "containerNo": container
                            })
                for c in containers:
                    c["provider"] = "CMA CGM"
            else:
                for container in list(set(extract_values(content, "equipmentReference"))):
                    arrival_info = get_container_vessel_arrival_date(content)
                    if arrival_info:
                        arrival_info["containerNo"] = container
                        containers.append(arrival_info)
                for c in containers:
                    c["provider"] = "Maersk"

            if len(content.get("events")) == 0:
                continue
            else:
                break
        except Exception:
            continue

    return containers    










 