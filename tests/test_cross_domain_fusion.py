# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: Phase 5 Test Suite for M11 Cross-Domain Fusion Engine & Evidence Graphs

import copy
import json
import os
import pytest
import numpy as np
import pandas as pd

from dfap.investigation.cross_domain_fusion import (
    CrossDomainFusionEngine,
    ConflictStatus,
    CROSS_DOMAIN_FUSION_CONFIG
)
from dfap.investigation.temporal_engine import AUTHORITATIVE_IDENTITY_BRIDGE_SHA256


@pytest.fixture
def fusion_engine():
    return CrossDomainFusionEngine()


def test_identity_bridge_enforcement(fusion_engine):
    """Verifies that the fusion engine loads the authoritative controlled identity bridge."""
    assert not fusion_engine.bridge_df.empty
    assert "canonical_entity_id" in fusion_engine.bridge_df.columns
    mappings = fusion_engine.get_controlled_mappings_for_entity("ENT_CROSS_SYNDICATE_ALPHA")
    assert len(mappings) >= 2
    for m in mappings:
        assert m["canonical_entity_id"] == "ENT_CROSS_SYNDICATE_ALPHA"
        assert m["confidence"] >= 0.70
        assert "evidence_ref" in m


def test_no_implicit_cross_domain_identity(fusion_engine):
    """
    CRITICAL IDENTITY INTEGRITY:
    Never infer identity across domains from correlation or similarity alone.
    Unregistered entities without bridge mappings must abstain.
    """
    unregistered_entity = "ENT_UNREGISTERED_SUSPECT_999"
    res = fusion_engine.fuse_for_entity(unregistered_entity)
    assert res["conflict_status"] == ConflictStatus.IDENTITY_UNCERTAIN
    assert res["corroboration_score"] == 0.0
    assert "FUSION ABSTAINED" in res["explanation"]


def test_temporal_window_correctness(fusion_engine):
    """Verifies that temporal window constraints properly filter and evaluate coherence."""
    entity = "ENT_CROSS_SYNDICATE_ALPHA"
    base_time = 1421980000.0  # anchor

    # Evidence spanning 30 hours with authorized entity identifiers
    items = [
        {"finding_id": "F1", "source_domain": "FINANCIAL", "raw_identifier": "WALLET_1Dark6f24042c69bf5fd787db", "anomaly_score": 0.85, "epoch_time": base_time, "event_id": "E1", "evidence_ref": "ref:1"},
        {"finding_id": "F2", "source_domain": "TELECOM", "raw_identifier": "IP_10.0.1.1", "anomaly_score": 0.80, "epoch_time": base_time + 1800.0, "event_id": "E2", "evidence_ref": "ref:2"},     # +30 mins
        {"finding_id": "F3", "source_domain": "SOCIAL", "raw_identifier": "SO_10661", "anomaly_score": 0.75, "epoch_time": base_time + 108000.0, "event_id": "E3", "evidence_ref": "ref:3"}    # +30 hours
    ]

    # TIGHT (1h): excludes F3 (30h)
    fused_tight = fusion_engine.fuse_for_entity(entity, domain_evidence_items=items, temporal_window_name="TIGHT")
    assert "E3" not in fused_tight["trigger_events"]
    assert len(fused_tight["trigger_events"]) == 2

    # BROAD (7d): includes all 3
    fused_broad = fusion_engine.fuse_for_entity(entity, domain_evidence_items=items, temporal_window_name="BROAD")
    assert "E3" in fused_broad["trigger_events"]
    assert len(fused_broad["trigger_events"]) == 3


