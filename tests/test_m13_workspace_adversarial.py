# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: M13 Investigation Workspace Adversarial Test Suite (Tests A-Z + 17-Step Console E2E)

import copy
import json
import pytest
import pandas as pd

from dfap.investigation.workspace import (
    InvestigationWorkspaceBackend,
    CaseStatus,
    MatchStatus,
    InvestigationCase
)
from dfap.investigation.evidence_provenance import (
    CanonicalEvidenceRecord,
    EvidenceType,
    ProvenanceIntegrityStatus
)
from dfap.wp4.cli import handle_m13_command


@pytest.fixture
def backend():
    return InvestigationWorkspaceBackend(
        output_dir="output",
        canonical_dir="data/canonical",
        cases_dir="data/cases"
    )


VALID_ENTITY = "ENT_1F405CAB3F4951DA"
FOREIGN_ENTITY = "ENT_0F0FC38C24C0539E"


def _get_connected_chain(backend):
    for eid in sorted(backend.valid_entities):
        findings = [f for f in backend.findings_by_id.values() if str(f.get("entity_id", "")) == eid]
        if not findings:
            continue
        fid = str(findings[0]["finding_id"])
        ev_ids = list(backend.evidence_engine.finding_evidence_map.get(fid, []))
        if not ev_ids:
            prov = backend.get_provenance(fid)
            ev_ids = [
                n["node_id"]
                for n in prov.get("lineage_chain", [])
                if isinstance(n, dict) and n.get("node_id") in backend.evidence_engine.evidence_store
            ]
        if not ev_ids:
            continue
        ev = backend.evidence_engine.get_evidence(ev_ids[0])
        if ev and eid in ev.canonical_entity_ids:
            return eid, fid, ev_ids[0]
    return VALID_ENTITY, None, None


# ─────────────────────────────────────────────────────────────────────────────
# ADVERSARIAL TESTS A THROUGH Z
# ─────────────────────────────────────────────────────────────────────────────

def test_a_valid_entity_search(backend):
    """Test A: Valid entity search returns confirmed results with authoritative metadata."""
    results = backend.search(VALID_ENTITY, query_type="entity")
    assert len(results) > 0
    match = next((r for r in results if r["canonical_entity_id"] == VALID_ENTITY), None)
    assert match is not None
    assert match["match_status"] in (MatchStatus.CONFIRMED, MatchStatus.POSSIBLE)
    assert match["match_confidence"] > 0.0
    assert "identifier_type" in match
    assert "match_method" in match


def test_b_possible_identity_clearly_distinguished(backend):
    """Test B: Possible identity matches are explicitly distinguished from confirmed."""
    # Substring search that is not exact
    results = backend.search("1F405", query_type="entity")
    assert len(results) > 0
    # Any partial non-exact match should have POSSIBLE status or lower confidence
    for r in results:
        assert r["match_status"] in (MatchStatus.CONFIRMED, MatchStatus.POSSIBLE, MatchStatus.UNRESOLVED)
        if r["match_status"] == MatchStatus.POSSIBLE:
            assert r["match_confidence"] < 1.0


def test_c_rejected_identity_clearly_distinguished(backend):
    """Test C: Rejected identities are clearly distinguished and never collapsed into confirmed."""
    # Inject a known rejected identity in entities_df for adversarial testing
    backend.entities_df = pd.concat([
        backend.entities_df,
        pd.DataFrame([{
            "canonical_entity_id": "ENT_REJECTED_TEST",
            "raw_identifier": "RAW_REJECTED_999",
            "identifier_type": "ACCOUNT",
            "match_confidence": 0.10,
            "match_method": "REJECTED_HEURISTIC",
            "match_status": MatchStatus.REJECTED,
            "evidence": "{}"
        }])
    ], ignore_index=True)
    results = backend.search("RAW_REJECTED_999", query_type="account")
    assert len(results) > 0
    rej = next((r for r in results if r["raw_identifier"] == "RAW_REJECTED_999"), None)
    assert rej is not None
    assert rej["match_status"] == MatchStatus.REJECTED


def test_d_unknown_entity_rejected(backend):
    """Test D: Unknown entity rejected when authoritative identity is required (Fail Closed)."""
    with pytest.raises(ValueError, match="Fail Closed: Entity 'ENT_NONEXISTENT_999' is unknown"):
        backend.investigate_entity("ENT_NONEXISTENT_999")


