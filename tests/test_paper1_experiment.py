# Author: Sam Roger X
# Component: DFAP Paper 1 Evaluation Harness
# Scope: Focused Test Suite (20 Tests) for Paper 1 Experimental Evaluation Harness

import os
import json
import pytest
from dfap.experiments.paper1_models import (
    AbstentionPresentationCondition,
    GroundTruthLabel,
    ParticipantResponse,
    ExperimentCase,
    Trial,
    ParticipantAssignment,
    CalibrationMetrics,
)
from dfap.experiments.paper1_renderers import render_presentation
from dfap.experiments.paper1_case_bank import get_paper1_case_bank
from dfap.experiments.paper1_metrics import compute_calibration_metrics
from dfap.experiments.paper1_harness import Paper1ExperimentHarness


@pytest.fixture
def case_bank():
    return get_paper1_case_bank()


@pytest.fixture
def conflicted_case(case_bank):
    for c in case_bank:
        if c["m11_state"].get("overall_status") == "ABSTENTION_REQUIRED":
            return c
    pytest.fail("No conflicted case found in case bank")


@pytest.fixture
def normal_case(case_bank):
    for c in case_bank:
        if c["m11_state"].get("overall_status") == "FUSION_PERMITTED":
            return c
    pytest.fail("No normal case found in case bank")


# ── TEST 1: CONDITION ENUM & MODEL ───────────────────────────────────────────
def test_1_condition_enum_and_model():
    conditions = [
        AbstentionPresentationCondition.SILENT_DROP,
        AbstentionPresentationCondition.LOW_SCORE,
        AbstentionPresentationCondition.FORCED_DISCLOSURE,
    ]
    assert len(conditions) == 3
    assert AbstentionPresentationCondition("SILENT_DROP") == AbstentionPresentationCondition.SILENT_DROP
    assert AbstentionPresentationCondition("LOW_SCORE") == AbstentionPresentationCondition.LOW_SCORE
    assert AbstentionPresentationCondition("FORCED_DISCLOSURE") == AbstentionPresentationCondition.FORCED_DISCLOSURE


# ── TEST 2: DETERMINISTIC PARTICIPANT ASSIGNMENT ─────────────────────────────
def test_2_deterministic_participant_assignment():
    h1 = Paper1ExperimentHarness(seed=12345)
    h2 = Paper1ExperimentHarness(seed=12345)
    
    a1 = h1.assign_participant("ANON_INVESTIGATOR_99")
    a2 = h2.assign_participant("ANON_INVESTIGATOR_99")
    
    assert a1.condition == a2.condition
    assert a1.assignment_seed == a2.assignment_seed == 12345


# ── TEST 3: BALANCED ASSIGNMENT ──────────────────────────────────────────────
def test_3_balanced_assignment():
    h = Paper1ExperimentHarness(seed=999)
    for i in range(12):
        h.assign_participant(f"USER_{i:02d}")
        
    counts = {
        AbstentionPresentationCondition.SILENT_DROP: 0,
        AbstentionPresentationCondition.LOW_SCORE: 0,
        AbstentionPresentationCondition.FORCED_DISCLOSURE: 0,
    }
    for a in h.assignments.values():
        counts[a.condition] += 1
        
    assert counts[AbstentionPresentationCondition.SILENT_DROP] == 4
    assert counts[AbstentionPresentationCondition.LOW_SCORE] == 4
    assert counts[AbstentionPresentationCondition.FORCED_DISCLOSURE] == 4


# ── TEST 4: MATCHED CASE GENERATION ──────────────────────────────────────────
def test_4_matched_case_generation():
    h = Paper1ExperimentHarness(seed=42)
    h.assign_participant("P_A", AbstentionPresentationCondition.SILENT_DROP)
    h.assign_participant("P_B", AbstentionPresentationCondition.LOW_SCORE)
    h.assign_participant("P_C", AbstentionPresentationCondition.FORCED_DISCLOSURE)
    
    trials_a = h.get_participant_trials("P_A")
    trials_b = h.get_participant_trials("P_B")
    trials_c = h.get_participant_trials("P_C")
    
    assert len(trials_a) == len(trials_b) == len(trials_c) == 7
    for ta, tb, tc in zip(trials_a, trials_b, trials_c):
        assert ta.experiment_case_id == tb.experiment_case_id == tc.experiment_case_id
        assert ta.ground_truth == tb.ground_truth == tc.ground_truth


