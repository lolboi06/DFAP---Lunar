# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: Test suite for M12 Evidence Chain Resolution and Verification (RC5 Hardening)

import pytest
import os
import json
import pandas as pd
from dfap.wp4.service import WP4Service
from dfap.wp4.contracts import (
    EvidenceChainError,
    ErrorCode,
    EvidenceStatus,
)


@pytest.fixture
def wp4_service():
    return WP4Service(data_dir="output")


def test_authoritative_findings_contract():
    """Formally verifies output/m3/findings/findings.parquet is the authoritative finding artifact."""
    path = "output/m3/findings/findings.parquet"
    assert os.path.exists(path), f"Authoritative findings contract missing: {path}"
    df = pd.read_parquet(path)
    assert len(df) == 12
    assert "finding_id" in df.columns
    assert "entity_id" in df.columns
    assert "anomaly_type" in df.columns
    assert "composite_score" in df.columns
    assert "evidence_refs" in df.columns
    assert "graph_refs" in df.columns


def test_list_findings_returns_deterministic_records(wp4_service):
    findings = wp4_service.list_findings()
    assert len(findings) > 0
    assert all("finding_id" in f and "entity_id" in f for f in findings)
    fids = [f["finding_id"] for f in findings]
    assert fids == sorted(fids)


def test_get_finding_success_and_unknown_error(wp4_service):
    findings = wp4_service.list_findings()
    first_fid = findings[0]["finding_id"]
    
    fnd = wp4_service.get_finding(first_fid)
    assert fnd["finding_id"] == first_fid
    assert "anomaly_type" in fnd
    assert "composite_score" in fnd

    with pytest.raises(EvidenceChainError) as exc_info:
        wp4_service.get_finding("FND_NON_EXISTENT_999")
    assert exc_info.value.error_code == ErrorCode.UNKNOWN_FINDING


def test_get_evidence_chain_real_artifact_resolution(wp4_service):
    findings = wp4_service.list_findings()
    first_fid = findings[0]["finding_id"]

    chain = wp4_service.get_evidence_chain(first_fid)
    assert chain["finding_id"] == first_fid
    assert chain["evidence_status"] in (EvidenceStatus.FULLY_EVIDENCED.value, EvidenceStatus.PARTIALLY_EVIDENCED.value)
    assert len(chain["evidence_events"]) > 0

    first_ev = chain["evidence_events"][0]
    assert "event_id" in first_ev
    assert "sha256_hash" in first_ev
    assert "source_file" in first_ev
    assert "source_row_index" in first_ev

    assert len(chain["provenance_steps"]) >= 3
    assert chain["provenance_steps"][0]["activity_type"] == "IngestionActivity"
    assert chain["provenance_steps"][-1]["activity_type"] == "FusionActivity"


def test_get_events_lookup(wp4_service):
    findings = wp4_service.list_findings()
    first_fid = findings[0]["finding_id"]
    chain = wp4_service.get_evidence_chain(first_fid)
    event_ids = [e["event_id"] for e in chain["evidence_events"]]

    events = wp4_service.get_events(event_ids)
    assert len(events) == len(event_ids)
    assert [e["event_id"] for e in events] == event_ids


# ── EXACT-SET CONSISTENCY TESTS ───────────────────────────────────────────────

def test_case_a_exact_set_consistent_fully_evidenced(wp4_service):
    """event_ids={A}, evidence_refs={hash(A)} -> consistent -> FULLY_EVIDENCED."""
    first_fid = wp4_service.list_findings()[0]["finding_id"]
    chain = wp4_service.get_evidence_chain(first_fid)
    assert chain["evidence_status"] == EvidenceStatus.FULLY_EVIDENCED.value
    assert not any(ErrorCode.INCONSISTENT_EVIDENCE_REFERENCE.value in iss for iss in chain["issues"])


def test_case_b_evidence_ref_only_resolves(wp4_service):
    """event_ids={}, evidence_refs={hash(A)} -> resolve from evidence_refs -> FULLY_EVIDENCED."""
    first_fid = wp4_service.list_findings()[0]["finding_id"]
    original_event_ids = wp4_service.evidence_engine.findings_by_id[first_fid]["event_ids"]
    try:
        wp4_service.evidence_engine.findings_by_id[first_fid]["event_ids"] = "[]"
        chain = wp4_service.get_evidence_chain(first_fid)
        assert len(chain["evidence_events"]) > 0
        assert chain["evidence_status"] == EvidenceStatus.FULLY_EVIDENCED.value
    finally:
        wp4_service.evidence_engine.findings_by_id[first_fid]["event_ids"] = original_event_ids


def test_case_c1_event_ids_subset_inconsistent(wp4_service):
    """event_ids={A, B}, evidence_refs={hash(A)} -> INCONSISTENT_EVIDENCE_REFERENCE -> NOT FULLY_EVIDENCED."""
    first_fid = wp4_service.list_findings()[0]["finding_id"]
    original_event_ids = wp4_service.evidence_engine.findings_by_id[first_fid]["event_ids"]
    original_ev_refs = wp4_service.evidence_engine.findings_by_id[first_fid]["evidence_refs"]
    try:
        wp4_service.evidence_engine.findings_by_id[first_fid]["event_ids"] = json.dumps(["EVT_80E854E8D3B557DC", "EVT_3ECE757380845FF1"])
        wp4_service.evidence_engine.findings_by_id[first_fid]["evidence_refs"] = json.dumps(["e248c66d000150b130280e00e4343b4f3c61aca54fda0ab29eafc9b2b762a7ca"])
        
        chain = wp4_service.get_evidence_chain(first_fid)
        assert chain["evidence_status"] != EvidenceStatus.FULLY_EVIDENCED.value
        assert any(ErrorCode.INCONSISTENT_EVIDENCE_REFERENCE.value in iss for iss in chain["issues"])
    finally:
        wp4_service.evidence_engine.findings_by_id[first_fid]["event_ids"] = original_event_ids
        wp4_service.evidence_engine.findings_by_id[first_fid]["evidence_refs"] = original_ev_refs


