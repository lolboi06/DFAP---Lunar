# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: Evidence Quality & Reliability Engine Verification Suite (Scenarios A through N)

import copy
import pytest
import numpy as np
import pandas as pd
from typing import Dict, Any, List

from dfap.investigation.workspace import InvestigationWorkspaceBackend, CaseStatus
from dfap.investigation.evidence_provenance import (
    CanonicalEvidenceRecord,
    EvidenceStatus,
    ProvenanceIntegrityStatus,
)
from dfap.investigation.reliability import (
    ReliabilityConfig,
    ReliabilityStatus,
    EvidenceSufficiency,
    ConflictSeverity,
    EvidenceQualityReliabilityEngine,
)
from dfap.investigation.reliability_fixture import (
    CASE_RELIABILITY_ID,
    RELIABILITY_ENTITY_ID,
    TRIGGER_TIMESTAMP_EPOCH,
    register_reliability_fixture,
    create_scenario_a_records,
    create_scenario_b_records,
    create_scenario_e_contradiction_records,
)
from dfap.investigation.copilot import InvestigationCopilot
from dfap.wp4.cli import handle_m13_command


@pytest.fixture
def workspace_with_reliability():
    """Sets up an InvestigationWorkspaceBackend pre-loaded with the Test 8 conflict fixture and reliability fixture."""
    backend = InvestigationWorkspaceBackend(
        output_dir="output",
        canonical_dir="data/canonical",
        cases_dir="data/cases"
    )
    fixture_data = register_reliability_fixture(backend)
    return backend, fixture_data


# ══════════════════════════════════════════════════════════════════════════════
# 1. CONFIGURATION VALIDATION TESTS
# ══════════════════════════════════════════════════════════════════════════════

def test_config_valid_default():
    """Verify default ReliabilityConfig is valid and immutable."""
    cfg = ReliabilityConfig()
    assert cfg.algorithm_version == "v1.0.0_PRODUCTION_RESEARCH"
    assert cfg.configuration_version == "cfg_v1.0"
    assert abs(sum(cfg.weights.values()) - 1.0) < 1e-5


def test_config_rejects_invalid_weights_sum():
    """Explicitly reject configurations where component weights do not sum to 1.0."""
    with pytest.raises(ValueError, match="sum exactly to 1.0"):
        ReliabilityConfig(weights={
            "identity": 0.30,
            "temporal": 0.20,
            "evidence_quality": 0.20,
            "corroboration": 0.20,
            "data_quality": 0.10,
            "provenance": 0.20,  # Sum = 1.20
        })


def test_config_rejects_negative_weight():
    """Explicitly reject negative weights."""
    with pytest.raises(ValueError, match="non-negative"):
        ReliabilityConfig(weights={
            "identity": -0.10,
            "temporal": 0.25,
            "evidence_quality": 0.25,
            "corroboration": 0.25,
            "data_quality": 0.15,
            "provenance": 0.20,
        })


def test_config_rejects_empty_versions():
    """Explicitly reject empty algorithm or configuration version strings."""
    with pytest.raises(ValueError, match="algorithm_version"):
        ReliabilityConfig(algorithm_version="")
    with pytest.raises(ValueError, match="configuration_version"):
        ReliabilityConfig(configuration_version="   ")


# ══════════════════════════════════════════════════════════════════════════════
# 2. SCENARIOS A THROUGH N
# ══════════════════════════════════════════════════════════════════════════════

def test_scenario_a_independent_support(workspace_with_reliability):
    """Scenario A: 3 independent supporting events across 3 domains -> corroboration 1.0, HIGH reliability."""
    backend, _ = workspace_with_reliability
    engine = EvidenceQualityReliabilityEngine(backend)

    res = engine.assess_finding(CASE_RELIABILITY_ID, "FND_REL_SCENARIO_A")
    assert res.overall_status == ReliabilityStatus.HIGH
    assert res.evidence_sufficiency == EvidenceSufficiency.SUFFICIENT_EVIDENCE
    assert res.conflict_severity == ConflictSeverity.NO_CONFLICT
    assert res.components["corroboration_strength"] == 1.0
    assert res.overall_score >= 0.80
    assert len(res.duplicate_evidence) == 0


