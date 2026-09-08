# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: M13 Investigation Workspace State Manager

import json
from typing import Dict, List, Optional, Any, Tuple
from dateutil.parser import isoparse
from dfap.wp4.contracts import (
    WorkspaceState,
    WorkspaceError,
    ErrorCode,
)


class InvestigationWorkspace:
    """
    M13 Investigation Workspace State Manager.
    Manages selection states, timeline boundaries, and focus filters deterministically.
    Guarantees zero mutation of source artifacts and strict validation of time ranges and references.
    """

    def __init__(self, valid_entity_ids: Optional[Set[str]] = None, valid_finding_ids: Optional[Set[str]] = None):
        self._valid_entity_ids = valid_entity_ids or set()
        self._valid_finding_ids = valid_finding_ids or set()
        self._state = WorkspaceState()

    def get_state(self) -> WorkspaceState:
        """Returns the current immutable workspace state."""
        return self._state

    def reset_state(self) -> WorkspaceState:
        """Resets the workspace state to empty default."""
        self._state = WorkspaceState()
        return self._state

    def _validate_timestamp(self, ts: Optional[str], field_name: str) -> Optional[str]:
        if ts is None:
            return None
        ts_str = str(ts).strip()
        if not ts_str:
            return None
        try:
            parsed = isoparse(ts_str)
            return parsed.isoformat()
        except Exception as e:
            raise WorkspaceError(
                f"Invalid ISO timestamp for {field_name}: '{ts}' ({str(e)})",
                ErrorCode.INVALID_TIME_RANGE
            )

    def update_state(
        self,
        selected_entity_id: Optional[str] = None,
        selected_finding_id: Optional[str] = None,
        timeline_start: Optional[str] = None,
        timeline_end: Optional[str] = None,
        selected_event_ids: Optional[List[str]] = None,
        selected_relationship_ids: Optional[List[str]] = None,
    ) -> WorkspaceState:
        """
        Applies controlled updates to the investigation state with validation.
        """
        # Determine updated fields
        ent_id = self._state.selected_entity_id if selected_entity_id is None else (str(selected_entity_id).strip() or None)
        fnd_id = self._state.selected_finding_id if selected_finding_id is None else (str(selected_finding_id).strip() or None)
        
        t_start = self._state.timeline_start if timeline_start is None else self._validate_timestamp(timeline_start, "timeline_start")
        t_end = self._state.timeline_end if timeline_end is None else self._validate_timestamp(timeline_end, "timeline_end")

        # Validate time window ordering
        if t_start and t_end:
            dt_start = isoparse(t_start)
            dt_end = isoparse(t_end)
            if dt_start > dt_end:
                raise WorkspaceError(
                    f"timeline_start ({t_start}) cannot be strictly after timeline_end ({t_end})",
                    ErrorCode.INVALID_TIME_RANGE
                )

        # Validate entity and finding references if validators registered
        if ent_id and self._valid_entity_ids and ent_id not in self._valid_entity_ids:
            raise WorkspaceError(
                f"Invalid selected_entity_id: '{ent_id}' not found in resolved entities",
                ErrorCode.SCHEMA_CONTRACT_ERROR
            )

        if fnd_id and self._valid_finding_ids and fnd_id not in self._valid_finding_ids:
            raise WorkspaceError(
                f"Invalid selected_finding_id: '{fnd_id}' not found in findings",
                ErrorCode.UNKNOWN_FINDING
            )

        ev_ids = tuple(sorted(set(str(e).strip() for e in selected_event_ids if str(e).strip()))) if selected_event_ids is not None else self._state.selected_event_ids
        rel_ids = tuple(sorted(set(str(r).strip() for r in selected_relationship_ids if str(r).strip()))) if selected_relationship_ids is not None else self._state.selected_relationship_ids

        self._state = WorkspaceState(
            selected_entity_id=ent_id,
            selected_finding_id=fnd_id,
            timeline_start=t_start,
            timeline_end=t_end,
            selected_event_ids=ev_ids,
            selected_relationship_ids=rel_ids,
        )
        return self._state

    def serialize_state(self) -> str:
        """Returns deterministic canonical JSON string of state."""
        return self._state.to_canonical_json()

    def deserialize_state(self, json_str: str) -> WorkspaceState:
        """Loads and validates state from JSON string."""
        try:
            data = json.loads(json_str)
        except Exception as e:
            raise WorkspaceError(f"Malformed state JSON: {str(e)}", ErrorCode.SCHEMA_CONTRACT_ERROR)

        if not isinstance(data, dict):
            raise WorkspaceError("State JSON must be a dictionary", ErrorCode.SCHEMA_CONTRACT_ERROR)

        return self.update_state(
            selected_entity_id=data.get("selected_entity_id"),
            selected_finding_id=data.get("selected_finding_id"),
            timeline_start=data.get("timeline_start"),
            timeline_end=data.get("timeline_end"),
            selected_event_ids=data.get("selected_event_ids", []),
            selected_relationship_ids=data.get("selected_relationship_ids", []),
        )