def test_independent_domain_counting(fusion_engine):
    """Verifies that evidence from 3 independent domains produces independent_domain_count == 3."""
    entity = "ENT_CROSS_SYNDICATE_ALPHA"
    items = [
        {"finding_id": "F1", "source_domain": "TELECOM", "raw_identifier": "IP_10.0.1.1", "anomaly_score": 0.85, "epoch_time": 1000.0, "event_id": "E1", "evidence_ref": "ref:1"},
        {"finding_id": "F2", "source_domain": "FINANCIAL", "raw_identifier": "WALLET_1Dark6f24042c69bf5fd787db", "anomaly_score": 0.90, "epoch_time": 1050.0, "event_id": "E2", "evidence_ref": "ref:2"},
        {"finding_id": "F3", "source_domain": "SOCIAL", "raw_identifier": "SO_10661", "anomaly_score": 0.75, "epoch_time": 1100.0, "event_id": "E3", "evidence_ref": "ref:3"},
    ]
    res = fusion_engine.fuse_for_entity(entity, domain_evidence_items=items)
    assert res["independent_domain_count"] == 3
    assert set(res["domains_present"]) == {"TELECOM", "FINANCIAL", "SOCIAL"}
    assert res["conflict_status"] == ConflictStatus.SUPPORTED
    assert res["corroboration_score"] > 0.60


def test_same_domain_duplicate_collapse(fusion_engine):
    """
    CRITICAL INDEPENDENCE RULE:
    Multiple findings from the same domain or derived from the same event
    must NOT artificially inflate independent_domain_count.
    """
    entity = "ENT_CROSS_SYNDICATE_ALPHA"
    duplicate_items = [
        {"finding_id": "F_TEL_1", "source_domain": "TELECOM", "raw_identifier": "IP_10.0.1.1", "anomaly_score": 0.85, "epoch_time": 1000.0, "event_id": "E_TEL_1", "evidence_ref": "ref:1"},
        {"finding_id": "F_TEL_2", "source_domain": "TELECOM", "raw_identifier": "IP_10.0.1.1", "anomaly_score": 0.88, "epoch_time": 1010.0, "event_id": "E_TEL_1", "evidence_ref": "ref:2"},  # same event
        {"finding_id": "F_TEL_3", "source_domain": "TELECOM", "raw_identifier": "IP_10.0.1.1", "anomaly_score": 0.80, "epoch_time": 1020.0, "event_id": "E_TEL_3", "evidence_ref": "ref:3"},  # same domain
    ]
    res = fusion_engine.fuse_for_entity(entity, domain_evidence_items=duplicate_items)
    assert res["independent_domain_count"] == 1
    assert res["conflict_status"] == ConflictStatus.INSUFFICIENT_EVIDENCE


def test_conflict_preservation(fusion_engine):
    """
    CRITICAL CONFLICT INTEGRITY:
    Contradictory evidence must NOT be averaged away.
    It must trigger CONFLICTED status and apply conflict penalty.
    """
    entity = "ENT_CROSS_SYNDICATE_ALPHA"
    conflicting_items = [
        {"finding_id": "F1", "source_domain": "TELECOM", "raw_identifier": "IP_10.0.1.1", "anomaly_score": 0.92, "epoch_time": 1000.0, "event_id": "E1", "evidence_ref": "ref:1"},   # Strong anomaly
        {"finding_id": "F2", "source_domain": "FINANCIAL", "raw_identifier": "WALLET_1Dark6f24042c69bf5fd787db", "anomaly_score": 0.10, "epoch_time": 1100.0, "event_id": "E2", "evidence_ref": "ref:2"}, # Strongly normal (contradicting)
    ]
    res = fusion_engine.fuse_for_entity(entity, domain_evidence_items=conflicting_items)
    assert res["conflict_status"] == ConflictStatus.CONFLICTED
    assert "TELECOM" in res["supporting_domains"]
    assert "FINANCIAL" in res["contradicting_domains"]
    assert "CONFLICT: Contradicted by FINANCIAL" in res["explanation"]


