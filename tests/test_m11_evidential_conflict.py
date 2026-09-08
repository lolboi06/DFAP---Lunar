# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: M11 Evidential Conflict Intelligence Test Suite

import pytest
import math
from dfap.investigation.evidential_conflict import (
    EvidentialConflictAnalyzer,
    EvidentialConflictStatus,
    EvidentialRequiredAction,
    compute_betp,
    compute_hellinger_distance,
    compute_belief_vector_cosine,
    compute_compound_conflict,
    analyze_domain_pair,
    normalize_mass_vector,
    DEFAULT_EVIDENTIAL_CONFLICT_THRESHOLDS
)
from dfap.investigation.cross_domain_fusion import CrossDomainFusionEngine, ConflictStatus
from dfap.investigation.copilot import InvestigationCopilot
from dfap.investigation.conflict_fixture import (
    register_contradiction_fixture,
    CASE_CONFLICT_ID,
    CONFLICT_ENTITY_ID,
    SUPPORT_EVID_ID,
    CONTRA_EVID_ID
)
from dfap.investigation.workspace import InvestigationWorkspaceBackend


def test_agreeing_evidence_no_conflict():
    """Agreeing domain evidence yields d_H = 0, Cosine = 1.0, Conf = 0.0 -> NO_MATERIAL_CONFLICT."""
    # Two agreeing domains with identical high anomaly belief
    mass_a = (0.80, 0.10, 0.10)
    mass_b = (0.80, 0.10, 0.10)

    betp_a = compute_betp(mass_a)
    betp_b = compute_betp(mass_b)
    d_h = compute_hellinger_distance(betp_a, betp_b)
    cos_sim = compute_belief_vector_cosine(mass_a, mass_b)
    conf = compute_compound_conflict(d_h, cos_sim)

    assert d_h == 0.0
    assert cos_sim == 1.0
    assert conf == 0.0

    res = analyze_domain_pair("TELECOM", mass_a, "FINANCIAL", mass_b)
    assert res["conflict_status"] == EvidentialConflictStatus.NO_MATERIAL_CONFLICT
    assert res["required_action"] == EvidentialRequiredAction.PROCEED
    assert res["compound_conflict"] == 0.0
    assert "within acceptable bounds" in res["explanation"]


def test_conflicting_domains_abstention_required():
    """Clearly conflicting domain evidence triggers ABSTENTION_REQUIRED and HUMAN_REVIEW."""
    # Domain A (Financial): anomalous structuring signal
    # Domain B (Social): normal organic activity baseline
    analyzer = EvidentialConflictAnalyzer(thresholds={
        "material_conflict_threshold": 0.25,
        "abstention_conflict_threshold": 0.38
    })

    res = analyzer.analyze_pair("FINANCIAL", 0.92, "SOCIAL", 0.08)

    assert res["domain_a"] == "FINANCIAL"
    assert res["domain_b"] == "SOCIAL"
    assert res["hellinger_distance"] > 0.40
    assert res["belief_vector_cosine"] < 0.30
    assert res["compound_conflict"] >= 0.38
    assert res["conflict_status"] == EvidentialConflictStatus.ABSTENTION_REQUIRED
    assert res["required_action"] == EvidentialRequiredAction.HUMAN_REVIEW

    # Neutral, objective language without criminal / fraud / guilt claims
    forbidden_terms = ["guilt", "fraud", "criminal", "illicit", "culprit", "perpetrator"]
    for term in forbidden_terms:
        assert term not in res["explanation"].lower()