def test_scenario_b_duplicate_evidence(workspace_with_reliability):
    """Scenario B: 3 duplicate copies of the same event -> corroboration 0.33, lower score than A."""
    backend, _ = workspace_with_reliability
    engine = EvidenceQualityReliabilityEngine(backend)

    res_a = engine.assess_finding(CASE_RELIABILITY_ID, "FND_REL_SCENARIO_A")
    res_b = engine.assess_finding(CASE_RELIABILITY_ID, "FND_REL_SCENARIO_B")

    assert res_b.components["corroboration_strength"] == pytest.approx(0.3333, abs=1e-3)
    assert res_b.overall_score < res_a.overall_score
    assert len(res_b.duplicate_evidence) == 2, "Two of three duplicate copies must be detected and clustered"
    assert res_b.evidence_sufficiency != EvidenceSufficiency.SUFFICIENT_EVIDENCE
    assert res_b.evidence_sufficiency == EvidenceSufficiency.WEAK_EVIDENCE
    assert res_b.overall_status != ReliabilityStatus.HIGH
    assert res_b.overall_status == ReliabilityStatus.MEDIUM


def test_scenario_c_strong_support_no_contradiction(workspace_with_reliability):
    """Scenario C: Strong support without contradictory evidence -> NO_CONFLICT, zero penalty."""
    backend, _ = workspace_with_reliability
    engine = EvidenceQualityReliabilityEngine(backend)

    res = engine.assess_finding(CASE_RELIABILITY_ID, "FND_REL_SCENARIO_A")
    assert res.conflict_severity == ConflictSeverity.NO_CONFLICT
    assert res.contradiction_strength == 0.0
    assert res.contradiction_penalty == 0.0
    assert res.support_strength > 0.80


def test_scenario_d_strong_support_weak_contradiction(workspace_with_reliability):
    """Scenario D: Strong support + weak contradiction -> WEAK_CONFLICT, minimal penalty applied."""
    backend, _ = workspace_with_reliability
    engine = EvidenceQualityReliabilityEngine(backend)

    # Register a weak contradicting evidence record
    weak_contra_rec = CanonicalEvidenceRecord(
        evidence_type="BEHAVIORAL_BASELINE",
        source_domain="SOCIAL",
        source_id="SO_REL_WEAK_CONTRA",
        source_file="weak_contra.parquet",
        source_row_index=0,
        canonical_entity_ids=[RELIABILITY_ENTITY_ID],
        event_ids=["EVT_REL_WEAK_CONTRA"],
        observation_timestamp=TRIGGER_TIMESTAMP_EPOCH - 10.0,
        ingestion_timestamp="2026-09-05T00:00:00Z",
        derivation_method="BASELINE_MONITOR",
        confidence=0.90,
        evidence_quality=0.20,  # Weak quality / borderline
        evidence_category="CONTRADICTING",
        evidence_id="EVID-REL-WEAK-CONTRA",
        metadata={"anomaly_score": 0.22}
    )
    backend.evidence_engine.register_evidence(weak_contra_rec)
    backend._entity_alias_to_canonical["SO_REL_WEAK_CONTRA"] = RELIABILITY_ENTITY_ID

    # Create finding with A support + weak contradiction
    fnd_d = {
        "finding_id": "FND_REL_SCENARIO_D",
        "entity_id": RELIABILITY_ENTITY_ID,
        "canonical_entity_id": RELIABILITY_ENTITY_ID,
        "detector": "M11_FUSION",
        "anomaly_score": 0.88,
        "confidence": 0.85,
        "status": "SUPPORTED",
        "timestamp": TRIGGER_TIMESTAMP_EPOCH,
        "observation_timestamp": TRIGGER_TIMESTAMP_EPOCH,
        "supporting_evidence": ["EVID-REL-SUPP-A1", "EVID-REL-SUPP-A2"],
        "contradicting_evidence": ["EVID-REL-WEAK-CONTRA"],
    }
    backend.findings_by_id["FND_REL_SCENARIO_D"] = fnd_d
    backend.evidence_engine.finding_evidence_map["FND_REL_SCENARIO_D"] = ["EVID-REL-SUPP-A1", "EVID-REL-SUPP-A2", "EVID-REL-WEAK-CONTRA"]
    backend.attach_finding(CASE_RELIABILITY_ID, "FND_REL_SCENARIO_D")
    backend.attach_evidence(CASE_RELIABILITY_ID, "EVID-REL-WEAK-CONTRA")

    res = engine.assess_finding(CASE_RELIABILITY_ID, "FND_REL_SCENARIO_D")
    assert res.conflict_severity == ConflictSeverity.WEAK_CONFLICT
    assert res.contradiction_strength <= 0.25
    assert res.contradiction_penalty > 0.0
    assert res.contradiction_penalty <= 0.05