def test_uncertain_identity_abstention():
    """Verifies that an identity bridge mapping below confidence threshold causes fusion to abstain."""
    low_conf_bridge = pd.DataFrame([{
        "case_id": "CASE-LOW-CONF",
        "canonical_entity_id": "ENT_LOW_CONFIDENCE",
        "domain": "FINANCIAL",
        "raw_identifier": "WALLET_UNCERTAIN",
        "mapping_method": "WEAK_HEURISTIC",
        "confidence": 0.40,  # Below 0.70 threshold
        "evidence_ref": "ref:weak_link"
    }])
    temp_path = "output/temp_low_conf_bridge.parquet"
    low_conf_bridge.to_parquet(temp_path)

    try:
        engine = CrossDomainFusionEngine(identity_bridge_path="data/cases/identity_bridge.parquet")
        engine.bridge_df = low_conf_bridge  # inject low-confidence bridge in-memory
        res = engine.fuse_for_entity("ENT_LOW_CONFIDENCE")
        assert res["conflict_status"] == ConflictStatus.IDENTITY_UNCERTAIN
        assert res["corroboration_score"] == 0.0
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def test_provenance_completeness(fusion_engine):
    """Verifies that every fused case preserves complete provenance and evidence refs."""
    entity = "ENT_CROSS_SYNDICATE_ALPHA"
    items = [
        {"finding_id": "F1", "source_domain": "TELECOM", "raw_identifier": "IP_10.0.1.1", "anomaly_score": 0.85, "epoch_time": 1000.0, "event_id": "E1", "evidence_ref": "ref:ev_tel_01"},
        {"finding_id": "F2", "source_domain": "FINANCIAL", "raw_identifier": "WALLET_1Dark6f24042c69bf5fd787db", "anomaly_score": 0.88, "epoch_time": 1050.0, "event_id": "E2", "evidence_ref": "ref:ev_fin_02"},
    ]
    res = fusion_engine.fuse_for_entity(entity, domain_evidence_items=items)
    assert len(res["provenance_refs"]) >= 2
    assert "ref:ev_tel_01" in res["provenance_refs"]
    assert "ref:ev_fin_02" in res["provenance_refs"]
    assert res["evidence_completeness"] == 1.0


def test_future_evidence_invariance(fusion_engine):
    """
    CRITICAL PROOF: Evidence occurring in the future strictly after the temporal window
    cannot alter the past fused case results.
    """
    entity = "ENT_CROSS_SYNDICATE_ALPHA"
    base_time = 1421980000.0
    past_items = [
        {"finding_id": "F1", "source_domain": "TELECOM", "raw_identifier": "IP_10.0.1.1", "anomaly_score": 0.85, "epoch_time": base_time, "event_id": "E1", "evidence_ref": "ref:1"},
        {"finding_id": "F2", "source_domain": "FINANCIAL", "raw_identifier": "WALLET_1Dark6f24042c69bf5fd787db", "anomaly_score": 0.90, "epoch_time": base_time + 1000.0, "event_id": "E2", "evidence_ref": "ref:2"}
    ]

    # Fusion before future injection
    fused_before = fusion_engine.fuse_for_entity(entity, domain_evidence_items=past_items, temporal_window_name="MODERATE")

    # Injected future evidence 60 days later
    future_items = past_items + [
        {"finding_id": "F_FUTURE", "source_domain": "SOCIAL", "raw_identifier": "SO_10661", "anomaly_score": 0.99, "epoch_time": base_time + (60 * 86400.0), "event_id": "E_FUTURE", "evidence_ref": "ref:future"}
    ]

    fused_after = fusion_engine.fuse_for_entity(entity, domain_evidence_items=future_items, temporal_window_name="MODERATE")

    # Invariance assert
    assert fused_before["trigger_events"] == fused_after["trigger_events"]
    assert fused_before["corroboration_score"] == fused_after["corroboration_score"]
    assert fused_before["independent_domain_count"] == fused_after["independent_domain_count"]


def test_real_entity_with_no_upstream_findings_produces_zero_fabricated_evidence(fusion_engine):
    """
    CRITICAL INTEGRITY REGRESSION TEST:
    Verifies that a real entity in the identity bridge with zero authentic findings
    in findings.parquet produces:
      - zero fabricated evidence
      - zero fabricated event IDs
      - zero fabricated anomaly scores
      - conflict_status = INSUFFICIENT_EVIDENCE
      - corroboration_score = 0.0
    Production discovery must NEVER manufacture event_id, finding_id, timestamp,
    anomaly_score, or evidence_ref from an identity mapping alone.
    """
    real_entity = "ENT_CROSS_SYNDICATE_ALPHA"
    # Call without passing synthetic domain_evidence_items
    fused = fusion_engine.fuse_for_entity(real_entity)

    assert fused["domain_evidence_count"] == 0
    assert fused["independent_domain_count"] == 0
    assert fused["trigger_events"] == []
    assert fused["supporting_findings"] == []
    assert fused["domain_scores"] == {}
    assert fused["corroboration_score"] == 0.0
    assert fused["conflict_status"] == ConflictStatus.INSUFFICIENT_EVIDENCE
    assert "FUSION ABSTAINED" in fused["explanation"]