def test_e_valid_case_creation(backend):
    """Test E: Valid case creation succeeds and records initial audit entries."""
    case = backend.create_case(VALID_ENTITY, created_by="TEST_AGENT")
    assert case.case_id.startswith("CASE-")
    assert case.canonical_entity_id == VALID_ENTITY
    assert case.status == CaseStatus.OPEN
    assert len(case.audit_log) >= 2
    actions = [a["action"] for a in case.audit_log]
    assert "CASE_CREATED" in actions
    assert "TARGET_SELECTED" in actions


def test_f_invalid_entity_case_rejected(backend):
    """Test F: Invalid entity case creation rejected (Fail Closed)."""
    with pytest.raises(ValueError, match="Fail Closed: Canonical entity 'ENT_INVALID_999' is unknown"):
        backend.create_case("ENT_INVALID_999")


def test_g_finding_attached(backend):
    """Test G: Finding attached to case succeeds and records audit event."""
    case = backend.create_case(VALID_ENTITY)
    # Find a finding belonging to VALID_ENTITY or register one
    fnd_id = next((fid for fid, f in backend.findings_by_id.items() if str(f.get("entity_id", "")) == VALID_ENTITY), None)
    if not fnd_id:
        fnd_id = "FND_TEST_ATTACH_01"
        backend.findings_by_id[fnd_id] = {
            "finding_id": fnd_id,
            "entity_id": VALID_ENTITY,
            "source_domain": "FINANCIAL",
            "composite_score": 0.85
        }
    updated = backend.attach_finding(case.case_id, fnd_id)
    assert fnd_id in updated.finding_ids
    actions = [a["action"] for a in updated.audit_log]
    assert "FINDING_ATTACHED" in actions


def test_h_duplicate_finding_attachment_idempotent(backend):
    """Test H: Duplicate finding attachment is idempotent and does not create duplicates."""
    case = backend.create_case(VALID_ENTITY)
    fnd_id = "FND_IDEMPOTENT_TEST"
    backend.findings_by_id[fnd_id] = {
        "finding_id": fnd_id,
        "entity_id": VALID_ENTITY,
        "source_domain": "FINANCIAL"
    }
    backend.attach_finding(case.case_id, fnd_id)
    backend.attach_finding(case.case_id, fnd_id)
    c = backend.get_case(case.case_id)
    assert c.finding_ids.count(fnd_id) == 1


def test_i_foreign_finding_rejected(backend):
    """Test I: Foreign finding belonging to another canonical entity is rejected (Fail Closed)."""
    case = backend.create_case(VALID_ENTITY)
    foreign_fnd = "FND_FOREIGN_999"
    backend.findings_by_id[foreign_fnd] = {
        "finding_id": foreign_fnd,
        "entity_id": FOREIGN_ENTITY,
        "source_domain": "TELECOM"
    }
    with pytest.raises(ValueError, match="Foreign finding rejected"):
        backend.attach_finding(case.case_id, foreign_fnd)


def test_j_evidence_attached(backend):
    """Test J: Evidence attached to case succeeds and records audit event."""
    case = backend.create_case(VALID_ENTITY)
    ev = CanonicalEvidenceRecord(
        evidence_type=EvidenceType.CANONICAL_EVENT,
        source_domain="TELECOM",
        source_id="SRC_ATT_01",
        source_file="data/test.parquet",
        source_row_index=1,
        canonical_entity_ids=[VALID_ENTITY],
        event_ids=["EVT_ATT_01"],
        observation_timestamp="2020-01-01T00:00:00Z",
        ingestion_timestamp="2020-01-01T00:05:00Z",
        derivation_method="TELECOM_INGESTION"
    )
    backend.evidence_engine.register_evidence(ev)
    updated = backend.attach_evidence(case.case_id, ev.evidence_id)
    assert ev.evidence_id in updated.evidence_ids
    assert ev.provenance_ref in updated.provenance_refs
    actions = [a["action"] for a in updated.audit_log]
    assert "EVIDENCE_ATTACHED" in actions


