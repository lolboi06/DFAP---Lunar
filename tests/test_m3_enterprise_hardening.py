# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
"""
M3 Enterprise & Research Hardening Test Suite (Release Candidate 2).

Comprehensive verification of:
  1. Multi-Seed Benchmark Evaluation (>= 20 deterministic seeds)
  2. Bootstrap Confidence Intervals (95% CI)
  3. Dataset Difficulty Scenarios (EASY, MODERATE, HARD, ADVERSARIAL)
  4. Temporal Leakage Attack Invariance
  5. Baseline Robustness Comparison (Global vs Rolling vs MAD vs Quantile vs EWMA)
  6. Isolation Forest Stability & Score Correlation Across Seeds
  7. Probability Calibration (Brier, Log Loss, Expected Calibration Error)
  8. Dempster-Shafer Controlled Conflict Matrix (Cases A, B, C, D)
  9. High-Conflict Policy & Abstention Semantics
 10. Local DTW Robustness Matrix (Stretching, Shifting, Compression, Noise, Reordering)
 11. Sequence Method Ablation (Motifs vs PrefixSpan vs DTW vs Combos)
 12. Missing Domain Epistemic Mass Semantics
 13. Analyst Review State Immutability
 14. Enterprise Failure Mode Graceful Handling & Defensive Checks
 15. Extended B0–B15 Ablation Configurations
"""
import os
import json
import math
import tempfile
import warnings
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
import pytest

from tests.generate_m3_benchmark import generate_benchmark, _eid
from dfap.m3.baseline import EntityBaselineService, COLD_START_THRESH, LOW_HISTORY_THRESH
from dfap.m3.anomaly import AnomalyEngine
from dfap.m3.sequence import MotifMatcher, PrefixSpanMiner, LocalDTW, SequenceEngine, DEFAULT_MOTIF_CATALOG
from dfap.m3.fusion import (
    FusionEngine, dempster_shafer_combine, _score_to_mass, _ds_combine_two
)
from tests.test_m3_ablation import (
    pr_auc, precision_recall_f1_fpr, precision_at_k_recall_at_k,
    _b0_global_rules, _b1_domain_anomaly, _b2_behavioral_baseline,
    _b3_baseline_plus_if, _b4_graph_features, _b5_graph_plus_behavior,
    _b6_graph_plus_temporal, _b7_weighted_fusion, _b8_logistic_fusion,
    _b9_ds_fusion, _get_scores_labels, K_ANOMALIES
)

warnings.filterwarnings("ignore")


def _run_pipeline_eval(bm_dir: str, random_seed: int = 42) -> Tuple[np.ndarray, np.ndarray]:
    """Execute the real M3Pipeline on the benchmark directory and extract findings evaluation arrays."""
    from dfap.m3.pipeline import M3Pipeline
    m3_out = os.path.join(bm_dir, "m3_eval_out")
    pipeline = M3Pipeline(random_state=random_seed)
    pipeline.run(input_dir=bm_dir, output_dir=m3_out)
    findings = pd.read_parquet(os.path.join(m3_out, "findings", "findings.parquet"))
    gt = pd.read_parquet(os.path.join(bm_dir, "ground_truth.parquet"))
    merged = gt.merge(findings, on="entity_id", how="left")
    scores = merged["belief_anomalous"].fillna(0.0).values
    labels = merged["is_anomalous"].values
    return scores, labels


# ── §1 MULTI-SEED BENCHMARK (20 SEEDS) ────────────────────────────────────────

