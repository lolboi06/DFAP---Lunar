# Author: Sam Roger X
# Component: DFAP Paper 3 Evaluation Harness
# Scope: State Management Architectures: MUTABLE_BASELINE (overwrite) vs LEDGER (event-sourced replay)

import os
import uuid
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timezone

from dfap.investigation.event_sourcing import (
    EventStore,
    DecisionEvent,
    EventType,
    DecisionState,
    IdentityDecisionMaterializer,
)
from dfap.experiments.paper3_models import (
    ERArchitecture,
    IdentityStateRecord,
)


class MutableIdentityStore:
    """
    Conventional Mutable Overwrite-in-Place Identity Resolution Store.
    
    Architectural characteristics:
    - Current identity state is mutated directly in memory / table.
    - Correction overwrites the previous state.
    - Historical incorrect state is permanently lost.
    - No immutable event ledger exists; corrected_via_event is None.
    """

    def __init__(self):
        self.architecture = ERArchitecture.MUTABLE_BASELINE
        # raw_id -> canonical_entity_id
        self.id_to_entity: Dict[str, str] = {}
        # canonical_entity_id -> set of raw_ids
        self.entity_to_ids: Dict[str, set] = {}
        # raw_id -> status (CONFIRMED, POSSIBLE, REJECTED)
        self.statuses: Dict[str, str] = {}

    def register_link(self, raw_id: str, canonical_entity_id: str, status: str = "CONFIRMED"):
        """Inserts or overwrites an entity mapping directly."""
        old_entity = self.id_to_entity.get(raw_id)
        if old_entity and old_entity in self.entity_to_ids:
            self.entity_to_ids[old_entity].discard(raw_id)

        self.id_to_entity[raw_id] = canonical_entity_id
        if canonical_entity_id not in self.entity_to_ids:
            self.entity_to_ids[canonical_entity_id] = set()
        self.entity_to_ids[canonical_entity_id].add(raw_id)
        self.statuses[raw_id] = status

    def overwrite_correction(self, raw_id: str, new_canonical_entity_id: str, new_status: str = "CONFIRMED") -> None:
        """Applies correction via direct overwrite."""
        self.register_link(raw_id, new_canonical_entity_id, new_status)

    def get_canonical_entity(self, raw_id: str) -> Optional[str]:
        return self.id_to_entity.get(raw_id)

    def get_raw_identifiers(self, canonical_entity_id: str) -> List[str]:
        return sorted(list(self.entity_to_ids.get(canonical_entity_id, set())))

    def get_status(self, raw_id: str) -> str:
        return self.statuses.get(raw_id, "UNKNOWN")

    def snapshot(self) -> Dict[str, Any]:
        return {
            "id_to_entity": dict(self.id_to_entity),
            "statuses": dict(self.statuses),
            "architecture": self.architecture.value,
        }


