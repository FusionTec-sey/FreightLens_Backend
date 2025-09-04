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

# Example usage:
# discharge_data = get_discharge_events(your_json_data)
# print(discharge_data)