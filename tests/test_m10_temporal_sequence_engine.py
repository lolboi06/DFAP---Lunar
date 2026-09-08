# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: M10 Temporal Sequence Engine — Lean Verification Suite

import copy
import hashlib
import random
import pytest
import pandas as pd
from typing import Dict, Any, List

from dfap.investigation.workspace import InvestigationWorkspaceBackend
from dfap.investigation.copilot import InvestigationCopilot
from dfap.investigation.temporal_sequence import (
    TemporalSequenceEngine,
    TemporalSequence,
    TemporalSequenceItem,
    TemporalWindowType,
    OrderingBasis,
    TemporalSequenceFeatures,
    TemporalTransition,
    MotifMatch,
    SequencePhase,
)
from dfap.wp4.cli import handle_m13_command

TEST_ENTITY = "ENT_M10_TEST_USER"
PIVOT_T = 1700000000.0


def _sha(val: str) -> str:
    return hashlib.sha256(val.encode("utf-8")).hexdigest()


@pytest.fixture
def sample_events():
    T = PIVOT_T
    return [
        {
            "event_id": "EVT_01",
            "actor_id": TEST_ENTITY,
            "target_id": "DEST_A",
            "timestamp": pd.to_datetime(T - 500, unit="s", utc=True).isoformat(),
            "epoch_time": T - 500,
            "event_type": "LOGIN",
            "source_domain": "AUTH",
            "sha256_hash": _sha("EVT_01"),
            "evidence_ref": "EVD_01",
        },
        {
            "event_id": "EVT_02",
            "actor_id": TEST_ENTITY,
            "target_id": "DEST_B",
            "timestamp": pd.to_datetime(T - 300, unit="s", utc=True).isoformat(),
            "epoch_time": T - 300,
            "event_type": "TRANSFER",
            "source_domain": "FINANCIAL",
            "sha256_hash": _sha("EVT_02"),
            "evidence_ref": "EVD_02",
        },
        {
            "event_id": "EVT_03",
            "actor_id": TEST_ENTITY,
            "target_id": "DEST_C",
            "timestamp": pd.to_datetime(T - 100, unit="s", utc=True).isoformat(),
            "epoch_time": T - 100,
            "event_type": "MESSAGE",
            "source_domain": "COMMUNICATION",
            "sha256_hash": _sha("EVT_03"),
            "evidence_ref": "EVD_03",
        },
        {
            "event_id": "EVT_04",
            "actor_id": TEST_ENTITY,
            "target_id": "DEST_D",
            "timestamp": pd.to_datetime(T, unit="s", utc=True).isoformat(),
            "epoch_time": T,
            "event_type": "ALERT",
            "source_domain": "SECURITY",
            "sha256_hash": _sha("EVT_04"),
            "evidence_ref": "EVD_04",
        },
        {
            "event_id": "EVT_05",
            "actor_id": TEST_ENTITY,
            "target_id": "DEST_E",
            "timestamp": pd.to_datetime(T + 200, unit="s", utc=True).isoformat(),
            "epoch_time": T + 200,
            "event_type": "TRANSFER",
            "source_domain": "FINANCIAL",
            "sha256_hash": _sha("EVT_05"),
            "evidence_ref": "EVD_05",
        },
    ]


def test_deterministic_ordering_independent_of_input_rows(sample_events):
    """
    Test 1: Input permutation invariance.
    Regardless of input row order, the engine must produce an identical sequence.
    """
    engine = TemporalSequenceEngine()
    baseline_seq = engine.build_sequence(sample_events, canonical_entity_id=TEST_ENTITY)
    expected_ids = [it.event_id for it in baseline_seq.items]

    for seed in [42, 1337, 2026, 9999]:
        shuffled = copy.deepcopy(sample_events)
        random.seed(seed)
        random.shuffle(shuffled)

        seq = engine.build_sequence(shuffled, canonical_entity_id=TEST_ENTITY)
        result_ids = [it.event_id for it in seq.items]

        assert result_ids == expected_ids
        for i, item in enumerate(seq.items):
            assert item.sequence_index == i
            assert item.time_delta_from_previous == baseline_seq.items[i].time_delta_from_previous