def test_zero_vector_and_degenerate_handling():
    """Zero vectors, missing inputs, and degenerate mass functions produce stable, bounded outputs without NaN."""
    # Pure zero mass
    zero_mass = (0.0, 0.0, 0.0)
    norm = normalize_mass_vector(zero_mass)
    assert norm == (0.0, 0.0, 0.0)

    betp_zero = compute_betp(zero_mass)
    assert betp_zero == {"ANOMALOUS": 0.5, "NORMAL": 0.5}
    assert not math.isnan(betp_zero["ANOMALOUS"])
    assert not math.isinf(betp_zero["ANOMALOUS"])

    # Two zero vectors
    cos_both_zero = compute_belief_vector_cosine(zero_mass, zero_mass)
    assert cos_both_zero == 1.0

    # One zero vector, one non-zero
    cos_one_zero = compute_belief_vector_cosine(zero_mass, (0.7, 0.2, 0.1))
    assert cos_one_zero == 0.0

    # None input (missing domain)
    betp_none = compute_betp(None)
    assert betp_none == {"ANOMALOUS": 0.5, "NORMAL": 0.5}

    # Negative numbers in dict
    betp_neg = compute_betp({"ANOMALOUS": -0.5, "NORMAL": -0.5, "THETA": 0.0})
    assert betp_neg == {"ANOMALOUS": 0.5, "NORMAL": 0.5}

    # Compound conflict bounded in [0.0, 1.0]
    conf = compute_compound_conflict(0.999, -0.999)
    assert 0.0 <= conf <= 1.0


def test_multi_domain_worst_pair_identification():
    """Multi-domain analysis correctly identifies the worst conflicting pair among 3+ domains."""
    analyzer = EvidentialConflictAnalyzer()
    domain_scores = {
        "FINANCIAL": 0.92,
        "SOCIAL": 0.08,
        "IPDR": 0.40
    }
    summary = analyzer.analyze_domains(domain_scores)

    assert summary["overall_status"] == EvidentialConflictStatus.ABSTENTION_REQUIRED
    assert summary["requires_human_review"] is True
    assert summary["abstention_required"] is True
    assert summary["required_action"] == EvidentialRequiredAction.HUMAN_REVIEW
    assert summary["worst_pair"] in [("FINANCIAL", "SOCIAL"), ("SOCIAL", "FINANCIAL")]
    assert len(summary["pairwise_conflicts"]) == 3  # (FIN, SOC), (FIN, IPDR), (IPDR, SOC)


def test_configurable_thresholds():
    """Thresholds can be custom configured and deterministically alter status classification."""
    # 0.92 vs 0.08 produces compound conflict ~0.3927

    # 1. With strict threshold (abstention 0.30), conflict triggers ABSTENTION_REQUIRED
    strict_analyzer = EvidentialConflictAnalyzer(thresholds={
        "material_conflict_threshold": 0.20,
        "abstention_conflict_threshold": 0.30
    })
    strict_res = strict_analyzer.analyze_pair("DOM1", 0.92, "DOM2", 0.08)

    # 2. With moderate threshold (material 0.30, abstention 0.50), conflict triggers MATERIAL_CONFLICT
    moderate_analyzer = EvidentialConflictAnalyzer(thresholds={
        "material_conflict_threshold": 0.30,
        "abstention_conflict_threshold": 0.50
    })
    moderate_res = moderate_analyzer.analyze_pair("DOM1", 0.92, "DOM2", 0.08)

    # 3. With lenient threshold (material 0.50, abstention 0.70), conflict triggers NO_MATERIAL_CONFLICT
    lenient_analyzer = EvidentialConflictAnalyzer(thresholds={
        "material_conflict_threshold": 0.50,
        "abstention_conflict_threshold": 0.70
    })
    lenient_res = lenient_analyzer.analyze_pair("DOM1", 0.92, "DOM2", 0.08)

    assert strict_res["conflict_status"] == EvidentialConflictStatus.ABSTENTION_REQUIRED
    assert strict_res["required_action"] == EvidentialRequiredAction.HUMAN_REVIEW

    assert moderate_res["conflict_status"] == EvidentialConflictStatus.MATERIAL_CONFLICT
    assert moderate_res["required_action"] == EvidentialRequiredAction.REVIEW_DISCREPANCY

    assert lenient_res["conflict_status"] == EvidentialConflictStatus.NO_MATERIAL_CONFLICT
    assert lenient_res["required_action"] == EvidentialRequiredAction.PROCEED