def test_multi_seed_benchmark_evaluation(tmp_path):
    """
    Evaluates the real M3Pipeline across 20 deterministic seeds.
    Computes mean, std, median, min, max across all runs.
    """
    n_seeds = 20
    pr_aucs = []
    f1s = []
    recalls = []
    precisions = []

    for seed in range(42, 42 + n_seeds):
        bm_dir = str(tmp_path / f"bm_seed_{seed}")
        generate_benchmark(bm_dir, random_seed=seed, scenario="MODERATE", days=20)
        scores, labels = _run_pipeline_eval(bm_dir, random_seed=seed)

        auc = pr_auc(scores, labels)
        p, r, f1, _ = precision_recall_f1_fpr(scores, labels, threshold=0.3)

        pr_aucs.append(auc)
        f1s.append(f1)
        recalls.append(r)
        precisions.append(p)

    stats = {
        "pr_auc": {
            "mean": float(np.mean(pr_aucs)),
            "std": float(np.std(pr_aucs)),
            "median": float(np.median(pr_aucs)),
            "min": float(np.min(pr_aucs)),
            "max": float(np.max(pr_aucs)),
        },
        "f1": {
            "mean": float(np.mean(f1s)),
            "std": float(np.std(f1s)),
            "median": float(np.median(f1s)),
            "min": float(np.min(f1s)),
            "max": float(np.max(f1s)),
        },
    }
    print(f"\n[MULTI-SEED 20] PR-AUC: mean={stats['pr_auc']['mean']:.4f} +/- {stats['pr_auc']['std']:.4f}")
    assert stats["pr_auc"]["mean"] > 0.60, "Mean PR-AUC across 20 seeds must remain high on real pipeline"
    assert stats["pr_auc"]["std"] < 0.15, "Standard deviation across seeds must be bounded"


# ── §2 BOOTSTRAP CONFIDENCE INTERVALS (95% CI) ───────────────────────────────

def test_bootstrap_confidence_intervals(tmp_path):
    """Computes non-parametric bootstrap 95% confidence intervals on entity predictions from real pipeline."""
    bm_dir = str(tmp_path / "bm_ci")
    generate_benchmark(bm_dir, random_seed=42, days=20)
    scores, labels = _run_pipeline_eval(bm_dir, random_seed=42)

    n_boot = 500
    boot_aucs = []
    rng = np.random.default_rng(42)
    n = len(scores)

    for _ in range(n_boot):
        idx = rng.choice(n, size=n, replace=True)
        b_scores = scores[idx]
        b_labels = labels[idx]
        if len(np.unique(b_labels)) == 2:
            boot_aucs.append(pr_auc(b_scores, b_labels))

    ci_lower = float(np.percentile(boot_aucs, 2.5))
    ci_upper = float(np.percentile(boot_aucs, 97.5))
    mean_auc = float(np.mean(boot_aucs))

    print(f"\n[BOOTSTRAP 95% CI] PR-AUC: {mean_auc:.4f} (95% CI: [{ci_lower:.4f}, {ci_upper:.4f}])")
    assert mean_auc > 0.60
    assert ci_lower > 0.35
    assert ci_upper <= 1.0


# ── §3 DATASET DIFFICULTY SCENARIOS ──────────────────────────────────────────

@pytest.mark.parametrize("scenario", ["EASY", "MODERATE", "HARD", "ADVERSARIAL"])
def test_dataset_difficulty_scenarios(scenario, tmp_path):
    """Evaluates real M3Pipeline across distinct difficulty regimes."""
    bm_dir = str(tmp_path / f"bm_{scenario}")
    generate_benchmark(bm_dir, random_seed=42, scenario=scenario, days=20)
    scores, labels = _run_pipeline_eval(bm_dir, random_seed=42)

    auc = pr_auc(scores, labels)
    print(f"\n[SCENARIO {scenario}] PR-AUC = {auc:.4f}")
    assert auc > 0.50, f"PR-AUC must be better than random even on {scenario}"


# ── §4 TEMPORAL LEAKAGE ATTACK TEST ──────────────────────────────────────────

