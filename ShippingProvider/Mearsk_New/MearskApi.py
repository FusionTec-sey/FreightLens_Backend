import requests
import time
from typing import Optional, Union, List, Dict, Any
from ..DCSA import DCSA
# from ...auth.config import settings
from auth.config import settings
class Maersk(DCSA):
    
    def __init__(self, client_id: str, client_secret: str, token_url: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.token_url = token_url
        
        self._token_data = {"access_token": None, "expires_at": 0}

    def _get_access_token(self) -> str:
        current_time = time.time()
        if self._token_data["access_token"] and current_time < self._token_data["expires_at"]:
            return self._token_data["access_token"]

        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Consumer-Key": self.client_id,
            
        }
        data = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            
        }
        print(self.token_url)
        response = requests.post(self.token_url, headers=headers, data=data)
        response.raise_for_status()
        json_data = response.json()
        # print(json_data)
        access_token = json_data.get("access_token")
        expires_in = json_data.get("expires_in", 3600)
        
        if not access_token:
            raise Exception(f"Token not found in response: {json_data}")

        self._token_data["access_token"] = access_token
        self._token_data["expires_at"] = current_time + expires_in - 30
        return access_token

    def make_request(self, url: str, params: Dict[str, Any]) -> Dict[str, Any]:
        token = self._get_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Consumer-Key": self.client_id,
        }

        # print(url)
        response = requests.get(url,  headers=headers, params=params)
        response.raise_for_status()
        return response.json()

    def track_and_trace(
        self,
        eventType: Optional[Union[str, List[str]]] = None,
        equipmentReference: Optional[str] = None,
        documentTypeCode: Optional[List[str]] = None,
        carrierBookingReference: Optional[str] = None,
        transportDocumentReference: Optional[str] = None,
        vesselIMONumber: Optional[str] = None,
        transportCallID: Optional[str] = None,
        shipmentEventTypeCode: Optional[str] = None,
        UNLocationCode: Optional[str] = None,
        limit: int = 100,
        cursor: Optional[str] = None
        ) -> Dict[str, Any]:
        """
        General track & trace method that accepts various optional parameters.

        Only parameters that are not None will be included in the request.
        """
        params: Dict[str, Any] = {"limit": limit}

        if eventType:
            if isinstance(eventType, list):
                params["eventType"] = ",".join(eventType)
            else:
                params["eventType"] = eventType

        if equipmentReference:
            params["equipmentReference"] = equipmentReference

        if documentTypeCode:
            params["documentTypeCode"] = ",".join(documentTypeCode)

        if carrierBookingReference:
            params["carrierBookingReference"] = carrierBookingReference

        if transportDocumentReference:
            params["transportDocumentReference"] = transportDocumentReference

        if vesselIMONumber:
            params["vesselIMONumber"] = vesselIMONumber

        if transportCallID:
            params["transportCallID"] = transportCallID

        if shipmentEventTypeCode:
            params["shipmentEventTypeCode"] = shipmentEventTypeCode

        if UNLocationCode:
            params["UNLocationCode"] = UNLocationCode

        if cursor:
            params["cursor"] = cursor

        try:
            data = self.make_request(settings.MEARSK_TRACK_AND_TRACE_URL, params)
            return data
        except requests.HTTPError as http_err:
            print(f"HTTP error occurred: {http_err}")
        except Exception as err:
            print(f"Other error occurred: {err}")
        return {}

    def bill_of_landing(self, transportDocumentReference: str) -> Dict[str, Any]:
        try:
            if transportDocumentReference is None:
                raise ValueError("transportDocumentReference must be provided")
            print(settings.MEARSK_SHIPMENTS_URL + f"/{transportDocumentReference}")
            data = self.make_request(settings.MEARSK_SHIPMENTS_URL + f"/{transportDocumentReference}", {})
            return data
        except requests.HTTPError as http_err:
            print(f"HTTP error occurred: {http_err}")
        except Exception as err:
            print(f"Other error occurred: {err}")
        return {}
    
    