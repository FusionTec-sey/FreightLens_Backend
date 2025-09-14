# from ShippingProvider import CMACGM
# from auth.config import settings
# cmacgm = CMACGM(
#     client_id=settings.CMA_CGM_CLIENT_ID,
#     client_secret=settings.CMA_CGM_SECRET,
#     token_url=settings.CMA_CGM_TOKEN_URL,
#     api_key=settings.CMA_CGM_API_KEY,
#     # api_url=settings.CMA_CGM_TRACK_AND_TRACE_URL
#     )



# with open("output.txt", "w") as file:
#     file.write(str(cmacgm.bi(transportDocumentReference="GGZ2601947")))
    
    
    
from ShippingProvider import Maersk, CMACGM
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
            
            # Get vessel IMO number from transportCall
            vessel_imo = None
            transport_call = event.get('transportCall', {})
            vessel_info = transport_call.get('vessel', {})
            if vessel_info:
                vessel_imo = vessel_info.get('vesselIMONumber')
            
            # Only add if we haven't processed this container yet
            if container_no not in processed_containers:
                discharge_events.append({
                    'eventDateTime': event_datetime,
                    'vesselIMONumber': vessel_imo,
                    'containerNo': container_no
                })
                processed_containers.add(container_no)
    
    return discharge_events

def get_container_vessel_arrival_date(data, target_location_code="SCVIC"):
    for event in data.get("events", []):
        if event.get("transportCall", {}).get("UNLocationCode") == target_location_code:
            return {
                "eventDateTime": event.get("eventDateTime"),
                "vesselIMONumber": event.get("transportCall", {}).get("vessel", {}).get("vesselIMONumber")
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
    # api_url=settings.CMA_CGM_TRACK_AND_TRACE_URL
    )

providers = [maersk, CmaCgm]
# with open("output.txt", "w") as file:
#     file.write(str(maersk.track_and_trace(transportDocumentReference="255553918")))
content = []
containers = []

for provider in providers:
    try:
        content = provider.track_and_trace(transportDocumentReference="GGZ2601947")
        # print(content)
        if provider.__class__.__name__ == "CMACGM":
            content = {'events': content}
            # print(list(set(extract_values(content, "equipmentReference"))))
            # for container in list(set(extract_values(content, "equipmentReference"))):
    
            containers.append( get_eta_data(content.get('events')))
        else:
            for container in list(set(extract_values(content, "equipmentReference"))):

                # containers.append( get_container_vessel_arrival_date(content))
                arrival_info = get_container_vessel_arrival_date(content)
                if arrival_info:
                    arrival_info["containerNo"] = container
                    containers.append(arrival_info)
                    

        if len(content.get("events")) == 0:
            continue
        else:
            break
        
    except Exception as e:
        # print(f"Error with provider {provider.__class__.__name__}: {e}")
        continue



print(containers)






 