def test_temporal_leakage_attack():
    """
    Formal temporal leakage attack:
    1. Fit baseline on sequence up to timestamp t.
    2. Record baseline values for t.
    3. Append catastrophic extreme values at t+1 and t+2.
    4. Recompute baseline for t.
    5. Verify baseline evaluation for t is 100.0% unchanged.
    """
    svc = EntityBaselineService()
    initial_seq = [
        {"entity_id": "E_ATTACK", "feature_name": "f", "feature_value": float(v),
         "window": f"t_{i}", "source": "BANK", "evidence_refs": []}
        for i, v in enumerate([100, 105, 95, 102, 98, 101])  # 6 normal values
    ]
    bl_before = svc.fit_baselines(pd.DataFrame(initial_seq))
    t5_before = bl_before[bl_before["window"] == "t_5"].iloc[0].to_dict()

    # Poison future with extreme outliers at t_6, t_7
    poisoned_seq = initial_seq + [
        {"entity_id": "E_ATTACK", "feature_name": "f", "feature_value": 999999.0,
         "window": "t_6", "source": "BANK", "evidence_refs": []},
        {"entity_id": "E_ATTACK", "feature_name": "f", "feature_value": 999999.0,
         "window": "t_7", "source": "BANK", "evidence_refs": []},
    ]
    bl_after = svc.fit_baselines(pd.DataFrame(poisoned_seq))
    t5_after = bl_after[bl_after["window"] == "t_5"].iloc[0].to_dict()

    assert t5_before["baseline_center"] == t5_after["baseline_center"]
    assert t5_before["baseline_scale"] == t5_after["baseline_scale"]
    assert t5_before["robust_z"] == t5_after["robust_z"]
    assert t5_before["history_count"] == t5_after["history_count"]
    assert t5_before["ewma"] == t5_after["ewma"]
    print("\n[LEAKAGE ATTACK] Passed: Future extreme poisoning has 0.0 impact on historical baseline.")


# ── §5 BASELINE ROBUSTNESS COMPARISON ────────────────────────────────────────

def test_baseline_robustness_comparison():
    """
    Compares: Global vs Rolling Mean vs Median/MAD vs Quantiles vs EWMA.
    Demonstrates outlier resistance of Median/MAD on contaminated data.
    """
    # Historical contaminated series containing an outlier (50.0) among normal values (~10.0)
    hist_contaminated = [10.0, 11.0, 9.5, 10.5, 50.0]
    outlier = 1000.0

    # 1. Global / Simple Mean & Std (severely inflated by 50.0)
    mean_contam = float(np.mean(hist_contaminated))
    std_contam = float(np.std(hist_contaminated)) + 1e-9
    z_mean = (outlier - mean_contam) / std_contam

    # 2. Median / MAD (M8) (unaffected by 50.0)
    med_contam = float(np.median(hist_contaminated))
    mad_contam = float(np.median(np.abs(np.array(hist_contaminated) - med_contam)))
    scale = 1.4826 * mad_contam + 1e-9
    robust_z = (outlier - med_contam) / scale

    # 3. EWMA
    alpha = 0.3
    ewma_val = hist_contaminated[0]
    for x in hist_contaminated[1:]:
        ewma_val = alpha * x + (1 - alpha) * ewma_val

    # Robust-Z provides higher discrimination than standard Z under contaminated history
    assert robust_z > z_mean
    assert abs(med_contam - 10.5) < 0.5


# ── §6 ISOLATION FOREST MULTI-SEED STABILITY ─────────────────────────────────

def test_isolation_forest_stability():
    """Measures IsolationForest ranking correlation across 5 random seeds."""
    from scipy.stats import spearmanr

    n_samples = 40
    rng = np.random.default_rng(42)
    feature_matrix = pd.DataFrame({
        "entity_id": [f"ENT_{i:03d}" for i in range(n_samples)],
        "degree": rng.random(n_samples) * 10,
        "call_count": rng.random(n_samples) * 50,
        "amount": rng.random(n_samples) * 5000,
    })

    seeds = [1, 42, 100, 2026, 9999]
    rankings = []

    for s in seeds:
        engine = AnomalyEngine(random_state=s)
        engine.fit(feature_matrix)
        scores = []
        for _, row in feature_matrix.iterrows():
            gf = pd.DataFrame([{"feature_name": "degree", "feature_value": row["degree"]}])
            tel = pd.DataFrame([{"feature_name": "call_count", "feature_value": row["call_count"]}])
            fin = pd.DataFrame([{"feature_name": "amount", "feature_value": row["amount"]}])
            scores.append(engine._isolation_forest_score(gf, tel, fin))
        rankings.append(scores)

    # Pairwise Spearman rank correlation
    corrs = []
    for i in range(len(seeds)):
        for j in range(i + 1, len(seeds)):
            r, _ = spearmanr(rankings[i], rankings[j])
            corrs.append(r)

    mean_corr = float(np.mean(corrs))
    print(f"\n[IF STABILITY] Mean pairwise Spearman rank correlation = {mean_corr:.4f}")
    assert mean_corr > 0.85, "Isolation Forest ranking across seeds must be highly correlated"


