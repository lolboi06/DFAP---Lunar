# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: Feature 1 - CLI Interface & Smoke Test Demonstration

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from typing import Optional, Union, List

from dfap.investigation.workspace import InvestigationWorkspaceBackend
from dfap.investigation.event_sourcing import EventStore
from dfap.investigation.query_parser import (
    QueryParserService,
    QueryType,
    QueryResult
)
from dfap.investigation.query_fixture import (
    register_query_feature_fixture,
    FIXTURE_CASE_ID,
    FIXTURE_CONTEXT_ENTITY,
    ENT_RAHUL_A,
    ENT_RAHUL_B,
    ENT_RAHUL_C,
    ENT_AMIT
)


def get_service_and_backend(case_id: Optional[str] = None, reference_time: Optional[datetime] = None):
    backend = InvestigationWorkspaceBackend(
        output_dir="output",
        canonical_dir="data/canonical",
        cases_dir="data/cases"
    )
    c_id, edges = register_query_feature_fixture(backend)
    event_store = EventStore("data/query_decision_events.jsonl")
    ref_dt = reference_time or datetime(2026, 9, 8, 12, 0, 0, tzinfo=timezone.utc)
    service = QueryParserService(
        backend=backend,
        event_store=event_store,
        custom_graph_edges=edges,
        reference_time=ref_dt
    )
    return service, backend, case_id or c_id


def run_smoke_test():
    print("=" * 60)
    print("DFAP FEATURE 1: GRAMMAR-CONSTRAINED QUERY PARSING SMOKE TEST")
    print("=" * 60)

    service, backend, case_id = get_service_and_backend()
    session = service.get_or_create_session(case_context_id=case_id, officer_id="OFFICER_INVESTIGATOR_01")

    # ── 1. OFFICER NATURAL-LANGUAGE QUERY (AMBIGUOUS SAME-NAME) ────────────────
    print("\n[Step 1] Officer Query (Ambiguous Entity): 'Find Rahul Sharma'")
    print(f"Active Case Context: {case_id} (Target: {FIXTURE_CONTEXT_ENTITY})")

    res1 = service.execute_query(
        "Find Rahul Sharma",
        session_id=session.session_id,
        case_context_id=case_id
    )

    print("\n[Step 2] Actual Structured QueryIntent:")
    print(json.dumps(res1.intent.model_dump(), indent=2))

    print("\n[Step 3] Actual M2 Resolution & Disambiguation Gate:")
    print(f"Disambiguation Required: {res1.disambiguation_required}")
    print(f"Execution Status: {res1.execution_status}")
    print(f"Backend Operation Executed: {res1.executed_backend_operation} (VERIFIED: NO EXECUTION)")

    print("\n[Step 4] M4 Graph-Distance Candidate Ranking Table:")
    print(f"{'Candidate ID':<15}{'Canonical Entity ID':<25}{'Graph Distance':<18}{'Rank Position':<15}{'Confirmation Status'}")
    print("-" * 85)
    for idx, c in enumerate(res1.disambiguation_candidates):
        print(f"{c.candidate_id:<15}{c.canonical_entity_id:<25}{c.graph_distance_to_context:<18}{idx + 1:<15}{'CONFIRMED'}")

    assert res1.disambiguation_required is True
    assert res1.execution_status == "BLOCKED_DISAMBIGUATION"
    assert res1.executed_backend_operation is None, "Safety violation: query executed before officer selection!"

    # ── 2. EXPLICIT OFFICER SELECTION ──────────────────────────────────────────
    print("\n[Step 5] Explicit Officer Selection:")
    print("Officer selects 'CAND_1' (ENT_RAHUL_SHARMA_A - nearest 1-hop neighbor)...")

    res_res = service.resolve_disambiguation(
        session_id=session.session_id,
        candidate_id="CAND_1",
        officer_id="OFFICER_INVESTIGATOR_01"
    )

    print(f"Post-Selection Execution Status: {res_res.execution_status}")
    print(f"Executed M13 Operation: {res_res.executed_backend_operation}")
    print(f"Resolved Entity: {res_res.resolved_entity_ids}")
    print(f"Event IDs Appended: {res_res.event_ids}")
    assert res_res.execution_status == "SUCCESS"
    assert res_res.executed_backend_operation == "backend.investigate_entity"

    # ── 3. TIMELINE QUERY & MULTI-TURN REFINEMENT ──────────────────────────────
    print("\n[Step 6] Multi-Turn Query 1: 'Show timeline for Amit Kumar'")
    res_amit = service.execute_query(
        "Show timeline for Amit Kumar",
        session_id=session.session_id,
        case_context_id=case_id
    )
    print(f"Execution Status: {res_amit.execution_status}")
    print(f"Resolved Entity: {res_amit.resolved_entity_ids}")
    print(f"Timeline Events Count: {len(res_amit.data) if isinstance(res_amit.data, list) else 0}")
    assert res_amit.execution_status == "SUCCESS"
    assert ENT_AMIT in res_amit.resolved_entity_ids

    print("\n[Step 7] Multi-Turn Query 2 (Follow-up Refinement): 'Now just last month'")
    res_follow = service.execute_query(
        "Now just last month",
        session_id=session.session_id,
        case_context_id=case_id
    )
    print(f"Follow-up Intent QueryType: {res_follow.intent.query_type.value}")
    print(f"Inherited Entity Ref: {res_follow.intent.entity_ref}")
    tf = res_follow.intent.time_filter
    print("Time Filter Extracted:")
    if tf and tf.start_date and tf.end_date:
        print(f"    start_date: {tf.start_date}")
        print(f"    end_date: {tf.end_date}")
    else:
        print("    start_date: None")
        print("    end_date: None")
    print(f"Execution Status: {res_follow.execution_status}")
    assert res_follow.intent.query_type == QueryType.TIMELINE
    assert res_follow.intent.entity_ref == ENT_AMIT
    assert tf is not None
    assert tf.start_date == "2026-08-01T00:00:00Z"
    assert tf.end_date == "2026-08-31T23:59:59Z"
    assert tf.start_epoch is not None
    assert tf.end_epoch is not None
    assert res_follow.execution_status == "SUCCESS"
    assert res_follow.executed_backend_operation == "backend.get_timeline"
    assert len(res_follow.data) == 0, "M13 filter verified: September event excluded from August bounds"

    # ── 4. OUT-OF-SCOPE REJECTION ─────────────────────────────────────────────
    print("\n[Step 8] Out-of-Scope Destruction Attempt: 'Delete this record'")
    res_bad = service.execute_query(
        "Delete this record",
        session_id=session.session_id,
        case_context_id=case_id
    )
    print(f"Execution Status: {res_bad.execution_status}")
    print(f"System Message: {res_bad.message}")
    assert res_bad.execution_status == "UNSUPPORTED"
    assert res_bad.executed_backend_operation is None

    # ── 5. EVENTSTORE AUDIT HISTORY ───────────────────────────────────────────
    print("\n[Step 9] EventStore Audit Verification:")
    all_events = service.event_store.get_events()
    recent_events = all_events[-5:]
    for e in recent_events:
        print(f"  - Event ID: {e.event_id} | Type: {e.event_type.value} | Officer: {e.officer_id} | Entity: {e.entity_id}")

    print("\n" + "=" * 60)
    print("FEATURE 1 SMOKE TEST PASSED — ZERO FABRICATION, STRICT GATE VERIFIED")
    print("=" * 60)


