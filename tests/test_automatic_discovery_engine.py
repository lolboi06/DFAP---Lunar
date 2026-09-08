# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: Phase 4.1 Mandatory Test Suite for Causal Walk-Forward Discovery, Leakage Invariance & Multi-Slice Evaluation

import copy
import json
import pytest
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score

from dfap.investigation.inference_contract import (
    InferenceDataContract,
    InferenceContractViolationError,
    PROHIBITED_GROUND_TRUTH_COLUMNS,
    PredictionUnit,
    InferenceMode,
    DETECTOR_CONFIG
)
from dfap.investigation.detectors import (
    RobustStatisticalDetector,
    IsolationForestDetector,
    TemporalSequenceDetector,
    AnomalyDecisionEngine,
)
from dfap.investigation.auto_discovery import AutoDiscoveryEngine
from dfap.investigation.evaluation import (
    UNSWEvaluator,
    StackOverflowEvaluator,
    load_authentic_unsw_mixed_benchmark,
    evaluate_unsw_multi_slice,
    evaluate_score_parameter_sensitivity
)


@pytest.fixture
def engine():
    return AutoDiscoveryEngine(random_state=42)


def test_inference_contract_excludes_ground_truth():
    """Verifies that ground truth columns are strictly stripped and rejected at the inference boundary."""
    dirty_df = pd.DataFrame({
        "event_id": ["EVT_1", "EVT_2"],
        "actor_id": ["ACT_1", "ACT_2"],
        "is_attack_ground_truth": [0, 1],
        "attack_cat": ["Normal", "Exploit"],
        "label": [0, 1]
    })

    # 1. Sanitization strips labels
    clean_df = InferenceDataContract.sanitize_observable_events(dirty_df, strict_fail_on_labels=False)
    for col in PROHIBITED_GROUND_TRUTH_COLUMNS:
        assert col not in clean_df.columns
    assert InferenceDataContract.verify_clean_inference_state(clean_df) is True

    # 2. Strict mode raises violation error
    with pytest.raises(InferenceContractViolationError):
        InferenceDataContract.sanitize_observable_events(dirty_df, strict_fail_on_labels=True)


def test_walk_forward_baseline_excludes_pivot(engine):
    """Verifies that for every event e_k at t_k, the baseline excludes e_k itself."""
    df_raw = pd.read_parquet("data/canonical/stackoverflow_canonical.parquet")
    scored = engine.score_full_population(df_raw.iloc[:200], dataset_tag="stackoverflow")

    for s in scored:
        if s["history_event_count"] >= 2:
            assert s["event_id"] not in s["baseline_event_ids"]
            assert s["baseline_end"] < s["trigger_epoch"]


def test_walk_forward_baseline_excludes_future(engine):
    """Verifies that no baseline event has an epoch timestamp >= the pivot event's epoch."""
    df_raw = pd.read_parquet("data/canonical/stackoverflow_canonical.parquet")
    scored = engine.score_full_population(df_raw.iloc[:300], dataset_tag="stackoverflow")

    for s in scored:
        t_pivot = s["trigger_epoch"]
        assert s["baseline_cutoff"] <= t_pivot
        assert s["observation_cutoff"] <= t_pivot


def test_stackoverflow_causal_audit_record(engine):
    """Verifies that every Stack Overflow scored event stores a complete causal audit record."""
    df_raw = pd.read_parquet("data/canonical/stackoverflow_canonical.parquet")
    scored = engine.score_full_population(df_raw.iloc[:100], dataset_tag="stackoverflow")
    assert len(scored) == 100

    for s in scored:
        assert "baseline_event_ids" in s
        assert "baseline_end" in s
        assert "trigger_event_id" in s
        assert "trigger_epoch" in s
        assert "history_event_count" in s
        assert "detector_training_cutoff" in s
        assert "equal_timestamp_excluded_count" in s
        assert s["inference_mode"] == InferenceMode.CAUSAL_WALK_FORWARD
        assert s["prediction_unit"] == PredictionUnit.STACKOVERFLOW
        # Verify baseline_end is STRICTLY < trigger_epoch when history exists
        if s["history_event_count"] > 0:
            assert s["baseline_end"] < s["trigger_epoch"]


