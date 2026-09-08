# Author: Sam Roger X
# Component: DFAP M8 Adaptive Behavioral Baselines
# Scope: Deterministic EWMA adaptive baseline tracking with contamination protection, explicit state machine, immutable audit trail, and M9/M14 integration

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Any, List, Optional, Tuple


class BaselineState(str, Enum):
    COLD_START = "COLD_START"
    STABLE_BASELINE = "STABLE_BASELINE"
    ADAPTATION_IN_PROGRESS = "ADAPTATION_IN_PROGRESS"


class UpdateDecision(str, Enum):
    COLD_START_ACCUMULATION = "COLD_START_ACCUMULATION"
    UPDATED_BASELINE = "UPDATED_BASELINE"
    DRIFT_ADAPTED = "DRIFT_ADAPTED"
    EXCLUDED_FROM_BASELINE = "EXCLUDED_FROM_BASELINE"
    QUARANTINED = "QUARANTINED"


class SignalClassification(str, Enum):
    OBSERVED = "OBSERVED"
    MODEL_INFERENCE = "MODEL_INFERENCE"
    BASELINE_DECISION = "BASELINE_DECISION"


STANDARD_BASELINE_LIMITATIONS = [
    "Behavioral deviations quantify statistical divergence from historical baseline, NOT criminal intent or legal guilt.",
    "Adaptive baseline adjustments reflect mathematical drift, NOT intentional, fraudulent, or conspiratorial behavior.",
    "Exclusions and quarantines serve to protect baseline mathematical integrity, NOT to infer culpability.",
    "Human investigator corroboration and source evidence review are strictly required prior to any operational action."
]


@dataclass
class BaselineObservationRecord:
    """Immutable audit record for every observed feature value and resulting baseline decision."""
    step_index: int
    entity_id: str
    feature_name: str
    observation_value: float
    previous_baseline: float
    new_baseline: float
    deviation: float
    standardized_deviation: float
    state_before: str
    state_after: str
    update_decision: str
    update_reason: str
    timestamp: Optional[float] = None
    evidence_refs: List[str] = field(default_factory=list)
    signal_type: str = SignalClassification.BASELINE_DECISION.value

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_index": self.step_index,
            "entity_id": self.entity_id,
            "feature_name": self.feature_name,
            "observation_value": round(self.observation_value, 4),
            "previous_baseline": round(self.previous_baseline, 4),
            "new_baseline": round(self.new_baseline, 4),
            "deviation": round(self.deviation, 4),
            "standardized_deviation": round(self.standardized_deviation, 4),
            "state_before": self.state_before,
            "state_after": self.state_after,
            "update_decision": self.update_decision,
            "update_reason": self.update_reason,
            "timestamp": self.timestamp,
            "evidence_refs": self.evidence_refs,
            "signal_type": self.signal_type,
            "signal_classification": self.signal_type,
            "disclaimer": "Statistical behavioral baseline decision; NOT proof of criminal guilt or malicious intent."
        }


