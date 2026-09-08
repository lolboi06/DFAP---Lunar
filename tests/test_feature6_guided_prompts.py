# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: Feature 6 - Guided Next-Step Prompts Test Suite (Tests 1-13)

import pytest
import pandas as pd
from dfap.investigation.workspace import InvestigationWorkspaceBackend, InvestigationCase, CaseStatus
from dfap.investigation.event_sourcing import EventStore, EventType
from dfap.investigation.guided_prompts import (
    GuidedPromptService,
    PromptCandidate,
    PromptDecision,
)


@pytest.fixture
def prompt_setup(tmp_path):
    store_file = tmp_path / "prompt_events.jsonl"
    event_store = EventStore(str(store_file))
    backend = InvestigationWorkspaceBackend(
        output_dir=str(tmp_path / "output"),
        canonical_dir="data/canonical",
        cases_dir="data/cases"
    )
    service = GuidedPromptService(
        backend=backend,
        event_store=event_store,
        min_history=5,
        decision_threshold=0.40,
        min_exploration_prob=0.05
    )
    return service, backend, event_store


# TEST 1 — Deterministic candidate generation
def test_1_deterministic_candidate_generation(prompt_setup):
    service, backend, _ = prompt_setup
    # Add dummy finding to trigger VIEW_TIMELINE
    backend.findings_by_id["FND_TEST_01"] = {
        "finding_id": "FND_TEST_01",
        "score": 0.85,
        "status": "ACTIVE"
    }

    cands1 = service.generate_candidates()
    cands2 = service.generate_candidates()

    assert [c.prompt_type for c in cands1] == [c.prompt_type for c in cands2]
    assert [c.is_safety_critical for c in cands1] == [c.is_safety_critical for c in cands2]


# TEST 2 — POSSIBLE match generates RESOLVE_POSSIBLE_MATCH
def test_2_possible_match_generates_candidate(prompt_setup):
    service, backend, _ = prompt_setup
    # Inject POSSIBLE row into entities_df
    row = pd.DataFrame([{
        "canonical_entity_id": "ENT_TEST_POSSIBLE",
        "raw_identifier": "+1-555-9999",
        "identifier_type": "PHONE",
        "match_status": "POSSIBLE"
    }])
    backend.entities_df = pd.concat([backend.entities_df, row], ignore_index=True)

    cands = service.generate_candidates()
    types = [c.prompt_type for c in cands]
    assert service.PROMPT_RESOLVE_POSSIBLE_MATCH in types


# TEST 3 — Unreviewed PREDICTED edge generates REVIEW_PREDICTED_LINK
def test_3_predicted_edge_generates_candidate(prompt_setup):
    service, backend, _ = prompt_setup
    # Add PREDICTED edge to evidence_engine graph
    backend.evidence_engine.graph.edges.append({
        "parent_id": "ENT_A",
        "child_id": "ENT_B",
        "relation": "ASSOCIATED_WITH",
        "status": "PREDICTED"
    })

    cands = service.generate_candidates()
    types = [c.prompt_type for c in cands]
    assert service.PROMPT_REVIEW_PREDICTED_LINK in types


# TEST 4 — Unviewed anomaly generates VIEW_TIMELINE
def test_4_unviewed_anomaly_generates_candidate(prompt_setup):
    service, backend, _ = prompt_setup
    backend.findings_by_id["FND_01"] = {"finding_id": "FND_01", "score": 0.9}

    cands = service.generate_candidates()
    types = [c.prompt_type for c in cands]
    assert service.PROMPT_VIEW_TIMELINE in types


