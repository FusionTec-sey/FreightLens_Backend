# from .TrackAndTrace import trackAndTrace
# from datetime import datetime

# def format_local_iso8601(iso_datetime_str):
#     dt = datetime.fromisoformat(iso_datetime_str)
#     return dt.strftime("%Y-%m-%d  ")  # %B = full month name

# def getContainerVessaleArrivalDate(data, target_location_code="SCVIC"):
    
#     """
#     Returns eventDateTime and vesselIMONumber for the first event with the specified UNLocationCode.

#     Parameters:
#         data (dict): JSON-like structure with 'events' list.
#         target_location_code (str): The UNLocationCode to filter by (default: "SCVIC").

#     Returns:
#         dict or None: Dictionary with eventDateTime and vesselIMONumber or None if not found.
#     """
    
#     for event in data.get("events", []):
#         if event.get("transportCall", {}).get("UNLocationCode") == target_location_code:
#             return {
#                 "eventDateTime": event.get("eventDateTime"),
#                 "vesselIMONumber": event.get("transportCall", {}).get("vessel", {}).get("vesselIMONumber")
#             }
#     return None

# def getContainerList(data):
#     """
#     Extract unique referenceValue entries where referenceType == 'EQ' from events.
    
#     Parameters:
#         data (dict): JSON-like dict containing 'events' with 'references'

#     Returns:
#         list: Unique EQ reference values
#     """
#     if not isinstance(data, dict) or "events" not in data:
#         return []

#     unique_values = {
#         ref["referenceValue"]
#         for event in data["events"]
#         for ref in event.get("references", [])
#         if ref.get("referenceType") == "EQ"
#     }

#     return list(unique_values)

# def getContainerDetails(bl):
#     try:
#         containers  =    trackAndTrace({
#                                 "transportDocumentReference": bl,
#                                 "eventType"                 : "SHIPMENT",
#                                 "shipmentEventTypeCode"     : "RECE"
                                
#                             })
#     except Exception as err:
#         return "Please Check BL"
        
#     containerDetails = []
#     for conNo in getContainerList(containers):
#         details =   trackAndTrace(param={
#                                 "equipmentReference": conNo,
#                                 "eventType"                 : "TRANSPORT",
#                                 "transportEventTypeCode"     :"ARRI"    
#                     })
        
#         data = getContainerVessaleArrivalDate(details)
#         data["containerNo"] = conNo
#         containerDetails.append(data)
#     return containerDetails
        
# # print(getContainerDetails("253003164"))

# def getArrivalDate(containerNo):
#     try:    
#         details =   trackAndTrace(param={
#                             "equipmentReference": containerNo,
#                             "eventType"                 : "TRANSPORT",
#                             "transportEventTypeCode"     :"ARRI"    
#                 })
        
#         return getContainerVessaleArrivalDate(details)["eventDateTime"]
#     except Exception as es:
#         return "Please Check Container Number"

# # print(getArrivalDate("MRKU5890699"))

from datetime import datetime

def format_local_iso8601(iso_datetime_str):
    dt = datetime.fromisoformat(iso_datetime_str)
    return dt.strftime("%Y-%m-%d")

def get_container_vessel_arrival_date(data, target_location_code="SCVIC"):
    for event in data.get("events", []):
        if event.get("transportCall", {}).get("UNLocationCode") == target_location_code:
            return {
                "eventDateTime": event.get("eventDateTime"),
                "vesselIMONumber": event.get("transportCall", {}).get("vessel", {}).get("vesselIMONumber")
            }
    return None

def get_container_list(data):
    if not isinstance(data, dict) or "events" not in data:
        return []

    unique_values = {
        ref["referenceValue"]
        for event in data["events"]
        for ref in event.get("references", [])
        if ref.get("referenceType") == "EQ"
    }
    return list(unique_values)
