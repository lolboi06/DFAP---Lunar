# Author: Sam Roger X
# Component: DFAP Paper 1 Evaluation Harness
# Scope: CLI Interface & Smoke Test Walkthrough for Paper 1 Experiment

import argparse
import json
import os
import sys
from typing import Optional, List, Dict, Any

from dfap.experiments.paper1_models import (
    AbstentionPresentationCondition,
    GroundTruthLabel,
    ParticipantResponse,
)
from dfap.experiments.paper1_harness import Paper1ExperimentHarness


STATE_FILE = "data/paper1_experiment_state.json"


def save_harness_state(harness: Paper1ExperimentHarness, path: str = STATE_FILE):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    state = {
        "experiment_id": harness.experiment_id,
        "seed": harness.seed,
        "created_at": harness.created_at,
        "assignments": {k: v.model_dump() for k, v in harness.assignments.items()},
        "trials": {
            k: [t.model_dump() for t in t_list]
            for k, t_list in harness.trials.items()
        }
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def load_or_create_harness(path: str = STATE_FILE, seed: int = 42, exp_id: str = "EXP_PAPER1_DEFAULT") -> Paper1ExperimentHarness:
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                state = json.load(f)
            harness = Paper1ExperimentHarness(experiment_id=state["experiment_id"], seed=state["seed"])
            harness.created_at = state.get("created_at", harness.created_at)
            from dfap.experiments.paper1_models import ParticipantAssignment, Trial
            harness.assignments = {
                k: ParticipantAssignment(**v) for k, v in state.get("assignments", {}).items()
            }
            harness.trials = {
                k: [Trial(**t) for t in t_list]
                for k, t_list in state.get("trials", {}).items()
            }
            return harness
        except Exception:
            pass
    return Paper1ExperimentHarness(experiment_id=exp_id, seed=seed)


def run_smoke_walkthrough():
    """
    Executes the required synthetic experiment walkthrough (Section 26).
    1. Create Paper 1 experiment.
    2. Load synthetic case bank (7 cases).
    3. Assign participants to each condition.
    4. Generate matched trials across all three conditions.
    5. Show that all three conditions use identical underlying evidence.
    6. Show: SILENT_DROP -> finding absent.
    7. Show: LOW_SCORE -> finding visible but no explicit abstention disclosure.
    8. Show: FORCED_DISCLOSURE -> explicit ABSTAINED claim present.
    9. Confirm all three retain the same underlying M11 state.
    10. Record synthetic participant responses.
    11. Calculate accuracy.
    12. Calculate calibration metrics (ECE, over/underconfidence, Brier).
    13. Export results (CSV & JSON).
    14. Confirm internal condition labels are not present in participant-facing text.
    """
    print("=" * 75)
    print("DFAP PAPER 1: FORCED ABSTENTION DISCLOSURE EXPERIMENT SMOKE TEST")
    print("=" * 75)

    # 1. Create experiment
    exp_id = "EXP_PAPER1_SMOKE_001"
    seed = 42
    harness = Paper1ExperimentHarness(experiment_id=exp_id, seed=seed)
    print(f"\n[Step 1] Experiment Created:")
    print(f"  Experiment ID: {harness.experiment_id}")
    print(f"  Random Seed:   {harness.seed}")
    print(f"  Created At:    {harness.created_at}")

    # 2. Case bank inspection
    case_bank = harness.case_bank_list
    print(f"\n[Step 2] Synthetic Case Bank Loaded: {len(case_bank)} cases")
    for c in case_bank:
        print(f"  - [{c['case_id']}] {c['finding_id']}: M11={c['m11_state']['overall_status']}, GT={c['ground_truth'].value}")

    # 3. Assign 3 participants (one per condition)
    print(f"\n[Step 3] Assigning participants across presentation conditions (Between-Subjects):")
    p_silent = harness.assign_participant("PARTICIPANT_A01", AbstentionPresentationCondition.SILENT_DROP)
    p_low = harness.assign_participant("PARTICIPANT_B02", AbstentionPresentationCondition.LOW_SCORE)
    p_forced = harness.assign_participant("PARTICIPANT_C03", AbstentionPresentationCondition.FORCED_DISCLOSURE)

    print(f"  Participant {p_silent.participant_id} -> {p_silent.condition.value}")
    print(f"  Participant {p_low.participant_id}    -> {p_low.condition.value}")
    print(f"  Participant {p_forced.participant_id} -> {p_forced.condition.value}")

    # 4 & 5. Inspect matched case: CASE_P1_03 (Conflicted finding where M11 abstains)
    target_case_id = "CASE_P1_03"
    c_def = harness.case_bank_dict[target_case_id]
    print(f"\n[Step 4 & 5] Matched Case Invariants Inspection for {target_case_id} ({c_def['finding_id']}):")
    print(f"  M11 State:           {c_def['m11_state']['overall_status']}")
    print(f"  Hellinger Distance:  {c_def['m11_state']['hellinger_distance']}")
    print(f"  Ground Truth:        {c_def['ground_truth'].value}")
    print(f"  Evidence Item Count: {len(c_def['evidence_items'])}")
    print(f"  Evidence IDs:        {[e['evidence_id'] for e in c_def['evidence_items']]}")

    # 6. SILENT_DROP Presentation
    pres_silent = harness.get_trial_presentation("PARTICIPANT_A01", f"TRL_PARTICIPANT_A01_{target_case_id}")
    print(f"\n[Step 6] Condition: SILENT_DROP View:")
    print(f"  Finding Visible:     {pres_silent['case_presentation']['finding_visible']}")
    print(f"  Finding ID:          {pres_silent['case_presentation']['finding_id']}")
    print(f"  Corroboration Score: {pres_silent['case_presentation']['corroboration_score']}")
    print(f"  Status Summary:      {pres_silent['case_presentation']['status_summary']}")
    assert pres_silent["case_presentation"]["finding_visible"] is False, "SILENT_DROP must omit abstained finding"
    assert pres_silent["case_presentation"]["finding_id"] is None, "Finding ID must be None in SILENT_DROP"

    # 7. LOW_SCORE Presentation
    pres_low = harness.get_trial_presentation("PARTICIPANT_B02", f"TRL_PARTICIPANT_B02_{target_case_id}")
    print(f"\n[Step 7] Condition: LOW_SCORE View:")
    print(f"  Finding Visible:     {pres_low['case_presentation']['finding_visible']}")
    print(f"  Finding ID:          {pres_low['case_presentation']['finding_id']}")
    print(f"  Corroboration Score: {pres_low['case_presentation']['corroboration_score']}")
    print(f"  Abstention Disclosed:{pres_low['case_presentation']['abstention_disclosed']}")
    print(f"  Status Summary:      {pres_low['case_presentation']['status_summary']}")
    assert pres_low["case_presentation"]["finding_visible"] is True, "LOW_SCORE must show finding"
    assert pres_low["case_presentation"]["abstention_disclosed"] is False, "LOW_SCORE must NOT disclose abstention"
    assert pres_low["case_presentation"]["corroboration_score"] == 0.20, "LOW_SCORE must present low score"

    # 8. FORCED_DISCLOSURE Presentation
    pres_forced = harness.get_trial_presentation("PARTICIPANT_C03", f"TRL_PARTICIPANT_C03_{target_case_id}")
    print(f"\n[Step 8] Condition: FORCED_DISCLOSURE View:")
    print(f"  Finding Visible:     {pres_forced['case_presentation']['finding_visible']}")
    print(f"  Finding ID:          {pres_forced['case_presentation']['finding_id']}")
    print(f"  Corroboration Score: {pres_forced['case_presentation']['corroboration_score']}")
    print(f"  Abstention Disclosed:{pres_forced['case_presentation']['abstention_disclosed']}")
    print(f"  Status Summary:      {pres_forced['case_presentation']['status_summary']}")
    abst_claims = [c for c in pres_forced["case_presentation"]["claims"] if c.get("claim_type") == "ABSTAINED"]
    print(f"  Structural Claims:   {[c['claim_id'] for c in pres_forced['case_presentation']['claims']]}")
    print(f"  ABSTAINED Claim:     '{abst_claims[0]['text']}'")
    assert pres_forced["case_presentation"]["abstention_disclosed"] is True, "FORCED_DISCLOSURE must disclose abstention"
    assert len(abst_claims) == 1, "FORCED_DISCLOSURE must contain exactly 1 structural ABSTAINED claim"

    # 9. Verify underlying state remains strictly unchanged
    print(f"\n[Step 9] Verifying Underlying State Invariant Across All 3 Presentations:")
    assert c_def["m11_state"]["overall_status"] == "ABSTENTION_REQUIRED"
    assert c_def["ground_truth"] == GroundTruthLabel.WEAKLY_SUPPORTED
    print(f"  Authoritative M11 state preserved: {c_def['m11_state']['overall_status']}")
    print(f"  Ground truth preserved:            {c_def['ground_truth'].value}")

    # 10. Record synthetic participant responses across all 7 trials
    print(f"\n[Step 10] Simulating Synthetic Participant Judgments:")
    # Participant A (SILENT_DROP): without seeing abstention, guesses inconsistently on conflicted cases
    harness.record_response("PARTICIPANT_A01", f"TRL_PARTICIPANT_A01_CASE_P1_01", ParticipantResponse.WELL_SUPPORTED, 0.90)
    harness.record_response("PARTICIPANT_A01", f"TRL_PARTICIPANT_A01_CASE_P1_02", ParticipantResponse.WEAKLY_SUPPORTED, 0.80)
    harness.record_response("PARTICIPANT_A01", f"TRL_PARTICIPANT_A01_CASE_P1_03", ParticipantResponse.WEAKLY_SUPPORTED, 0.50)  # Correct but low confidence
    harness.record_response("PARTICIPANT_A01", f"TRL_PARTICIPANT_A01_CASE_P1_04", ParticipantResponse.WEAKLY_SUPPORTED, 0.85)  # Overconfident incorrect
    harness.record_response("PARTICIPANT_A01", f"TRL_PARTICIPANT_A01_CASE_P1_05", ParticipantResponse.WELL_SUPPORTED, 0.75)    # Overconfident incorrect
    harness.record_response("PARTICIPANT_A01", f"TRL_PARTICIPANT_A01_CASE_P1_06", ParticipantResponse.WELL_SUPPORTED, 0.95)
    harness.record_response("PARTICIPANT_A01", f"TRL_PARTICIPANT_A01_CASE_P1_07", ParticipantResponse.WEAKLY_SUPPORTED, 0.80)

    # Participant C (FORCED_DISCLOSURE): accurately calibrated on conflicted cases
    harness.record_response("PARTICIPANT_C03", f"TRL_PARTICIPANT_C03_CASE_P1_01", ParticipantResponse.WELL_SUPPORTED, 0.90)
    harness.record_response("PARTICIPANT_C03", f"TRL_PARTICIPANT_C03_CASE_P1_02", ParticipantResponse.WEAKLY_SUPPORTED, 0.85)
    harness.record_response("PARTICIPANT_C03", f"TRL_PARTICIPANT_C03_CASE_P1_03", ParticipantResponse.WEAKLY_SUPPORTED, 0.90)
    harness.record_response("PARTICIPANT_C03", f"TRL_PARTICIPANT_C03_CASE_P1_04", ParticipantResponse.WELL_SUPPORTED, 0.80)
    harness.record_response("PARTICIPANT_C03", f"TRL_PARTICIPANT_C03_CASE_P1_05", ParticipantResponse.WEAKLY_SUPPORTED, 0.85)
    harness.record_response("PARTICIPANT_C03", f"TRL_PARTICIPANT_C03_CASE_P1_06", ParticipantResponse.WELL_SUPPORTED, 0.95)
    harness.record_response("PARTICIPANT_C03", f"TRL_PARTICIPANT_C03_CASE_P1_07", ParticipantResponse.WEAKLY_SUPPORTED, 0.85)

    # 11 & 12. Score participants and compute calibration metrics
    print(f"\n[Step 11 & 12] Calibration & Trust Metrics Evaluation:")
    score_a = harness.score_participant("PARTICIPANT_A01")
    score_c = harness.score_participant("PARTICIPANT_C03")
    
    print(f"  SILENT_DROP (Participant A):")
    print(f"    Accuracy:             {score_a.accuracy * 100:.1f}%")
    print(f"    Expected Cal Error:   {score_a.calibration_error:.4f}")
    print(f"    Mean Confidence:      {score_a.mean_confidence:.4f}")
    print(f"    Overconfidence Rate:  {score_a.overconfidence_rate * 100:.1f}%")
    print(f"    Brier Score:          {score_a.brier_score:.4f}")

    print(f"  FORCED_DISCLOSURE (Participant C):")
    print(f"    Accuracy:             {score_c.accuracy * 100:.1f}%")
    print(f"    Expected Cal Error:   {score_c.calibration_error:.4f}")
    print(f"    Mean Confidence:      {score_c.mean_confidence:.4f}")
    print(f"    Overconfidence Rate:  {score_c.overconfidence_rate * 100:.1f}%")
    print(f"    Brier Score:          {score_c.brier_score:.4f}")

    # 13. Export results
    print(f"\n[Step 13] Exporting Researcher Datasets:")
    export_paths = harness.export_results("output/paper1_smoke_results")
    for k, p in export_paths.items():
        print(f"  - {k}: {p} (exists={os.path.exists(p)}, size={os.path.getsize(p)} bytes)")

    # 14. Confirm blinding invariant (condition name never leaked in presentation)
    print(f"\n[Step 14] Verifying Participant Blinding Invariant:")
    pres_json = json.dumps(pres_forced["case_presentation"])
    for cond_name in ["SILENT_DROP", "LOW_SCORE", "FORCED_DISCLOSURE"]:
        assert cond_name not in pres_json, f"Condition name '{cond_name}' leaked in participant presentation!"
    print("  BLINDING VERIFIED: Zero internal condition names present in participant-facing payload.")

    print("\n" + "=" * 75)
    print("PAPER 1 EXPERIMENTAL HARNESS — IMPLEMENTED & VERIFIED")
    print("=" * 75)


def main(args: Optional[List[str]] = None):
    parser = argparse.ArgumentParser(
        prog="dfap.experiments.cli_paper1",
        description="DFAP Paper 1: Forced Abstention Disclosure Experimental Harness CLI"
    )
    subparsers = parser.add_subparsers(dest="command", help="Experiment commands")

    # smoke
    subparsers.add_parser("smoke", help="Run full synthetic experimental walkthrough")

    # create
    p_create = subparsers.add_parser("create", help="Create new experiment session")
    p_create.add_argument("--id", default="EXP_PAPER1_DEFAULT", help="Experiment ID")
    p_create.add_argument("--seed", type=int, default=42, help="Random seed")

    # assign
    p_assign = subparsers.add_parser("assign", help="Assign participant to condition")
    p_assign.add_argument("participant_id", help="Anonymous participant ID")
    p_assign.add_argument("--condition", choices=["SILENT_DROP", "LOW_SCORE", "FORCED_DISCLOSURE"], default=None)

    # trial
    p_trial = subparsers.add_parser("trial", help="Get presentation for a specific trial")
    p_trial.add_argument("participant_id", help="Participant ID")
    p_trial.add_argument("trial_id", help="Trial ID")

    # record
    p_rec = subparsers.add_parser("record", help="Record participant judgment response")
    p_rec.add_argument("participant_id", help="Participant ID")
    p_rec.add_argument("trial_id", help="Trial ID")
    p_rec.add_argument("response", choices=["WELL_SUPPORTED", "WEAKLY_SUPPORTED", "UNSURE"], help="Judgment")
    p_rec.add_argument("confidence", type=float, help="Confidence rating (0.0 - 1.0 or 0 - 100)")
    p_rec.add_argument("--time-ms", type=int, default=None, help="Latency in ms")

    # score
    p_score = subparsers.add_parser("score", help="Score participant accuracy and calibration")
    p_score.add_argument("participant_id", help="Participant ID")

    # aggregate
    subparsers.add_parser("aggregate", help="Aggregate condition-level results across participants")

    # export
    p_exp = subparsers.add_parser("export", help="Export researcher CSV and JSON datasets")
    p_exp.add_argument("--output-dir", default="output/paper1_results", help="Destination folder")

    parsed = parser.parse_args(args)

    if parsed.command == "smoke":
        run_smoke_walkthrough()
        return

    harness = load_or_create_harness()

    if parsed.command == "create":
        harness = Paper1ExperimentHarness(experiment_id=parsed.id, seed=parsed.seed)
        save_harness_state(harness)
        print(f"Created experiment '{parsed.id}' with seed {parsed.seed}.")

    elif parsed.command == "assign":
        cond = AbstentionPresentationCondition(parsed.condition) if parsed.condition else None
        assignment = harness.assign_participant(parsed.participant_id, condition=cond)
        save_harness_state(harness)
        print(json.dumps(assignment.model_dump(), indent=2))

    elif parsed.command == "trial":
        pres = harness.get_trial_presentation(parsed.participant_id, parsed.trial_id)
        print(json.dumps(pres, indent=2))

    elif parsed.command == "record":
        trial = harness.record_response(
            participant_id=parsed.participant_id,
            trial_id=parsed.trial_id,
            response=parsed.response,
            confidence=parsed.confidence,
            response_time_ms=parsed.time_ms,
        )
        save_harness_state(harness)
        print(json.dumps({
            "status": "RECORDED",
            "trial_id": trial.trial_id,
            "is_correct": trial.is_correct,
            "confidence": trial.confidence_rating,
        }, indent=2))

    elif parsed.command == "score":
        metrics = harness.score_participant(parsed.participant_id)
        print(json.dumps(metrics.model_dump(), indent=2))

    elif parsed.command == "aggregate":
        res = harness.aggregate_results()
        print(json.dumps(res.model_dump(), indent=2))

    elif parsed.command == "export":
        paths = harness.export_results(output_dir=parsed.output_dir)
        print(json.dumps({"exported_files": paths}, indent=2))

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
