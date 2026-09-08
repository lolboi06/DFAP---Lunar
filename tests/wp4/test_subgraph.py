# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: Test suite for M13 Network & 2-Hop Subgraph Backend and Cytoscape Serialization

import pytest
from dfap.wp4.service import WP4Service
from dfap.wp4.contracts import WorkspaceError, ErrorCode, RelationshipStatus


@pytest.fixture
def wp4_service():
    return WP4Service(data_dir="output")


def test_subgraph_hop_boundaries_0_1_2(wp4_service):
    entity_id = "ENT_0F0FC38C24C0539E"

    # Hop 0 (root node only)
    sub0 = wp4_service.get_entity_subgraph(entity_id, hops=0)
    assert sub0["hop_count"] == 0
    assert len(sub0["nodes"]) == 1
    assert sub0["nodes"][0]["id"] == entity_id
    assert sub0["nodes"][0]["hop_distance"] == 0

    # Hop 1 (direct 1-hop neighborhood)
    sub1 = wp4_service.get_entity_subgraph(entity_id, hops=1)
    assert sub1["hop_count"] == 1
    assert all(n["hop_distance"] <= 1 for n in sub1["nodes"])

    # Hop 2 (bounded 2-hop neighborhood)
    sub2 = wp4_service.get_entity_subgraph(entity_id, hops=2)
    assert sub2["hop_count"] == 2
    assert all(n["hop_distance"] <= 2 for n in sub2["nodes"])


def test_subgraph_rejects_hops_greater_than_2_and_negative(wp4_service):
    entity_id = "ENT_0F0FC38C24C0539E"

    with pytest.raises(WorkspaceError) as exc_info:
        wp4_service.get_entity_subgraph(entity_id, hops=3)
    assert exc_info.value.error_code == ErrorCode.INVALID_HOP_COUNT

    with pytest.raises(WorkspaceError) as exc_info:
        wp4_service.get_entity_subgraph(entity_id, hops=-1)
    assert exc_info.value.error_code == ErrorCode.INVALID_HOP_COUNT


def test_subgraph_preserves_relationship_status_and_evidence(wp4_service):
    entity_id = "ENT_0F0FC38C24C0539E"
    sub = wp4_service.get_entity_subgraph(entity_id, hops=2)
    
    for edge in sub["edges"]:
        assert edge["relationship_status"] in (RelationshipStatus.OBSERVED.value, RelationshipStatus.INFERRED.value)
        assert "evidence_event_ids" in edge
        assert "source" in edge
        assert "target" in edge


def test_cytoscape_payload_serializer(wp4_service):
    entity_id = "ENT_0F0FC38C24C0539E"
    cy = wp4_service.get_cytoscape_payload(entity_id, hops=2)

    assert "nodes" in cy
    assert "edges" in cy
    
    for n in cy["nodes"]:
        assert "data" in n
        assert "id" in n["data"]
        assert "node_type" in n["data"]

    for e in cy["edges"]:
        assert "data" in e
        assert "source" in e["data"]
        assert "target" in e["data"]
        assert "relationship_status" in e["data"]
        assert "evidence_event_ids" in e["data"]
