"""
Logistics API Engine - Unified Tracking Service
Aggregates and orchestrates tracking across multiple shipping lines.
"""

from typing import Optional, List
from ..models import FullTrackingResponse
from ..base import BaseLogisticsProvider
from ..providers.cma_cgm_provider import CmaCgmLogisticsProvider
from ..providers.maersk_provider import MaerskLogisticsProvider


class TrackingService:
    def __init__(self, providers: Optional[List[BaseLogisticsProvider]] = None):
        if providers:
            self.providers = providers
        else:
            self.providers = [
                CmaCgmLogisticsProvider(),
                MaerskLogisticsProvider(),
            ]

    def track(self, reference: str, carrier: Optional[str] = None) -> Optional[FullTrackingResponse]:
        """
        Tracks a shipment by B/L number or Container number across carriers.
        """
        clean_ref = reference.strip()

        # If specific carrier requested, use it first
        if carrier:
            c_lower = carrier.lower()
            for p in self.providers:
                if c_lower in p.name.lower():
                    res = p.track_shipment(clean_ref)
                    if res:
                        return res

        # Otherwise try providers in priority order
        for p in self.providers:
            try:
                res = p.track_shipment(clean_ref)
                if res and res.total_milestones > 0:
                    return res
            except Exception as e:
                print(f"[TrackingService] Error with provider {p.name}: {e}")
                continue

        return None
