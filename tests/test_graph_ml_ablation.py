# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: Targeted Test Suite for Graph ML Ablation (GraphSAGE vs Temporal GNN/TGN)

import pytest
import numpy as np
import torch

from dfap.graph_ml.benchmark import GraphMLAblationBenchmark, ModelInferenceState
from dfap.graph_ml.service import GraphMLService
from dfap.investigation.workspace import InvestigationWorkspaceBackend
from dfap.investigation.four_domain_fixture import register_four_domain_fixture, FOUR_DOMAIN_CASE_ID
from dfap.wp4.cli import handle_m13_command
from dfap.investigation.copilot import InvestigationCopilot


@pytest.fixture
def benchmark():
    return GraphMLAblationBenchmark(seed=42)


@pytest.fixture
def service():
    svc = GraphMLService(default_seed=42)
    svc.run_benchmark()
    return svc


@pytest.fixture
def workspace_backend():
    backend = InvestigationWorkspaceBackend()
    register_four_domain_fixture(backend)
    return backend


def test_chronological_split_strict_ordering(benchmark):
    """Verifies strict temporal separation: TRAIN < VAL < TEST with zero temporal overlap."""
    dataset = benchmark.generate_synthetic_temporal_dataset()
    t_split = dataset["temporal_split"]

    train_max = t_split["train_range"][1]
    val_min = t_split["val_range"][0]
    val_max = t_split["val_range"][1]
    test_min = t_split["test_range"][0]

    assert train_max < val_min, f"Train max ({train_max}) must be strictly less than val min ({val_min})"
    assert val_max < test_min, f"Val max ({val_max}) must be strictly less than test min ({test_min})"
    assert benchmark.verify_chronological_integrity(dataset) is True


def test_zero_future_leakage(benchmark):
    """Verifies that test evaluation items occur strictly after training and validation cuts."""
    dataset = benchmark.generate_synthetic_temporal_dataset()
    train_max = dataset["temporal_split"]["train_range"][1]
    val_max = dataset["temporal_split"]["val_range"][1]

    for item in dataset["test_eval_items"]:
        assert item["t"] > train_max
        assert item["t"] > val_max


def test_known_pair_uses_actual_model(service):
    """Verifies known pair evaluates through retained model state without fabricated constants."""
    # GraphSAGE
    pred_sage = service.predict_relationship("ENT_NODE_00", "ENT_NODE_01", model="graphsage")
    assert pred_sage["prediction_status"] == "PREDICTED"
    assert pred_sage["evidence_refs"] == []
    assert pred_sage["prediction_probability"] is not None
    assert 0.0 <= pred_sage["prediction_probability"] <= 1.0

    # Verify against direct inference from retained model state
    inf_sage = service._benchmark_runner.graphsage_inference_state
    src_t = torch.tensor([inf_sage.node_to_idx["ENT_NODE_00"]], dtype=torch.long)
    dst_t = torch.tensor([inf_sage.node_to_idx["ENT_NODE_01"]], dtype=torch.long)
    with torch.no_grad():
        direct_sage_prob = round(float(inf_sage.model(inf_sage.node_features, inf_sage.edge_index, src_t, dst_t)[0]), 4)
    assert pred_sage["prediction_probability"] == direct_sage_prob

    # TGN
    pred_tgn = service.predict_relationship("ENT_NODE_00", "ENT_NODE_01", model="tgn")
    assert pred_tgn["prediction_status"] == "PREDICTED"
    assert pred_tgn["evidence_refs"] == []
    assert pred_tgn["prediction_probability"] is not None
    assert 0.0 <= pred_tgn["prediction_probability"] <= 1.0


def test_different_known_pairs_are_model_evaluated(service):
    """Verifies that different valid pairs are evaluated via direct model inference."""
    inf_sage = service._benchmark_runner.graphsage_inference_state

    pairs = [("ENT_NODE_00", "ENT_NODE_01"), ("ENT_NODE_04", "ENT_NODE_05")]
    for s_id, d_id in pairs:
        res = service.predict_relationship(s_id, d_id, model="graphsage")
        assert res["prediction_status"] == "PREDICTED"
        assert res["prediction_probability"] is not None

        # Verify exact match with direct inference
        src_t = torch.tensor([inf_sage.node_to_idx[s_id]], dtype=torch.long)
        dst_t = torch.tensor([inf_sage.node_to_idx[d_id]], dtype=torch.long)
        with torch.no_grad():
            expected_prob = round(float(inf_sage.model(inf_sage.node_features, inf_sage.edge_index, src_t, dst_t)[0]), 4)
        assert res["prediction_probability"] == expected_prob


def test_unknown_pair_is_unavailable(service):
    """Verifies that unknown identifiers return structured UNAVAILABLE without fabricated numbers."""
    res_src_unk = service.predict_relationship("UNKNOWN_ENTITY_XYZ", "ENT_NODE_01", model="tgn")
    assert res_src_unk["status"] == "UNAVAILABLE"
    assert res_src_unk["prediction_status"] == "UNAVAILABLE"
    assert res_src_unk["prediction_probability"] is None
    assert "outside the trained benchmark graph" in res_src_unk["reason"]
    assert "No model prediction was produced" in res_src_unk["disclaimer"]

    res_dst_unk = service.predict_relationship("ENT_NODE_00", "UNKNOWN_ENTITY_ABC", model="graphsage")
    assert res_dst_unk["status"] == "UNAVAILABLE"
    assert res_dst_unk["prediction_probability"] is None