def test_future_event_excluded_from_pre_trigger_history(sample_events):
    """
    Test 2: Strict causal pre-trigger history (zero future leakage).
    Events with t > T or index > trigger_index must never appear in pre-trigger history.
    """
    engine = TemporalSequenceEngine()
    seq = engine.build_sequence(sample_events, canonical_entity_id=TEST_ENTITY)

    # EVT_04 is at trigger time T
    trigger_item = next(it for it in seq.items if it.event_id == "EVT_04")
    pre_items = engine.get_pre_trigger_sequence(seq, trigger_event=trigger_item)

    pre_ids = [it.event_id for it in pre_items]
    assert pre_ids == ["EVT_01", "EVT_02", "EVT_03"]
    assert "EVT_04" not in pre_ids
    assert "EVT_05" not in pre_ids

    # Every item must strictly precede T
    for it in pre_items:
        assert it.epoch_time < trigger_item.epoch_time
        assert it.sequence_index < trigger_item.sequence_index


def test_equal_timestamp_excluded_without_authoritative_sequence():
    """
    Test 3: Equal-timestamp collision without sequence proof is excluded / marked UNRESOLVED.
    Never infer order from row position or arbitrary heuristics.
    """
    T = PIVOT_T
    events = [
        {
            "event_id": "EVT_PRIOR",
            "actor_id": TEST_ENTITY,
            "target_id": "DEST_A",
            "epoch_time": T - 10,
            "timestamp": pd.to_datetime(T - 10, unit="s", utc=True).isoformat(),
        },
        {
            "event_id": "EVT_TRIG",
            "actor_id": TEST_ENTITY,
            "target_id": "DEST_B",
            "epoch_time": T,
            "timestamp": pd.to_datetime(T, unit="s", utc=True).isoformat(),
        },
        {
            "event_id": "EVT_COLLISION",
            "actor_id": TEST_ENTITY,
            "target_id": "DEST_C",
            "epoch_time": T,
            "timestamp": pd.to_datetime(T, unit="s", utc=True).isoformat(),
        },
    ]

    engine = TemporalSequenceEngine()
    seq = engine.build_sequence(events, canonical_entity_id=TEST_ENTITY)

    # Ordering basis must reflect unresolved tie
    assert seq.ordering_basis == OrderingBasis.UNRESOLVED
    assert len(seq.unresolved_ties) > 0

    # In pre-trigger history for EVT_TRIG, the concurrent unsequenced collision must be excluded
    trigger_item = next(it for it in seq.items if it.event_id == "EVT_TRIG")
    pre_items = engine.get_pre_trigger_sequence(seq, trigger_event=trigger_item)

    pre_ids = [it.event_id for it in pre_items]
    assert "EVT_COLLISION" not in pre_ids
    assert pre_ids == ["EVT_PRIOR"]


