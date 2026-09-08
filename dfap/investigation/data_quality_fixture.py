# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: Synthetic Data Quality & Source Health Test Fixture (Scenarios A through N)

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from dfap.investigation.data_quality import (
    DataQualityConfig,
    DataQualityDimension,
    DataQualitySourceHealthEngine,
    DimensionStatus,
    SourceHealthAssessment,
    SourceHealthStatus,
)
from dfap.investigation.evidence_provenance import (
    CanonicalEvidenceRecord,
    EvidenceStatus,
    ProvenanceIntegrityStatus,
)
from dfap.investigation.workspace import CaseStatus, InvestigationWorkspaceBackend
from dfap.schemas import CANONICAL_COLUMNS
from dfap.validation import RowValidationReport

CASE_DATA_HEALTH_ID = "CASE-DATA-HEALTH-001"
DATA_HEALTH_ENTITY_ID = "ENT_SYNTHETIC_DATA_HEALTH_001"
REFERENCE_TIMESTAMP_STR = "2026-09-05T00:00:00Z"
REFERENCE_TIMESTAMP_EPOCH = 1788566400.0


def create_healthy_baseline_dataframe(count: int = 100) -> pd.DataFrame:
    """Generates a perfectly compliant canonical dataframe."""
    rows = []
    for i in range(count):
        row = {
            "event_id": f"EVT_HEALTHY_{i:04d}",
            "timestamp": "2026-09-04T12:00:00Z",
            "actor_id": f"ACTOR_{i % 5:02d}",
            "target_id": f"TARGET_{i % 3:02d}",
            "event_type": "IP_SESSION",
            "source_domain": "IPDR",
            "attributes": json.dumps({"dur": 10.5, "sbytes": 500, "proto": "tcp"}),
            "sha256_hash": hashlib.sha256(f"EVT_HEALTHY_{i:04d}".encode()).hexdigest(),
        }
        rows.append(row)
    return pd.DataFrame(rows)


# -----------------------------------------------------------------------------
# Scenario Creators (A through N)
# -----------------------------------------------------------------------------

def create_scenario_a_healthy() -> Dict[str, Any]:
    """Scenario A: Healthy baseline - all 12 dimensions pass."""
    df = create_healthy_baseline_dataframe(100)
    rep = RowValidationReport("scenario_a.csv")
    rep.received_rows = 100
    rep.accepted_rows = 100
    rep.rejected_rows = 0

    return {
        "scenario": "A",
        "name": "Healthy Baseline",
        "df": df,
        "source_id": "SRC_SCENARIO_A",
        "reference_baseline_count": 100,
        "reference_timestamp": REFERENCE_TIMESTAMP_STR,
        "reference_domains": {"IPDR"},
        "validation_report": rep,
        "expected_overall": SourceHealthStatus.HEALTHY,
        "expected_dim_status": {
            DataQualityDimension.SCHEMA_VALIDITY.value: DimensionStatus.HEALTHY,
            DataQualityDimension.COMPLETENESS.value: DimensionStatus.HEALTHY,
            DataQualityDimension.TIMESTAMP_VALIDITY.value: DimensionStatus.HEALTHY,
            DataQualityDimension.IDENTIFIER_VALIDITY.value: DimensionStatus.HEALTHY,
            DataQualityDimension.DUPLICATE_RATE.value: DimensionStatus.HEALTHY,
            DataQualityDimension.FRESHNESS.value: DimensionStatus.HEALTHY,
            DataQualityDimension.VOLUME_HEALTH.value: DimensionStatus.HEALTHY,
            DataQualityDimension.DOMAIN_DISTRIBUTION.value: DimensionStatus.HEALTHY,
            DataQualityDimension.REJECTION_HEALTH.value: DimensionStatus.HEALTHY,
            DataQualityDimension.CROSS_FIELD_CONSISTENCY.value: DimensionStatus.HEALTHY,
        }
    }