def test_scenario_e_strong_support_strong_contradiction(workspace_with_reliability):
    """Scenario E: Strong support + strong contradiction -> CONFLICTED, contradiction preserved, penalty applied."""
    backend, _ = workspace_with_reliability
    engine = EvidenceQualityReliabilityEngine(backend)

    res = engine.assess_finding(CASE_RELIABILITY_ID, "FND_REL_SCENARIO_E")
    assert res.overall_status == ReliabilityStatus.CONFLICTED
    assert res.conflict_severity in (ConflictSeverity.MODERATE_CONFLICT, ConflictSeverity.STRONG_CONFLICT)
    assert res.support_strength >= 0.40
    assert res.contradiction_strength >= 0.80
    assert res.contradiction_penalty >= 0.20
    assert "EVID-REL-CONTRA-SUPP" in res.supporting_evidence
    assert "EVID-REL-CONTRA-OPP" in res.contradicting_evidence


def test_scenario_f_contradiction_only(workspace_with_reliability):
    """Scenario F: Contradiction only -> cannot produce positive HIGH reliability; overall_status is LOW."""
    backend, _ = workspace_with_reliability
    engine = EvidenceQualityReliabilityEngine(backend)

    fnd_f = {
        "finding_id": "FND_REL_SCENARIO_F",
        "entity_id": RELIABILITY_ENTITY_ID,
        "canonical_entity_id": RELIABILITY_ENTITY_ID,
        "detector": "M11_FUSION",
        "anomaly_score": 0.08,
        "confidence": 0.30,
        "status": "NOT_SUPPORTED",
        "timestamp": TRIGGER_TIMESTAMP_EPOCH,
        "observation_timestamp": TRIGGER_TIMESTAMP_EPOCH,
        "supporting_evidence": [],
        "contradicting_evidence": ["EVID-REL-CONTRA-OPP"],
    }
    backend.findings_by_id["FND_REL_SCENARIO_F"] = fnd_f
    backend.evidence_engine.finding_evidence_map["FND_REL_SCENARIO_F"] = ["EVID-REL-CONTRA-OPP"]
    backend.attach_finding(CASE_RELIABILITY_ID, "FND_REL_SCENARIO_F")

    res = engine.assess_finding(CASE_RELIABILITY_ID, "FND_REL_SCENARIO_F")
    assert res.overall_status != ReliabilityStatus.HIGH
    assert res.support_strength == 0.0
    assert res.contradiction_strength > 0.50
    assert res.overall_status == ReliabilityStatus.LOW


