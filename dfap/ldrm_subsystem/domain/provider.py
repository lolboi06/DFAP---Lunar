"""
Provider Domain Entity for Lawful Data Request Module.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Any, Optional
import uuid

from dfap.ldrm_subsystem.domain.enums import (
    ProviderCategory,
    ProviderVerificationStatus,
    ProviderActiveStatus,
    DatasetType,
    TransmissionMethod,
)
from dfap.ldrm_subsystem.domain.utils import utc_now

@dataclass
class ProviderDestination:
    id: str
    method: TransmissionMethod
    address: str
    verified_by: Optional[str] = None
    verified_at: Optional[datetime] = None


@dataclass
class Provider:
    """
    Represents an external entity (Telecom Operator, ISP, Financial Institution, etc.)
    registered with the lawful data request system.
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    category: ProviderCategory = ProviderCategory.OTHER
    jurisdiction: str = "NATIONAL"
    verification_status: ProviderVerificationStatus = ProviderVerificationStatus.PENDING_VERIFICATION
    active_status: ProviderActiveStatus = ProviderActiveStatus.ACTIVE
    supported_datasets: List[DatasetType] = field(default_factory=list)
    contact_details: Dict[str, Any] = field(default_factory=dict)
    submission_methods: List[TransmissionMethod] = field(default_factory=lambda: [TransmissionMethod.MOCK_DISPATCH])
    response_methods: List[str] = field(default_factory=lambda: ['MOCK'])
    destinations: List[ProviderDestination] = field(default_factory=list)
    endpoint_references: Dict[str, str] = field(default_factory=dict)
    required_fields: List[str] = field(default_factory=list)
    required_documents: List[str] = field(default_factory=list)
    configuration_metadata: Dict[str, Any] = field(default_factory=dict)
    last_reviewed_at: Optional[datetime] = None
    verified_by: Optional[str] = None
    verified_at: Optional[datetime] = None
    verification_notes: Optional[str] = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    @property
    def is_eligible_for_dispatch(self) -> bool:
        """
        Only VERIFIED and ACTIVE providers can receive lawful requests.
        """
        return (
            self.verification_status == ProviderVerificationStatus.VERIFIED
            and self.active_status == ProviderActiveStatus.ACTIVE
        )

    def verify(self, verified_by: str, notes: Optional[str] = None) -> None:
        self.verification_status = ProviderVerificationStatus.VERIFIED
        self.verified_by = verified_by
        self.verified_at = utc_now()
        self.last_reviewed_at = self.verified_at
        self.verification_notes = notes
        self.updated_at = utc_now()

    def suspend(self, notes: Optional[str] = None) -> None:
        self.verification_status = ProviderVerificationStatus.SUSPENDED
        self.verification_notes = notes
        self.updated_at = utc_now()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category.value,
            "jurisdiction": self.jurisdiction,
            "verification_status": self.verification_status.value,
            "active_status": self.active_status.value,
            "supported_datasets": [d.value for d in self.supported_datasets],
            "contact_details": self.contact_details,
            "submission_methods": [m.value for m in self.submission_methods],
            "response_methods": self.response_methods,
            "destinations": [{"id": d.id, "method": d.method.value, "address": d.address,
                              "verified_by": d.verified_by, "verified_at": d.verified_at.isoformat() if d.verified_at else None} for d in self.destinations],
            "endpoint_references": self.endpoint_references,
            "required_fields": self.required_fields,
            "required_documents": self.required_documents,
            "configuration_metadata": self.configuration_metadata,
            "last_reviewed_at": self.last_reviewed_at.isoformat() if self.last_reviewed_at else None,
            "verified_by": self.verified_by,
            "verified_at": self.verified_at.isoformat() if self.verified_at else None,
            "verification_notes": self.verification_notes,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }
