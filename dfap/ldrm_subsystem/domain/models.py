"""
Core Domain Models for Lawful Data Request Module (LDRM).
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Any, Optional
import uuid
import json
from datetime import timezone

from dfap.ldrm_subsystem.domain.enums import (
    RequestStatus,
    AuthorityType,
    DatasetType,
    TargetType,
    Priority,
)
from dfap.ldrm_subsystem.domain.utils import utc_now

@dataclass
class RequestTarget:
    """
    Represents an identifier target within the requested dataset scope.
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    target_type: TargetType = TargetType.PHONE_NUMBER
    target_value: str = ""
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    requested_categories: List[str] = field(default_factory=list)
    justification: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "target_type": self.target_type.value,
            "target_value": self.target_value,
            "start_time": self.start_time.astimezone(timezone.utc).isoformat() if self.start_time and self.start_time.tzinfo else (self.start_time.isoformat() if self.start_time else None),
            "end_time": self.end_time.astimezone(timezone.utc).isoformat() if self.end_time and self.end_time.tzinfo else (self.end_time.isoformat() if self.end_time else None),
            "requested_categories": sorted(self.requested_categories),
            "justification": self.justification,
        }

    def canonical_dict(self) -> Dict[str, Any]:
        """Returns deterministic dictionary representation for canonical hashing."""
        return {
            "target_type": self.target_type.value,
            "target_value": self.target_value.strip(),
            "start_time": self.start_time.astimezone(timezone.utc).isoformat() if self.start_time and self.start_time.tzinfo else (self.start_time.isoformat() if self.start_time else None),
            "end_time": self.end_time.astimezone(timezone.utc).isoformat() if self.end_time and self.end_time.tzinfo else (self.end_time.isoformat() if self.end_time else None),
            "requested_categories": sorted(self.requested_categories),
            "justification": self.justification.strip(),
        }


@dataclass
class RequestAuthorization:
    """
    Represents formal legal authorization granted by a designated human authority.
    Must cryptographically bind to the canonical request hash at time of approval.
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    approver_id: str = ""
    approver_name: str = ""
    approver_role: str = ""
    authority_type: AuthorityType = AuthorityType.COURT_ORDER
    authority_reference: str = ""  # e.g., Warrant Number / Court Order Case ID
    issuing_authority: str = ""    # e.g., "District Court of New Delhi"
    approved_scope_summary: str = ""
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None
    bound_request_version: int = 0
    approved_scope: Dict[str, Any] = field(default_factory=dict)
    signer_id: str = ""
    signature_algorithm: str = ""
    bound_canonical_hash: str = ""  # SHA-256 of the request package at moment of approval
    digital_signature: str = ""
    authorized_at: datetime = field(default_factory=utc_now)
    is_invalidated: bool = False
    invalidation_reason: Optional[str] = None
    invalidated_at: Optional[datetime] = None

    def invalidate(self, reason: str) -> None:
        self.is_invalidated = True
        self.invalidation_reason = reason
        self.invalidated_at = utc_now()

    def is_valid_for_hash(self, current_hash: str) -> bool:
        """Verify that authorization has not been invalidated and still matches the current package hash."""
        if self.is_invalidated:
            return False
        if not self.bound_canonical_hash:
            return False
        return self.bound_canonical_hash == current_hash

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "approver_id": self.approver_id,
            "approver_name": self.approver_name,
            "approver_role": self.approver_role,
            "authority_type": self.authority_type.value,
            "authority_reference": self.authority_reference,
            "issuing_authority": self.issuing_authority,
            "approved_scope_summary": self.approved_scope_summary,
            "valid_from": self.valid_from.isoformat() if self.valid_from else None,
            "valid_until": self.valid_until.isoformat() if self.valid_until else None,
            "bound_canonical_hash": self.bound_canonical_hash,
            "bound_request_version": self.bound_request_version,
            "approved_scope": self.approved_scope,
            "signer_id": self.signer_id,
            "signature_algorithm": self.signature_algorithm,
            "digital_signature": self.digital_signature,
            "authorized_at": self.authorized_at.isoformat(),
            "is_invalidated": self.is_invalidated,
            "invalidation_reason": self.invalidation_reason,
            "invalidated_at": self.invalidated_at.isoformat() if self.invalidated_at else None,
        }


@dataclass
class LawfulDataRequest:
    """
    Main entity representing a Lawful Data Request across its entire lifecycle.
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    case_id: str = ""
    request_number: str = ""
    provider_id: str = ""
    dataset_type: DatasetType = DatasetType.CDR
    status: RequestStatus = RequestStatus.DRAFT
    priority: Priority = Priority.ROUTINE
    targets: List[RequestTarget] = field(default_factory=list)
    authorization: Optional[RequestAuthorization] = None
    created_by: str = ""
    assigned_to: Optional[str] = None
    legal_review_notes: Optional[str] = None
    legal_reviewer_id: Optional[str] = None
    canonical_hash: Optional[str] = None
    request_version: int = 1
    revision: int = 1
    scope: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def canonical_dict(self) -> Dict[str, Any]:
        """
        Generates canonical dictionary for deterministic hashing.
        Sorted keys and canonical fields guarantee consistent SHA-256 calculation.
        """
        d_type = getattr(self.dataset_type, 'value', self.dataset_type)
        return {
            "request_id": self.id,
            "scope": self.scope,
            "case_id": self.case_id,
            "dataset_type": d_type,
            "provider_id": self.provider_id,
            "targets": sorted([t.canonical_dict() for t in self.targets], key=lambda t: json.dumps(t, sort_keys=True)),
            "version": self.request_version,
        }

    def to_dict(self) -> Dict[str, Any]:
        d_type = getattr(self.dataset_type, 'value', self.dataset_type)
        stat = getattr(self.status, 'value', self.status)
        prio = getattr(self.priority, 'value', self.priority)
        return {
            "id": self.id,
            "case_id": self.case_id,
            "request_number": self.request_number,
            "provider_id": self.provider_id,
            "dataset_type": d_type,
            "status": stat,
            "priority": prio,
            "targets": [t.to_dict() for t in self.targets],
            "authorization": self.authorization.to_dict() if self.authorization else None,
            "created_by": self.created_by,
            "assigned_to": self.assigned_to,
            "legal_review_notes": self.legal_review_notes,
            "legal_reviewer_id": self.legal_reviewer_id,
            "canonical_hash": self.canonical_hash,
            "request_version": self.request_version,
            "revision": self.revision,
            "scope": self.scope,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }
