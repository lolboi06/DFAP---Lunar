"""
Transmission Domain Entity for Lawful Data Request Module.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Any, Optional
import uuid

from dfap.ldrm_subsystem.domain.enums import TransmissionMethod, TransmissionStatus
from dfap.ldrm_subsystem.domain.utils import utc_now

@dataclass
class RequestTransmission:
    """
    Represents an outbound dispatch event of an authorized, signed request package to a provider.
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    request_id: str = ""
    case_id: str = ""
    authorization_id: str = ""
    request_version: int = 0
    provider_id: str = ""
    dispatched_by: str = ""
    dispatch_timestamp: datetime = field(default_factory=utc_now)
    transmission_method: TransmissionMethod = TransmissionMethod.MOCK_DISPATCH
    provider_tracking_ref: Optional[str] = None
    package_payload_hash: str = ""  # Hash of transmitted canonical payload
    transmission_status: TransmissionStatus = TransmissionStatus.PENDING
    acknowledgment_timestamp: Optional[datetime] = None
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def acknowledge(self, tracking_ref: Optional[str] = None) -> None:
        self.transmission_status = TransmissionStatus.ACKNOWLEDGED
        self.acknowledgment_timestamp = utc_now()
        if tracking_ref:
            self.provider_tracking_ref = tracking_ref

    def fail(self, error: str) -> None:
        self.transmission_status = TransmissionStatus.FAILED
        self.error_message = error

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "request_id": self.request_id,
            "case_id": self.case_id,
            "authorization_id": self.authorization_id,
            "request_version": self.request_version,
            "provider_id": self.provider_id,
            "dispatched_by": self.dispatched_by,
            "dispatch_timestamp": self.dispatch_timestamp.isoformat(),
            "transmission_method": self.transmission_method.value,
            "provider_tracking_ref": self.provider_tracking_ref,
            "package_payload_hash": self.package_payload_hash,
            "transmission_status": self.transmission_status.value,
            "acknowledgment_timestamp": self.acknowledgment_timestamp.isoformat() if self.acknowledgment_timestamp else None,
            "error_message": self.error_message,
            "metadata": self.metadata,
        }
