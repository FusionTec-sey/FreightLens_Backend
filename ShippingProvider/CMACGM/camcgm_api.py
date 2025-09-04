from urllib.request import HTTPBasicAuthHandler
import requests
from datetime import datetime, timedelta
from typing import Optional, List, Union, Dict, Any
from .CMA_CGM_helper import get_eta_data

class CMACGMTrackTrace:
    
    def __init__(
        self,
        base_url: str = "https://apis.cma-cgm.net/operation/trackandtrace/v1",
        api_key: Optional[str] = None,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None
     ):
        """
        Initialize the CMA CGM Track & Trace API client.
        
        Args:
            base_url: Base URL for the API
            api_key: API key for public endpoints (optional if using OAuth)
            client_id: OAuth client ID for private endpoints (optional)
            client_secret: OAuth client secret for private endpoints (optional)
        """
        self.base_url = base_url
        self.api_key = api_key
        self.client_id = client_id
        self.client_secret = client_secret
        self.token_url = "https://auth.cma-cgm.com/as/token.oauth2"
        
        # Validate we have at least one authentication method
        if not (api_key or (client_id and client_secret)):
            raise ValueError("Either API key or OAuth credentials must be provided")

    def _get_headers(self, use_oauth: bool = False) -> Dict[str, str]:
        """Get headers for API requests"""
        headers = {"Accept": "application/json"}
        
        if use_oauth:
            token = self._get_oauth_token()
            if token:
                headers["Authorization"] = f"Bearer {token}"
        elif self.api_key:
            headers["keyId"] = self.api_key
        
        return headers

    def _get_oauth_token(self) -> Optional[str]:
        """Get OAuth2 access token for private endpoints"""
        if not (self.client_id and self.client_secret):
            return None
            
        try:
            response = requests.post(
                self.token_url,
                auth=HTTPBasicAuthHandler(self.client_id, self.client_secret),
                data={
                    "grant_type": "client_credentials",
                    "scope": "tandtcommercial:read:be tandtpublic:read:be"
                }
            )
            response.raise_for_status()
            return response.json().get("access_token")
        except requests.exceptions.RequestException as e:
            print(f"Error getting OAuth token: {e}")
            return None

    def search_events(
        self,
        event_type: Optional[Union[str, List[str]]] = None,
        equipment_reference: Optional[str] = None,
        document_type_code: Optional[List[str]] = None,
        carrier_booking_reference: Optional[str] = None,
        transport_document_reference: Optional[str] = None,
        vessel_imo_number: Optional[str] = None,
        transport_call_id: Optional[str] = None,
        shipment_event_type_code: Optional[str] = None,
        un_location_code: Optional[str] = None,
        event_created_since: Optional[datetime] = None,
        event_datetime_before: Optional[datetime] = None,
        behalf_of: Optional[str] = None,
        limit: int = 100,
        cursor: Optional[str] = None,
        use_oauth: bool = False
        ) -> Optional[List[Dict[str, Any]]]:
        """
        Search for tracking events with various filters.
        
        Args:
            event_type: Filter by event type (SHIPMENT, TRANSPORT, EQUIPMENT)
            equipment_reference: Filter by container number
            carrier_booking_reference: Filter by booking reference
            transport_document_reference: Filter by bill of lading number
            vessel_imo_number: Filter by vessel IMO number
            transport_call_id: Filter by transport call ID
            un_location_code: Filter by UN location code
            event_created_since: Filter events created after this datetime
            event_datetime_before: Filter events that occurred before this datetime
            behalf_of: End customer code (mandatory for third parties)
            limit: Maximum number of results to return (default 100)
            cursor: Pagination cursor
            use_oauth: Whether to use OAuth for private endpoints
            
        Returns:
            List of events or None if error occurs
        """
        params = {"limit": limit}
        
        # Add filters to params
        if event_type:
            if isinstance(event_type, list):
                params["eventType"] = ",".join(event_type)
            else:
                params["eventType"] = event_type
        if shipment_event_type_code:
            params["shipmentEventTypeCode"] = shipment_event_type_code
        if equipment_reference:
            params["equipmentReference"] = equipment_reference
        if carrier_booking_reference:
            params["carrierBookingReference"] = carrier_booking_reference
        if transport_document_reference:
            params["transportDocumentReference"] = transport_document_reference
        if vessel_imo_number:
            params["vesselIMONumber"] = vessel_imo_number
        if transport_call_id:
            params["transportCallID"] = transport_call_id
        if un_location_code:
            params["UNLocationCode"] = un_location_code
        if event_created_since:
            params["eventCreatedDateTime:gte"] = event_created_since.isoformat()
        if event_datetime_before:
            params["eventDateTime:lte"] = event_datetime_before.isoformat()
        if behalf_of:
            params["behalfOf"] = behalf_of
        if cursor:
            params["cursor"] = cursor
        if document_type_code:
            params["documentTypeCode"] = document_type_code
        
        try:
            response = requests.get(
                f"{self.base_url}/events",
                headers=self._get_headers(use_oauth),
                params=params
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Error searching events: {e}")
            return None

    def get_events_by_reference(
        self,
        tracking_reference: str,
        behalf_of: Optional[str] = None,
        limit: int = 100,
        cursor: Optional[str] = None,
        use_oauth: bool = False
        ) -> Optional[List[Dict[str, Any]]]:
        """
        Get events for a specific tracking reference (booking or container number).
        
        Args:
            tracking_reference: Booking reference or container number
            behalf_of: End customer code (mandatory for third parties)
            limit: Maximum number of results to return (default 100)
            cursor: Pagination cursor
            use_oauth: Whether to use OAuth for private endpoints
            
        Returns:
            List of events or None if error occurs
        """
        params = {"limit": limit}
        
        if behalf_of:
            params["behalfOf"] = behalf_of
        if cursor:
            params["cursor"] = cursor
        
        try:
            response = requests.get(
                f"{self.base_url}/events/{tracking_reference}",
                headers=self._get_headers(use_oauth),
                params=params
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Error getting events for {tracking_reference}: {e}")
            return None

    def get_container_history(
        self,
        container_number: str,
        days: int = 30,
        use_oauth: bool = False
        ) -> Optional[List[Dict[str, Any]]]:
        """
        Convenience method to get container history with a simple interface.
        
        Args:
            container_number: Container number to track
            days: Number of days of history to retrieve
            use_oauth: Whether to use OAuth for private endpoints
            
        Returns:
            List of events or None if error occurs
        """
        return self.search_events(
            event_type="EQUIPMENT",
            equipment_reference=container_number,
            event_created_since=datetime.utcnow() - timedelta(days=days),
            use_oauth=use_oauth
        )

    def get_booking_status(
        self,
        booking_reference: str,
        use_oauth: bool = False
        ) -> Optional[List[Dict[str, Any]]]:
        """
        Convenience method to get booking status with a simple interface.
        
        Args:
            booking_reference: Booking reference to track
            use_oauth: Whether to use OAuth for private endpoints
            
        Returns:
            List of events or None if error occurs
        """
        return self.get_events_by_reference(
            tracking_reference=booking_reference,
            use_oauth=use_oauth
        )

    def get_BoL(self, bl):
        val = self.search_events(transport_document_reference=bl, event_type="EQUIPMENT")
        # print(val)
        return get_eta_data(val)
                


# Example usage
if __name__ == "__main__":
    # Initialize with either API key or OAuth credentials (or both)
    tracker = CMACGMTrackTrace(
        api_key="X2wG7Gc7In0roXj2u1OG2qp4yMIhHwOm",
        client_id="beapp-fusiontech",
        client_secret="T3FefGXrLjQBWCQT98D1VsbKXb1aKGgOWamRUSGWkDmvlNzR1ZsLv0El8XF7RDFS"
    )
    
    print(tracker.get_BoL("GGZ2601947"))
    # # Example 1: Search for container events in last 7 days
    # container_events = tracker.search_events(
    #     event_type="EQUIPMENT",
    #     equipment_reference="APZU4812090",
    #     event_created_since=datetime.utcnow() - timedelta(days=7)
    # )
    
    # if container_events:
    #     print(f"Found {len(container_events)} container events")
    #     for event in container_events:
    #         print(f"{event.get('eventType')} at {event.get('eventDateTime')}")
    
    # Example 2: Get events by booking reference
    # booking_events = tracker.get_events_by_reference("TLLU5021050")
    
    # print(booking_events)
        
    # if booking_events:
    #     print(f"\nFound {len(booking_events)} booking events")
    #     for event in booking_events:
    #         print(f"{event.get('eventType')} at {event.get('eventDateTime')}")
    
    # # Example 3: Convenience method for container history
    # container_history = tracker.get_container_history("APZU4812090", days=30)
    
    # # Example 4: Convenience method for booking status
    # booking_status = tracker.get_booking_status("ABC709951")