# ── TEST 5: SILENT_DROP BEHAVIOR ─────────────────────────────────────────────
def test_5_silent_drop_behavior(conflicted_case):
    pres = render_presentation(conflicted_case, AbstentionPresentationCondition.SILENT_DROP)
    assert pres["finding_visible"] is False
    assert pres["finding_id"] is None
    assert pres["claims"] == []
    assert pres["abstention_disclosed"] is False


# ── TEST 6: LOW_SCORE BEHAVIOR ───────────────────────────────────────────────
def test_6_low_score_behavior(conflicted_case):
    pres = render_presentation(conflicted_case, AbstentionPresentationCondition.LOW_SCORE)
    assert pres["finding_visible"] is True
    assert pres["finding_id"] == conflicted_case["finding_id"]
    assert pres["corroboration_score"] == 0.20
    assert pres["abstention_disclosed"] is False
    assert not any(c.get("claim_type") == "ABSTAINED" for c in pres["claims"])


# ── TEST 7: FORCED_DISCLOSURE BEHAVIOR ───────────────────────────────────────
def test_7_forced_disclosure_behavior(conflicted_case):
    pres = render_presentation(conflicted_case, AbstentionPresentationCondition.FORCED_DISCLOSURE)
    assert pres["finding_visible"] is True
    assert pres["finding_id"] == conflicted_case["finding_id"]
    assert pres["abstention_disclosed"] is True
    abst_claims = [c for c in pres["claims"] if c.get("claim_type") == "ABSTAINED"]
    assert len(abst_claims) == 1
    assert "ABSTENTION REQUIRED" in abst_claims[0]["text"]


# ── TEST 8: M11 STATE UNCHANGED ACROSS CONDITIONS ────────────────────────────
def test_8_m11_state_unchanged_across_conditions(conflicted_case):
    orig_status = conflicted_case["m11_state"]["overall_status"]
    orig_dist = conflicted_case["m11_state"]["hellinger_distance"]
    
    _ = render_presentation(conflicted_case, AbstentionPresentationCondition.SILENT_DROP)
    _ = render_presentation(conflicted_case, AbstentionPresentationCondition.LOW_SCORE)
    _ = render_presentation(conflicted_case, AbstentionPresentationCondition.FORCED_DISCLOSURE)
    
    assert conflicted_case["m11_state"]["overall_status"] == orig_status
    assert conflicted_case["m11_state"]["hellinger_distance"] == orig_dist


# ── TEST 9: M12 EVIDENCE UNCHANGED ACROSS CONDITIONS ─────────────────────────
def test_9_m12_evidence_unchanged_across_conditions(conflicted_case):
    orig_ev = list(conflicted_case["evidence_items"])
    
    _ = render_presentation(conflicted_case, AbstentionPresentationCondition.SILENT_DROP)
    _ = render_presentation(conflicted_case, AbstentionPresentationCondition.LOW_SCORE)
    _ = render_presentation(conflicted_case, AbstentionPresentationCondition.FORCED_DISCLOSURE)
    
    assert conflicted_case["evidence_items"] == orig_ev


# ── TEST 10: FEATURE 3 RISK UNCHANGED ACROSS CONDITIONS ──────────────────────
def test_10_feature3_risk_unchanged_across_conditions(conflicted_case):
    orig_score = conflicted_case["score"]
    
    _ = render_presentation(conflicted_case, AbstentionPresentationCondition.SILENT_DROP)
    _ = render_presentation(conflicted_case, AbstentionPresentationCondition.LOW_SCORE)
    _ = render_presentation(conflicted_case, AbstentionPresentationCondition.FORCED_DISCLOSURE)
    
    assert conflicted_case["score"] == orig_score


# ── TEST 11: GROUND TRUTH NEVER DERIVED FROM PARTICIPANT RESPONSE ────────────
def test_11_ground_truth_never_derived_from_participant_response():
    h = Paper1ExperimentHarness(seed=42)
    h.assign_participant("P_TEST", AbstentionPresentationCondition.FORCED_DISCLOSURE)
    trial = h.get_participant_trials("P_TEST")[0]
    orig_gt = trial.ground_truth
    
    # Intentionally record opposite response
    opp_resp = (
        ParticipantResponse.WEAKLY_SUPPORTED
        if orig_gt == GroundTruthLabel.WELL_SUPPORTED
        else ParticipantResponse.WELL_SUPPORTED
    )
    rec = h.record_response("P_TEST", trial.trial_id, opp_resp, confidence=0.95)
    
    assert rec.ground_truth == orig_gt
    assert rec.is_correct is False
    assert trial.ground_truth == orig_gt


