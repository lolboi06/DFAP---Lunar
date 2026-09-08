# Author: Sam Roger X
# Component: DFAP Paper 1 Evaluation Harness
# Scope: Models & Data Structures for Forced Abstention Disclosure Evaluation

from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional, Any, Union
from pydantic import BaseModel, ConfigDict, Field


class AbstentionPresentationCondition(str, Enum):
    """
    Experimental presentation conditions for human-facing abstention disclosure.
    Underlying M11 decision, M12 evidence, and ground truth remain 100% identical.
    """
    SILENT_DROP = "SILENT_DROP"
    LOW_SCORE = "LOW_SCORE"
    FORCED_DISCLOSURE = "FORCED_DISCLOSURE"


class GroundTruthLabel(str, Enum):
    """
    Independent ground-truth support status for controlled evaluation.
    Strictly distinct from system abstention or model confidence.
    """
    WELL_SUPPORTED = "WELL_SUPPORTED"
    WEAKLY_SUPPORTED = "WEAKLY_SUPPORTED"


class ParticipantResponse(str, Enum):
    """
    Investigator judgment regarding evidentiary support.
    """
    WELL_SUPPORTED = "WELL_SUPPORTED"
    WEAKLY_SUPPORTED = "WEAKLY_SUPPORTED"
    UNSURE = "UNSURE"


class ExperimentCase(BaseModel):
    """
    A single controlled synthetic case instance evaluated under a specific condition.
    """
    model_config = ConfigDict(extra="forbid")

    experiment_case_id: str = Field(..., description="Unique deterministic case ID")
    finding_id: str = Field(..., description="Underlying finding ID")
    condition: AbstentionPresentationCondition = Field(..., description="Experimental presentation condition")
    evidence_snapshot: List[Dict[str, Any]] = Field(default_factory=list, description="Immutable M12 evidence references")
    ground_truth_label: GroundTruthLabel = Field(..., description="Objective ground-truth support status")
    m11_state: Dict[str, Any] = Field(default_factory=dict, description="Authoritative M11 fusion & conflict state")
    presentation_payload: Dict[str, Any] = Field(default_factory=dict, description="Rendered presentation data")
    generated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class Trial(BaseModel):
    """
    A single participant task instance representing a presentation condition and recorded judgment.
    """
    model_config = ConfigDict(extra="forbid")

    trial_id: str = Field(..., description="Unique trial ID")
    experiment_case_id: str = Field(..., description="Underlying experiment case ID")
    condition: AbstentionPresentationCondition = Field(..., description="Internal presentation condition")
    case_presentation: Dict[str, Any] = Field(..., description="Blinded participant-facing presentation")
    question: str = Field(
        default="Based on the case information presented, how well-supported is this finding?",
        description="Core judgment evaluation question"
    )
    ground_truth: GroundTruthLabel = Field(..., description="Underlying ground-truth label")
    participant_response: Optional[ParticipantResponse] = Field(None, description="Investigator judgment")
    response_time_ms: Optional[int] = Field(None, description="Response latency in milliseconds")
    confidence_rating: Optional[float] = Field(None, description="Subjective confidence rating in [0.0, 1.0]")
    is_correct: Optional[bool] = Field(None, description="Whether judgment matched ground truth")


class ParticipantAssignment(BaseModel):
    """
    Between-subjects condition assignment for an anonymous participant.
    """
    model_config = ConfigDict(extra="forbid")

    participant_id: str = Field(..., description="Anonymous participant identifier")
    condition: AbstentionPresentationCondition = Field(..., description="Assigned presentation condition")
    assignment_seed: int = Field(..., description="Reproducibility randomization seed")
    assigned_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class CalibrationMetrics(BaseModel):
    """
    Calibration and accuracy metrics computed over a set of participant trials.
    """
    model_config = ConfigDict(extra="forbid")

    n_trials: int = Field(..., description="Total trials evaluated")
    accuracy: float = Field(..., description="Fraction of trials judged correctly")
    calibration_error: float = Field(..., description="Expected Calibration Error (ECE)")
    mean_confidence: float = Field(..., description="Mean subjective confidence across trials")
    confidence_when_correct: float = Field(..., description="Mean confidence on correct judgments")
    confidence_when_incorrect: float = Field(..., description="Mean confidence on incorrect judgments")
    overconfidence_rate: float = Field(..., description="Fraction of trials with high confidence (>=0.70) but incorrect")
    underconfidence_rate: float = Field(..., description="Fraction of trials with low confidence (<=0.40) but correct")
    brier_score: float = Field(..., description="Mean squared difference between confidence and correctness")


class ConditionMetrics(BaseModel):
    """
    Aggregated performance breakdown for one experimental presentation condition.
    """
    model_config = ConfigDict(extra="forbid")

    condition: AbstentionPresentationCondition
    n_participants: int
    n_trials: int
    metrics: CalibrationMetrics
    breakdowns: Dict[str, Dict[str, float]] = Field(
        default_factory=dict,
        description="Stratified metrics for WELL_SUPPORTED, WEAKLY_SUPPORTED, and ABSTENTION_REQUIRED subsets"
    )


class ExperimentResult(BaseModel):
    """
    Structured export container for the entire experiment run.
    """
    model_config = ConfigDict(extra="forbid")

    experiment_id: str
    experiment_version: str = "v1.0-paper1"
    dfap_version: str = "v10.0.0"
    experiment_seed: int
    created_at: str
    participant_count: int
    total_trials: int
    conditions: Dict[str, ConditionMetrics]
