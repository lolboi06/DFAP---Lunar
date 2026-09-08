"""
Response Domain Entity for Lawful Data Request Module.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Any, Optional
import uuid

from dfap.ldrm_subsystem.domain.enums import ProviderResponseStatus, IngestionStatus
from dfap.ldrm_subsystem.domain.utils import utc_now

@dataclass
class ProviderResponse:
    """
    Represents an inbound dataset or response received from a provider.
    Maintains exact raw payload integrity, cryptographic hash, and evidence linkage.
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    request_id: str = ""
    transmission_id: str = ""
    raw_payload: bytes = field(default=b"", repr=False)
    verified_at: Optional[datetime] = None
    verified_by: Optional[str] = None
    provider_id: str = ""
    case_id: str = ""
    receipt_timestamp: datetime = field(default_factory=utc_now)
    provider_status: ProviderResponseStatus = ProviderResponseStatus.COMPLETED
    raw_payload_path: str = ""
    raw_payload_hash: str = ""  # SHA-256 over raw received bytes
    evidence_id: Optional[str] = None  # Reference to DFAP M12 Evidence Record
    ingestion_status: IngestionStatus = IngestionStatus.PENDING
    ingestion_result_summary: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def bind_evidence(self, evidence_id: str) -> None:
        self.evidence_id = evidence_id

    def mark_ingested(self, summary: Dict[str, Any]) -> None:
        self.ingestion_status = IngestionStatus.INGESTED
        self.ingestion_result_summary = summary

    def mark_ingestion_failed(self, error: str) -> None:
        self.ingestion_status = IngestionStatus.FAILED
        self.error_message = error

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "request_id": self.request_id,
            "transmission_id": self.transmission_id,
            "verified_at": self.verified_at.isoformat() if self.verified_at else None,
            "verified_by": self.verified_by,
            "provider_id": self.provider_id,
            "case_id": self.case_id,
            "receipt_timestamp": self.receipt_timestamp.isoformat(),
            "provider_status": self.provider_status.value,
            "raw_payload_path": self.raw_payload_path,
            "raw_payload_hash": self.raw_payload_hash,
            "evidence_id": self.evidence_id,
            "ingestion_status": self.ingestion_status.value,
            "ingestion_result_summary": self.ingestion_result_summary,
            "error_message": self.error_message,
            "metadata": self.metadata,
        }
