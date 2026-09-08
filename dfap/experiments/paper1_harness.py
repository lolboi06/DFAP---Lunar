# Author: Sam Roger X
# Component: DFAP Paper 1 Evaluation Harness
# Scope: Experiment Runner, Balanced Randomization, Trial Orchestration, and Researcher Export

import csv
import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Union

from dfap.experiments.paper1_models import (
    AbstentionPresentationCondition,
    GroundTruthLabel,
    ParticipantResponse,
    ParticipantAssignment,
    Trial,
    CalibrationMetrics,
    ConditionMetrics,
    ExperimentResult,
)
from dfap.experiments.paper1_case_bank import get_paper1_case_bank
from dfap.experiments.paper1_renderers import render_presentation
from dfap.experiments.paper1_metrics import (
    compute_calibration_metrics,
    compute_condition_breakdowns,
)


class Paper1ExperimentHarness:
    """
    Experimental Evaluation Harness for Paper 1:
    'Forced Abstention Disclosure in Multi-Domain Evidence Fusion'
    
    Enforces:
    - Identical M11, M12, Ground Truth, Risk Tier, and Graph state across conditions.
    - Strictly controlled between-subjects balanced assignment.
    - Complete blinding of experimental condition names in participant-facing views.
    - Deterministic trust calibration metrics (ECE, Over/Underconfidence, Brier Score).
    - Comprehensive researcher trial-level and condition-level exports.
    """

    def __init__(
        self,
        experiment_id: str = "EXP_PAPER1_DEFAULT",
        seed: int = 42,
        case_bank: Optional[List[Dict[str, Any]]] = None,
    ):
        self.experiment_id = experiment_id
        self.seed = int(seed)
        self.created_at = datetime.now(timezone.utc).isoformat()
        
        # Load synthetic case bank
        raw_cases = case_bank if case_bank is not None else get_paper1_case_bank()
        self.case_bank_dict: Dict[str, Dict[str, Any]] = {c["case_id"]: c for c in raw_cases}
        self.case_bank_list: List[Dict[str, Any]] = raw_cases

        # State storage
        self.assignments: Dict[str, ParticipantAssignment] = {}
        self.trials: Dict[str, List[Trial]] = {}  # participant_id -> List[Trial]

    # ── 1. BALANCED RANDOMIZATION & ASSIGNMENT ───────────────────────────────

    def assign_participant(
        self,
        participant_id: str,
        condition: Optional[AbstentionPresentationCondition] = None,
    ) -> ParticipantAssignment:
        """
        Assigns an anonymous participant to a presentation condition.
        If condition is None, performs balanced deterministic assignment based on current cohort sizes and seed.
        """
        p_id = str(participant_id).strip()
        if p_id in self.assignments:
            return self.assignments[p_id]

        if condition is not None:
            chosen_cond = condition
        else:
            # Deterministic balanced assignment
            conditions = [
                AbstentionPresentationCondition.SILENT_DROP,
                AbstentionPresentationCondition.LOW_SCORE,
                AbstentionPresentationCondition.FORCED_DISCLOSURE,
            ]
            
            # Count current assignments per condition
            counts = {c: 0 for c in conditions}
            for a in self.assignments.values():
                counts[a.condition] += 1

            min_count = min(counts.values())
            candidate_conditions = [c for c in conditions if counts[c] == min_count]

            if len(candidate_conditions) == 1:
                chosen_cond = candidate_conditions[0]
            else:
                # Deterministic tie-breaking using seed and participant hash
                hash_input = f"{self.seed}:{p_id}".encode("utf-8")
                hash_val = int(hashlib.sha256(hash_input).hexdigest(), 16)
                chosen_cond = candidate_conditions[hash_val % len(candidate_conditions)]

        assignment = ParticipantAssignment(
            participant_id=p_id,
            condition=chosen_cond,
            assignment_seed=self.seed,
            assigned_at=datetime.now(timezone.utc).isoformat()
        )
        self.assignments[p_id] = assignment

        # Automatically generate trials for this participant
        self._generate_trials_for_participant(p_id, chosen_cond)

        return assignment

    # ── 2. TRIAL GENERATION & PRESENTATION ───────────────────────────────────

    def _generate_trials_for_participant(
        self,
        participant_id: str,
        condition: AbstentionPresentationCondition,
    ) -> List[Trial]:
        """Generates matched trials for each case in the case bank for the assigned condition."""
        trials_list: List[Trial] = []

        for case_def in self.case_bank_list:
            case_id = case_def["case_id"]
            trial_id = f"TRL_{participant_id}_{case_id}"

            # Render presentation under the assigned condition (strictly blinded)
            presentation = render_presentation(case_def, condition)

            trial = Trial(
                trial_id=trial_id,
                experiment_case_id=case_id,
                condition=condition,
                case_presentation=presentation,
                question="Based on the case information presented, how well-supported is this finding?",
                ground_truth=case_def["ground_truth"],
                participant_response=None,
                response_time_ms=None,
                confidence_rating=None,
                is_correct=None,
            )
            trials_list.append(trial)

        self.trials[participant_id] = trials_list
        return trials_list

    def get_participant_trials(self, participant_id: str) -> List[Trial]:
        """Returns trials for a participant. Auto-assigns if participant is new."""
        if participant_id not in self.assignments:
            self.assign_participant(participant_id)
        return self.trials[participant_id]

    def get_trial_presentation(self, participant_id: str, trial_id: str) -> Dict[str, Any]:
        """
        Retrieves the participant-facing presentation payload for a specific trial.
        Guarantees that internal condition labels are strictly absent.
        """
        trials = self.get_participant_trials(participant_id)
        for t in trials:
            if t.trial_id == trial_id:
                # Return presentation payload + question + trial_id
                return {
                    "trial_id": t.trial_id,
                    "case_id": t.experiment_case_id,
                    "question": t.question,
                    "case_presentation": t.case_presentation,
                    "response_options": ["WELL_SUPPORTED", "WEAKLY_SUPPORTED", "UNSURE"],
                }
        raise KeyError(f"Trial ID '{trial_id}' not found for participant '{participant_id}'.")

    # ── 3. RESPONSE RECORDING & SCORING ──────────────────────────────────────

    def record_response(
        self,
        participant_id: str,
        trial_id: str,
        response: Union[str, ParticipantResponse],
        confidence: float,
        response_time_ms: Optional[int] = None,
    ) -> Trial:
        """
        Records investigator judgment and confidence rating.
        Ground truth is strictly defined by the fixture and never altered by the response.
        """
        trials = self.get_participant_trials(participant_id)
        target_trial: Optional[Trial] = None
        for t in trials:
            if t.trial_id == trial_id:
                target_trial = t
                break

        if target_trial is None:
            raise KeyError(f"Trial '{trial_id}' not found for participant '{participant_id}'.")

        # Parse response
        if isinstance(response, str):
            resp_clean = response.strip().upper()
            resp_enum = ParticipantResponse(resp_clean)
        else:
            resp_enum = response

        # Validate confidence in [0.0, 1.0]
        conf_val = float(confidence)
        if conf_val > 1.0 and conf_val <= 100.0:
            # Handle percentage input e.g. 80 -> 0.80
            conf_val = conf_val / 100.0
        conf_val = max(0.0, min(1.0, conf_val))

        target_trial.participant_response = resp_enum
        target_trial.confidence_rating = round(conf_val, 4)
        target_trial.response_time_ms = response_time_ms
        target_trial.is_correct = (resp_enum.value == target_trial.ground_truth.value)

        return target_trial

    def score_participant(self, participant_id: str) -> CalibrationMetrics:
        """Computes calibration and accuracy metrics for an individual participant."""
        trials = self.get_participant_trials(participant_id)
        completed = [t for t in trials if t.participant_response is not None]
        return compute_calibration_metrics(completed)

    # ── 4. AGGREGATION & BETWEEN-SUBJECTS COMPARISON ─────────────────────────

    def aggregate_results(self) -> ExperimentResult:
        """
        Aggregates completed trials across all participants into condition-level metrics.
        Facilitates direct comparison of SILENT_DROP vs LOW_SCORE vs FORCED_DISCLOSURE.
        """
        condition_trials: Dict[AbstentionPresentationCondition, List[Trial]] = {
            AbstentionPresentationCondition.SILENT_DROP: [],
            AbstentionPresentationCondition.LOW_SCORE: [],
            AbstentionPresentationCondition.FORCED_DISCLOSURE: [],
        }
        condition_participants: Dict[AbstentionPresentationCondition, set] = {
            AbstentionPresentationCondition.SILENT_DROP: set(),
            AbstentionPresentationCondition.LOW_SCORE: set(),
            AbstentionPresentationCondition.FORCED_DISCLOSURE: set(),
        }

        total_trials_count = 0
        for p_id, p_trials in self.trials.items():
            assignment = self.assignments[p_id]
            for t in p_trials:
                if t.participant_response is not None:
                    condition_trials[assignment.condition].append(t)
                    condition_participants[assignment.condition].add(p_id)
                    total_trials_count += 1

        conditions_summary: Dict[str, ConditionMetrics] = {}
        for cond, t_list in condition_trials.items():
            metrics = compute_calibration_metrics(t_list)
            breakdowns = compute_condition_breakdowns(t_list, self.case_bank_dict)
            conditions_summary[cond.value] = ConditionMetrics(
                condition=cond,
                n_participants=len(condition_participants[cond]),
                n_trials=len(t_list),
                metrics=metrics,
                breakdowns=breakdowns,
            )

        return ExperimentResult(
            experiment_id=self.experiment_id,
            experiment_seed=self.seed,
            created_at=self.created_at,
            participant_count=len(self.assignments),
            total_trials=total_trials_count,
            conditions=conditions_summary,
        )

    # ── 5. RESEARCHER DATA EXPORT ────────────────────────────────────────────

    def export_results(self, output_dir: str = "output/paper1_results") -> Dict[str, str]:
        """
        Exports machine-readable researcher datasets:
        1. trials.csv: atomic trial judgments with M11 state and confidence
        2. participants.csv: participant condition assignments
        3. results.json: aggregated condition metrics & ECE calibration
        """
        os.makedirs(output_dir, exist_ok=True)
        trials_csv_path = os.path.join(output_dir, "trials.csv")
        participants_csv_path = os.path.join(output_dir, "participants.csv")
        results_json_path = os.path.join(output_dir, "results.json")

        # 1. Export trials.csv
        with open(trials_csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "trial_id",
                "participant_id",
                "condition",
                "experiment_case_id",
                "finding_id",
                "ground_truth",
                "m11_overall_status",
                "participant_response",
                "confidence_rating",
                "is_correct",
                "response_time_ms",
            ])
            for p_id, p_trials in self.trials.items():
                for t in p_trials:
                    c_def = self.case_bank_dict.get(t.experiment_case_id, {})
                    m11_st = c_def.get("m11_state", {}).get("overall_status", "UNKNOWN")
                    writer.writerow([
                        t.trial_id,
                        p_id,
                        t.condition.value,
                        t.experiment_case_id,
                        c_def.get("finding_id", "N/A"),
                        t.ground_truth.value,
                        m11_st,
                        t.participant_response.value if t.participant_response else "",
                        t.confidence_rating if t.confidence_rating is not None else "",
                        t.is_correct if t.is_correct is not None else "",
                        t.response_time_ms if t.response_time_ms is not None else "",
                    ])

        # 2. Export participants.csv
        with open(participants_csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["participant_id", "condition", "assignment_seed", "assigned_at"])
            for p_id, a in self.assignments.items():
                writer.writerow([a.participant_id, a.condition.value, a.assignment_seed, a.assigned_at])

        # 3. Export results.json
        agg_res = self.aggregate_results()
        with open(results_json_path, "w", encoding="utf-8") as f:
            f.write(agg_res.model_dump_json(indent=2))

        return {
            "trials_csv": trials_csv_path,
            "participants_csv": participants_csv_path,
            "results_json": results_json_path,
        }