# ── TEST 12: PARTICIPANT-FACING OUTPUT BLINDS CONDITION NAME ─────────────────
def test_12_participant_facing_output_blinds_condition(conflicted_case, normal_case):
    for cond in AbstentionPresentationCondition:
        pres_c = render_presentation(conflicted_case, cond)
        pres_n = render_presentation(normal_case, cond)
        
        c_str = json.dumps(pres_c)
        n_str = json.dumps(pres_n)
        
        for name in ["SILENT_DROP", "LOW_SCORE", "FORCED_DISCLOSURE"]:
            assert name not in c_str, f"Leaked condition name '{name}' in conflicted presentation"
            assert name not in n_str, f"Leaked condition name '{name}' in normal presentation"


# ── TEST 13: FORCED ABSTAINED CLAIM EXISTS WHEN M11 ABSTAINS ─────────────────
def test_13_forced_abstained_claim_exists(conflicted_case):
    pres = render_presentation(conflicted_case, AbstentionPresentationCondition.FORCED_DISCLOSURE)
    abst_claims = [c for c in pres["claims"] if c.get("claim_type") == "ABSTAINED"]
    assert len(abst_claims) == 1
    assert abst_claims[0]["source_module"] == "M11"
    assert "ABSTENTION REQUIRED" in abst_claims[0]["text"]


# ── TEST 14: SILENT DROP PRESENTATION OMITS ABSTAINED FINDING ────────────────
def test_14_silent_drop_presentation_omits_finding(conflicted_case):
    pres = render_presentation(conflicted_case, AbstentionPresentationCondition.SILENT_DROP)
    assert pres["finding_visible"] is False
    assert pres["finding_id"] is None
    assert pres["corroboration_score"] is None


# ── TEST 15: LOW SCORE PRESENTATION LACKS EXPLICIT ABSTENTION DISCLOSURE ─────
def test_15_low_score_lacks_explicit_abstention_disclosure(conflicted_case):
    pres = render_presentation(conflicted_case, AbstentionPresentationCondition.LOW_SCORE)
    assert pres["finding_visible"] is True
    assert pres["abstention_disclosed"] is False
    for claim in pres["claims"]:
        assert claim.get("claim_type") != "ABSTAINED"
        assert "ABSTENTION" not in claim.get("text", "")


# ── TEST 16: ACCURACY CALCULATION ────────────────────────────────────────────
def test_16_accuracy_calculation():
    trials = [
        Trial(
            trial_id="T1", experiment_case_id="C1", condition=AbstentionPresentationCondition.FORCED_DISCLOSURE,
            case_presentation={}, ground_truth=GroundTruthLabel.WELL_SUPPORTED,
            participant_response=ParticipantResponse.WELL_SUPPORTED, confidence_rating=0.8
        ),
        Trial(
            trial_id="T2", experiment_case_id="C2", condition=AbstentionPresentationCondition.FORCED_DISCLOSURE,
            case_presentation={}, ground_truth=GroundTruthLabel.WEAKLY_SUPPORTED,
            participant_response=ParticipantResponse.WELL_SUPPORTED, confidence_rating=0.7  # incorrect
        ),
        Trial(
            trial_id="T3", experiment_case_id="C3", condition=AbstentionPresentationCondition.FORCED_DISCLOSURE,
            case_presentation={}, ground_truth=GroundTruthLabel.WEAKLY_SUPPORTED,
            participant_response=ParticipantResponse.WEAKLY_SUPPORTED, confidence_rating=0.9
        ),
        Trial(
            trial_id="T4", experiment_case_id="C4", condition=AbstentionPresentationCondition.FORCED_DISCLOSURE,
            case_presentation={}, ground_truth=GroundTruthLabel.WELL_SUPPORTED,
            participant_response=ParticipantResponse.UNSURE, confidence_rating=0.5  # UNSURE -> incorrect
        ),
    ]
    m = compute_calibration_metrics(trials)
    assert m.n_trials == 4
    assert m.accuracy == 0.50  # 2 correct out of 4


# ── TEST 17: CONFIDENCE CALCULATION ──────────────────────────────────────────
def test_17_confidence_calculation():
    trials = [
        Trial(
            trial_id="T1", experiment_case_id="C1", condition=AbstentionPresentationCondition.FORCED_DISCLOSURE,
            case_presentation={}, ground_truth=GroundTruthLabel.WELL_SUPPORTED,
            participant_response=ParticipantResponse.WELL_SUPPORTED, confidence_rating=0.8
        ),
        Trial(
            trial_id="T2", experiment_case_id="C2", condition=AbstentionPresentationCondition.FORCED_DISCLOSURE,
            case_presentation={}, ground_truth=GroundTruthLabel.WEAKLY_SUPPORTED,
            participant_response=ParticipantResponse.WELL_SUPPORTED, confidence_rating=0.6
        ),
    ]
    m = compute_calibration_metrics(trials)
    assert m.mean_confidence == 0.70
    assert m.confidence_when_correct == 0.80
    assert m.confidence_when_incorrect == 0.60


