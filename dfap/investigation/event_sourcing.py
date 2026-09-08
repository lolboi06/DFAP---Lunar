import json
import os
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import List, Dict, Any, Optional

class EventType(str, Enum):
    IDENTITY_CONFIRM = "IDENTITY_CONFIRM"
    IDENTITY_REJECT = "IDENTITY_REJECT"
    IDENTITY_UNDO = "IDENTITY_UNDO"
    QUERY_DISAMBIGUATION = "QUERY_DISAMBIGUATION"
    NARRATIVE_CORRECTION = "NARRATIVE_CORRECTION"
    GLOSSARY_CORRECTION = "GLOSSARY_CORRECTION"
    QUERY_ISSUED = "QUERY_ISSUED"
    DISAMBIGUATION_RESOLVED = "DISAMBIGUATION_RESOLVED"
    PROMPT_SHOWN = "PROMPT_SHOWN"
    PROMPT_OUTCOME = "PROMPT_OUTCOME"

class DecisionState(str, Enum):
    POSSIBLE = "POSSIBLE"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    PENDING_SECOND_OFFICER_APPROVAL = "PENDING_SECOND_OFFICER_APPROVAL"
    NONE = "NONE"

class DecisionEvent:
    def __init__(self, event_type: EventType, officer_id: str, case_id: str, entity_id: str, previous_state: DecisionState, requested_state: DecisionState, reason: str, metadata: Dict[str, Any] = None, event_id: str = None, timestamp: str = None):
        self.event_id = event_id or str(uuid.uuid4())
        self.event_type = event_type
        self.timestamp = timestamp or datetime.now(timezone.utc).isoformat()
        self.officer_id = officer_id
        self.case_id = case_id
        self.entity_id = entity_id
        self.previous_state = previous_state
        self.requested_state = requested_state
        self.reason = reason
        self.metadata = metadata or {}

    def to_dict(self):
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "timestamp": self.timestamp,
            "officer_id": self.officer_id,
            "case_id": self.case_id,
            "entity_id": self.entity_id,
            "previous_state": self.previous_state.value,
            "requested_state": self.requested_state.value,
            "reason": self.reason,
            "metadata": self.metadata
        }

    def model_dump(self):
        """Pydantic compatibility alias."""
        return self.to_dict()

    def dict(self):
        """Pydantic compatibility alias."""
        return self.to_dict()

    @classmethod
    def from_dict(cls, d: Dict[str, Any]):
        return cls(
            event_type=EventType(d["event_type"]),
            officer_id=d["officer_id"],
            case_id=d["case_id"],
            entity_id=d["entity_id"],
            previous_state=DecisionState(d["previous_state"]),
            requested_state=DecisionState(d["requested_state"]),
            reason=d["reason"],
            metadata=d.get("metadata", {}),
            event_id=d["event_id"],
            timestamp=d["timestamp"]
        )

class EventStore:
    """Deterministic local append-only persistence adapter."""
    def __init__(self, file_path: str = "data/decision_events.jsonl"):
        self.file_path = file_path

    def append_event(self, event: DecisionEvent):
        parent_dir = os.path.dirname(self.file_path)
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)
        with open(self.file_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event.to_dict()) + "\n")

    def get_events(self) -> List[DecisionEvent]:
        events = []
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        events.append(DecisionEvent.from_dict(json.loads(line)))
        except FileNotFoundError:
            pass
        return events

    def get_events_for_case(self, case_id: str) -> List[DecisionEvent]:
        return [e for e in self.get_events() if e.case_id == case_id]

    def get_events_for_officer(self, officer_id: str) -> List[DecisionEvent]:
        return [e for e in self.get_events() if e.officer_id == officer_id]

class IdentityDecisionMaterializer:
    def __init__(self, store: EventStore):
        self.store = store

    def replay(self, entity_id: str) -> Dict[str, Any]:
        events = self.store.get_events()
        entity_events = [e for e in events if e.entity_id == entity_id]
        
        state_stack = [DecisionState.POSSIBLE]
        officer_stack = [None]
        history = []

        for e in entity_events:
            history.append(e)
            if e.event_type == EventType.IDENTITY_UNDO:
                if len(state_stack) > 1:
                    state_stack.pop()
                    officer_stack.pop()
            else:
                current_state = state_stack[-1]
                pending_officer = officer_stack[-1]
                
                new_state = current_state
                new_pending_officer = pending_officer

                if e.event_type == EventType.IDENTITY_CONFIRM:
                    new_state = DecisionState.CONFIRMED
                    new_pending_officer = None
                elif e.event_type == EventType.IDENTITY_REJECT:
                    is_red_tier = e.metadata.get("is_red_tier", False)
                    if is_red_tier:
                        if current_state == DecisionState.PENDING_SECOND_OFFICER_APPROVAL:
                            if pending_officer != e.officer_id:
                                new_state = DecisionState.REJECTED
                                new_pending_officer = None
                        else:
                            new_state = DecisionState.PENDING_SECOND_OFFICER_APPROVAL
                            new_pending_officer = e.officer_id
                    else:
                        new_state = DecisionState.REJECTED
                        new_pending_officer = None
                
                state_stack.append(new_state)
                officer_stack.append(new_pending_officer)

        return {
            "entity_id": entity_id,
            "state": state_stack[-1],
            "pending_officer": officer_stack[-1],
            "history": history
        }

def append_decision(store: EventStore, event_type: EventType, officer_id: str, case_id: str, entity_id: str, reason: str, metadata: Dict[str, Any] = None) -> DecisionEvent:
    materializer = IdentityDecisionMaterializer(store)
    current_info = materializer.replay(entity_id)
    current_state = current_info["state"]
    
    req_state = current_state
    if event_type == EventType.IDENTITY_CONFIRM:
        req_state = DecisionState.CONFIRMED
    elif event_type == EventType.IDENTITY_REJECT:
        is_red = (metadata or {}).get("is_red_tier", False)
        req_state = DecisionState.REJECTED if not is_red else DecisionState.PENDING_SECOND_OFFICER_APPROVAL
        
    event = DecisionEvent(
        event_type=event_type,
        officer_id=officer_id,
        case_id=case_id,
        entity_id=entity_id,
        previous_state=current_state,
        requested_state=req_state,
        reason=reason,
        metadata=metadata
    )
    store.append_event(event)
    return event

def replay_decisions(store: EventStore, entity_id: str) -> Dict[str, Any]:
    materializer = IdentityDecisionMaterializer(store)
    return materializer.replay(entity_id)

def get_decision_history(store: EventStore, entity_id: str) -> List[DecisionEvent]:
    return replay_decisions(store, entity_id)["history"]

def materialize_identity_state(store: EventStore, entity_id: str) -> DecisionState:
    return replay_decisions(store, entity_id)["state"]
