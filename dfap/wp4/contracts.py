# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: Strict contracts, error taxonomies, and typed models for Member 4

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Dict, List, Optional, Any, Set, Tuple
import json

# Authoritative frozen Member 1–3 artifact SHA-256 baselines
FROZEN_UPSTREAM_MANIFEST = {
    "canonical_events.parquet": "a90e1bf43ad413dc52633237690ae7e55ada89ddeb3005fa218c3fd01d866a63",
    "resolved_entities.parquet": "1eeff0fbb82b6cd9517b71a3f561e5a0de36f51eddeba15acf424ae666ee3096",
    "provenance_ledger.parquet": "6ee4a80405b8d0ff8768077d32a41102cb0a60630b7c713c1a48223a363d181e",
    "graph_features.parquet": "ba0acdd140e804df4c94dcc6c1120140b734c6eed89a48fe7bc960cb01b20940",
    "telecom_features.parquet": "39ffca030550cbe76de6861f725f4c7321671f84ec2b87037d85381e2e344646",
    "financial_features.parquet": "2c8e9c59a7a5e3042c14b742850395818d2c66287ffbd9946f20c7935177478a",
    "social_features.parquet": "3b33e581a4c57637ed391ba946d5343bdd243656a501b0e01f1ff7a6de2e2f1f",
    "m3/findings/findings.parquet": "e25aeb8844f2955bbc0a1336a2e3e115b469d097a28759836ce6d63359723d86",
}

# Required schema definitions per frozen artifact
REQUIRED_SCHEMAS = {
    "canonical_events.parquet": {"event_id", "timestamp", "event_type", "source_domain", "actor_id", "sha256_hash", "attributes"},
    "provenance_ledger.parquet": {"sha256_hash", "source_file", "source_row_index"},
    "resolved_entities.parquet": {"canonical_entity_id"},
    "graph_features.parquet": {"entity_id", "feature_name", "feature_value"},
    "telecom_features.parquet": {"entity_id", "feature_name", "feature_value"},
    "financial_features.parquet": {"entity_id", "feature_name", "feature_value"},
    "social_features.parquet": {"entity_id", "feature_name", "feature_value"},
    "m3/findings/findings.parquet": {"finding_id", "entity_id", "anomaly_type", "composite_score", "evidence_refs", "graph_refs"},
}


class ErrorCode(str, Enum):
    UNKNOWN_FINDING = "UNKNOWN_FINDING"
    MISSING_FEATURE = "MISSING_FEATURE"
    MISSING_EVIDENCE_REF = "MISSING_EVIDENCE_REF"
    MISSING_EVENT = "MISSING_EVENT"
    MISSING_PROVENANCE = "MISSING_PROVENANCE"
    INVALID_SHA256 = "INVALID_SHA256"
    DUPLICATE_EVIDENCE_REF = "DUPLICATE_EVIDENCE_REF"
    DUPLICATE_EVENT_REF = "DUPLICATE_EVENT_REF"
    INCONSISTENT_SOURCE_METADATA = "INCONSISTENT_SOURCE_METADATA"
    INCONSISTENT_EVIDENCE_REFERENCE = "INCONSISTENT_EVIDENCE_REFERENCE"
    SCHEMA_CONTRACT_ERROR = "SCHEMA_CONTRACT_ERROR"
    INVALID_HOP_COUNT = "INVALID_HOP_COUNT"
    INVALID_TIME_RANGE = "INVALID_TIME_RANGE"
    UPSTREAM_INTEGRITY_ERROR = "UPSTREAM_INTEGRITY_ERROR"
    UNKNOWN_RELATIONSHIP_STATUS = "UNKNOWN_RELATIONSHIP_STATUS"
    REGISTRY_FILE_MISSING = "REGISTRY_FILE_MISSING"
    REGISTRY_CORRUPTED = "REGISTRY_CORRUPTED"
    REGISTRY_SCHEMA_ERROR = "REGISTRY_SCHEMA_ERROR"
    REGISTRY_INVALID_VALUE = "REGISTRY_INVALID_VALUE"
    MALFORMED_STREAM_EVENT = "MALFORMED_STREAM_EVENT"
    DEAD_LETTER_EVENT = "DEAD_LETTER_EVENT"
    STREAM_REPLAY_DUPLICATE = "STREAM_REPLAY_DUPLICATE"


class EvidenceStatus(str, Enum):
    FULLY_EVIDENCED = "FULLY_EVIDENCED"
    PARTIALLY_EVIDENCED = "PARTIALLY_EVIDENCED"
    UNREFERENCED_OR_BROKEN = "UNREFERENCED_OR_BROKEN"


class RelationshipStatus(str, Enum):
    OBSERVED = "OBSERVED"
    INFERRED = "INFERRED"


class UpstreamContractError(Exception):
    """Raised when an upstream contract or schema validation fails."""
    def __init__(self, message: str, error_code: ErrorCode = ErrorCode.SCHEMA_CONTRACT_ERROR):
        super().__init__(message)
        self.error_code = error_code


class EntityRegistryError(UpstreamContractError):
    """Raised when loading or validating the M1 entity registry fails."""
    pass


class EntityRegistrySchemaError(EntityRegistryError):
    """Raised when the M1 entity registry is missing required schema columns."""
    pass


