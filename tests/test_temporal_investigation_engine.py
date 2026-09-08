# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: Phase 3 Test Suite for Canonical Temporal Investigation Engine

import copy
import hashlib
import json
import os
import pytest
import pandas as pd

from dfap.schemas import TemporalSemantics
from dfap.investigation.temporal_engine import (
    TemporalEventEngine,
    load_identity_bridge_readonly,
    AUTHORITATIVE_IDENTITY_BRIDGE_SHA256,
)
from dfap.investigation.auto_discovery import AutoDiscoveryEngine


@pytest.fixture
def engine():
    return TemporalEventEngine()


def test_temporal_history_observed_vs_surrogate(engine):
    """Verifies history correctly distinguishes CHRONOLOGICAL_HISTORY from ORDERED_HISTORY."""
    # 1. Stack Overflow: Observed timestamps
    so_hist = engine.get_entity_history("SO_10661", dataset="stackoverflow")
    assert so_hist["history_type"] == "CHRONOLOGICAL_HISTORY"
    assert so_hist["temporal_semantics"] == TemporalSemantics.OBSERVED_TIMESTAMP
    assert so_hist["total_events"] > 0
    assert "activity_by_time" in so_hist

    # 2. UNSW: Sequence surrogate
    unsw_hist = engine.get_entity_history("FLOW_1", dataset="unsw")
    assert unsw_hist["history_type"] == "ORDERED_HISTORY"
    assert unsw_hist["temporal_semantics"] == TemporalSemantics.SEQUENCE_ORDER_SURROGATE
    assert unsw_hist["total_events"] == 1


def test_profile_strictly_before_or_at_pivot(engine):
    """Verifies that behavioral profiles use strictly past events (<= pivot)."""
    evts = engine.events_for_entity("SO_10661", dataset="stackoverflow")
    assert len(evts) >= 10
    pivot_evt = evts[5]
    pivot_epoch = pivot_evt["epoch_time"]

    prof = engine.build_profile("SO_10661", pivot=pivot_epoch, dataset="stackoverflow")
    assert prof["event_count_before_pivot"] == 6  # index 0 to 5 inclusive
    assert prof["historical_statistics"]["last_seen_epoch"] <= pivot_epoch


def test_future_leakage_invariance_under_appended_extreme_anomaly(engine):
    """
    CRITICAL PROOF: Appending extreme anomalous events strictly in the future
    MUST NOT alter the profile computed at pivot P.
    """
    evts = engine.events_for_entity("SO_10661", dataset="stackoverflow")
    pivot_evt = evts[10]
    pivot_epoch = pivot_evt["epoch_time"]

    # Profile 1: Computed before future tampering
    prof_before = engine.build_profile("SO_10661", pivot=pivot_epoch, dataset="stackoverflow")

    # Tamper with future: Add extreme future events
    future_anomaly = {
        "event_id": "EVT_FUTURE_EXTREME_ANOMALY",
        "actor_id": "SO_10661",
        "target_id": "SO_UNKNOWN_TARGET_9999",
        "amount": 1000000.0,
        "epoch_time": pivot_epoch + 100000.0,
        "timestamp": "2029-01-01T00:00:00+00:00",
        "source_domain": "SOCIAL",
        "temporal_semantics": TemporalSemantics.OBSERVED_TIMESTAMP,
        "sha256_hash": "deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
        "attributes": json.dumps({"interaction_type": "extreme_surge"})
    }

    # Inject into in-memory dataset
    engine.datasets["stackoverflow"] = pd.concat([
        engine.datasets["stackoverflow"],
        pd.DataFrame([future_anomaly])
    ], ignore_index=True)

    # Profile 2: Computed after future tampering
    prof_after = engine.build_profile("SO_10661", pivot=pivot_epoch, dataset="stackoverflow")

    # Invariance Assertions
    assert prof_before["event_count_before_pivot"] == prof_after["event_count_before_pivot"]
    assert prof_before["frequency_per_hour"] == prof_after["frequency_per_hour"]
    assert prof_before["counterparty_count"] == prof_after["counterparty_count"]
    assert prof_before["burstiness_index"] == prof_after["burstiness_index"]
    assert prof_before["domain_mix"] == prof_after["domain_mix"]
    assert prof_before["historical_statistics"] == prof_after["historical_statistics"]


def test_pivot_deviation_analysis(engine):
    """Verifies that analyze_pivot detects deviations with baseline, observed, score, and evidence."""
    evts = engine.events_for_entity("SO_10661", dataset="stackoverflow")
    assert len(evts) >= 10
    pivot_evt = evts[8]

    res = engine.analyze_pivot("SO_10661", pivot_event_id=pivot_evt["event_id"], dataset="stackoverflow")
    assert res["entity_id"] == "SO_10661"
    assert res["pivot_event_id"] == pivot_evt["event_id"]
    assert len(res["deviations"]) > 0

    for dev in res["deviations"]:
        assert "metric" in dev
        assert "baseline" in dev
        assert "observed" in dev
        assert "score" in dev
        assert "evidence_ref" in dev
        assert dev["evidence_ref"].startswith("hash:")