# TEST 5 — RED + unresolved POSSIBLE match is safety-critical
def test_5_red_plus_possible_is_safety_critical(prompt_setup):
    service, backend, _ = prompt_setup
    case_id = "CASE-RED-001"
    # Case with finding evaluated as RED / HIGH
    backend.findings_by_id["FND_RED_01"] = {
        "finding_id": "FND_RED_01",
        "anomaly_score": 0.95,
        "composite_score": 0.95,
        "status": "ACTIVE"
    }
    case = InvestigationCase(
        case_id=case_id,
        canonical_entity_id="ENT_RED_TARGET",
        finding_ids=["FND_RED_01"]
    )
    backend.cases[case_id] = case

    # Inject POSSIBLE entity
    row = pd.DataFrame([{
        "canonical_entity_id": "ENT_POSSIBLE_RED",
        "raw_identifier": "+1-555-RED",
        "identifier_type": "PHONE",
        "match_status": "POSSIBLE"
    }])
    backend.entities_df = pd.concat([backend.entities_df, row], ignore_index=True)

    cands = service.generate_candidates(case_id=case_id)
    resolve_cand = next(c for c in cands if c.prompt_type == service.PROMPT_RESOLVE_POSSIBLE_MATCH)
    assert resolve_cand.is_safety_critical is True


# TEST 6 — Safety-critical prompt is shown 100% of the time even after simulated suppression history
def test_6_safety_critical_shown_100_percent(prompt_setup):
    service, _, _ = prompt_setup
    officer_id = "OFFICER_STRICT"
    prompt_type = service.PROMPT_RESOLVE_POSSIBLE_MATCH

    # Simulate heavy rejection history: 100 IGNORED outcomes
    b_params = service._get_bandit_params(officer_id, prompt_type)
    b_params["beta"] = 100.0
    b_params["alpha"] = 1.0
    b_params["history_count"] = 100

    cand = PromptCandidate(
        prompt_type=prompt_type,
        is_safety_critical=True,
        context_features={"risk_tier": "RED"}
    )

    # Run 50 decisions — must be shown 100% of the time
    for _ in range(50):
        decs = service.decide_prompts(
            case_id="CASE-001",
            officer_id=officer_id,
            simulated_candidates=[cand]
        )
        assert len(decs) == 1
        assert decs[0].shown is True


# TEST 7 — Safety-critical prompt never invokes bandit selection
def test_7_safety_critical_never_invokes_bandit(prompt_setup):
    service, _, _ = prompt_setup
    cand = PromptCandidate(
        prompt_type=service.PROMPT_RESOLVE_POSSIBLE_MATCH,
        is_safety_critical=True,
        context_features={"risk_tier": "RED"}
    )
    decs = service.decide_prompts(
        case_id="CASE-001",
        officer_id="OFFICER_NEW",
        simulated_candidates=[cand]
    )
    assert decs[0].context_snapshot.get("bandit_evaluated") is False
    assert decs[0].context_snapshot.get("bypass_reason") == "SAFETY_CRITICAL_RED_TIER_BYPASS"


# TEST 8 — New officer sees prompts without suppression (Cold start)
def test_8_cold_start_unsuppressed(prompt_setup):
    service, _, _ = prompt_setup
    officer_id = "OFFICER_FRESH"
    cand = PromptCandidate(
        prompt_type=service.PROMPT_VIEW_TIMELINE,
        is_safety_critical=False,
        context_features={}
    )

    # First 4 decisions (< min_history=5) must all be shown
    for _ in range(4):
        decs = service.decide_prompts(
            case_id="CASE-001",
            officer_id=officer_id,
            simulated_candidates=[cand]
        )
        assert decs[0].shown is True
        assert decs[0].context_snapshot["cold_start"] is True


# TEST 9 — FOLLOWED updates Beta state
def test_9_followed_updates_beta(prompt_setup):
    service, _, _ = prompt_setup
    cand = PromptCandidate(
        prompt_type=service.PROMPT_VIEW_TIMELINE,
        is_safety_critical=False,
        context_features={}
    )
    decs = service.decide_prompts(
        case_id="CASE-001",
        officer_id="OFFICER_A",
        simulated_candidates=[cand]
    )
    d_id = decs[0].decision_id

    b_before = service._get_bandit_params("OFFICER_A", service.PROMPT_VIEW_TIMELINE)["alpha"]
    service.record_outcome(d_id, "FOLLOWED")
    b_after = service._get_bandit_params("OFFICER_A", service.PROMPT_VIEW_TIMELINE)["alpha"]

    assert b_after == b_before + 1.0