def test_scenario_g_missing_provenance(workspace_with_reliability):
    """Scenario G: Evidence lacks DAG root ancestor -> provenance completeness penalized, sufficiency degraded."""
    backend, _ = workspace_with_reliability
    engine = EvidenceQualityReliabilityEngine(backend)

    # Disconnected evidence record (not added to graph)
    rec_g = CanonicalEvidenceRecord(
        evidence_type="ANOMALY_DETECTION",
        source_domain="FINANCIAL",
        source_id="WALLET_REL_SUPP_A1",
        source_file="unlinked.parquet",
        source_row_index=0,
        canonical_entity_ids=[RELIABILITY_ENTITY_ID],
        event_ids=["EVT_G"],
        observation_timestamp=TRIGGER_TIMESTAMP_EPOCH - 10.0,
        ingestion_timestamp="2026-09-05T00:00:00Z",
        derivation_method="DISCONNECTED",
        confidence=0.95,
        evidence_quality=1.0,
        evidence_category="SUPPORTING",
        evidence_id="EVID-REL-UNLINKED-G",
    )
    backend.evidence_engine.register_evidence(rec_g)

    fnd_g = {
        "finding_id": "FND_REL_SCENARIO_G",
        "entity_id": RELIABILITY_ENTITY_ID,
        "canonical_entity_id": RELIABILITY_ENTITY_ID,
        "detector": "M11_FUSION",
        "anomaly_score": 0.85,
        "confidence": 0.85,
        "status": "SUPPORTED",
        "timestamp": TRIGGER_TIMESTAMP_EPOCH,
        "observation_timestamp": TRIGGER_TIMESTAMP_EPOCH,
        "supporting_evidence": ["EVID-REL-UNLINKED-G"],
    }
    backend.findings_by_id["FND_REL_SCENARIO_G"] = fnd_g
    backend.evidence_engine.finding_evidence_map["FND_REL_SCENARIO_G"] = ["EVID-REL-UNLINKED-G"]
    backend.attach_finding(CASE_RELIABILITY_ID, "FND_REL_SCENARIO_G")
    backend.attach_evidence(CASE_RELIABILITY_ID, "EVID-REL-UNLINKED-G")

    res = engine.assess_finding(CASE_RELIABILITY_ID, "FND_REL_SCENARIO_G")
    assert res.overall_status != ReliabilityStatus.HIGH
    # Single item with unlinked lineage cannot achieve sufficient evidence status
    assert res.evidence_sufficiency in (EvidenceSufficiency.WEAK_EVIDENCE, EvidenceSufficiency.NO_VALID_EVIDENCE)
    assert res.components["identity_confidence"] == 0.95, "Strong identity must remain strong"
    assert not any("identity" in r.lower() for r in res.reasons), "No identity-ambiguity reason may appear"
    assert any("provenance" in r.lower() for r in res.reasons), "Provenance issue must be explicitly identified"
    item_g = res.evidence_breakdown[0]
    assert item_g.cryptographic_integrity == "INTEGRITY_VERIFIED"
    assert item_g.lineage_status == "UNLINKED_LINEAGE"
    assert item_g.provenance_status == "RECORD_INTEGRITY_ONLY_UNLINKED_LINEAGE"


def test_scenario_h_weak_identity(workspace_with_reliability):
    """Scenario H: Ambiguous identity binding (confidence 0.45 < 0.70) -> degraded sufficiency / reliability."""
    backend, _ = workspace_with_reliability
    engine = EvidenceQualityReliabilityEngine(backend)

    rec_h = CanonicalEvidenceRecord(
        evidence_type="ANOMALY_DETECTION",
        source_domain="FINANCIAL",
        source_id="RAW_WEAK_ID_999",
        source_file="weak_id.parquet",
        source_row_index=0,
        canonical_entity_ids=[RELIABILITY_ENTITY_ID],
        event_ids=["EVT_H"],
        observation_timestamp=TRIGGER_TIMESTAMP_EPOCH - 10.0,
        ingestion_timestamp="2026-09-05T00:00:00Z",
        derivation_method="WEAK_DETECTOR",
        confidence=0.45,
        evidence_quality=1.0,
        evidence_category="SUPPORTING",
        evidence_id="EVID-REL-WEAK-ID",
    )
    backend.evidence_engine.register_evidence(rec_h)
    backend._entity_alias_to_canonical["RAW_WEAK_ID_999"] = RELIABILITY_ENTITY_ID

    fnd_h = {
        "finding_id": "FND_REL_SCENARIO_H",
        "entity_id": RELIABILITY_ENTITY_ID,
        "canonical_entity_id": RELIABILITY_ENTITY_ID,
        "detector": "M11_FUSION",
        "anomaly_score": 0.85,
        "confidence": 0.45,
        "status": "SUPPORTED",
        "timestamp": TRIGGER_TIMESTAMP_EPOCH,
        "observation_timestamp": TRIGGER_TIMESTAMP_EPOCH,
        "supporting_evidence": ["EVID-REL-WEAK-ID"],
    }
    backend.findings_by_id["FND_REL_SCENARIO_H"] = fnd_h
    backend.evidence_engine.finding_evidence_map["FND_REL_SCENARIO_H"] = ["EVID-REL-WEAK-ID"]
    backend.attach_finding(CASE_RELIABILITY_ID, "FND_REL_SCENARIO_H")
    backend.attach_evidence(CASE_RELIABILITY_ID, "EVID-REL-WEAK-ID")

    res = engine.assess_finding(CASE_RELIABILITY_ID, "FND_REL_SCENARIO_H")
    assert res.components["identity_confidence"] < 0.70
    assert res.evidence_sufficiency == EvidenceSufficiency.WEAK_EVIDENCE
    assert res.overall_status == ReliabilityStatus.LOW