def test_observed_timestamp_range_queries_and_surrogate_rejection(engine):
    """Verifies events_between works for observed timestamps and fails closed for surrogate datasets."""
    # Stack Overflow: Valid range query
    evts_so = engine.events_between(
        "SO_10661",
        start="2008-09-01T00:00:00Z",
        end="2008-10-01T00:00:00Z",
        dataset="stackoverflow"
    )
    assert len(evts_so) > 0
    for e in evts_so:
        assert 1220227200.0 <= e["epoch_time"] <= 1222819200.0

    # UNSW: Must strictly reject date-range queries
    with pytest.raises(ValueError) as exc_info:
        engine.events_between(
            "FLOW_1",
            start="2015-01-01T00:00:00Z",
            end="2015-02-01T00:00:00Z",
            dataset="unsw"
        )
    assert "Date-range queries are unsupported" in str(exc_info.value)
    assert "SEQUENCE_ORDER_SURROGATE" in str(exc_info.value)


def test_backtracking_and_forwardtracking_semantics(engine):
    """Verifies backtracking and forward tracking preserve language safety and temporal semantics."""
    # 1. Stack Overflow
    bt_so = engine.backtrack("SO_10661", pivot=1222200212.0, dataset="stackoverflow")
    assert bt_so["query"] == "BACKTRACK"
    assert bt_so["analysis_type"] == "REAL_TIME_TEMPORAL_ANALYSIS"
    assert bt_so["temporal_semantics"] == TemporalSemantics.OBSERVED_TIMESTAMP
    for pred in bt_so["ordered_predecessors"]:
        assert pred["epoch_time"] < 1222200212.0

    ft_so = engine.forwardtrack("SO_10661", pivot=1222200212.0, dataset="stackoverflow")
    assert ft_so["query"] == "FORWARDTRACK"
    assert ft_so["history_scope"] == "OBSERVED_FUTURE_HISTORY"
    for succ in ft_so["ordered_successors"]:
        assert succ["epoch_time"] > 1222200212.0

    # 2. UNSW Surrogate
    bt_unsw = engine.backtrack("FLOW_1", pivot=1421980001.5, dataset="unsw")
    assert bt_unsw["query"] == "ORDER_BACKTRACK"
    assert bt_unsw["analysis_type"] == "SEQUENCE_ORDER_ANALYSIS"
    assert bt_unsw["temporal_semantics"] == TemporalSemantics.SEQUENCE_ORDER_SURROGATE

    ft_unsw = engine.forwardtrack("FLOW_1", pivot=0.0, dataset="unsw")
    assert ft_unsw["query"] == "ORDER_FORWARD_TRACK"
    assert ft_unsw["analysis_type"] == "SEQUENCE_ORDER_ANALYSIS"
    assert ft_unsw["history_scope"] == "OBSERVED_FUTURE_HISTORY"


def test_temporal_path_monotonicity_and_constraints(engine):
    """Verifies temporal path discovery enforces non-decreasing ordering, max_hops, and cycle avoidance."""
    paths_res = engine.find_temporal_paths("SO_10661", "SO_28098", dataset="stackoverflow", max_hops=3)
    assert paths_res["paths_count"] > 0
    assert paths_res["temporal_semantics"] == TemporalSemantics.OBSERVED_TIMESTAMP

    for p in paths_res["paths"]:
        assert p["temporal_monotonic"] is True
        seq = p["sequence"]
        assert len(seq) <= 3
        for i in range(len(seq) - 1):
            assert seq[i]["epoch_time"] <= seq[i + 1]["epoch_time"], "Path violated temporal non-decreasing ordering!"

    # Disconnected entities should return 0 paths without error
    disc_res = engine.find_temporal_paths("SO_10661", "SO_NONEXISTENT_NODE_9999", dataset="stackoverflow")
    assert disc_res["paths_count"] == 0
    assert disc_res["paths"] == []


def test_identity_bridge_immutability():
    """Verifies that identity_bridge.parquet is strictly read-only and detects tampering."""
    # 1. Normal load succeeds
    df = load_identity_bridge_readonly("data/cases/identity_bridge.parquet")
    assert not df.empty
    assert "case_id" in df.columns

    # 2. Simulated mutation fails closed
    with open("data/cases/identity_bridge.parquet", "rb") as f:
        content = f.read()

    # Tampered file in temporary path
    tampered_path = "output/tampered_bridge.parquet"
    with open(tampered_path, "wb") as f:
        f.write(content + b"\x00")

    try:
        with pytest.raises(ValueError) as exc_info:
            load_identity_bridge_readonly(tampered_path)
        assert "MUTATION DETECTED" in str(exc_info.value)
    finally:
        if os.path.exists(tampered_path):
            os.remove(tampered_path)


def test_zero_fabricated_evidence_and_traceability(engine):
    """Verifies that every event produced by the engine has a legitimate backing source record."""
    so_evts = engine.events_for_entity("SO_10661", dataset="stackoverflow")
    assert len(so_evts) > 0
    for e in so_evts[:10]:
        assert e["sha256_hash"] is not None
        assert len(e["sha256_hash"]) == 64
        attrs = json.loads(e["attributes"]) if isinstance(e["attributes"], str) else e["attributes"]
        assert "source_sha256" in attrs
        assert attrs["source_sha256"] == "10808eb3e092d29e2b93a15de4b8782e009d48fe3d23477f4b173c62399dafc2"
        assert "source_row_index" in attrs


def test_blind_unsupervised_inference_no_ground_truth():
    """Verifies that during AutoDiscovery, ground-truth label columns are strictly inaccessible."""
    disc = AutoDiscoveryEngine()
    cases = disc.scan_dataset("stackoverflow", risk_threshold=0.35, max_cases=5)
    assert len(cases) > 0

    for c in cases:
        assert "is_attack_ground_truth" not in c
        assert "attack_category" not in c
        assert "crime_label" not in c
        assert "ground_truth" not in c
