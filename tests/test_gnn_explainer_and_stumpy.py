# Author: Sam Roger X
# Component: DFAP Graph ML & Temporal Research
# Scope: Targeted Smoke Tests for GNNExplainer and STUMPY vs DTW Ablation

import pytest
import numpy as np

from dfap.graph_ml.service import GraphMLService
from dfap.graph_ml.explainer import GNNExplanationService
from dfap.investigation.temporal_ablation import TemporalSimilarityAblation
from dfap.investigation.workspace import InvestigationWorkspaceBackend
from dfap.investigation.agentic_orchestrator import AgenticInvestigationOrchestrator, ClosedDFAPToolRegistry
from dfap.wp4.cli import handle_m13_command


@pytest.fixture
def workspace_backend():
    backend = InvestigationWorkspaceBackend(output_dir="output", canonical_dir="data/canonical", cases_dir="data/cases")
    return backend


# =============================================================================
# FEATURE 1: GNNEXPLAINER SMOKE TESTS
# =============================================================================

def test_gnn_explainer_graphsage_known_pair(workspace_backend):
    """Verify GraphSAGE explanation on known pair ENT_NODE_00 -> ENT_NODE_01."""
    service = workspace_backend.graph_ml_service
    explainer = GNNExplanationService(service)

    res = explainer.explain_prediction("ENT_NODE_00", "ENT_NODE_01", model="graphsage")

    assert res["status"] == "PREDICTED"
    assert res["prediction_status"] == "PREDICTED"
    assert res["prediction_type"] == "MODEL_PREDICTED_RELATIONSHIP"
    assert res["model_name"] == "GraphSAGE"
    assert res["source_entity"] == "ENT_NODE_00"
    assert res["target_entity"] == "ENT_NODE_01"
    assert isinstance(res["predicted_probability"], float)
    assert 0.0 <= res["predicted_probability"] <= 1.0

    # Verify influential structures & features are populated from actual model
    assert "neighborhood_considered" in res
    assert res["neighborhood_considered"]["subgraph_nodes_count"] > 0
    assert len(res["influential_nodes"]) > 0
    assert len(res["influential_edges"]) > 0
    assert len(res["influential_features"]) > 0
    assert res["explanation_method"] == "MODEL_GROUNDED_SUBGRAPH_ATTRIBUTION"
    assert res["evidence_refs"] == []  # Not factual evidence
    assert any("not establish guilt" in lim.lower() or "not proof of intent" in lim.lower() for lim in res["limitations"])


def test_gnn_explainer_tgn_known_pair(workspace_backend):
    """Verify TGN explanation on known pair ENT_NODE_00 -> ENT_NODE_01."""
    service = workspace_backend.graph_ml_service
    explainer = GNNExplanationService(service)

    res = explainer.explain_prediction("ENT_NODE_00", "ENT_NODE_01", model="tgn")

    assert res["status"] == "PREDICTED"
    assert res["prediction_status"] == "PREDICTED"
    assert res["prediction_type"] == "MODEL_PREDICTED_RELATIONSHIP"
    assert res["model_name"] == "TGN"
    assert res["source_entity"] == "ENT_NODE_00"
    assert res["target_entity"] == "ENT_NODE_01"
    assert isinstance(res["predicted_probability"], float)
    assert 0.0 <= res["predicted_probability"] <= 1.0

    # Verify temporal memory attribution
    assert "neighborhood_considered" in res
    assert len(res["influential_nodes"]) > 0
    assert len(res["influential_features"]) > 0
    assert res["explanation_method"] == "TEMPORAL_MEMORY_STATE_ATTRIBUTION"
    assert res["evidence_refs"] == []


def test_gnn_explainer_unknown_node_unavailable(workspace_backend):
    """Verify unknown node returns clean UNAVAILABLE without synthetic explanation."""
    explainer = GNNExplanationService(workspace_backend.graph_ml_service)

    res = explainer.explain_prediction("ENT_UNKNOWN_XYZ", "ENT_NODE_01", model="graphsage")
    assert res["status"] == "UNAVAILABLE"
    assert res["explanation_status"] == "UNAVAILABLE"
    assert res["predicted_probability"] is None
    assert "outside the trained benchmark graph" in res["reason"]

    res_tgn = explainer.explain_prediction("ENT_NODE_00", "ENT_NONEXISTENT", model="tgn")
    assert res_tgn["status"] == "UNAVAILABLE"
    assert res_tgn["predicted_probability"] is None


def test_gnn_explainer_deterministic(workspace_backend):
    """Verify repeated explanation calls return identical outputs."""
    explainer = GNNExplanationService(workspace_backend.graph_ml_service)

    run1 = explainer.explain_prediction("ENT_NODE_00", "ENT_NODE_01", model="graphsage")
    run2 = explainer.explain_prediction("ENT_NODE_00", "ENT_NODE_01", model="graphsage")

    assert run1["predicted_probability"] == run2["predicted_probability"]
    assert run1["influential_nodes"] == run2["influential_nodes"]
    assert run1["influential_edges"] == run2["influential_edges"]
    assert run1["influential_features"] == run2["influential_features"]


