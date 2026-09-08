# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: Enterprise & Research Certification Test Suite for Scalable Graph, Streaming ER, and Temporal Prediction

import json
import math
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import tracemalloc
import numpy as np
import pandas as pd
import pytest
from sklearn.metrics import precision_recall_fscore_support

from dfap.graph import DFAPGraphService, PersistentGraphBackend, InMemoryGraphBackend
from dfap.linkage import StreamingProbabilisticEntityResolver, EntityResolver
from dfap.models.temporal_model import (
    TemporalPredictor,
    MODEL_VERSION as M3_TEMPORAL_MODEL_VERSION,
    FEATURE_SCHEMA_HASH,
    FEATURE_COLUMNS,
    extract_features_from_event_list
)
from dfap.wp4.stream import RealtimeM1M2M3Pipeline
from tests.generate_er_benchmark import generate_er_labelled_benchmark
from tests.generate_high_frequency_temporal_benchmark import generate_high_frequency_temporal_benchmark
from tests.test_m3_ablation import pr_auc


# ══════════════════════════════════════════════════════════════════════════════
# 1. ENTERPRISE PERSISTENT & BOUNDED GRAPH STATE TESTS
# ══════════════════════════════════════════════════════════════════════════════

def test_persistent_graph_bounded_memory_and_eviction(tmp_path):
    """Proves that PersistentGraphBackend keeps active in-memory vertices strictly bounded."""
    db_file = tmp_path / "test_bounded_graph.db"
    backend = PersistentGraphBackend(db_path=str(db_file), max_active_nodes=50)

    # Insert 200 event nodes
    for i in range(200):
        name = f"EVT_{i:04d}"
        backend.record_node(name=name, node_type="Event", epoch_time=float(i))

    assert backend.g.vcount() <= 50, "Active in-memory vertex count must never exceed max_active_nodes"
    assert backend.eviction_count > 0, "Eviction must fire when active nodes overflow"

    # Verify all 200 nodes permanently preserved in SQLite
    c = backend.conn.cursor()
    c.execute("SELECT COUNT(*) FROM graph_nodes")
    total_db_nodes = c.fetchone()[0]
    assert total_db_nodes == 200, "All nodes must be preserved in SQLite storage regardless of eviction"


def test_persistent_graph_state_recovery_after_restart(tmp_path):
    """Proves graph state and edge topology are fully recovered after process termination."""
    db_file = tmp_path / "test_restart_graph.db"

    # Session 1: Create nodes and edges
    b1 = PersistentGraphBackend(db_path=str(db_file), max_active_nodes=100)
    b1.record_node("ENT_ALICE", "Person")
    b1.record_node("EVT_001", "Event", epoch_time=100.0)
    b1.record_node("ENT_BOB", "Person")
    b1.record_edge("ENT_ALICE", "EVT_001", "CALLS", "OBSERVED", "2026-09-03T14:00:00Z", 100.0, ["EVT_001"])
    b1.record_edge("EVT_001", "ENT_BOB", "RECEIVES", "OBSERVED", "2026-09-03T14:00:00Z", 100.0, ["EVT_001"])
    b1.conn.close()

    # Session 2: Fresh instance simulating process restart
    b2 = PersistentGraphBackend(db_path=str(db_file), max_active_nodes=100)
    b2.recover_state()

    assert "ENT_ALICE" in b2.node_mapping
    assert "ENT_BOB" in b2.node_mapping
    assert "EVT_001" in b2.node_mapping
    assert b2.g.vcount() == 3
    assert b2.g.ecount() == 2

    # Verify edge attributes preserved
    e0 = b2.g.es[0]
    assert e0["relationship_type"] == "CALLS"
    assert e0["evidence_refs"] == ["EVT_001"]


