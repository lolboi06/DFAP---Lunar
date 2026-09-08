# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: Test suite for M13 Unified Timeline Backend and Half-Open Window Semantics

import pytest
from dfap.wp4.service import WP4Service
from dfap.wp4.contracts import WorkspaceError, ErrorCode


@pytest.fixture
def wp4_service():
    return WP4Service(data_dir="output")


def test_timeline_extraction_and_ordering(wp4_service):
    entity_id = "ENT_0F0FC38C24C0539E"
    timeline = wp4_service.get_entity_timeline(entity_id)
    assert len(timeline) > 0

    # Verify deterministic ordering: sorted by timestamp then event_id
    keys = [(e["timestamp"], e["event_id"]) for e in timeline]
    assert keys == sorted(keys)

    # Verify canonical event preservation
    for ev in timeline:
        assert "event_id" in ev
        assert "timestamp" in ev
        assert "event_type" in ev
        assert "source_domain" in ev
        assert "actor_id" in ev
        assert "sha256_hash" in ev


def test_timeline_half_open_window_boundaries(wp4_service):
    entity_id = "ENT_0F0FC38C24C0539E"
    full_timeline = wp4_service.get_entity_timeline(entity_id)
    assert len(full_timeline) > 0

    exact_ts = full_timeline[0]["timestamp"]

    # Inclusive start: should match
    res_start = wp4_service.get_entity_timeline(entity_id, start=exact_ts)
    assert len(res_start) > 0

    # Exclusive end: exact timestamp as end boundary should NOT match [start, exact_ts)
    res_end = wp4_service.get_entity_timeline(entity_id, start=exact_ts, end=exact_ts)
    assert len(res_end) == 0


def test_timeline_reversed_window_error(wp4_service):
    entity_id = "ENT_0F0FC38C24C0539E"
    with pytest.raises(WorkspaceError) as exc_info:
        wp4_service.get_entity_timeline(
            entity_id,
            start="2026-09-02T12:00:00+00:00",
            end="2026-09-01T12:00:00+00:00"
        )
    assert exc_info.value.error_code == ErrorCode.INVALID_TIME_RANGE


def test_timeline_empty_window_and_unknown_entity(wp4_service):
    # Empty window
    empty_tl = wp4_service.get_entity_timeline(
        "ENT_0F0FC38C24C0539E",
        start="2020-01-01T00:00:00+00:00",
        end="2020-01-02T00:00:00+00:00"
    )
    assert empty_tl == []

    # Unknown entity returns empty list
    unk_tl = wp4_service.get_entity_timeline("ENT_UNKNOWN_NON_EXISTENT")
    assert unk_tl == []
