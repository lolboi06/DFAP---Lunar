# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research

import json

import pytest

from dfap.investigation.workspace import InvestigationWorkspaceBackend
from dfap.wp4.cli import handle_m13_command, run_interactive_console
from dfap.wp4.service import WP4Service


@pytest.fixture
def backend():
    return InvestigationWorkspaceBackend(output_dir="output", canonical_dir="data/canonical", cases_dir="data/cases")


VALID_ENTITY = "ENT_1F405CAB3F4951DA"
FOREIGN_ENTITY = "ENT_0F0FC38C24C0539E"


def _find_connected_entity_finding_evidence(backend):
    for entity_id in sorted(backend.valid_entities):
        findings = [
            f for f in backend.findings_by_id.values()
            if str(f.get("entity_id", "")) == entity_id
        ]
        if not findings:
            continue
        finding_id = str(findings[0]["finding_id"])
        prov = backend.get_provenance(finding_id)
        evidence_ids = list(backend.evidence_engine.finding_evidence_map.get(finding_id, []))
        if not evidence_ids:
            evidence_ids = [
                n["node_id"]
                for n in prov.get("lineage_chain", [])
                if isinstance(n, dict) and n.get("node_id") in backend.evidence_engine.evidence_store
            ]
        if not evidence_ids:
            continue
        evidence_id = str(evidence_ids[0])
        ev = backend.evidence_engine.get_evidence(evidence_id)
        if not ev:
            continue
        if entity_id not in ev.canonical_entity_ids:
            continue
        return entity_id, finding_id, evidence_id
    raise AssertionError("No connected real entity/finding/evidence chain found in authoritative data.")


def test_search_entity_command_uses_real_backend(backend):
    output = handle_m13_command(backend, f"search entity {VALID_ENTITY}")
    assert VALID_ENTITY in output
    assert "CONFIRMED" in output or "POSSIBLE" in output


def test_graph_2hop_subgraph_returns_real_neighbors(backend):
    graph = backend.graph_traversal.get_2hop_subgraph(VALID_ENTITY)
    assert graph["entity_id"] == VALID_ENTITY
    assert "1hop_neighbors" in graph
    assert "2hop_neighbors" in graph
    assert isinstance(graph["1hop_neighbors"], list)
    assert isinstance(graph["2hop_neighbors"], list)


def test_graph_2hop_subgraph_rejects_unknown_entity(backend):
    with pytest.raises(ValueError, match="Unknown graph entity"):
        backend.graph_traversal.get_2hop_subgraph("ENT_DOES_NOT_EXIST")


def test_real_e2e_entity_finding_evidence_provenance_case_chain_is_consistent(backend):
    entity_id, finding_id, evidence_id = _find_connected_entity_finding_evidence(backend)

    findings_for_entity = [
        f for f in backend.findings_by_id.values()
        if str(f.get("entity_id", "")) == entity_id
    ]
    assert findings_for_entity
    finding_in_results = findings_for_entity[0]
    assert finding_in_results["finding_id"] == finding_id

    finding_show = handle_m13_command(backend, f"finding show {finding_id}")
    assert finding_id in finding_show
    assert f'"entity": "{entity_id}"' in finding_show

    provenance = backend.get_provenance(finding_id)
    assert provenance["finding_id"] == finding_id
    assert provenance.get("lineage_chain")

    provenance_text = handle_m13_command(backend, f"provenance {finding_id}")
    assert finding_id in provenance_text
    assert "PROVENANCE" in provenance_text or "LINEAGE" in provenance_text

    evidence_ids_from_provenance = []
    for node in provenance.get("lineage_chain", []):
        if isinstance(node, dict) and node.get("node_id") in backend.evidence_engine.evidence_store:
            evidence_ids_from_provenance.append(node["node_id"])
    evidence_ids_from_provenance.extend(backend.evidence_engine.finding_evidence_map.get(finding_id, []))
    evidence_ids_from_provenance = sorted(set(evidence_ids_from_provenance))
    assert evidence_ids_from_provenance
    assert evidence_id in evidence_ids_from_provenance

    evidence_show = handle_m13_command(backend, f"evidence show {evidence_id}")
    assert evidence_id in evidence_show
    assert entity_id in evidence_show

    case = backend.create_case(entity_id, case_id="CASE-CHAIN-E2E")
    backend.attach_finding(case.case_id, finding_id)
    backend.attach_evidence(case.case_id, evidence_id)
    case_show = handle_m13_command(backend, f"case show {case.case_id}")
    assert case.case_id in case_show
    assert finding_id in case_show
    assert evidence_id in case_show
    assert backend.cases[case.case_id].canonical_entity_id == entity_id
    assert case.case_id in backend.cases
    assert backend.cases[case.case_id].finding_ids == [finding_id]
    assert backend.cases[case.case_id].evidence_ids == [evidence_id]