def test_equal_timestamp_ordered_with_authoritative_sequence():
    """
    Test 4: Equal timestamps with authoritative sequence numbers are ordered deterministically.
    """
    T = PIVOT_T
    events = [
        {
            "event_id": "EVT_SEQ1",
            "actor_id": TEST_ENTITY,
            "target_id": "DEST_A",
            "epoch_time": T,
            "sequence_number": 1,
            "timestamp": pd.to_datetime(T, unit="s", utc=True).isoformat(),
        },
        {
            "event_id": "EVT_SEQ2_TRIG",
            "actor_id": TEST_ENTITY,
            "target_id": "DEST_B",
            "epoch_time": T,
            "sequence_number": 2,
            "timestamp": pd.to_datetime(T, unit="s", utc=True).isoformat(),
        },
        {
            "event_id": "EVT_SEQ3",
            "actor_id": TEST_ENTITY,
            "target_id": "DEST_C",
            "epoch_time": T,
            "sequence_number": 3,
            "timestamp": pd.to_datetime(T, unit="s", utc=True).isoformat(),
        },
    ]

    engine = TemporalSequenceEngine()
    seq = engine.build_sequence(events, canonical_entity_id=TEST_ENTITY)

    assert seq.ordering_basis == OrderingBasis.AUTHORITATIVE_SEQUENCE
    assert len(seq.unresolved_ties) == 0

    trigger_item = next(it for it in seq.items if it.event_id == "EVT_SEQ2_TRIG")
    pre_items = engine.get_pre_trigger_sequence(seq, trigger_event=trigger_item)

    pre_ids = [it.event_id for it in pre_items]
    assert pre_ids == ["EVT_SEQ1"]
    assert "EVT_SEQ3" not in pre_ids


def test_temporal_windows_tight_moderate_broad():
    """
    Test 5: Canonical windowing:
    - TIGHT (3600s)
    - MODERATE (86400s)
    - BROAD (604800s)
    """
    T = PIVOT_T
    events = [
        {"event_id": "E_TIGHT", "actor_id": TEST_ENTITY, "epoch_time": T - 1800},         # 30 min ago
        {"event_id": "E_MOD", "actor_id": TEST_ENTITY, "epoch_time": T - 10000},          # ~2.8 hrs ago
        {"event_id": "E_BROAD", "actor_id": TEST_ENTITY, "epoch_time": T - 200000},       # ~2.3 days ago
        {"event_id": "E_OUTSIDE", "actor_id": TEST_ENTITY, "epoch_time": T - 1000000},     # ~11.5 days ago
        {"event_id": "E_TRIG", "actor_id": TEST_ENTITY, "epoch_time": T},
    ]

    engine = TemporalSequenceEngine()
    seq = engine.build_sequence(events, canonical_entity_id=TEST_ENTITY)
    trig = next(it for it in seq.items if it.event_id == "E_TRIG")

    windows = engine.generate_windows(seq, trigger_event=trig)

    tight_ids = [it.event_id for it in windows["PRE_TIGHT"]]
    mod_ids = [it.event_id for it in windows["PRE_MODERATE"]]
    broad_ids = [it.event_id for it in windows["PRE_BROAD"]]

    assert tight_ids == ["E_TIGHT"]
    assert mod_ids == ["E_MOD", "E_TIGHT"]
    assert broad_ids == ["E_BROAD", "E_MOD", "E_TIGHT"]
    assert "E_OUTSIDE" not in broad_ids


def test_entity_and_case_isolation():
    """
    Test 6: Entity and case isolation.
    Mixing foreign entities or cases must fail sequence validation.
    """
    T = PIVOT_T
    mixed_events = [
        {"event_id": "E1", "actor_id": TEST_ENTITY, "epoch_time": T - 20, "case_id": "CASE_1"},
        {"event_id": "E2", "actor_id": "ENT_FOREIGN_ATTACKER", "epoch_time": T - 10, "case_id": "CASE_1"},
        {"event_id": "E3", "actor_id": TEST_ENTITY, "epoch_time": T, "case_id": "CASE_2"},
    ]

    engine = TemporalSequenceEngine()
    seq = engine.build_sequence(mixed_events, canonical_entity_id=TEST_ENTITY, case_id="CASE_1")

    val_report = engine.validate_sequence(seq)
    assert not val_report["is_valid"]
    assert any("Entity mismatch" in issue for issue in val_report["issues"])
    assert any("Case mismatch" in issue for issue in val_report["issues"])