def test_scenario_i_spoofed_identity(workspace_with_reliability):
    """Scenario I: Spoofed caller-asserted ID not in bridge -> fail closed, INSUFFICIENT_EVIDENCE."""
    backend, _ = workspace_with_reliability
    engine = EvidenceQualityReliabilityEngine(backend)

    rec_i = CanonicalEvidenceRecord(
        evidence_type="ANOMALY_DETECTION",
        source_domain="FINANCIAL",
        source_id="SPOOFED_WALLET_NOT_IN_BRIDGE",
        source_file="spoofed.parquet",
        source_row_index=0,
        canonical_entity_ids=[RELIABILITY_ENTITY_ID],  # Unverified assertion!
        event_ids=["EVT_SPOOF"],
        observation_timestamp=TRIGGER_TIMESTAMP_EPOCH - 10.0,
        ingestion_timestamp="2026-09-05T00:00:00Z",
        derivation_method="SPOOF_DETECTOR",
        confidence=0.99,
        evidence_quality=1.0,
        evidence_category="SUPPORTING",
        evidence_id="EVID-REL-SPOOF",
    )
    backend.evidence_engine.register_evidence(rec_i)
    # Note: SPOOFED_WALLET_NOT_IN_BRIDGE is explicitly NOT added to bridge or backend._entity_alias_to_canonical

    fnd_i = {
        "finding_id": "FND_REL_SCENARIO_I",
        "entity_id": RELIABILITY_ENTITY_ID,
        "canonical_entity_id": RELIABILITY_ENTITY_ID,
        "detector": "M11_FUSION",
        "anomaly_score": 0.99,
        "confidence": 0.99,
        "status": "SUPPORTED",
        "timestamp": TRIGGER_TIMESTAMP_EPOCH,
        "observation_timestamp": TRIGGER_TIMESTAMP_EPOCH,
        "supporting_evidence": ["EVID-REL-SPOOF"],
    }
    backend.findings_by_id["FND_REL_SCENARIO_I"] = fnd_i
    backend.evidence_engine.finding_evidence_map["FND_REL_SCENARIO_I"] = ["EVID-REL-SPOOF"]
    backend.attach_finding(CASE_RELIABILITY_ID, "FND_REL_SCENARIO_I")
    backend.attach_evidence(CASE_RELIABILITY_ID, "EVID-REL-SPOOF")

    res = engine.assess_finding(CASE_RELIABILITY_ID, "FND_REL_SCENARIO_I")
    assert res.components["identity_confidence"] == 0.0
    assert res.evidence_sufficiency == EvidenceSufficiency.NO_VALID_EVIDENCE
    assert res.overall_status == ReliabilityStatus.INSUFFICIENT_EVIDENCE
    assert res.overall_score == 0.0


def test_scenario_j_future_evidence(workspace_with_reliability):
    """Scenario J: Future evidence (t > trigger) -> excluded from causal historical reliability."""
    backend, _ = workspace_with_reliability
    engine = EvidenceQualityReliabilityEngine(backend)

    res = engine.assess_finding(CASE_RELIABILITY_ID, "FND_REL_SCENARIO_J")
    # Finding J only has EVID-REL-FUTURE-001 which occurs 1 hour after trigger time
    item_assessment = res.evidence_breakdown[0]
    assert item_assessment.is_future_event is True
    assert item_assessment.temporal_contribution == 0.0
    assert item_assessment.reliability_contribution == 0.0
    assert res.overall_status == ReliabilityStatus.INSUFFICIENT_EVIDENCE
    assert res.overall_score == 0.0