def test_provenance_rejects_unknown_and_cross_entity_mismatch(backend):
    with pytest.raises(KeyError):
        backend.get_provenance("FND_DOES_NOT_EXIST")

    entity_a, finding_a, evidence_a = _find_connected_entity_finding_evidence(backend)
    other_entities = [eid for eid in sorted(backend.valid_entities) if eid != entity_a]
    entity_b = other_entities[0]
    finding_b = next(
        (fid for fid, f in backend.findings_by_id.items() if str(f.get("entity_id", "")) == entity_b),
        None,
    )
    assert finding_b is not None
    evidence_b = next(
        (
            evidence_id
            for evidence_id, evidence in backend.evidence_engine.evidence_store.items()
            if entity_b in evidence.canonical_entity_ids
        ),
        None,
    )
    assert evidence_b is not None

    with pytest.raises(ValueError):
        backend.evidence_engine.bind_finding_to_evidence(
            finding_b,
            canonical_entity_id=entity_b,
            evidence_ids=[evidence_a],
            expected_event_ids=[]
        )

    unrelated_same_entity = next(
        (
            ev_id
            for ev_id, ev in backend.evidence_engine.evidence_store.items()
            if entity_a in ev.canonical_entity_ids and ev_id != evidence_a and ev_id not in backend.evidence_engine.finding_evidence_map.get(finding_a, [])
        ),
        None,
    )
    if unrelated_same_entity is not None:
        assert unrelated_same_entity not in backend.evidence_engine.finding_evidence_map.get(finding_a, [])

    case = backend.create_case(entity_a, case_id="CASE-CHAIN-REJECT")
    with pytest.raises(ValueError):
        backend.attach_finding(case.case_id, finding_b)
    with pytest.raises(ValueError):
        backend.attach_evidence(case.case_id, evidence_b)


def test_case_create_show_and_attach_real_objects(backend):
    case_text = handle_m13_command(backend, f"case create {VALID_ENTITY}")
    case_id = next(part for part in case_text.split() if part.startswith("CASE-"))
    assert case_id.startswith("CASE-")

    show_text = handle_m13_command(backend, f"case show {case_id}")
    assert case_id in show_text
    assert VALID_ENTITY in show_text

    finding_id = next(iter(backend.findings_by_id))
    attach_result = handle_m13_command(backend, f"case attach-finding {case_id} {finding_id}")
    assert finding_id in attach_result

    evidence_id = next(iter(backend.evidence_engine.evidence_store))
    if evidence_id:
        ev_text = handle_m13_command(backend, f"case attach-evidence {case_id} {evidence_id}")
        assert evidence_id in ev_text


def test_findings_and_provenance_are_exposed(backend):
    finding_id = next(iter(backend.findings_by_id))
    finding_text = handle_m13_command(backend, f"finding show {finding_id}")
    assert finding_id in finding_text

    provenance_text = handle_m13_command(backend, f"provenance {finding_id}")
    assert "LINEAGE" in provenance_text or "FINDING" in provenance_text


def test_timeline_and_backtrack_are_real_and_temporal_semantics_preserved(backend):
    timeline_text = handle_m13_command(backend, f"timeline {VALID_ENTITY}")
    assert VALID_ENTITY in timeline_text
    assert "OBSERVED_TIMESTAMP" in timeline_text or "SEQUENCE_ORDER_SURROGATE" in timeline_text or "UNKNOWN_TIMESTAMP" in timeline_text

    backtrack_text = handle_m13_command(backend, f"backtrack {VALID_ENTITY} 24h")
    assert VALID_ENTITY in backtrack_text

    forwardtrack_text = handle_m13_command(backend, f"forwardtrack {VALID_ENTITY} 24h")
    assert VALID_ENTITY in forwardtrack_text


def test_case_exports_are_deterministic(backend):
    case = backend.create_case(VALID_ENTITY, case_id="CASE-TEST-DET")
    first = json.loads(backend.export_case(case.case_id, export_format="json"))
    second = json.loads(backend.export_case(case.case_id, export_format="json"))
    assert first == second


def test_console_why_for_active_discovery_case_uses_case_context_and_not_stale_fallback(monkeypatch, capsys):
    inputs = iter([
        "source unsw",
        "scan unsw",
        "open CASE-UNS-001",
        "why CASE-UNS-001",
        "copilot ask \"Why was FLOW_133 flagged?\"",
        "exit",
    ])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))

    run_interactive_console(WP4Service(data_dir="output"), initial_scenario="escalation")
    out = capsys.readouterr().out

    assert "CASE-UNS-001" in out
    assert "FLOW_133" in out
    assert "No active anomaly, case, or finding to explain." not in out
    assert "ENT_0F0FC38C24C0539E" not in out
    assert "EVD-CAN-b8479923d4e7" not in out
    assert "INSUFFICIENT_EVIDENCE" in out