def test_m13_workspace_sequence_integration():
    """
    Test 7: M13 Workspace backend integration.
    backend.build_temporal_sequence returns a certified TemporalSequence.
    """
    backend = InvestigationWorkspaceBackend()
    T = PIVOT_T
    events = [
        {"event_id": "EVT_M13_1", "actor_id": TEST_ENTITY, "epoch_time": T - 100, "timestamp": "2023-11-14T22:11:40Z"},
        {"event_id": "EVT_M13_2", "actor_id": TEST_ENTITY, "epoch_time": T - 50, "timestamp": "2023-11-14T22:12:30Z"},
        {"event_id": "EVT_M13_3", "actor_id": TEST_ENTITY, "epoch_time": T, "timestamp": "2023-11-14T22:13:20Z"},
    ]
    backend.set_live_stream_events(events)

    seq = backend.build_temporal_sequence(TEST_ENTITY)
    assert isinstance(seq, TemporalSequence)
    assert len(seq.items) >= 3
    assert seq.canonical_entity_id == TEST_ENTITY
    assert seq.is_causally_valid is True

    # Verify summary generation
    summary = backend.temporal_sequence_engine.summarize_sequence(seq, trigger_event=seq.items[-1])
    assert summary["trigger_event"]["event_id"] == "EVT_M13_3"
    assert len(summary["preceding_history"]) == 2


def test_m14_copilot_temporal_pre_trigger_query():
    """
    Test 8: M14 Copilot temporal pre-trigger query handling.
    Copilot must answer 'What happened before this event?' with grounded pre-trigger sequence.
    """
    backend = InvestigationWorkspaceBackend()
    T = PIVOT_T
    events = [
        {
            "event_id": "EVT_COPILOT_1",
            "actor_id": TEST_ENTITY,
            "target_id": "DEST_X",
            "epoch_time": T - 120,
            "timestamp": "2023-11-14T22:11:20Z",
            "event_type": "LOGIN",
            "source_domain": "AUTH",
            "sha256_hash": _sha("C1"),
            "evidence_ref": "EVD_COPILOT_1",
        },
        {
            "event_id": "EVT_COPILOT_2",
            "actor_id": TEST_ENTITY,
            "target_id": "DEST_Y",
            "epoch_time": T - 60,
            "timestamp": "2023-11-14T22:12:20Z",
            "event_type": "API_KEY_ROTATION",
            "source_domain": "IAM",
            "sha256_hash": _sha("C2"),
            "evidence_ref": "EVD_COPILOT_2",
        },
        {
            "event_id": "EVT_COPILOT_TRIG",
            "actor_id": TEST_ENTITY,
            "target_id": "DEST_Z",
            "epoch_time": T,
            "timestamp": "2023-11-14T22:13:20Z",
            "event_type": "UNAUTHORIZED_EXPORT",
            "source_domain": "SECURITY",
            "sha256_hash": _sha("C_TRIG"),
            "evidence_ref": "EVD_COPILOT_TRIG",
        },
        {
            "event_id": "EVT_COPILOT_FUTURE",
            "actor_id": TEST_ENTITY,
            "target_id": "DEST_W",
            "epoch_time": T + 100,
            "timestamp": "2023-11-14T22:15:00Z",
            "event_type": "LOGOUT",
            "source_domain": "AUTH",
            "sha256_hash": _sha("C_FUTURE"),
            "evidence_ref": "EVD_COPILOT_FUTURE",
        },
    ]
    backend.set_live_stream_events(events)

    copilot = InvestigationCopilot(backend)
    resp = copilot.ask("What happened before this event? EVT_COPILOT_TRIG", entity_id=TEST_ENTITY)

    assert resp["status"] == "GROUNDED"
    assert resp["confidence"] >= 0.85
    assert "EVD_COPILOT_1" in resp["evidence_refs"]
    assert "EVD_COPILOT_2" in resp["evidence_refs"]
    assert "EVD_COPILOT_FUTURE" not in resp["evidence_refs"]

    # Verify zero future leakage in claims and limitations
    assert any("zero future leakage" in str(lim).lower() for lim in resp["limitations"])
    assert any("preceding event" in str(cl.get("claim", "")).lower() for cl in resp["claims"])


