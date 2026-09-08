# Author: Sam Roger X
# Component: DFAP Paper 3 Evaluation Harness
# Scope: Data Models for Non-Destructive Identity Ledgers vs Mutable Baseline Evaluation

from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional, Any, Literal
from pydantic import BaseModel, ConfigDict, Field


class ERArchitecture(str, Enum):
    """
    Experimental Entity Resolution Architecture under comparison.
    """
    MUTABLE_BASELINE = "MUTABLE_BASELINE"
    LEDGER = "LEDGER"


class InjectedError(BaseModel):
    """
    Controlled identity resolution error injected identically into both architectures.
    """
    model_config = ConfigDict(extra="forbid")

    error_id: str = Field(..., description="Unique deterministic identifier for the error")
    error_type: Literal["FALSE_MERGE", "FALSE_SPLIT"] = Field(..., description="Adversarial error category")
    injection_point: str = Field(..., description="Subsystem or identifier pair where error occurs")
    affected_canonical_entity: str = Field(..., description="Target canonical entity affected")
    secondary_entity: Optional[str] = Field(None, description="Second entity involved in merge or split")
    injection_step: int = Field(default=1, description="Logical benchmark step at which error is introduced")
    correction_step: int = Field(default=3, description="Logical benchmark step at which correction is triggered")
    correction_info: Dict[str, Any] = Field(default_factory=dict, description="Identical correction payload")


class PropagationTrace(BaseModel):
    """
    Detailed audit trace of how far an injected error propagated through downstream stages.
    """
    model_config = ConfigDict(extra="forbid")

    error_id: str = Field(..., description="Injected error ID")
    architecture: ERArchitecture = Field(..., description="Evaluated architecture")
    reached_M4_graph: bool = Field(..., description="Whether erroneous identity contaminated M4 graph construction")
    reached_M6_features: bool = Field(..., description="Whether erroneous identity contaminated M6 feature extraction")
    reached_M8_baseline: bool = Field(..., description="Whether error contaminated M8 behavioral baseline")
    reached_M9_false_positive: bool = Field(..., description="Whether error caused an M9 false positive anomaly")
    propagation_stage_count: int = Field(..., description="Number of downstream stages reached (0 to 4)")
    corrected_via_event: Optional[str] = Field(None, description="Correction event ID (LEDGER only; None for MUTABLE)")
    steps_to_correction: Optional[int] = Field(None, description="Benchmark steps between error and correction")
    downstream_evidence: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Concrete empirical evidence from M4, M6, M8, M9 execution")
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class IdentityStateRecord(BaseModel):
    """
    Snapshot of an entity's identity state.
    """
    model_config = ConfigDict(extra="forbid")

    canonical_entity_id: str
    raw_identifiers: List[str]
    match_status: str  # CONFIRMED, POSSIBLE, REJECTED
    derivation_method: str
    last_event_id: Optional[str] = None
    is_replayed: bool = False


class Paper3Comparison(BaseModel):
    """
    Comparative summary of MUTABLE_BASELINE vs LEDGER across test cases.
    """
    model_config = ConfigDict(extra="forbid")

    experiment_id: str
    benchmark_version: str = "v1.0-paper3"
    seed: int
    n_cases: int
    n_errors_evaluated: int
    baseline_mean_propagation: float
    ledger_mean_propagation: float
    propagation_reduction: float
    baseline_containment_rates: Dict[str, float]
    ledger_containment_rates: Dict[str, float]
    ledger_mean_steps_to_correction: float
    b_cubed_metrics: Dict[str, float] = Field(default_factory=dict)
    traces: List[PropagationTrace] = Field(default_factory=list)
