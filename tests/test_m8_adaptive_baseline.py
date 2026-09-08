# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: M8 Adaptive Behavioral Baselines - Comprehensive Test Suite

import pytest
import math
from dfap.investigation.adaptive_baseline import (
    AdaptiveBaselineTracker,
    AdaptiveBaselineManager,
    BaselineState,
    UpdateDecision,
    SignalClassification,
    BaselineObservationRecord,
    run_five_phase_research_fixture,
)
from dfap.investigation.workspace import InvestigationWorkspaceBackend
from dfap.investigation.copilot import InvestigationCopilot
from dfap.wp4.cli import handle_m13_command


def test_ewma_calculation_accuracy():
    """Verify exact mathematical correctness of EWMA formula: EWMA_t = alpha * x_t + (1 - alpha) * EWMA_(t-1)."""
    alpha = 0.2
    tracker = AdaptiveBaselineTracker(alpha=alpha, min_observations=1, deviation_threshold=15.0)
    
    # Obs 1: x_0 = 10.0
    r1 = tracker.observe(10.0)
    assert r1.new_baseline == 10.0
    assert tracker.current_baseline == 10.0
    
    # Obs 2: x_1 = 20.0 -> EWMA_1 = 0.2 * 20.0 + 0.8 * 10.0 = 4.0 + 8.0 = 12.0
    r2 = tracker.observe(20.0)
    assert pytest.approx(r2.new_baseline, 1e-6) == 12.0
    assert pytest.approx(tracker.current_baseline, 1e-6) == 12.0
    
    # Obs 3: x_2 = 15.0 -> EWMA_2 = 0.2 * 15.0 + 0.8 * 12.0 = 3.0 + 9.6 = 12.6
    r3 = tracker.observe(15.0)
    assert pytest.approx(r3.new_baseline, 1e-6) == 12.6
    assert pytest.approx(tracker.current_baseline, 1e-6) == 12.6


def test_deterministic_repeated_calculation():
    """Verify identical sequence of inputs produces bitwise identical baseline outputs and history."""
    obs_seq = [10.0, 10.5, 9.8, 10.2, 10.1, 10.3, 15.0, 250.0, 10.4]
    
    t1 = AdaptiveBaselineTracker(alpha=0.15, min_observations=5, deviation_threshold=2.5)
    t2 = AdaptiveBaselineTracker(alpha=0.15, min_observations=5, deviation_threshold=2.5)
    
    for v in obs_seq:
        t1.observe(v)
        t2.observe(v)
        
    assert t1.current_baseline == t2.current_baseline
    assert t1.state == t2.state
    assert t1.observation_count == t2.observation_count
    assert t1.excluded_count == t2.excluded_count
    assert len(t1.history) == len(t2.history)
    for r1, r2 in zip(t1.history, t2.history):
        assert r1.to_dict() == r2.to_dict()


def test_cold_start_accumulation_and_transition():
    """Verify tracker starts in COLD_START and transitions to STABLE_BASELINE upon reaching min_observations."""
    min_obs = 5
    tracker = AdaptiveBaselineTracker(alpha=0.1, min_observations=min_obs)
    assert tracker.state == BaselineState.COLD_START
    
    for i in range(1, min_obs):
        r = tracker.observe(50.0)
        assert r.state_after == BaselineState.COLD_START.value
        assert r.update_decision == UpdateDecision.COLD_START_ACCUMULATION.value
        assert tracker.state == BaselineState.COLD_START
        
    # Reaching min_obs transitions to STABLE_BASELINE
    r_final = tracker.observe(50.0)
    assert r_final.state_after == BaselineState.STABLE_BASELINE.value
    assert tracker.state == BaselineState.STABLE_BASELINE