def test_sequence_feature_extraction(sample_events):
    """Test deterministic sequence feature extraction."""
    engine = TemporalSequenceEngine()
    seq = engine.build_sequence(sample_events, canonical_entity_id=TEST_ENTITY)
    features = engine.extract_features(seq)

    assert isinstance(features, TemporalSequenceFeatures)
    assert features.sequence_length == len(sample_events)
    assert features.unique_event_types == 4  # LOGIN, TRANSFER, MESSAGE, ALERT
    assert features.unique_domains == 4      # AUTH, FINANCIAL, COMMUNICATION, SECURITY
    assert features.min_inter_event_gap >= 0.0
    assert features.max_inter_event_gap >= features.min_inter_event_gap
    assert features.mean_inter_event_time > 0.0
    assert features.cross_domain_transition_count >= 1

    d = features.to_dict()
    assert isinstance(d, dict)
    assert d["sequence_length"] == len(sample_events)


def test_temporal_transition_analysis(sample_events):
    """Test event-to-event and domain-to-domain transition analysis."""
    engine = TemporalSequenceEngine()
    seq = engine.build_sequence(sample_events, canonical_entity_id=TEST_ENTITY)
    transitions = engine.analyze_transitions(seq)

    assert "event_transitions" in transitions
    assert "domain_transitions" in transitions
    assert "domain_to_event" in transitions

    ev_trans = transitions["event_transitions"]
    assert len(ev_trans) >= 1
    login_trans = next((t for t in ev_trans if t.source_event_type == "LOGIN" and t.target_event_type == "TRANSFER"), None)
    assert login_trans is not None
    assert isinstance(login_trans, TemporalTransition)
    assert login_trans.count >= 1
    assert login_trans.evidence_refs

    graph = engine.build_transition_graph(seq)
    assert "nodes" in graph
    assert "edges" in graph
    assert len(graph["nodes"]) > 0


def test_pattern_and_motif_detection():
    """Test repeated pattern detection and behavioral motifs."""
    engine = TemporalSequenceEngine()
    T = PIVOT_T
    motif_events = [
        {"event_id": "M0", "epoch_time": T - 100, "timestamp": "2023-11-14T22:00:00Z", "event_type": "LOGIN", "source_domain": "AUTH", "sha256_hash": _sha("M0"), "evidence_ref": "E_M0"},
        {"event_id": "M1", "epoch_time": T - 80, "timestamp": "2023-11-14T22:00:20Z", "event_type": "PERMISSION_CHANGE", "source_domain": "IAM", "sha256_hash": _sha("M1"), "evidence_ref": "E_M1"},
        {"event_id": "M2", "epoch_time": T - 60, "timestamp": "2023-11-14T22:00:40Z", "event_type": "TRANSFER", "source_domain": "FINANCIAL", "sha256_hash": _sha("M2"), "evidence_ref": "E_M2"},
        {"event_id": "M3", "epoch_time": T - 40, "timestamp": "2023-11-14T22:01:00Z", "event_type": "LOGIN", "source_domain": "AUTH", "sha256_hash": _sha("M3"), "evidence_ref": "E_M3"},
        {"event_id": "M4", "epoch_time": T - 20, "timestamp": "2023-11-14T22:01:20Z", "event_type": "PERMISSION_CHANGE", "source_domain": "IAM", "sha256_hash": _sha("M4"), "evidence_ref": "E_M4"},
        {"event_id": "M5", "epoch_time": T, "timestamp": "2023-11-14T22:01:40Z", "event_type": "TRANSFER", "source_domain": "FINANCIAL", "sha256_hash": _sha("M5"), "evidence_ref": "E_M5"},
    ]
    seq = engine.build_sequence(motif_events, canonical_entity_id=TEST_ENTITY)

    # Detect repeated n-grams
    patterns = engine.detect_patterns(seq, min_len=2, max_len=3, min_count=2)
    assert len(patterns) >= 1
    p0 = patterns[0]
    assert p0["count"] >= 2
    assert p0["evidence_refs"]

    # Detect motifs
    motifs = engine.detect_motifs(seq)
    motif_types = [m.motif_type for m in motifs]
    assert "ACCESS_CHANGE_TRANSFER" in motif_types
    match = next(m for m in motifs if m.motif_type == "ACCESS_CHANGE_TRANSFER")
    assert match.fit_score == 1.0
    assert len(match.matching_event_ids) == 3
    assert len(match.evidence_refs) == 3


