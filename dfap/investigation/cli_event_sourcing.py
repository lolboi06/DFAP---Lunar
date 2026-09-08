import os
import argparse
import json
from dfap.investigation.event_sourcing import (
    EventStore, EventType, append_decision, replay_decisions, get_decision_history, DecisionState
)

def run_smoke_test():
    store = EventStore("data/demo_feature4_events.jsonl")
    # clear file if exists
    if os.path.exists(store.file_path):
        os.remove(store.file_path)
    
    print("=== STARTING EVENT SOURCING SMOKE TEST ===")
    
    entity_id = "ENT_SYNTHETIC_TEST_001"
    case_id = "CASE-TEST-001"
    
    # 1. CONFIRM
    print("\n[Action] Officer A confirms identity")
    append_decision(store, EventType.IDENTITY_CONFIRM, "officer_A", case_id, entity_id, "Matches documentation")
    res = replay_decisions(store, entity_id)
    print(f"  Materialized State: {res['state'].value}")
    assert res["state"] == DecisionState.CONFIRMED
    
    # 2. UNDO
    print("\n[Action] Officer A undoes confirmation")
    append_decision(store, EventType.IDENTITY_UNDO, "officer_A", case_id, entity_id, "Mistake")
    res = replay_decisions(store, entity_id)
    print(f"  Materialized State: {res['state'].value}")
    assert res["state"] == DecisionState.POSSIBLE
    
    # 3. REJECT on RED finding (1st officer)
    print("\n[Action] Officer A rejects identity (RED finding)")
    append_decision(store, EventType.IDENTITY_REJECT, "officer_A", case_id, entity_id, "Suspicious mismatch", {"is_red_tier": True})
    res = replay_decisions(store, entity_id)
    print(f"  Materialized State: {res['state'].value} (Pending: {res['pending_officer']})")
    assert res["state"] == DecisionState.PENDING_SECOND_OFFICER_APPROVAL
    
    # 4. REJECT on RED finding (2nd officer)
    print("\n[Action] Officer B rejects identity (RED finding)")
    append_decision(store, EventType.IDENTITY_REJECT, "officer_B", case_id, entity_id, "Confirmed mismatch", {"is_red_tier": True})
    res = replay_decisions(store, entity_id)
    print(f"  Materialized State: {res['state'].value}")
    assert res["state"] == DecisionState.REJECTED
    
    # 5. Replay history verification
    print("\n[Action] Replaying History")
    history = get_decision_history(store, entity_id)
    for e in history:
        print(f"  - {e.timestamp} | {e.officer_id} | {e.event_type.value} | {e.reason}")
        
    res_final = replay_decisions(store, entity_id)
    print(f"\nFinal Verified State: {res_final['state'].value}")
    assert res_final["state"] == res["state"]
    print("=== SMOKE TEST PASSED ===")

def main(args=None):
    parser = argparse.ArgumentParser(prog='identity decision')
    subparsers = parser.add_subparsers(dest='command')
    
    parser_confirm = subparsers.add_parser('confirm')
    parser_confirm.add_argument('--officer', required=True)
    parser_confirm.add_argument('--case', required=True)
    parser_confirm.add_argument('--entity', required=True)
    parser_confirm.add_argument('--reason', required=True)
    
    parser_reject = subparsers.add_parser('reject')
    parser_reject.add_argument('--officer', required=True)
    parser_reject.add_argument('--case', required=True)
    parser_reject.add_argument('--entity', required=True)
    parser_reject.add_argument('--reason', required=True)
    parser_reject.add_argument('--red-tier', action='store_true')
    
    parser_undo = subparsers.add_parser('undo')
    parser_undo.add_argument('--officer', required=True)
    parser_undo.add_argument('--case', required=True)
    parser_undo.add_argument('--entity', required=True)
    parser_undo.add_argument('--reason', required=True)
    
    parser_history = subparsers.add_parser('history')
    parser_history.add_argument('--entity', required=True)
    
    parser_replay = subparsers.add_parser('replay')
    parser_replay.add_argument('--entity', required=True)
    
    subparsers.add_parser('demo')
    subparsers.add_parser('smoke')
    
    args = parser.parse_args(args)
    store = EventStore()
    
    if args.command in ('demo', 'smoke'):
        run_smoke_test()
        return
    elif args.command == 'confirm':
        append_decision(store, EventType.IDENTITY_CONFIRM, args.officer, args.case, args.entity, args.reason)
        print("Confirmed.")
    elif args.command == 'reject':
        meta = {"is_red_tier": True} if args.red_tier else {}
        append_decision(store, EventType.IDENTITY_REJECT, args.officer, args.case, args.entity, args.reason, meta)
        res = replay_decisions(store, args.entity)
        if res["state"] == DecisionState.PENDING_SECOND_OFFICER_APPROVAL:
            print("PENDING_SECOND_OFFICER_APPROVAL")
        else:
            print("Rejected.")
    elif args.command == 'undo':
        append_decision(store, EventType.IDENTITY_UNDO, args.officer, args.case, args.entity, args.reason)
        print("Undone.")
    elif args.command == 'history':
        hist = get_decision_history(store, args.entity)
        for h in hist:
            print(json.dumps(h.to_dict()))
    elif args.command == 'replay':
        res = replay_decisions(store, args.entity)
        print(f"Current State: {res['state'].value}")
        if res['pending_officer']:
            print(f"Pending Officer: {res['pending_officer']}")

if __name__ == '__main__':
    main()
