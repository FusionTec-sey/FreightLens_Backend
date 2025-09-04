import requests
import time

# Replace these with your actual credentials
CLIENT_ID = "RVgxOM09RDSTUAAAPQ0KHHYCZbrIXxAv"
CLIENT_SECRET = "L1ThtaCvgSvQVrG3"
TOKEN_URL = "https://api.maersk.com/customer-identity/oauth/v2/access_token"
TRACK_AND_TRACE_URL = "https://api.maersk.com/track-and-trace-private/events"
def test_maersk_api_directly():
    # Step 1: Get access token
    token_headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Consumer-Key": CLIENT_ID,
    }
    token_data = {
        "grant_type": "client_credentials",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    }
    
    token_response = requests.post(TOKEN_URL, headers=token_headers, data=token_data)
    token_response.raise_for_status()
    token_json = token_response.json()
    access_token = token_json.get("access_token")
    
    if not access_token:
        print("Failed to get access token")
        return
    
    print(f"Access token: {access_token}")
    
    # Step 2: Test Bill of Lading endpoint
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Consumer-Key": CLIENT_ID,
    }
    
    # Test with a sample Bill of Lading
    test_bl = "255352222"  # Replace with a real BL number
    bl_params = {
        "transportDocumentReference": test_bl,
        "eventType": "SHIPMENT",
        # "shipmentEventTypeCode": "RECE"
    }
    
    print(f"\nTesting Bill of Lading: {test_bl}")
    bl_response = requests.get(TRACK_AND_TRACE_URL, headers=headers, params=bl_params)
    try:
        bl_response.raise_for_status()
        bl_data = bl_response.json()
        print(f"BL Response: {bl_data}")
        
        # Extract container numbers from response (simplified)
        container_numbers = []
        if 'containers' in bl_data:
            container_numbers = [c['number'] for c in bl_data['containers']]
        print(f"Containers found: {container_numbers}")
        
    except Exception as e:
        print(f"Error getting BL data: {e}")
    
    # Step 3: Test Container endpoint
    test_container = "MRKU3587810"  # Replace with a real container number
    container_params = {
        "equipmentReference": test_container,
        "eventType": "TRANSPORT",
        "transportEventTypeCode": "ARRI"
    }
    
    print(f"\nTesting Container: {test_container}")
    container_response = requests.get(TRACK_AND_TRACE_URL, headers=headers, params=container_params)
    try:
        container_response.raise_for_status()
        container_data = container_response.json()
        print(f"Container Response: {container_data}")
        
        # Extract arrival info (simplified)
        arrival_info = {}
        if 'events' in container_data:
            for event in container_data['events']:
                if event.get('type') == 'ARRI':
                    arrival_info = {
                        'vessel': event.get('vesselName'),
                        'voyage': event.get('voyageNumber'),
                        'terminal': event.get('terminal'),
                        'arrivalDate': event.get('timestamp')
                    }
                    break
        print(f"Arrival info: {arrival_info}")
        
    except Exception as e:
        print(f"Error getting container data: {e}")

if __name__ == "__main__":
    test_maersk_api_directly()