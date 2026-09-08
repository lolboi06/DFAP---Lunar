# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
"""
M3 Pipeline — Orchestrates M8 Baseline → M9 Anomaly → M10 Sequence → M11 Fusion.

Consumes (read-only):
  output/canonical_events.parquet
  output/resolved_entities.parquet
  output/provenance_ledger.parquet
  output/graph_features.parquet
  output/telecom_features.parquet
  output/financial_features.parquet
  output/social_features.parquet

Produces:
  output/m3/baselines.parquet
  output/m3/anomalies/anomalies.parquet
  output/m3/sequences/sequence_matches.parquet
  output/m3/sequences/pattern_matches.parquet
  output/m3/motif_catalog.json
  output/m3/findings/findings.parquet
  output/m3/m3_manifest.json
"""
import hashlib
import json
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from dfap.m3.baseline import EntityBaselineService
from dfap.m3.anomaly import AnomalyEngine
from dfap.m3.sequence import SequenceEngine, DEFAULT_MOTIF_CATALOG
from dfap.m3.fusion import FusionEngine

MODEL_VERSION = "M3_PIPELINE_v1.0"
RANDOM_SEED = 42
SCHEMA_VERSION = "WP3.1"


class M3Pipeline:
    """Full M8–M11 research pipeline."""

    def __init__(
        self,
        confirmed_threshold: float = 0.85,
        random_state: int = RANDOM_SEED,
        config: Optional[Dict] = None,
    ):
        self.confirmed_threshold = confirmed_threshold
        self.random_state = random_state
        self.config = config or {}

        self.baseline_svc = EntityBaselineService()
        self.anomaly_engine = AnomalyEngine(random_state=random_state)
        self.sequence_engine = SequenceEngine(random_state=random_state)
        self.fusion_engine = FusionEngine(random_state=random_state)

    def run(self, input_dir: str, output_dir: str) -> Dict[str, Any]:
        """Execute the full M3 pipeline end-to-end."""
        run_id = f"M3RUN_{uuid.uuid4().hex[:10].upper()}"
        start_ts = datetime.now(timezone.utc).isoformat()
        t0 = time.perf_counter()

        print(f"[M3] Starting pipeline run {run_id}")
        os.makedirs(output_dir, exist_ok=True)
        os.makedirs(os.path.join(output_dir, "anomalies"), exist_ok=True)
        os.makedirs(os.path.join(output_dir, "sequences"), exist_ok=True)
        os.makedirs(os.path.join(output_dir, "findings"), exist_ok=True)

        # ── Load WP1/WP2 inputs ────────────────────────────────────────────────
        print("[M3] Loading WP1/WP2 frozen artifacts...")
        ev_df   = pd.read_parquet(os.path.join(input_dir, "canonical_events.parquet"))
        ent_df  = pd.read_parquet(os.path.join(input_dir, "resolved_entities.parquet"))
        gf_df   = pd.read_parquet(os.path.join(input_dir, "graph_features.parquet"))
        tel_df  = pd.read_parquet(os.path.join(input_dir, "telecom_features.parquet"))
        fin_df  = pd.read_parquet(os.path.join(input_dir, "financial_features.parquet"))
        soc_df  = pd.read_parquet(os.path.join(input_dir, "social_features.parquet"))

        # Verify WP1 not modified
        wp1_hashes = {}
        for fname in ["canonical_events.parquet", "resolved_entities.parquet",
                      "provenance_ledger.parquet"]:
            p = os.path.join(input_dir, fname)
            if os.path.exists(p):
                wp1_hashes[fname] = self._sha256_file(p)

        all_features = pd.concat([gf_df, tel_df, fin_df, soc_df], ignore_index=True)

        entity_raw_map = {
            row["canonical_entity_id"]: row["raw_identifier"]
            for _, row in ent_df.iterrows()
        } if "raw_identifier" in ent_df.columns else {}

        # ── M8: Behavioral Baseline ────────────────────────────────────────────
        print("[M8] Computing entity behavioral baselines...")
        t_m8 = time.perf_counter()
        baselines_df = self.baseline_svc.fit_baselines(all_features)
        t_m8 = time.perf_counter() - t_m8
        bl_path = os.path.join(output_dir, "baselines.parquet")
        baselines_df.to_parquet(bl_path, index=False)
        print(f"[M8] {len(baselines_df)} baseline records in {t_m8*1000:.1f}ms")

        # ── M9: Anomaly Engine ─────────────────────────────────────────────────
        print("[M9] Fitting IsolationForest and scoring anomalies...")
        t_m9 = time.perf_counter()
        feature_matrix = self._build_feature_matrix(all_features)
        if len(feature_matrix) >= 5:
            self.anomaly_engine.fit(feature_matrix)
        anomalies_df = self.anomaly_engine.score_entities(
            baselines_df, gf_df, tel_df, fin_df, soc_df, ev_df, entity_raw_map=entity_raw_map
        )
        t_m9 = time.perf_counter() - t_m9
        ano_path = os.path.join(output_dir, "anomalies", "anomalies.parquet")
        anomalies_df.to_parquet(ano_path, index=False)
        print(f"[M9] {len(anomalies_df)} anomaly records in {t_m9*1000:.1f}ms")

        # ── M10: Sequence Engine ───────────────────────────────────────────────
        print("[M10] Running temporal sequence analysis...")
        t_m10 = time.perf_counter()
        self.sequence_engine.fit(ev_df)

        all_motif_matches = []
        all_dtw_results = []
        all_pattern_rows = []

        entity_ids = ent_df["canonical_entity_id"].tolist()
        for eid in entity_ids:
            actor_mask = ev_df["actor_id"] == eid
            e_events = ev_df[actor_mask].sort_values("timestamp")
            result = self.sequence_engine.analyze(eid, ev_df)
            all_motif_matches.extend(result["motif_matches"])
            all_dtw_results.extend(result["dtw_results"])
            if not result["pattern_df"].empty:
                result["pattern_df"]["entity_id"] = eid
                all_pattern_rows.append(result["pattern_df"])

        motif_df = pd.DataFrame(all_motif_matches)
        dtw_df = pd.DataFrame(all_dtw_results)
        pattern_df = pd.concat(all_pattern_rows, ignore_index=True) if all_pattern_rows else pd.DataFrame()

        motif_df.to_parquet(os.path.join(output_dir, "sequences", "motif_matches.parquet"), index=False)
        dtw_df.to_parquet(os.path.join(output_dir, "sequences", "dtw_matches.parquet"), index=False) if not dtw_df.empty else None
        if not pattern_df.empty:
            pattern_df.to_parquet(os.path.join(output_dir, "sequences", "pattern_matches.parquet"), index=False)

        # Write motif catalog
        catalog_path = os.path.join(output_dir, "motif_catalog.json")
        with open(catalog_path, "w") as fh:
            json.dump(DEFAULT_MOTIF_CATALOG, fh, indent=2)

        t_m10 = time.perf_counter() - t_m10
        print(f"[M10] {len(all_motif_matches)} motif matches, {len(all_dtw_results)} DTW results in {t_m10*1000:.1f}ms")

        # ── M11: Fusion ────────────────────────────────────────────────────────
        print("[M11] Running cross-domain fusion...")
        t_m11 = time.perf_counter()
        findings = []

        anomaly_map = {}
        if not anomalies_df.empty:
            anomaly_map = {row["entity_id"]: row.to_dict()
                           for _, row in anomalies_df.iterrows()}

        for eid in entity_ids:
            ano = anomaly_map.get(eid, {})
            comp_scores_raw = json.loads(ano.get("component_scores", "{}")) if ano else {}

            # Build per-domain scores for fusion [0,1]
            tel_score = self._domain_score(tel_df, eid)
            fin_score = self._domain_score(fin_df, eid)
            soc_score = self._domain_score(soc_df, eid)
            beh_score = self._behavior_score(baselines_df, eid)
            gph_score = self._graph_score(gf_df, eid)
            tmp_score = self._temporal_score(motif_df, eid)

            domain_scores = {
                "telecom": tel_score,
                "financial": fin_score,
                "social": soc_score,
                "behavior": beh_score,
                "graph": gph_score,
                "temporal": tmp_score,
            }

            raw_id = entity_raw_map.get(eid, eid)
            e_events = ev_df[
                (ev_df["actor_id"] == eid) | (ev_df["actor_id"] == raw_id) |
                (ev_df["target_id"] == eid) | (ev_df["target_id"] == raw_id)
            ]
            ev_ids = e_events["event_id"].tolist()
            ev_hashes = e_events["sha256_hash"].tolist()
            ts_start = e_events["timestamp"].min() if not e_events.empty else ""
            ts_end = e_events["timestamp"].max() if not e_events.empty else ""

            entity_motif_matches = [m for m in all_motif_matches if m.get("entity_id") == eid]

            finding = self.fusion_engine.create_finding(
                entity_id=eid,
                domain_scores=domain_scores,
                anomaly_record=ano if ano else None,
                sequence_matches=entity_motif_matches,
                ts_start=ts_start,
                ts_end=ts_end,
                event_ids=ev_ids,
                evidence_refs=ev_hashes,
            )
            findings.append(finding)

        findings_df = pd.DataFrame(findings)
        findings_df.to_parquet(os.path.join(output_dir, "findings", "findings.parquet"), index=False)
        t_m11 = time.perf_counter() - t_m11
        print(f"[M11] {len(findings)} findings in {t_m11*1000:.1f}ms")

        t_total = time.perf_counter() - t0

        # ── Config hash & Governance Metadata (Section 17) ─────────────────────
        timestamps = ev_df["timestamp"].dropna().sort_values().tolist()
        t_min_str = timestamps[0] if timestamps else start_ts
        t_max_str = timestamps[-1] if timestamps else start_ts

        config_payload = {
            "schema_version": SCHEMA_VERSION,
            "pipeline_version": "1.0.0",
            "model_version": MODEL_VERSION,
            "feature_version": "WP2.1",
            "dataset_version": "WP1.1",
            "random_seed": self.random_state,
            "confirmed_threshold": self.confirmed_threshold,
        }
        config_hash = hashlib.sha256(
            json.dumps(config_payload, sort_keys=True).encode()
        ).hexdigest()

        manifest = {
            "run_id": run_id,
            "model_id": f"MDL_M3_{run_id}",
            "model_version": MODEL_VERSION,
            "pipeline_version": "1.0.0",
            "dataset_version": "WP1.1",
            "feature_version": "WP2.1",
            "schema_version": SCHEMA_VERSION,
            "config_hash": config_hash,
            "random_seed": self.random_state,
            "training_period": {"start": t_min_str, "end": t_max_str},
            "validation_period": {"start": t_min_str, "end": t_max_str},
            "test_period": {"start": t_min_str, "end": t_max_str},
            "calibration_period": {"start": t_min_str, "end": t_max_str},
            "wp1_hashes": wp1_hashes,
            "outputs": {
                "baselines": len(baselines_df),
                "anomalies": len(anomalies_df),
                "motif_matches": len(all_motif_matches),
                "dtw_results": len(all_dtw_results),
                "findings": len(findings),
            },
            "performance_ms": {
                "m8_baseline": round(t_m8 * 1000, 2),
                "m9_anomaly": round(t_m9 * 1000, 2),
                "m10_sequence": round(t_m10 * 1000, 2),
                "m11_fusion": round(t_m11 * 1000, 2),
                "total": round(t_total * 1000, 2),
            },
            "created_at": start_ts,
        }
        with open(os.path.join(output_dir, "m3_manifest.json"), "w") as fh:
            json.dump(manifest, fh, indent=2)

        # ── Operational Monitoring Report (Section 19) ────────────────────────
        n_findings = max(1, len(findings_df))
        anomaly_count = sum(1 for f in findings if f["status"] == "AI_GENERATED_LEAD" and f["composite_score"] >= 0.5)
        abstain_count = sum(1 for f in findings if f["status"] in ["CONFLICTED_EVIDENCE", "INSUFFICIENT_EVIDENCE"])
        high_conflict_count = sum(1 for f in findings if f.get("conflict_flag") == "HIGH_CONFLICT")

        comp_scores = findings_df["composite_score"].dropna().tolist() if not findings_df.empty else [0.0]

        # Missing domain rate across findings
        missing_domain_counts = 0
        for f in findings:
            try:
                m_doms = json.loads(f.get("missing_domains", "[]"))
                missing_domain_counts += len(m_doms)
            except Exception:
                pass
        total_possible_domain_slots = n_findings * 6  # 6 tracked domains

        monitoring_report = {
            "report_id": f"MON_{uuid.uuid4().hex[:10].upper()}",
            "run_id": run_id,
            "created_at": start_ts,
            "model_version": MODEL_VERSION,
            "anomaly_rate": round(anomaly_count / n_findings, 4),
            "missing_domain_rate": round(missing_domain_counts / max(1, total_possible_domain_slots), 4),
            "conflict_rate": round(high_conflict_count / n_findings, 4),
            "abstention_rate": round(abstain_count / n_findings, 4),
            "score_distribution": {
                "min": round(float(np.min(comp_scores)), 4),
                "q25": round(float(np.percentile(comp_scores, 25)), 4),
                "median": round(float(np.median(comp_scores)), 4),
                "q75": round(float(np.percentile(comp_scores, 75)), 4),
                "max": round(float(np.max(comp_scores)), 4),
                "mean": round(float(np.mean(comp_scores)), 4),
                "std": round(float(np.std(comp_scores)), 4),
            },
            "feature_missingness": {
                "telecom_features": int(tel_df.empty),
                "financial_features": int(fin_df.empty),
                "social_features": int(soc_df.empty),
                "graph_features": int(gf_df.empty),
            },
            "baseline_drift": {
                "cold_start_count": int((baselines_df["baseline_status"] == "COLD_START").sum()) if not baselines_df.empty else 0,
                "low_history_count": int((baselines_df["baseline_status"] == "LOW_HISTORY").sum()) if not baselines_df.empty else 0,
                "stable_baseline_count": int((baselines_df["baseline_status"] == "STABLE_BASELINE").sum()) if not baselines_df.empty else 0,
            },
            "model_latency": {
                "m8_ms": round(t_m8 * 1000, 2),
                "m9_ms": round(t_m9 * 1000, 2),
                "m10_ms": round(t_m10 * 1000, 2),
                "m11_ms": round(t_m11 * 1000, 2),
                "total_ms": round(t_total * 1000, 2),
            }
        }
        with open(os.path.join(output_dir, "monitoring_report.json"), "w") as fh:
            json.dump(monitoring_report, fh, indent=2)

        print(f"[M3] Complete in {t_total*1000:.1f}ms. Monitoring report exported.")
        return manifest

    # ── helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _sha256_file(p: str) -> str:
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                h.update(chunk)
        return h.hexdigest()

    @staticmethod
    def _build_feature_matrix(features_df: pd.DataFrame) -> pd.DataFrame:
        """Pivot features to wide format for IsolationForest."""
        if features_df.empty:
            return pd.DataFrame()
        try:
            wide = features_df.pivot_table(
                index="entity_id", columns="feature_name",
                values="feature_value", aggfunc="mean"
            ).fillna(0.0)
            return wide
        except Exception:
            return pd.DataFrame()

    @staticmethod
    def _domain_score(domain_df: pd.DataFrame, entity_id: str) -> Optional[float]:
        """Derive a [0,1] domain anomaly score from feature values relative to domain baseline."""
        if domain_df.empty or "entity_id" not in domain_df.columns:
            return None
        e = domain_df[domain_df["entity_id"] == entity_id]
        if e.empty:
            return None

        scores = []
        for feat_name, group in domain_df.groupby("feature_name"):
            e_feat = e[e["feature_name"] == feat_name]
            if not e_feat.empty:
                val = float(e_feat["feature_value"].iloc[0])
                all_vals = group["feature_value"].values
                med = float(np.median(all_vals))
                mad = float(np.median(np.abs(all_vals - med)))
                scale = 1.4826 * mad + 1e-6
                rz = abs(val - med) / scale
                scores.append(min(1.0, rz / 5.0))
        return float(np.max(scores)) if scores else 0.0

    @staticmethod
    def _behavior_score(baselines_df: pd.DataFrame, entity_id: str) -> Optional[float]:
        """Map max robust-Z to [0,1] behavior anomaly score."""
        if baselines_df.empty:
            return None
        e = baselines_df[
            (baselines_df["entity_id"] == entity_id) &
            (baselines_df["baseline_status"] != "COLD_START")
        ]
        if e.empty:
            return None
        max_rz = float(e["robust_z"].abs().max())
        return float(np.clip(max_rz / 10.0, 0.0, 1.0))

    @staticmethod
    def _graph_score(gf_df: pd.DataFrame, entity_id: str) -> Optional[float]:
        """Normalised graph structural score."""
        if gf_df.empty:
            return None
        e = gf_df[gf_df["entity_id"] == entity_id]
        if e.empty:
            return None
        gv = {row["feature_name"]: float(row["feature_value"]) for _, row in e.iterrows()}
        raw = (
            gv.get("degree", 0) / 10.0 +
            gv.get("shared_counterparties", 0) / 5.0 +
            gv.get("transaction_path_features", 0) / 10.0
        ) / 3.0
        return float(np.clip(raw, 0.0, 1.0))

    @staticmethod
    def _temporal_score(motif_df: pd.DataFrame, entity_id: str) -> Optional[float]:
        """Score based on number of motif matches."""
        if motif_df.empty:
            return 0.0
        n = len(motif_df[motif_df["entity_id"] == entity_id])
        return float(np.clip(n / 5.0, 0.0, 1.0))