# TEST 10 — IGNORED updates Beta state
def test_10_ignored_updates_beta(prompt_setup):
    service, _, _ = prompt_setup
    cand = PromptCandidate(
        prompt_type=service.PROMPT_VIEW_TIMELINE,
        is_safety_critical=False,
        context_features={}
    )
    decs = service.decide_prompts(
        case_id="CASE-001",
        officer_id="OFFICER_B",
        simulated_candidates=[cand]
    )
    d_id = decs[0].decision_id

    beta_before = service._get_bandit_params("OFFICER_B", service.PROMPT_VIEW_TIMELINE)["beta"]
    service.record_outcome(d_id, "IGNORED")
    beta_after = service._get_bandit_params("OFFICER_B", service.PROMPT_VIEW_TIMELINE)["beta"]

    assert beta_after == beta_before + 1.0


# TEST 11 — Non-critical prompt suppression changes after simulated history
def test_11_non_critical_suppression_changes(prompt_setup):
    service, _, _ = prompt_setup
    officer_id = "OFFICER_C"
    prompt_type = service.PROMPT_VIEW_TIMELINE
    cand = PromptCandidate(prompt_type=prompt_type, is_safety_critical=False, context_features={})

    # High negative feedback
    b_params = service._get_bandit_params(officer_id, prompt_type)
    b_params["beta"] = 50.0
    b_params["alpha"] = 1.0
    b_params["history_count"] = 50

    # With high beta and decision threshold 0.40, expectation is alpha/(alpha+beta) = 1/51 ~ 0.02
    # Probability should predominantly result in shown = False
    results = [
        service.decide_prompts("CASE-01", officer_id, [cand])[0].shown
        for _ in range(20)
    ]
    assert False in results


# TEST 12 — Non-critical prompt retains non-zero exploration
def test_12_non_zero_exploration(prompt_setup):
    service, _, _ = prompt_setup
    # min_exploration_prob is 0.05
    assert service.min_exploration_prob > 0.0
    b_params = service._get_bandit_params("OFFICER_D", service.PROMPT_VIEW_TIMELINE)
    b_params["beta"] = 1000.0  # extreme negative history
    b_params["alpha"] = 1.0
    b_params["history_count"] = 1000

    cand = PromptCandidate(prompt_type=service.PROMPT_VIEW_TIMELINE, is_safety_critical=False, context_features={})
    dec = service.decide_prompts("CASE-01", "OFFICER_D", [cand])[0]

    bounded_prob = dec.context_snapshot.get("bounded_prob", 0.0)
    assert bounded_prob >= service.min_exploration_prob


# TEST 13 — Prompt decisions are EventStore-auditable
def test_13_eventstore_auditable(prompt_setup):
    service, _, event_store = prompt_setup
    cand = PromptCandidate(
        prompt_type=service.PROMPT_VIEW_TIMELINE,
        is_safety_critical=False,
        context_features={"case_id": "CASE-AUDIT-001"}
    )
    decs = service.decide_prompts(
        case_id="CASE-AUDIT-001",
        officer_id="OFFICER_AUDIT",
        simulated_candidates=[cand]
    )
    assert len(decs) == 1
    d_id = decs[0].decision_id

    # Record outcome
    service.record_outcome(d_id, "FOLLOWED")

    events = event_store.get_events()
    shown_events = [e for e in events if e.event_type == EventType.PROMPT_SHOWN]
    outcome_events = [e for e in events if e.event_type == EventType.PROMPT_OUTCOME]

    assert len(shown_events) >= 1
    assert shown_events[-1].metadata["decision_id"] == d_id

    assert len(outcome_events) >= 1
    assert outcome_events[-1].metadata["decision_id"] == d_id
    assert outcome_events[-1].metadata["outcome"] == "FOLLOWED"