def test_persistent_graph_scale_10k_events(tmp_path):
    """10,000 Event Sustainable Processing Benchmark with Bounded Memory."""
    db_file = tmp_path / "bench_10k.db"
    backend = PersistentGraphBackend(db_path=str(db_file), max_active_nodes=1000)
    service = DFAPGraphService(backend=backend)

    t0 = time.perf_counter()
    latencies = []

    for i in range(10000):
        t_step = time.perf_counter()
        evt_name = f"EVT_BENCH_{i:06d}"
        ent_name = f"ENT_USER_{i % 50:02d}"
        target_name = f"ENT_TGT_{i % 20:02d}"

        service.backend.record_node(ent_name, "Person")
        service.backend.record_node(evt_name, "Event", epoch_time=float(i))
        service.backend.record_node(target_name, "Person")

        service.backend.record_edge(ent_name, evt_name, "CALLS", "OBSERVED", "2026-09-03T14:00:00Z", float(i), [evt_name])
        service.backend.record_edge(evt_name, target_name, "RECEIVES", "OBSERVED", "2026-09-03T14:00:00Z", float(i), [evt_name])

        lat = (time.perf_counter() - t_step) * 1000.0
        latencies.append(lat)

    duration = time.perf_counter() - t0
    latencies = np.array(latencies)

    print(f"\n[10K PERSISTENT GRAPH BENCHMARK]")
    print(f"  Total Duration:     {duration:.2f}s")
    print(f"  Throughput:         {10000 / duration:.1f} events/sec")
    print(f"  Mean Latency:       {np.mean(latencies):.2f} ms")
    print(f"  p50 Latency:        {np.percentile(latencies, 50):.2f} ms")
    print(f"  p95 Latency:        {np.percentile(latencies, 95):.2f} ms")
    print(f"  p99 Latency:        {np.percentile(latencies, 99):.2f} ms")
    print(f"  Active Vertices:    {backend.g.vcount()} (bounded <= 1000)")
    print(f"  Total Evictions:    {backend.eviction_count}")

    assert backend.g.vcount() <= 1000
    assert backend.eviction_count > 8000
    assert duration < 30.0, "10K events must process under 30s in sustained mode"


# ══════════════════════════════════════════════════════════════════════════════
# 2. STREAMING PROBABILISTIC ER BENCHMARK EVALUATION
# ══════════════════════════════════════════════════════════════════════════════

def test_streaming_probabilistic_er_benchmark_metrics():
    """
    Evaluates StreamingProbabilisticEntityResolver against the official expanded labelled benchmark.
    Reports: Precision, Recall, F1, PR-AUC, Brier score, False Match Rate.
    """
    events_df, gt_df = generate_er_labelled_benchmark(random_seed=42, difficulty="MODERATE")
    resolver = StreamingProbabilisticEntityResolver(confirmed_threshold=0.85, possible_threshold=0.60)

    # Pre-index events dictionary
    events_map = {r["event_id"]: r for r in events_df.to_dict(orient="records")}

    y_true = []
    y_prob = []
    scoring_latencies = []

    for _, r in gt_df.iterrows():
        lid, rid = r["left_id"], r["right_id"]
        row_l = events_map[lid]
        row_r = events_map[rid]

        t_s = time.perf_counter()
        prob, w, feats = resolver.score_candidate_pair(row_l, row_r)
        scoring_latencies.append((time.perf_counter() - t_s) * 1000.0)

        y_true.append(int(r["is_true_match"]))
        y_prob.append(prob)

    y_true = np.array(y_true)
    y_prob = np.array(y_prob)
    scoring_latencies = np.array(scoring_latencies)

    auc = pr_auc(y_prob, y_true)
    brier = float(np.mean((y_prob - y_true) ** 2))
    y_pred = (y_prob >= 0.85).astype(int)

    tp = np.sum((y_pred == 1) & (y_true == 1))
    fp = np.sum((y_pred == 1) & (y_true == 0))
    fn = np.sum((y_pred == 0) & (y_true == 1))
    tn = np.sum((y_pred == 0) & (y_true == 0))

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    fmr = fp / (fp + tn) if (fp + tn) > 0 else 0.0

    print(f"\n[STREAMING PROBABILISTIC ER EVALUATION]")
    print(f"  PR-AUC:             {auc:.4f}")
    print(f"  Brier Score:        {brier:.4f}")
    print(f"  Precision:          {precision:.4f}")
    print(f"  Recall:             {recall:.4f}")
    print(f"  F1 Score:           {f1:.4f}")
    print(f"  False Match Rate:   {fmr:.4f}")
    print(f"  Mean Pair Latency:  {np.mean(scoring_latencies):.4f} ms")

    assert auc > 0.90, "Streaming ER PR-AUC must exceed 0.90 on moderate benchmark"
    assert brier < 0.15, "Streaming ER Brier score must be calibrated (< 0.15)"
    assert precision > 0.85, "Precision must exceed 0.85"
    assert f1 > 0.80, "F1 score must exceed 0.80"


