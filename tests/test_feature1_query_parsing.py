# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: Feature 1 - Grammar-Constrained Query Parsing Test Suite (Tests A-N)

import os
from datetime import datetime, timezone
import pytest
from dfap.investigation.workspace import InvestigationWorkspaceBackend
from dfap.investigation.event_sourcing import EventStore, EventType
from dfap.investigation.query_parser import (
    QueryParserService,
    QueryIntent,
    QueryType,
    TimeRange,
    UNSUPPORTED_MESSAGE,
)
from dfap.investigation.query_fixture import (
    register_query_feature_fixture,
    FIXTURE_CASE_ID,
    FIXTURE_CONTEXT_ENTITY,
    ENT_RAHUL_A,
    ENT_RAHUL_B,
    ENT_RAHUL_C,
    ENT_AMIT,
    ENT_POSSIBLE_ONLY,
    RAW_POSSIBLE_ID,
)


@pytest.fixture
def test_setup(tmp_path):
    backend = InvestigationWorkspaceBackend(
        output_dir=str(tmp_path / "output"),
        canonical_dir="data/canonical",
        cases_dir="data/cases",
    )
    case_id, edges = register_query_feature_fixture(backend)
    event_store = EventStore(str(tmp_path / "query_events.jsonl"))
    service = QueryParserService(
        backend=backend,
        event_store=event_store,
        custom_graph_edges=edges,
        reference_time=datetime(2026, 9, 8, 12, 0, 0, tzinfo=timezone.utc),
    )
    return backend, service, case_id, event_store


# TEST A — ENTITY LOOKUP
def test_a_entity_lookup(test_setup):
    _, service, case_id, _ = test_setup
    intent = service.parse_intent("Find Rahul Sharma")
    assert intent.query_type == QueryType.ENTITY_LOOKUP
    assert intent.entity_ref == "Rahul Sharma"
    assert intent.entity_ref_2 is None


# TEST B — TIMELINE
def test_b_timeline(test_setup):
    _, service, case_id, _ = test_setup
    intent = service.parse_intent("Show Rahul Sharma's timeline for last month")
    assert intent.query_type == QueryType.TIMELINE
    assert intent.entity_ref is not None
    assert "Rahul Sharma" in intent.entity_ref
    assert intent.time_filter is not None
    assert intent.time_filter.raw_text == "last month"
    assert intent.time_filter.start_date == "2026-08-01T00:00:00Z"
    assert intent.time_filter.end_date == "2026-08-31T23:59:59Z"


# TEST C — PATH
def test_c_path_between(test_setup):
    _, service, case_id, _ = test_setup
    intent = service.parse_intent("Show the path between Rahul Sharma and Amit Kumar")
    assert intent.query_type == QueryType.PATH_BETWEEN
    assert intent.entity_ref == "Rahul Sharma"
    assert intent.entity_ref_2 == "Amit Kumar"


# TEST D — ANOMALY LIST
def test_d_anomaly_list(test_setup):
    _, service, case_id, _ = test_setup
    intent = service.parse_intent("Show anomalous activity")
    assert intent.query_type == QueryType.ANOMALY_LIST


# TEST E — MULTIPLE SAME-NAME CONFIRMED ENTITIES
def test_e_multiple_same_name_confirmed_entities(test_setup):
    _, service, case_id, _ = test_setup
    # Resolving "Rahul Sharma" matches ENT_RAHUL_A, ENT_RAHUL_B, ENT_RAHUL_C
    res = service.execute_query("Find Rahul Sharma", case_context_id=case_id)
    assert res.disambiguation_required is True
    assert res.execution_status == "BLOCKED_DISAMBIGUATION"
    assert len(res.disambiguation_candidates) == 3
    # No query executed automatically
    assert res.executed_backend_operation is None


# TEST F — GRAPH DISTANCE RANKING
def test_f_graph_distance_ranking(test_setup):
    _, service, case_id, _ = test_setup
    res = service.execute_query("Find Rahul Sharma", case_context_id=case_id)
    assert res.disambiguation_required is True
    cands = res.disambiguation_candidates

    # Known topology:
    # A = 1 hop, B = 2 hops, C = 4 hops
    assert cands[0].canonical_entity_id == ENT_RAHUL_A
    assert cands[0].graph_distance_to_context == 1

    assert cands[1].canonical_entity_id == ENT_RAHUL_B
    assert cands[1].graph_distance_to_context == 2

    assert cands[2].canonical_entity_id == ENT_RAHUL_C
    assert cands[2].graph_distance_to_context == 4


# TEST G — NO CASE CONTEXT
def test_g_no_case_context(test_setup):
    _, service, _, _ = test_setup
    # Case context omitted / None
    res = service.execute_query("Find Rahul Sharma", case_context_id=None)
    assert res.disambiguation_required is True
    assert "no active case context" in res.ranking_reason
    # Fallback to recency:
    # A: 2026-09-01, B: 2026-08-15, C: 2026-07-01
    assert res.disambiguation_candidates[0].canonical_entity_id == ENT_RAHUL_A
    assert res.disambiguation_candidates[1].canonical_entity_id == ENT_RAHUL_B
    assert res.disambiguation_candidates[2].canonical_entity_id == ENT_RAHUL_C


