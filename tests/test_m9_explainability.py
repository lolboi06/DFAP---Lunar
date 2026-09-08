# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: Targeted Test Suite for M9 On-Demand SHAP Explainability for Flagged Findings

import pytest

from dfap.investigation.workspace import InvestigationWorkspaceBackend
from dfap.investigation.four_domain_fixture import (
    register_four_domain_fixture,
    FOUR_DOMAIN_CASE_ID,
    FOUR_DOMAIN_ENTITY_ID,
    FND_4DOM_FUSED,
    EVD_4DOM_FIN,
    EVD_4DOM_CDR,
    EVD_4DOM_SOC,
    EVD_4DOM_IPDR,
)
from dfap.investigation.explainability import (
    M9ShapExplainer,
    ExplanationStatus,
    ExplainerType,
    SHAP_EXPLANATION_SCHEMA_VERSION,
)
from dfap.wp4.cli import handle_m13_command
from dfap.investigation.copilot import InvestigationCopilot


@pytest.fixture
def backend():
    b = InvestigationWorkspaceBackend()
    register_four_domain_fixture(b)
    return b


def test_valid_flagged_finding_shap_explanation(backend):
    """Verifies that FND_4DOM_FUSED_001 returns a valid, structured SHAP explanation."""
    exp = backend.explain_finding_shap(FND_4DOM_FUSED)
    assert exp["schema_version"] == SHAP_EXPLANATION_SCHEMA_VERSION
    assert exp["finding_id"] == FND_4DOM_FUSED
    assert exp["entity_id"] == FOUR_DOMAIN_ENTITY_ID
    assert exp["explanation_status"] == ExplanationStatus.EXPLAINED.value
    assert exp["explainer_type"] == ExplainerType.EXACT_SHAPLEY.value
    assert exp["model_identifier"] == "M11_CROSS_DOMAIN_FUSION_DETECTOR"

    # Verify features and values
    expected_feats = {"CDR", "FINANCIAL", "IPDR", "SOCIAL"}
    assert set(exp["feature_names"]) == expected_feats
    assert abs(exp["feature_values"]["FINANCIAL"] - 0.92) < 1e-4
    assert abs(exp["feature_values"]["CDR"] - 0.85) < 1e-4
    assert abs(exp["feature_values"]["SOCIAL"] - 0.08) < 1e-4
    assert abs(exp["feature_values"]["IPDR"] - 0.45) < 1e-4

    # Efficiency property: base_value + sum(shap_values) == anomaly_score
    base_val = exp["base_value"]
    shap_sum = sum(exp["shap_values"].values())
    assert abs((base_val + shap_sum) - exp["anomaly_score"]) < 1e-3


def test_top_contributor_extraction_and_directions(backend):
    """Verifies distinction between features driving anomaly score vs pulling toward baseline normality."""
    exp = backend.explain_finding_shap(FND_4DOM_FUSED)
    
    pos = exp["top_positive_contributors"]
    neg = exp["top_negative_contributors"]

    # FINANCIAL, IPDR, CDR must be positive contributors
    pos_names = [c["feature_name"] for c in pos]
    assert "FINANCIAL" in pos_names
    assert "CDR" in pos_names
    assert "IPDR" in pos_names
    for c in pos:
        assert c["shap_value"] > 0
        assert c["contribution"] == "TOWARD_ANOMALY"

    # SOCIAL must be negative contributor (pulling down anomaly towards normal baseline)
    neg_names = [c["feature_name"] for c in neg]
    assert "SOCIAL" in neg_names
    for c in neg:
        assert c["shap_value"] < 0
        assert c["contribution"] == "AWAY_FROM_ANOMALY"


def test_unchanged_m9_anomaly_score(backend):
    """Verifies that SHAP explanation never recomputes or replaces the authoritative anomaly score."""
    finding_before = backend.get_finding(FND_4DOM_FUSED)
    original_score = finding_before["score"]

    exp = backend.explain_finding_shap(FND_4DOM_FUSED)
    assert abs(exp["anomaly_score"] - original_score) < 1e-4

    finding_after = backend.get_finding(FND_4DOM_FUSED)
    assert finding_after["score"] == original_score