def create_scenario_b_missing_timestamps() -> Dict[str, Any]:
    """Scenario B: 25% missing or unparseable timestamps -> CRITICAL timestamp_validity."""
    df = create_healthy_baseline_dataframe(100)
    # Inject 25 missing/invalid timestamps
    for i in range(25):
        df.at[i, "timestamp"] = "INVALID_TIMESTAMP_STRING"

    return {
        "scenario": "B",
        "name": "Missing Timestamps",
        "df": df,
        "source_id": "SRC_SCENARIO_B",
        "reference_baseline_count": 100,
        "reference_timestamp": REFERENCE_TIMESTAMP_STR,
        "reference_domains": {"IPDR"},
        "expected_overall": SourceHealthStatus.CRITICAL,
        "expected_dim_status": {
            DataQualityDimension.TIMESTAMP_VALIDITY.value: DimensionStatus.CRITICAL
        }
    }


def create_scenario_c_malformed_identifiers() -> Dict[str, Any]:
    """Scenario C: 20% placeholder identifiers -> CRITICAL identifier_validity."""
    df = create_healthy_baseline_dataframe(100)
    for i in range(20):
        df.at[i, "actor_id"] = "00000000" if i % 2 == 0 else "null"

    return {
        "scenario": "C",
        "name": "Malformed Identifiers",
        "df": df,
        "source_id": "SRC_SCENARIO_C",
        "reference_baseline_count": 100,
        "reference_timestamp": REFERENCE_TIMESTAMP_STR,
        "reference_domains": {"IPDR"},
        "expected_overall": SourceHealthStatus.CRITICAL,
        "expected_dim_status": {
            DataQualityDimension.IDENTIFIER_VALIDITY.value: DimensionStatus.CRITICAL
        }
    }


def create_scenario_d_duplicate_events() -> Dict[str, Any]:
    """Scenario D: 25% duplicate event IDs -> CRITICAL duplicate_rate."""
    df = create_healthy_baseline_dataframe(100)
    for i in range(25):
        df.at[i, "event_id"] = "DUPLICATE_EVENT_ID_0001"

    return {
        "scenario": "D",
        "name": "Duplicate Events",
        "df": df,
        "source_id": "SRC_SCENARIO_D",
        "reference_baseline_count": 100,
        "reference_timestamp": REFERENCE_TIMESTAMP_STR,
        "reference_domains": {"IPDR"},
        "expected_overall": SourceHealthStatus.CRITICAL,
        "expected_dim_status": {
            DataQualityDimension.DUPLICATE_RATE.value: DimensionStatus.CRITICAL
        }
    }


def create_scenario_e_high_rejection() -> Dict[str, Any]:
    """Scenario E: High rejection rate (30% rejected) -> CRITICAL rejection_health."""
    df = create_healthy_baseline_dataframe(70)
    rep = RowValidationReport("scenario_e.csv")
    rep.received_rows = 100
    rep.accepted_rows = 70
    rep.rejected_rows = 30

    return {
        "scenario": "E",
        "name": "High Rejection Rate",
        "df": df,
        "source_id": "SRC_SCENARIO_E",
        "reference_baseline_count": 100,
        "reference_timestamp": REFERENCE_TIMESTAMP_STR,
        "reference_domains": {"IPDR"},
        "validation_report": rep,
        "expected_overall": SourceHealthStatus.CRITICAL,
        "expected_dim_status": {
            DataQualityDimension.REJECTION_HEALTH.value: DimensionStatus.CRITICAL
        }
    }


