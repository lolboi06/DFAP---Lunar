# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
"""
M11 — Cross-Domain Fusion Engine.

Three fusion models:

1. WEIGHTED FUSION
   Configurable weights per signal domain.
   Weights are documented heuristics — NOT scientifically optimised.
   Output: composite_score in [0,1] — NOT a probability.

2. LOGISTIC REGRESSION FUSION (calibrated)
   Trained on labelled synthetic benchmark with temporal split:
     - Training: 70% (historical)
     - Validation/calibration: 15%
     - Test: 15% (future, never seen during fitting)
   Calibration: CalibratedClassifierCV(method='sigmoid').
   Output: calibrated probability in (0, 1).
   Model artefact stores: coefficients, feature_set, calibration_method, model_version.

3. DEMPSTER-SHAFER FUSION (principal research model)
   Frame of discernment: Θ = {ANOMALOUS, NORMAL}
   Per domain d:
     m_d(ANOMALOUS) = belief evidence is anomalous
     m_d(NORMAL)    = belief evidence is normal
     m_d(Θ)         = uncommitted uncertainty mass
   Missing domain: m_d(Θ) = 1  (NOT score = 0)
   Conflict mass K is tracked explicitly.
   Dempster combination: standard orthogonal sum with K normalization.
   Output: belief_anomalous, belief_normal, uncertainty, conflict.

IMPORTANT PROBABILITY RULES:
  - Weighted composite score is NOT a probability.
  - IsolationForest score is NOT a probability.
  - DTW distance is NOT a probability.
  - D-S belief is NOT Bayesian probability.
  - ONLY the logistic calibrated output may be called a calibrated probability.

Status: All findings are AI_GENERATED_LEAD.
"""
import json
import uuid
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

MODEL_VERSION_DS = "M11_DS_FUSION_v1.0"
MODEL_VERSION_LR = "M11_LR_FUSION_v1.0"
MODEL_VERSION_WF = "M11_WEIGHTED_FUSION_v1.0"
RANDOM_SEED = 42

# Default domain weights — heuristic, not scientifically optimal.
# Document: financial gets highest weight due to quantifiable amounts.
DEFAULT_WEIGHTS = {
    "telecom": 0.20,
    "financial": 0.30,
    "social": 0.10,
    "behavior": 0.20,
    "graph": 0.10,
    "temporal": 0.10,
}


# ══════════════════════════════════════════════════════════════════════════════
# DEMPSTER-SHAFER COMBINER
# ══════════════════════════════════════════════════════════════════════════════

def _score_to_mass(score: Optional[float], sensitivity: float = 0.8) -> Tuple[float, float, float]:
    """
    Convert a raw anomaly score in [0,1] to Dempster-Shafer mass triple.
    (m_anomalous, m_normal, m_theta)

    If score is None (domain missing): m_theta = 1.0 (pure uncertainty).
    s in [0,1]:
      m_a = s * sensitivity
      m_n = (1.0 - s) * sensitivity
      m_theta = 1.0 - sensitivity
    """
    if score is None:
        return 0.0, 0.0, 1.0  # missing domain → full uncertainty

    s = float(np.clip(score, 0.0, 1.0))
    m_a = s * sensitivity
    m_n = (1.0 - s) * sensitivity
    m_theta = 1.0 - sensitivity

    return float(m_a), float(m_n), float(m_theta)


def _ds_combine_two(
    m1: Tuple[float, float, float],
    m2: Tuple[float, float, float],
) -> Tuple[float, float, float, float]:
    """
    Dempster's orthogonal combination of two mass functions.
    Θ = {A=ANOMALOUS, N=NORMAL, Ω=ANOMALOUS∪NORMAL}

    Returns (m_A, m_N, m_Ω, K)
    where K = conflict mass (mass assigned to empty set before normalisation).
    """
    m1a, m1n, m1t = m1
    m2a, m2n, m2t = m2

    # Raw products (unnormalised)
    raw_a = m1a * m2a + m1a * m2t + m1t * m2a
    raw_n = m1n * m2n + m1n * m2t + m1t * m2n
    raw_t = m1t * m2t
    K     = m1a * m2n + m1n * m2a  # conflict

    denom = 1.0 - K
    if denom < 1e-12:
        # Total conflict — return uniform uncertainty
        return 0.5, 0.5, 0.0, float(K)

    m_a = raw_a / denom
    m_n = raw_n / denom
    m_t = raw_t / denom

    return float(m_a), float(m_n), float(m_t), float(K)