def test_evidence_binding_preservation(backend):
    """Verifies evidence references remain bound to finding according to M12 lineage."""
    exp = backend.explain_finding_shap(FND_4DOM_FUSED)
    ev_refs = exp["evidence_refs"]
    assert EVD_4DOM_FIN in ev_refs
    assert EVD_4DOM_CDR in ev_refs
    assert EVD_4DOM_SOC in ev_refs
    assert EVD_4DOM_IPDR in ev_refs


def test_deterministic_output(backend):
    """Verifies repeated explanation requests produce stable, identical feature ordering and SHAP values."""
    exp1 = backend.explain_finding_shap(FND_4DOM_FUSED)
    exp2 = backend.explain_finding_shap(FND_4DOM_FUSED)

    assert exp1["feature_names"] == exp2["feature_names"]
    assert exp1["shap_values"] == exp2["shap_values"]
    assert exp1["top_positive_contributors"] == exp2["top_positive_contributors"]
    assert exp1["top_negative_contributors"] == exp2["top_negative_contributors"]


def test_missing_feature_and_unavailable_handling(backend):
    """Verifies that unsupported detector or missing feature vectors return structured UNAVAILABLE without fake SHAP."""
    # Register synthetic finding with unsupported detector
    backend.findings_by_id["FND_UNKNOWN_TEST"] = {
        "finding_id": "FND_UNKNOWN_TEST",
        "entity_id": FOUR_DOMAIN_ENTITY_ID,
        "detector": "UNKNOWN_CUSTOM_HEURISTIC",
        "score": 0.88,
    }

    exp = backend.explain_finding_shap("FND_UNKNOWN_TEST")
    assert exp["explanation_status"] == ExplanationStatus.UNAVAILABLE.value
    assert exp["explainer_type"] == ExplainerType.UNAVAILABLE.value
    assert exp["shap_values"] == {}
    assert "unavailable" in exp["explanation"].lower()


def test_semantic_safety_and_non_culpability(backend):
    """Verifies that SHAP explanations explicitly reject causal, criminal, or guilt claims."""
    exp = backend.explain_finding_shap(FND_4DOM_FUSED)
    assert "NOT real-world causation" in exp["explanation"]
    assert "fraudulent intent" in exp["explanation"] or "guilt" in exp["explanation"]
    assert any("NOT real-world causation" in lim for lim in exp["limitations"])
    assert any("guilt" in lim for lim in exp["limitations"])


def test_cli_integration(backend):
    """Verifies M13 CLI commands: finding explain and explain anomaly."""
    out_cmd1 = handle_m13_command(backend, f"finding explain {FND_4DOM_FUSED}")
    assert "M9 ON-DEMAND SHAP ANOMALY EXPLANATION" in out_cmd1
    assert FND_4DOM_FUSED in out_cmd1
    assert "FINANCIAL" in out_cmd1
    assert "SOCIAL" in out_cmd1
    assert "Limitations & Non-Culpability:" in out_cmd1

    out_cmd2 = handle_m13_command(backend, f"explain anomaly {FND_4DOM_FUSED}")
    assert "M9 ON-DEMAND SHAP ANOMALY EXPLANATION" in out_cmd2
    assert FND_4DOM_FUSED in out_cmd2


def test_copilot_why_anomalous_query(backend):
    """Verifies M14 Grounded Copilot cites SHAP model contribution explanation and disclaims causality."""
    copilot = InvestigationCopilot(backend)
    resp = copilot.ask(f"Why is finding {FND_4DOM_FUSED} anomalous?", case_id=FOUR_DOMAIN_CASE_ID, entity_id=FOUR_DOMAIN_ENTITY_ID)
    answer = resp["answer"]

    assert "SHAP Model Contribution Analysis" in answer
    assert "FINANCIAL" in answer
    assert "MODEL CONTRIBUTION EXPLANATION" in answer
    assert "NOT real-world causation" in answer or "not causal proof" in str(resp.get("limitations"))
    assert resp.get("shap_explanation") is not None
