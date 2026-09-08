# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: Test Suite for M13 Composite Risk Scoring & Triage Queue Prioritization

import json
import pytest

from dfap.investigation.workspace import InvestigationWorkspaceBackend
from dfap.investigation.four_domain_fixture import (
    register_four_domain_fixture,
    FOUR_DOMAIN_CASE_ID,
    FOUR_DOMAIN_ENTITY_ID,
    FND_4DOM_FUSED,
    FND_4DOM_CONTEXT,
)
from dfap.investigation.risk_scoring import (
    RiskScoringEngine,
    FindingRiskEvaluation,
    DEFAULT_RISK_SCORING_CONFIG,
    RISK_SCORING_SCHEMA_VERSION,
    PriorityLevel,
    MissingSignalPolicy,
)
from dfap.wp4.cli import handle_m13_command


@pytest.fixture
def backend():
    b = InvestigationWorkspaceBackend()
    register_four_domain_fixture(b)
    return b


def test_risk_scoring_config_and_schema():
    """Verifies explicit deterministic configuration weights sum to 1.0 and zero hidden constants."""
    cfg = DEFAULT_RISK_SCORING_CONFIG
    assert cfg["version"] == RISK_SCORING_SCHEMA_VERSION
    weights = cfg["weights"]
    assert weights["anomaly"] == 0.35
    assert weights["graph_significance"] == 0.20
    assert weights["fusion_confidence"] == 0.25
    assert weights["recency_clustering"] == 0.20
    assert abs(sum(weights.values()) - 1.0) < 1e-6
    assert cfg["priority_thresholds"]["high"] == 0.65
    assert cfg["priority_thresholds"]["medium"] == 0.40


def test_four_domain_case_triage_ranking(backend):
    """Verifies that CASE-DFAP-4DOMAIN-001 findings are deterministically prioritized with distinct ranks."""
    queue = backend.get_triage_queue(case_id=FOUR_DOMAIN_CASE_ID)
    assert len(queue) == 2

    # Rank 1 must be FND_4DOM_FUSED_001
    r1 = queue[0]
    assert r1["priority_rank"] == 1
    assert r1["finding_id"] == FND_4DOM_FUSED
    assert r1["entity_id"] == FOUR_DOMAIN_ENTITY_ID
    assert r1["priority_level"] == PriorityLevel.HIGH.value
    assert r1["risk_score"] >= 0.65
    assert r1["requires_human_review"] is True
    assert r1["conflict_status"] == "CONFLICTED"
    assert "EVIDENTIAL_CONFLICT_DETECTED" in r1["reason_codes"]
    assert "HIGH_FUSION_CORROBORATION" in r1["reason_codes"]
    assert r1["fusion_component"]["is_available"] is True

    # Rank 2 must be FND_4DOM_CONTEXT_002
    r2 = queue[1]
    assert r2["priority_rank"] == 2
    assert r2["finding_id"] == FND_4DOM_CONTEXT
    assert r2["risk_score"] < r1["risk_score"]
    assert r2["requires_human_review"] is False
    assert r2["fusion_component"]["is_available"] is False
    assert "FUSION_CONFIDENCE_UNAVAILABLE" in r2["missing_signals"]


def test_missing_signal_policy(backend):
    """Verifies REDISTRIBUTE_ACTIVE_WEIGHTS vs ZERO_FILL policies without fabricating fake data."""
    # Test REDISTRIBUTE_ACTIVE_WEIGHTS
    engine_redist = RiskScoringEngine(
        backend,
        config={**DEFAULT_RISK_SCORING_CONFIG, "missing_signal_policy": MissingSignalPolicy.REDISTRIBUTE_ACTIVE_WEIGHTS.value}
    )
    ev_redist = engine_redist.evaluate_finding(FND_4DOM_CONTEXT)
    assert "FUSION_CONFIDENCE_UNAVAILABLE" in ev_redist.missing_signals
    assert ev_redist.fusion_component["raw_value"] is None

    # Test ZERO_FILL
    engine_zero = RiskScoringEngine(
        backend,
        config={**DEFAULT_RISK_SCORING_CONFIG, "missing_signal_policy": MissingSignalPolicy.ZERO_FILL.value}
    )
    ev_zero = engine_zero.evaluate_finding(FND_4DOM_CONTEXT)
    assert "FUSION_CONFIDENCE_UNAVAILABLE" in ev_zero.missing_signals
    # Zero fill produces a lower score because weight of missing signal is not redistributed
    assert ev_zero.risk_score < ev_redist.risk_score


