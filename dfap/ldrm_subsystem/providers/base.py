"""
Provider Adapter Interface for Lawful Data Request Module.
"""
from abc import ABC, abstractmethod
import hashlib
from typing import Dict, Any, Optional

from dfap.ldrm_subsystem.domain.transmission import RequestTransmission
from dfap.ldrm_subsystem.domain.response import ProviderResponse

class ProviderDispatchError(Exception):
    """Raised when dispatching to a provider fails."""
    pass


class ProviderAdapter(ABC):
    """
    Abstract adapter for communicating with external lawful data providers.
    Encapsulates protocol-specific transport (Mock, Secure API, SFTP, Portal).
    """

    @property
    @abstractmethod
    def adapter_name(self) -> str:
        """Name of the adapter."""
        pass

    @abstractmethod
    def dispatch(self, transmission: RequestTransmission, canonical_payload: Dict[str, Any]) -> RequestTransmission:
        """
        Dispatches a signed canonical request package to the provider.
        Returns the updated transmission with tracking ref and status.
        """
        pass

    @abstractmethod
    def get_status(self, provider_tracking_ref: str) -> Dict[str, Any]:
        """
        Fetches current status of a previously dispatched request.
        """
        pass

    @abstractmethod
    def retrieve_response(self, provider_tracking_ref: str) -> Optional[ProviderResponse]:
        """
        Retrieves the provider's response payload when ready.
        """
        pass

    def verify_response(self, response: ProviderResponse) -> bool:
        """Common response integrity contract, also used by communication connectors."""
        return bool(response.raw_payload_hash and hashlib.sha256(response.raw_payload).hexdigest() == response.raw_payload_hash)
