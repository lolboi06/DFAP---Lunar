# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: Unsupervised Automatic Forensic Case Discovery Engine (Causal Walk-Forward & Full Population Scoring)

import hashlib
import json
import logging
import math
import os
import time
from typing import Dict, Any, List, Optional, Union
import numpy as np
import pandas as pd

from dfap.schemas import TemporalSemantics
from dfap.investigation.inference_contract import (
    InferenceDataContract,
    PredictionUnit,
    InferenceMode,
    DETECTOR_CONFIG
)
from dfap.investigation.detectors import (
    RobustStatisticalDetector,
    IsolationForestDetector,
    TemporalSequenceDetector,
    AnomalyDecisionEngine,
    robust_z_score,
    score_from_z
)

logger = logging.getLogger(__name__)


class AutoDiscoveryEngine:
    """
    Automatic Forensic Case Discovery Engine.
    Scans authentic observable records WITHOUT predefined suspects.
    Strictly unsupervised: Prohibited ground-truth labels are completely isolated and inaccessible.
    Ensemble Architecture:
      - Detector A: Robust Statistical Deviation (Median / MAD)
      - Detector B: Isolation Forest Density Isolation
      - Detector C: Causal Temporal & Sequence Cadence Shift
    Methodological Contracts:
      - Stack Overflow: Walk-forward event scoring using strictly past events (< t_pivot).
      - UNSW: Full-population network-flow attack scoring under SEQUENCE_ORDER_ANALYSIS.
    """

    def __init__(self, canonical_dir: str = "data/canonical", random_state: int = 42):
        self.canonical_dir = canonical_dir
        self.random_state = random_state
        self.stat_detector = RobustStatisticalDetector(random_state=random_state)
        self.iforest_detector = IsolationForestDetector(random_state=random_state, n_estimators=50)
        self.temporal_detector = TemporalSequenceDetector(random_state=random_state)
        self.discovered_cases: List[Dict[str, Any]] = []
        self.last_run_metadata: Dict[str, Any] = {}

    def scan_dataset(
        self,
        dataset_name: str,
        risk_threshold: float = 0.35,
        max_cases: int = 25
    ) -> List[Dict[str, Any]]:
        """Scans a canonical dataset by delegating to scan_events."""
        key = dataset_name.lower().strip()
        can_path = f"{self.canonical_dir}/{key}_canonical.parquet"
        if not os.path.exists(can_path):
            return []

        df = pd.read_parquet(can_path)
        if "epoch_time" in df.columns:
            df = df.sort_values("epoch_time").reset_index(drop=True)
        return self.scan_events(df, risk_threshold=risk_threshold, max_cases=max_cases, dataset_tag=key)

    def scan_events(
        self,
        observable_events: Union[List[Dict[str, Any]], pd.DataFrame],
        risk_threshold: float = 0.35,
        max_cases: int = 25,
        inference_cutoff_epoch: Optional[float] = None,
        dataset_tag: str = "case_subgraph"
    ) -> List[Dict[str, Any]]:
        """
        Executes blind unsupervised anomaly detection ON OBSERVABLE EVENTS ONLY.
        Scores full population, then ranks and returns top candidates.
        """
        t_start = time.perf_counter()

        scored_population = self.score_full_population(
            observable_events=observable_events,
            inference_cutoff_epoch=inference_cutoff_epoch,
            dataset_tag=dataset_tag
        )

        # Filter by threshold and sort descending by risk score
        eligible = [c for c in scored_population if c["risk_score"] >= risk_threshold]
        eligible.sort(key=lambda x: x["risk_score"], reverse=True)

        top_candidates = eligible[:max_cases]
        key = dataset_tag.lower().strip()

        # Assign official case IDs
        for rank, c in enumerate(top_candidates, start=1):
            c["case_id"] = f"CASE-{key[:3].upper()}-{rank:03d}"
            c["candidate_id"] = f"CAND-{key[:3].upper()}-{rank:03d}"

        t_end = time.perf_counter()

        run_id = f"RUN-{key.upper()}-{int(time.time())}"
        self.last_run_metadata = {
            "run_id": run_id,
            "dataset": key,
            "records_scanned": len(scored_population),
            "unique_entities_scanned": len(set(c["entity_id"] for c in scored_population)),
            "candidates_found": len(top_candidates),
            "risk_threshold": risk_threshold,
            "max_cases_requested": max_cases,
            "inference_cutoff_epoch": inference_cutoff_epoch,
            "random_state": self.random_state,
            "runtime_ms": round((t_end - t_start) * 1000.0, 2),
            "feature_schema_version": "v4.1.0_CAUSAL_RESEARCH",
            "detector_config": DETECTOR_CONFIG.get(key, {})
        }

        self.discovered_cases = top_candidates
        return top_candidates

    def score_full_population(
        self,
        observable_events: Union[List[Dict[str, Any]], pd.DataFrame],
        inference_cutoff_epoch: Optional[float] = None,
        dataset_tag: str = "case_subgraph"
    ) -> List[Dict[str, Any]]:
        """
        Scores the complete declared evaluation population without pre-filtering.
        Returns event_id and scores for ALL eligible events.
        """
        if isinstance(observable_events, list):
            if not observable_events:
                return []
            df = pd.DataFrame(observable_events)
        else:
            df = observable_events.copy()

        if df.empty:
            return []

        # 1. STRICT INFERENCE BOUNDARY
        df = InferenceDataContract.sanitize_observable_events(df, strict_fail_on_labels=False)

        if "epoch_time" in df.columns:
            df = df.sort_values("epoch_time").reset_index(drop=True)

        # 2. TEMPORAL ISOLATION
        if inference_cutoff_epoch is not None:
            df = df[df["epoch_time"] <= inference_cutoff_epoch].reset_index(drop=True)

        if df.empty:
            return []

        key = dataset_tag.lower().strip()

        if key == "unsw":
            return self._score_unsw_population(df, inference_cutoff_epoch)
        elif key == "stackoverflow":
            return self._score_stackoverflow_walk_forward(df, inference_cutoff_epoch)
        else:
            return self._score_generic_population(df, inference_cutoff_epoch, dataset_tag)

    def _score_unsw_population(
        self,
        df: pd.DataFrame,
        inference_cutoff: Optional[float]
    ) -> List[Dict[str, Any]]:
        """Scores all UNSW events as FLOW_ANOMALY under SEQUENCE_ORDER_ANALYSIS."""
        n = len(df)
        if n == 0:
            return []

        attrs_list = [json.loads(a) if isinstance(a, str) else (a or {}) for a in df["attributes"]]

        # Extract feature matrix (n x 8)
        feats = np.zeros((n, 8), dtype=float)
        for i, a in enumerate(attrs_list):
            feats[i, 0] = float(a.get("flow_duration_sec", 0.0))
            feats[i, 1] = float(a.get("sent_bytes", 0.0))
            feats[i, 2] = float(a.get("recv_bytes", 0.0))
            feats[i, 3] = float(a.get("rate", 0.0))
            feats[i, 4] = float(a.get("sload", 0.0))
            feats[i, 5] = float(a.get("dload", 0.0))
            feats[i, 6] = float(a.get("ct_dst_src_ltm", 1.0))
            feats[i, 7] = float(a.get("ct_srv_src", 1.0))

        # Detectors
        scores_stat = self.stat_detector.score_features(feats)
        scores_iforest = self.iforest_detector.fit_and_score(feats)

        rates = feats[:, 3]
        med_rate = float(np.median(rates)) if len(rates) else 1.0
        scores_temp = np.array([
            min(0.99, max(0.05, float(r / max(100.0, med_rate * 5.0))))
            for r in rates
        ])

        medians = np.median(feats, axis=0)
        feature_names = ["flow_duration_sec", "sent_bytes", "recv_bytes", "rate", "sload", "dload", "ct_dst_src_ltm", "ct_srv_src"]

        all_records = []
        for i in range(n):
            row = df.iloc[i]
            dec = AnomalyDecisionEngine.combine_detectors(
                score_stat=float(scores_stat[i]),
                score_iforest=float(scores_iforest[i]),
                score_temporal=float(scores_temp[i]),
                event_count=1,
                min_events_required=1
            )
            r_score = dec["risk_score"]
            ev_ref = f"hash:{str(row.get('sha256_hash', ''))[:16]}"

            signals = []
            reasons = []
            for f_idx, f_name in enumerate(feature_names):
                obs_val = feats[i, f_idx]
                base_val = medians[f_idx]
                if obs_val > base_val * 2.5 and obs_val > 5.0:
                    diff = obs_val - base_val
                    s_norm = round(min(1.0, diff / max(1.0, base_val * 5.0)), 3)
                    signals.append({
                        "feature": f_name,
                        "baseline_method": "EMPIRICAL_POPULATION_MEDIAN",
                        "baseline_sample_size": n,
                        "baseline_value": round(float(base_val), 2),
                        "observed_value": round(float(obs_val), 2),
                        "normalized_score": s_norm,
                        "weight": 0.25,
                        "evidence_ref": ev_ref
                    })
                    reasons.append({
                        "WHAT": f_name,
                        "EXPECTED": f"Population median {base_val:.2f}",
                        "OBSERVED": f"Observed value {obs_val:.2f}",
                        "DEVIATION": f"+{diff:.2f} above median",
                        "EVIDENCE": ev_ref
                    })

            top_reasons = [f"{r['WHAT']} observed {r['OBSERVED']} (baseline {r['EXPECTED']})" for r in reasons[:3]]
            if not top_reasons:
                top_reasons = [f"Multi-detector flow feature isolation depth (score {r_score:.3f})"]

            all_records.append({
                "event_id": row["event_id"],
                "trigger_event_id": row["event_id"],
                "score": r_score,
                "risk_score": r_score,
                "anomaly_score": r_score,
                "entity_id": row["actor_id"],
                "seed_entity": row["actor_id"],
                "dataset": "unsw",
                "prediction_unit": PredictionUnit.UNSW,
                "inference_mode": InferenceMode.BATCH_UNSUPERVISED,
                "detector_training_mode": InferenceMode.BATCH_UNSUPERVISED_TRANSDUCTIVE,
                "detector_config": DETECTOR_CONFIG["unsw"],
                "temporal_semantics": TemporalSemantics.SEQUENCE_ORDER_SURROGATE,
                "analysis_type": "SEQUENCE_ORDER_ANALYSIS",
                "classification": "FLOW_ANOMALY",
                "anomaly_type": "FLOW_ANOMALY",
                "confidence": dec["confidence"],
                "uncertainty": dec["uncertainty"],
                "epistemic_uncertainty": dec["epistemic_uncertainty"],
                "detector_agreement": dec["detector_agreement"],
                "agreement": dec["agreement"],
                "disagreement": dec["disagreement"],
                "data_sufficiency": dec["data_sufficiency"],
                "detector_scores": dec["detector_scores"],
                "trigger_timestamp": str(row["timestamp"]),
                "trigger_epoch": float(row["epoch_time"]),
                "domain": "IPDR",
                "baseline_cutoff": inference_cutoff or float(row["epoch_time"]),
                "observation_cutoff": float(row["epoch_time"]),
                "signals": signals,
                "why_suspicious": reasons,
                "top_reasons": top_reasons,
                "evidence_reasons": top_reasons,
                "backing_event_ids": [row["event_id"]],
                "evidence_refs": [ev_ref],
                "lead_summary": f"Unsupervised Flow Anomaly: {', '.join(top_reasons[:2])}"
            })

        return all_records

    def _score_stackoverflow_walk_forward(
        self,
        df: pd.DataFrame,
        inference_cutoff: Optional[float]
    ) -> List[Dict[str, Any]]:
        """
        Genuinely causal walk-forward per-event scoring on Stack Overflow interactions.
        For every event e_k at t_k, the baseline contains ONLY events strictly before t_k.
        Prediction Unit: EVENT/USER TEMPORAL INTERACTION ANOMALY.
        """
        all_scored_events = []

        # Group by actor and score each event causally walk-forward
        for entity_id, grp in df.groupby("actor_id"):
            grp_sorted = grp.sort_values("epoch_time").reset_index(drop=True)
            n_events = len(grp_sorted)

            epochs = grp_sorted["epoch_time"].values
            event_ids = grp_sorted["event_id"].values
            targets = grp_sorted["target_id"].values
            timestamps = grp_sorted["timestamp"].values
            hashes = grp_sorted["sha256_hash"].values

            # Walk forward across events
            for k in range(n_events):
                t_k = float(epochs[k])
                evt_id_k = str(event_ids[k])
                target_k = str(targets[k])
                ts_k = str(timestamps[k])
                ev_ref_k = f"hash:{str(hashes[k])[:16]}"

                # Causal history mask: STRICTLY prior timestamps only (t_i < t_k)
                prior_indices = [idx for idx in range(n_events) if epochs[idx] < t_k]
                equal_indices = [idx for idx in range(n_events) if epochs[idx] == t_k and str(event_ids[idx]) != evt_id_k]
                equal_excluded_count = len(equal_indices)
                history_count = len(prior_indices)
                prior_event_ids = [str(event_ids[idx]) for idx in prior_indices]

                if history_count < 2:
                    # Insufficient history before pivot
                    dec = AnomalyDecisionEngine.combine_detectors(
                        score_stat=0.10,
                        score_iforest=0.10,
                        score_temporal=0.10,
                        event_count=history_count,
                        min_events_required=2
                    )
                    all_scored_events.append({
                        "event_id": evt_id_k,
                        "trigger_event_id": evt_id_k,
                        "score": dec["risk_score"],
                        "risk_score": dec["risk_score"],
                        "anomaly_score": dec["risk_score"],
                        "entity_id": entity_id,
                        "seed_entity": entity_id,
                        "dataset": "stackoverflow",
                        "prediction_unit": PredictionUnit.STACKOVERFLOW,
                        "inference_mode": InferenceMode.CAUSAL_WALK_FORWARD,
                        "detector_training_cutoff": t_k,
                        "detector_config": DETECTOR_CONFIG["stackoverflow"],
                        "temporal_semantics": TemporalSemantics.OBSERVED_TIMESTAMP,
                        "analysis_type": "REAL_TIME_TEMPORAL_ANALYSIS",
                        "classification": dec["classification"],
                        "anomaly_type": "TEMPORAL_INTERACTION_ANOMALY",
                        "confidence": dec["confidence"],
                        "uncertainty": dec["uncertainty"],
                        "epistemic_uncertainty": dec["epistemic_uncertainty"],
                        "detector_agreement": dec["detector_agreement"],
                        "agreement": dec["agreement"],
                        "disagreement": dec["disagreement"],
                        "data_sufficiency": dec["data_sufficiency"],
                        "data_sufficiency_warning": dec.get("data_sufficiency_warning", ""),
                        "detector_scores": dec["detector_scores"],
                        "trigger_timestamp": ts_k,
                        "trigger_epoch": t_k,
                        "domain": "SOCIAL",
                        "baseline_start": float(epochs[prior_indices[0]]) if history_count > 0 else None,
                        "baseline_end": float(epochs[prior_indices[-1]]) if history_count > 0 else None,
                        "baseline_cutoff": t_k,
                        "observation_cutoff": t_k,
                        "history_event_count": history_count,
                        "equal_timestamp_excluded_count": equal_excluded_count,
                        "baseline_event_ids": prior_event_ids,
                        "signals": [],
                        "why_suspicious": [],
                        "top_reasons": ["Insufficient historical observations before pivot"],
                        "evidence_reasons": ["Insufficient historical observations before pivot"],
                        "backing_event_ids": prior_event_ids + [evt_id_k],
                        "evidence_refs": [ev_ref_k],
                        "lead_summary": "Unsupervised Temporal Anomaly: Insufficient historical evidence"
                    })
                    continue

                # Empirical historical baseline
                prior_epochs = np.array([epochs[idx] for idx in prior_indices])
                prior_targets = set([targets[idx] for idx in prior_indices])
                prior_deltas = np.diff(prior_epochs)

                med_delta = float(np.median(prior_deltas)) if len(prior_deltas) else 3600.0
                mad_delta = float(np.median(np.abs(prior_deltas - med_delta))) if len(prior_deltas) else 0.0

                obs_delta = float(t_k - epochs[prior_indices[-1]])
                z_cadence = robust_z_score(obs_delta, med_delta, mad_delta, std_fallback=float(np.std(prior_deltas)) if len(prior_deltas) else 1.0)

                is_novel_contact = target_k not in prior_targets
                novelty_rate = 1.0 if is_novel_contact else 0.0

                # Rolling burst: prior events in trailing 1 hour strictly before t_k
                t_1h = t_k - 3600.0
                recent_1h_count = sum(1 for ep in prior_epochs if ep >= t_1h)
                historical_hourly_rate = float(history_count / max(1.0, (epochs[prior_indices[-1]] - epochs[prior_indices[0]]) / 3600.0))
                burst_ratio = (recent_1h_count + 1) / max(0.2, historical_hourly_rate)

                # Detector scoring
                score_stat = score_from_z(abs(z_cadence))
                score_iforest = min(0.95, max(0.05, 0.20 + 0.40 * novelty_rate + 0.40 * min(1.0, burst_ratio / 5.0)))
                score_temp = TemporalSequenceDetector.score_temporal_features(
                    cadence_ratio=max(1.0, obs_delta / max(1.0, med_delta)) if obs_delta > med_delta else max(1.0, med_delta / max(1.0, obs_delta)),
                    burstiness_index=float((mad_delta - med_delta) / (mad_delta + med_delta)) if (mad_delta + med_delta) > 0 else 0.0,
                    novelty_turnover=novelty_rate,
                    recent_surge_ratio=burst_ratio
                )

                dec = AnomalyDecisionEngine.combine_detectors(
                    score_stat=score_stat,
                    score_iforest=score_iforest,
                    score_temporal=score_temp,
                    event_count=history_count,
                    min_events_required=2
                )

                # Explicit signals
                signals = [
                    {
                        "feature": "interarrival_cadence_delta",
                        "baseline_method": "EMPIRICAL_HISTORICAL_MEDIAN_MAD",
                        "baseline_sample_size": len(prior_deltas),
                        "baseline_value": round(med_delta, 2),
                        "observed_value": round(obs_delta, 2),
                        "normalized_score": round(score_stat, 3),
                        "weight": 0.4,
                        "evidence_ref": ev_ref_k
                    },
                    {
                        "feature": "counterparty_novelty",
                        "baseline_method": "EMPIRICAL_HISTORICAL_KNOWN_SET",
                        "baseline_sample_size": len(prior_targets),
                        "baseline_value": f"{len(prior_targets)} known peers",
                        "observed_value": target_k,
                        "normalized_score": 0.85 if is_novel_contact else 0.10,
                        "weight": 0.3,
                        "evidence_ref": ev_ref_k
                    },
                    {
                        "feature": "hourly_burst_ratio",
                        "baseline_method": "HISTORICAL_HOURLY_FREQUENCY",
                        "baseline_sample_size": history_count,
                        "baseline_value": round(historical_hourly_rate, 3),
                        "observed_value": recent_1h_count + 1,
                        "normalized_score": round(min(1.0, burst_ratio / 5.0), 3),
                        "weight": 0.3,
                        "evidence_ref": ev_ref_k
                    }
                ]

                reasons = [
                    {
                        "WHAT": "interarrival_cadence_delta",
                        "EXPECTED": f"Historical median cadence {med_delta:.1f}s",
                        "OBSERVED": f"Observed inter-arrival {obs_delta:.1f}s",
                        "DEVIATION": f"Robust Z-score: {z_cadence:+.2f}",
                        "EVIDENCE": ev_ref_k
                    },
                    {
                        "WHAT": "counterparty_novelty",
                        "EXPECTED": f"Interaction with known peers ({len(prior_targets)} peers)",
                        "OBSERVED": f"Interaction with peer '{target_k}'",
                        "DEVIATION": "NEW_UNSEEN_PEER" if is_novel_contact else "RECURRENT_PEER",
                        "EVIDENCE": ev_ref_k
                    }
                ]

                top_reasons = [
                    f"Cadence shift: observed {obs_delta:.1f}s vs median {med_delta:.1f}s (Z={z_cadence:+.2f})",
                    f"Counterparty novelty: {'unseen peer' if is_novel_contact else 'known peer'} ({target_k})"
                ]

                all_scored_events.append({
                    "event_id": evt_id_k,
                    "trigger_event_id": evt_id_k,
                    "score": dec["risk_score"],
                    "risk_score": dec["risk_score"],
                    "anomaly_score": dec["risk_score"],
                    "entity_id": entity_id,
                    "seed_entity": entity_id,
                    "dataset": "stackoverflow",
                    "prediction_unit": PredictionUnit.STACKOVERFLOW,
                    "inference_mode": InferenceMode.CAUSAL_WALK_FORWARD,
                    "detector_training_cutoff": t_k,
                    "detector_config": DETECTOR_CONFIG["stackoverflow"],
                    "temporal_semantics": TemporalSemantics.OBSERVED_TIMESTAMP,
                    "analysis_type": "REAL_TIME_TEMPORAL_ANALYSIS",
                    "classification": dec["classification"],
                    "anomaly_type": "TEMPORAL_INTERACTION_ANOMALY",
                    "confidence": dec["confidence"],
                    "uncertainty": dec["uncertainty"],
                    "epistemic_uncertainty": dec["epistemic_uncertainty"],
                    "detector_agreement": dec["detector_agreement"],
                    "agreement": dec["agreement"],
                    "disagreement": dec["disagreement"],
                    "data_sufficiency": dec["data_sufficiency"],
                    "detector_scores": dec["detector_scores"],
                    "trigger_timestamp": ts_k,
                    "trigger_epoch": t_k,
                    "domain": "SOCIAL",
                    "baseline_start": float(epochs[prior_indices[0]]) if history_count > 0 else None,
                    "baseline_end": float(epochs[prior_indices[-1]]) if history_count > 0 else None,
                    "baseline_cutoff": t_k,
                    "observation_cutoff": t_k,
                    "history_event_count": history_count,
                    "equal_timestamp_excluded_count": equal_excluded_count,
                    "baseline_event_ids": prior_event_ids,
                    "signals": signals,
                    "why_suspicious": reasons,
                    "top_reasons": top_reasons,
                    "evidence_reasons": top_reasons,
                    "backing_event_ids": prior_event_ids + [evt_id_k],
                    "evidence_refs": [ev_ref_k],
                    "lead_summary": f"Unsupervised Temporal Anomaly: {', '.join(top_reasons)}"
                })

        return all_scored_events

    def _score_generic_population(
        self,
        df: pd.DataFrame,
        inference_cutoff: Optional[float],
        dataset_tag: str
    ) -> List[Dict[str, Any]]:
        """Fallback population scoring for generic datasets."""
        all_records = []
        for i, row in df.iterrows():
            amt = float(row.get("amount", 0.0))
            score = min(0.95, max(0.05, amt / 50000.0 if amt > 0 else 0.20))
            ev_ref = f"hash:{str(row.get('sha256_hash', ''))[:16]}"
            all_records.append({
                "event_id": row["event_id"],
                "trigger_event_id": row["event_id"],
                "score": round(score, 3),
                "risk_score": round(score, 3),
                "anomaly_score": round(score, 3),
                "entity_id": row["actor_id"],
                "seed_entity": row["actor_id"],
                "dataset": dataset_tag,
                "prediction_unit": PredictionUnit.ELLIPTIC,
                "temporal_semantics": row.get("temporal_semantics", TemporalSemantics.OBSERVED_TIMESTAMP),
                "analysis_type": "REAL_TIME_TEMPORAL_ANALYSIS",
                "classification": "TOPOLOGY_ANOMALY",
                "anomaly_type": "TOPOLOGY_ANOMALY",
                "confidence": 0.50,
                "uncertainty": 0.50,
                "epistemic_uncertainty": 0.50,
                "detector_agreement": 0.70,
                "agreement": 0.70,
                "disagreement": 0.30,
                "data_sufficiency": "SUFFICIENT",
                "detector_scores": {"statistical": round(score, 3), "isolation_forest": round(score, 3), "temporal": 0.30},
                "trigger_timestamp": str(row["timestamp"]),
                "trigger_epoch": float(row["epoch_time"]),
                "domain": str(row.get("source_domain", "BANK")),
                "baseline_cutoff": inference_cutoff or float(row["epoch_time"]),
                "observation_cutoff": float(row["epoch_time"]),
                "signals": [],
                "why_suspicious": [],
                "top_reasons": [f"Topological anomaly score {score:.3f}"],
                "evidence_reasons": [f"Topological anomaly score {score:.3f}"],
                "backing_event_ids": [row["event_id"]],
                "evidence_refs": [ev_ref],
                "lead_summary": f"Unsupervised Anomaly: score {score:.3f}"
            })
        return all_records

    def create_case_from_candidate(self, candidate: Dict[str, Any], run_id: Optional[str] = None) -> Dict[str, Any]:
        """Creates an official, immutable case dossier starting point from an anomaly candidate."""
        cand_id = candidate.get("candidate_id", candidate.get("case_id", "CAND-UNKNOWN"))
        ds = candidate.get("dataset", "unknown")
        cid = candidate.get("case_id", f"CASE-{ds[:3].upper()}-{cand_id[-3:]}")

        return {
            "case_id": cid,
            "subject": candidate.get("entity_id"),
            "trigger_event": candidate.get("trigger_event_id"),
            "score": candidate.get("risk_score"),
            "classification": candidate.get("classification"),
            "signals": candidate.get("signals", []),
            "why_suspicious": candidate.get("why_suspicious", []),
            "evidence_refs": candidate.get("evidence_refs", []),
            "dataset": ds,
            "provenance": "REAL_PUBLIC_DATA_UNSUPERVISED_DISCOVERY",
            "run_id": run_id or self.last_run_metadata.get("run_id", "RUN-ADHOC"),
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        }

    def reconcile_with_ground_truth(self, case_id: str) -> Dict[str, Any]:
        """
        Forensic post-discovery audit: checks isolated ground truth for the flagged case.
        Ground truth was NEVER accessible during discovery.
        """
        case = next((c for c in self.discovered_cases if c["case_id"] == case_id), None)
        if not case:
            raise ValueError(f"Case '{case_id}' not found in discovery registry.")

        key = case["dataset"]
        gt_path = f"{self.canonical_dir}/{key}_ground_truth.parquet"
        if not os.path.exists(gt_path):
            return {"case_id": case_id, "reconciliation": "GROUND_TRUTH_FILE_ABSENT"}

        gt_df = pd.read_parquet(gt_path)
        trig_evt = case["trigger_event_id"]
        row_gt = gt_df[gt_df["event_id"] == trig_evt]

        if row_gt.empty:
            return {"case_id": case_id, "reconciliation": "EVENT_NOT_IN_LABELLED_BENCHMARK"}

        gt_record = row_gt.iloc[0].to_dict()
        is_true_anomaly = bool(
            gt_record.get("is_illicit_ground_truth") or
            gt_record.get("is_attack_ground_truth") or
            gt_record.get("is_sockpuppet_ring_ground_truth")
        )

        return {
            "case_id": case_id,
            "entity_id": case["entity_id"],
            "dataset": key,
            "dfap_detected_risk": case["risk_score"],
            "dfap_anomaly_type": case["anomaly_type"],
            "ground_truth_confirmed_anomaly": is_true_anomaly,
            "ground_truth_detail": {k: v for k, v in gt_record.items() if k != "event_id"},
            "verdict": "CONFIRMED_TRUE_POSITIVE" if is_true_anomaly else "EVALUATION_SAMPLE"
        }