class LedgerIdentityStore:
    """
    Event-Sourced Non-Destructive Identity Resolution Ledger.
    
    Architectural characteristics:
    - Authoritative truth is the append-only DecisionEvent log.
    - Current identity state is a MATERIALIZED VIEW derived by deterministic event replay.
    - An erroneous decision is NEVER overwritten or deleted from the event store.
    - Correction is appended as an explicit new event (IDENTITY_UNDO or IDENTITY_REJECT).
    - Historical incorrect state remains 100% recoverable by point-in-time replay.
    - Downstream modules consume the materialized current state.
    """

    def __init__(self, event_store: Optional[EventStore] = None):
        self.architecture = ERArchitecture.LEDGER
        self.event_store = event_store or EventStore(f"data/paper3_events_{uuid.uuid4().hex[:8]}.jsonl")
        self.last_correction_event_id: Optional[str] = None

    def append_decision(
        self,
        event_type: Any,
        officer_id: str,
        case_id: str,
        raw_id: str,
        canonical_entity_id: str,
        reason: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> DecisionEvent:
        """Appends an immutable identity decision event."""
        if isinstance(event_type, str):
            event_type = EventType(event_type)

        meta = dict(metadata or {})
        meta["raw_id"] = raw_id
        meta["canonical_entity_id"] = canonical_entity_id

        # Determine states
        prev_entity = self.get_canonical_entity(raw_id)
        prev_state = DecisionState.CONFIRMED if prev_entity else DecisionState.POSSIBLE

        req_state = DecisionState.CONFIRMED
        if event_type in (EventType.IDENTITY_REJECT, EventType.IDENTITY_UNDO):
            req_state = DecisionState.REJECTED

        event = DecisionEvent(
            event_type=event_type,
            officer_id=officer_id,
            case_id=case_id,
            entity_id=f"{canonical_entity_id}:{raw_id}",
            previous_state=prev_state,
            requested_state=req_state,
            reason=reason,
            metadata=meta,
        )
        self.event_store.append_event(event)
        return event

    def append_correction(
        self,
        officer_id: str,
        case_id: str,
        raw_id: str,
        correct_canonical_entity_id: str,
        reason: str,
        correction_event_type: EventType = EventType.IDENTITY_CONFIRM,
    ) -> DecisionEvent:
        """
        Appends an explicit correction event without mutating historical decisions.
        Records the correction event ID.
        """
        event = self.append_decision(
            event_type=correction_event_type,
            officer_id=officer_id,
            case_id=case_id,
            raw_id=raw_id,
            canonical_entity_id=correct_canonical_entity_id,
            reason=reason,
            metadata={"is_correction": True},
        )
        self.last_correction_event_id = event.event_id
        return event

    def replay_current_state(self, up_to_timestamp: Optional[str] = None) -> Tuple[Dict[str, str], Dict[str, set], Dict[str, str]]:
        """
        Deterministically replays all events up to up_to_timestamp to produce the materialized identity view.
        Returns (id_to_entity, entity_to_ids, statuses).
        """
        events = self.event_store.get_events()
        if up_to_timestamp:
            events = [e for e in events if e.timestamp <= up_to_timestamp]

        id_to_entity: Dict[str, str] = {}
        entity_to_ids: Dict[str, set] = {}
        statuses: Dict[str, str] = {}

        for e in events:
            raw_id = e.metadata.get("raw_id")
            canon_id = e.metadata.get("canonical_entity_id")
            if not raw_id or not canon_id:
                continue

            if e.event_type == EventType.IDENTITY_CONFIRM:
                old_ent = id_to_entity.get(raw_id)
                if old_ent and old_ent in entity_to_ids:
                    entity_to_ids[old_ent].discard(raw_id)

                id_to_entity[raw_id] = canon_id
                if canon_id not in entity_to_ids:
                    entity_to_ids[canon_id] = set()
                entity_to_ids[canon_id].add(raw_id)
                statuses[raw_id] = "CONFIRMED"

            elif e.event_type in (EventType.IDENTITY_REJECT, EventType.IDENTITY_UNDO):
                old_ent = id_to_entity.get(raw_id)
                if old_ent and old_ent in entity_to_ids:
                    entity_to_ids[old_ent].discard(raw_id)
                id_to_entity.pop(raw_id, None)
                statuses[raw_id] = "REJECTED"

        return id_to_entity, entity_to_ids, statuses

    def get_canonical_entity(self, raw_id: str) -> Optional[str]:
        id_to_entity, _, _ = self.replay_current_state()
        return id_to_entity.get(raw_id)

    def get_raw_identifiers(self, canonical_entity_id: str) -> List[str]:
        _, entity_to_ids, _ = self.replay_current_state()
        return sorted(list(entity_to_ids.get(canonical_entity_id, set())))

    def get_status(self, raw_id: str) -> str:
        _, _, statuses = self.replay_current_state()
        return statuses.get(raw_id, "UNKNOWN")

    def get_historical_state(self, event_index: int) -> Tuple[Dict[str, str], Dict[str, set]]:
        """Replays state up to a specific event index, proving historical state recoverability."""
        events = self.event_store.get_events()
        cutoff_events = events[:event_index + 1] if event_index < len(events) else events
        
        id_to_entity: Dict[str, str] = {}
        entity_to_ids: Dict[str, set] = {}
        for e in cutoff_events:
            raw_id = e.metadata.get("raw_id")
            canon_id = e.metadata.get("canonical_entity_id")
            if not raw_id or not canon_id:
                continue
            if e.event_type == EventType.IDENTITY_CONFIRM:
                old_ent = id_to_entity.get(raw_id)
                if old_ent and old_ent in entity_to_ids:
                    entity_to_ids[old_ent].discard(raw_id)
                id_to_entity[raw_id] = canon_id
                if canon_id not in entity_to_ids:
                    entity_to_ids[canon_id] = set()
                entity_to_ids[canon_id].add(raw_id)
            elif e.event_type in (EventType.IDENTITY_REJECT, EventType.IDENTITY_UNDO):
                old_ent = id_to_entity.get(raw_id)
                if old_ent and old_ent in entity_to_ids:
                    entity_to_ids[old_ent].discard(raw_id)
                id_to_entity.pop(raw_id, None)

        return id_to_entity, entity_to_ids