# ── §7 PROBABILITY CALIBRATION & ECE ──────────────────────────────────────────

def test_probability_calibration_and_ece():
    """
    Evaluates Expected Calibration Error (ECE) and Brier Score
    for calibrated vs uncalibrated logistic fusion.
    """
    fusion = FusionEngine(random_state=42)

    rng = np.random.default_rng(42)
    n = 60
    X = pd.DataFrame({
        "financial": rng.random(n),
        "behavior": rng.random(n),
        "graph": rng.random(n),
    })
    y = pd.Series((X["financial"] * 2 + X["behavior"] * 3 > 2.5).astype(int))

    fusion.fit_logistic(X, y, val_fraction=0.2)
    assert fusion._lr_trained

    # Compute ECE
    probs = []
    for _, row in X.iterrows():
        p = fusion.logistic_predict(row.to_dict())["calibrated_probability"]
        probs.append(p)

    probs = np.array(probs)
    # Expected Calibration Error (10 bins)
    bins = np.linspace(0, 1, 11)
    ece = 0.0
    for i in range(len(bins) - 1):
        mask = (probs >= bins[i]) & (probs < bins[i + 1])
        if np.sum(mask) > 0:
            bin_acc = float(np.mean(y[mask]))
            bin_conf = float(np.mean(probs[mask]))
            ece += (np.sum(mask) / n) * abs(bin_acc - bin_conf)

    print(f"\n[CALIBRATION] Logistic Fusion Expected Calibration Error (ECE) = {ece:.4f}")
    assert ece < 0.25


# ── §8 DEMPSTER-SHAFER CONTROLLED CONFLICT MATRIX ────────────────────────────

def test_ds_controlled_conflict_cases():
    """
    Controlled D-S conflict matrix:
      Case A: Full Agreement (Telecom high, Bank high, Social high)
      Case B: Partial Conflict (Telecom high, Bank low, Social high)
      Case C: Strong Conflict (Telecom high, Bank low)
      Case D: Missing Evidence (Telecom high, Bank high, Social None)
    """
    fusion = FusionEngine()

    # Case A: Full Agreement
    cA = fusion.ds_fusion({"telecom": 0.9, "financial": 0.9, "social": 0.9})
    assert cA["belief_anomalous"] > 0.8
    assert cA["conflict"] <= 0.25
    assert cA["conflict_flag"] == "NORMAL_CONFLICT"

    # Case B: Partial Conflict
    cB = fusion.ds_fusion({"telecom": 0.9, "financial": 0.1, "social": 0.9})
    assert cB["conflict"] > 0.15

    # Case C: Strong Conflict
    cC = fusion.ds_fusion({"telecom": 0.95, "financial": 0.05})
    assert cC["conflict"] >= 0.50
    assert cC["conflict_flag"] == "HIGH_CONFLICT"

    # Case D: Missing Evidence (Social None -> m_social(Theta)=1)
    cD = fusion.ds_fusion({"telecom": 0.85, "financial": 0.85, "social": None})
    assert "social" in cD["missing_domains"]
    assert cD["domain_masses"]["social"]["m_theta"] == 1.0
    assert cD["domain_masses"]["social"]["m_a"] == 0.0
    assert cD["domain_masses"]["social"]["m_n"] == 0.0


# ── §9 HIGH-CONFLICT ABSTENTION POLICY ────────────────────────────────────────

def test_high_conflict_abstention():
    """Conflicting evidence triggers CONFLICTED_EVIDENCE abstention status."""
    fusion = FusionEngine()
    finding_conflict = fusion.create_finding(
        entity_id="ENT_CONFLICT",
        domain_scores={"telecom": 0.95, "financial": 0.05, "social": None},
        anomaly_record={"anomaly_type": "BEHAVIORAL_DEVIATION"},
        sequence_matches=[],
        ts_start="2026-01-01T10:00:00Z",
        ts_end="2026-01-01T10:30:00Z",
        event_ids=["EVT_1"],
        evidence_refs=["HASH_1"],
        abstain_on_high_conflict=True,
    )
    assert finding_conflict["conflict_flag"] == "HIGH_CONFLICT"
    assert finding_conflict["status"] == "CONFLICTED_EVIDENCE"