def test_scenario_k_empty_evidence(workspace_with_reliability):
    """Scenario K: Empty evidence -> NO_VALID_EVIDENCE, score 0.0, INSUFFICIENT_EVIDENCE."""
    backend, _ = workspace_with_reliability
    engine = EvidenceQualityReliabilityEngine(backend)

    fnd_k = {
        "finding_id": "FND_REL_SCENARIO_K",
        "entity_id": RELIABILITY_ENTITY_ID,
        "canonical_entity_id": RELIABILITY_ENTITY_ID,
        "detector": "EMPTY_DETECTOR",
        "anomaly_score": 0.50,
        "status": "INSUFFICIENT_EVIDENCE",
        "supporting_evidence": [],
    }
    backend.findings_by_id["FND_REL_SCENARIO_K"] = fnd_k
    backend.evidence_engine.finding_evidence_map["FND_REL_SCENARIO_K"] = []
    backend.attach_finding(CASE_RELIABILITY_ID, "FND_REL_SCENARIO_K")

    res = engine.assess_finding(CASE_RELIABILITY_ID, "FND_REL_SCENARIO_K")
    assert res.overall_score == 0.0
    assert res.overall_status == ReliabilityStatus.INSUFFICIENT_EVIDENCE
    assert res.evidence_sufficiency == EvidenceSufficiency.NO_VALID_EVIDENCE


def test_scenario_l_multiple_derivation_paths(workspace_with_reliability):
    """Scenario L: Multiple derivation paths from same source file and row -> clustered as 1 independent item."""
    backend, _ = workspace_with_reliability
    engine = EvidenceQualityReliabilityEngine(backend)

    # 2 records sharing source_file and source_row_index
    r_l1 = CanonicalEvidenceRecord(
        evidence_type="ANOMALY_DETECTION",
        source_domain="FINANCIAL",
        source_id="WALLET_REL_SUPP_A1",
        source_file="shared_source.parquet",
        source_row_index=42,
        canonical_entity_ids=[RELIABILITY_ENTITY_ID],
        event_ids=["EVT_DERIV_1"],
        observation_timestamp=TRIGGER_TIMESTAMP_EPOCH - 10.0,
        ingestion_timestamp="2026-09-05T00:00:00Z",
        derivation_method="PATH_A",
        confidence=0.95,
        evidence_id="EVID-L1",
    )
    r_l2 = CanonicalEvidenceRecord(
        evidence_type="ANOMALY_DETECTION",
        source_domain="FINANCIAL",
        source_id="WALLET_REL_SUPP_A1",
        source_file="shared_source.parquet",
        source_row_index=42,  # Exactly the same row!
        canonical_entity_ids=[RELIABILITY_ENTITY_ID],
        event_ids=["EVT_DERIV_2"],
        observation_timestamp=TRIGGER_TIMESTAMP_EPOCH - 10.0,
        ingestion_timestamp="2026-09-05T00:00:00Z",
        derivation_method="PATH_B",
        confidence=0.95,
        evidence_id="EVID-L2",
    )
    backend.evidence_engine.register_evidence(r_l1)
    backend.evidence_engine.register_evidence(r_l2)

    fnd_l = {
        "finding_id": "FND_REL_SCENARIO_L",
        "entity_id": RELIABILITY_ENTITY_ID,
        "canonical_entity_id": RELIABILITY_ENTITY_ID,
        "detector": "M11_FUSION",
        "anomaly_score": 0.90,
        "status": "SUPPORTED",
        "timestamp": TRIGGER_TIMESTAMP_EPOCH,
        "observation_timestamp": TRIGGER_TIMESTAMP_EPOCH,
        "supporting_evidence": ["EVID-L1", "EVID-L2"],
    }
    backend.findings_by_id["FND_REL_SCENARIO_L"] = fnd_l
    backend.evidence_engine.finding_evidence_map["FND_REL_SCENARIO_L"] = ["EVID-L1", "EVID-L2"]
    backend.attach_finding(CASE_RELIABILITY_ID, "FND_REL_SCENARIO_L")
    backend.attach_evidence(CASE_RELIABILITY_ID, "EVID-L1")
    backend.attach_evidence(CASE_RELIABILITY_ID, "EVID-L2")

    res = engine.assess_finding(CASE_RELIABILITY_ID, "FND_REL_SCENARIO_L")
    assert "EVID-L2" in res.duplicate_evidence
    assert res.components["corroboration_strength"] == pytest.approx(0.3333, abs=1e-3)


