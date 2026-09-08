# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
"""
M9 — Multi-Level Anomaly Engine.

Six anomaly levels:
  EVENT        — single event deviates from domain norms
  ENTITY       — entity-level behavioral deviation
  RELATIONSHIP — novel or unusual graph relationship
  COMMUNITY    — deviation from community-level baseline
  SUBGRAPH     — structural deviation in local subgraph
  SEQUENCE     — sequential pattern anomaly

Five component scores (kept SEPARATE — never prematurely collapsed):
  rule_score              — deterministic threshold rules
  baseline_deviation_score — robust-Z derived from M8 baseline
  isolation_forest_score  — IsolationForest anomaly score (native semantics, NOT probability)
  graph_novelty_score     — deviation in graph structural features
  relationship_score      — novel edges / unusual counterparties

Anomaly types (non-criminal, non-conclusive):
  UNUSUAL_EVENT, BEHAVIORAL_DEVIATION, RELATIONSHIP_NOVELTY,
  COMMUNITY_DEVIATION, SUBGRAPH_DEVIATION, SEQUENCE_DEVIATION

Status: All outputs are AI_GENERATED_LEAD — never GUILTY, FRAUD_CONFIRMED, MALICIOUS.

IsolationForest configuration:
  random_state   = 42    (reproducibility)
  contamination  = 'auto'
  n_estimators   = 100
  max_features   = 1.0

Note: IsolationForest score is the raw decision_function value.
  Negative values → more anomalous. NOT a probability.
  Score is stored as-is with type 'ISOLATION_FOREST_SCORE'.
"""
import json
import uuid
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

MODEL_VERSION = "M9_ANOMALY_v1.0"
RANDOM_SEED = 42

# Anomaly levels
LEVELS = {"EVENT", "ENTITY", "RELATIONSHIP", "COMMUNITY", "SUBGRAPH", "SEQUENCE"}

# Anomaly types
TYPES = {
    "EVENT":        "UNUSUAL_EVENT",
    "ENTITY":       "BEHAVIORAL_DEVIATION",
    "RELATIONSHIP": "RELATIONSHIP_NOVELTY",
    "COMMUNITY":    "COMMUNITY_DEVIATION",
    "SUBGRAPH":     "SUBGRAPH_DEVIATION",
    "SEQUENCE":     "SEQUENCE_DEVIATION",
}

# Rule thresholds (deterministic, configurable)
DEFAULT_RULE_CONFIG = {
    "robust_z_threshold": 3.0,      # |robust_z| >= 3 triggers rule_score = 1.0
    "weighted_degree_cap": 100_000, # unusually high transaction volume
    "degree_spike": 5,              # degree >> entity baseline
    "night_call_ratio_high": 0.8,   # ≥80% night calls
    "transaction_count_spike": 20,  # many transactions in window
}


