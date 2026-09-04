"""
Logistics API Engine - Vessel Intelligence Service
Handles vessel master specifications, caching, and fleet enrichment.
"""

from typing import Optional, Dict
from ..models import VesselProfile
from ..providers.cma_cgm_provider import CmaCgmLogisticsProvider


class VesselService:
    def __init__(self, provider: Optional[CmaCgmLogisticsProvider] = None):
        self.provider = provider or CmaCgmLogisticsProvider()
        self._cache: Dict[str, VesselProfile] = {}

    def get_vessel_specs(self, imo: str) -> Optional[VesselProfile]:
        imo_clean = imo.strip()
        if imo_clean in self._cache:
            return self._cache[imo_clean]

        profile = self.provider.get_vessel_info(imo_clean)
        if profile:
            self._cache[imo_clean] = profile
        return profile