def test_scenario_m_foreign_case_isolation(workspace_with_reliability):
    """Scenario M: Foreign case evidence is strictly isolated and cannot contribute."""
    backend, _ = workspace_with_reliability
    engine = EvidenceQualityReliabilityEngine(backend)

    # Create Case B
    case_b = backend.create_case(canonical_entity_id="ENT_1F405CAB3F4951DA", case_id="CASE-FOREIGN-001")

    # Attempting to assess Finding A under Case B must be rejected
    with pytest.raises(ValueError, match="Case isolation violation"):
        engine.assess_finding("CASE-FOREIGN-001", "FND_REL_SCENARIO_A")


def test_scenario_n_parameter_sensitivity(workspace_with_reliability):
    """
    Scenario N: Engineering sensitivity analysis on heuristic scoring weights.
    Tests baseline vs ±10% weight perturbations and ±20% multiplier perturbations.
    Verifies rank ordering stability and categorical stability.
    """
    backend, _ = workspace_with_reliability
    engine = EvidenceQualityReliabilityEngine(backend)

    findings_to_rank = ["FND_REL_SCENARIO_A", "FND_REL_SCENARIO_B", "FND_REL_SCENARIO_E"]

    # 1. Baseline assessment
    base_scores = []
    base_statuses = []
    for fid in findings_to_rank:
        a = engine.assess_finding(CASE_RELIABILITY_ID, fid)
        base_scores.append(a.overall_score)
        base_statuses.append(a.overall_status)

    assert base_scores[0] > base_scores[1] > base_scores[2], "Baseline ranking: A (high) > B (dup) > E (conflict)"

    # 2. Perturbed Config 1: +10% identity, -10% corroboration
    w_p1 = {
        "identity": 0.275,
        "temporal": 0.150,
        "evidence_quality": 0.150,
        "corroboration": 0.175,
        "data_quality": 0.100,
        "provenance": 0.150,
    }
    cfg_p1 = ReliabilityConfig(weights=w_p1)
    p1_scores = [engine.assess_finding(CASE_RELIABILITY_ID, fid, config=cfg_p1).overall_score for fid in findings_to_rank]
    p1_statuses = [engine.assess_finding(CASE_RELIABILITY_ID, fid, config=cfg_p1).overall_status for fid in findings_to_rank]

    assert p1_scores[0] > p1_scores[1] > p1_scores[2], "Rank order must remain invariant under ±10% perturbation"
    assert p1_statuses == base_statuses, "Categorical statuses must remain 100% stable under ±10% perturbation"

    # 3. Perturbed Config 2: +20% contradiction penalty multiplier
    cfg_p2 = ReliabilityConfig(conflict_penalty_multiplier={
        "NO_CONFLICT": 0.0,
        "WEAK_CONFLICT": 0.12,
        "MODERATE_CONFLICT": 0.30,
        "STRONG_CONFLICT": 0.42,
    })
    p2_scores = [engine.assess_finding(CASE_RELIABILITY_ID, fid, config=cfg_p2).overall_score for fid in findings_to_rank]
    p2_statuses = [engine.assess_finding(CASE_RELIABILITY_ID, fid, config=cfg_p2).overall_status for fid in findings_to_rank]

    assert p2_scores[0] > p2_scores[1] > p2_scores[2]
    assert p2_statuses[2] == ReliabilityStatus.CONFLICTED