def test_deterministic_ranking(fusion_engine):
    """Verifies that autonomous discovery produces deterministic case order and scores."""
    evidence_pool = {
        "ENT_CROSS_SYNDICATE_ALPHA": [
            {"finding_id": "F1", "source_domain": "TELECOM", "raw_identifier": "IP_10.0.1.1", "anomaly_score": 0.85, "epoch_time": 1000.0, "event_id": "E1", "evidence_ref": "ref:1"},
            {"finding_id": "F2", "source_domain": "FINANCIAL", "raw_identifier": "WALLET_1Dark6f24042c69bf5fd787db", "anomaly_score": 0.90, "epoch_time": 1050.0, "event_id": "E2", "evidence_ref": "ref:2"},
            {"finding_id": "F3", "source_domain": "SOCIAL", "raw_identifier": "SO_10661", "anomaly_score": 0.80, "epoch_time": 1100.0, "event_id": "E3", "evidence_ref": "ref:3"},
        ],
        "ENT_CROSS_INTRUDER_BETA": [
            {"finding_id": "F4", "source_domain": "TELECOM", "raw_identifier": "IP_10.0.1.2", "anomaly_score": 0.70, "epoch_time": 1000.0, "event_id": "E4", "evidence_ref": "ref:4"},
            {"finding_id": "F5", "source_domain": "FINANCIAL", "raw_identifier": "WALLET_1Darkd91e3007ce525ba9b98f", "anomaly_score": 0.65, "epoch_time": 1050.0, "event_id": "E5", "evidence_ref": "ref:5"}
        ]
    }
    run1 = fusion_engine.discover_fused_cases(domain_evidence_by_entity=evidence_pool, temporal_window_name="MODERATE")
    run2 = fusion_engine.discover_fused_cases(domain_evidence_by_entity=evidence_pool, temporal_window_name="MODERATE")

    assert len(run1) == 2
    assert len(run2) == 2
    for c1, c2 in zip(run1, run2):
        assert c1["fusion_case_id"] == c2["fusion_case_id"]
        assert c1["corroboration_score"] == c2["corroboration_score"]
        assert c1["canonical_entity_id"] == c2["canonical_entity_id"]


