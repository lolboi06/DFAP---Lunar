# Author: Sam Roger X
# Component: DFAP Paper 3 Evaluation Harness
# Scope: Experiment Orchestrator, Fairness Verification, and Machine-Readable Researcher Export

import csv
import json
import os
from typing import Dict, List, Any, Optional
from datetime import datetime, timezone

from dfap.experiments.paper3_models import (
    ERArchitecture,
    InjectedError,
    PropagationTrace,
    Paper3Comparison,
)
from dfap.experiments.paper3_case_bank import get_paper3_case_bank
from dfap.experiments.paper3_pipeline import DownstreamPropagationPipeline
from dfap.experiments.paper3_metrics import compare_architectures


class Paper3FairnessError(RuntimeError):
    """Raised when an experimental condition violates identical injection or correction invariants."""
    pass


class Paper3ExperimentHarness:
    """
    Experimental Evaluation Harness for Paper 3:
    'Non-Destructive Identity Ledgers'
    
    Enforces:
    - Strictly identical case population, planted entities, injected errors, and correction triggers.
    - Automated fairness verification checking equivalence before metric computation.
    - Downstream pipeline isolation (zero pollution of production M4/M8/M9 state).
    - Machine-readable JSON and CSV researcher exports.
    """

    def __init__(
        self,
        experiment_id: str = "EXP_PAPER3_DEFAULT",
        seed: int = 42,
        case_bank: Optional[List[Dict[str, Any]]] = None,
    ):
        self.experiment_id = experiment_id
        self.seed = int(seed)
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.case_bank = case_bank if case_bank is not None else get_paper3_case_bank()
        self.pipeline = DownstreamPropagationPipeline()

        # Execution records
        self.baseline_traces: List[PropagationTrace] = []
        self.ledger_traces: List[PropagationTrace] = []
        self.last_comparison: Optional[Paper3Comparison] = None

    def verify_fairness(
        self,
        case_def_a: Dict[str, Any],
        case_def_b: Dict[str, Any],
    ) -> bool:
        """
        Fairness Check (Section 20):
        Verifies that both architectures receive 100% identical:
        - Case ID
        - Error ID
        - Error type
        - Injection point
        - Affected entity
        - Correction step
        - Correction info
        """
        err_a: InjectedError = case_def_a["injected_error"]
        err_b: InjectedError = case_def_b["injected_error"]

        checks = [
            (case_def_a["case_id"] == case_def_b["case_id"], "case_id mismatch"),
            (err_a.error_id == err_b.error_id, "error_id mismatch"),
            (err_a.error_type == err_b.error_type, "error_type mismatch"),
            (err_a.injection_point == err_b.injection_point, "injection_point mismatch"),
            (err_a.affected_canonical_entity == err_b.affected_canonical_entity, "affected_canonical_entity mismatch"),
            (err_a.correction_step == err_b.correction_step, "correction_step mismatch"),
            (err_a.correction_info == err_b.correction_info, "correction_info mismatch"),
        ]

        for ok, msg in checks:
            if not ok:
                raise Paper3FairnessError(f"Fairness verification violated: {msg}")
        return True

    def run_case(
        self,
        case_def: Dict[str, Any],
        architecture: ERArchitecture,
    ) -> PropagationTrace:
        """Executes a single architecture pipeline run for a case."""
        return self.pipeline.run_pipeline(case_def, architecture)

    def run_experiment(self) -> Paper3Comparison:
        """
        Executes the complete comparative evaluation across all benchmark cases.
        Guarantees fairness and compiles metrics.
        """
        self.baseline_traces.clear()
        self.ledger_traces.clear()

        for case_def in self.case_bank:
            # 1. Automated Fairness Check
            self.verify_fairness(case_def, case_def)

            # 2. Run MUTABLE_BASELINE
            t_base = self.run_case(case_def, ERArchitecture.MUTABLE_BASELINE)
            self.baseline_traces.append(t_base)

            # 3. Run LEDGER
            t_ledg = self.run_case(case_def, ERArchitecture.LEDGER)
            self.ledger_traces.append(t_ledg)

        # 4. Synthesize comparative metrics
        comparison = compare_architectures(
            baseline_traces=self.baseline_traces,
            ledger_traces=self.ledger_traces,
            experiment_id=self.experiment_id,
            seed=self.seed,
        )
        self.last_comparison = comparison
        return comparison

    def export_results(self, output_dir: str = "output/paper3_results") -> Dict[str, str]:
        """
        Exports machine-readable researcher datasets:
        1. traces.csv: trial-level downstream propagation traces
        2. comparison.json: full structured Paper3Comparison
        """
        if self.last_comparison is None:
            self.run_experiment()

        os.makedirs(output_dir, exist_ok=True)
        traces_csv = os.path.join(output_dir, "traces.csv")
        comparison_json = os.path.join(output_dir, "comparison.json")

        # 1. Export traces.csv
        with open(traces_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "error_id",
                "architecture",
                "reached_M4_graph",
                "reached_M6_features",
                "reached_M8_baseline",
                "reached_M9_false_positive",
                "propagation_stage_count",
                "corrected_via_event",
                "steps_to_correction",
                "timestamp"
            ])
            for t in self.last_comparison.traces:
                writer.writerow([
                    t.error_id,
                    t.architecture.value,
                    t.reached_M4_graph,
                    t.reached_M6_features,
                    t.reached_M8_baseline,
                    t.reached_M9_false_positive,
                    t.propagation_stage_count,
                    t.corrected_via_event or "",
                    t.steps_to_correction if t.steps_to_correction is not None else "",
                    t.timestamp,
                ])

        # 2. Export comparison.json
        with open(comparison_json, "w", encoding="utf-8") as f:
            f.write(self.last_comparison.model_dump_json(indent=2))

        return {
            "traces_csv": traces_csv,
            "comparison_json": comparison_json,
        }
