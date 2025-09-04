# providers/base.py

from abc import ABC, abstractmethod

class BaseShippingProvider(ABC):
    @abstractmethod
    def get_BoL(self, bl: str) -> list:
        pass

    @abstractmethod
    def get_arrival(self, container_no: str) -> dict:
        pass