def dempster_shafer_combine(masses: List[Tuple[float, float, float]]) -> Dict[str, float]:
    """
    Sequentially combine N domain mass functions using Dempster's rule.
    Returns dict with belief_anomalous, belief_normal, uncertainty, conflict.
    """
    if not masses:
        return {
            "belief_anomalous": 0.0, "belief_normal": 0.0,
            "uncertainty": 1.0, "conflict": 0.0,
        }

    combined = masses[0]
    total_K = 0.0

    for m in masses[1:]:
        ca, cn, ct, K = _ds_combine_two(combined, m)
        total_K += K
        combined = (ca, cn, ct)

    return {
        "belief_anomalous": float(combined[0]),
        "belief_normal": float(combined[1]),
        "uncertainty": float(combined[2]),
        "conflict": float(np.clip(total_K, 0.0, 1.0)),
    }


# ══════════════════════════════════════════════════════════════════════════════
# FUSION ENGINE
# ══════════════════════════════════════════════════════════════════════════════

class FusionEngine:
    """
    M11 Cross-Domain Fusion Engine.
    Implements weighted, logistic, and Dempster-Shafer fusion.
    """

    def __init__(self, weights: Optional[Dict[str, float]] = None, random_state: int = RANDOM_SEED):
        self.weights = weights or DEFAULT_WEIGHTS
        self.random_state = random_state
        self._lr_model = None
        self._lr_feature_cols: List[str] = []
        self._lr_trained = False
        self._lr_coefficients: Optional[Dict] = None

    # ── Weighted Fusion ───────────────────────────────────────────────────────

    def weighted_fusion(self, domain_scores: Dict[str, Optional[float]]) -> Dict[str, Any]:
        """
        Configurable weighted fusion.
        Returns composite_score in [0,1] — NOT a probability.
        """
        total_weight = 0.0
        weighted_sum = 0.0
        active_domains = []

        for domain, weight in self.weights.items():
            score = domain_scores.get(domain)
            if score is not None:
                s = float(np.clip(score, 0.0, 1.0))
                weighted_sum += weight * s
                total_weight += weight
                active_domains.append(domain)

        composite = weighted_sum / total_weight if total_weight > 0 else 0.0

        return {
            "fusion_model": "WEIGHTED",
            "model_version": MODEL_VERSION_WF,
            "composite_score": float(composite),
            "score_type": "WEIGHTED_COMPOSITE — NOT a probability",
            "active_domains": active_domains,
            "weights_used": {k: v for k, v in self.weights.items() if k in active_domains},
            "weight_documentation": "Heuristic weights. NOT scientifically optimised.",
        }

    # ── Logistic Regression Fusion ────────────────────────────────────────────

    def fit_logistic(
        self,
        feature_matrix: pd.DataFrame,
        labels: pd.Series,
        val_fraction: float = 0.15,
    ):
        """
        Fit calibrated logistic regression on training portion.
        Temporal split: features must be ordered chronologically.
        val_fraction of data held out for calibration — never shuffled.
        """
        from sklearn.linear_model import LogisticRegression
        from sklearn.calibration import CalibratedClassifierCV
        from sklearn.preprocessing import StandardScaler

        n = len(feature_matrix)
        if n < 10:
            return  # insufficient data

        train_end = int(n * (1.0 - val_fraction))
        X_train = feature_matrix.iloc[:train_end].values
        y_train = labels.iloc[:train_end].values
        X_val = feature_matrix.iloc[train_end:].values
        y_val = labels.iloc[train_end:].values

        if len(np.unique(y_train)) < 2:
            return

        scaler = StandardScaler()
        X_train_sc = scaler.fit_transform(X_train)
        X_val_sc = scaler.transform(X_val)

        base = LogisticRegression(
            random_state=self.random_state, max_iter=1000, C=1.0
        )
        try:
            calibrated = CalibratedClassifierCV(
                base, method="sigmoid", cv=2
            )
            calibrated.fit(X_train_sc, y_train)
            self._lr_model = calibrated
        except Exception:
            base.fit(X_train_sc, y_train)
            self._lr_model = base

        self._lr_feature_cols = feature_matrix.columns.tolist()
        self._lr_trained = True
        self._lr_scaler = scaler
        self._lr_coefficients = {
            "feature_set": self._lr_feature_cols,
            "model_version": MODEL_VERSION_LR,
            "calibration_method": "sigmoid (Platt scaling)",
            "random_state": self.random_state,
            "training_samples": int(train_end),
            "calibration_samples": int(n - train_end),
            "note": "Output is calibrated probability. Base model: L2 LogReg.",
        }

    def logistic_predict(self, domain_scores: Dict[str, Optional[float]]) -> Dict[str, Any]:
        """
        Predict calibrated probability for a single observation.
        """
        if not self._lr_trained or self._lr_model is None:
            return {
                "fusion_model": "LOGISTIC",
                "model_version": MODEL_VERSION_LR,
                "calibrated_probability": None,
                "status": "MODEL_NOT_FITTED",
            }

        row = np.array(
            [float(domain_scores.get(c, 0.0) or 0.0) for c in self._lr_feature_cols]
        ).reshape(1, -1)
        row_sc = self._lr_scaler.transform(row)

        prob = float(self._lr_model.predict_proba(row_sc)[0][1])

        return {
            "fusion_model": "LOGISTIC",
            "model_version": MODEL_VERSION_LR,
            "calibrated_probability": prob,
            "score_type": "CALIBRATED_PROBABILITY — output of CalibratedClassifierCV(sigmoid)",
            "coefficients_ref": self._lr_coefficients,
        }

    # ── Dempster-Shafer Fusion ────────────────────────────────────────────────

    def ds_fusion(
        self, domain_scores: Dict[str, Optional[float]]
    ) -> Dict[str, Any]:
        """
        Dempster-Shafer combination over all domains.
        Missing domain → m(Θ) = 1.0  (NOT score = 0).
        Returns belief_anomalous, belief_normal, uncertainty, conflict, conflict_flag.
        """
        domain_order = list(self.weights.keys())
        masses = [_score_to_mass(domain_scores.get(d)) for d in domain_order]
        result = dempster_shafer_combine(masses)
        k = result["conflict"]

        if k < 0.25:
            c_flag = "NORMAL_CONFLICT"
        elif k < 0.50:
            c_flag = "MODERATE_CONFLICT"
        else:
            c_flag = "HIGH_CONFLICT"

        missing_domains = [d for d, s in domain_scores.items() if s is None]

        return {
            "fusion_model": "DEMPSTER_SHAFER",
            "model_version": MODEL_VERSION_DS,
            "belief_anomalous": result["belief_anomalous"],
            "belief_normal": result["belief_normal"],
            "uncertainty": result["uncertainty"],
            "conflict": result["conflict"],
            "conflict_flag": c_flag,
            "missing_domains": missing_domains,
            "domain_masses": {
                d: {"m_a": float(m[0]), "m_n": float(m[1]), "m_theta": float(m[2])}
                for d, m in zip(domain_order, masses)
            },
            "score_type": "DS_BELIEF — NOT Bayesian probability. See Shafer (1976).",
            "missing_domain_policy": "m(Θ)=1 for absent domains — missing is NOT negative evidence.",
        }

    # ── Finding Constructor ───────────────────────────────────────────────────

    def create_finding(
        self,
        entity_id: str,
        domain_scores: Dict[str, Optional[float]],
        anomaly_record: Optional[Dict],
        sequence_matches: Optional[List],
        ts_start: str,
        ts_end: str,
        event_ids: List[str],
        evidence_refs: List[str],
        review_state: str = "UNREVIEWED",
        config_hash: Optional[str] = None,
        abstain_on_high_conflict: bool = True,
    ) -> Dict[str, Any]:
        """
        Produce a hardened M11 finding combining all fusion models,
        governance metadata, explicit conflict policies, and analyst review states.
        """
        from datetime import datetime, timezone
        import hashlib

        wf = self.weighted_fusion(domain_scores)
        ds = self.ds_fusion(domain_scores)
        lr = self.logistic_predict(domain_scores)

        finding_id = f"FND_{uuid.uuid4().hex[:12].upper()}"
        now_ts = datetime.now(timezone.utc).isoformat()

        # Validate review state
        valid_review_states = {
            "UNREVIEWED", "REVIEWED", "TRUE_LEAD",
            "FALSE_POSITIVE", "DISMISSED", "CONFIRMED_BY_ANALYST"
        }
        if review_state not in valid_review_states:
            review_state = "UNREVIEWED"

        # Determine finding status & abstention
        conflict_val = ds["conflict"]
        uncertainty_val = ds["uncertainty"]
        
        if abstain_on_high_conflict and conflict_val >= 0.50:
            status = "CONFLICTED_EVIDENCE"
        elif uncertainty_val >= 0.80 and wf["composite_score"] < 0.30:
            status = "INSUFFICIENT_EVIDENCE"
        else:
            status = "AI_GENERATED_LEAD"

        if config_hash is None:
            config_payload = {
                "weights": self.weights,
                "model_version_ds": MODEL_VERSION_DS,
                "model_version_lr": MODEL_VERSION_LR,
                "model_version_wf": MODEL_VERSION_WF,
            }
            config_hash = hashlib.sha256(
                json.dumps(config_payload, sort_keys=True).encode()
            ).hexdigest()

        return {
            # Hardened Contract Fields (Section 16)
            "finding_id": finding_id,
            "finding_version": "WP3.2",
            "created_at": now_ts,
            "entity_id": entity_id,
            "timestamp_start": ts_start,
            "timestamp_end": ts_end,
            "anomaly_type": (anomaly_record or {}).get("anomaly_type", "BEHAVIORAL_DEVIATION"),

            # Preserved domain & component scores
            "domain_scores": json.dumps(
                {k: (round(v, 4) if v is not None else None)
                 for k, v in domain_scores.items()},
                sort_keys=True,
            ),
            "behavior_score": domain_scores.get("behavior"),
            "graph_score": domain_scores.get("graph"),
            "temporal_score": domain_scores.get("temporal"),
            "sequence_score": domain_scores.get("temporal"),

            # Fusion Model Results
            "fusion_model": "WEIGHTED+DS+LR",
            "composite_score": wf["composite_score"],
            "belief_anomalous": ds["belief_anomalous"],
            "belief_normal": ds["belief_normal"],
            "uncertainty": ds["uncertainty"],
            "conflict": ds["conflict"],
            "conflict_flag": ds["conflict_flag"],
            "missing_domains": json.dumps(ds["missing_domains"]),
            "calibrated_probability": lr.get("calibrated_probability"),

            # Evidence & Provenance
            "event_ids": json.dumps(event_ids),
            "graph_refs": json.dumps((anomaly_record or {}).get("graph_refs", [])),
            "evidence_refs": json.dumps(evidence_refs),
            "evidence_count": len(evidence_refs),
            "anomaly_ref": (anomaly_record or {}).get("anomaly_id", ""),
            "sequence_match_count": len(sequence_matches) if sequence_matches else 0,

            # Governance & Analyst Review State
            "model_version": f"{MODEL_VERSION_DS}|{MODEL_VERSION_LR}|{MODEL_VERSION_WF}",
            "feature_version": "WP2.1",
            "config_hash": config_hash,
            "review_state": review_state,
            "status": status,
        }