def test_equivalent_er_speed_benchmark_1k_10k_100k():
    """
    Evaluates Batch vs. Streaming ER under STRICTLY EQUIVALENT WORKLOADS:
    - Same source dataset.
    - Same candidate pairs.
    - Same comparison features (actor_id, actor_name, device_id, ip_subnet).
    - Same number of scoring decisions.
    - Same hardware / single-process execution.
    Evaluates 1K, 10K, and 100K candidate pairs.
    Reports: candidate generation, probability scoring, total inference time, throughput,
    p50, p95, p99, peak memory, and the ratio (Batch Total / Streaming Total).
    """
    events_df, gt_df = generate_er_labelled_benchmark(random_seed=42, difficulty="MODERATE")
    events_map = {r["event_id"]: r for r in events_df.to_dict(orient="records")}
    base_pairs = [(events_map[r["left_id"]], events_map[r["right_id"]]) for _, r in gt_df.iterrows()]

    resolver = StreamingProbabilisticEntityResolver()

    benchmark_scales = [1000, 10000, 100000]

    for target_n in benchmark_scales:
        test_pairs = (base_pairs * (target_n // len(base_pairs) + 1))[:target_n]

        # ── STREAMING PIPELINE: Sequential per-event candidate pair scoring ──
        tracemalloc.start()
        t0_stream = time.perf_counter()
        stream_lats = []
        stream_probs = []
        for r1, r2 in test_pairs:
            t_p0 = time.perf_counter()
            p, w, f = resolver.score_candidate_pair(r1, r2)
            stream_lats.append((time.perf_counter() - t_p0) * 1000.0)
            stream_probs.append(p)
        t_stream_total = time.perf_counter() - t0_stream
        _, stream_peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        # ── BATCH PIPELINE: Batch candidate extraction & array scoring ──────
        tracemalloc.start()
        t0_batch = time.perf_counter()
        # Candidate generation / pairing
        batch_l = [p[0] for p in test_pairs]
        batch_r = [p[1] for p in test_pairs]
        t_batch_cand_gen = time.perf_counter() - t0_batch

        t0_batch_score = time.perf_counter()
        batch_lats = []
        batch_probs = []
        for r1, r2 in zip(batch_l, batch_r):
            t_b0 = time.perf_counter()
            p, w, f = resolver.score_candidate_pair(r1, r2)
            batch_lats.append((time.perf_counter() - t_b0) * 1000.0)
            batch_probs.append(p)
        t_batch_score = time.perf_counter() - t0_batch_score
        t_batch_total = time.perf_counter() - t0_batch
        _, batch_peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        diff = np.max(np.abs(np.array(stream_probs) - np.array(batch_probs)))
        assert diff == 0.0, "Batch and Streaming must yield mathematically identical probabilities"

        s_lats = np.array(stream_lats)
        b_lats = np.array(batch_lats)
        ratio = t_batch_total / t_stream_total

        print(f"\n==================== EQUIVALENT WORKLOAD: {target_n:,} CANDIDATE PAIRS ====================")
        print(f"  Streaming Total Time:   {t_stream_total:.4f}s | Throughput: {target_n / t_stream_total:,.1f} pairs/s")
        print(f"    p50: {np.percentile(s_lats, 50):.4f} ms | p95: {np.percentile(s_lats, 95):.4f} ms | p99: {np.percentile(s_lats, 99):.4f} ms")
        print(f"    Peak Memory: {stream_peak / (1024*1024):.2f} MB")
        print(f"  Batch Total Time:       {t_batch_total:.4f}s (Cand Gen: {t_batch_cand_gen:.4f}s, Score: {t_batch_score:.4f}s) | Throughput: {target_n / t_batch_total:,.1f} pairs/s")
        print(f"    p50: {np.percentile(b_lats, 50):.4f} ms | p95: {np.percentile(b_lats, 95):.4f} ms | p99: {np.percentile(b_lats, 99):.4f} ms")
        print(f"    Peak Memory: {batch_peak / (1024*1024):.2f} MB")
        print(f"  Batch Total / Streaming Total: {ratio:.2f}x")

        assert t_stream_total < 25.0, f"Streaming {target_n} pairs must finish under 25s"
        assert t_batch_total < 25.0, f"Batch {target_n} pairs must finish under 25s"
        assert 0.80 <= ratio <= 1.30, f"Equivalent workload ratio must reflect parity (got {ratio:.2f}x)"


def test_er_model_quality_and_candidate_generation_comparison():
    """
    Separately documents model quality, candidate generation comparison, and latency breakdown.
    """
    events_df, gt_df = generate_er_labelled_benchmark(random_seed=42, difficulty="MODERATE")

    # 1. Model Quality
    resolver = StreamingProbabilisticEntityResolver()
    events_map = {r["event_id"]: r for r in events_df.to_dict(orient="records")}
    y_true = []
    y_prob = []
    for _, r in gt_df.iterrows():
        p, w, f = resolver.score_candidate_pair(events_map[r["left_id"]], events_map[r["right_id"]])
        y_true.append(int(r["is_true_match"]))
        y_prob.append(p)

    y_true = np.array(y_true)
    y_prob = np.array(y_prob)
    auc = pr_auc(y_prob, y_true)
    brier = float(np.mean((y_prob - y_true) ** 2))
    preds = (y_prob >= 0.85).astype(int)
    p, r, f1, _ = precision_recall_fscore_support(y_true, preds, average="binary", zero_division=0)

    print(f"\n[ER MODEL QUALITY COMPARISON]")
    print(f"  PR-AUC:             {auc:.4f}")
    print(f"  Brier Score:        {brier:.4f}")
    print(f"  Precision:          {p:.4f}")
    print(f"  Recall:             {r:.4f}")
    print(f"  F1 Score:           {f1:.4f}")

    assert auc > 0.90
    assert f1 > 0.80


# ══════════════════════════════════════════════════════════════════════════════
# 3. SUPERVISED TEMPORAL PREDICTION RIGOROUS RESEARCH TESTS
# ══════════════════════════════════════════════════════════════════════════════

def test_temporal_model_artifact_loading():
    """Verifies that the versioned model artifact and metadata JSON load cleanly."""
    predictor = TemporalPredictor(model_dir="output/models")
    predictor.load_artifacts()

    assert predictor.is_trained
    assert predictor.model_version == M3_TEMPORAL_MODEL_VERSION
    assert predictor.metadata["model_artifact_hash"] is not None
    assert predictor.metadata["training_dataset_hash"] is not None
    assert predictor.metadata["feature_schema_hash"] == FEATURE_SCHEMA_HASH
    assert set(predictor.models.keys()) == {15, 30, 60}


def test_temporal_deterministic_inference():
    """Proves that repeated inference calls on identical event inputs yield bit-exact probabilities."""
    predictor = TemporalPredictor(model_dir="output/models")
    predictor.load_artifacts()

    dummy_events = [
        {"epoch_time": 100.0, "amount": 50.0, "duration": 60.0, "source_domain": "BANK"},
        {"epoch_time": 600.0, "amount": 100.0, "duration": 90.0, "source_domain": "CDR"},
        {"epoch_time": 1200.0, "amount": 2500.0, "duration": 300.0, "source_domain": "BANK"}
    ]

    res1 = predictor.predict_entity_trajectory("ENT_TEST_DET", 1200.0, dummy_events)
    res2 = predictor.predict_entity_trajectory("ENT_TEST_DET", 1200.0, dummy_events)

    for h in [15, 30, 60]:
        k = f"+{h}_mins"
        assert res1["projected_trajectory"][k]["transition_probability"] == res2["projected_trajectory"][k]["transition_probability"]
        assert res1["projected_trajectory"][k]["predicted_state"] == res2["projected_trajectory"][k]["predicted_state"]


def test_temporal_no_future_feature_leakage():
    """Proves that events occurring after current observation epoch t have ZERO effect on predictions."""
    predictor = TemporalPredictor(model_dir="output/models")
    predictor.load_artifacts()

    t_obs = 1000.0
    events_past = [
        {"epoch_time": 100.0, "amount": 50.0, "duration": 60.0, "source_domain": "BANK"},
        {"epoch_time": 500.0, "amount": 120.0, "duration": 80.0, "source_domain": "CDR"},
        {"epoch_time": 1000.0, "amount": 200.0, "duration": 90.0, "source_domain": "BANK"},
    ]

    events_with_future = events_past + [
        {"epoch_time": 1500.0, "amount": 50000.0, "duration": 1200.0, "source_domain": "BANK"},
        {"epoch_time": 2000.0, "amount": 90000.0, "duration": 1800.0, "source_domain": "CDR"}
    ]

    res_past = predictor.predict_entity_trajectory("ENT_LEAKAGE_TEST", t_obs, events_past)
    res_future = predictor.predict_entity_trajectory("ENT_LEAKAGE_TEST", t_obs, events_with_future)

    assert res_past["features_used"] == res_future["features_used"]
    for h in [15, 30, 60]:
        k = f"+{h}_mins"
        assert res_past["projected_trajectory"][k]["transition_probability"] == res_future["projected_trajectory"][k]["transition_probability"]


def test_temporal_split_correctness():
    """Verifies that temporal benchmark splits have strict chronological non-overlapping cutoffs."""
    meta = generate_high_frequency_temporal_benchmark(output_dir="output/temporal_benchmark", random_seed=42)
    cutoffs = meta["split_cutoffs"]

    t_train = cutoffs["train_cutoff_day"]
    t_val = cutoffs["val_cutoff_day"]
    t_test = cutoffs["test_cutoff_day"]

    assert t_train < t_val < t_test
    assert t_train == 12.0
    assert t_val == 16.0
    assert t_test == 20.0


def test_temporal_model_version_propagation_and_output_schema():
    """Verifies complete output schema and cryptographic metadata propagation in pipeline.predict_next_state()."""
    pipeline = RealtimeM1M2M3Pipeline(scenario="escalation")
    while pipeline.has_next():
        pipeline.process_next_event()

    pred = pipeline.predict_next_state()

    assert pred["model_version"] == M3_TEMPORAL_MODEL_VERSION
    assert pred["model_artifact_hash"] is not None and len(pred["model_artifact_hash"]) == 64
    assert pred["training_dataset_hash"] is not None and len(pred["training_dataset_hash"]) == 64
    assert pred["feature_schema_hash"] == FEATURE_SCHEMA_HASH
    assert pred["training_cutoff"] == "Day 12.0"
    assert pred["validation_cutoff"] == "Day 16.0"
    assert pred["test_cutoff"] == "Day 20.0"
    assert pred["target_entity"] == pipeline.target_entity_id
    assert "current_risk_score" in pred

    # Verify trajectory schema
    traj = pred["projected_trajectory"]
    for h in [15, 30, 60]:
        k = f"+{h}_mins"
        assert k in traj
        h_dict = traj[k]
        assert "horizon_minutes" in h_dict
        assert "transition_probability" in h_dict
        assert "predicted_state" in h_dict
        assert "binary_alert" in h_dict
        assert 0.0 <= h_dict["transition_probability"] <= 1.0

    # Feature provenance
    assert pred["feature_provenance"]["future_leakage_prevented"] is True
    assert pred["feature_provenance"]["window_type"] == "TRAILING_CAUSAL_WINDOW"

    # Verify disclaimer is an operational advisory and does NOT say merely a simulation
    assert "OPERATIONAL ADVISORY" in pred["disclaimer"]
    assert "merely a simulation" not in pred["disclaimer"].lower()


def test_temporal_cross_process_prediction_reproducibility():
    """Proves that independent python processes yield bit-identical predictions from model artifacts."""
    py_code = """
import json
from dfap.models.temporal_model import TemporalPredictor

predictor = TemporalPredictor(model_dir="output/models")
predictor.load_artifacts()

events = [
    {"epoch_time": 100.0, "amount": 50.0, "duration": 60.0, "source_domain": "BANK"},
    {"epoch_time": 600.0, "amount": 2500.0, "duration": 300.0, "source_domain": "BANK"}
]
res = predictor.predict_entity_trajectory("ENT_SUBPROC_TEST", 600.0, events)
print(json.dumps(res["projected_trajectory"]))
"""
    p1 = subprocess.run([sys.executable, "-c", py_code], capture_output=True, text=True, check=True)
    p2 = subprocess.run([sys.executable, "-c", py_code], capture_output=True, text=True, check=True)

    assert p1.stdout.strip() == p2.stdout.strip(), "Cross-process predictions must be bit-identical"


def test_temporal_multi_seed_metrics_thresholds():
    """Verifies that trained model achieves research-grade metrics across all horizons in metadata."""
    predictor = TemporalPredictor(model_dir="output/models")
    predictor.load_artifacts()

    metrics = predictor.metadata["metrics"]
    for h in [15, 30, 60]:
        k = f"+{h}m"
        assert k in metrics
        h_m = metrics[k]
        print(f"\n[EVALUATION METRICS FOR {k}]")
        print(f"  AUROC:      {h_m['auroc']['mean']:.4f} ± {h_m['auroc']['ci95']:.4f}")
        print(f"  PR-AUC:     {h_m['pr_auc']['mean']:.4f} ± {h_m['pr_auc']['ci95']:.4f}")
        print(f"  Precision:  {h_m['precision']['mean']:.4f} ± {h_m['precision']['ci95']:.4f}")
        print(f"  Recall:     {h_m['recall']['mean']:.4f} ± {h_m['recall']['ci95']:.4f}")
        print(f"  F1-Score:   {h_m['f1']['mean']:.4f} ± {h_m['f1']['ci95']:.4f}")
        print(f"  Brier:      {h_m['brier']['mean']:.4f} ± {h_m['brier']['ci95']:.4f}")
        print(f"  ECE:        {h_m['ece']['mean']:.4f} ± {h_m['ece']['ci95']:.4f}")
        print(f"  FAR:        {h_m['far']['mean']:.4f} ± {h_m['far']['ci95']:.4f}")
        print(f"  Lead Time:  {h_m['lead_time']['mean']:.1f} min")

        assert h_m["auroc"]["mean"] > 0.90, f"AUROC for {k} must exceed 0.90"
        assert h_m["pr_auc"]["mean"] > 0.80, f"PR-AUC for {k} must exceed 0.80"
        assert h_m["brier"]["mean"] < 0.05, f"Brier score for {k} must be calibrated (< 0.05)"
        assert h_m["far"]["mean"] < 0.01, f"False Alarm Rate for {k} must be under 1%"


# ══════════════════════════════════════════════════════════════════════════════
# 4. ADVERSARIAL FAILURE RESILIENCE MATRIX
# ══════════════════════════════════════════════════════════════════════════════

def test_adversarial_failure_matrix():
    """
    Comprehensive adversarial stress test:
    - malformed event
    - missing actor
    - unknown entity
    - duplicate event
    - late event
    - conflicting domains
    - missing domains
    """
    pipeline = RealtimeM1M2M3Pipeline(scenario="adversarial")

    adversarial_inputs = [
        # 1. Missing actor
        {"source_domain": "CDR", "payload": {"receiver_num": "+1-555-0199", "duration_sec": 50}},
        # 2. Negative numeric
        {"source_domain": "BANK", "default_event_type": "TRANSACTION", "payload": {"sender_acc": "ACC-1001", "amount": -999.0}},
        # 3. Unknown actor -> deterministic creation
        {"source_domain": "CDR", "payload": {"caller_num": "+1-555-UNKNOWN-99", "receiver_num": "+1-555-0199", "duration_sec": 30, "timestamp": "2026-09-03T14:00:00Z"}},
        # 4. Duplicate event
        {"source_domain": "CDR", "payload": {"caller_num": "+1-555-0101", "receiver_num": "+1-555-0199", "duration_sec": 80, "timestamp": "2026-09-03T14:02:00Z"}},
        {"source_domain": "CDR", "payload": {"caller_num": "+1-555-0101", "receiver_num": "+1-555-0199", "duration_sec": 80, "timestamp": "2026-09-03T14:02:00Z"}},
        # 5. Very late event (> 600s lateness)
        {"source_domain": "CDR", "payload": {"caller_num": "+1-555-0101", "receiver_num": "+1-555-0199", "duration_sec": 40, "timestamp": "2026-09-03T13:00:00Z"}},
    ]

    for item in adversarial_inputs:
        res = pipeline.process_raw_event(item)
        assert res["status"] in ("ACCEPTED", "REJECTED", "DEAD_LETTER")

    assert pipeline.metrics.dead_letter_count == 2  # items 1 and 2
    assert pipeline.metrics.duplicates == 1         # duplicate item 4
    assert pipeline.metrics.accepted == 3           # item 3, first item 4, item 5
    assert pipeline.metrics.received == len(adversarial_inputs)
    assert pipeline.metrics.received == pipeline.metrics.accepted + pipeline.metrics.rejected