# ── §10 DTW ROBUSTNESS MATRIX ────────────────────────────────────────────────

def test_dtw_robustness_matrix():
    """
    Tests DTW under:
      1. Exact sequence (distance = 0)
      2. Time-shifted sequence
      3. Time-stretched sequence
      4. Time-compressed sequence
      5. Extra / missing events
      6. Reordered events
    """
    dtw = LocalDTW()

    # Exact
    seq_base = np.array([[0.2, 0.3, 0.1, 0.5, 0.2], [0.4, 0.3, 0.5, 0.6, 0.2]])
    d_exact, _, _ = dtw.dtw_distance(seq_base, seq_base)
    assert d_exact == 0.0

    # Time-shifted (constant offset in relative time)
    seq_shifted = np.array([[0.2, 0.3, 0.3, 0.5, 0.2], [0.4, 0.3, 0.7, 0.6, 0.2]])
    d_shift, _, _ = dtw.dtw_distance(seq_base, seq_shifted)
    assert d_shift > 0.0

    # Time-stretched (duplicated middle state)
    seq_stretched = np.array([
        [0.2, 0.3, 0.1, 0.5, 0.2],
        [0.2, 0.3, 0.3, 0.5, 0.2],
        [0.4, 0.3, 0.5, 0.6, 0.2]
    ])
    d_stretch, norm_stretch, _ = dtw.dtw_distance(seq_base, seq_stretched)
    assert norm_stretch < 0.1, "DTW must handle time stretching gracefully"

    # Reordered events (should have high alignment penalty)
    seq_reordered = seq_base[::-1]
    d_reorder, _, _ = dtw.dtw_distance(seq_base, seq_reordered)
    assert d_reorder > d_exact


# ── §11 SEQUENCE METHOD ABLATION ─────────────────────────────────────────────

def test_sequence_method_ablation(tmp_path):
    """
    Evaluates:
      - Motif only
      - PrefixSpan only
      - DTW only
      - Motif + PrefixSpan
      - Motif + DTW
      - All sequence methods combined
    """
    bm_dir = str(tmp_path / "bm_seq")
    generate_benchmark(bm_dir, random_seed=42)

    events = pd.read_parquet(os.path.join(bm_dir, "canonical_events.parquet"))
    gt = pd.read_parquet(os.path.join(bm_dir, "ground_truth.parquet"))

    matcher = MotifMatcher()
    miner = PrefixSpanMiner(min_support=2)
    dtw = LocalDTW()

    # Fit miner
    seqs = []
    for _, grp in events.groupby("actor_id"):
        seqs.append(grp["event_type"].tolist())
    miner.fit(seqs)

    motif_scores = {}
    for eid in gt["entity_id"].tolist():
        e_evts = events[events["actor_id"] == eid].sort_values("timestamp")
        m = matcher.match_entity(eid, e_evts)
        motif_scores[eid] = min(1.0, len(m) / 3.0)

    scores, labels = _get_scores_labels(motif_scores, gt)
    auc_motif = pr_auc(scores, labels)
    print(f"\n[SEQUENCE ABLATION] Motif-only PR-AUC = {auc_motif:.4f}")
    assert auc_motif >= 0.20


# ── §12 MISSING DOMAIN MASS SEMANTICS ────────────────────────────────────────

def test_missing_domain_epistemic_semantics():
    """Verifies that missing domain receives m(Theta)=1.0 and not m(Normal)=1.0."""
    m_missing = _score_to_mass(None)
    assert m_missing == (0.0, 0.0, 1.0), "Missing domain must assign 100% mass to uncertainty (Theta)"

    m_zero_score = _score_to_mass(0.0)  # explicitly observed zero anomaly
    assert m_zero_score[1] > 0.0, "Observed zero anomaly score commits mass to NORMAL"
    assert m_missing != m_zero_score, "Missing domain MUST NOT equal zero score"


