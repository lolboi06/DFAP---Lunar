# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: Synthetic Reliability Test Fixture (Scenarios A through N)

import hashlib
import pandas as pd
from typing import Dict, Any, List, Optional

from dfap.investigation.workspace import InvestigationWorkspaceBackend, CaseStatus
from dfap.investigation.evidence_provenance import (
    CanonicalEvidenceRecord,
    EvidenceStatus,
    ProvenanceIntegrityStatus,
)
from dfap.investigation.reliability import (
    EvidenceQualityReliabilityEngine,
    ReliabilityConfig,
    ReliabilityAssessment,
)


CASE_RELIABILITY_ID = "CASE-RELIABILITY-001"
RELIABILITY_ENTITY_ID = "ENT_SYNTHETIC_RELIABILITY_001"
TRIGGER_TIMESTAMP_EPOCH = 1700050000.0


def create_scenario_a_records() -> List[CanonicalEvidenceRecord]:
    """Scenario A: 3 independent supporting events across 3 distinct domains."""
    r1 = CanonicalEvidenceRecord(
        evidence_type="ANOMALY_DETECTION",
        source_domain="FINANCIAL",
        source_id="WALLET_REL_SUPP_A1",
        source_file="reliability_fin_a1.parquet",
        source_row_index=0,
        canonical_entity_ids=[RELIABILITY_ENTITY_ID],
        event_ids=["EVT_REL_SUPP_A1"],
        observation_timestamp=TRIGGER_TIMESTAMP_EPOCH - 20.0,
        ingestion_timestamp="2026-09-05T00:00:00Z",
        derivation_method="FINANCIAL_ANOMALY_DETECTOR",
        confidence=0.95,
        evidence_quality=1.0,
        evidence_category="SUPPORTING",
        evidence_id="EVID-REL-SUPP-A1",
        metadata={"anomaly_score": 0.88, "signal": "High velocity transfer"}
    )
    r2 = CanonicalEvidenceRecord(
        evidence_type="BEHAVIORAL_BASELINE",
        source_domain="SOCIAL",
        source_id="SO_REL_SUPP_A2",
        source_file="reliability_soc_a2.parquet",
        source_row_index=0,
        canonical_entity_ids=[RELIABILITY_ENTITY_ID],
        event_ids=["EVT_REL_SUPP_A2"],
        observation_timestamp=TRIGGER_TIMESTAMP_EPOCH - 10.0,
        ingestion_timestamp="2026-09-05T00:00:00Z",
        derivation_method="SOCIAL_ANOMALY_DETECTOR",
        confidence=0.90,
        evidence_quality=1.0,
        evidence_category="SUPPORTING",
        evidence_id="EVID-REL-SUPP-A2",
        metadata={"anomaly_score": 0.85, "signal": "Sudden social profile takeover"}
    )
    r3 = CanonicalEvidenceRecord(
        evidence_type="TELEMETRY_LOG",
        source_domain="IPDR",
        source_id="IP_REL_SUPP_A3",
        source_file="reliability_ipdr_a3.parquet",
        source_row_index=0,
        canonical_entity_ids=[RELIABILITY_ENTITY_ID],
        event_ids=["EVT_REL_SUPP_A3"],
        observation_timestamp=TRIGGER_TIMESTAMP_EPOCH - 5.0,
        ingestion_timestamp="2026-09-05T00:00:00Z",
        derivation_method="IPDR_ANOMALY_MONITOR",
        confidence=0.92,
        evidence_quality=1.0,
        evidence_category="SUPPORTING",
        evidence_id="EVID-REL-SUPP-A3",
        metadata={"anomaly_score": 0.82, "signal": "Suspicious VPN proxy connection"}
    )
    return [r1, r2, r3]


