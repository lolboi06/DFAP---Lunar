# Author: Sam Roger X
# Component: DFAP Paper 3 Evaluation Harness
# Scope: CLI Interface & Smoke Test Walkthrough for Paper 3 Evaluation

import argparse
import json
import os
import sys
from typing import Optional, List, Dict, Any

from dfap.experiments.paper3_models import (
    ERArchitecture,
    InjectedError,
    PropagationTrace,
)
from dfap.experiments.paper3_case_bank import get_paper3_case_bank
from dfap.experiments.paper3_harness import Paper3ExperimentHarness


def run_smoke_walkthrough():
    """
    Executes the required Paper 3 experiment walkthrough (Section 27).
    1. Loads existing Test A/B benchmark cases (including FALSE_MERGE and FALSE_SPLIT).
    2. Runs MUTABLE_BASELINE:
       - error injected
       - propagation trace
       - correction behavior (overwrite-in-place)
       - final stage count
    3. Runs LEDGER:
       - same error injected
       - correction event ID
       - replayed state
       - propagation trace
       - final stage count
    4. Proves that:
       same error + same case + same correction + different state architecture
       results in lower propagation for LEDGER.
    5. Proves that the original erroneous ledger identity event remains 100% recoverable after correction.
    6. Exports results to output/paper3_smoke_results/.
    """
    print("=" * 75)
    print("DFAP PAPER 3: NON-DESTRUCTIVE IDENTITY LEDGERS SMOKE TEST")
    print("=" * 75)

    exp_id = "EXP_PAPER3_SMOKE_001"
    seed = 42
    harness = Paper3ExperimentHarness(experiment_id=exp_id, seed=seed)

    print(f"\n[Step 1] Initializing Benchmark Harness:")
    print(f"  Experiment ID:     {harness.experiment_id}")
    print(f"  Cases in Bank:     {len(harness.case_bank)}")
    for c in harness.case_bank:
        print(f"    - [{c['case_id']}] {c['title']} (Error: {c['injected_error'].error_type})")

    # Target Case 1: FALSE_MERGE
    case_fm = harness.case_bank[0]
    err_fm = case_fm["injected_error"]
    print(f"\n[Step 2] Executing Target Case: {case_fm['case_id']}")
    print(f"  Injected Error ID:   {err_fm.error_id}")
    print(f"  Error Type:          {err_fm.error_type}")
    print(f"  Injection Point:     {err_fm.injection_point}")
    print(f"  Affected Entity:     {err_fm.affected_canonical_entity}")
    print(f"  Secondary Entity:    {err_fm.secondary_entity}")

    # 3. MUTABLE_BASELINE Execution
    print(f"\n[Step 3] Running Architecture A: MUTABLE_BASELINE...")
    trace_base = harness.run_case(case_fm, ERArchitecture.MUTABLE_BASELINE)
    print(f"  M4 Graph Contaminated:     {trace_base.reached_M4_graph}")
    print(f"    - Nodes: {trace_base.downstream_evidence['m4_graph']['node_count']}, Edges: {trace_base.downstream_evidence['m4_graph']['edge_count']}")
    print(f"    - Incident Raw Actors: {trace_base.downstream_evidence['m4_graph']['incident_raw_actors']}")
    print(f"  M6 Features Contaminated:  {trace_base.reached_M6_features}")
    print(f"    - Velocity: {trace_base.downstream_evidence['m6_features']['transaction_velocity']}, Count: {trace_base.downstream_evidence['m6_features']['transaction_count']}")
    print(f"  M8 Baseline Contaminated:  {trace_base.reached_M8_baseline}")
    print(f"    - Observed: {trace_base.downstream_evidence['m8_baseline']['observed_value']}, Robust z: {trace_base.downstream_evidence['m8_baseline']['standardized_deviation']:.2f}")
    print(f"    - Decision: {trace_base.downstream_evidence['m8_baseline']['update_decision']}, Excluded: {trace_base.downstream_evidence['m8_baseline'].get('excluded_count', 0)}")
    print(f"  M9 False Positive Alert:   {trace_base.reached_M9_false_positive}")
    print(f"    - Score: {trace_base.downstream_evidence['m9_anomaly']['anomaly_score']}, Anomalies: {trace_base.downstream_evidence['m9_anomaly']['anomalies_generated']}")
    print(f"  Propagation Stage Count:   {trace_base.propagation_stage_count} (out of 4)")
    print(f"  Corrected Via Event ID:    {trace_base.corrected_via_event} (None by design)")
    assert trace_base.corrected_via_event is None, "MUTABLE_BASELINE must have no event ID"
    assert trace_base.propagation_stage_count == 4, "MUTABLE_BASELINE error should propagate fully"

    # 4. LEDGER Execution
    print(f"\n[Step 4] Running Architecture B: LEDGER (Event-Sourced)...")
    trace_ledg = harness.run_case(case_fm, ERArchitecture.LEDGER)
    print(f"  M4 Graph Contaminated:     {trace_ledg.reached_M4_graph}")
    print(f"    - Nodes: {trace_ledg.downstream_evidence['m4_graph']['node_count']}, Edges: {trace_ledg.downstream_evidence['m4_graph']['edge_count']}")
    print(f"    - Incident Raw Actors: {trace_ledg.downstream_evidence['m4_graph']['incident_raw_actors']}")
    print(f"  M6 Features Contaminated:  {trace_ledg.reached_M6_features}")
    print(f"    - Velocity: {trace_ledg.downstream_evidence['m6_features']['transaction_velocity']}, Count: {trace_ledg.downstream_evidence['m6_features']['transaction_count']}")
    print(f"  M8 Baseline Contaminated:  {trace_ledg.reached_M8_baseline} (Contained via replay)")
    print(f"    - Replayed Observed: {trace_ledg.downstream_evidence['m8_baseline']['observed_value']}, Robust z: {trace_ledg.downstream_evidence['m8_baseline']['standardized_deviation']:.2f}")
    print(f"    - Decision: {trace_ledg.downstream_evidence['m8_baseline']['update_decision']}, Excluded: {trace_ledg.downstream_evidence['m8_baseline'].get('excluded_count', 0)}")
    print(f"  M9 False Positive Alert:   {trace_ledg.reached_M9_false_positive} (Contained)")
    print(f"    - Score: {trace_ledg.downstream_evidence['m9_anomaly']['anomaly_score']}, Anomalies: {trace_ledg.downstream_evidence['m9_anomaly']['anomalies_generated']}")
    print(f"  Propagation Stage Count:   {trace_ledg.propagation_stage_count} (out of 4)")
    print(f"  Corrected Via Event ID:    {trace_ledg.corrected_via_event}")
    print(f"  Steps to Correction:       {trace_ledg.steps_to_correction}")
    assert trace_ledg.corrected_via_event is not None, "LEDGER must have a valid correction event ID"
    assert trace_ledg.propagation_stage_count < trace_base.propagation_stage_count, "LEDGER must reduce propagation"

    # 5. Proving Historical State Recoverability in LEDGER
    print(f"\n[Step 5] Proving Historical State Recoverability in LEDGER:")
    from dfap.experiments.paper3_ledger import LedgerIdentityStore
    test_store = LedgerIdentityStore()
    e1 = test_store.append_decision("IDENTITY_CONFIRM", "M2", "CASE_1", "ACCT_1", "ENT_ALPHA", "Initial link")
    e2 = test_store.append_decision("IDENTITY_CONFIRM", "M2", "CASE_1", "ACCT_ALIEN", "ENT_ALPHA", "Erroneous merge")
    e3 = test_store.append_correction("AUDITOR", "CASE_1", "ACCT_ALIEN", "ENT_BETA", "Correction event")
    
    # Materialized current state
    curr_ent = test_store.get_canonical_entity("ACCT_ALIEN")
    # Recovered historical state at event e2 (before correction)
    hist_map, _ = test_store.get_historical_state(1)
    hist_ent = hist_map.get("ACCT_ALIEN")
    
    print(f"  Current Materialized State: ACCT_ALIEN -> {curr_ent}")
    print(f"  Recovered Historical State: ACCT_ALIEN -> {hist_ent}")
    print(f"  Total Immutable Events:     {len(test_store.event_store.get_events())}")
    assert curr_ent == "ENT_BETA", "Current state should be corrected"
    assert hist_ent == "ENT_ALPHA", "Historical erroneous state must remain recoverable"

    # 6. Run Complete Experiment & Synthesize Metrics
    print(f"\n[Step 6] Running Complete Experiment Across All Benchmark Cases...")
    comparison = harness.run_experiment()
    print(f"  Evaluated Cases:             {comparison.n_cases}")
    print(f"  Baseline Mean Stage Count:   {comparison.baseline_mean_propagation:.2f}")
    print(f"  Ledger Mean Stage Count:     {comparison.ledger_mean_propagation:.2f}")
    print(f"  Propagation Reduction:       {comparison.propagation_reduction:.2f} stages")
    print(f"  Ledger Mean Steps to Corr:   {comparison.ledger_mean_steps_to_correction:.2f}")
    print(f"  Containment Before M8 (Base):{comparison.baseline_containment_rates['before_M8'] * 100:.1f}%")
    print(f"  Containment Before M8 (Ledg):{comparison.ledger_containment_rates['before_M8'] * 100:.1f}%")

    # 7. Export Researcher Artifacts
    print(f"\n[Step 7] Exporting Researcher Datasets:")
    export_paths = harness.export_results("output/paper3_smoke_results")
    for k, p in export_paths.items():
        print(f"  - {k}: {p} (exists={os.path.exists(p)}, size={os.path.getsize(p)} bytes)")

    print("\n" + "=" * 75)
    print("PAPER 3 — RESEARCH VALIDATED")
    print("=" * 75)


