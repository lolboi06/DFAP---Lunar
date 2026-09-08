"""
Immutable Evidence Storage Abstraction for DFAP LDRM (DFAP Stage 3).
Provides write-once, tamper-proof raw evidence storage with SHA-256 chain-of-custody verification.
Explicitly forbids overwrite_original().
"""
import hashlib
from pathlib import Path
from typing import Dict, Any, Optional
from dataclasses import dataclass
from dfap.ldrm_subsystem.domain.utils import utc_now


class EvidenceStorageError(ValueError):
    pass


@dataclass
class EvidenceRecord:
    evidence_id: str
    response_id: str
    request_id: str
    case_id: str
    provider_id: str
    received_at: str
    sha256: str
    size_bytes: int
    media_type: str
    storage_reference: str
    chain_of_custody_reference: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "response_id": self.response_id,
            "request_id": self.request_id,
            "case_id": self.case_id,
            "provider_id": self.provider_id,
            "received_at": self.received_at,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "media_type": self.media_type,
            "storage_reference": self.storage_reference,
            "chain_of_custody_reference": self.chain_of_custody_reference,
        }


class ImmutableEvidenceStorage:
    """
    Write-once original evidence storage backend.
    """

    def __init__(self, storage_dir: str, repository):
        self.storage_path = Path(storage_dir).joinpath("evidence_originals")
        self.storage_path.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.repository = repository

    def _path(self, evidence_id: str) -> Path:
        """Storage names are derived, never taken from provider-supplied text."""
        if not evidence_id or any(c in evidence_id for c in '/\\.\x00') or len(evidence_id) > 200:
            raise EvidenceStorageError(f"Unsafe evidence identifier: {evidence_id!r}")
        path = self.storage_path.joinpath(f"{evidence_id}.bin").resolve()
        if self.storage_path.resolve() not in path.parents:
            raise EvidenceStorageError("Evidence path escapes the storage directory")
        return path

    def overwrite_original(self, *args, **kwargs):
        """Explicitly absent capability (Stage 3 §20). Original evidence is write-once."""
        raise EvidenceStorageError(
            "Original provider evidence is immutable; overwrite_original() is not implemented")

    def find_by_hash(self, sha256: str):
        """Duplicate detection: has this exact payload already been stored?"""
        with self.repository.lock:
            rows = self.repository.connection.execute(
                "SELECT * FROM evidence_store_metadata WHERE sha256=?", (sha256,)).fetchall()
        return [r["evidence_id"] for r in rows]

    def store_derived(self, evidence_id: str, artifact_name: str, content: bytes) -> dict:
        """Derived artifacts live beside, never inside, the original record."""
        original = self.get_record(evidence_id)
        derived_dir = self.storage_path.parent.joinpath("evidence_derived", evidence_id)
        derived_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        safe = hashlib.sha256(artifact_name.encode()).hexdigest()[:32]
        path = derived_dir.joinpath(f"{safe}.bin")
        path.write_bytes(content)
        return {"evidence_id": evidence_id, "artifact_name": artifact_name,
                "storage_reference": str(path), "sha256": hashlib.sha256(content).hexdigest(),
                "derived_from_sha256": original.sha256}

    def store_original(
        self,
        evidence_id: str,
        response_id: str,
        request_id: str,
        case_id: str,
        provider_id: str,
        raw_payload: bytes,
        media_type: str = "application/json",
        actor_id: str = "system"
    ) -> EvidenceRecord:
        digest = hashlib.sha256(raw_payload).hexdigest()
        file_path = self._path(evidence_id)

        # Write-once enforcement: check if file or metadata already exists
        if file_path.exists():
            existing_bytes = file_path.read_bytes()
            if hashlib.sha256(existing_bytes).hexdigest() != digest:
                raise EvidenceStorageError(f"Tamper attempt detected: Original evidence '{evidence_id}' cannot be overwritten")
            # If exact duplicate content, return existing record
            return self.get_record(evidence_id)

        # Persist raw bytes read-only. Provider content is stored, never executed.
        file_path.write_bytes(raw_payload)
        file_path.chmod(0o400)

        custody_ref = f"COC-{evidence_id[:8]}-{digest[:8]}"
        record = EvidenceRecord(
            evidence_id=evidence_id,
            response_id=response_id,
            request_id=request_id,
            case_id=case_id,
            provider_id=provider_id,
            received_at=utc_now().isoformat(),
            sha256=digest,
            size_bytes=len(raw_payload),
            media_type=media_type,
            storage_reference=str(file_path),
            chain_of_custody_reference=custody_ref,
        )

        with self.repository.lock:
            self.repository.connection.execute(
                "INSERT INTO evidence_store_metadata VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    record.evidence_id,
                    record.response_id,
                    record.request_id,
                    record.case_id,
                    record.provider_id,
                    record.received_at,
                    record.sha256,
                    record.size_bytes,
                    record.media_type,
                    record.storage_reference,
                    record.chain_of_custody_reference,
                ),
            )

        return record

    def get_original(self, evidence_id: str) -> bytes:
        file_path = self._path(evidence_id)
        if not file_path.exists():
            raise EvidenceStorageError(f"Evidence file for ID '{evidence_id}' not found")
        content = file_path.read_bytes()
        record = self.get_record(evidence_id)
        if hashlib.sha256(content).hexdigest() != record.sha256:
            raise EvidenceStorageError(f"Evidence integrity error: SHA-256 mismatch for '{evidence_id}'")
        return content

    def get_record(self, evidence_id: str) -> EvidenceRecord:
        with self.repository.lock:
            row = self.repository.connection.execute(
                "SELECT * FROM evidence_store_metadata WHERE evidence_id=?", (evidence_id,)
            ).fetchone()
            if not row:
                raise EvidenceStorageError(f"Evidence metadata for ID '{evidence_id}' not found")
            return EvidenceRecord(
                evidence_id=row["evidence_id"],
                response_id=row["response_id"],
                request_id=row["request_id"],
                case_id=row["case_id"],
                provider_id=row["provider_id"],
                received_at=row["received_at"],
                sha256=row["sha256"],
                size_bytes=row["size_bytes"],
                media_type=row["media_type"],
                storage_reference=row["storage_reference"],
                chain_of_custody_reference=row["chain_of_custody_reference"],
            )

    def verify_hash(self, evidence_id: str, expected_sha256: str) -> bool:
        record = self.get_record(evidence_id)
        content = self.get_original(evidence_id)
        actual = hashlib.sha256(content).hexdigest()
        return record.sha256 == expected_sha256 and actual == expected_sha256