class AnomalyEngine:
    """
    Consumes WP2 feature parquets + M8 baseline outputs to produce
    multi-level anomaly records.
    """

    def __init__(self, rule_config: Optional[Dict] = None, random_state: int = RANDOM_SEED):
        self.rule_config = rule_config or DEFAULT_RULE_CONFIG
        self.random_state = random_state
        self._if_model = None
        self._if_feature_cols: List[str] = []
        self._if_trained = False

    # ── public ───────────────────────────────────────────────────────────────

    def fit(self, feature_matrix: pd.DataFrame):
        """
        Train IsolationForest on historical feature matrix.
        feature_matrix: wide-format DataFrame (entity_id index, feature columns).
        """
        from sklearn.ensemble import IsolationForest

        numeric_cols = feature_matrix.select_dtypes(include=[np.number]).columns.tolist()
        if not numeric_cols or len(feature_matrix) < 5:
            self._if_trained = False
            return

        self._if_feature_cols = numeric_cols
        X = feature_matrix[numeric_cols].fillna(0.0).values

        self._if_model = IsolationForest(
            n_estimators=100,
            contamination="auto",
            random_state=self.random_state,
            max_features=1.0,
        )
        self._if_model.fit(X)
        self._if_trained = True

    def score_entities(
        self,
        baselines_df: pd.DataFrame,
        graph_features_df: pd.DataFrame,
        telecom_df: pd.DataFrame,
        financial_df: pd.DataFrame,
        social_df: pd.DataFrame,
        canonical_events_df: pd.DataFrame,
        entity_raw_map: Optional[Dict[str, str]] = None,
    ) -> pd.DataFrame:
        """
        Produce anomaly records for all entities.
        Returns anomalies DataFrame.
        """
        anomalies = []
        entity_raw_map = entity_raw_map or {}
        all_entity_ids = set(baselines_df["entity_id"].unique())

        for entity_id in all_entity_ids:
            e_baselines = baselines_df[baselines_df["entity_id"] == entity_id] if not baselines_df.empty and "entity_id" in baselines_df.columns else pd.DataFrame()
            e_graph = graph_features_df[graph_features_df["entity_id"] == entity_id] if not graph_features_df.empty and "entity_id" in graph_features_df.columns else pd.DataFrame()
            e_telecom = telecom_df[telecom_df["entity_id"] == entity_id] if not telecom_df.empty and "entity_id" in telecom_df.columns else pd.DataFrame()
            e_financial = financial_df[financial_df["entity_id"] == entity_id] if not financial_df.empty and "entity_id" in financial_df.columns else pd.DataFrame()
            e_social = social_df[social_df["entity_id"] == entity_id] if not social_df.empty and "entity_id" in social_df.columns else pd.DataFrame()
            raw_id = entity_raw_map.get(entity_id, entity_id) if "entity_raw_map" in locals() else entity_id
            e_events = canonical_events_df[
                (canonical_events_df["actor_id"] == entity_id) |
                (canonical_events_df["actor_id"] == raw_id) |
                (canonical_events_df["target_id"] == entity_id) |
                (canonical_events_df["target_id"] == raw_id)
            ] if not canonical_events_df.empty and "actor_id" in canonical_events_df.columns else pd.DataFrame()

            # Collect evidence refs
            ev_ids = e_events["event_id"].tolist() if not e_events.empty else []
            sha_hashes = e_events["sha256_hash"].tolist() if not e_events.empty else []

            ts_start = e_events["timestamp"].min() if not e_events.empty else ""
            ts_end = e_events["timestamp"].max() if not e_events.empty else ""

            # ── Component scores ──────────────────────────────────────────────
            rule_score = self._rule_score(e_baselines, e_graph, e_telecom, e_financial)
            baseline_dev = self._baseline_deviation_score(e_baselines)
            if_score = self._isolation_forest_score(e_graph, e_telecom, e_financial)
            graph_nov = self._graph_novelty_score(e_graph)
            rel_score = self._relationship_score(e_graph, e_events)

            component_scores = {
                "rule_score": rule_score,
                "baseline_deviation_score": baseline_dev,
                "isolation_forest_score": if_score,   # native score, NOT probability
                "graph_novelty_score": graph_nov,
                "relationship_score": rel_score,
            }

            # ── Level classification ──────────────────────────────────────────
            level, atype, reasons = self._classify(
                component_scores, e_baselines, e_graph, e_telecom, e_financial, e_social
            )

            anomaly_id = f"ANO_{uuid.uuid4().hex[:12].upper()}"

            anomalies.append({
                "anomaly_id": anomaly_id,
                "entity_id": entity_id,
                "timestamp_start": ts_start,
                "timestamp_end": ts_end,
                "anomaly_level": level,
                "anomaly_type": atype,
                "score": float(rule_score + baseline_dev * 0.5),  # composite summary (NOT probability)
                "score_type": "COMPOSITE_ANOMALY_SCORE",
                "component_scores": json.dumps(component_scores, sort_keys=True),
                "reasons": json.dumps(reasons, sort_keys=False),
                "event_ids": json.dumps(ev_ids),
                "graph_refs": json.dumps(e_graph["feature_name"].tolist() if not e_graph.empty and "feature_name" in e_graph.columns else []),
                "evidence_refs": json.dumps(sha_hashes),
                "model_version": MODEL_VERSION,
                "status": "AI_GENERATED_LEAD",
            })

        return pd.DataFrame(anomalies)

    # ── component scorers ────────────────────────────────────────────────────

    def _rule_score(
        self,
        baselines: pd.DataFrame,
        graph: pd.DataFrame,
        telecom: pd.DataFrame,
        financial: pd.DataFrame,
    ) -> float:
        """
        Deterministic rule-based score in [0.0, 1.0].
        Each triggered rule contributes 0.2 (capped at 1.0).
        """
        score = 0.0
        cfg = self.rule_config

        # Rule 1: Any feature has |robust_z| >= threshold
        if not baselines.empty:
            rz = baselines["robust_z"].abs()
            if (rz >= cfg["robust_z_threshold"]).any():
                score += 0.2

        # Rule 2: Night call ratio high
        if not telecom.empty:
            ncr = telecom[telecom["feature_name"] == "night_call_ratio"]["feature_value"]
            if not ncr.empty and float(ncr.iloc[0]) >= cfg["night_call_ratio_high"]:
                score += 0.2

        # Rule 3: Transaction count spike
        if not financial.empty:
            tc = financial[financial["feature_name"] == "transaction_count"]["feature_value"]
            if not tc.empty and float(tc.iloc[0]) >= cfg["transaction_count_spike"]:
                score += 0.2

        # Rule 4: Weighted degree exceeds cap
        if not graph.empty:
            wd = graph[graph["feature_name"] == "weighted_degree"]["feature_value"]
            if not wd.empty and float(wd.iloc[0]) >= cfg["weighted_degree_cap"]:
                score += 0.2

        # Rule 5: Degree spike
        if not graph.empty:
            deg = graph[graph["feature_name"] == "degree"]["feature_value"]
            if not deg.empty and float(deg.iloc[0]) >= cfg["degree_spike"]:
                score += 0.2

        return min(1.0, score)

    def _baseline_deviation_score(self, baselines: pd.DataFrame) -> float:
        """
        Entity-level deviation score from M8 baselines.
        Derived from robust-Z values.
        Score in [0, ∞) — higher = more deviant.
        Only STABLE_BASELINE and LOW_HISTORY contribute; COLD_START is discounted.
        """
        if baselines.empty:
            return 0.0

        mask = baselines["baseline_status"].isin(["STABLE_BASELINE", "LOW_HISTORY"])
        reliable = baselines[mask]
        if reliable.empty:
            return 0.0

        rz_abs = reliable["robust_z"].abs()
        return float(rz_abs.max())  # max deviation across features

    def _isolation_forest_score(
        self, graph: pd.DataFrame, telecom: pd.DataFrame, financial: pd.DataFrame
    ) -> float:
        """
        IsolationForest decision_function score for this entity.
        Raw value: negative = more anomalous.
        Returns 0.0 if model not trained or features unavailable.
        IMPORTANT: This is NOT a probability.
        """
        if not self._if_trained or self._if_model is None:
            return 0.0

        feature_vals = {}
        for df in [graph, telecom, financial]:
            if not df.empty:
                for _, row in df.iterrows():
                    feature_vals[row["feature_name"]] = float(row["feature_value"])

        row_vec = np.array(
            [feature_vals.get(c, 0.0) for c in self._if_feature_cols]
        ).reshape(1, -1)

        return float(self._if_model.decision_function(row_vec)[0])

    def _graph_novelty_score(self, graph: pd.DataFrame) -> float:
        """
        Graph structural novelty: degree + shared_counterparties + path features.
        Score is a raw composite — NOT a probability.
        """
        if graph.empty:
            return 0.0
        gv = {row["feature_name"]: float(row["feature_value"])
              for _, row in graph.iterrows()}
        deg = gv.get("degree", 0.0)
        sc = gv.get("shared_counterparties", 0.0)
        path = gv.get("transaction_path_features", 0.0)
        # Normalised heuristic — documented non-probability
        return float(min(1.0, (deg / 10.0 + sc / 5.0 + path / 10.0) / 3.0))

    def _relationship_score(
        self, graph: pd.DataFrame, events: pd.DataFrame
    ) -> float:
        """
        Novel relationship score based on unique counterparty count relative to expected.
        Score in [0.0, 1.0] — normalised heuristic, NOT a probability.
        """
        if events.empty:
            return 0.0
        unique_targets = events["target_id"].dropna().nunique()
        return float(min(1.0, unique_targets / 10.0))

    def _classify(
        self,
        scores: Dict[str, float],
        baselines: pd.DataFrame,
        graph: pd.DataFrame,
        telecom: pd.DataFrame,
        financial: pd.DataFrame,
        social: pd.DataFrame,
    ):
        """
        Determine the primary anomaly level, type, and reasons list.
        Returns (level, type, reasons[]).
        """
        reasons = []

        # Priority-ordered level determination
        if scores["baseline_deviation_score"] >= 3.0:
            level = "ENTITY"
            reasons.append(f"Robust-Z deviation ≥ 3.0 (actual: {scores['baseline_deviation_score']:.2f})")
        elif scores["graph_novelty_score"] >= 0.5:
            level = "SUBGRAPH"
            reasons.append(f"Graph novelty score: {scores['graph_novelty_score']:.3f}")
        elif scores["relationship_score"] >= 0.5:
            level = "RELATIONSHIP"
            reasons.append(f"Unusual counterparty count (rel_score={scores['relationship_score']:.3f})")
        elif scores["rule_score"] >= 0.4:
            level = "EVENT"
            reasons.append(f"Rule triggers fired (rule_score={scores['rule_score']:.2f})")
        elif scores["isolation_forest_score"] < -0.1:
            level = "ENTITY"
            reasons.append(f"IsolationForest score={scores['isolation_forest_score']:.4f} (negative=anomalous)")
        else:
            level = "ENTITY"
            reasons.append("Low composite anomaly signal — monitoring only")

        atype = TYPES[level]

        if not baselines.empty:
            top_dev = baselines.reindex(baselines["robust_z"].abs().sort_values(ascending=False).index).head(2)
            for _, row in top_dev.iterrows():
                reasons.append(
                    f"Feature '{row['feature_name']}': robust_z={row['robust_z']:.2f} "
                    f"(status={row['baseline_status']})"
                )

        return level, atype, reasons