class EntityRegistryValueError(EntityRegistryError):
    """Raised when the M1 entity registry contains malformed values (invalid IDs, confidences, or statuses)."""
    pass


class UpstreamIntegrityError(Exception):
    """Raised when upstream cryptographic hash or file verification fails."""
    def __init__(self, message: str, error_code: ErrorCode = ErrorCode.UPSTREAM_INTEGRITY_ERROR):
        super().__init__(message)
        self.error_code = error_code


@dataclass(frozen=True)
class DeadLetterRecord:
    run_id: str
    correlation_id: str
    source_domain: str
    source_file: str
    source_row_index: int
    error_code: str
    error_message: str
    raw_event_hash: str
    timestamp: str
    raw_payload: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class EvidenceChainError(Exception):
    """Raised when evidence chain resolution or verification encounters an invalid state."""
    def __init__(self, message: str, error_code: ErrorCode, details: Optional[Dict[str, Any]] = None):
        super().__init__(f"[{error_code.value}] {message}")
        self.error_code = error_code
        self.details = details or {}


class WorkspaceError(Exception):
    """Raised when workspace state modification or validation fails."""
    def __init__(self, message: str, error_code: ErrorCode = ErrorCode.SCHEMA_CONTRACT_ERROR):
        super().__init__(f"[{error_code.value}] {message}")
        self.error_code = error_code


@dataclass(frozen=True)
class ProvenanceStep:
    step_index: int
    entity_type: str
    entity_id: str
    activity_type: str
    used_ids: Tuple[str, ...]
    generated_ids: Tuple[str, ...]
    sha256_hash: Optional[str]
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_index": self.step_index,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "activity_type": self.activity_type,
            "used_ids": list(self.used_ids),
            "generated_ids": list(self.generated_ids),
            "sha256_hash": self.sha256_hash,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class CanonicalEvidenceEvent:
    event_id: str
    timestamp: str
    event_type: str
    source_domain: str
    actor_id: str
    target_id: Optional[str]
    sha256_hash: str
    attributes: Dict[str, Any]
    source_file: Optional[str] = None
    source_row_index: Optional[int] = None
    source_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "source_domain": self.source_domain,
            "actor_id": self.actor_id,
            "target_id": self.target_id,
            "sha256_hash": self.sha256_hash,
            "attributes": self.attributes,
            "source_file": self.source_file,
            "source_row_index": self.source_row_index,
            "source_id": self.source_id,
        }


@dataclass(frozen=True)
class ResolvedFeature:
    feature_name: str
    feature_store: str
    feature_value: Any
    entity_id: str
    window: Optional[str] = None
    evidence_refs: Tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "feature_name": self.feature_name,
            "feature_store": self.feature_store,
            "feature_value": self.feature_value,
            "entity_id": self.entity_id,
            "window": self.window,
            "evidence_refs": list(self.evidence_refs),
        }


@dataclass(frozen=True)
class EvidenceChain:
    finding_id: str
    entity_id: str
    anomaly_type: str
    composite_score: float
    evidence_status: str
    event_count: int
    evidence_events: Tuple[CanonicalEvidenceEvent, ...]
    resolved_features: Tuple[ResolvedFeature, ...]
    provenance_steps: Tuple[ProvenanceStep, ...]
    prov_o_document: Dict[str, Any]
    upstream_manifest: Dict[str, str]
    issues: Tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "finding_id": self.finding_id,
            "entity_id": self.entity_id,
            "anomaly_type": self.anomaly_type,
            "composite_score": self.composite_score,
            "evidence_status": self.evidence_status,
            "event_count": self.event_count,
            "evidence_events": [e.to_dict() for e in self.evidence_events],
            "resolved_features": [f.to_dict() for f in self.resolved_features],
            "provenance_steps": [s.to_dict() for s in self.provenance_steps],
            "prov_o_document": self.prov_o_document,
            "upstream_manifest": self.upstream_manifest,
            "issues": list(self.issues),
        }

    def to_canonical_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, indent=2)


@dataclass(frozen=True)
class WorkspaceState:
    selected_entity_id: Optional[str] = None
    selected_finding_id: Optional[str] = None
    timeline_start: Optional[str] = None
    timeline_end: Optional[str] = None
    selected_event_ids: Tuple[str, ...] = field(default_factory=tuple)
    selected_relationship_ids: Tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "selected_entity_id": self.selected_entity_id,
            "selected_finding_id": self.selected_finding_id,
            "timeline_start": self.timeline_start,
            "timeline_end": self.timeline_end,
            "selected_event_ids": list(self.selected_event_ids),
            "selected_relationship_ids": list(self.selected_relationship_ids),
        }

    def to_canonical_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, indent=2)


@dataclass(frozen=True)
class CytoscapeNodeData:
    id: str
    label: str
    node_type: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CytoscapeEdgeData:
    id: str
    source: str
    target: str
    relationship_type: str
    relationship_status: str
    evidence_event_ids: Tuple[str, ...]
    timestamp: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CytoscapeGraph:
    nodes: Tuple[Dict[str, Any], ...]
    edges: Tuple[Dict[str, Any], ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "nodes": list(self.nodes),
            "edges": list(self.edges),
        }

    def to_canonical_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, indent=2)