# TEST H — POSSIBLE EXCLUSION
def test_h_possible_exclusion(test_setup):
    _, service, case_id, _ = test_setup
    # RAW_POSSIBLE_ID maps ONLY to ENT_POSSIBLE_ONLY (status: POSSIBLE)
    res = service.execute_query(f"Find {RAW_POSSIBLE_ID}", case_context_id=case_id)
    assert res.execution_status == "NOT_FOUND"
    assert res.executed_backend_operation is None
    assert "POSSIBLE" in res.message


# TEST I — ZERO MATCH
def test_i_zero_match(test_setup):
    _, service, case_id, _ = test_setup
    res = service.execute_query("Find NONEXISTENT_PERSON_XYZ_9999", case_context_id=case_id)
    assert res.execution_status == "NOT_FOUND"
    assert "No confirmed entity found" in res.message
    assert "stronger identifier" in res.message


# TEST J — OUT OF SCOPE
def test_j_out_of_scope(test_setup):
    _, service, case_id, _ = test_setup
    res = service.execute_query("Delete this record immediately", case_context_id=case_id)
    assert res.execution_status == "UNSUPPORTED"
    assert res.executed_backend_operation is None
    assert res.message == UNSUPPORTED_MESSAGE


# TEST K — SERVER-CONTROLLED CASE CONTEXT
def test_k_server_controlled_case_context(test_setup):
    _, service, case_id, _ = test_setup
    session = service.get_or_create_session(case_context_id=case_id)
    # Even if model or caller injects case_context_id into raw json, parse_intent strips it
    intent = service.parse_intent("Find Amit Kumar", session=session)
    assert intent.case_context_id == case_id


# TEST L — MULTI-TURN CONTEXT RETENTION
def test_l_multi_turn_context(test_setup):
    _, service, case_id, _ = test_setup
    session = service.get_or_create_session(case_context_id=case_id)

    # Turn 1: Explicit entity query for Amit Kumar
    res1 = service.execute_query("Show timeline for Amit Kumar", session_id=session.session_id)
    assert res1.execution_status == "SUCCESS"
    assert session.last_resolved_entity_id == ENT_AMIT

    # Turn 2: Follow-up query without entity mention
    res2 = service.execute_query("Now just last month", session_id=session.session_id)
    assert res2.intent.query_type == QueryType.TIMELINE
    assert res2.intent.entity_ref == ENT_AMIT
    assert res2.case_context_id == case_id
    assert res2.execution_status == "SUCCESS"
    assert res2.intent.time_filter is not None
    assert res2.intent.time_filter.start_date == "2026-08-01T00:00:00Z"
    assert res2.intent.time_filter.end_date == "2026-08-31T23:59:59Z"
    assert res2.intent.time_filter.start_epoch is not None
    assert res2.intent.time_filter.end_epoch is not None
    assert res2.executed_backend_operation == "backend.get_timeline"


# TEST M — EVENT LOG
def test_m_event_log(test_setup):
    _, service, case_id, event_store = test_setup
    session = service.get_or_create_session(case_context_id=case_id)

    # 1. Query issued event
    res1 = service.execute_query("Find Amit Kumar", session_id=session.session_id)
    assert res1.execution_status == "SUCCESS"

    events = event_store.get_events()
    issued_evs = [e for e in events if e.event_type == EventType.QUERY_ISSUED]
    assert len(issued_evs) >= 1
    assert issued_evs[-1].metadata["query_type"] == "ENTITY_LOOKUP"

    # 2. Disambiguation resolved event
    res_amb = service.execute_query("Find Rahul Sharma", session_id=session.session_id)
    assert res_amb.disambiguation_required is True

    # Officer explicitly selects CAND_1 (ENT_RAHUL_A)
    res_res = service.resolve_disambiguation(
        session_id=session.session_id,
        candidate_id="CAND_1",
        officer_id="OFFICER_JONES"
    )
    assert res_res.execution_status == "SUCCESS"

    events_after = event_store.get_events()
    disambig_evs = [e for e in events_after if e.event_type == EventType.DISAMBIGUATION_RESOLVED]
    assert len(disambig_evs) >= 1
    assert disambig_evs[-1].officer_id == "OFFICER_JONES"
    assert disambig_evs[-1].metadata["selected_candidate_id"] == "CAND_1"
    assert disambig_evs[-1].metadata["canonical_entity_id"] == ENT_RAHUL_A


# TEST N — PATH CONFIRMATION (Endpoints validation)
def test_n_path_confirmation(test_setup):
    _, service, case_id, _ = test_setup
    # Endpoint 1 is confirmed Amit, Endpoint 2 is unconfirmed POSSIBLE only
    res = service.execute_query(
        f"Show path between Amit Kumar and {RAW_POSSIBLE_ID}",
        case_context_id=case_id
    )
    assert res.execution_status == "NOT_FOUND"
    assert res.executed_backend_operation is None
    assert "POSSIBLE" in res.message