class AdaptiveBaselineTracker:
    """
    Online, O(1) EWMA adaptive behavioral baseline tracker for a single entity-feature stream.
    Formula:
        EWMA_t = alpha * x_t + (1 - alpha) * EWMA_(t-1)
    With contamination protection:
        - Outliers (z > deviation_threshold) are EXCLUDED or QUARANTINED without mutating baseline.
        - Moderate sustained shifts (drift_threshold < z <= deviation_threshold) transition to ADAPTATION_IN_PROGRESS.
        - Normal values (z <= drift_threshold) transition to or remain in STABLE_BASELINE.
    """

    def __init__(
        self,
        entity_id: str = "ENT_DEFAULT",
        feature_name: str = "PRIMARY",
        alpha: float = 0.15,
        min_observations: int = 5,
        deviation_threshold: float = 3.0,
        drift_threshold: float = 1.5,
        initial_baseline: Optional[float] = None,
        initial_variance: Optional[float] = None,
        epsilon: float = 1e-4
    ):
        self.entity_id = entity_id
        self.feature_name = feature_name
        self.alpha = float(alpha)
        self.min_observations = int(min_observations)
        self.deviation_threshold = float(deviation_threshold)
        self.drift_threshold = float(drift_threshold)
        self.epsilon = float(epsilon)

        self.current_baseline: float = float(initial_baseline) if initial_baseline is not None else 0.0
        self.current_variance: float = float(initial_variance) if initial_variance is not None else 1.0
        self.state: BaselineState = BaselineState.COLD_START

        self.observation_count: int = 0
        self.adaptation_count: int = 0
        self.excluded_count: int = 0
        self.quarantined_count: int = 0

        self.consecutive_drift_count: int = 0
        self.consecutive_anomaly_count: int = 0

        self.history: List[BaselineObservationRecord] = []
        self._quarantine_buffer: List[float] = []

    @property
    def current_std(self) -> float:
        return math.sqrt(max(self.current_variance, self.epsilon))

    def observe(
        self,
        value: float,
        timestamp: Optional[float] = None,
        evidence_refs: Optional[List[str]] = None
    ) -> BaselineObservationRecord:
        """
        Processes a single feature observation in O(1) time.
        Updates state and baseline under strict contamination protection rules.
        """
        x_t = float(value)
        refs = list(evidence_refs or [])
        state_before = self.state.value
        prev_baseline = self.current_baseline
        prev_variance = self.current_variance
        prev_std = self.current_std

        # Compute raw and standardized deviations against existing baseline
        if self.observation_count == 0:
            deviation = 0.0
            z_score = 0.0
        else:
            deviation = abs(x_t - prev_baseline)
            z_score = deviation / prev_std

        update_decision: UpdateDecision
        update_reason: str
        new_baseline = prev_baseline
        new_variance = prev_variance
        state_after = self.state

        # ── State Machine & Contamination Protection Logic ────────────────────

        if self.state == BaselineState.COLD_START:
            # Phase 1: Cold start accumulation
            self.observation_count += 1
            if self.observation_count == 1:
                new_baseline = x_t
                new_variance = 1.0
            else:
                # Running mean & variance during initial accumulation
                n = self.observation_count
                delta = x_t - prev_baseline
                new_baseline = prev_baseline + delta / n
                delta2 = x_t - new_baseline
                new_variance = ((n - 1) * prev_variance + delta * delta2) / n

            update_decision = UpdateDecision.COLD_START_ACCUMULATION
            update_reason = f"Cold start observation {self.observation_count}/{self.min_observations} accumulated into initial baseline."

            # Transition check: exit COLD_START once sufficient observations are collected
            if self.observation_count >= self.min_observations:
                state_after = BaselineState.STABLE_BASELINE
            else:
                state_after = BaselineState.COLD_START

        else:
            # Entity has exited cold start: STABLE_BASELINE or ADAPTATION_IN_PROGRESS
            self.observation_count += 1

            if z_score > self.deviation_threshold:
                # Extreme deviation: ANOMALOUS
                self.consecutive_anomaly_count += 1
                self.consecutive_drift_count = 0
                self._quarantine_buffer.append(x_t)

                if self.consecutive_anomaly_count >= 2:
                    # Repeated anomaly: Quarantine protection
                    self.quarantined_count += 1
                    update_decision = UpdateDecision.QUARANTINED
                    update_reason = (
                        f"Repeated anomalous observation (z={z_score:.2f} > {self.deviation_threshold}); "
                        f"quarantined to protect baseline from malicious or erratic contamination."
                    )
                else:
                    # Isolated anomaly: Exclusion
                    self.excluded_count += 1
                    update_decision = UpdateDecision.EXCLUDED_FROM_BASELINE
                    update_reason = (
                        f"Isolated extreme deviation (z={z_score:.2f} > {self.deviation_threshold}); "
                        f"excluded from baseline update to maintain mathematical stability."
                    )

                # Baseline is NOT modified: contamination blocked
                new_baseline = prev_baseline
                new_variance = prev_variance
                # State remains as is (or preserves existing baseline)
                state_after = self.state

            elif z_score > self.drift_threshold:
                # Moderate deviation: Legitimate behavioral drift
                self.consecutive_anomaly_count = 0
                self.consecutive_drift_count += 1
                self.adaptation_count += 1

                # Enter ADAPTATION_IN_PROGRESS on sustained drift
                if self.consecutive_drift_count >= 2:
                    state_after = BaselineState.ADAPTATION_IN_PROGRESS
                else:
                    state_after = self.state

                # Adapt baseline gradually via EWMA
                new_baseline = self.alpha * x_t + (1.0 - self.alpha) * prev_baseline
                delta = x_t - prev_baseline
                new_variance = (1.0 - self.alpha) * (prev_variance + self.alpha * (delta ** 2))

                update_decision = UpdateDecision.DRIFT_ADAPTED
                update_reason = (
                    f"Moderate deviation (z={z_score:.2f} > {self.drift_threshold}); "
                    f"incorporated into baseline under controlled adaptation."
                )

            else:
                # Normal observation: within normal variance bounds
                self.consecutive_anomaly_count = 0

                # If we were adapting and variance/deviation restabilizes, return to STABLE_BASELINE
                if self.state == BaselineState.ADAPTATION_IN_PROGRESS:
                    self.consecutive_drift_count = 0
                    state_after = BaselineState.STABLE_BASELINE
                else:
                    state_after = BaselineState.STABLE_BASELINE

                # Update baseline via standard EWMA
                new_baseline = self.alpha * x_t + (1.0 - self.alpha) * prev_baseline
                delta = x_t - prev_baseline
                new_variance = (1.0 - self.alpha) * (prev_variance + self.alpha * (delta ** 2))

                update_decision = UpdateDecision.UPDATED_BASELINE
                update_reason = f"Normal observation (z={z_score:.2f} <= {self.drift_threshold}); updated EWMA baseline."

        # Commit state updates
        self.current_baseline = new_baseline
        self.current_variance = max(new_variance, self.epsilon)
        self.state = state_after

        # Record immutable audit history
        record = BaselineObservationRecord(
            step_index=len(self.history) + 1,
            entity_id=self.entity_id,
            feature_name=self.feature_name,
            observation_value=x_t,
            previous_baseline=prev_baseline,
            new_baseline=new_baseline,
            deviation=deviation,
            standardized_deviation=z_score,
            state_before=state_before,
            state_after=state_after.value,
            update_decision=update_decision.value,
            update_reason=update_reason,
            timestamp=timestamp,
            evidence_refs=refs,
            signal_type=SignalClassification.BASELINE_DECISION.value
        )
        self.history.append(record)
        return record

    def get_status(self) -> Dict[str, Any]:
        """Returns structured status summary of current baseline tracker."""
        return {
            "entity_id": self.entity_id,
            "feature_name": self.feature_name,
            "current_baseline": round(self.current_baseline, 4),
            "current_variance": round(self.current_variance, 4),
            "current_std": round(self.current_std, 4),
            "state": self.state.value,
            "observation_count": self.observation_count,
            "adaptation_count": self.adaptation_count,
            "excluded_count": self.excluded_count,
            "quarantined_count": self.quarantined_count,
            "alpha": self.alpha,
            "min_observations": self.min_observations,
            "deviation_threshold": self.deviation_threshold,
            "drift_threshold": self.drift_threshold,
            "quarantined_observations": [round(v, 4) for v in self._quarantine_buffer[-5:]],
            "limitations": STANDARD_BASELINE_LIMITATIONS
        }