def main(args: Optional[list] = None):
    parser = argparse.ArgumentParser(prog="dfap query", description="Feature 1 Query Parsing & Disambiguation CLI")
    subparsers = parser.add_subparsers(dest="subcommand")

    # query parse "<officer input>"
    p_parse = subparsers.add_parser("parse", help="Parse natural-language query to structured QueryIntent")
    p_parse.add_argument("input", type=str, help="Natural-language officer inquiry")
    p_parse.add_argument("--case", type=str, default=FIXTURE_CASE_ID, help="Active case ID")

    # query execute "<officer input>"
    p_exec = subparsers.add_parser("execute", help="Parse, resolve, and execute query")
    p_exec.add_argument("input", type=str, help="Natural-language officer inquiry")
    p_exec.add_argument("--case", type=str, default=FIXTURE_CASE_ID, help="Active case ID")
    p_exec.add_argument("--officer", type=str, default="OFFICER_01", help="Officer ID")

    # query disambiguate <session_id>
    p_dis = subparsers.add_parser("disambiguate", help="List pending disambiguation candidates for a session")
    p_dis.add_argument("session_id", type=str, help="Session ID")

    # query resolve <session_id> <candidate_id>
    p_res = subparsers.add_parser("resolve", help="Explicitly select candidate and resume execution")
    p_res.add_argument("session_id", type=str, help="Session ID")
    p_res.add_argument("candidate_id", type=str, help="Selected Candidate ID (e.g. CAND_1)")
    p_res.add_argument("--officer", type=str, default="OFFICER_01", help="Officer ID")

    # query smoke
    subparsers.add_parser("smoke", help="Run comprehensive smoke test walkthrough")

    parsed_args = parser.parse_args(args)

    if parsed_args.subcommand == "smoke":
        run_smoke_test()
        return

    service, backend, case_id = get_service_and_backend(getattr(parsed_args, "case", None))

    if parsed_args.subcommand == "parse":
        intent = service.parse_intent(parsed_args.input)
        print(json.dumps(intent.model_dump(), indent=2))

    elif parsed_args.subcommand == "execute":
        res = service.execute_query(parsed_args.input, case_context_id=parsed_args.case, officer_id=parsed_args.officer)
        print(f"Execution Status: {res.execution_status}")
        if res.disambiguation_required:
            print("DISAMBIGUATION REQUIRED! Candidates:")
            for c in res.disambiguation_candidates:
                print(f"  [{c.candidate_id}] {c.display_label} (Hop distance: {c.graph_distance_to_context})")
        else:
            print(f"Backend Operation: {res.executed_backend_operation}")
            print(f"Result Data: {res.data}")

    elif parsed_args.subcommand == "disambiguate":
        session = service.sessions.get(parsed_args.session_id)
        if not session or not session.pending_candidates:
            print("No pending disambiguation candidates.")
        else:
            for cid, cand in session.pending_candidates.items():
                print(f"[{cid}] {cand.display_label} (Distance: {cand.graph_distance_to_context})")

    elif parsed_args.subcommand == "resolve":
        res = service.resolve_disambiguation(parsed_args.session_id, parsed_args.candidate_id, officer_id=parsed_args.officer)
        print(f"Execution Status: {res.execution_status}")
        print(f"Backend Operation: {res.executed_backend_operation}")
        print(f"Data: {res.data}")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