def test_sequence_comparison_edit_distance_and_dtw(sample_events):
    """Test normalized edit distance and DTW distance comparison."""
    engine = TemporalSequenceEngine()
    seq_a = engine.build_sequence(sample_events, canonical_entity_id="USER_A")

    # Sequence B identical to A
    res_identical = engine.compare_sequences(seq_a, seq_a)
    assert res_identical["edit_distance"] == 0
    assert res_identical["edit_distance_normalized"] == 0.0
    assert res_identical["dtw_distance"] == 0.0
    assert res_identical["alignment_similarity"] == 1.0

    # Sequence C different
    c_events = [
        {"event_id": "C1", "epoch_time": 100.0, "timestamp": "2023-11-14T00:00:00Z", "event_type": "EXPORT", "source_domain": "STORAGE", "sha256_hash": _sha("C1")},
        {"event_id": "C2", "epoch_time": 200.0, "timestamp": "2023-11-14T00:01:00Z", "event_type": "DELETE", "source_domain": "STORAGE", "sha256_hash": _sha("C2")},
    ]
    seq_c = engine.build_sequence(c_events, canonical_entity_id="USER_C")
    res_diff = engine.compare_sequences(seq_a, seq_c)
    assert res_diff["edit_distance"] > 0
    assert res_diff["edit_distance_normalized"] > 0.0
    assert res_diff["alignment_similarity"] < 1.0


def test_sequence_phasing_and_compression():
    """Test rule-based sequence phasing and compression by temporal gap."""
    engine = TemporalSequenceEngine()
    burst_events = [
        # Cluster 1: 3 events spaced by 2s
        {"event_id": "B1", "epoch_time": 1000.0, "timestamp": "2023-11-14T00:00:00Z", "event_type": "QUERY", "source_domain": "API", "sha256_hash": _sha("B1"), "evidence_ref": "EB1"},
        {"event_id": "B2", "epoch_time": 1002.0, "timestamp": "2023-11-14T00:00:02Z", "event_type": "QUERY", "source_domain": "API", "sha256_hash": _sha("B2"), "evidence_ref": "EB2"},
        {"event_id": "B3", "epoch_time": 1004.0, "timestamp": "2023-11-14T00:00:04Z", "event_type": "QUERY", "source_domain": "API", "sha256_hash": _sha("B3"), "evidence_ref": "EB3"},
        # Gap of 400 seconds (> 300 default)
        # Cluster 2: 2 events spaced by 5s
        {"event_id": "B4", "epoch_time": 1404.0, "timestamp": "2023-11-14T00:06:44Z", "event_type": "TRANSFER", "source_domain": "FINANCIAL", "sha256_hash": _sha("B4"), "evidence_ref": "EB4"},
        {"event_id": "B5", "epoch_time": 1409.0, "timestamp": "2023-11-14T00:06:49Z", "event_type": "TRANSFER", "source_domain": "FINANCIAL", "sha256_hash": _sha("B5"), "evidence_ref": "EB5"},
    ]
    seq = engine.build_sequence(burst_events, canonical_entity_id=TEST_ENTITY)
    phases = engine.compress_phases(seq, gap_threshold_seconds=100.0)

    assert len(phases) == 2
    assert phases[0].event_count == 3
    assert phases[0].domains == ["API"]
    assert phases[1].event_count == 2
    assert phases[1].domains == ["FINANCIAL"]
    assert phases[0].evidence_refs == ["EB1", "EB2", "EB3"]
    assert phases[1].evidence_refs == ["EB4", "EB5"]