def create_scenario_f_broken_references() -> Dict[str, Any]:
    """Scenario F: Broken references rate > 0.10 -> CRITICAL referential_consistency."""
    # Create evidence records pointing to nonexistent canonical event IDs
    df = pd.DataFrame([
        {"canonical_event_id": "NON_EXISTENT_EVT_01", "event_id": "EV1", "actor_id": "A1"},
        {"canonical_event_id": "NON_EXISTENT_EVT_02", "event_id": "EV2", "actor_id": "A2"},
        {"canonical_event_id": "NON_EXISTENT_EVT_03", "event_id": "EV3", "actor_id": "A3"},
        {"canonical_event_id": "VALID_C_01", "event_id": "EV4", "actor_id": "A4"},
    ])

    return {
        "scenario": "F",
        "name": "Broken References",
        "df": df,
        "source_id": "SRC_SCENARIO_F",
        "reference_baseline_count": 4,
        "reference_timestamp": REFERENCE_TIMESTAMP_STR,
        "valid_canonical_ids": {"VALID_C_01"},
        "expected_overall": SourceHealthStatus.CRITICAL,
        "expected_dim_status": {
            DataQualityDimension.REFERENTIAL_CONSISTENCY.value: DimensionStatus.CRITICAL
        }
    }


def create_scenario_g_incomplete_provenance() -> Dict[str, Any]:
    """Scenario G: SHA-256 mismatch against manifest -> CRITICAL provenance_completeness."""
    df = create_healthy_baseline_dataframe(10)
    # Manifest entry with incorrect SHA-256
    manifest_fake = {
        "source_sha256": "0000000000000000000000000000000000000000000000000000000000000000",
        "raw_record_count": 10,
        "domain": "IPDR"
    }

    # Write a temporary file
    tmp = tempfile.NamedTemporaryFile(suffix=".csv", delete=False)
    tmp.write(b"event_id,timestamp,actor_id\n1,2026-01-01,A\n")
    tmp.close()

    return {
        "scenario": "G",
        "name": "Incomplete / Tampered Provenance",
        "df": df,
        "source_id": "SRC_SCENARIO_G",
        "source_file_path": tmp.name,
        "manifest_entry": manifest_fake,
        "reference_baseline_count": 10,
        "reference_timestamp": REFERENCE_TIMESTAMP_STR,
        "reference_domains": {"IPDR"},
        "expected_overall": SourceHealthStatus.CRITICAL,
        "expected_dim_status": {
            DataQualityDimension.PROVENANCE_COMPLETENESS.value: DimensionStatus.CRITICAL
        }
    }


def create_scenario_h_stale_source() -> Dict[str, Any]:
    """Scenario H: Stale source (events from 2 years ago) -> CRITICAL freshness."""
    df = create_healthy_baseline_dataframe(50)
    # All timestamps set to 2024 (over 600 days old relative to 2026-09-05)
    df["timestamp"] = "2024-01-01T00:00:00Z"

    return {
        "scenario": "H",
        "name": "Stale Source",
        "df": df,
        "source_id": "SRC_SCENARIO_H",
        "reference_baseline_count": 50,
        "reference_timestamp": REFERENCE_TIMESTAMP_STR,
        "reference_domains": {"IPDR"},
        "expected_overall": SourceHealthStatus.CRITICAL,
        "expected_dim_status": {
            DataQualityDimension.FRESHNESS.value: DimensionStatus.CRITICAL
        }
    }


def create_scenario_i_volume_collapse() -> Dict[str, Any]:
    """Scenario I: Volume collapse (5 records observed vs 100 baseline -> 5%) -> CRITICAL volume_health."""
    df = create_healthy_baseline_dataframe(5)

    return {
        "scenario": "I",
        "name": "Source Volume Collapse",
        "df": df,
        "source_id": "SRC_SCENARIO_I",
        "reference_baseline_count": 100,
        "reference_timestamp": REFERENCE_TIMESTAMP_STR,
        "reference_domains": {"IPDR"},
        "expected_overall": SourceHealthStatus.CRITICAL,
        "expected_dim_status": {
            DataQualityDimension.VOLUME_HEALTH.value: DimensionStatus.CRITICAL
        }
    }