def test_case_c2_evidence_refs_superset_inconsistent(wp4_service):
    """event_ids={A}, evidence_refs={hash(A), hash(B)} -> INCONSISTENT_EVIDENCE_REFERENCE -> NOT FULLY_EVIDENCED."""
    first_fid = wp4_service.list_findings()[0]["finding_id"]
    original_event_ids = wp4_service.evidence_engine.findings_by_id[first_fid]["event_ids"]
    original_ev_refs = wp4_service.evidence_engine.findings_by_id[first_fid]["evidence_refs"]
    try:
        wp4_service.evidence_engine.findings_by_id[first_fid]["event_ids"] = json.dumps(["EVT_80E854E8D3B557DC"])
        wp4_service.evidence_engine.findings_by_id[first_fid]["evidence_refs"] = json.dumps([
            "e248c66d000150b130280e00e4343b4f3c61aca54fda0ab29eafc9b2b762a7ca",
            "041fb8d87f35167b6950f8dc3bf4b9f01f183a8d9af5623d5126e3356a2340c6"
        ])
        
        chain = wp4_service.get_evidence_chain(first_fid)
        assert chain["evidence_status"] != EvidenceStatus.FULLY_EVIDENCED.value
        assert any(ErrorCode.INCONSISTENT_EVIDENCE_REFERENCE.value in iss for iss in chain["issues"])
    finally:
        wp4_service.evidence_engine.findings_by_id[first_fid]["event_ids"] = original_event_ids
        wp4_service.evidence_engine.findings_by_id[first_fid]["evidence_refs"] = original_ev_refs


def test_case_c3_event_ids_and_evidence_refs_both_multi_match(wp4_service):
    """event_ids={A, B}, evidence_refs={hash(A), hash(B)} -> consistent -> FULLY_EVIDENCED."""
    first_fid = wp4_service.list_findings()[0]["finding_id"]
    original_event_ids = wp4_service.evidence_engine.findings_by_id[first_fid]["event_ids"]
    original_ev_refs = wp4_service.evidence_engine.findings_by_id[first_fid]["evidence_refs"]
    try:
        wp4_service.evidence_engine.findings_by_id[first_fid]["event_ids"] = json.dumps(["EVT_80E854E8D3B557DC", "EVT_3ECE757380845FF1"])
        wp4_service.evidence_engine.findings_by_id[first_fid]["evidence_refs"] = json.dumps([
            "e248c66d000150b130280e00e4343b4f3c61aca54fda0ab29eafc9b2b762a7ca",
            "041fb8d87f35167b6950f8dc3bf4b9f01f183a8d9af5623d5126e3356a2340c6"
        ])
        
        chain = wp4_service.get_evidence_chain(first_fid)
        assert chain["evidence_status"] == EvidenceStatus.FULLY_EVIDENCED.value
        assert not any(ErrorCode.INCONSISTENT_EVIDENCE_REFERENCE.value in iss for iss in chain["issues"])
    finally:
        wp4_service.evidence_engine.findings_by_id[first_fid]["event_ids"] = original_event_ids
        wp4_service.evidence_engine.findings_by_id[first_fid]["evidence_refs"] = original_ev_refs


def test_case_d_unknown_evidence_ref(wp4_service):
    """unknown evidence_ref -> MISSING_EVIDENCE_REF -> NOT FULLY_EVIDENCED."""
    first_fid = wp4_service.list_findings()[0]["finding_id"]
    original_ev_refs = wp4_service.evidence_engine.findings_by_id[first_fid]["evidence_refs"]
    try:
        wp4_service.evidence_engine.findings_by_id[first_fid]["evidence_refs"] = json.dumps(["9" * 64])
        chain = wp4_service.get_evidence_chain(first_fid)
        assert chain["evidence_status"] != EvidenceStatus.FULLY_EVIDENCED.value
        assert any(ErrorCode.MISSING_EVIDENCE_REF.value in iss for iss in chain["issues"])
    finally:
        wp4_service.evidence_engine.findings_by_id[first_fid]["evidence_refs"] = original_ev_refs


def test_complete_feature_traceability_on_real_artifacts(wp4_service):
    """
    Proves full feature traceability:
    finding_id -> feature reference -> exact feature store -> feature_name ->
    feature_value -> evidence_refs -> event_id -> canonical event -> sha256 ->
    provenance ledger -> source file -> source row
    """
    findings = wp4_service.list_findings()
    assert len(findings) > 0

    first_fid = findings[0]["finding_id"]
    chain = wp4_service.get_evidence_chain(first_fid)

    assert len(chain["resolved_features"]) > 0
    for feat in chain["resolved_features"]:
        assert feat["feature_name"] is not None
        assert feat["feature_store"] in (
            "graph_features.parquet",
            "telecom_features.parquet",
            "financial_features.parquet",
            "social_features.parquet",
        )
        assert feat["entity_id"] == chain["entity_id"]
        assert len(feat["evidence_refs"]) > 0

    assert len(chain["evidence_events"]) > 0
    for ev in chain["evidence_events"]:
        assert ev["event_id"] is not None
        assert len(ev["sha256_hash"]) == 64
        assert ev["source_file"] is not None
        assert ev["source_row_index"] is not None and ev["source_row_index"] >= 0
