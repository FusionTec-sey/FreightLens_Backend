# providers/base.py

from abc import ABC, abstractmethod
from typing import Dict, Any
class BaseShippingProvider(ABC):
    
    @abstractmethod
    def get_BoL(self, bl: str) -> list:
        pass

    @abstractmethod
    def get_arrival(self, container_no: str) -> dict:
        pass
    
class DCSA(ABC):
    """Abstract class defining the interface for container API operations."""

    @abstractmethod
    def track_and_trace(self, transportDocumentReference: str) -> Dict[str, Any]:
        """Track the status and location of a container."""
        pass

    @abstractmethod
    def bill_of_landing(self, transportDocumentReference: str) -> Dict[str, Any]:
        """Retrieve booking information."""
        pass
    
    