def test_input_order_independence(backend):
    """Verifies that the ranked queue order is strictly deterministic regardless of input list permutations."""
    engine = RiskScoringEngine(backend)
    list_forward = [FND_4DOM_FUSED, FND_4DOM_CONTEXT]
    list_reversed = [FND_4DOM_CONTEXT, FND_4DOM_FUSED]

    ranked_f = engine.rank_findings(finding_ids=list_forward)
    ranked_r = engine.rank_findings(finding_ids=list_reversed)

    assert [x.finding_id for x in ranked_f] == [x.finding_id for x in ranked_r]
    assert [x.priority_rank for x in ranked_f] == [1, 2]
    assert [x.priority_rank for x in ranked_r] == [1, 2]


def test_deterministic_tie_breaking(backend):
    """Verifies deterministic tie-breaking by finding_id ascending when scores are identical."""
    # Create two synthetic findings with identical attributes
    backend.findings_by_id["FND_TIE_B"] = {
        "finding_id": "FND_TIE_B",
        "entity_id": FOUR_DOMAIN_ENTITY_ID,
        "score": 0.50,
        "status": "ACTIVE"
    }
    backend.findings_by_id["FND_TIE_A"] = {
        "finding_id": "FND_TIE_A",
        "entity_id": FOUR_DOMAIN_ENTITY_ID,
        "score": 0.50,
        "status": "ACTIVE"
    }

    engine = RiskScoringEngine(backend)
    ranked = engine.rank_findings(finding_ids=["FND_TIE_B", "FND_TIE_A"])
    assert ranked[0].finding_id == "FND_TIE_A"
    assert ranked[1].finding_id == "FND_TIE_B"
    assert ranked[0].risk_score == ranked[1].risk_score
    assert ranked[0].priority_rank == 1
    assert ranked[1].priority_rank == 2


def test_semantic_safety_and_guilt_neutrality(backend):
    """Verifies explanations maintain strict safety guardrails and never assert criminal guilt or legal liability."""
    ev = backend.evaluate_finding_risk(FND_4DOM_FUSED)
    explanation = ev["explanation"]
    assert "does not infer guilt" in explanation
    assert "human review is required" in explanation
    assert "criminal" in explanation or "guilt" in explanation


def test_cli_risk_commands(backend):
    """Verifies M13 CLI integration: case risk, finding risk, risk queue, and copilot risk."""
    # 1. case risk
    out_case_risk = handle_m13_command(backend, f"case risk {FOUR_DOMAIN_CASE_ID}")
    assert f"CASE RISK TRIAGE QUEUE: {FOUR_DOMAIN_CASE_ID}" in out_case_risk
    assert FND_4DOM_FUSED in out_case_risk
    assert FND_4DOM_CONTEXT in out_case_risk
    assert "HIGH" in out_case_risk

    # 2. finding risk
    out_fnd_risk = handle_m13_command(backend, f"finding risk {FND_4DOM_FUSED}")
    assert "FINDING RISK EVALUATION" in out_fnd_risk
    assert FND_4DOM_FUSED in out_fnd_risk
    assert "Priority Level:    HIGH" in out_fnd_risk
    assert "Conflict Status:   CONFLICTED" in out_fnd_risk
    assert "Human Review Req:  True" in out_fnd_risk

    # 3. risk queue
    out_queue = handle_m13_command(backend, f"risk queue {FOUR_DOMAIN_CASE_ID}")
    assert f"RISK TRIAGE QUEUE (Case: {FOUR_DOMAIN_CASE_ID})" in out_queue
    assert "Rank" in out_queue
    assert "Finding ID" in out_queue

    # 4. copilot risk
    out_copilot_risk = handle_m13_command(backend, f"copilot risk {FND_4DOM_FUSED}")
    data = json.loads(out_copilot_risk)
    assert data["finding_id"] == FND_4DOM_FUSED
    assert data["priority_level"] == "HIGH"
    assert data["requires_human_review"] is True