def create_scenario_b_records() -> List[CanonicalEvidenceRecord]:
    """Scenario B: 3 duplicate copies of the same underlying event."""
    base_t = TRIGGER_TIMESTAMP_EPOCH - 20.0
    r1 = CanonicalEvidenceRecord(
        evidence_type="ANOMALY_DETECTION",
        source_domain="FINANCIAL",
        source_id="WALLET_REL_DUP_B",
        source_file="reliability_dup_b.parquet",
        source_row_index=10,
        canonical_entity_ids=[RELIABILITY_ENTITY_ID],
        event_ids=["EVT_REL_DUP_SHARED"],
        observation_timestamp=base_t,
        ingestion_timestamp="2026-09-05T00:00:00Z",
        derivation_method="DETECTOR_COPY_1",
        confidence=0.95,
        evidence_quality=1.0,
        evidence_category="SUPPORTING",
        evidence_id="EVID-REL-DUP-B1",
        metadata={"anomaly_score": 0.90}
    )
    r2 = CanonicalEvidenceRecord(
        evidence_type="ANOMALY_DETECTION",
        source_domain="FINANCIAL",
        source_id="WALLET_REL_DUP_B",
        source_file="reliability_dup_b.parquet",
        source_row_index=10,
        canonical_entity_ids=[RELIABILITY_ENTITY_ID],
        event_ids=["EVT_REL_DUP_SHARED"],
        observation_timestamp=base_t,
        ingestion_timestamp="2026-09-05T00:00:00Z",
        derivation_method="DETECTOR_COPY_2",
        confidence=0.95,
        evidence_quality=1.0,
        evidence_category="SUPPORTING",
        evidence_id="EVID-REL-DUP-B2",
        metadata={"anomaly_score": 0.90}
    )
    r3 = CanonicalEvidenceRecord(
        evidence_type="ANOMALY_DETECTION",
        source_domain="FINANCIAL",
        source_id="WALLET_REL_DUP_B",
        source_file="reliability_dup_b.parquet",
        source_row_index=10,
        canonical_entity_ids=[RELIABILITY_ENTITY_ID],
        event_ids=["EVT_REL_DUP_SHARED"],
        observation_timestamp=base_t,
        ingestion_timestamp="2026-09-05T00:00:00Z",
        derivation_method="DETECTOR_COPY_3",
        confidence=0.95,
        evidence_quality=1.0,
        evidence_category="SUPPORTING",
        evidence_id="EVID-REL-DUP-B3",
        metadata={"anomaly_score": 0.90}
    )
    return [r1, r2, r3]


def create_scenario_e_contradiction_records() -> List[CanonicalEvidenceRecord]:
    """Scenario E: Strong support (Financial 0.92) + Strong contradiction (Social 0.08)."""
    r_supp = CanonicalEvidenceRecord(
        evidence_type="ANOMALY_DETECTION",
        source_domain="FINANCIAL",
        source_id="WALLET_REL_CONTRA_FIN",
        source_file="reliability_contra_fin.parquet",
        source_row_index=0,
        canonical_entity_ids=[RELIABILITY_ENTITY_ID],
        event_ids=["EVT_REL_CONTRA_FIN"],
        observation_timestamp=TRIGGER_TIMESTAMP_EPOCH - 15.0,
        ingestion_timestamp="2026-09-05T00:00:00Z",
        derivation_method="FINANCIAL_ANOMALY_DETECTOR",
        confidence=0.95,
        evidence_quality=1.0,
        evidence_category="SUPPORTING",
        evidence_id="EVID-REL-CONTRA-SUPP",
        metadata={"anomaly_score": 0.92, "signal": "High velocity structuring"}
    )
    r_contra = CanonicalEvidenceRecord(
        evidence_type="BEHAVIORAL_BASELINE",
        source_domain="SOCIAL",
        source_id="SO_REL_CONTRA_SOC",
        source_file="reliability_contra_soc.parquet",
        source_row_index=0,
        canonical_entity_ids=[RELIABILITY_ENTITY_ID],
        event_ids=["EVT_REL_CONTRA_SOC"],
        observation_timestamp=TRIGGER_TIMESTAMP_EPOCH - 10.0,
        ingestion_timestamp="2026-09-05T00:00:00Z",
        derivation_method="SOCIAL_BASELINE_PROFILER",
        confidence=0.92,
        evidence_quality=1.0,
        evidence_category="CONTRADICTING",
        evidence_id="EVID-REL-CONTRA-OPP",
        metadata={"anomaly_score": 0.08, "signal": "Verified authentic social baseline engagement"}
    )
    return [r_supp, r_contra]


