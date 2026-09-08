# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: Research Test Suite for Temporal Backtracking, Forward Tracking, and Path Monotonicity

import pandas as pd
import pytest

from dfap.investigation.graph_traversal import InvestigationGraphTraversal


def test_backtracking_strict_temporal_backward_causality():
    """Verifies that backtracking only returns events with timestamp <= pivot timestamp."""
    traversal = InvestigationGraphTraversal()
    df = pd.read_parquet("data/canonical/elliptic_canonical.parquet")

    pivot_idx = 100
    w = df["actor_id"].iloc[pivot_idx]
    t_pivot = df["timestamp"].iloc[pivot_idx]
    epoch_pivot = df["epoch_time"].iloc[pivot_idx]

    bt = traversal.backtrack(w, pivot_timestamp=t_pivot, dataset="elliptic", max_results=50)

    for step in bt["preceding_timeline"]:
        assert step["epoch_time"] <= epoch_pivot, "Backtracking step occurred after pivot timestamp!"
        assert step["direction"] == "BACKWARD"
        assert "evidence_ref" in step


def test_forwardtracking_strict_temporal_forward_causality():
    """Verifies that forward tracking only returns events with timestamp >= pivot timestamp."""
    traversal = InvestigationGraphTraversal()
    df = pd.read_parquet("data/canonical/elliptic_canonical.parquet")

    pivot_idx = 100
    w = df["actor_id"].iloc[pivot_idx]
    t_pivot = df["timestamp"].iloc[pivot_idx]
    epoch_pivot = df["epoch_time"].iloc[pivot_idx]

    ft = traversal.forwardtrack(w, pivot_timestamp=t_pivot, dataset="elliptic", max_results=50)

    for step in ft["subsequent_timeline"]:
        assert step["epoch_time"] >= epoch_pivot, "Forward tracking step occurred before pivot timestamp!"
        assert step["direction"] == "FORWARD"
        assert "evidence_ref" in step


def test_find_temporal_paths_monotonic_non_decreasing():
    """Verifies that discovered multi-hop paths strictly enforce non-decreasing timestamps."""
    traversal = InvestigationGraphTraversal()
    df = pd.read_parquet("data/canonical/elliptic_canonical.parquet")

    w_src = df["actor_id"].iloc[0]
    w_tgt = df["target_id"].iloc[0]

    paths_res = traversal.find_temporal_paths(w_src, w_tgt, dataset="elliptic")
    assert "paths" in paths_res

    for path in paths_res["paths"]:
        assert path["temporal_monotonic"] is True
        seq = path["sequence"]
        for i in range(len(seq) - 1):
            assert seq[i]["epoch_time"] <= seq[i + 1]["epoch_time"], "Path violated temporal causality!"


def test_find_common_entities():
    """Verifies identification of common counterparties shared by two entities."""
    traversal = InvestigationGraphTraversal()
    df = pd.read_parquet("data/canonical/elliptic_canonical.parquet")

    w1 = df["actor_id"].iloc[0]
    w2 = df["actor_id"].iloc[1]

    common_res = traversal.find_common_entities(w1, w2, dataset="elliptic")
    assert "common_entities" in common_res
    assert isinstance(common_res["common_entities"], list)


def test_bfs_connected_component_isolation_two_disconnected_graphs():
    """
    MATHEMATICAL PROOF OF BFS GRAPH CONNECTIVITY:
    Given two disconnected components (A-B-C and X-Y-Z), BFS seeded from 'A'
    MUST extract only {A, B, C} and strictly exclude {X, Y, Z}.
    """
    from dfap.investigation.benchmark_generator import ForensicBenchmarkGenerator

    gen = ForensicBenchmarkGenerator()

    # Synthetic graph containing two strictly disconnected subgraphs
    events = [
        # Component 1 (Seeded from A)
        {"event_id": "EVT_01", "actor_id": "NODE_A", "target_id": "NODE_B", "epoch_time": 100.0, "timestamp": "2026-01-01T00:00:00Z"},
        {"event_id": "EVT_02", "actor_id": "NODE_B", "target_id": "NODE_C", "epoch_time": 200.0, "timestamp": "2026-01-01T01:00:00Z"},
        # Component 2 (Disconnected from A)
        {"event_id": "EVT_03", "actor_id": "NODE_X", "target_id": "NODE_Y", "epoch_time": 150.0, "timestamp": "2026-01-01T00:30:00Z"},
        {"event_id": "EVT_04", "actor_id": "NODE_Y", "target_id": "NODE_Z", "epoch_time": 250.0, "timestamp": "2026-01-01T01:30:00Z"}
    ]
    df_disconnected = pd.DataFrame(events)

    sub_df, cert = gen.extract_connected_temporal_subgraph(df_disconnected, seed_entity="NODE_A")

    # Verify component isolation
    assert set(sub_df["event_id"]) == {"EVT_01", "EVT_02"}, "Disconnected events from Component 2 leaked into extraction!"
    assert cert["seed_entity"] == "NODE_A"
    assert set(cert["component_nodes"]) == {"NODE_A", "NODE_B", "NODE_C"}
    assert "NODE_X" not in cert["component_nodes"]
    assert "NODE_Y" not in cert["component_nodes"]
    assert "NODE_Z" not in cert["component_nodes"]
    assert cert["component_edges"] == 2
    assert cert["is_connected_component"] is True
    assert "BFS_BOUNDED_SUBGRAPH_ROOT_NODE_A" in cert["connectivity_certificate"]
