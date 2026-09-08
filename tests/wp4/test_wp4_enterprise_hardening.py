# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: Master Enterprise Hardening Test Suite for Work Package 4 (Member 4)

import pytest
import os
import hashlib
from dfap.wp4.service import WP4Service
from dfap.wp4.contracts import (
    EvidenceChainError,
    WorkspaceError,
    UpstreamContractError,
    ErrorCode,
    EvidenceStatus,
    RelationshipStatus,
)


@pytest.fixture
def service():
    return WP4Service(data_dir="output")


def test_m12_upstream_contract_validation(service):
    diag = service.verify_upstream_integrity()
    assert diag["status"] == "HEALTHY"
    assert diag["read_only"] is True
    assert "canonical_events.parquet" in diag["manifest"]
    assert "provenance_ledger.parquet" in diag["manifest"]
    assert "resolved_entities.parquet" in diag["manifest"]


def test_m12_evidence_chain_completeness_and_prov_o(service):
    findings = service.list_findings()
    assert len(findings) > 0

    for f in findings:
        fid = f["finding_id"]
        chain = service.get_evidence_chain(fid)
        assert chain["finding_id"] == fid
        assert "prov_o_document" in chain
        assert "@context" in chain["prov_o_document"]
        assert len(chain["evidence_events"]) > 0


def test_m13_timeline_contract(service):
    entity_id = "ENT_0F0FC38C24C0539E"
    timeline = service.get_entity_timeline(entity_id)
    assert len(timeline) > 0

    for ev in timeline:
        assert ev["event_id"] is not None
        assert ev["timestamp"] is not None
        assert ev["source_domain"] in ("CDR", "IPDR", "BANK", "SOCIAL")


def test_m13_subgraph_2hop_boundary_contract(service):
    entity_id = "ENT_0F0FC38C24C0539E"
    sub = service.get_entity_subgraph(entity_id, hops=2)
    assert sub["hop_count"] == 2
    assert all(n["hop_distance"] <= 2 for n in sub["nodes"])

    cy = service.get_cytoscape_payload(entity_id, hops=2)
    assert "nodes" in cy
    assert "edges" in cy


def test_m13_workspace_state_lifecycle(service):
    service.reset_workspace_state()
    s0 = service.get_workspace_state()
    assert s0["selected_entity_id"] is None

    service.update_workspace_state(selected_entity_id="ENT_0F0FC38C24C0539E")
    s1 = service.get_workspace_state()
    assert s1["selected_entity_id"] == "ENT_0F0FC38C24C0539E"

    service.reset_workspace_state()
    s2 = service.get_workspace_state()
    assert s2["selected_entity_id"] is None
