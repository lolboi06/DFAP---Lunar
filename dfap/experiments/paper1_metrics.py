# Author: Sam Roger X
# Component: DFAP Paper 1 Evaluation Harness
# Scope: Calibration & Accuracy Metrics Computation (ECE, Overconfidence, Underconfidence)

import math
from typing import List, Dict, Any, Optional
import numpy as np

from dfap.experiments.paper1_models import (
    Trial,
    CalibrationMetrics,
    ConditionMetrics,
    AbstentionPresentationCondition,
    GroundTruthLabel,
    ParticipantResponse,
)


def compute_calibration_metrics(trials: List[Trial], n_bins: int = 5) -> CalibrationMetrics:
    """
    Computes trust calibration and judgment accuracy metrics over a set of completed trials.
    Guarantees deterministic, bounded mathematical calculations.
    """
    if not trials:
        return CalibrationMetrics(
            n_trials=0,
            accuracy=0.0,
            calibration_error=0.0,
            mean_confidence=0.0,
            confidence_when_correct=0.0,
            confidence_when_incorrect=0.0,
            overconfidence_rate=0.0,
            underconfidence_rate=0.0,
            brier_score=0.0,
        )

    n_total = len(trials)
    correct_flags: List[bool] = []
    confidences: List[float] = []

    for t in trials:
        # Determine correctness
        is_corr = False
        if t.participant_response is not None:
            # UNSURE is evaluated as incorrect under binary support judgment
            if t.participant_response.value == t.ground_truth.value:
                is_corr = True
        correct_flags.append(is_corr)

        # Normalized confidence in [0.0, 1.0]
        c = float(t.confidence_rating) if t.confidence_rating is not None else 0.50
        c = float(np.clip(c, 0.0, 1.0))
        confidences.append(c)

    correct_arr = np.array(correct_flags, dtype=bool)
    conf_arr = np.array(confidences, dtype=float)

    accuracy = float(np.mean(correct_arr))
    mean_conf = float(np.mean(conf_arr))

    correct_confs = conf_arr[correct_arr]
    incorrect_confs = conf_arr[~correct_arr]

    conf_when_correct = float(np.mean(correct_confs)) if len(correct_confs) > 0 else 0.0
    conf_when_incorrect = float(np.mean(incorrect_confs)) if len(incorrect_confs) > 0 else 0.0

    # Overconfidence: High confidence (>= 0.70) while incorrect
    high_conf_mask = conf_arr >= 0.70
    overconfident_count = np.sum(high_conf_mask & (~correct_arr))
    overconfidence_rate = float(overconfident_count / n_total)

    # Underconfidence: Low confidence (<= 0.40) while correct
    low_conf_mask = conf_arr <= 0.40
    underconfident_count = np.sum(low_conf_mask & correct_arr)
    underconfidence_rate = float(underconfident_count / n_total)

    # Brier Score: Mean squared error between confidence and correctness indicator
    target_indicator = correct_arr.astype(float)
    brier_score = float(np.mean((conf_arr - target_indicator) ** 2))

    # Expected Calibration Error (ECE)
    ece = 0.0
    bin_boundaries = np.linspace(0.0, 1.0, n_bins + 1)
    for i in range(n_bins):
        bin_lower = bin_boundaries[i]
        bin_upper = bin_boundaries[i + 1]
        
        if i == n_bins - 1:
            in_bin = (conf_arr >= bin_lower) & (conf_arr <= bin_upper)
        else:
            in_bin = (conf_arr >= bin_lower) & (conf_arr < bin_upper)
            
        bin_size = np.sum(in_bin)
        if bin_size > 0:
            bin_acc = np.mean(correct_arr[in_bin])
            bin_conf = np.mean(conf_arr[in_bin])
            ece += (bin_size / n_total) * abs(bin_acc - bin_conf)

    return CalibrationMetrics(
        n_trials=n_total,
        accuracy=round(accuracy, 4),
        calibration_error=round(float(ece), 4),
        mean_confidence=round(mean_conf, 4),
        confidence_when_correct=round(conf_when_correct, 4),
        confidence_when_incorrect=round(conf_when_incorrect, 4),
        overconfidence_rate=round(overconfidence_rate, 4),
        underconfidence_rate=round(underconfidence_rate, 4),
        brier_score=round(brier_score, 4),
    )


def compute_condition_breakdowns(
    trials: List[Trial],
    case_bank_dict: Dict[str, Dict[str, Any]],
) -> Dict[str, Dict[str, float]]:
    """
    Computes performance breakdowns for sub-cohorts:
    - WELL_SUPPORTED
    - WEAKLY_SUPPORTED
    - ABSTENTION_REQUIRED
    """
    cohorts = {
        "WELL_SUPPORTED": [t for t in trials if t.ground_truth == GroundTruthLabel.WELL_SUPPORTED],
        "WEAKLY_SUPPORTED": [t for t in trials if t.ground_truth == GroundTruthLabel.WEAKLY_SUPPORTED],
        "ABSTENTION_REQUIRED": [
            t for t in trials
            if case_bank_dict.get(t.experiment_case_id, {}).get("m11_state", {}).get("overall_status") == "ABSTENTION_REQUIRED"
        ]
    }

    breakdowns: Dict[str, Dict[str, float]] = {}
    for name, cohort_trials in cohorts.items():
        if cohort_trials:
            cm = compute_calibration_metrics(cohort_trials)
            breakdowns[name] = {
                "n_trials": cm.n_trials,
                "accuracy": cm.accuracy,
                "calibration_error": cm.calibration_error,
                "mean_confidence": cm.mean_confidence,
                "overconfidence_rate": cm.overconfidence_rate,
                "underconfidence_rate": cm.underconfidence_rate,
            }
        else:
            breakdowns[name] = {
                "n_trials": 0,
                "accuracy": 0.0,
                "calibration_error": 0.0,
                "mean_confidence": 0.0,
                "overconfidence_rate": 0.0,
                "underconfidence_rate": 0.0,
            }

    return breakdowns