def test_synthetic_control_cases(fusion_engine):
    """
    MANDATORY SYNTHETIC CONTROLLED FIXTURES (Section 14):
      CASE_A: telecom + financial + social aligned -> SUPPORTED, high corroboration
      CASE_B: telecom only -> INSUFFICIENT_EVIDENCE
      CASE_C: financial + unrelated social -> rejects cross-entity contamination
      CASE_D: high similarity but uncertain identity -> IDENTITY_UNCERTAIN
      CASE_E: temporal mismatch -> low coherence / window exclusion
      CASE_F: contradictory evidence -> CONFLICTED
    """
    entity = "ENT_CROSS_SYNDICATE_ALPHA"
    t0 = 1421980000.0

    # CASE A: Aligned
    case_a_items = [
        {"finding_id": "FA1", "source_domain": "TELECOM", "raw_identifier": "IP_10.0.1.1", "anomaly_score": 0.85, "epoch_time": t0, "event_id": "EA1", "evidence_ref": "ref:A1"},
        {"finding_id": "FA2", "source_domain": "FINANCIAL", "raw_identifier": "WALLET_1Dark6f24042c69bf5fd787db", "anomaly_score": 0.90, "epoch_time": t0 + 100.0, "event_id": "EA2", "evidence_ref": "ref:A2"},
        {"finding_id": "FA3", "source_domain": "SOCIAL", "raw_identifier": "SO_10661", "anomaly_score": 0.80, "epoch_time": t0 + 200.0, "event_id": "EA3", "evidence_ref": "ref:A3"}
    ]
    res_a = fusion_engine.fuse_for_entity(entity, domain_evidence_items=case_a_items)
    assert res_a["conflict_status"] == ConflictStatus.SUPPORTED
    assert res_a["independent_domain_count"] == 3
    assert res_a["corroboration_score"] >= 0.70

    # CASE B: Single domain only
    case_b_items = [
        {"finding_id": "FB1", "source_domain": "TELECOM", "raw_identifier": "IP_10.0.1.1", "anomaly_score": 0.85, "epoch_time": t0, "event_id": "EB1", "evidence_ref": "ref:B1"}
    ]
    res_b = fusion_engine.fuse_for_entity(entity, domain_evidence_items=case_b_items)
    assert res_b["conflict_status"] == ConflictStatus.INSUFFICIENT_EVIDENCE
    assert res_b["independent_domain_count"] == 1

    # CASE C: Unrelated entity
    res_c = fusion_engine.fuse_for_entity("ENT_UNRELATED_NON_BRIDGED_ACTOR")
    assert res_c["conflict_status"] == ConflictStatus.IDENTITY_UNCERTAIN

    # CASE D: Uncertain identity
    # Covered via test_uncertain_identity_abstention

    # CASE E: Temporal mismatch
    case_e_items = [
        {"finding_id": "FE1", "source_domain": "TELECOM", "raw_identifier": "IP_10.0.1.1", "anomaly_score": 0.85, "epoch_time": t0, "event_id": "EE1", "evidence_ref": "ref:E1"},
        {"finding_id": "FE2", "source_domain": "FINANCIAL", "raw_identifier": "WALLET_1Dark6f24042c69bf5fd787db", "anomaly_score": 0.90, "epoch_time": t0 + (30 * 86400.0), "event_id": "EE2", "evidence_ref": "ref:E2"}
    ]
    res_e = fusion_engine.fuse_for_entity(entity, domain_evidence_items=case_e_items, temporal_window_name="TIGHT")
    assert len(res_e["trigger_events"]) == 1  # 30-day distant event excluded from 1h window

    # CASE F: Contradictory evidence
    case_f_items = [
        {"finding_id": "FF1", "source_domain": "TELECOM", "raw_identifier": "IP_10.0.1.1", "anomaly_score": 0.95, "epoch_time": t0, "event_id": "EF1", "evidence_ref": "ref:F1"},
        {"finding_id": "FF2", "source_domain": "FINANCIAL", "raw_identifier": "WALLET_1Dark6f24042c69bf5fd787db", "anomaly_score": 0.15, "epoch_time": t0 + 50.0, "event_id": "EF2", "evidence_ref": "ref:F2"}
    ]
    res_f = fusion_engine.fuse_for_entity(entity, domain_evidence_items=case_f_items)
    assert res_f["conflict_status"] == ConflictStatus.CONFLICTED


def test_ablation_correctness(fusion_engine):
    """
    CRITICAL ABLATION STUDY:
    Demonstrates that independent multi-domain fusion reduces uncertainty
    and provides corroboration beyond any single isolated domain.
    """
    entity = "ENT_CROSS_SYNDICATE_ALPHA"
    pool = {
        "TELECOM": [{"finding_id": "F_TEL", "source_domain": "TELECOM", "raw_identifier": "IP_10.0.1.1", "anomaly_score": 0.85, "epoch_time": 1000.0, "event_id": "E_TEL", "evidence_ref": "ref:tel"}],
        "FINANCIAL": [{"finding_id": "F_FIN", "source_domain": "FINANCIAL", "raw_identifier": "WALLET_1Dark6f24042c69bf5fd787db", "anomaly_score": 0.90, "epoch_time": 1050.0, "event_id": "E_FIN", "evidence_ref": "ref:fin"}],
        "SOCIAL": [{"finding_id": "F_SOC", "source_domain": "SOCIAL", "raw_identifier": "SO_10661", "anomaly_score": 0.78, "epoch_time": 1100.0, "event_id": "E_SOC", "evidence_ref": "ref:soc"}],
        "GRAPH": [{"finding_id": "F_GRP", "source_domain": "GRAPH", "raw_identifier": "IP_10.0.1.1", "anomaly_score": 0.82, "epoch_time": 1150.0, "event_id": "E_GRP", "evidence_ref": "ref:grp"}]
    }

    ablation = fusion_engine.run_ablation_study(entity, domain_evidence_pool=pool)
    configs = ablation["configurations"]

    # 1. Single domain has INSUFFICIENT_EVIDENCE and higher uncertainty
    assert configs["telecom_only"]["conflict_status"] == ConflictStatus.INSUFFICIENT_EVIDENCE
    assert configs["telecom_only"]["uncertainty"] > configs["three_domain_telecom_financial_social"]["uncertainty"]

    # 2. Corroboration score monotonically increases with independent corroborating domains
    score_1dom = configs["telecom_only"]["corroboration_score"]
    score_2dom = configs["pairwise_telecom_financial"]["corroboration_score"]
    score_3dom = configs["three_domain_telecom_financial_social"]["corroboration_score"]
    assert score_1dom < score_2dom < score_3dom