def test_gradual_drift_adaptation():
    """Verify that small, persistent shifts in behavior enter ADAPTATION_IN_PROGRESS and adjust baseline."""
    tracker = AdaptiveBaselineTracker(alpha=0.2, min_observations=5, deviation_threshold=2.5)
    # Establish stable baseline around 100.0
    for _ in range(10):
        tracker.observe(100.0)
    assert tracker.state == BaselineState.STABLE_BASELINE
    initial_baseline = tracker.current_baseline
    
    # Introduce small gradual increments
    drift_values = [100.5, 101.0, 101.5, 102.0, 102.5, 103.0]
    for v in drift_values:
        tracker.observe(v)
        
    # Baseline should have increased gradually toward 103.0
    assert tracker.current_baseline > initial_baseline
    assert tracker.adaptation_count > 0


def test_isolated_anomaly_exclusion():
    """Verify that an isolated extreme value is excluded and does not contaminate the baseline."""
    tracker = AdaptiveBaselineTracker(alpha=0.1, min_observations=5, deviation_threshold=2.5)
    # Establish baseline around 50.0 with minor variance
    for v in [50.0, 49.5, 50.5, 50.0, 50.2, 49.8, 50.1, 49.9]:
        tracker.observe(v)
    assert tracker.state == BaselineState.STABLE_BASELINE
    baseline_before = tracker.current_baseline
    
    # Spike observation
    record = tracker.observe(500.0)
    assert record.update_decision == UpdateDecision.EXCLUDED_FROM_BASELINE.value
    assert record.new_baseline == baseline_before
    assert tracker.current_baseline == baseline_before
    assert tracker.excluded_count == 1
    assert "excluded from baseline update" in record.update_reason


def test_repeated_anomaly_quarantine():
    """Verify that consecutive extreme anomalies are quarantined to protect baseline integrity."""
    tracker = AdaptiveBaselineTracker(alpha=0.1, min_observations=5, deviation_threshold=2.5)
    for v in [20.0, 20.1, 19.9, 20.0, 20.2, 19.8]:
        tracker.observe(v)
    baseline_before = tracker.current_baseline
    
    # Send 4 repeated anomalies
    r1 = tracker.observe(300.0)
    assert r1.update_decision == UpdateDecision.EXCLUDED_FROM_BASELINE.value
    
    r2 = tracker.observe(305.0)
    assert r2.update_decision == UpdateDecision.QUARANTINED.value
    
    r3 = tracker.observe(310.0)
    assert r3.update_decision == UpdateDecision.QUARANTINED.value
    
    assert tracker.quarantined_count >= 2
    # Crucially, baseline is NOT contaminated
    assert tracker.current_baseline == baseline_before


def test_history_immutability():
    """Verify that history is an append-only audit trail recording step-by-step telemetry."""
    tracker = AdaptiveBaselineTracker(alpha=0.1, min_observations=3)
    tracker.observe(10.0, timestamp=1000.0, evidence_refs=["EV_001"])
    tracker.observe(11.0, timestamp=1001.0, evidence_refs=["EV_002"])
    tracker.observe(12.0, timestamp=1002.0, evidence_refs=["EV_003"])
    
    history = tracker.history
    assert len(history) == 3
    assert history[0].step_index == 1
    assert history[0].evidence_refs == ["EV_001"]
    assert history[1].step_index == 2
    assert history[2].step_index == 3
    
    # Confirm dictionary serialization contains all required audit fields
    d = history[0].to_dict()
    required_keys = {
        "step_index", "timestamp", "observation_value", "previous_baseline",
        "new_baseline", "deviation", "standardized_deviation", "state_before",
        "state_after", "update_decision", "update_reason", "signal_classification", "evidence_refs"
    }
    assert required_keys.issubset(set(d.keys()))


