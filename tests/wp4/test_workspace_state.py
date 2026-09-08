# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: Test suite for M13 Investigation Workspace State Manager

import pytest
from dfap.wp4.workspace import InvestigationWorkspace
from dfap.wp4.contracts import WorkspaceError, ErrorCode


def test_workspace_initial_state_and_reset():
    ws = InvestigationWorkspace()
    state = ws.get_state()
    assert state.selected_entity_id is None
    assert state.selected_finding_id is None
    assert state.timeline_start is None
    assert state.timeline_end is None
    assert state.selected_event_ids == ()
    assert state.selected_relationship_ids == ()

    # Update state
    ws.update_state(
        selected_entity_id="ENT_123",
        selected_finding_id="FND_456",
        selected_event_ids=["EVT_1", "EVT_2"]
    )
    upd_state = ws.get_state()
    assert upd_state.selected_entity_id == "ENT_123"
    assert upd_state.selected_finding_id == "FND_456"
    assert len(upd_state.selected_event_ids) == 2

    # Reset state
    res_state = ws.reset_state()
    assert res_state.selected_entity_id is None
    assert res_state.selected_finding_id is None
    assert res_state.selected_event_ids == ()


def test_workspace_state_serialization_roundtrip():
    ws = InvestigationWorkspace()
    ws.update_state(
        selected_entity_id="ENT_TARGET_01",
        selected_finding_id="FND_ALERT_99",
        timeline_start="2026-09-01T00:00:00+00:00",
        timeline_end="2026-09-02T00:00:00+00:00",
        selected_event_ids=["EVT_B", "EVT_A"], # tests sorting
        selected_relationship_ids=["REL_1"]
    )

    serialized = ws.serialize_state()
    assert "ENT_TARGET_01" in serialized

    # Deserialize into new workspace
    ws2 = InvestigationWorkspace()
    ws2.deserialize_state(serialized)
    s2 = ws2.get_state()

    assert s2.selected_entity_id == "ENT_TARGET_01"
    assert s2.selected_finding_id == "FND_ALERT_99"
    assert s2.timeline_start == "2026-09-01T00:00:00+00:00"
    assert s2.timeline_end == "2026-09-02T00:00:00+00:00"
    assert s2.selected_event_ids == ("EVT_A", "EVT_B") # sorted
    assert s2.selected_relationship_ids == ("REL_1",)


def test_workspace_rejects_invalid_date_range():
    ws = InvestigationWorkspace()
    with pytest.raises(WorkspaceError) as exc_info:
        ws.update_state(
            timeline_start="2026-09-02T00:00:00+00:00",
            timeline_end="2026-09-01T00:00:00+00:00"
        )
    assert exc_info.value.error_code == ErrorCode.INVALID_TIME_RANGE