def test_m13_m14_and_cli_sequence_integration(tmp_path):
    """Test M13 backend wrapper, M14 copilot queries, and CLI sequence commands."""
    backend = InvestigationWorkspaceBackend(output_dir=str(tmp_path))
    T = PIVOT_T
    events = [
        {"event_id": "E1", "actor_id": TEST_ENTITY, "epoch_time": T - 200, "timestamp": "2023-11-14T22:00:00Z", "event_type": "LOGIN", "source_domain": "AUTH", "sha256_hash": _sha("E1"), "evidence_ref": "EV_E1"},
        {"event_id": "E2", "actor_id": TEST_ENTITY, "epoch_time": T - 100, "timestamp": "2023-11-14T22:01:40Z", "event_type": "PERMISSION_CHANGE", "source_domain": "IAM", "sha256_hash": _sha("E2"), "evidence_ref": "EV_E2"},
        {"event_id": "E3", "actor_id": TEST_ENTITY, "epoch_time": T, "timestamp": "2023-11-14T22:03:20Z", "event_type": "TRANSFER", "source_domain": "FINANCIAL", "sha256_hash": _sha("E3"), "evidence_ref": "EV_E3"},
        {"event_id": "E4", "actor_id": TEST_ENTITY, "epoch_time": T + 50, "timestamp": "2023-11-14T22:04:10Z", "event_type": "LOGOUT", "source_domain": "AUTH", "sha256_hash": _sha("E4"), "evidence_ref": "EV_E4"},
    ]
    backend.set_live_stream_events(events)

    # 1. Copilot question: What happened after this event?
    copilot = InvestigationCopilot(backend)
    post_resp = copilot.ask("What happened after this event? E3", entity_id=TEST_ENTITY)
    assert post_resp["status"] == "GROUNDED"
    assert "EV_E4" in post_resp["evidence_refs"]
    assert "EV_E1" not in post_resp["evidence_refs"]
    assert any("zero future leakage" in str(l).lower() for l in post_resp["limitations"])

    # 2. Copilot question: What patterns occurred around this trigger?
    pattern_resp = copilot.ask("What patterns occurred around this trigger?", entity_id=TEST_ENTITY)
    assert pattern_resp["status"] in {"GROUNDED", "INSUFFICIENT_EVIDENCE"}
    assert "patterns" in pattern_resp["answer"].lower() or "motifs" in pattern_resp["answer"].lower()

    # 3. Copilot question: What are the major phases of activity?
    phase_resp = copilot.ask("What are the major phases of activity?", entity_id=TEST_ENTITY)
    assert phase_resp["status"] == "GROUNDED"
    assert "phase" in phase_resp["answer"].lower()

    # 4. CLI sequence commands
    out_seq = handle_m13_command(backend, f"sequence {TEST_ENTITY}")
    assert "SEQUENCE TIMELINE" in out_seq
    assert "E1" in out_seq

    out_feat = handle_m13_command(backend, f"sequence features {TEST_ENTITY}")
    assert "SEQUENCE FEATURES" in out_feat
    assert "sequence_length" in out_feat

    out_trans = handle_m13_command(backend, f"sequence transitions {TEST_ENTITY}")
    assert "SEQUENCE TRANSITIONS" in out_trans

    out_phases = handle_m13_command(backend, f"sequence phases {TEST_ENTITY}")
    assert "SEQUENCE PHASES" in out_phases

    out_patterns = handle_m13_command(backend, f"sequence patterns {TEST_ENTITY}")
    assert "SEQUENCE PATTERNS" in out_patterns

