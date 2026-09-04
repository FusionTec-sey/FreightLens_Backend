"""
Logistics API Engine - Demurrage & Detention (D&D) Engine
Computes port terminal dwell time (Demurrage) and consignee possession time (Detention),
monitors Last Free Day (LFD) countdowns, and calculates accrued penalty fees.
"""

from typing import Optional
from ..models import DnDReport
from ..providers.cma_cgm_provider import CmaCgmLogisticsProvider


class DemurrageDetentionEngine:
    def __init__(self, provider: Optional[CmaCgmLogisticsProvider] = None):
        self.provider = provider or CmaCgmLogisticsProvider()

    def evaluate_dnd(self, reference: str, default_free_days: int = 10) -> Optional[DnDReport]:
        """
        Runs hybrid D&D evaluation:
        1. Checks official carrier D&D API conditions.
        2. Falls back to deriving exact days from live discharge, gate-out, and empty-return milestones.
        """
        return self.provider.get_dnd_status(reference, default_free_days=default_free_days)