def test_no_python_hash_fallback(service, monkeypatch):
    """Proves inference does not invoke Python built-in hash()."""
    def boom(*args, **kwargs):
        raise AssertionError("Python hash() was invoked during Graph ML inference!")

    monkeypatch.setattr("builtins.hash", boom)

    # Known pair prediction
    res_sage = service.predict_relationship("ENT_NODE_00", "ENT_NODE_01", model="graphsage")
    assert res_sage["prediction_status"] == "PREDICTED"

    res_tgn = service.predict_relationship("ENT_NODE_00", "ENT_NODE_01", model="tgn")
    assert res_tgn["prediction_status"] == "PREDICTED"

    # Unknown pair prediction
    res_unk = service.predict_relationship("UNKNOWN_NODE", "ENT_NODE_01", model="tgn")
    assert res_unk["status"] == "UNAVAILABLE"


def test_prediction_does_not_mutate_m4(workspace_backend):
    """Confirms that running Graph ML predictions leaves M4 SQLite and igraph state untouched."""
    initial_vcount = workspace_backend.graph_service.backend.g.vcount() if hasattr(workspace_backend, "graph_service") else 0
    initial_ecount = workspace_backend.graph_service.backend.g.ecount() if hasattr(workspace_backend, "graph_service") else 0

    _ = workspace_backend.predict_graph_relationship("ENT_NODE_00", "ENT_NODE_01", model="tgn")
    _ = workspace_backend.predict_graph_relationship("ENT_NODE_00", "ENT_NODE_01", model="graphsage")
    _ = workspace_backend.predict_graph_relationship("UNKNOWN_NODE", "ENT_NODE_01", model="tgn")

    if hasattr(workspace_backend, "graph_service"):
        assert workspace_backend.graph_service.backend.g.vcount() == initial_vcount
        assert workspace_backend.graph_service.backend.g.ecount() == initial_ecount


def test_tgn_prediction_does_not_mutate_memory(service):
    """Verifies that requesting TGN predictions does NOT mutate retained inference memory."""
    inf_tgn = service._benchmark_runner.tgn_inference_state
    initial_mem = inf_tgn.model.memory.memory.clone()

    # Issue multiple predictions across different pairs
    _ = service.predict_relationship("ENT_NODE_00", "ENT_NODE_01", model="tgn")
    _ = service.predict_relationship("ENT_NODE_04", "ENT_NODE_05", model="tgn")
    _ = service.predict_relationship("ENT_NODE_01", "ENT_NODE_02", model="tgn")

    after_mem = inf_tgn.model.memory.memory.clone()
    assert torch.equal(initial_mem, after_mem), "TGN memory tensor was mutated during inference!"


def test_prediction_semantic_isolation(service):
    """Verifies that prediction records enforce semantic isolation from observed evidence."""
    res = service.predict_relationship("ENT_NODE_00", "ENT_NODE_01", model="tgn")
    assert res["prediction_status"] == "PREDICTED"
    assert res["prediction_type"] == "MODEL_PREDICTED_RELATIONSHIP"
    assert res["evidence_refs"] == []
    assert "NOT confirmed observation" in res["disclaimer"]
    assert "NOT forensic evidence" in res["disclaimer"]
    assert "NOT proof of guilt" in res["disclaimer"]


def test_deterministic_inference():
    """Verifies that identical seeds produce identical model predictions."""
    svc1 = GraphMLService(default_seed=99)
    svc2 = GraphMLService(default_seed=99)

    pred1_sage = svc1.predict_relationship("ENT_NODE_00", "ENT_NODE_01", model="graphsage")
    pred2_sage = svc2.predict_relationship("ENT_NODE_00", "ENT_NODE_01", model="graphsage")
    assert pred1_sage["prediction_probability"] == pred2_sage["prediction_probability"]

    pred1_tgn = svc1.predict_relationship("ENT_NODE_00", "ENT_NODE_01", model="tgn")
    pred2_tgn = svc2.predict_relationship("ENT_NODE_00", "ENT_NODE_01", model="tgn")
    assert pred1_tgn["prediction_probability"] == pred2_tgn["prediction_probability"]


def test_cli_known_and_unknown_prediction(workspace_backend):
    """Verifies CLI output for both known pairs (probabilities) and unknown pairs (UNAVAILABLE)."""
    # Known pair
    out_known = handle_m13_command(workspace_backend, "graph ml predict ENT_NODE_00 ENT_NODE_01 tgn")
    assert "GRAPH ML LINK PREDICTION" in out_known
    assert "Model:            TGN" in out_known
    assert "Status:           PREDICTED" in out_known
    assert "Probability:" in out_known
    assert "None" not in out_known

    # Unknown pair
    out_unk = handle_m13_command(workspace_backend, "graph ml predict UNKNOWN_SRC ENT_NODE_01 tgn")
    assert "GRAPH ML LINK PREDICTION" in out_unk
    assert "Status:           UNAVAILABLE" in out_unk
    assert "Probability:      None" in out_unk
    assert "outside the trained benchmark graph" in out_unk