# ── TEST 18: CALIBRATION METRIC (ECE) CALCULATION ────────────────────────────
def test_18_calibration_metric_ece_bounded():
    trials = [
        Trial(
            trial_id=f"T{i}", experiment_case_id=f"C{i}", condition=AbstentionPresentationCondition.LOW_SCORE,
            case_presentation={}, ground_truth=GroundTruthLabel.WELL_SUPPORTED,
            participant_response=ParticipantResponse.WELL_SUPPORTED if i % 2 == 0 else ParticipantResponse.WEAKLY_SUPPORTED,
            confidence_rating=0.75
        )
        for i in range(10)
    ]
    m = compute_calibration_metrics(trials, n_bins=5)
    assert 0.0 <= m.calibration_error <= 1.0
    assert 0.0 <= m.brier_score <= 1.0


# ── TEST 19: OVERCONFIDENCE & UNDERCONFIDENCE CALCULATION ─────────────────────
def test_19_overconfidence_and_underconfidence_calculation():
    trials = [
        # Overconfident: conf >= 0.70 while incorrect
        Trial(
            trial_id="T1", experiment_case_id="C1", condition=AbstentionPresentationCondition.LOW_SCORE,
            case_presentation={}, ground_truth=GroundTruthLabel.WEAKLY_SUPPORTED,
            participant_response=ParticipantResponse.WELL_SUPPORTED, confidence_rating=0.85
        ),
        # Underconfident: conf <= 0.40 while correct
        Trial(
            trial_id="T2", experiment_case_id="C2", condition=AbstentionPresentationCondition.LOW_SCORE,
            case_presentation={}, ground_truth=GroundTruthLabel.WELL_SUPPORTED,
            participant_response=ParticipantResponse.WELL_SUPPORTED, confidence_rating=0.30
        ),
        # Well-calibrated
        Trial(
            trial_id="T3", experiment_case_id="C3", condition=AbstentionPresentationCondition.LOW_SCORE,
            case_presentation={}, ground_truth=GroundTruthLabel.WELL_SUPPORTED,
            participant_response=ParticipantResponse.WELL_SUPPORTED, confidence_rating=0.90
        ),
        Trial(
            trial_id="T4", experiment_case_id="C4", condition=AbstentionPresentationCondition.LOW_SCORE,
            case_presentation={}, ground_truth=GroundTruthLabel.WEAKLY_SUPPORTED,
            participant_response=ParticipantResponse.WEAKLY_SUPPORTED, confidence_rating=0.80
        ),
    ]
    m = compute_calibration_metrics(trials)
    assert m.overconfidence_rate == 0.25  # 1 in 4
    assert m.underconfidence_rate == 0.25  # 1 in 4


# ── TEST 20: DETERMINISTIC EXPORT & REPRODUCIBILITY ──────────────────────────
def test_20_deterministic_export_and_reproducibility(tmp_path):
    h = Paper1ExperimentHarness(experiment_id="EXP_TEST_EXPORT", seed=42)
    h.assign_participant("P1", AbstentionPresentationCondition.SILENT_DROP)
    h.assign_participant("P2", AbstentionPresentationCondition.FORCED_DISCLOSURE)
    
    # Record one response for each
    h.record_response("P1", "TRL_P1_CASE_P1_01", ParticipantResponse.WELL_SUPPORTED, 0.85)
    h.record_response("P2", "TRL_P2_CASE_P1_01", ParticipantResponse.WELL_SUPPORTED, 0.90)
    
    export_dir = str(tmp_path / "export_test")
    paths = h.export_results(export_dir)
    
    assert os.path.exists(paths["trials_csv"])
    assert os.path.exists(paths["participants_csv"])
    assert os.path.exists(paths["results_json"])
    
    # Inspect CSV rows
    with open(paths["trials_csv"], "r", encoding="utf-8") as f:
        lines = f.readlines()
        assert len(lines) >= 15  # header + 14 trials (7 per participant)
        assert "m11_overall_status" in lines[0]
        
    with open(paths["results_json"], "r", encoding="utf-8") as f:
        data = json.load(f)
        assert data["experiment_id"] == "EXP_TEST_EXPORT"
        assert data["participant_count"] == 2
        assert "FORCED_DISCLOSURE" in data["conditions"]
