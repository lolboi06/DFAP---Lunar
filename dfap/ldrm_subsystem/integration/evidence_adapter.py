"""Host evidence contract and explicit standalone evidence store."""
import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict
from dfap.ldrm_subsystem.domain.utils import utc_now
from dfap.ldrm_subsystem.persistence.repositories import SQLiteRepository


@dataclass
class EvidenceRecord:
    evidence_id: str
    case_id: str
    source_name: str
    payload_hash: str
    byte_length: int
    mime_type: str = 'application/octet-stream'
    registered_at: datetime = field(default_factory=utc_now)
    w3c_prov_urn: str = ''
    metadata: Dict[str, Any] = field(default_factory=dict)


class EvidenceAdapter(ABC):
    @abstractmethod
    def register_evidence(self, case_id, source_name, raw_payload_bytes, payload_hash, metadata=None):
        """Preserve bytes, deduplicating on metadata['response_id'] for retries."""
        ...

    @abstractmethod
    def verify_evidence_integrity(self, evidence_id, raw_payload_bytes): ...

    @abstractmethod
    def get_evidence(self, evidence_id): ...


class LocalEvidenceAdapter(EvidenceAdapter):
    """Standalone storage, not an implementation of an absent DFAP evidence system."""
    def __init__(self, repository=None):
        self.repository = repository or SQLiteRepository()

    def register_evidence(self, case_id, source_name, raw_payload_bytes, payload_hash, metadata=None):
        if hashlib.sha256(raw_payload_bytes).hexdigest() != payload_hash:
            raise ValueError('Evidence hash mismatch')
        metadata = metadata or {}
        identity = metadata.get('response_id') or f'{source_name}:{payload_hash}'
        evidence_id = 'EVID-' + hashlib.sha256(f'{case_id}:{identity}'.encode()).hexdigest()
        with self.repository.transaction():
            try:
                existing = self.repository.get('evidence', evidence_id, EvidenceRecord)
            except KeyError:
                existing = None
            if existing:
                if existing.payload_hash != payload_hash or existing.case_id != case_id or existing.metadata != metadata:
                    raise ValueError('Evidence retry does not match original registration')
                return existing
            self.repository.preserve(raw_payload_bytes)
            record = EvidenceRecord(evidence_id, case_id, source_name, payload_hash, len(raw_payload_bytes),
                                    w3c_prov_urn=f'urn:dfap:prov:evidence:{evidence_id}', metadata=metadata)
            self.repository.put('evidence', evidence_id, record, immutable=True)
            return record

    def verify_evidence_integrity(self, evidence_id, raw_payload_bytes):
        record = self.get_evidence(evidence_id)
        return bool(record and record.payload_hash == hashlib.sha256(raw_payload_bytes).hexdigest()
                    and self.repository.read_artifact(record.payload_hash) == raw_payload_bytes)

    def get_evidence(self, evidence_id):
        try:
            return self.repository.get('evidence', evidence_id, EvidenceRecord)
        except KeyError:
            return None


DefaultEvidenceAdapter = LocalEvidenceAdapter