class AdaptiveBaselineManager:
    """
    Investigation-level behavioral baseline service managing entity-feature trackers.
    Provides research fixtures, M9 integration hooks, M13 CLI formatting, and M14 tool contracts.
    """

    def __init__(self, default_alpha: float = 0.15, default_min_obs: int = 5):
        self.default_alpha = default_alpha
        self.default_min_obs = default_min_obs
        self._trackers: Dict[Tuple[str, str], AdaptiveBaselineTracker] = {}

    def get_or_create_tracker(
        self,
        entity_id: str,
        feature_name: str,
        alpha: Optional[float] = None,
        min_observations: Optional[int] = None,
        **kwargs
    ) -> AdaptiveBaselineTracker:
        """Retrieves or instantiates an entity-feature baseline tracker."""
        key = (entity_id.strip(), feature_name.strip())
        if key not in self._trackers:
            self._trackers[key] = AdaptiveBaselineTracker(
                entity_id=key[0],
                feature_name=key[1],
                alpha=alpha if alpha is not None else self.default_alpha,
                min_observations=min_observations if min_observations is not None else self.default_min_obs,
                **kwargs
            )
        return self._trackers[key]

    def observe(
        self,
        entity_id: str,
        feature_name: str,
        value: float,
        timestamp: Optional[float] = None,
        evidence_refs: Optional[List[str]] = None,
        **kwargs
    ) -> BaselineObservationRecord:
        """Processes an observation through the appropriate entity-feature tracker."""
        tracker = self.get_or_create_tracker(entity_id, feature_name, **kwargs)
        return tracker.observe(value=value, timestamp=timestamp, evidence_refs=evidence_refs)

    def get_status(self, entity_id: str, feature_name: Optional[str] = None) -> Dict[str, Any]:
        """Returns baseline status for an entity, across all features or a specific feature."""
        ent_clean = entity_id.strip()
        matching_keys = [k for k in self._trackers.keys() if k[0] == ent_clean]
        if feature_name:
            feat_clean = feature_name.strip()
            matching_keys = [k for k in matching_keys if k[1] == feat_clean]

        if not matching_keys:
            # Return cold start default descriptor
            return {
                "entity_id": ent_clean,
                "feature_name": feature_name or "ALL",
                "current_baseline": 0.0,
                "state": BaselineState.COLD_START.value,
                "observation_count": 0,
                "adaptation_count": 0,
                "excluded_count": 0,
                "quarantined_count": 0,
                "is_cold_start": True,
                "reason": "No historical observations recorded for entity.",
                "limitations": STANDARD_BASELINE_LIMITATIONS
            }

        if len(matching_keys) == 1:
            tracker = self._trackers[matching_keys[0]]
            res = tracker.get_status()
            res["is_cold_start"] = (tracker.state == BaselineState.COLD_START)
            return res

        # Multiple features summary
        features_summary = {}
        for k in matching_keys:
            features_summary[k[1]] = self._trackers[k].get_status()

        return {
            "entity_id": ent_clean,
            "features_count": len(matching_keys),
            "features": features_summary,
            "limitations": STANDARD_BASELINE_LIMITATIONS
        }

    def get_history(self, entity_id: str, feature_name: Optional[str] = None) -> List[Dict[str, Any]]:
        """Returns chronological immutable audit history for an entity's baselines."""
        ent_clean = entity_id.strip()
        all_records = []
        for (e, f), tracker in self._trackers.items():
            if e == ent_clean and (feature_name is None or f == feature_name.strip()):
                all_records.extend([r.to_dict() for r in tracker.history])
        all_records.sort(key=lambda r: (r.get("step_index", 0)))
        return all_records

    # ── M9 Anomaly Layer Integration Hook ─────────────────────────────────────

    def assess_m9_observation(
        self,
        entity_id: str,
        feature_name: str,
        current_value: float,
        timestamp: Optional[float] = None,
        evidence_refs: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Small clean interface for M9 Anomaly Engine.
        Returns baseline context alongside deviation and update decision without modifying M9 scoring formulas.
        """
        tracker = self.get_or_create_tracker(entity_id, feature_name)
        record = tracker.observe(current_value, timestamp=timestamp, evidence_refs=evidence_refs)

        return {
            "entity_id": entity_id,
            "feature_name": feature_name,
            "current_value": round(float(current_value), 4),
            "baseline_value": round(float(record.previous_baseline), 4),
            "new_baseline": round(float(record.new_baseline), 4),
            "deviation": round(float(record.deviation), 4),
            "standardized_deviation": round(float(record.standardized_deviation), 4),
            "baseline_state": record.state_after,
            "observation_count": tracker.observation_count,
            "adaptation_status": "ADAPTING" if record.state_after == BaselineState.ADAPTATION_IN_PROGRESS.value else "STABLE",
            "update_decision": record.update_decision,
            "update_reason": record.update_reason,
            "is_anomalous": record.update_decision in (UpdateDecision.EXCLUDED_FROM_BASELINE.value, UpdateDecision.QUARANTINED.value),
            "evidence_refs": record.evidence_refs,
            "limitations": STANDARD_BASELINE_LIMITATIONS
        }

    # ── M14 Agentic Investigation Tool Interface ──────────────────────────────

    def query_agentic_tool(
        self,
        question: str,
        entity_id: str,
        feature_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Structured tool contract for M14 Agentic Copilot.
        Directly answers operational questions:
          - "What is the behavioral baseline state?"
          - "Has the baseline adapted?"
          - "Why was this observation excluded?"
          - "Was this observation allowed to update the baseline?"
          - "Is this entity still in cold start?"
        """
        q_lower = question.lower()
        status = self.get_status(entity_id, feature_name)
        history = self.get_history(entity_id, feature_name)
        latest_rec = history[-1] if history else {}

        # Default structured envelope
        ans: str
        claims: List[Dict[str, Any]] = []
        is_cold = status.get("is_cold_start", status.get("state") == BaselineState.COLD_START.value)

        if "cold start" in q_lower or "still in cold" in q_lower:
            obs_cnt = status.get("observation_count", 0)
            min_obs = status.get("min_observations", self.default_min_obs)
            if is_cold:
                ans = f"Entity '{entity_id}' is currently in COLD_START ({obs_cnt}/{min_obs} required observations). Behavioral baselines are not yet mature."
            else:
                ans = f"Entity '{entity_id}' has completed cold start ({obs_cnt} observations >= {min_obs} threshold) and holds state '{status.get('state')}''."
            claims.append({
                "claim": ans,
                "evidence_ids": latest_rec.get("evidence_refs", [])
            })

        elif "adapted" in q_lower or "adaptation" in q_lower or "drift" in q_lower:
            adapt_cnt = status.get("adaptation_count", 0)
            curr_state = status.get("state")
            b_val = status.get("current_baseline", 0.0)
            if adapt_cnt > 0:
                ans = f"Baseline for entity '{entity_id}' has adapted {adapt_cnt} times (current state: {curr_state}, baseline value: {b_val:.4f})."
            else:
                ans = f"Baseline for entity '{entity_id}' has not undergone adaptation drift (adaptation count: 0, state: {curr_state})."
            claims.append({
                "claim": ans,
                "evidence_ids": latest_rec.get("evidence_refs", [])
            })

        elif "excluded" in q_lower or "quarantined" in q_lower or "why" in q_lower:
            ex_cnt = status.get("excluded_count", 0)
            q_cnt = status.get("quarantined_count", 0)
            latest_dec = latest_rec.get("update_decision", "N/A")
            latest_reason = latest_rec.get("update_reason", "No observations on record.")
            ans = (
                f"For entity '{entity_id}', {ex_cnt} observation(s) were excluded and {q_cnt} quarantined. "
                f"Latest decision was '{latest_dec}': {latest_reason}"
            )
            claims.append({
                "claim": ans,
                "evidence_ids": latest_rec.get("evidence_refs", [])
            })

        elif "allowed to update" in q_lower or "was this observation" in q_lower:
            latest_dec = latest_rec.get("update_decision", "N/A")
            latest_val = latest_rec.get("observation_value", None)
            allowed = latest_dec in (UpdateDecision.UPDATED_BASELINE.value, UpdateDecision.DRIFT_ADAPTED.value, UpdateDecision.COLD_START_ACCUMULATION.value)
            ans = f"Observation (value: {latest_val}) was {'ALLOWED' if allowed else 'BLOCKED'} from updating baseline (decision: {latest_dec}). Reason: {latest_rec.get('update_reason')}."
            claims.append({
                "claim": ans,
                "evidence_ids": latest_rec.get("evidence_refs", [])
            })

        else:
            # Baseline state summary
            curr_state = status.get("state", "UNKNOWN")
            b_val = status.get("current_baseline", 0.0)
            obs_cnt = status.get("observation_count", 0)
            ans = (
                f"Entity '{entity_id}' baseline state is '{curr_state}' (current baseline: {b_val:.4f}, "
                f"observation count: {obs_cnt}, adaptations: {status.get('adaptation_count', 0)}, "
                f"excluded: {status.get('excluded_count', 0)}, quarantined: {status.get('quarantined_count', 0)})."
            )
            claims.append({
                "claim": ans,
                "evidence_ids": latest_rec.get("evidence_refs", [])
            })

        return {
            "entity_id": entity_id,
            "feature_name": feature_name or status.get("feature_name", "PRIMARY"),
            "current_value": latest_rec.get("observation_value"),
            "baseline_value": status.get("current_baseline"),
            "previous_baseline": latest_rec.get("previous_baseline"),
            "new_baseline": latest_rec.get("new_baseline"),
            "deviation": latest_rec.get("deviation"),
            "state": status.get("state"),
            "observation_count": status.get("observation_count", 0),
            "update_decision": latest_rec.get("update_decision"),
            "update_reason": latest_rec.get("update_reason"),
            "answer": ans,
            "claims": claims,
            "evidence_refs": latest_rec.get("evidence_refs", []),
            "provenance_refs": [],
            "uncertainties": ["Baseline confidence depends on continuous observation count and stability."],
            "limitations": STANDARD_BASELINE_LIMITATIONS,
            "audit_verifiable": True,
            "culpability_assessment": "NONE (Mathematical baseline divergence does not establish culpability or intent)"
        }

    # ── 5-Phase Controlled Research Fixture ───────────────────────────────────

    def run_five_phase_research_fixture(self) -> Dict[str, Any]:
        """
        Executes the controlled 5-phase research benchmark on a test entity:
          Phase 1: Cold Start (5 observations)
          Phase 2: Stable Normal Behavior (10 observations around 100.0)
          Phase 3: Gradual Legitimate Drift (10 observations stepping 103.0 -> 130.0)
          Phase 4: Isolated Anomaly (1 observation at 350.0)
          Phase 5: Repeated Anomalous Observations (5 observations at ~400.0)
        """
        entity_id = "ENT_RESEARCH_FIXTURE_001"
        feature_name = "TRANSACTION_VOLUME"

        # Initialize fresh tracker
        tracker = AdaptiveBaselineTracker(
            entity_id=entity_id,
            feature_name=feature_name,
            alpha=0.15,
            min_observations=5,
            deviation_threshold=3.0,
            drift_threshold=1.5
        )

        phase_results: Dict[str, Any] = {}

        # ── Phase 1: Cold Start (5 observations) ──
        p1_obs = [100.0, 101.0, 99.0, 100.5, 99.5]
        p1_records = [tracker.observe(v) for v in p1_obs]
        p1_final_rec = p1_records[-1]
        phase_results["phase_1_cold_start"] = {
            "observations": p1_obs,
            "final_state": p1_final_rec.state_after,
            "final_baseline": round(tracker.current_baseline, 4),
            "observation_count": tracker.observation_count,
            "excluded_count": tracker.excluded_count
        }

        baseline_after_cold = tracker.current_baseline

        # ── Phase 2: Stable Normal Behavior (10 observations) ──
        p2_obs = [100.2, 99.8, 100.5, 100.1, 99.7, 100.3, 99.9, 100.4, 100.0, 100.2]
        p2_records = [tracker.observe(v) for v in p2_obs]
        phase_results["phase_2_stable_normal"] = {
            "observations_count": len(p2_obs),
            "final_state": tracker.state.value,
            "final_baseline": round(tracker.current_baseline, 4),
            "observation_count": tracker.observation_count,
            "excluded_count": tracker.excluded_count
        }

        baseline_stable = tracker.current_baseline

        # ── Phase 3: Gradual Legitimate Drift (10 observations: 100.6 -> 108.0) ──
        p3_obs = [100.6, 101.1, 101.7, 102.3, 103.0, 103.8, 104.7, 105.7, 106.8, 108.0]
        p3_records = [tracker.observe(v) for v in p3_obs]
        phase_results["phase_3_gradual_drift"] = {
            "observations": p3_obs,
            "state_during_drift": [r.state_after for r in p3_records],
            "baseline_trajectory": [round(r.new_baseline, 4) for r in p3_records],
            "final_state": tracker.state.value,
            "final_baseline": round(tracker.current_baseline, 4),
            "adaptation_count": tracker.adaptation_count
        }

        baseline_after_drift = tracker.current_baseline

        # ── Phase 4: Isolated Anomaly (1 extreme spike: 350.0) ──
        p4_obs = [350.0]
        p4_rec = tracker.observe(p4_obs[0])
        phase_results["phase_4_isolated_anomaly"] = {
            "spike_value": p4_obs[0],
            "update_decision": p4_rec.update_decision,
            "update_reason": p4_rec.update_reason,
            "baseline_before_spike": round(p4_rec.previous_baseline, 4),
            "baseline_after_spike": round(p4_rec.new_baseline, 4),
            "is_baseline_preserved": math.isclose(p4_rec.previous_baseline, p4_rec.new_baseline, rel_tol=1e-5),
            "excluded_count": tracker.excluded_count
        }

        baseline_after_isolated = tracker.current_baseline

        # ── Phase 5: Repeated Anomalous Observations (5 extreme observations ~400.0) ──
        p5_obs = [400.0, 405.0, 395.0, 410.0, 400.0]
        p5_records = [tracker.observe(v) for v in p5_obs]
        phase_results["phase_5_repeated_anomalies"] = {
            "observations": p5_obs,
            "decisions": [r.update_decision for r in p5_records],
            "final_baseline": round(tracker.current_baseline, 4),
            "baseline_unchanged_across_anomalies": math.isclose(baseline_after_isolated, tracker.current_baseline, rel_tol=1e-5),
            "quarantined_count": tracker.quarantined_count,
            "excluded_count": tracker.excluded_count
        }

        return {
            "entity_id": entity_id,
            "feature_name": feature_name,
            "summary_metrics": {
                "initial_cold_baseline": round(baseline_after_cold, 4),
                "stable_baseline": round(baseline_stable, 4),
                "baseline_after_drift": round(baseline_after_drift, 4),
                "baseline_after_isolated_anomaly": round(baseline_after_isolated, 4),
                "final_baseline": round(tracker.current_baseline, 4),
                "total_observations": tracker.observation_count,
                "total_adaptations": tracker.adaptation_count,
                "total_excluded": tracker.excluded_count,
                "total_quarantined": tracker.quarantined_count,
                "drift_adaptation_successful": (baseline_after_drift > baseline_stable),
                "contamination_prevented": math.isclose(baseline_after_drift, tracker.current_baseline, rel_tol=1e-5),
            },
            "phase_breakdown": phase_results
        }


def run_five_phase_research_fixture() -> Dict[str, Any]:
    """Convenience module function executing the controlled 5-phase research fixture."""
    manager = AdaptiveBaselineManager()
    res = manager.run_five_phase_research_fixture()
    summary = res["summary_metrics"]
    phases = res["phase_breakdown"]
    return {
        "entity_id": res["entity_id"],
        "feature_name": res["feature_name"],
        "cold_start_completed": phases["phase_1_cold_start"]["final_state"] != BaselineState.COLD_START.value,
        "drift_adaptation_successful": summary["drift_adaptation_successful"],
        "isolated_anomaly_excluded": phases["phase_4_isolated_anomaly"]["excluded_count"] >= 1,
        "repeated_anomaly_quarantined": phases["phase_5_repeated_anomalies"]["quarantined_count"] >= 1,
        "contamination_prevented": summary["contamination_prevented"],
        "total_observations": summary["total_observations"],
        "phases": phases,
        "summary_metrics": summary,
    }