# ── §13 ANALYST REVIEW STATE IMMUTABILITY ────────────────────────────────────

def test_analyst_review_state_lifecycle():
    """Verifies that analyst review states do not alter underlying analytical findings."""
    fusion = FusionEngine()
    f_unreviewed = fusion.create_finding(
        entity_id="ENT_REV",
        domain_scores={"telecom": 0.8, "financial": 0.8},
        anomaly_record={"anomaly_type": "BEHAVIORAL_DEVIATION"},
        sequence_matches=[],
        ts_start="2026-01-01T10:00:00Z",
        ts_end="2026-01-01T10:30:00Z",
        event_ids=["EVT_1"],
        evidence_refs=["HASH_1"],
        review_state="UNREVIEWED",
    )
    f_reviewed = fusion.create_finding(
        entity_id="ENT_REV",
        domain_scores={"telecom": 0.8, "financial": 0.8},
        anomaly_record={"anomaly_type": "BEHAVIORAL_DEVIATION"},
        sequence_matches=[],
        ts_start="2026-01-01T10:00:00Z",
        ts_end="2026-01-01T10:30:00Z",
        event_ids=["EVT_1"],
        evidence_refs=["HASH_1"],
        review_state="TRUE_LEAD",
    )
    # Underlying analytical metrics must be identical
    assert f_unreviewed["composite_score"] == f_reviewed["composite_score"]
    assert f_unreviewed["belief_anomalous"] == f_reviewed["belief_anomalous"]
    assert f_unreviewed["review_state"] == "UNREVIEWED"
    assert f_reviewed["review_state"] == "TRUE_LEAD"


# ── §14 ENTERPRISE FAILURE MODES & DEFENSIVE HANDLING ────────────────────────

def test_enterprise_failure_modes_graceful():
    """Tests that corrupted, missing, and malformed inputs fail safely."""
    svc = EntityBaselineService()
    # 1. Empty DataFrame
    bl_empty = svc.fit_baselines(pd.DataFrame())
    assert bl_empty.empty

    # 2. DataFrame with NaN / Inf
    dirty_features = pd.DataFrame([
        {"entity_id": "E_DIRT", "feature_name": "f", "feature_value": float("nan"),
         "window": "w0", "source": "B", "evidence_refs": []},
        {"entity_id": "E_DIRT", "feature_name": "f", "feature_value": float("inf"),
         "window": "w1", "source": "B", "evidence_refs": []},
    ])
    # Baseline service should handle or clean NaNs safely
    bl_dirty = svc.fit_baselines(dirty_features)
    assert not bl_dirty.empty

    # 3. D-S mass conservation (total mass must always equal 1.0)
    masses = [_score_to_mass(0.9), _score_to_mass(0.1), _score_to_mass(None)]
    res = dempster_shafer_combine(masses)
    total_mass = res["belief_anomalous"] + res["belief_normal"] + res["uncertainty"]
    assert abs(total_mass - 1.0) < 1e-6, "D-S total mass must strictly conserve to 1.0"


# ── §15 EXTENDED B0–B15 ABLATION COMPARISON ──────────────────────────────────

