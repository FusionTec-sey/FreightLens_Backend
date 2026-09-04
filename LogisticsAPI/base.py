"""
Logistics API Engine - Abstract Provider Base Class
Enables pluggable carrier adapters (CMA CGM, Maersk, MSC, Hapag-Lloyd, etc.).
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List
from .models import FullTrackingResponse, VesselProfile, DnDReport, TransportDocumentManifest


class BaseLogisticsProvider(ABC):
    """
    Standard interface for all ocean carrier & freight logistics integrations.
    Any carrier added in the future must implement this interface.
    """

    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    def track_shipment(self, reference: str) -> Optional[FullTrackingResponse]:
        """
        Fetch full tracking data for a Bill of Lading or Container reference.
        Returns complete chronological timeline, container statuses, and vessels.
        """
        pass

    @abstractmethod
    def get_vessel_info(self, imo: str) -> Optional[VesselProfile]:
        """
        Lookup vessel specifications by 7-digit IMO number.
        """
        pass

    @abstractmethod
    def get_dnd_status(self, reference: str, default_free_days: int = 10) -> Optional[DnDReport]:
        """
        Retrieve Demurrage & Detention status and countdown metrics.
        """
        pass

    @abstractmethod
    def get_transport_document(self, bl_reference: str) -> Optional[TransportDocumentManifest]:
        """
        Retrieve official Bill of Lading manifest, cargo specifications, and parties.
        """
        pass

    @abstractmethod
    def parse_webhook_event(self, raw_payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parse an inbound push event from carrier webhook into standardized milestone.
        """
        pass