# =========================================================================
# PHASE 5 INTEGRITY FIX #2: MANDATORY TESTS A THROUGH F
# =========================================================================

def test_entity_a_with_valid_a_evidence_accepted(fusion_engine):
    """
    TEST A: entity A + valid A evidence -> accepted.
    Evidence items carrying entity A's mapped raw identifier are verified and accepted.
    """
    entity_a = "ENT_CROSS_SYNDICATE_ALPHA"
    valid_a_items = [
        {"finding_id": "F_A1", "source_domain": "TELECOM", "raw_identifier": "IP_10.0.1.1", "anomaly_score": 0.85, "epoch_time": 1000.0, "event_id": "E1", "evidence_ref": "ref:tel_a"},
        {"finding_id": "F_A2", "source_domain": "FINANCIAL", "raw_identifier": "WALLET_1Dark6f24042c69bf5fd787db", "anomaly_score": 0.90, "epoch_time": 1050.0, "event_id": "E2", "evidence_ref": "ref:fin_a"},
    ]
    res = fusion_engine.fuse_for_entity(entity_a, domain_evidence_items=valid_a_items)
    assert res["conflict_status"] == ConflictStatus.SUPPORTED
    assert res["domain_evidence_count"] == 2
    assert res["independent_domain_count"] == 2
    assert res["corroboration_score"] > 0.60


def test_entity_a_with_valid_b_evidence_rejected(fusion_engine):
    """
    TEST B: entity A + valid B evidence -> rejected/abstained.
    Evidence items belonging to entity B (IP_10.0.1.2) must NOT contaminate entity A.
    """
    entity_a = "ENT_CROSS_SYNDICATE_ALPHA"
    # IP_10.0.1.2 maps to ENT_CROSS_INTRUDER_BETA, NOT ENT_CROSS_SYNDICATE_ALPHA
    b_items = [
        {"finding_id": "F_B1", "source_domain": "TELECOM", "raw_identifier": "IP_10.0.1.2", "anomaly_score": 0.85, "epoch_time": 1000.0, "event_id": "E_B1", "evidence_ref": "ref:b"}
    ]
    res = fusion_engine.fuse_for_entity(entity_a, domain_evidence_items=b_items)
    assert res["domain_evidence_count"] == 0
    assert res["independent_domain_count"] == 0
    assert res["corroboration_score"] == 0.0
    assert res["conflict_status"] == ConflictStatus.INSUFFICIENT_EVIDENCE
    assert "Zero valid domain evidence items bound" in res["explanation"]


def test_entity_a_with_unmapped_evidence_rejected(fusion_engine):
    """
    TEST C: entity A + unmapped evidence -> rejected/abstained.
    Evidence with an unmapped raw identifier not in the bridge is rejected.
    """
    entity_a = "ENT_CROSS_SYNDICATE_ALPHA"
    unmapped_items = [
        {"finding_id": "F_UNMAPPED", "source_domain": "TELECOM", "raw_identifier": "IP_192.168.99.99", "anomaly_score": 0.88, "epoch_time": 1000.0, "event_id": "E_U", "evidence_ref": "ref:u"}
    ]
    res = fusion_engine.fuse_for_entity(entity_a, domain_evidence_items=unmapped_items)
    assert res["domain_evidence_count"] == 0
    assert res["corroboration_score"] == 0.0
    assert res["conflict_status"] == ConflictStatus.INSUFFICIENT_EVIDENCE