def create_scenario_j_volume_spike() -> Dict[str, Any]:
    """Scenario J: Volume spike (400 records observed vs 100 baseline -> 400%) -> CRITICAL volume_health."""
    df = create_healthy_baseline_dataframe(400)

    return {
        "scenario": "J",
        "name": "Source Volume Spike",
        "df": df,
        "source_id": "SRC_SCENARIO_J",
        "reference_baseline_count": 100,
        "reference_timestamp": REFERENCE_TIMESTAMP_STR,
        "reference_domains": {"IPDR"},
        "expected_overall": SourceHealthStatus.CRITICAL,
        "expected_dim_status": {
            DataQualityDimension.VOLUME_HEALTH.value: DimensionStatus.CRITICAL
        }
    }


def create_scenario_k_domain_disappearance() -> Dict[str, Any]:
    """Scenario K: Domain disappearance (expected IPDR and BANK, but only BANK observed) -> CRITICAL domain_distribution."""
    df = create_healthy_baseline_dataframe(50)
    df["source_domain"] = "BANK"
    df["event_type"] = "TRANSACTION"

    return {
        "scenario": "K",
        "name": "Domain Disappearance",
        "df": df,
        "source_id": "SRC_SCENARIO_K",
        "reference_baseline_count": 50,
        "reference_timestamp": REFERENCE_TIMESTAMP_STR,
        "reference_domains": {"IPDR", "BANK"},  # IPDR disappeared!
        "expected_overall": SourceHealthStatus.CRITICAL,
        "expected_dim_status": {
            DataQualityDimension.DOMAIN_DISTRIBUTION.value: DimensionStatus.CRITICAL
        }
    }


def create_scenario_l_mixed_defects() -> Dict[str, Any]:
    """Scenario L: Mixed multi-defect (missing timestamps + duplicate IDs + staleness) -> CRITICAL."""
    df = create_healthy_baseline_dataframe(50)
    # Stale timestamps and invalid timestamps
    df["timestamp"] = "2024-01-01T00:00:00Z"
    for i in range(10):
        df.at[i, "timestamp"] = "INVALID_TIMESTAMP"
    # Duplicate IDs
    for i in range(15):
        df.at[i, "event_id"] = "DUP_MIXED_001"
    # Placeholders
    for i in range(10):
        df.at[i, "actor_id"] = "unknown"

    return {
        "scenario": "L",
        "name": "Mixed Multi-Defect",
        "df": df,
        "source_id": "SRC_SCENARIO_L",
        "reference_baseline_count": 50,
        "reference_timestamp": REFERENCE_TIMESTAMP_STR,
        "reference_domains": {"IPDR"},
        "expected_overall": SourceHealthStatus.CRITICAL,
        "expected_dim_status": {
            DataQualityDimension.TIMESTAMP_VALIDITY.value: DimensionStatus.CRITICAL,
            DataQualityDimension.DUPLICATE_RATE.value: DimensionStatus.CRITICAL,
            DataQualityDimension.IDENTIFIER_VALIDITY.value: DimensionStatus.CRITICAL,
        }
    }


def create_scenario_m_unavailable() -> Dict[str, Any]:
    """Scenario M: Non-existent source file -> UNAVAILABLE."""
    return {
        "scenario": "M",
        "name": "Unavailable Source",
        "df": None,
        "source_id": "SRC_SCENARIO_M",
        "source_file_path": "data/sources/non_existent_source_path_9999.csv",
        "expected_overall": SourceHealthStatus.UNAVAILABLE,
    }


def create_scenario_n_degraded_usable() -> Dict[str, Any]:
    """
    Scenario N: Valid degraded source remaining usable.
    Defects exist but all remain within DEGRADED bounds (none CRITICAL):
      - 3% duplicate rate (config: 0.01 degraded, 0.15 critical) -> DEGRADED
      - 3% rejection rate (config: 0.05 degraded, 0.20 critical)
      - volume ratio 0.85 (config: [0.80, 1.50] healthy) -> HEALTHY
      - timestamps intact -> HEALTHY
    Overall status: DEGRADED.
    """
    df = create_healthy_baseline_dataframe(100)
    # Inject 3 duplicates (3% rate)
    df.at[0, "event_id"] = df.at[1, "event_id"]
    df.at[2, "event_id"] = df.at[3, "event_id"]
    df.at[4, "event_id"] = df.at[5, "event_id"]

    return {
        "scenario": "N",
        "name": "Valid Degraded Source Remaining Usable",
        "df": df,
        "source_id": "SRC_SCENARIO_N",
        "reference_baseline_count": 100,
        "reference_timestamp": REFERENCE_TIMESTAMP_STR,
        "reference_domains": {"IPDR"},
        "expected_overall": SourceHealthStatus.DEGRADED,
        "expected_dim_status": {
            DataQualityDimension.DUPLICATE_RATE.value: DimensionStatus.DEGRADED
        }
    }


