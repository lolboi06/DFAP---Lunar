"""
Domain models for external Mock Providers subsystem.
These models represent provider-side request tracking, separate from LDRM.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, Any, List, Optional
import uuid


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProviderRequestStatus(str, Enum):
    RECEIVED = "RECEIVED"
    UNDER_REVIEW = "UNDER_REVIEW"
    CLARIFICATION_REQUIRED = "CLARIFICATION_REQUIRED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    PROCESSING = "PROCESSING"
    PARTIAL_RESPONSE = "PARTIAL_RESPONSE"
    COMPLETED = "COMPLETED"


class ProviderUserRole(str, Enum):
    PROVIDER_REVIEWER = "PROVIDER_REVIEWER"
    PROVIDER_SUPERVISOR = "PROVIDER_SUPERVISOR"


@dataclass
class MockProviderRequest:
    provider_request_id: str
    agency_request_reference: str
    agency_case_reference: str
    provider_id: str
    dataset_type: str
    requested_record_categories: List[str] = field(default_factory=list)
    date_range: Dict[str, Any] = field(default_factory=dict)
    received_at: str = field(default_factory=utc_now)
    status: ProviderRequestStatus = ProviderRequestStatus.RECEIVED
    request_package_hash: Optional[str] = None
    provider_notes: str = ""
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider_request_id": self.provider_request_id,
            "agency_request_reference": self.agency_request_reference,
            "agency_case_reference": self.agency_case_reference,
            "provider_id": self.provider_id,
            "dataset_type": self.dataset_type,
            "requested_record_categories": self.requested_record_categories,
            "date_range": self.date_range,
            "received_at": self.received_at,
            "status": self.status.value if isinstance(self.status, Enum) else self.status,
            "request_package_hash": self.request_package_hash,
            "provider_notes": self.provider_notes,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class ProviderWebhookEvent:
    event_id: str
    provider_reference: str
    agency_request_reference: str
    event_type: str
    timestamp: str
    response_reference: Optional[str] = None
    payload: Dict[str, Any] = field(default_factory=dict)
