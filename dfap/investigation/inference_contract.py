# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: Strict Inference Boundary Contract & Ground-Truth Sanitization Guard

import logging
from typing import Set, List
import pandas as pd

logger = logging.getLogger(__name__)

PROHIBITED_GROUND_TRUTH_COLUMNS: Set[str] = {
    "label",
    "attack_cat",
    "is_attack_ground_truth",
    "class_label",
    "crime_label",
    "is_anomaly",
    "ground_truth",
    "anomaly_label",
    "target_class",
    "ground_truth_confirmed_anomaly"
}


class PredictionUnit:
    UNSW = "EVENT-LEVEL NETWORK ATTACK DETECTION"
    STACKOVERFLOW = "EVENT/USER TEMPORAL INTERACTION ANOMALY"
    ELLIPTIC = "EVENT-LEVEL CRYPTO TOPOLOGY ANOMALY"


class InferenceMode:
    BATCH_UNSUPERVISED = "BATCH_UNSUPERVISED"
    BATCH_UNSUPERVISED_TRANSDUCTIVE = "BATCH_UNSUPERVISED_TRANSDUCTIVE"
    CAUSAL_WALK_FORWARD = "CAUSAL_WALK_FORWARD"


DETECTOR_CONFIG = {
    "version": "v4.1.0_PARAMETERIZED",
    "design_classification": "EMPIRICAL_BASELINES_WITH_PARAMETERIZED_SCORING_WEIGHTS",
    "unsw": {
        "features": ["flow_duration_sec", "sent_bytes", "recv_bytes", "rate", "sload", "dload", "ct_dst_src_ltm", "ct_srv_src"],
        "rate_scale_floor": 100.0,
        "rate_scale_multiplier": 5.0,
        "outlier_multiplier_threshold": 2.5,
        "absolute_floor": 5.0,
        "feature_weight": 0.25,
        "iforest_trees": 50,
        "random_state": 42
    },
    "stackoverflow": {
        "cadence_weight": 0.40,
        "novelty_weight": 0.30,
        "burst_weight": 0.30,
        "novelty_score_new": 0.85,
        "novelty_score_known": 0.10,
        "burst_window_seconds": 3600.0,
        "burst_cap_divisor": 5.0,
        "cadence_sigmoid_divisor": 2.0,
        "min_history_events": 2
    },
    "ensemble": {
        "disagreement_threshold": 0.65,
        "high_score_threshold": 0.65,
        "elevated_score_threshold": 0.40,
        "min_agreement_for_high": 0.50
    }
}


class InferenceContractViolationError(Exception):
    """Raised when ground-truth labels attempt to penetrate the blind inference boundary."""
    pass


class InferenceDataContract:
    """
    Enforces strict isolation between blind unsupervised detection and evaluation ground truth.
    Automatic discovery MUST receive only:
      - canonical events
      - domain features
      - graph features
      - observable behavioral history
    """

    @classmethod
    def sanitize_observable_events(
        cls,
        df: pd.DataFrame,
        strict_fail_on_labels: bool = False
    ) -> pd.DataFrame:
        """
        Validates that observable events entering inference do NOT carry ground-truth labels.
        In strict mode, raises an error if labels are present.
        In default mode, strips any prohibited label columns completely.
        """
        found_prohibited = [c for c in df.columns if c.lower() in PROHIBITED_GROUND_TRUTH_COLUMNS]

        if found_prohibited and strict_fail_on_labels:
            raise InferenceContractViolationError(
                f"INFERENCE BREACH: Prohibited ground-truth columns {found_prohibited} detected in input dataframe! "
                f"DFAP inference must remain strictly blind and unsupervised."
            )

        clean_df = df.drop(columns=found_prohibited, errors="ignore").copy(deep=True)
        return clean_df

    @classmethod
    def verify_clean_inference_state(cls, df: pd.DataFrame) -> bool:
        """Verifies that no prohibited ground truth fields are present."""
        for c in df.columns:
            if c.lower() in PROHIBITED_GROUND_TRUTH_COLUMNS:
                return False
        return True