def test_cross_domain_fusion_engine_evidential_conflict_integration():
    """CrossDomainFusionEngine seamlessly integrates evidential conflict without averaging disagreement away."""
    engine = CrossDomainFusionEngine(identity_bridge_path="data/cases/identity_bridge.parquet")

    # Add mock bridge rows
    import pandas as pd
    df_bridge = pd.DataFrame([
        {
            "case_id": "CASE-M11-CONF-TEST",
            "canonical_entity_id": "ENT-CONF-TEST-01",
            "domain": "FINANCIAL",
            "raw_identifier": "WALLET_01",
            "mapping_method": "CONTROLLED_CASE_MAPPING",
            "confidence": 0.95,
            "evidence_ref": "ref:fin_01"
        },
        {
            "case_id": "CASE-M11-CONF-TEST",
            "canonical_entity_id": "ENT-CONF-TEST-01",
            "domain": "SOCIAL",
            "raw_identifier": "HANDLE_01",
            "mapping_method": "CONTROLLED_CASE_MAPPING",
            "confidence": 0.90,
            "evidence_ref": "ref:soc_01"
        }
    ])
    engine.bridge_df = pd.concat([engine.bridge_df, df_bridge], ignore_index=True)

    items = [
        {
            "finding_id": "FND_FIN",
            "source_domain": "FINANCIAL",
            "raw_identifier": "WALLET_01",
            "anomaly_score": 0.92,
            "epoch_time": 1700000000.0,
            "event_id": "EVT_FIN_01",
            "evidence_ref": "ref:fin_ev_01"
        },
        {
            "finding_id": "FND_SOC",
            "source_domain": "SOCIAL",
            "raw_identifier": "HANDLE_01",
            "anomaly_score": 0.08,
            "epoch_time": 1700000010.0,
            "event_id": "EVT_SOC_01",
            "evidence_ref": "ref:soc_ev_01"
        }
    ]

    fused = engine.fuse_for_entity("ENT-CONF-TEST-01", domain_evidence_items=items)

    assert fused["conflict_status"] == ConflictStatus.CONFLICTED
    assert "evidential_conflict" in fused
    ev_conf = fused["evidential_conflict"]
    assert ev_conf["overall_status"] == EvidentialConflictStatus.ABSTENTION_REQUIRED
    assert fused["requires_human_review"] is True
    assert fused["required_action"] == EvidentialRequiredAction.HUMAN_REVIEW

    # Disagreement is preserved: individual domain scores are present and distinct
    assert fused["domain_scores"]["FINANCIAL"] == 0.92
    assert fused["domain_scores"]["SOCIAL"] == 0.08

    # Risk score does NOT increase due to conflict (conflict penalty applied)
    assert fused["corroboration_score"] < 0.50


def test_m14_copilot_conflict_grounding_and_metrics():
    """M14 Copilot articulates evidential conflict metrics, Hellinger distance, and required action without guilt claims."""
    backend = InvestigationWorkspaceBackend()
    register_contradiction_fixture(backend)
    copilot = InvestigationCopilot(backend)

    res = copilot.ask("Are there conflicts between the available evidence?", case_id=CASE_CONFLICT_ID)

    assert res["status"] == "CONFLICTED"
    assert "evidential_conflict" in res
    assert res["required_action"] == "HUMAN_REVIEW"
    answer = res["answer"]

    # Verify key metrics are articulated in grounded explanation
    assert "FINANCIAL" in answer
    assert "SOCIAL" in answer
    assert "Hellinger distance" in answer or "hellinger" in answer.lower()
    assert "cosine similarity" in answer or "cosine" in answer.lower()
    assert "compound conflict" in answer.lower()
    assert "HUMAN_REVIEW" in answer or "human review" in answer.lower()

    # Verify no fraud / criminal accusations
    forbidden_terms = ["guilty", "criminal organization", "fraudster", "illicit scheme", "perpetrator"]
    for term in forbidden_terms:
        assert term not in answer.lower()