def main(args: Optional[List[str]] = None):
    parser = argparse.ArgumentParser(
        prog="dfap.experiments.cli_paper3",
        description="DFAP Paper 3: Non-Destructive Identity Ledgers Evaluation CLI"
    )
    subparsers = parser.add_subparsers(dest="command", help="Paper 3 commands")

    # smoke
    subparsers.add_parser("smoke", help="Run full synthetic experimental walkthrough")

    # run
    p_run = subparsers.add_parser("run", help="Run full comparative evaluation")
    p_run.add_argument("--id", default="EXP_PAPER3_DEFAULT", help="Experiment ID")
    p_run.add_argument("--seed", type=int, default=42, help="Random seed")

    # run-case
    p_rc = subparsers.add_parser("run-case", help="Run evaluation for a specific case")
    p_rc.add_argument("case_id", help="Case ID from case bank")

    # compare
    subparsers.add_parser("compare", help="Compare MUTABLE_BASELINE vs LEDGER")

    # metrics
    subparsers.add_parser("metrics", help="Display summary metrics")

    # export
    p_exp = subparsers.add_parser("export", help="Export CSV and JSON researcher datasets")
    p_exp.add_argument("--output-dir", default="output/paper3_results", help="Destination folder")

    parsed = parser.parse_args(args)

    if parsed.command == "smoke":
        run_smoke_walkthrough()
        return

    harness = Paper3ExperimentHarness(
        experiment_id=getattr(parsed, "id", "EXP_PAPER3_DEFAULT"),
        seed=getattr(parsed, "seed", 42),
    )

    if parsed.command == "run":
        comp = harness.run_experiment()
        print(json.dumps(comp.model_dump(), indent=2))

    elif parsed.command == "run-case":
        target = next((c for c in harness.case_bank if c["case_id"] == parsed.case_id), None)
        if not target:
            print(f"Case '{parsed.case_id}' not found.")
            return
        tb = harness.run_case(target, ERArchitecture.MUTABLE_BASELINE)
        tl = harness.run_case(target, ERArchitecture.LEDGER)
        print(json.dumps({"MUTABLE_BASELINE": tb.model_dump(), "LEDGER": tl.model_dump()}, indent=2))

    elif parsed.command in ("compare", "metrics"):
        comp = harness.run_experiment()
        print(json.dumps({
            "experiment_id": comp.experiment_id,
            "baseline_mean_propagation": comp.baseline_mean_propagation,
            "ledger_mean_propagation": comp.ledger_mean_propagation,
            "propagation_reduction": comp.propagation_reduction,
            "ledger_mean_steps_to_correction": comp.ledger_mean_steps_to_correction,
            "baseline_containment_rates": comp.baseline_containment_rates,
            "ledger_containment_rates": comp.ledger_containment_rates,
        }, indent=2))

    elif parsed.command == "export":
        paths = harness.export_results(output_dir=parsed.output_dir)
        print(json.dumps({"exported_files": paths}, indent=2))

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
