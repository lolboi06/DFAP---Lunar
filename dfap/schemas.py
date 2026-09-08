# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research

import json
from typing import Any, Dict, Optional, List
from pydantic import BaseModel, Field


# Frozen Vocabularies
ALLOWED_SOURCE_DOMAINS = {"CDR", "IPDR", "BANK", "SOCIAL"}
ALLOWED_EVENT_TYPES = {
    "CALL", "IP_SESSION", "TRANSACTION", "LOGIN", "SOCIAL", "DEVICE_EVENT", "LOCATION_EVENT"
}
ALLOWED_MATCH_STATUSES = {"CONFIRMED", "POSSIBLE", "REJECTED"}
ALLOWED_MATCH_METHODS = {"EXACT", "PROBABILISTIC", "HEURISTIC"}
SCHEMA_VERSION = "WP1.1"


class TemporalSemantics:
    OBSERVED_TIMESTAMP = "OBSERVED_TIMESTAMP"
    SEQUENCE_ORDER_SURROGATE = "SEQUENCE_ORDER_SURROGATE"
    UNKNOWN_TIMESTAMP = "UNKNOWN_TIMESTAMP"


CANONICAL_COLUMNS = [
    "event_id", "timestamp", "actor_id", "target_id", "event_type", "source_domain", "attributes", "sha256_hash"
]
PROVENANCE_LEDGER_COLUMNS = [
    "sha256_hash", "source_id", "source_file", "source_row_index", "ingestion_timestamp", "schema_version"
]
RESOLVED_ENTITIES_COLUMNS = [
    "canonical_entity_id", "raw_identifier", "identifier_type", "match_confidence", "match_method", "match_status", "evidence"
]


class CanonicalEvent(BaseModel):
    """
    Frozen Canonical Event Contract.
    canonical_events.parquet: event_id, timestamp, actor_id, target_id, event_type, source_domain, attributes, sha256_hash
    """
    event_id: str = Field(..., description="Unique deterministic event identifier")
    timestamp: str = Field(..., description="ISO-8601 UTC normalized timestamp")
    actor_id: str = Field(..., description="Primary actor identifier")
    target_id: Optional[str] = Field(None, description="Primary target identifier (or None)")
    event_type: str = Field(..., description="Event type from frozen vocabulary")
    source_domain: str = Field(..., description="Source domain from frozen vocabulary")
    attributes: str = Field(..., description="Serialized JSON payload of attributes")
    sha256_hash: str = Field(..., description="SHA-256 evidence hash in provenance ledger")

    def get_attributes_dict(self) -> Dict[str, Any]:
        try:
            return json.loads(self.attributes)
        except Exception:
            return {}


class ProvenanceRecord(BaseModel):
    """
    Frozen Provenance Ledger Contract.
    provenance_ledger.parquet: sha256_hash, source_id, source_file, source_row_index, ingestion_timestamp, schema_version
    """
    sha256_hash: str = Field(..., description="Deterministic SHA-256 evidence hash of canonical source row")
    source_id: str = Field(..., description="Identifier for source system/domain")
    source_file: str = Field(..., description="Raw source filename")
    source_row_index: int = Field(..., description="0-based raw row index in source file")
    ingestion_timestamp: str = Field(..., description="UTC timestamp when record was ingested")
    schema_version: str = Field("WP1.1", description="Schema version identifier")


class ResolvedEntity(BaseModel):
    """
    Frozen Resolved Entity Contract.
    resolved_entities.parquet: canonical_entity_id, raw_identifier, identifier_type, match_confidence, match_method, match_status, evidence
    """
    canonical_entity_id: str = Field(..., description="Unique entity cluster identifier")
    raw_identifier: str = Field(..., description="Primary raw identifier associated with entity")
    identifier_type: str = Field(..., description="Type of identifier (PHONE, IP, ACCOUNT, HANDLE, USER_ID)")
    match_confidence: float = Field(..., description="Pairwise or cluster match confidence probability")
    match_method: str = Field(..., description="Linkage method used (EXACT, PROBABILISTIC)")
    match_status: str = Field(..., description="Identity decision status (CONFIRMED, POSSIBLE, REJECTED)")
    evidence: str = Field(..., description="JSON string summarizing linkage evidence")


class EntityMatch(BaseModel):
    """
    WP1 Audit Artifact Contract.
    entity_matches.parquet: match_id, left_record_id, right_record_id, match_probability, match_weight, blocking_rule, comparison_summary, match_method, match_status, decision_reason, model_version
    """
    match_id: str = Field(..., description="Unique match record identifier")
    left_record_id: str = Field(..., description="First event/record identifier")
    right_record_id: str = Field(..., description="Second event/record identifier")
    match_probability: float = Field(..., description="Probabilistic match probability [0.0 - 1.0]")
    match_weight: float = Field(..., description="Fellegi-Sunter log-likelihood match weight")
    blocking_rule: str = Field(..., description="Blocking rule that generated the candidate pair")
    comparison_summary: str = Field(..., description="JSON summary of feature comparisons")
    match_method: str = Field(..., description="Match method (EXACT, PROBABILISTIC)")
    match_status: str = Field(..., description="Decision status (CONFIRMED, POSSIBLE, REJECTED)")
    decision_reason: str = Field(..., description="Textual explanation of match decision")
    model_version: str = Field("Splink_4.0_FS", description="Model version used")


class IngestionRequest(BaseModel):
    raw_data_dir: str = Field("./data/raw", description="Directory path containing raw source CSVs")
    output_dir: str = Field("./output", description="Directory path for contract Parquet files")
    confirmed_threshold: float = Field(0.85, description="Probability threshold for CONFIRMED match")
    possible_threshold: float = Field(0.60, description="Probability threshold for POSSIBLE match")


class IngestionResponse(BaseModel):
    status: str
    events_processed: int
    entities_resolved: int
    provenance_records: int
    matches_audited: int
    canonical_events_path: str
    resolved_entities_path: str
    provenance_ledger_path: str
    entity_matches_path: str
    manifest_path: str
    execution_timestamp: str