def test_m9_anomaly_integration_interface():
    """Verify assess_m9_observation provides rich baseline context non-invasively."""
    manager = AdaptiveBaselineManager()
    
    # Feed 6 initial observations
    for i in range(6):
        manager.observe("ENT_TEST_M9", "transaction_volume", 100.0 + i)
        
    res = manager.assess_m9_observation("ENT_TEST_M9", "transaction_volume", 500.0)
    assert res["entity_id"] == "ENT_TEST_M9"
    assert res["feature_name"] == "transaction_volume"
    assert res["current_value"] == 500.0
    assert res["is_anomalous"] is True
    assert res["update_decision"] in (UpdateDecision.EXCLUDED_FROM_BASELINE.value, UpdateDecision.QUARANTINED.value)
    assert "limitations" in res


def test_m14_agentic_tool_contract_and_non_culpability():
    """Verify agentic tool query produces structured, verifiable responses without legal/culpability assertion."""
    manager = AdaptiveBaselineManager()
    for _ in range(5):
        manager.observe("ENT_M14_TEST", "login_rate", 5.0)
    manager.observe("ENT_M14_TEST", "login_rate", 50.0)  # Outlier
    
    # Q1: State
    res_state = manager.query_agentic_tool("What is the behavioral baseline state?", "ENT_M14_TEST", "login_rate")
    assert "ENT_M14_TEST" in res_state["answer"]
    assert res_state["audit_verifiable"] is True
    assert "does not establish culpability" in res_state["culpability_assessment"]
    
    # Q2: Exclusion
    res_ex = manager.query_agentic_tool("Why was this observation excluded?", "ENT_M14_TEST", "login_rate")
    assert "excluded" in res_ex["answer"].lower()
    
    # Q3: Allowed to update
    res_allowed = manager.query_agentic_tool("Was this observation allowed to update the baseline?", "ENT_M14_TEST", "login_rate")
    assert "BLOCKED" in res_allowed["answer"]


def test_copilot_m14_baseline_query_routing():
    """Verify InvestigationCopilot routes baseline questions through query_adaptive_baseline_agentic."""
    backend = InvestigationWorkspaceBackend(output_dir="output", canonical_dir="data/canonical", cases_dir="data/cases")
    # Feed baseline observations into backend
    for _ in range(6):
        backend.observe_adaptive_baseline("ENT_COPILOT_M8", "activity_frequency", 10.0)
        
    copilot = InvestigationCopilot(backend)
    ans = copilot.ask("What is the behavioral baseline state for ENT_COPILOT_M8?", entity_id="ENT_COPILOT_M8")
    
    assert ans["status"] == "GROUNDED"
    assert "ENT_COPILOT_M8" in ans["answer"]
    assert ans["dataset"] == "ADAPTIVE_BASELINE_M8"
    assert "culpability_assessment" in ans


def test_m13_workspace_cli_commands():
    """Verify M13 CLI commands: baseline <entity>, baseline status, baseline history."""
    backend = InvestigationWorkspaceBackend(output_dir="output", canonical_dir="data/canonical", cases_dir="data/cases")
    for _ in range(5):
        backend.observe_adaptive_baseline("ENT_CLI_M8", "signal_x", 42.0)
        
    out1 = handle_m13_command(backend, "baseline ENT_CLI_M8")
    assert "ENT_CLI_M8" in out1
    assert "signal_x" in out1
    assert "42.0" in out1
    
    out2 = handle_m13_command(backend, "baseline ENT_CLI_M8 status")
    assert "ENT_CLI_M8" in out2
    assert "Observation Count" in out2
    
    out3 = handle_m13_command(backend, "baseline ENT_CLI_M8 history")
    assert "ENT_CLI_M8" in out3
    assert "Step" in out3
    assert "Decision" in out3


def test_five_phase_controlled_research_fixture():
    """Verify full 5-phase fixture execution: cold start, stable, drift, isolated anomaly, repeated anomaly."""
    res = run_five_phase_research_fixture()
    
    assert res["cold_start_completed"] is True
    assert res["drift_adaptation_successful"] is True
    assert res["isolated_anomaly_excluded"] is True
    assert res["repeated_anomaly_quarantined"] is True
    assert res["contamination_prevented"] is True
    assert res["total_observations"] == 31
    assert len(res["phases"]) == 5