def test_two_independent_supporting_events_qualify_for_sufficient_evidence(workspace_with_reliability):
    """Two independent events qualify for SUFFICIENT_EVIDENCE; caps at MEDIUM when target is 3."""
    backend, _ = workspace_with_reliability
    engine = EvidenceQualityReliabilityEngine(backend)

    fnd_2 = {
        "finding_id": "FND_REL_TWO_INDEP",
        "entity_id": RELIABILITY_ENTITY_ID,
        "canonical_entity_id": RELIABILITY_ENTITY_ID,
        "detector": "M11_FUSION",
        "anomaly_score": 0.88,
        "confidence": 0.90,
        "status": "SUPPORTED",
        "timestamp": TRIGGER_TIMESTAMP_EPOCH,
        "observation_timestamp": TRIGGER_TIMESTAMP_EPOCH,
        "supporting_evidence": ["EVID-REL-SUPP-A1", "EVID-REL-SUPP-A2"],
        "contradicting_evidence": [],
    }
    backend.findings_by_id["FND_REL_TWO_INDEP"] = fnd_2
    backend.evidence_engine.finding_evidence_map["FND_REL_TWO_INDEP"] = ["EVID-REL-SUPP-A1", "EVID-REL-SUPP-A2"]
    backend.attach_finding(CASE_RELIABILITY_ID, "FND_REL_TWO_INDEP")

    res = engine.assess_finding(CASE_RELIABILITY_ID, "FND_REL_TWO_INDEP")
    assert res.evidence_sufficiency == EvidenceSufficiency.SUFFICIENT_EVIDENCE
    assert res.components["corroboration_strength"] == pytest.approx(2.0 / 3.0, abs=1e-3)
    assert res.overall_status == ReliabilityStatus.MEDIUM


def test_three_independent_supporting_events_qualify_for_high(workspace_with_reliability):
    """Three independent events satisfy target_independent_events=3 and qualify for HIGH."""
    backend, _ = workspace_with_reliability
    engine = EvidenceQualityReliabilityEngine(backend)

    res = engine.assess_finding(CASE_RELIABILITY_ID, "FND_REL_SCENARIO_A")
    assert res.evidence_sufficiency == EvidenceSufficiency.SUFFICIENT_EVIDENCE
    assert res.components["corroboration_strength"] == 1.0
    assert res.overall_score >= 0.80
    assert res.overall_status == ReliabilityStatus.HIGH


# ══════════════════════════════════════════════════════════════════════════════
# 3. DETERMINISM & CLI INTEGRATION TESTS
# ══════════════════════════════════════════════════════════════════════════════

def test_engine_determinism(workspace_with_reliability):
    """Running assessment multiple times yields identical score, status, and components."""
    backend, _ = workspace_with_reliability
    engine = EvidenceQualityReliabilityEngine(backend)

    res1 = engine.assess_finding(CASE_RELIABILITY_ID, "FND_REL_SCENARIO_A").to_dict()
    res2 = engine.assess_finding(CASE_RELIABILITY_ID, "FND_REL_SCENARIO_A").to_dict()

    # Exclude evaluated_at timestamp
    del res1["evaluated_at"]
    del res2["evaluated_at"]

    assert res1 == res2, "Multiple evaluations must produce bit-for-bit identical results"


def test_m14_copilot_reliability_query(workspace_with_reliability):
    """M14 copilot grounded Q&A routing for reliability queries."""
    backend, _ = workspace_with_reliability
    copilot = InvestigationCopilot(backend)

    q_res = copilot.ask("How reliable is finding FND_REL_SCENARIO_A?", case_id=CASE_RELIABILITY_ID)
    assert q_res["status"] == "GROUNDED"
    assert "reliability" in q_res
    rel = q_res["reliability"]
    assert rel["overall_status"] == "HIGH"
    assert rel["overall_score"] >= 0.80
    assert "deterministic reliability score" in q_res["answer"]


def test_cli_copilot_reliability_command(workspace_with_reliability):
    """Console command 'copilot reliability FND_REL_SCENARIO_A' produces structured JSON."""
    backend, _ = workspace_with_reliability

    out = handle_m13_command(backend, f"copilot reliability FND_REL_SCENARIO_A {CASE_RELIABILITY_ID}")
    assert "overall_score" in out
    assert "overall_status" in out
    assert "HIGH" in out
    assert "components" in out