def test_entity_a_with_similar_looking_b_identifier_rejected(fusion_engine):
    """
    TEST D: entity A + similar-looking B identifier -> rejected/abstained.
    Even slight syntactic modifications or spoofed lookalikes must fail identity verification.
    """
    entity_a = "ENT_CROSS_SYNDICATE_ALPHA"
    lookalike_items = [
        {"finding_id": "F_LOOKALIKE_1", "source_domain": "TELECOM", "raw_identifier": "IP_10.0.1.10", "anomaly_score": 0.85, "epoch_time": 1000.0, "event_id": "E_L1", "evidence_ref": "ref:l1"},
        {"finding_id": "F_LOOKALIKE_2", "source_domain": "FINANCIAL", "raw_identifier": "WALLET_1Dark6f24042c69bf5fd787d", "anomaly_score": 0.90, "epoch_time": 1050.0, "event_id": "E_L2", "evidence_ref": "ref:l2"}
    ]
    res = fusion_engine.fuse_for_entity(entity_a, domain_evidence_items=lookalike_items)
    assert res["domain_evidence_count"] == 0
    assert res["corroboration_score"] == 0.0
    assert res["conflict_status"] == ConflictStatus.INSUFFICIENT_EVIDENCE


def test_entity_a_with_matching_timestamp_score_but_wrong_identity_rejected(fusion_engine):
    """
    TEST E: entity A + evidence with matching timestamp/score but wrong identity -> rejected/abstained.
    Temporal alignment or score coincidence can never substitute for authentic identity linkage.
    """
    entity_a = "ENT_CROSS_SYNDICATE_ALPHA"
    # Identical timestamp and score to A's timeline, but mapped to B's identifier
    coincidental_b_items = [
        {"finding_id": "F_COINCIDENCE", "source_domain": "TELECOM", "raw_identifier": "IP_10.0.1.2", "anomaly_score": 0.85, "epoch_time": 1000.0, "event_id": "E_COINC", "evidence_ref": "ref:coinc"}
    ]
    res = fusion_engine.fuse_for_entity(entity_a, domain_evidence_items=coincidental_b_items)
    assert res["domain_evidence_count"] == 0
    assert res["corroboration_score"] == 0.0
    assert res["conflict_status"] == ConflictStatus.INSUFFICIENT_EVIDENCE


def test_accepted_evidence_contains_explicit_identity_provenance(fusion_engine):
    """
    TEST F: accepted evidence output must contain explicit identity provenance:
      - canonical_entity_id
      - source/raw identifier
      - mapping_method
      - mapping_confidence
      - mapping_evidence_ref
    """
    entity_a = "ENT_CROSS_SYNDICATE_ALPHA"
    valid_items = [
        {"finding_id": "F_A1", "source_domain": "TELECOM", "raw_identifier": "IP_10.0.1.1", "anomaly_score": 0.85, "epoch_time": 1000.0, "event_id": "E1", "evidence_ref": "ref:tel_a"},
        {"finding_id": "F_A2", "source_domain": "FINANCIAL", "raw_identifier": "WALLET_1Dark6f24042c69bf5fd787db", "anomaly_score": 0.90, "epoch_time": 1050.0, "event_id": "E2", "evidence_ref": "ref:fin_a"},
    ]
    res = fusion_engine.fuse_for_entity(entity_a, domain_evidence_items=valid_items)
    assert res["conflict_status"] == ConflictStatus.SUPPORTED

    assert "identity_provenance" in res
    assert len(res["identity_provenance"]) == 2

    for prov in res["identity_provenance"]:
        assert prov["canonical_entity_id"] == entity_a
        assert prov["raw_identifier"] in ["IP_10.0.1.1", "WALLET_1Dark6f24042c69bf5fd787db"]
        assert prov["mapping_method"] == "CONTROLLED_CASE_MAPPING"
        assert prov["mapping_confidence"] >= 0.70
        assert prov["mapping_evidence_ref"].startswith("ref:bridge_")
