# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: Research Test Suite for Unsupervised Auto-Discovery and Causal Behavioral Profiling

import pandas as pd
import pytest

from dfap.investigation.auto_discovery import AutoDiscoveryEngine
from dfap.investigation.behavioral_profile import BehavioralProfiler


def test_auto_discovery_without_predefined_suspects():
    """Verifies that AutoDiscovery scans datasets and discovers anomalies without any prior suspect."""
    engine = AutoDiscoveryEngine()

    for ds in ["elliptic", "unsw", "stackoverflow"]:
        cases = engine.scan_dataset(ds, risk_threshold=0.35, max_cases=10)
        assert len(cases) > 0, f"AutoDiscovery must identify suspicious cases in {ds}"

        top_case = cases[0]
        assert "case_id" in top_case
        assert "entity_id" in top_case
        assert "risk_score" in top_case
        assert "trigger_event_id" in top_case
        assert "anomaly_type" in top_case
        assert len(top_case["top_reasons"]) > 0
        assert top_case["risk_score"] >= 0.35


def test_behavioral_profile_strict_causality_no_future_leakage():
    """Proves that BehavioralProfiler only uses historical events occurring at or before epoch t."""
    profiler = BehavioralProfiler()

    events_past = [
        {"epoch_time": 1000.0, "amount": 100.0, "source_domain": "BANK", "event_type": "TRANSACTION", "target_id": "TGT_A"},
        {"epoch_time": 2000.0, "amount": 250.0, "source_domain": "BANK", "event_type": "TRANSACTION", "target_id": "TGT_B"}
    ]

    events_with_future = events_past + [
        {"epoch_time": 5000.0, "amount": 999999.0, "source_domain": "BANK", "event_type": "TRANSACTION", "target_id": "TGT_FUTURE"}
    ]

    t_obs = 3000.0
    prof_past = profiler.compute_financial_profile(events_past, t_obs)
    prof_with_future = profiler.compute_financial_profile(events_with_future, t_obs)

    # Future transaction of $999,999 must NOT alter profile at epoch 3000.0
    assert prof_past["total_transactions"] == prof_with_future["total_transactions"]
    assert prof_past["mean_amount_usd"] == prof_with_future["mean_amount_usd"]
    assert prof_past["max_amount_usd"] == prof_with_future["max_amount_usd"]
    assert prof_with_future["max_amount_usd"] == 250.0


def test_post_discovery_ground_truth_reconciliation_audit():
    """Verifies that discovered cases can be audited against isolated ground truth."""
    engine = AutoDiscoveryEngine()
    cases = engine.scan_dataset("elliptic", risk_threshold=0.35, max_cases=5)
    assert len(cases) > 0

    audit = engine.reconcile_with_ground_truth(cases[0]["case_id"])
    assert audit["case_id"] == cases[0]["case_id"]
    assert "ground_truth_confirmed_anomaly" in audit
    assert audit["verdict"] in ("CONFIRMED_TRUE_POSITIVE", "EVALUATION_SAMPLE")


def test_forensic_benchmark_generator_end_to_end():
    """Verifies that ForensicBenchmarkGenerator runs blind inference on connected components and reveals labels post-inference."""
    from dfap.investigation.benchmark_generator import ForensicBenchmarkGenerator

    gen = ForensicBenchmarkGenerator()
    res = gen.evaluate_case("elliptic", seed_idx=1, risk_threshold=0.35, max_events=100)

    assert "case_id" in res
    assert "connectivity_certificate" in res
    assert res["connectivity_certificate"]["is_connected_component"] is True
    assert len(res["source_record_ids_sample"]) > 0

    # Strict temporal cutoff
    boundaries = res["temporal_boundaries"]
    assert boundaries["observable_events_up_to_pivot"] > 0
    assert boundaries["future_events_withheld"] >= 0

    # Blind inference
    blind = res["blind_inference"]
    assert blind["cases_discovered"] > 0

    # Traversal
    trav = res["causal_traversal"]
    assert trav["backtracking_steps"] >= 0
    assert trav["forwardtracking_steps"] >= 0

    # Post-inference ground truth
    gt = res["ground_truth_reconciliation"]
    assert "tp" in gt
    assert "fp" in gt
    assert "fn" in gt
    assert "precision" in gt
    assert "recall" in gt
    assert "f1_score" in gt
    assert 0.0 <= gt["precision"] <= 1.0
    assert 0.0 <= gt["recall"] <= 1.0


def test_extreme_future_anomaly_does_not_alter_detection():
    """
    CRITICAL PROOF OF ZERO TEMPORAL LEAKAGE:
    Inserting an extreme future anomaly strictly after the inference cutoff epoch
    MUST NOT alter the detection decisions or risk ranking at the pivot epoch.
    """
    engine = AutoDiscoveryEngine()
    cutoff_epoch = 2000.0

    # Historical and pivot events
    events_observable = [
        {"event_id": "EVT_01", "actor_id": "ACT_A", "target_id": "TGT_1", "epoch_time": 500.0, "amount": 100.0, "source_domain": "BANK", "timestamp": "2026-01-01T00:00:00Z"},
        {"event_id": "EVT_02", "actor_id": "ACT_A", "target_id": "TGT_2", "epoch_time": 1000.0, "amount": 120.0, "source_domain": "BANK", "timestamp": "2026-01-01T01:00:00Z"},
        {"event_id": "EVT_03", "actor_id": "ACT_A", "target_id": "TGT_3", "epoch_time": 1500.0, "amount": 80000.0, "source_domain": "BANK", "timestamp": "2026-01-01T02:00:00Z"},
        {"event_id": "EVT_04", "actor_id": "ACT_A", "target_id": "TGT_4", "epoch_time": 1900.0, "amount": 95000.0, "source_domain": "BANK", "timestamp": "2026-01-01T03:00:00Z"}
    ]

    # Baseline blind detection before inserting future anomaly
    cases_before = engine.scan_events(
        events_observable,
        risk_threshold=0.35,
        inference_cutoff_epoch=cutoff_epoch
    )

    # Insert an EXTREME future anomaly occurring well after cutoff_epoch (e.g. $100,000,000 heist)
    events_with_extreme_future = events_observable + [
        {
            "event_id": "EVT_FUTURE_HEIST",
            "actor_id": "ACT_A",
            "target_id": "WALLET_MIXER_EXTREME",
            "epoch_time": 999999.0,
            "amount": 100000000.0,
            "source_domain": "BANK",
            "timestamp": "2026-01-10T00:00:00Z"
        }
    ]

    # Detection after adding future anomaly
    cases_after = engine.scan_events(
        events_with_extreme_future,
        risk_threshold=0.35,
        inference_cutoff_epoch=cutoff_epoch
    )

    # PROVE ZERO LEAKAGE: Results must be identical
    assert len(cases_before) == len(cases_after), "Future event leaked into case count!"
    assert cases_before[0]["entity_id"] == cases_after[0]["entity_id"]
    assert cases_before[0]["risk_score"] == cases_after[0]["risk_score"]
    assert cases_before[0]["trigger_event_id"] == cases_after[0]["trigger_event_id"]
    assert cases_before[0]["top_reasons"] == cases_after[0]["top_reasons"]