# ── CROSS-PROCESS PERSISTENCE REGRESSION TESTS (REQUIREMENTS A - L) ─────────

def test_14_cross_process_persistence_and_bandit_rehydration(prompt_setup):
    """
    Simulates separate CLI processes / process boundaries:
    A. Create PromptDecision
    B. Persist it (PROMPT_SHOWN event)
    C. Construct fresh PromptService & EventStore instance
    D. Record outcome using original decision_id
    E. Verify PROMPT_OUTCOME is persisted
    F. Retrieve history from a third fresh instance
    G. Verify bandit history includes outcome (alpha=2.0, history=1)
    K. Original PROMPT_SHOWN event remains unchanged
    """
    service1, backend, event_store1 = prompt_setup
    case_id = "CASE-PROC-001"
    officer_id = "OFFICER_PROC_01"
    prompt_type = GuidedPromptService.PROMPT_VIEW_TIMELINE

    cand = PromptCandidate(
        prompt_type=prompt_type,
        is_safety_critical=False,
        context_features={"case_id": case_id, "test": "cross_proc"}
    )

    # A & B: Process 1 creates decision and persists it
    decs1 = service1.decide_prompts(case_id=case_id, officer_id=officer_id, simulated_candidates=[cand])
    assert len(decs1) == 1
    d_id = decs1[0].decision_id
    assert decs1[0].shown is True

    # Record snapshot of original PROMPT_SHOWN event (for K)
    disk_events_p1 = event_store1.get_events()
    shown_p1 = [e for e in disk_events_p1 if e.event_type == EventType.PROMPT_SHOWN and e.metadata.get("decision_id") == d_id]
    assert len(shown_p1) == 1
    orig_shown_dict = shown_p1[0].to_dict()

    # C: Process 2 boundary — fresh EventStore and fresh GuidedPromptService
    store_file = event_store1.file_path
    event_store2 = EventStore(store_file)
    service2 = GuidedPromptService(backend=backend, event_store=event_store2)

    # Verify decision_id was rehydrated into service2
    assert d_id in service2.decisions
    rehydrated_dec = service2.decisions[d_id]
    assert rehydrated_dec.prompt_type == prompt_type
    assert rehydrated_dec.officer_id == officer_id
    assert rehydrated_dec.shown is True
    assert rehydrated_dec.outcome is None

    # D & I: Process 2 records outcome FOLLOWED using original decision_id
    res_dec2 = service2.record_outcome(decision_id=d_id, outcome="FOLLOWED")
    assert res_dec2.decision_id == d_id
    assert res_dec2.outcome == "FOLLOWED"

    # E: Verify PROMPT_OUTCOME is persisted on disk
    disk_events_p2 = event_store2.get_events()
    outcome_evs = [e for e in disk_events_p2 if e.event_type == EventType.PROMPT_OUTCOME and e.metadata.get("decision_id") == d_id]
    assert len(outcome_evs) == 1
    assert outcome_evs[0].metadata["outcome"] == "FOLLOWED"

    # F & G: Process 3 boundary — retrieve history & bandit state from fresh instance
    event_store3 = EventStore(store_file)
    service3 = GuidedPromptService(backend=backend, event_store=event_store3)

    case_history = event_store3.get_events_for_case(case_id)
    assert len(case_history) == 2
    assert case_history[0].event_type == EventType.PROMPT_SHOWN
    assert case_history[1].event_type == EventType.PROMPT_OUTCOME

    # G: Verify bandit history includes outcome (alpha=2.0, beta=1.0, history_count=1)
    b_params3 = service3._get_bandit_params(officer_id, prompt_type)
    assert b_params3["alpha"] == 2.0
    assert b_params3["beta"] == 1.0
    assert b_params3["history_count"] == 1

    # K: Verify original PROMPT_SHOWN event remains strictly unchanged
    disk_events_p3 = event_store3.get_events()
    shown_p3 = [e for e in disk_events_p3 if e.event_type == EventType.PROMPT_SHOWN and e.metadata.get("decision_id") == d_id]
    assert len(shown_p3) == 1
    assert shown_p3[0].to_dict() == orig_shown_dict


