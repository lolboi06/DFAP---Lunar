import os
import pytest
from dfap.investigation.event_sourcing import (
    EventStore, 
    EventType, 
    DecisionState, 
    append_decision, 
    replay_decisions,
    materialize_identity_state
)

@pytest.fixture
def temp_store(tmp_path):
    store_file = tmp_path / "test_events.jsonl"
    return EventStore(str(store_file))

def test_confirm_event_append(temp_store):
    append_decision(temp_store, EventType.IDENTITY_CONFIRM, "officer_1", "case_1", "ent_1", "Looks good")
    state = materialize_identity_state(temp_store, "ent_1")
    assert state == DecisionState.CONFIRMED

def test_reject_event_append(temp_store):
    append_decision(temp_store, EventType.IDENTITY_REJECT, "officer_1", "case_1", "ent_1", "Bad ID")
    state = materialize_identity_state(temp_store, "ent_1")
    assert state == DecisionState.REJECTED

def test_undo_event_append(temp_store):
    append_decision(temp_store, EventType.IDENTITY_CONFIRM, "officer_1", "case_1", "ent_1", "Looks good")
    assert materialize_identity_state(temp_store, "ent_1") == DecisionState.CONFIRMED
    
    append_decision(temp_store, EventType.IDENTITY_UNDO, "officer_2", "case_1", "ent_1", "Mistake")
    assert materialize_identity_state(temp_store, "ent_1") == DecisionState.POSSIBLE

def test_replay_determinism(temp_store):
    append_decision(temp_store, EventType.IDENTITY_CONFIRM, "officer_1", "case_1", "ent_1", "Confirming")
    append_decision(temp_store, EventType.IDENTITY_REJECT, "officer_2", "case_1", "ent_1", "Actually rejecting")
    
    # replay 1
    res1 = replay_decisions(temp_store, "ent_1")
    # replay 2
    res2 = replay_decisions(temp_store, "ent_1")
    
    assert res1["state"] == res2["state"]
    assert len(res1["history"]) == len(res2["history"])
    assert res1["state"] == DecisionState.REJECTED

def test_immutable_history(temp_store):
    append_decision(temp_store, EventType.IDENTITY_CONFIRM, "officer_1", "case_1", "ent_1", "Yes")
    append_decision(temp_store, EventType.IDENTITY_UNDO, "officer_1", "case_1", "ent_1", "Undo")
    
    events = temp_store.get_events()
    assert len(events) == 2
    assert events[0].event_type == EventType.IDENTITY_CONFIRM
    assert events[1].event_type == EventType.IDENTITY_UNDO

def test_two_person_red_rejection(temp_store):
    append_decision(temp_store, EventType.IDENTITY_REJECT, "officer_1", "case_1", "ent_1", "Red reject", {"is_red_tier": True})
    assert materialize_identity_state(temp_store, "ent_1") == DecisionState.PENDING_SECOND_OFFICER_APPROVAL
    
    append_decision(temp_store, EventType.IDENTITY_REJECT, "officer_2", "case_1", "ent_1", "Red reject confirm", {"is_red_tier": True})
    assert materialize_identity_state(temp_store, "ent_1") == DecisionState.REJECTED

def test_same_officer_cannot_satisfy_second_approval(temp_store):
    append_decision(temp_store, EventType.IDENTITY_REJECT, "officer_1", "case_1", "ent_1", "Red reject", {"is_red_tier": True})
    append_decision(temp_store, EventType.IDENTITY_REJECT, "officer_1", "case_1", "ent_1", "Try to confirm my own reject", {"is_red_tier": True})
    
    assert materialize_identity_state(temp_store, "ent_1") == DecisionState.PENDING_SECOND_OFFICER_APPROVAL

def test_non_red_rejection_behavior(temp_store):
    append_decision(temp_store, EventType.IDENTITY_REJECT, "officer_1", "case_1", "ent_1", "Normal reject", {"is_red_tier": False})
    assert materialize_identity_state(temp_store, "ent_1") == DecisionState.REJECTED

def test_m4_immutability(temp_store):
    m4_path = "data/graph/m4_edges.parquet"
    if os.path.exists(m4_path):
        mtime_before = os.path.getmtime(m4_path)
        
        append_decision(temp_store, EventType.IDENTITY_CONFIRM, "officer_1", "case_1", "ent_1", "Yes")
        replay_decisions(temp_store, "ent_1")
        
        mtime_after = os.path.getmtime(m4_path)
        assert mtime_before == mtime_after

def test_shared_correction_event_schema(temp_store):
    append_decision(temp_store, EventType.NARRATIVE_CORRECTION, "officer_1", "case_1", "ent_1", "Fix typo", {"field": "summary"})
    events = temp_store.get_events()
    assert len(events) == 1
    assert events[0].event_type == EventType.NARRATIVE_CORRECTION