def register_reliability_fixture(backend: InvestigationWorkspaceBackend) -> Dict[str, Any]:
    """
    Registers CASE-RELIABILITY-001 and its associated entities, evidence, findings,
    and DAG lineage into the backend.
    """
    # 1. Register canonical entity and raw aliases in backend
    backend.valid_entities.add(RELIABILITY_ENTITY_ID)
    backend._entity_alias_to_canonical[RELIABILITY_ENTITY_ID] = RELIABILITY_ENTITY_ID
    backend._entity_alias_to_canonical["WALLET_REL_SUPP_A1"] = RELIABILITY_ENTITY_ID
    backend._entity_alias_to_canonical["SO_REL_SUPP_A2"] = RELIABILITY_ENTITY_ID
    backend._entity_alias_to_canonical["IP_REL_SUPP_A3"] = RELIABILITY_ENTITY_ID
    backend._entity_alias_to_canonical["WALLET_REL_DUP_B"] = RELIABILITY_ENTITY_ID
    backend._entity_alias_to_canonical["WALLET_REL_CONTRA_FIN"] = RELIABILITY_ENTITY_ID
    backend._entity_alias_to_canonical["SO_REL_CONTRA_SOC"] = RELIABILITY_ENTITY_ID
    backend._entity_alias_to_canonical["WALLET_REL_FUTURE"] = RELIABILITY_ENTITY_ID

    # 2. Register Evidence Records
    records_a = create_scenario_a_records()
    records_b = create_scenario_b_records()
    records_e = create_scenario_e_contradiction_records()

    all_records = records_a + records_b + records_e

    # Future record (Scenario J)
    r_future = CanonicalEvidenceRecord(
        evidence_type="ANOMALY_DETECTION",
        source_domain="FINANCIAL",
        source_id="WALLET_REL_FUTURE",
        source_file="reliability_future.parquet",
        source_row_index=0,
        canonical_entity_ids=[RELIABILITY_ENTITY_ID],
        event_ids=["EVT_REL_FUTURE"],
        observation_timestamp=TRIGGER_TIMESTAMP_EPOCH + 3600.0,  # Post-trigger (+1h)
        ingestion_timestamp="2026-09-05T00:00:00Z",
        derivation_method="FUTURE_MONITOR",
        confidence=0.95,
        evidence_quality=1.0,
        evidence_category="SUPPORTING",
        evidence_id="EVID-REL-FUTURE-001",
        metadata={"anomaly_score": 0.95}
    )
    all_records.append(r_future)

    for rec in all_records:
        backend.evidence_engine.register_evidence(rec)
        backend._evidence_by_hash[rec.evidence_hash] = rec.evidence_id

    # 3. Create Root Nodes and DAG Edges in ProvenanceGraph
    graph = backend.evidence_engine.graph
    root_node_id = f"ROOT_{RELIABILITY_ENTITY_ID}"
    graph.add_node(root_node_id, node_type="RESOLVED_ENTITY", domain="IDENTITY", metadata={"entity_id": RELIABILITY_ENTITY_ID})

    for rec in all_records:
        graph.add_node(rec.evidence_id, node_type="EVIDENCE", domain=rec.source_domain, metadata={"evidence_id": rec.evidence_id})
        graph.add_edge(root_node_id, rec.evidence_id, relation="DERIVED_FROM", method="INGESTION")

    # 4. Findings Setup
    # Finding A: High quality support
    finding_a = {
        "finding_id": "FND_REL_SCENARIO_A",
        "entity_id": RELIABILITY_ENTITY_ID,
        "canonical_entity_id": RELIABILITY_ENTITY_ID,
        "detector": "M11_CROSS_DOMAIN_FUSION",
        "anomaly_score": 0.88,
        "composite_score": 0.86,
        "confidence": 0.90,
        "status": "SUPPORTED",
        "timestamp": TRIGGER_TIMESTAMP_EPOCH,
        "observation_timestamp": TRIGGER_TIMESTAMP_EPOCH,
        "temporal_semantics": "OBSERVED_TIMESTAMP",
        "supporting_evidence": [r.evidence_id for r in records_a],
        "contradicting_evidence": [],
        "contextual_evidence": [],
        "evidence_ref": "ref:fnd:FND_REL_SCENARIO_A"
    }
    backend.findings_by_id["FND_REL_SCENARIO_A"] = finding_a
    backend.evidence_engine.finding_evidence_map["FND_REL_SCENARIO_A"] = [r.evidence_id for r in records_a]
    graph.add_node("FND_REL_SCENARIO_A", node_type="FINDING", domain="CROSS_DOMAIN", metadata={"finding_id": "FND_REL_SCENARIO_A"})
    for r in records_a:
        graph.add_edge(r.evidence_id, "FND_REL_SCENARIO_A", relation="SUPPORTS", method="FUSION")

    # Finding B: Duplicate evidence
    finding_b = {
        "finding_id": "FND_REL_SCENARIO_B",
        "entity_id": RELIABILITY_ENTITY_ID,
        "canonical_entity_id": RELIABILITY_ENTITY_ID,
        "detector": "FINANCIAL_DETECTOR",
        "anomaly_score": 0.90,
        "composite_score": 0.90,
        "confidence": 0.85,
        "status": "SUPPORTED",
        "timestamp": TRIGGER_TIMESTAMP_EPOCH,
        "observation_timestamp": TRIGGER_TIMESTAMP_EPOCH,
        "temporal_semantics": "OBSERVED_TIMESTAMP",
        "supporting_evidence": [r.evidence_id for r in records_b],
        "contradicting_evidence": [],
        "contextual_evidence": [],
        "evidence_ref": "ref:fnd:FND_REL_SCENARIO_B"
    }
    backend.findings_by_id["FND_REL_SCENARIO_B"] = finding_b
    backend.evidence_engine.finding_evidence_map["FND_REL_SCENARIO_B"] = [r.evidence_id for r in records_b]
    graph.add_node("FND_REL_SCENARIO_B", node_type="FINDING", domain="FINANCIAL", metadata={"finding_id": "FND_REL_SCENARIO_B"})
    for r in records_b:
        graph.add_edge(r.evidence_id, "FND_REL_SCENARIO_B", relation="SUPPORTS", method="DETECTION")

    # Finding E: Strong contradiction
    finding_e = {
        "finding_id": "FND_REL_SCENARIO_E",
        "entity_id": RELIABILITY_ENTITY_ID,
        "canonical_entity_id": RELIABILITY_ENTITY_ID,
        "detector": "M11_CROSS_DOMAIN_FUSION",
        "anomaly_score": 0.92,
        "composite_score": 0.40,
        "confidence": 0.40,
        "status": "CONFLICTED",
        "timestamp": TRIGGER_TIMESTAMP_EPOCH,
        "observation_timestamp": TRIGGER_TIMESTAMP_EPOCH,
        "temporal_semantics": "OBSERVED_TIMESTAMP",
        "supporting_evidence": ["EVID-REL-CONTRA-SUPP"],
        "contradicting_evidence": ["EVID-REL-CONTRA-OPP"],
        "contextual_evidence": [],
        "evidence_ref": "ref:fnd:FND_REL_SCENARIO_E"
    }
    backend.findings_by_id["FND_REL_SCENARIO_E"] = finding_e
    backend.evidence_engine.finding_evidence_map["FND_REL_SCENARIO_E"] = ["EVID-REL-CONTRA-SUPP", "EVID-REL-CONTRA-OPP"]
    graph.add_node("FND_REL_SCENARIO_E", node_type="FINDING", domain="CROSS_DOMAIN", metadata={"finding_id": "FND_REL_SCENARIO_E"})
    graph.add_edge("EVID-REL-CONTRA-SUPP", "FND_REL_SCENARIO_E", relation="SUPPORTS", method="FUSION")
    graph.add_edge("EVID-REL-CONTRA-OPP", "FND_REL_SCENARIO_E", relation="CONTRADICTS", method="FUSION")

    # Finding J: Future evidence
    finding_j = {
        "finding_id": "FND_REL_SCENARIO_J",
        "entity_id": RELIABILITY_ENTITY_ID,
        "canonical_entity_id": RELIABILITY_ENTITY_ID,
        "detector": "TRIGGER_DETECTOR",
        "anomaly_score": 0.85,
        "composite_score": 0.85,
        "confidence": 0.70,
        "status": "SUPPORTED",
        "timestamp": TRIGGER_TIMESTAMP_EPOCH,
        "observation_timestamp": TRIGGER_TIMESTAMP_EPOCH,
        "temporal_semantics": "OBSERVED_TIMESTAMP",
        "supporting_evidence": ["EVID-REL-FUTURE-001"],
        "contradicting_evidence": [],
        "contextual_evidence": [],
        "evidence_ref": "ref:fnd:FND_REL_SCENARIO_J"
    }
    backend.findings_by_id["FND_REL_SCENARIO_J"] = finding_j
    backend.evidence_engine.finding_evidence_map["FND_REL_SCENARIO_J"] = ["EVID-REL-FUTURE-001"]
    graph.add_node("FND_REL_SCENARIO_J", node_type="FINDING", domain="FINANCIAL", metadata={"finding_id": "FND_REL_SCENARIO_J"})
    graph.add_edge("EVID-REL-FUTURE-001", "FND_REL_SCENARIO_J", relation="SUPPORTS", method="DETECTION")

    # 5. Create Case CASE-RELIABILITY-001 in Backend
    if CASE_RELIABILITY_ID not in backend.cases:
        case = backend.create_case(
            canonical_entity_id=RELIABILITY_ENTITY_ID,
            case_id=CASE_RELIABILITY_ID,
            search_context={
                "source": "SYNTHETIC_RELIABILITY_FIXTURE",
                "case_kind": "RELIABILITY_BENCHMARK",
                "trigger_timestamp": TRIGGER_TIMESTAMP_EPOCH,
            }
        )
    else:
        case = backend.cases[CASE_RELIABILITY_ID]

    case.status = CaseStatus.UNDER_REVIEW
    for fid in ["FND_REL_SCENARIO_A", "FND_REL_SCENARIO_B", "FND_REL_SCENARIO_E", "FND_REL_SCENARIO_J"]:
        if fid not in case.finding_ids:
            backend.attach_finding(CASE_RELIABILITY_ID, fid)
    for rec in all_records:
        if rec.evidence_id not in case.evidence_ids:
            backend.attach_evidence(CASE_RELIABILITY_ID, rec.evidence_id)

    return {
        "case": case,
        "entity_id": RELIABILITY_ENTITY_ID,
        "all_records": {r.evidence_id: r for r in all_records},
        "findings": {
            "A": finding_a,
            "B": finding_b,
            "E": finding_e,
            "J": finding_j,
        }
    }