# FOCUSED REGRESSION TESTS: RELATIVE TIME FILTER RESOLUTION

def test_temporal_resolution_last_month(test_setup):
    _, service, _, _ = test_setup
    # Standard check with reference_dt = 2026-09-08
    tr = service.resolve_time_bounds("last month")
    assert tr is not None
    assert tr.start_date == "2026-08-01T00:00:00Z"
    assert tr.end_date == "2026-08-31T23:59:59Z"
    assert tr.start_epoch == datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc).timestamp()
    assert tr.end_epoch == datetime(2026, 8, 31, 23, 59, 59, tzinfo=timezone.utc).timestamp()

    # Year-boundary transition check: January 15, 2026 -> December 2025
    jan_ref = datetime(2026, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
    service.set_reference_time(jan_ref)
    tr_jan = service.resolve_time_bounds("last month")
    assert tr_jan is not None
    assert tr_jan.start_date == "2025-12-01T00:00:00Z"
    assert tr_jan.end_date == "2025-12-31T23:59:59Z"


def test_temporal_resolution_this_month(test_setup):
    _, service, _, _ = test_setup
    tr = service.resolve_time_bounds("this month")
    assert tr is not None
    assert tr.start_date == "2026-09-01T00:00:00Z"
    assert tr.end_date == "2026-09-30T23:59:59Z"


def test_temporal_resolution_yesterday_today_weeks(test_setup):
    _, service, _, _ = test_setup
    # Reference: 2026-09-08 (Tuesday)
    # Yesterday: 2026-09-07
    tr_yest = service.resolve_time_bounds("yesterday")
    assert tr_yest.start_date == "2026-09-07T00:00:00Z"
    assert tr_yest.end_date == "2026-09-07T23:59:59Z"

    # Today: 2026-09-08
    tr_today = service.resolve_time_bounds("today")
    assert tr_today.start_date == "2026-09-08T00:00:00Z"
    assert tr_today.end_date == "2026-09-08T23:59:59Z"

    # Last week: 2026-08-31 to 2026-09-06
    tr_lw = service.resolve_time_bounds("last week")
    assert tr_lw.start_date == "2026-08-31T00:00:00Z"
    assert tr_lw.end_date == "2026-09-06T23:59:59Z"

    # This week: 2026-09-07 to 2026-09-13
    tr_tw = service.resolve_time_bounds("this week")
    assert tr_tw.start_date == "2026-09-07T00:00:00Z"
    assert tr_tw.end_date == "2026-09-13T23:59:59Z"


def test_unresolved_temporal_expression_needs_clarification(test_setup):
    _, service, case_id, event_store = test_setup
    session = service.get_or_create_session(case_context_id=case_id)

    # 1. Direct query with unresolved temporal phrase "recently"
    res1 = service.execute_query("Show timeline for Amit Kumar recently", session_id=session.session_id)
    assert res1.execution_status == "NEEDS_CLARIFICATION"
    assert res1.executed_backend_operation is None
    assert res1.data is None
    assert "cannot be deterministically resolved" in res1.message

    # Verify event logged
    events = event_store.get_events()
    assert any(e.event_type == EventType.QUERY_ISSUED and e.metadata.get("status") == "NEEDS_CLARIFICATION" for e in events)

    # 2. Multi-turn follow-up with "a few days ago"
    res_base = service.execute_query("Show timeline for Amit Kumar", session_id=session.session_id)
    assert res_base.execution_status == "SUCCESS"
    res2 = service.execute_query("Now a few days ago", session_id=session.session_id)
    assert res2.execution_status == "NEEDS_CLARIFICATION"
    assert res2.executed_backend_operation is None
    assert res2.data is None


def test_resolved_temporal_bounds_passed_to_m13(test_setup):
    backend, service, case_id, _ = test_setup
    session = service.get_or_create_session(case_context_id=case_id)

    # Amit has an event on 2026-09-05T14:00:00Z (September 2026)
    # Query for "last month" (August 2026) -> executed backend op should be get_timeline, but 0 events returned
    res_aug = service.execute_query("Show timeline for Amit Kumar for last month", session_id=session.session_id)
    assert res_aug.execution_status == "SUCCESS"
    assert res_aug.executed_backend_operation == "backend.get_timeline"
    assert len(res_aug.data) == 0

    # Query for "this month" (September 2026) -> 1 event returned
    res_sep = service.execute_query("Show timeline for Amit Kumar for this month", session_id=session.session_id)
    assert res_sep.execution_status == "SUCCESS"
    assert res_sep.executed_backend_operation == "backend.get_timeline"
    assert len(res_sep.data) == 1
    assert res_sep.data[0]["event_id"] == "EVT_AMIT_01"


def test_existing_disambiguation_behavior_preserved(test_setup):
    _, service, case_id, _ = test_setup
    # Disambiguation must still work identically: multiple candidates block execution
    res = service.execute_query("Show timeline for Rahul Sharma", case_context_id=case_id)
    assert res.disambiguation_required is True
    assert res.execution_status == "BLOCKED_DISAMBIGUATION"
    assert res.executed_backend_operation is None
    assert len(res.disambiguation_candidates) == 3