def test_15_ignored_outcome_cross_process_rehydration(prompt_setup):
    """
    J. IGNORED outcome is persisted and beta parameter is correctly updated across instances.
    """
    service1, backend, event_store1 = prompt_setup
    case_id = "CASE-PROC-002"
    officer_id = "OFFICER_PROC_02"
    prompt_type = GuidedPromptService.PROMPT_VIEW_TIMELINE

    cand = PromptCandidate(
        prompt_type=prompt_type,
        is_safety_critical=False,
        context_features={"case_id": case_id}
    )

    decs = service1.decide_prompts(case_id=case_id, officer_id=officer_id, simulated_candidates=[cand])
    d_id = decs[0].decision_id

    # Fresh instance records IGNORED
    service2 = GuidedPromptService(backend=backend, event_store=EventStore(event_store1.file_path))
    service2.record_outcome(decision_id=d_id, outcome="IGNORED")

    # Fresh instance verifies beta increment
    service3 = GuidedPromptService(backend=backend, event_store=EventStore(event_store1.file_path))
    b_params = service3._get_bandit_params(officer_id, prompt_type)
    assert b_params["alpha"] == 1.0
    assert b_params["beta"] == 2.0
    assert b_params["history_count"] == 1


def test_16_invalid_decision_id_raises_controlled_error(prompt_setup):
    """
    H. Invalid decision_id still raises a controlled KeyError.
    """
    service, _, _ = prompt_setup
    with pytest.raises(KeyError, match="PromptDecision ID 'non-existent-uuid-9999' not found"):
        service.record_outcome("non-existent-uuid-9999", "FOLLOWED")

    # Invalid outcome string raises ValueError
    cand = PromptCandidate(
        prompt_type=service.PROMPT_VIEW_TIMELINE,
        is_safety_critical=False,
        context_features={}
    )
    decs = service.decide_prompts("CASE-001", "OFFICER_X", [cand])
    with pytest.raises(ValueError, match="Invalid outcome 'MAYBE'"):
        service.record_outcome(decs[0].decision_id, "MAYBE")


def test_17_cross_process_safety_critical_invariant(prompt_setup):
    """
    L. Safety-critical prompt behavior remains unchanged across process boundaries:
       100% shown, bandit bypassed, survives reload.
    """
    service1, backend, event_store1 = prompt_setup
    case_id = "CASE-PROC-SC-001"
    officer_id = "OFFICER_PROC_SC"
    prompt_type = service1.PROMPT_RESOLVE_POSSIBLE_MATCH

    cand = PromptCandidate(
        prompt_type=prompt_type,
        is_safety_critical=True,
        context_features={"risk_tier": "RED"}
    )

    # Process 1 decides
    decs1 = service1.decide_prompts(case_id=case_id, officer_id=officer_id, simulated_candidates=[cand])
    d_id = decs1[0].decision_id
    assert decs1[0].shown is True
    assert decs1[0].context_snapshot["bypass_reason"] == "SAFETY_CRITICAL_RED_TIER_BYPASS"

    # Process 2 records outcome
    service2 = GuidedPromptService(backend=backend, event_store=EventStore(event_store1.file_path))
    service2.record_outcome(d_id, "FOLLOWED")

    # Process 3 verifies decision outcome and future safety-critical prompt behavior
    service3 = GuidedPromptService(backend=backend, event_store=EventStore(event_store1.file_path))
    assert service3.decisions[d_id].outcome == "FOLLOWED"

    # Future decision on safety-critical prompt MUST still be shown 100%
    decs3 = service3.decide_prompts(case_id=case_id, officer_id=officer_id, simulated_candidates=[cand])
    assert decs3[0].shown is True
    assert decs3[0].context_snapshot["bypass_reason"] == "SAFETY_CRITICAL_RED_TIER_BYPASS"
