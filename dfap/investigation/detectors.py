# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: Multi-Detector Anomaly Engine (Statistical, Isolation Forest, Temporal & Abstention)

import json
import logging
import math
from typing import Dict, Any, List, Optional, Tuple
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

logger = logging.getLogger(__name__)


def robust_z_score(val: float, median: float, mad: float, std_fallback: float = 1.0) -> float:
    """Computes robust z-score using Median Absolute Deviation (MAD), falling back to std if MAD is zero."""
    scale = 1.4826 * mad
    if scale <= 1e-6:
        scale = max(std_fallback, 1e-4)
    return float((val - median) / scale)


def score_from_z(z: float) -> float:
    """Maps positive z-score to [0, 1] normalized anomaly score using sigmoid."""
    if z <= 0.0:
        return 0.05
    return float(2.0 / (1.0 + math.exp(-z / 2.0)) - 1.0)


class RobustStatisticalDetector:
    """
    Detector A: Robust statistical outlier detection.
    Uses median and MAD (Median Absolute Deviation) to prevent masking by extreme outliers.
    """

    def __init__(self, random_state: int = 42):
        self.random_state = random_state

    def score_features(self, X: np.ndarray) -> np.ndarray:
        """Computes statistical outlier score for each row in feature matrix X."""
        if len(X) == 0:
            return np.array([])
        if len(X) == 1:
            return np.array([0.5])

        medians = np.median(X, axis=0)
        mads = np.median(np.abs(X - medians), axis=0)
        stds = np.std(X, axis=0)

        row_scores = []
        for row in X:
            z_scores = []
            for j in range(len(row)):
                z = robust_z_score(row[j], medians[j], mads[j], stds[j])
                z_scores.append(abs(z))
            # Average of top 3 strongest deviating features
            z_scores.sort(reverse=True)
            top_z = float(np.mean(z_scores[:3])) if z_scores else 0.0
            row_scores.append(score_from_z(top_z))

        return np.array(row_scores)


class IsolationForestDetector:
    """
    Detector B: Unsupervised multi-dimensional density isolation.
    Uses tree isolation depth to score point anomalies.
    """

    def __init__(self, random_state: int = 42, n_estimators: int = 100):
        self.random_state = random_state
        self.n_estimators = n_estimators
        self.model = IsolationForest(
            n_estimators=self.n_estimators,
            contamination="auto",
            random_state=self.random_state,
            n_jobs=1
        )

    def fit_and_score(self, X: np.ndarray) -> np.ndarray:
        """Fits Isolation Forest on observable features and returns normalized [0, 1] risk scores."""
        if len(X) < 5:
            return np.full(len(X), 0.5)

        self.model.fit(X)
        # Decision function: lower values mean more anomalous
        raw_scores = self.model.decision_function(X)
        min_s, max_s = float(np.min(raw_scores)), float(np.max(raw_scores))
        if max_s - min_s <= 1e-6:
            return np.full(len(X), 0.5)

        # Invert so higher value means higher anomaly risk
        norm_scores = (max_s - raw_scores) / (max_s - min_s)
        return np.clip(norm_scores, 0.01, 0.99)


class TemporalSequenceDetector:
    """
    Detector C: Sequence & Temporal Cadence Shift Detector.
    Evaluates changes in inter-arrival times, burstiness index jumps, and novelty turnover.
    Strictly causal: Baselines use only historical events strictly <= pivot.
    """

    def __init__(self, random_state: int = 42):
        self.random_state = random_state

    @staticmethod
    def score_temporal_features(
        cadence_ratio: float,
        burstiness_index: float,
        novelty_turnover: float,
        recent_surge_ratio: float
    ) -> float:
        """Combines temporal shift features into normalized temporal risk score."""
        s_cad = min(1.0, max(0.0, (cadence_ratio - 1.0) / 3.0)) if cadence_ratio > 1.0 else 0.05
        s_burst = min(1.0, max(0.0, (burstiness_index + 1.0) / 2.0))
        s_nov = min(1.0, max(0.0, novelty_turnover))
        s_surge = min(1.0, max(0.0, recent_surge_ratio / 5.0))

        comb = 0.35 * s_cad + 0.25 * s_burst + 0.20 * s_nov + 0.20 * s_surge
        return round(float(np.clip(comb, 0.05, 0.98)), 3)


class AnomalyDecisionEngine:
    """
    Ensemble decision engine combining multiple detectors with explicit abstention logic.
    Classifications:
      - HIGH: strong agreement across detectors above threshold
      - ELEVATED: moderate anomaly signal
      - NORMAL: within standard population envelope
      - CONFLICTED: severe disagreement between detectors
      - INSUFFICIENT_EVIDENCE: below minimum required data volume
    """

    @staticmethod
    def combine_detectors(
        score_stat: float,
        score_iforest: float,
        score_temporal: float,
        event_count: int,
        min_events_required: int = 2
    ) -> Dict[str, Any]:
        """Combines individual detector scores, separating detector agreement from statistical confidence."""
        is_sufficient = (event_count >= min_events_required)
        data_sufficiency = "SUFFICIENT" if is_sufficient else "INSUFFICIENT_HISTORY"

        if not is_sufficient:
            return {
                "classification": "INSUFFICIENT_EVIDENCE",
                "risk_score": 0.10,
                "confidence": 0.20,
                "uncertainty": 0.80,
                "epistemic_uncertainty": 0.80,
                "detector_agreement": 0.0,
                "agreement": 0.0,
                "disagreement": 1.0,
                "data_sufficiency": data_sufficiency,
                "data_sufficiency_warning": f"Only {event_count} historical observations available (minimum {min_events_required} required).",
                "detector_scores": {
                    "statistical": round(score_stat, 3),
                    "isolation_forest": round(score_iforest, 3),
                    "temporal": round(score_temporal, 3)
                }
            }

        scores = [score_stat, score_iforest, score_temporal]
        combined = float(np.mean(scores))
        score_std = float(np.std(scores))

        # Disagreement is normalized variance among detectors
        disagreement = round(min(1.0, score_std / 0.5), 3)
        agreement = round(1.0 - disagreement, 3)
        confidence = round(float(np.clip(agreement * (1.0 - 1.0 / (event_count + 1)), 0.10, 0.95)), 3)
        epistemic_uncertainty = round(1.0 - confidence, 3)

        if disagreement > 0.65:
            classification = "CONFLICTED"
        elif combined >= 0.65 and agreement >= 0.50:
            classification = "HIGH"
        elif combined >= 0.40:
            classification = "ELEVATED"
        else:
            classification = "NORMAL"

        return {
            "classification": classification,
            "risk_score": round(combined, 3),
            "confidence": confidence,
            "uncertainty": epistemic_uncertainty,
            "epistemic_uncertainty": epistemic_uncertainty,
            "detector_agreement": agreement,
            "agreement": agreement,
            "disagreement": disagreement,
            "data_sufficiency": data_sufficiency,
            "detector_scores": {
                "statistical": round(score_stat, 3),
                "isolation_forest": round(score_iforest, 3),
                "temporal": round(score_temporal, 3)
            }
        }