def test_foreign_entity_rejection_and_duplicate_attachment_idempotency(backend):
    case = backend.create_case(VALID_ENTITY, case_id="CASE-FOREIGN-REJECT")
    foreign = next(fid for fid, item in backend.findings_by_id.items() if item.get("entity_id") == FOREIGN_ENTITY)
    with pytest.raises(ValueError):
        backend.attach_finding(case.case_id, foreign)

    finding_id = next(fid for fid, item in backend.findings_by_id.items() if item.get("entity_id") == VALID_ENTITY)
    backend.attach_finding(case.case_id, finding_id)
    backend.attach_finding(case.case_id, finding_id)
    assert case.case_id in backend.cases
    assert backend.cases[case.case_id].finding_ids.count(finding_id) == 1


def test_foreign_evidence_rejection_and_case_audit_history(backend):
    case = backend.create_case(VALID_ENTITY, case_id="CASE-EVIDENCE-REJECT")
    foreign_evidence = next(
        ev_id for ev_id, ev in backend.evidence_engine.evidence_store.items()
        if VALID_ENTITY not in ev.canonical_entity_ids
    )
    with pytest.raises(ValueError):
        backend.attach_evidence(case.case_id, foreign_evidence)

    valid_evidence = next(
        ev_id for ev_id, ev in backend.evidence_engine.evidence_store.items()
        if VALID_ENTITY in ev.canonical_entity_ids
    )
    backend.attach_evidence(case.case_id, valid_evidence)
    backend.attach_evidence(case.case_id, valid_evidence)
    assert valid_evidence in backend.cases[case.case_id].evidence_ids
    assert len(backend.cases[case.case_id].audit_log) >= 2


def test_provenance_preservation_and_unknown_timestamp_handling(backend):
    finding_id = next(iter(backend.findings_by_id))
    provenance = backend.get_provenance(finding_id)
    assert provenance["is_valid"] is True
    assert isinstance(provenance["lineage_chain"], list)

    timeline = backend.get_timeline(VALID_ENTITY)
    assert timeline
    assert all("temporal_semantics" in event for event in timeline)


def test_real_end_to_end_console_workflow(backend):
    entity_id = VALID_ENTITY
    case_create = handle_m13_command(backend, f"case create {entity_id}")
    case_id = next(part for part in case_create.split() if part.startswith("CASE-"))
    assert case_id.startswith("CASE-")

    investigate = handle_m13_command(backend, f"investigate {entity_id}")
    assert entity_id in investigate

    findings = handle_m13_command(backend, f"findings {entity_id}")
    assert "FINDINGS" in findings or "[]" in findings or "finding_id" in findings

    finding_id = next(iter(backend.findings_by_id))
    finding_show = handle_m13_command(backend, f"finding show {finding_id}")
    assert finding_id in finding_show

    evidence_id = next(iter(backend.evidence_engine.evidence_store))
    evidence_show = handle_m13_command(backend, f"evidence show {evidence_id}")
    assert evidence_id in evidence_show

    provenance = handle_m13_command(backend, f"provenance {finding_id}")
    assert "PROVENANCE" in provenance

    timeline = handle_m13_command(backend, f"timeline {entity_id}")
    assert entity_id in timeline

    backtrack = handle_m13_command(backend, f"backtrack {entity_id} 24h")
    assert entity_id in backtrack

    forwardtrack = handle_m13_command(backend, f"forwardtrack {entity_id} 24h")
    assert entity_id in forwardtrack

    paths = handle_m13_command(backend, f"paths {entity_id}")
    assert entity_id in paths or "1hop" in paths or "2hop" in paths

    attach_finding = handle_m13_command(backend, f"case attach-finding {case_id} {finding_id}")
    assert finding_id in attach_finding

    attach_evidence = handle_m13_command(backend, f"case attach-evidence {case_id} {evidence_id}")
    assert evidence_id in attach_evidence

    note = handle_m13_command(backend, f"case note {case_id} \"audit note\"")
    assert "NOTE" in note or "audit" in note.lower()

    status = handle_m13_command(backend, f"case status {case_id} UNDER_REVIEW")
    assert "UNDER_REVIEW" in status

    audit = handle_m13_command(backend, f"case audit {case_id}")
    assert "audit" in audit.lower() or "STATUS_CHANGED" in audit or "CASE_CREATED" in audit

    export_text = handle_m13_command(backend, f"case export {case_id}")
    assert "CASE EXPORT" in export_text
    exported = json.loads(backend.export_case(case_id, export_format="json"))
    assert exported["case_id"] == case_id


def test_m13_rejects_unknown_entity_and_unknown_evidence(backend):
    with pytest.raises(ValueError):
        backend.create_case("ENT_DOES_NOT_EXIST")

    with pytest.raises(KeyError):
        backend.attach_evidence("CASE-DOES-NOT-EXIST", "EVD-DOES-NOT-EXIST")

    unknown_finding = "FND_DOES_NOT_EXIST"
    with pytest.raises(KeyError):
        backend.get_finding(unknown_finding)