def test_k_foreign_evidence_rejected(backend):
    """Test K: Foreign evidence binding to another entity is rejected (Fail Closed)."""
    case = backend.create_case(VALID_ENTITY)
    ev_foreign = CanonicalEvidenceRecord(
        evidence_type=EvidenceType.CANONICAL_EVENT,
        source_domain="FINANCIAL",
        source_id="SRC_FOR_01",
        source_file="data/test.parquet",
        source_row_index=2,
        canonical_entity_ids=[FOREIGN_ENTITY],
        event_ids=["EVT_FOR_01"],
        observation_timestamp="2020-01-01T00:00:00Z",
        ingestion_timestamp="2020-01-01T00:05:00Z",
        derivation_method="FINANCIAL_INGESTION"
    )
    backend.evidence_engine.register_evidence(ev_foreign)
    with pytest.raises(ValueError, match="Foreign evidence rejected"):
        backend.attach_evidence(case.case_id, ev_foreign.evidence_id)


def test_l_provenance_preserved(backend):
    """Test L: Provenance is preserved and lineage hops are traceable."""
    # Register source -> event -> finding in evidence engine
    src = CanonicalEvidenceRecord(
        evidence_type=EvidenceType.SOURCE_RECORD,
        source_domain="TELECOM",
        source_id="SRC_LINEAGE_01",
        source_file="raw.csv",
        source_row_index=10,
        canonical_entity_ids=[VALID_ENTITY],
        event_ids=["EVT_LINEAGE_01"],
        observation_timestamp="2020-01-01T00:00:00Z",
        ingestion_timestamp="2020-01-01T00:05:00Z",
        derivation_method="RAW_EXTRACTION"
    )
    backend.evidence_engine.register_evidence(src)
    canon = CanonicalEvidenceRecord(
        evidence_type=EvidenceType.CANONICAL_EVENT,
        source_domain="TELECOM",
        source_id="SRC_LINEAGE_01",
        source_file="raw.csv",
        source_row_index=10,
        canonical_entity_ids=[VALID_ENTITY],
        event_ids=["EVT_LINEAGE_01"],
        observation_timestamp="2020-01-01T00:00:00Z",
        ingestion_timestamp="2020-01-01T00:05:00Z",
        derivation_method="SCHEMA_NORMALIZATION",
        parent_evidence_ids=[src.evidence_id]
    )
    backend.evidence_engine.register_evidence(canon)
    fnd_id = "FND_LINEAGE_TEST"
    backend.evidence_engine.bind_finding_to_evidence(
        finding_id=fnd_id,
        finding_type="ANOMALY_FINDING",
        evidence_ids=[canon.evidence_id],
        canonical_entity_id=VALID_ENTITY
    )
    prov = backend.get_provenance(fnd_id)
    assert prov["is_valid"] is True
    assert prov["lineage_hops_count"] >= 2


def test_m_timeline_respects_cutoff(backend):
    """Test M: Timeline respects from_time and to_time cutoffs strictly."""
    events = backend.get_timeline(VALID_ENTITY)
    assert len(events) > 0
    timestamps = [e["epoch_time"] for e in events if e.get("epoch_time") is not None]
    if len(timestamps) >= 2:
        t_min = min(timestamps)
        t_max = max(timestamps)
        t_mid = (t_min + t_max) / 2.0
        filtered = backend.get_timeline(VALID_ENTITY, from_time=t_min, to_time=t_mid)
        for e in filtered:
            if e.get("epoch_time") is not None:
                assert t_min <= e["epoch_time"] <= t_mid