def test_gnn_explainer_cli_command(workspace_backend):
    """Verify CLI graph ml explain command."""
    out = handle_m13_command(workspace_backend, "graph ml explain ENT_NODE_00 ENT_NODE_01 graphsage")
    assert "GRAPH ML GNNEXPLAINER ATTRIBUTION" in out
    assert "MODEL:                    GraphSAGE" in out
    assert "PREDICTION:" in out
    assert "TOP INFLUENTIAL NODES:" in out
    assert "LIMITATIONS:" in out

    out_unavail = handle_m13_command(workspace_backend, "graph ml explain ENT_UNKNOWN ENT_NODE_01")
    assert "UNAVAILABLE" in out_unavail


# =============================================================================
# FEATURE 2: STUMPY VS DTW ABLATION SMOKE TESTS
# =============================================================================

def test_stumpy_vs_dtw_ablation_both_available():
    """Verify temporal similarity ablation produces structured comparative metrics."""
    ablation = TemporalSimilarityAblation()
    res = ablation.run_controlled_ablation()

    assert res["ablation_id"] == "ABLATION-TEMPORAL-STUMPY-DTW-001"
    assert res["series_length"] == 60
    assert res["window_length"] == 8

    # DTW metrics
    dtw = res["dtw"]
    assert dtw["available"] is True
    assert isinstance(dtw["distance"], float)
    assert isinstance(dtw["similarity_score"], float)
    assert dtw["runtime_ms"] >= 0.0
    assert dtw["matched_index"] is not None

    # STUMPY metrics
    stump = res["stumpy"]
    assert stump["available"] is True
    assert isinstance(stump["distance"], float)
    assert isinstance(stump["similarity_score"], float)
    assert stump["runtime_ms"] >= 0.0
    assert stump["matched_index"] is not None

    # Verify both identify the planted recurring motif
    assert res["comparison"]["same_best_match"] is True
    assert "table_markdown" in res
    assert "limitations" in res


def test_stumpy_vs_dtw_ablation_stumpy_unavailable_fallback():
    """Verify clean fail-closed UNAVAILABLE when STUMPY is not available."""
    ablation = TemporalSimilarityAblation()
    res = ablation.run_controlled_ablation(simulate_stumpy_unavailable=True)

    assert res["dtw"]["available"] is True
    assert res["dtw"]["distance"] is not None

    assert res["stumpy"]["available"] is False
    assert res["stumpy"]["status"] == "UNAVAILABLE"
    assert res["stumpy"]["distance"] is None
    assert res["stumpy"]["similarity_score"] is None
    assert "UNAVAILABLE" in res["table_markdown"]


def test_stumpy_vs_dtw_cli_command(workspace_backend):
    """Verify CLI sequence ablation stumpy-dtw command."""
    out = handle_m13_command(workspace_backend, "sequence ablation stumpy-dtw")
    assert "TEMPORAL SIMILARITY ABLATION (STUMPY vs DTW)" in out
    assert "DFAP_DTW" in out
    assert "STUMPY_MASS" in out
    assert "LIMITATIONS:" in out


# =============================================================================
# M14 AGENTIC INTEGRATION SMOKE TESTS
# =============================================================================

def test_m14_closed_registry_contains_new_tools(workspace_backend):
    """Verify both new tools are registered in ClosedDFAPToolRegistry."""
    registry = ClosedDFAPToolRegistry(workspace_backend)
    assert registry.is_valid_tool("gnn_explain_prediction")
    assert registry.is_valid_tool("temporal_similarity_ablation")

    rec_gnn = registry.execute_tool("gnn_explain_prediction", 1, extra_params={"source_id": "ENT_NODE_00", "target_id": "ENT_NODE_01", "model": "graphsage"})
    assert rec_gnn.result_status == "SUCCESS"
    assert "GNN Attribution (GraphSAGE)" in rec_gnn.output_summary

    rec_abl = registry.execute_tool("temporal_similarity_ablation", 2)
    assert rec_abl.result_status == "SUCCESS"
    assert "Temporal Similarity Ablation" in rec_abl.output_summary


def test_m14_agentic_orchestrator_routes_gnn_and_stumpy_questions(workspace_backend):
    """Verify M14 orchestrator selects new tools for relevant investigator prompts."""
    orchestrator = AgenticInvestigationOrchestrator(workspace_backend)

    tools_gnn = orchestrator._plan_tools("Why did GraphSAGE predict the relationship between ENT_NODE_00 and ENT_NODE_01?", None, None, None)
    assert "gnn_explain_prediction" in tools_gnn

    tools_stumpy = orchestrator._plan_tools("How does STUMPY compare with the existing DTW temporal similarity method?", None, None, None)
    assert "temporal_similarity_ablation" in tools_stumpy