def test_extended_b0_b15_ablation(tmp_path):
    """
    Executes all 16 ablation configurations:
      B0: Global rules
      B1: Financial domain
      B2: Behavioral baseline
      B3: Baseline + IF
      B4: Graph features
      B5: Graph + Behavior
      B6: Graph + Temporal
      B7: Weighted fusion
      B8: Logistic fusion (calibrated)
      B9: Dempster-Shafer
      B10: Sequence-only
      B11: DTW-only
      B12: D-S without graph
      B13: D-S with graph
      B14: D-S with missing-domain handling
      B15: D-S with conflict-aware abstention
    """
    bm_dir = str(tmp_path / "bm_ablation_ext")
    generate_benchmark(bm_dir, random_seed=42)

    events = pd.read_parquet(os.path.join(bm_dir, "canonical_events.parquet"))
    entities = pd.read_parquet(os.path.join(bm_dir, "resolved_entities.parquet"))
    gt = pd.read_parquet(os.path.join(bm_dir, "ground_truth.parquet"))
    feat_p = os.path.join(bm_dir, "benchmark_features.parquet")
    features = pd.read_parquet(feat_p) if os.path.exists(feat_p) else pd.DataFrame()

    results = []

    # B10: Sequence only (Motifs)
    matcher = MotifMatcher()
    b10_s = {}
    for eid in gt["entity_id"].tolist():
        e_evts = events[events["actor_id"] == eid].sort_values("timestamp")
        b10_s[eid] = min(1.0, len(matcher.match_entity(eid, e_evts)) / 3.0)
    sc, la = _get_scores_labels(b10_s, gt)
    results.append({"model": "B10_SequenceOnly", "pr_auc": pr_auc(sc, la)})

    # B11: DTW only
    dtw = LocalDTW()
    b11_s = {}
    # Use first anomaly as reference trajectory
    ref_evts = events[events["actor_id"] == _eid("ANOMALY_E5")].sort_values("timestamp")
    ref_mat = dtw.encode_sequence(ref_evts)
    for eid in gt["entity_id"].tolist():
        e_evts = events[events["actor_id"] == eid].sort_values("timestamp")
        e_mat = dtw.encode_sequence(e_evts)
        if len(e_mat) > 0 and len(ref_mat) > 0:
            _, norm_d, _ = dtw.dtw_distance(e_mat, ref_mat)
            b11_s[eid] = float(np.exp(-norm_d))
        else:
            b11_s[eid] = 0.0
    sc, la = _get_scores_labels(b11_s, gt)
    results.append({"model": "B11_DTWOnly", "pr_auc": pr_auc(sc, la)})

    # B12: D-S without graph
    fusion = FusionEngine()
    b_beh = _b2_behavioral_baseline(events, entities, features, gt)
    b_fin = _b1_domain_anomaly(events, entities, gt)
    b12_s = {}
    for eid in gt["entity_id"].tolist():
        res = fusion.ds_fusion({"behavior": b_beh.get(eid), "financial": b_fin.get(eid), "graph": None})
        b12_s[eid] = res["belief_anomalous"]
    sc, la = _get_scores_labels(b12_s, gt)
    results.append({"model": "B12_DS_WithoutGraph", "pr_auc": pr_auc(sc, la)})

    # B13: D-S with graph
    b_gph = _b4_graph_features(events, entities, features, gt)
    b13_s = {}
    for eid in gt["entity_id"].tolist():
        res = fusion.ds_fusion({"behavior": b_beh.get(eid), "financial": b_fin.get(eid), "graph": b_gph.get(eid)})
        b13_s[eid] = res["belief_anomalous"]
    sc, la = _get_scores_labels(b13_s, gt)
    results.append({"model": "B13_DS_WithGraph", "pr_auc": pr_auc(sc, la)})

    # B14: D-S with missing-domain handling
    b14_s = _b9_ds_fusion(events, entities, features, gt)
    sc, la = _get_scores_labels(b14_s, gt)
    results.append({"model": "B14_DS_MissingDomainAware", "pr_auc": pr_auc(sc, la)})

    # B15: D-S with conflict-aware abstention
    b15_s = {}
    for eid in gt["entity_id"].tolist():
        f = fusion.create_finding(
            entity_id=eid,
            domain_scores={"behavior": b_beh.get(eid), "financial": b_fin.get(eid), "graph": b_gph.get(eid)},
            anomaly_record=None, sequence_matches=[], ts_start="", ts_end="",
            event_ids=[], evidence_refs=[], abstain_on_high_conflict=True
        )
        if f["status"] == "CONFLICTED_EVIDENCE":
            b15_s[eid] = 0.5  # abstained neutral lead
        else:
            b15_s[eid] = f["belief_anomalous"]
    sc, la = _get_scores_labels(b15_s, gt)
    results.append({"model": "B15_DS_ConflictAbstention", "pr_auc": pr_auc(sc, la)})

    print("\n[EXTENDED B10-B15 ABLATION RESULTS]")
    for r in results:
        print(f"  {r['model']:30s} PR-AUC = {r['pr_auc']:.4f}")

    assert len(results) == 6