def test_n_future_event_excluded_from_historical_query(backend):
    """Test N: Future events strictly excluded from historical backtrack query."""
    events = backend.get_timeline(VALID_ENTITY)
    timestamps = [e["epoch_time"] for e in events if e.get("epoch_time") is not None]
    if len(timestamps) >= 2:
        pivot = sorted(timestamps)[len(timestamps) // 2]
        bt = backend.backtrack(VALID_ENTITY, pivot=pivot)
        for e in bt.get("preceding_events", []):
            if e.get("epoch_time") is not None:
                assert e["epoch_time"] < pivot


def test_o_unknown_timestamp_preserved(backend):
    """Test O: UNKNOWN_TIMESTAMP is preserved and never fabricated into UTC dates."""
    backend.live_stream_events.append({
        "event_id": "EVT_UNKNOWN_TS",
        "actor_id": VALID_ENTITY,
        "target_id": "TARGET_99",
        "timestamp": None,
        "epoch_time": None,
        "temporal_semantics": "UNKNOWN_TIMESTAMP",
        "source_domain": "TELECOM"
    })
    tl = backend.get_timeline(VALID_ENTITY)
    target = next((e for e in tl if e["event_id"] == "EVT_UNKNOWN_TS"), None)
    assert target is not None
    assert target["temporal_semantics"] == "UNKNOWN_TIMESTAMP"
    assert target.get("epoch_time") is None


def test_p_sequence_order_surrogate_preserved(backend):
    """Test P: SEQUENCE_ORDER_SURROGATE is preserved and never fabricated into calendar dates."""
    backend.live_stream_events.append({
        "event_id": "EVT_SURROGATE_01",
        "actor_id": VALID_ENTITY,
        "target_id": "TARGET_99",
        "timestamp": "seq:105",
        "epoch_time": 105.0,
        "temporal_semantics": "SEQUENCE_ORDER_SURROGATE",
        "source_domain": "NETWORK"
    })
    tl = backend.get_timeline(VALID_ENTITY)
    target = next((e for e in tl if e["event_id"] == "EVT_SURROGATE_01"), None)
    assert target is not None
    assert target["temporal_semantics"] == "SEQUENCE_ORDER_SURROGATE"


def test_q_valid_backtrack(backend):
    """Test Q: Valid backtrack returns preceding causal chain."""
    res = backend.backtrack(VALID_ENTITY, window_seconds=86400.0)
    assert "entity_id" in res
    assert "preceding_events" in res
    assert isinstance(res["preceding_events"], list)


def test_r_valid_forwardtrack(backend):
    """Test R: Valid forwardtrack returns subsequent causal chain."""
    res = backend.forwardtrack(VALID_ENTITY, window_seconds=86400.0)
    assert "entity_id" in res
    assert "subsequent_events" in res
    assert isinstance(res["subsequent_events"], list)


def test_s_temporal_graph_path_correctness(backend):
    """Test S: Temporal graph paths correctly resolve 1-hop and 2-hop neighborhoods."""
    paths = backend.get_paths(VALID_ENTITY)
    assert len(paths) > 0
    subgraph = paths[0]
    assert subgraph.get("entity_id") == VALID_ENTITY
    assert "1hop_neighbors" in subgraph
    assert "2hop_neighbors" in subgraph


def test_t_m11_fused_finding_preserved(backend):
    """Test T: M11 cross-domain fused finding retains contributing domain evidence."""
    inv = backend.investigate_entity(VALID_ENTITY)
    assert "m11_fused_findings" in inv
    assert "domains" in inv
    assert isinstance(inv["domains"], list)


def test_u_m12_integrity_failure_propagates(backend):
    """Test U: M12 evidence tampering propagates and invalidates finding provenance."""
    src = CanonicalEvidenceRecord(
        evidence_type=EvidenceType.SOURCE_RECORD,
        source_domain="FINANCIAL",
        source_id="SRC_TAMPER_01",
        source_file="fin.parquet",
        source_row_index=5,
        canonical_entity_ids=[VALID_ENTITY],
        event_ids=["EVT_TAMPER_01"],
        observation_timestamp="2020-01-01T00:00:00Z",
        ingestion_timestamp="2020-01-01T00:05:00Z",
        derivation_method="FINANCIAL_INGESTION"
    )
    backend.evidence_engine.register_evidence(src)
    fnd_id = "FND_TAMPER_TEST"
    backend.evidence_engine.bind_finding_to_evidence(
        finding_id=fnd_id,
        finding_type="ANOMALY_FINDING",
        evidence_ids=[src.evidence_id],
        canonical_entity_id=VALID_ENTITY
    )
    # Directly tamper with evidence record in store
    backend.evidence_engine.evidence_store[src.evidence_id].source_row_index = 9999
    prov = backend.get_provenance(fnd_id)
    assert prov["is_valid"] is False
    assert prov["integrity_status"] in (
        ProvenanceIntegrityStatus.TAMPERED_RECORD_DETECTED,
        ProvenanceIntegrityStatus.BROKEN_PROVENANCE_CHAIN
    )


def test_v_case_status_history_preserved(backend):
    """Test V: Case status history is preserved across transitions without destroying historical states."""
    case = backend.create_case(VALID_ENTITY)
    backend.update_case_status(case.case_id, CaseStatus.UNDER_REVIEW, reason="Initial review")
    backend.update_case_status(case.case_id, CaseStatus.ESCALATED, reason="High anomaly score")
    c = backend.get_case(case.case_id)
    assert c.status == CaseStatus.ESCALATED
    assert len(c.status_history) == 2
    assert c.status_history[0]["from_status"] == CaseStatus.OPEN
    assert c.status_history[0]["to_status"] == CaseStatus.UNDER_REVIEW
    assert c.status_history[1]["from_status"] == CaseStatus.UNDER_REVIEW
    assert c.status_history[1]["to_status"] == CaseStatus.ESCALATED


def test_w_investigator_notes_persisted(backend):
    """Test W: Investigator notes are persisted with timestamps and authors."""
    case = backend.create_case(VALID_ENTITY)
    backend.add_case_note(case.case_id, "First preliminary note", author="INVESTIGATOR_ALICE")
    backend.add_case_note(case.case_id, "Second escalation note", author="INVESTIGATOR_BOB")
    c = backend.get_case(case.case_id)
    assert len(c.notes) == 2
    assert c.notes[0]["author"] == "INVESTIGATOR_ALICE"
    assert c.notes[1]["author"] == "INVESTIGATOR_BOB"
    assert "First preliminary note" in c.notes[0]["text"]
    assert "Second escalation note" in c.notes[1]["text"]


def test_x_deterministic_case_export(backend):
    """Test X: Case export produces valid structured JSON containing all audit and lineage fields."""
    case = backend.create_case(VALID_ENTITY, case_id="CASE-EXPORT-TEST")
    backend.add_case_note(case.case_id, "Audit note for export")
    export_json = backend.export_case(case.case_id, export_format="json")
    data = json.loads(export_json)
    assert data["case_id"] == "CASE-EXPORT-TEST"
    assert data["canonical_entity_id"] == VALID_ENTITY
    assert "audit_log" in data
    assert "status_history" in data
    assert "notes" in data


def test_y_repeated_export_deterministic(backend):
    """Test Y: Repeated case exports are byte-for-byte deterministic."""
    case = backend.create_case(VALID_ENTITY, case_id="CASE-DET-EXP")
    first = backend.export_case(case.case_id, export_format="json")
    second = backend.export_case(case.case_id, export_format="json")
    assert first == second


def test_z_cross_entity_contamination_rejected(backend):
    """Test Z: Cross-entity contamination is strictly prevented across cases, findings, and evidence."""
    case_a = backend.create_case(VALID_ENTITY)
    # Foreign finding rejection
    foreign_fnd = "FND_CONTAM_01"
    backend.findings_by_id[foreign_fnd] = {
        "finding_id": foreign_fnd,
        "entity_id": FOREIGN_ENTITY,
        "source_domain": "FINANCIAL"
    }
    with pytest.raises(ValueError):
        backend.attach_finding(case_a.case_id, foreign_fnd)

    # Foreign evidence rejection
    ev_foreign = CanonicalEvidenceRecord(
        evidence_type=EvidenceType.CANONICAL_EVENT,
        source_domain="FINANCIAL",
        source_id="SRC_CONTAM_02",
        source_file="fin.parquet",
        source_row_index=1,
        canonical_entity_ids=[FOREIGN_ENTITY],
        event_ids=["EVT_CONTAM_02"],
        observation_timestamp="2020-01-01T00:00:00Z",
        ingestion_timestamp="2020-01-01T00:05:00Z",
        derivation_method="FINANCIAL_INGESTION"
    )
    backend.evidence_engine.register_evidence(ev_foreign)
    with pytest.raises(ValueError):
        backend.attach_evidence(case_a.case_id, ev_foreign.evidence_id)


# ─────────────────────────────────────────────────────────────────────────────
# CONSOLE END-TO-END WORKFLOW TEST (SECTION 15)
# ─────────────────────────────────────────────────────────────────────────────

def test_console_end_to_end_17_step_workflow(backend):
    """
    Automated Console Workflow Test (Section 15):
    1. search entity
    2. select canonical entity
    3. create case
    4. inspect case
    5. retrieve findings
    6. inspect evidence
    7. inspect provenance
    8. inspect timeline
    9. backtrack
    10. forwardtrack
    11. inspect graph/path
    12. attach finding
    13. attach evidence
    14. add note
    15. change status
    16. audit case
    17. export case
    """
    # 1. search entity
    out1 = handle_m13_command(backend, f"search entity {VALID_ENTITY}")
    assert VALID_ENTITY in out1
    assert "CONFIRMED" in out1 or "POSSIBLE" in out1

    # 2. select canonical entity
    selected_entity = VALID_ENTITY

    # 3. create case
    out3 = handle_m13_command(backend, f"case create {selected_entity}")
    assert "CASE CREATED" in out3
    case_id = next(p for p in out3.split() if p.startswith("CASE-"))

    # 4. inspect case
    out4 = handle_m13_command(backend, f"case show {case_id}")
    assert case_id in out4
    assert selected_entity in out4

    # 5. retrieve findings
    out5 = handle_m13_command(backend, f"findings {selected_entity}")
    assert "FINDINGS" in out5

    # 6. inspect evidence
    # Ensure at least one evidence item exists in store for selected entity
    ev = CanonicalEvidenceRecord(
        evidence_type=EvidenceType.CANONICAL_EVENT,
        source_domain="TELECOM",
        source_id="SRC_E2E_01",
        source_file="telecom.parquet",
        source_row_index=12,
        canonical_entity_ids=[selected_entity],
        event_ids=["EVT_E2E_01"],
        observation_timestamp="2020-01-01T00:00:00Z",
        ingestion_timestamp="2020-01-01T00:05:00Z",
        derivation_method="TELECOM_INGESTION"
    )
    backend.evidence_engine.register_evidence(ev)
    out6 = handle_m13_command(backend, f"evidence {ev.evidence_id}")
    assert ev.evidence_id in out6

    # 7. inspect provenance
    fnd_id = "FND_E2E_TEST"
    backend.evidence_engine.bind_finding_to_evidence(
        finding_id=fnd_id,
        finding_type="ANOMALY_FINDING",
        evidence_ids=[ev.evidence_id],
        canonical_entity_id=selected_entity
    )
    backend.findings_by_id[fnd_id] = {
        "finding_id": fnd_id,
        "entity_id": selected_entity,
        "source_domain": "TELECOM",
        "composite_score": 0.88
    }
    out7 = handle_m13_command(backend, f"provenance {fnd_id}")
    assert "PROVENANCE" in out7
    assert fnd_id in out7

    # 8. inspect timeline
    out8 = handle_m13_command(backend, f"timeline {selected_entity}")
    assert selected_entity in out8

    # 9. backtrack
    out9 = handle_m13_command(backend, f"backtrack {selected_entity} 24h")
    assert "BACKTRACK" in out9
    assert selected_entity in out9

    # 10. forwardtrack
    out10 = handle_m13_command(backend, f"forwardtrack {selected_entity} 24h")
    assert "FORWARDTRACK" in out10
    assert selected_entity in out10

    # 11. inspect graph/path
    out11 = handle_m13_command(backend, f"paths {selected_entity}")
    assert "PATHS" in out11
    assert selected_entity in out11

    # 12. attach finding
    out12 = handle_m13_command(backend, f"case attach-finding {case_id} {fnd_id}")
    assert "CASE FINDING ATTACHED" in out12
    assert fnd_id in out12

    # 13. attach evidence
    out13 = handle_m13_command(backend, f"case attach-evidence {case_id} {ev.evidence_id}")
    assert "CASE EVIDENCE ATTACHED" in out13
    assert ev.evidence_id in out13

    # 14. add note
    out14 = handle_m13_command(backend, f"case note {case_id} \"Investigator review: confirmed multi-hop anomaly\"")
    assert "CASE NOTE ADDED" in out14

    # 15. change status
    out15 = handle_m13_command(backend, f"case status {case_id} ESCALATED")
    assert "CASE STATUS UPDATED" in out15
    assert "ESCALATED" in out15

    # 16. audit case
    out16 = handle_m13_command(backend, f"case audit {case_id}")
    assert "CASE AUDIT" in out16
    assert "CASE_CREATED" in out16
    assert "FINDING_ATTACHED" in out16
    assert "EVIDENCE_ATTACHED" in out16
    assert "STATUS_CHANGED" in out16

    # 17. export case
    out17 = handle_m13_command(backend, f"case export {case_id}")
    assert "CASE EXPORT" in out17
    assert case_id in out17
