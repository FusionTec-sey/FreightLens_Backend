# # providers/maersk_api.py

import time
import requests
# from config import CLIENT_ID, CLIENT_SECRET, TOKEN_URL, TRACK_AND_TRACE_URL
from auth.config import settings
from ..base import BaseShippingProvider
from .mearsk_helpers import get_container_list, get_container_vessel_arrival_date


class MaerskAPI(BaseShippingProvider):
    
    def __init__(self):
        self.client_id = settings.CLIENT_ID
        self.client_secret = settings.CLIENT_SECRET
        self.token_url = settings.TOKEN_URL
        self.api_url = settings.TRACK_AND_TRACE_URL
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

        response = requests.post(self.token_url, headers=headers, data=data)
        response.raise_for_status()
        json_data = response.json()

        access_token = json_data.get("access_token")
        expires_in = json_data.get("expires_in", 3600)
        if not access_token:
            raise Exception(f"Token not found in response: {json_data}")

        self._token_data["access_token"] = access_token
        self._token_data["expires_at"] = current_time + expires_in - 30
        # print(access_token)
        return access_token

    def _make_request(self, params: dict) -> dict:
        token = self._get_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Consumer-Key": self.client_id,
        }
        response = requests.get(self.api_url, headers=headers, params=params)
        response.raise_for_status()
        return response.json()

    def get_BoL(self, bl: str) -> list:
        try:
            containers = self._make_request({
                "transportDocumentReference": bl,
                "eventType": "SHIPMENT"
                # "shipmentEventTypeCode": "RECE"
            })
        except Exception:
            return []
        # print(f"Containers for BL {bl}: {containers}")
        container_details = []
        for con_no in get_container_list(containers):
            try:
                data = self._make_request({
                    "equipmentReference": con_no,
                    "eventType": "TRANSPORT",
                    "transportEventTypeCode": "ARRI",
                    "transportDocumentReference": bl
                })
                arrival_info = get_container_vessel_arrival_date(data)
                if arrival_info:
                    arrival_info["containerNo"] = con_no
                    container_details.append(arrival_info)
            except Exception:
                continue  # skip if one container fails
        # print(data)
        return container_details

    def get_arrival(self, container_no: str) -> dict:
        try:
            data = self._make_request({
                "equipmentReference": container_no,
                "eventType": "TRANSPORT",
                "transportEventTypeCode": "ARRI"
            })
            return get_container_vessel_arrival_date(data)
        except Exception:
            return {}


# import time
# import requests
# from config import CLIENT_ID, CLIENT_SECRET, TOKEN_URL, TRACK_AND_TRACE_URL
# from ..base import BaseShippingProvider
# from .mearsk_helpers import get_container_list, get_container_vessel_arrival_date


# class MaerskAPI(BaseShippingProvider):
    
#     def __init__(self):
#         self.client_id = CLIENT_ID
#         self.client_secret = CLIENT_SECRET
#         self.token_url = TOKEN_URL
#         self.api_url = TRACK_AND_TRACE_URL
#         self._token_data = {"access_token": None, "expires_at": 0}
#         self._initialize_token()

#     def _initialize_token(self) -> None:
#         """Fetch and store a new access token"""
#         headers = {
#             "Content-Type": "application/x-www-form-urlencoded",
#             "Consumer-Key": self.client_id,
#         }
#         data = {
#             "grant_type": "client_credentials",
#             "client_id": self.client_id,
#             "client_secret": self.client_secret,
#         }

#         try:
#             response = requests.post(self.token_url, headers=headers, data=data)
#             response.raise_for_status()
#             json_data = response.json()

#             access_token = json_data.get("access_token")
#             expires_in = json_data.get("expires_in", 3600)
#             print(access_token)
#             if not access_token:
#                 raise Exception(f"Token not found in response: {json_data}")

#             self._token_data["access_token"] = access_token
#             self._token_data["expires_at"] = time.time() + expires_in - 30  # 30 second buffer
#         except Exception as e:
#             raise Exception(f"Failed to initialize token: {str(e)}")

#     def _token_is_valid(self) -> bool:
#         """Check if the stored token is still valid"""
#         return (self._token_data["access_token"] and 
#                 time.time() < self._token_data["expires_at"])

#     def _refresh_token_if_needed(self) -> None:
#         """Refresh the token if it's expired or about to expire"""
#         if not self._token_is_valid():
#             self._initialize_token()

#     def _make_request(self, params: dict) -> dict:
#         """Make API request with automatic token refresh"""
#         self._refresh_token_if_needed()
        
#         headers = {
#             "Authorization": f"Bearer {self._token_data['access_token']}",
#             "Consumer-Key": self.client_id,
#         }
        
#         try:
#             response = requests.get(self.api_url, headers=headers, params=params)
#             response.raise_for_status()
#             return response.json()
#         except requests.exceptions.HTTPError as http_err:
#             if response.status_code == 401:  # Unauthorized (possibly token expired)
#                 # Try once more with a fresh token
#                 self._initialize_token()
                
#                 headers["Authorization"] = f"Bearer {self._token_data['access_token']}"
#                 response = requests.get(self.api_url, headers=headers, params=params)
#                 response.raise_for_status()
#                 return response.json()
#             raise  # Re-raise other HTTP errors

#     def get_BoL(self, bl: str) -> list:
#         try:
#             containers = self._make_request({
#                 "transportDocumentReference": bl,
#                 "eventType": "SHIPMENT"
#             })
#         except Exception as e:
#             print(f"Error getting BL {bl}: {str(e)}")
#             return []
        
#         print(f"Containers for BL {bl}: {containers}")
#         container_details = []
#         for con_no in get_container_list(containers):
#             try:
#                 data = self._make_request({
#                     "equipmentReference": con_no,
#                     # "eventType": "TRANSPORT"
#                     # "transportEventTypeCode": "ARRI"
#                 })
#                 arrival_info = get_container_vessel_arrival_date(data)
#                 if arrival_info:
#                     arrival_info["containerNo"] = con_no
#                     container_details.append(arrival_info)
#             except Exception as e:
#                 print(f"Error getting container {con_no} data: {str(e)}")
#                 continue
#         return container_details

#     def get_arrival(self, container_no: str) -> dict:
#         try:
#             data = self._make_request({
#                 "equipmentReference": container_no,
#                 "eventType": "TRANSPORT",
#                 "transportEventTypeCode": "ARRI"
#             })
#             return get_container_vessel_arrival_date(data)
#         except Exception as e:
#             print(f"Error getting arrival for container {container_no}: {str(e)}")
#             return {}
        