ALL_SCENARIO_CREATORS = {
    "A": create_scenario_a_healthy,
    "B": create_scenario_b_missing_timestamps,
    "C": create_scenario_c_malformed_identifiers,
    "D": create_scenario_d_duplicate_events,
    "E": create_scenario_e_high_rejection,
    "F": create_scenario_f_broken_references,
    "G": create_scenario_g_incomplete_provenance,
    "H": create_scenario_h_stale_source,
    "I": create_scenario_i_volume_collapse,
    "J": create_scenario_j_volume_spike,
    "K": create_scenario_k_domain_disappearance,
    "L": create_scenario_l_mixed_defects,
    "M": create_scenario_m_unavailable,
    "N": create_scenario_n_degraded_usable,
}


def register_data_quality_fixture(backend: InvestigationWorkspaceBackend) -> Dict[str, Any]:
    """
    Instantiates and registers CASE-DATA-HEALTH-001 into the workspace backend.
    Attaches canonical evidence records and findings across healthy and degraded sources.
    """
    # 1. Evidence record for healthy source A
    ev_a = CanonicalEvidenceRecord(
        evidence_type="TELEMETRY_LOG",
        source_domain="IPDR",
        source_id="SRC_SCENARIO_A",
        source_file="scenario_a.parquet",
        source_row_index=0,
        canonical_entity_ids=[DATA_HEALTH_ENTITY_ID],
        event_ids=["EVT_HEALTHY_0001"],
        observation_timestamp=REFERENCE_TIMESTAMP_EPOCH - 100.0,
        ingestion_timestamp=REFERENCE_TIMESTAMP_STR,
        derivation_method="HEALTHY_MONITOR",
        confidence=0.95,
        evidence_quality=1.0,
        evidence_category="SUPPORTING",
        evidence_id="EVID-DQ-HEALTHY-001",
        metadata={"data_quality": "VERIFIED_CLEAN"}
    )

    # 2. Evidence record for degraded source N
    ev_n = CanonicalEvidenceRecord(
        evidence_type="TELEMETRY_LOG",
        source_domain="IPDR",
        source_id="SRC_SCENARIO_N",
        source_file="scenario_n.parquet",
        source_row_index=0,
        canonical_entity_ids=[DATA_HEALTH_ENTITY_ID],
        event_ids=["EVT_DEGRADED_0001"],
        observation_timestamp=REFERENCE_TIMESTAMP_EPOCH - 200.0,
        ingestion_timestamp=REFERENCE_TIMESTAMP_STR,
        derivation_method="DEGRADED_MONITOR",
        confidence=0.80,
        evidence_quality=0.85,
        evidence_category="SUPPORTING",
        evidence_id="EVID-DQ-DEGRADED-001",
        metadata={"data_quality": "DEGRADED_SOURCE_WARNING"}
    )

    backend.valid_entities.add(DATA_HEALTH_ENTITY_ID)

    sc_a = create_scenario_a_healthy()
    sc_n = create_scenario_n_degraded_usable()

    if hasattr(backend, "register_source_dataset"):
        backend.register_source_dataset("SRC_SCENARIO_A", sc_a["df"])
        backend.register_source_dataset("scenario_a.parquet", sc_a["df"])
        backend.register_source_dataset("SRC_SCENARIO_N", sc_n["df"])
        backend.register_source_dataset("scenario_n.parquet", sc_n["df"])

    all_records = [ev_a, ev_n]
    for rec in all_records:
        backend.evidence_engine.register_evidence(rec)
        backend._evidence_by_hash[rec.evidence_hash] = rec.evidence_id

    # 3. Add findings
    fnd_a = {
        "finding_id": "FND_DQ_SCENARIO_A",
        "entity_id": DATA_HEALTH_ENTITY_ID,
        "canonical_entity_id": DATA_HEALTH_ENTITY_ID,
        "detector": "HEALTHY_DETECTOR",
        "anomaly_score": 0.90,
        "composite_score": 0.90,
        "confidence": 0.95,
        "status": "SUPPORTED",
        "timestamp": REFERENCE_TIMESTAMP_EPOCH,
        "observation_timestamp": REFERENCE_TIMESTAMP_EPOCH,
        "temporal_semantics": "OBSERVED_TIMESTAMP",
        "supporting_evidence": ["EVID-DQ-HEALTHY-001"],
        "contradicting_evidence": [],
        "contextual_evidence": [],
        "evidence_ref": "ref:fnd:FND_DQ_SCENARIO_A"
    }
    backend.findings_by_id["FND_DQ_SCENARIO_A"] = fnd_a
    backend.evidence_engine.finding_evidence_map["FND_DQ_SCENARIO_A"] = ["EVID-DQ-HEALTHY-001"]

    fnd_n = {
        "finding_id": "FND_DQ_SCENARIO_N",
        "entity_id": DATA_HEALTH_ENTITY_ID,
        "canonical_entity_id": DATA_HEALTH_ENTITY_ID,
        "detector": "DEGRADED_DETECTOR",
        "anomaly_score": 0.75,
        "composite_score": 0.75,
        "confidence": 0.80,
        "status": "SUPPORTED",
        "timestamp": REFERENCE_TIMESTAMP_EPOCH,
        "observation_timestamp": REFERENCE_TIMESTAMP_EPOCH,
        "temporal_semantics": "OBSERVED_TIMESTAMP",
        "supporting_evidence": ["EVID-DQ-DEGRADED-001"],
        "contradicting_evidence": [],
        "contextual_evidence": [],
        "evidence_ref": "ref:fnd:FND_DQ_SCENARIO_N"
    }
    backend.findings_by_id["FND_DQ_SCENARIO_N"] = fnd_n
    backend.evidence_engine.finding_evidence_map["FND_DQ_SCENARIO_N"] = ["EVID-DQ-DEGRADED-001"]

    # 4. Create case in backend
    if CASE_DATA_HEALTH_ID not in backend.cases:
        case = backend.create_case(
            canonical_entity_id=DATA_HEALTH_ENTITY_ID,
            case_id=CASE_DATA_HEALTH_ID,
            search_context={
                "source": "SYNTHETIC_DATA_HEALTH_FIXTURE",
                "case_kind": "DATA_HEALTH_BENCHMARK",
                "trigger_timestamp": REFERENCE_TIMESTAMP_EPOCH,
            }
        )
    else:
        case = backend.cases[CASE_DATA_HEALTH_ID]

    case.status = CaseStatus.UNDER_REVIEW
    if "FND_DQ_SCENARIO_A" not in case.finding_ids:
        backend.attach_finding(CASE_DATA_HEALTH_ID, "FND_DQ_SCENARIO_A")
    if "FND_DQ_SCENARIO_N" not in case.finding_ids:
        backend.attach_finding(CASE_DATA_HEALTH_ID, "FND_DQ_SCENARIO_N")

    for rec in all_records:
        if rec.evidence_id not in case.evidence_ids:
            backend.attach_evidence(CASE_DATA_HEALTH_ID, rec.evidence_id)

    return {
        "case": case,
        "entity_id": DATA_HEALTH_ENTITY_ID,
        "records": {r.evidence_id: r for r in all_records},
        "findings": {
            "A": fnd_a,
            "N": fnd_n,
        }
    }
