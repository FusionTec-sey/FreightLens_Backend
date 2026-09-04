# # providers/maersk_api.py

import time
import requests
# from config import CLIENT_ID, CLIENT_SECRET, TOKEN_URL, TRACK_AND_TRACE_URL
from auth.config import settings
from ..DCSA import BaseShippingProvider
from .mearsk_helpers import get_container_list, get_container_vessel_arrival_date


class MaerskAPI(BaseShippingProvider):
    
    def __init__(self):
        self.client_id = settings.MEARSK_CLIENT_ID
        self.client_secret = settings.MEARSK_SECRET
        self.token_url = settings.MEARSK_TOKEN_URL
        self.api_url = settings.MEARSK_TRACK_AND_TRACE_URL
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

    def get_BoL(self,bl: str) -> list:
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