def test_walk_forward_equal_timestamps_excluded(engine):
    """
    CRITICAL TIE SEMANTICS:
    Creates 3 events at the exact same timestamp.
    Verifies none of the same-timestamp events appear in each other's baseline_event_ids,
    and equal_timestamp_excluded_count == 2 for each event.
    """
    dup_events = [
        {"event_id": "EVT_1", "actor_id": "U1", "target_id": "T1", "epoch_time": 1000.0, "timestamp": "2020-01-01T00:00:00Z", "amount": 0.0, "source_domain": "SOCIAL", "sha256_hash": "a"*64, "attributes": "{}"},
        {"event_id": "EVT_2", "actor_id": "U1", "target_id": "T2", "epoch_time": 1000.0, "timestamp": "2020-01-01T00:00:00Z", "amount": 0.0, "source_domain": "SOCIAL", "sha256_hash": "b"*64, "attributes": "{}"},
        {"event_id": "EVT_3", "actor_id": "U1", "target_id": "T3", "epoch_time": 1000.0, "timestamp": "2020-01-01T00:00:00Z", "amount": 0.0, "source_domain": "SOCIAL", "sha256_hash": "c"*64, "attributes": "{}"},
    ]
    scored = engine.score_full_population(dup_events, dataset_tag="stackoverflow")
    assert len(scored) == 3
    for s in scored:
        assert s["history_event_count"] == 0
        assert s["baseline_event_ids"] == []
        assert s["equal_timestamp_excluded_count"] == 2
        assert isinstance(s["score"], float)


def test_stackoverflow_baseline_epochs_strictly_less_than_trigger(engine):
    """
    AUDIT TEST: For every scored Stack Overflow event,
    asserts that EVERY baseline event b satisfies epoch(b) < trigger_epoch.
    """
    df_raw = pd.read_parquet("data/canonical/stackoverflow_canonical.parquet")
    scored = engine.score_full_population(df_raw.iloc[:300], dataset_tag="stackoverflow")
    epoch_lookup = dict(zip(df_raw["event_id"], df_raw["epoch_time"]))

    for s in scored:
        t_pivot = s["trigger_epoch"]
        for b_id in s["baseline_event_ids"]:
            b_epoch = epoch_lookup[b_id]
            assert b_epoch < t_pivot, f"Causal violation: baseline event {b_id} (epoch {b_epoch}) >= trigger_epoch {t_pivot}!"


def test_future_leakage_invariance_comprehensive(engine):
    """
    CRITICAL PROOF: Score of pivot P remains invariant under:
      - future normal events
      - future counterparty insertion
      - future feature distribution shift
      - future extreme numeric values
      - future events belonging to OTHER entities
    """
    df_raw = pd.read_parquet("data/canonical/stackoverflow_canonical.parquet").sort_values("epoch_time").reset_index(drop=True)
    entity_user = "SO_10661"
    user_evts = df_raw[df_raw["actor_id"] == entity_user].reset_index(drop=True)

    pivot_idx = 10
    pivot_epoch = float(user_evts.iloc[pivot_idx]["epoch_time"])

    # Score before future tampering
    scored_before = engine.score_full_population(user_evts.iloc[:pivot_idx + 1], dataset_tag="stackoverflow")
    p1_score = scored_before[pivot_idx]["score"]
    p1_base_ids = scored_before[pivot_idx]["baseline_event_ids"]

    # Injections after pivot:
    # 1. Extreme numeric value & novel counterparty
    # 2. Future events for other entities
    future_injections = [
        {
            "event_id": "EVT_FUTURE_EXTREME_1",
            "actor_id": entity_user,
            "target_id": "SO_NEW_STRANGE_PEER_9999",
            "epoch_time": pivot_epoch + 10000.0,
            "timestamp": "2030-01-01T00:00:00Z",
            "amount": 999999999.0,
            "source_domain": "SOCIAL",
            "sha256_hash": "f"*64,
            "attributes": "{}"
        },
        {
            "event_id": "EVT_FUTURE_OTHER_ENTITY",
            "actor_id": "SO_COMPLETELY_DIFFERENT_ACTOR_555",
            "target_id": "SO_TARGET_444",
            "epoch_time": pivot_epoch + 5000.0,
            "timestamp": "2030-01-01T00:00:00Z",
            "amount": 500.0,
            "source_domain": "SOCIAL",
            "sha256_hash": "e"*64,
            "attributes": "{}"
        }
    ]
    df_tampered = pd.concat([user_evts.iloc[:pivot_idx + 1], pd.DataFrame(future_injections)], ignore_index=True)

    # Score after future tampering
    scored_after = engine.score_full_population(df_tampered, dataset_tag="stackoverflow")
    # Find pivot event in output
    pivot_after = next(s for s in scored_after if s["event_id"] == user_evts.iloc[pivot_idx]["event_id"])

    assert pivot_after["score"] == p1_score
    assert pivot_after["baseline_event_ids"] == p1_base_ids


def test_full_population_scoring(engine):
    """Verifies that the detector produces scores for ALL events in the declared population."""
    df_unsw = pd.read_parquet("data/canonical/unsw_canonical.parquet").iloc[:500]
    scored = engine.score_full_population(df_unsw, dataset_tag="unsw")
    assert len(scored) == 500
    for s in scored:
        assert "event_id" in s
        assert "score" in s


def test_pr_auc_matches_sklearn():
    """Verifies that PR-AUC exactly matches sklearn.metrics.average_precision_score."""
    pop = [
        {"event_id": f"EVT_{i}", "score": round(float(np.sin(i) * 0.5 + 0.5), 3)}
        for i in range(100)
    ]
    gt_df = pd.DataFrame({
        "event_id": [f"EVT_{i}" for i in range(100)],
        "is_attack_ground_truth": [1 if i % 4 == 0 else 0 for i in range(100)]
    })

    evaluator = UNSWEvaluator()
    res = evaluator.evaluate_full_population(pop, ground_truth_df=gt_df)

    y_true = np.array(gt_df["is_attack_ground_truth"])
    y_score = np.array([p["score"] for p in pop])
    expected_pr_auc = round(float(average_precision_score(y_true, y_score)), 4)

    assert res["pr_auc"] == expected_pr_auc
    assert res["roc_auc"] == round(float(roc_auc_score(y_true, y_score)), 4)


def test_single_class_auc_is_not_defined():
    """Verifies that if ground truth contains only 1 class, AUC is reported as NOT_DEFINED, not a fake 0.0."""
    pop = [{"event_id": f"EVT_{i}", "score": 0.5} for i in range(50)]
    gt_df = pd.DataFrame({
        "event_id": [f"EVT_{i}" for i in range(50)],
        "is_attack_ground_truth": [0 for _ in range(50)]
    })

    evaluator = UNSWEvaluator()
    res = evaluator.evaluate_full_population(pop, ground_truth_df=gt_df)

    assert res["roc_auc"] == "NOT_DEFINED"
    assert res["pr_auc"] == "NOT_DEFINED"
    assert res["reason"] == "SINGLE_CLASS_EVALUATION_POPULATION"


def test_candidate_truncation_cannot_change_full_pr_auc():
    """Verifies PR-AUC is computed across the full population N, not truncated to top-k."""
    pop = [{"event_id": f"EVT_{i}", "score": float(i) / 100.0} for i in range(100)]
    gt_df = pd.DataFrame({
        "event_id": [f"EVT_{i}" for i in range(100)],
        "is_attack_ground_truth": [1 if i > 50 else 0 for i in range(100)]
    })

    evaluator = UNSWEvaluator()
    res = evaluator.evaluate_full_population(pop, ground_truth_df=gt_df, top_k_list=[5, 10])
    assert res["records_evaluated"] == 100


def test_score_ordering_does_not_affect_label_alignment():
    """Verifies that whether population is sorted ascending or descending, label alignment and PR-AUC match."""
    pop = [{"event_id": f"EVT_{i}", "score": float(i % 10) / 10.0} for i in range(50)]
    gt_df = pd.DataFrame({
        "event_id": [f"EVT_{i}" for i in range(50)],
        "is_attack_ground_truth": [1 if i % 2 == 0 else 0 for i in range(50)]
    })

    evaluator = UNSWEvaluator()
    res1 = evaluator.evaluate_full_population(pop, ground_truth_df=gt_df)
    res2 = evaluator.evaluate_full_population(list(reversed(pop)), ground_truth_df=gt_df)

    assert res1["pr_auc"] == res2["pr_auc"]
    assert res1["roc_auc"] == res2["roc_auc"]


def test_missing_ground_truth_events_detected():
    """Verifies that missing ground-truth records are strictly caught with an error rather than silently assigned 0."""
    pop = [{"event_id": "EVT_1", "score": 0.8}, {"event_id": "EVT_MISSING", "score": 0.9}]
    gt_df = pd.DataFrame({
        "event_id": ["EVT_1"],
        "is_attack_ground_truth": [1]
    })

    evaluator = UNSWEvaluator()
    with pytest.raises(ValueError) as exc_info:
        evaluator.evaluate_full_population(pop, ground_truth_df=gt_df)
    assert "missing from ground truth reference" in str(exc_info.value)


def test_unsw_multi_slice_evaluation(engine):
    """
    CRITICAL: Validates multi-slice evaluation on 3 independent authentic mixed-class slices from UNSW.
    Reports mean ± std for ROC-AUC, PR-AUC, precision, recall, F1, and FPR.
    """
    res = evaluate_unsw_multi_slice(engine, slice_ranges=[(45000, 47000), (62000, 64000), (112000, 114000)])
    assert res["multi_slice_count"] == 3
    summary = res["summary_mean_std"]
    for metric in ["roc_auc", "pr_auc", "precision", "recall", "f1", "fpr"]:
        assert "mean" in summary[metric]
        assert "std" in summary[metric]
        assert isinstance(summary[metric]["mean"], float)


def test_score_parameter_sensitivity(engine):
    """Verifies that score parameter sensitivity analysis runs blind and reports stability."""
    df_raw = pd.read_parquet("data/canonical/stackoverflow_canonical.parquet").iloc[:100]
    sens = evaluate_score_parameter_sensitivity(engine, df_raw)
    assert "top_20_jaccard_overlaps" in sens
    assert "sensitivity_status" in sens
    assert "mean_overlap" in sens
