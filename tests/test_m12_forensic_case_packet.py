# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: Test Suite for M12 Forensic Case Packet (Synthesis, Deterministic Export, Traceability, M13 CLI, M14 Copilot)

import json
import os
import pytest

from dfap.investigation.workspace import InvestigationWorkspaceBackend
from dfap.investigation.forensic_fixture import (
    register_forensic_demo_fixture,
    FORENSIC_DEMO_CASE_ID,
    FORENSIC_DEMO_ENTITY_ID,
    FND_FORENSIC_001,
    EVD_FIN_SUPPORT,
    EVD_SOC_CONTRA,
)
from dfap.investigation.forensic_case_packet import (
    ForensicCasePacketEngine,
    PacketStatus,
    PacketRequiredAction
)
from dfap.investigation.copilot import InvestigationCopilot
from dfap.wp4.cli import handle_m13_command


@pytest.fixture
def workspace_with_forensic_case():
    backend = InvestigationWorkspaceBackend()
    register_forensic_demo_fixture(backend)
    return backend


def test_forensic_case_packet_generation(workspace_with_forensic_case):
    backend = workspace_with_forensic_case
    engine = ForensicCasePacketEngine(backend)
    packet = engine.generate_packet(FORENSIC_DEMO_CASE_ID)

    # 1. Status & Required Action
    assert packet.packet_status == PacketStatus.CONFLICTED.value
    assert packet.required_action == PacketRequiredAction.HUMAN_REVIEW.value
    assert packet.packet_digest is not None
    assert len(packet.packet_digest) == 64

    # 2. Case metadata
    assert packet.case["case_id"] == FORENSIC_DEMO_CASE_ID
    assert FORENSIC_DEMO_ENTITY_ID in packet.case["entities"]
    assert "FINANCIAL" in packet.case["domains"]
    assert "SOCIAL" in packet.case["domains"]

    # 3. Findings
    assert len(packet.findings) == 1
    f0 = packet.findings[0]
    assert f0["finding_id"] == FND_FORENSIC_001
    assert EVD_FIN_SUPPORT in f0["supporting_evidence_ids"]
    assert EVD_SOC_CONTRA in f0["contradicting_evidence_ids"]
    assert len(f0["claims"]) >= 1

    # 4. Timeline
    assert len(packet.timeline) >= 12
    for ev in packet.timeline:
        assert "event_id" in ev
        assert "timestamp" in ev
        assert "ordering_basis" in ev
        assert ev["ordering_basis"] == "AUTHORITATIVE_TIMESTAMP"
        assert "evidence_ref" in ev
        assert "provenance_ref" in ev

    # 5. Temporal Intelligence (M10 integration)
    temp_intel = packet.temporal_intelligence
    assert temp_intel["sequence_summary"]["total_events"] >= 12
    assert len(temp_intel["discovered_motifs"]) >= 1
    motif = temp_intel["discovered_motifs"][0]
    assert motif["motif_id"].startswith("DISCOVERED_MOTIF_")
    assert motif["cluster_size"] >= 3
    assert motif["representative_event_types"] == ["LOGIN", "QUERY", "TRANSFER"]

    # 6. Evidential Conflict Intelligence (M11 integration)
    conflict_intel = packet.conflict_intelligence
    assert conflict_intel["overall_status"] in ("MATERIAL_CONFLICT", "ABSTENTION_REQUIRED")
    assert conflict_intel["required_action"] == "HUMAN_REVIEW"
    assert len(conflict_intel["pairs"]) >= 1
    conflicted_pairs = [p for p in conflict_intel["pairs"] if p["conflict_status"] in ("MATERIAL_CONFLICT", "ABSTENTION_REQUIRED")]
    assert len(conflicted_pairs) >= 1
    assert conflicted_pairs[0]["compound_conflict"] > 0.35

    # 7. End-to-End Forensic Traceability Matrix
    # Trace: CLAIM -> FINDING -> EVIDENCE -> CANONICAL EVENT -> SOURCE RECORD -> PROVENANCE
    trace_matrix = packet.traceability_matrix
    assert len(trace_matrix) >= 3
    for row in trace_matrix:
        assert row["claim_id"].startswith("CLM-")
        assert "finding_id" in row
        assert row["evidence_id"].startswith("EVD-")
        assert row["canonical_event_id"].startswith("EVT_")
        assert row["source_record_id"].startswith("RECORD_")
        assert row["source_file"].endswith(".parquet")
        assert row["provenance_ref"].startswith("ref:evd:")
        assert row["traceability_status"] == "GROUNDED"


def test_deterministic_export_json_and_markdown(workspace_with_forensic_case, tmp_path):
    backend = workspace_with_forensic_case
    engine = ForensicCasePacketEngine(backend)
    export_res = engine.export_packet(FORENSIC_DEMO_CASE_ID, output_dir=str(tmp_path))

    assert os.path.exists(export_res["json_path"])
    assert os.path.exists(export_res["markdown_path"])

    # Verify JSON content
    with open(export_res["json_path"], "r", encoding="utf-8") as f:
        json_data = json.load(f)
    assert json_data["packet_status"] == "CONFLICTED"
    assert json_data["case"]["case_id"] == FORENSIC_DEMO_CASE_ID
    assert len(json_data["traceability_matrix"]) >= 3

    # Verify Markdown content
    with open(export_res["markdown_path"], "r", encoding="utf-8") as f:
        md_text = f.read()
    assert f"# DFAP Forensic Case Dossier: {FORENSIC_DEMO_CASE_ID}" in md_text
    assert "STATUS: CONFLICTED — Material Evidential Disagreement Detected" in md_text
    assert "CLAIM ──▶ FINDING ──▶ EVIDENCE ──▶ CANONICAL EVENT ──▶ SOURCE RECORD ──▶ PROVENANCE" in md_text
    assert "RECORD_FIN_SRC_001" in md_text
    assert "DISCOVERED_MOTIF_005" in md_text or "DISCOVERED_MOTIF_" in md_text


def test_cli_case_forensic_command(workspace_with_forensic_case):
    backend = workspace_with_forensic_case
    output = handle_m13_command(backend, f"case forensic {FORENSIC_DEMO_CASE_ID}")

    assert "FORENSIC CASE PACKET" in output
    assert f"Case: {FORENSIC_DEMO_CASE_ID}" in output
    assert "Status: CONFLICTED" in output
    assert "Findings: 1" in output
    assert "Conflicts: 1" in output or "Conflicts:" in output
    assert "Discovered motifs:" in output
    assert "Exported:" in output
    assert f"CASE_{FORENSIC_DEMO_CASE_ID}_FORENSIC_PACKET.json" in output
    assert f"CASE_{FORENSIC_DEMO_CASE_ID}_FORENSIC_REPORT.md" in output


def test_copilot_forensic_packet_grounded_queries(workspace_with_forensic_case):
    backend = workspace_with_forensic_case
    copilot = InvestigationCopilot(backend)

    # 1. "What is in the forensic case packet?"
    q1 = f"What is in the forensic case packet for {FORENSIC_DEMO_CASE_ID}?"
    resp1 = copilot.ask(q1, case_id=FORENSIC_DEMO_CASE_ID)
    assert resp1["status"] == "CONFLICTED"
    assert "finding" in resp1["answer"].lower()
    assert "evidence" in resp1["answer"].lower()
    assert "timeline" in resp1["answer"].lower()
    assert resp1.get("forensic_packet") is not None

    # 2. "Show me the evidence chain for this finding."
    q2 = f"Show me the evidence chain for finding {FND_FORENSIC_001}"
    resp2 = copilot.ask(q2, case_id=FORENSIC_DEMO_CASE_ID)
    assert resp2["status"] == "CONFLICTED"
    assert "evidence chain" in resp2["answer"].lower()
    assert "canonical event" in resp2["answer"].lower()
    assert EVD_FIN_SUPPORT in resp2["evidence_refs"]

    # 3. "What conflicts exist in this case?"
    q3 = f"What conflicts exist in case {FORENSIC_DEMO_CASE_ID}?"
    resp3 = copilot.ask(q3, case_id=FORENSIC_DEMO_CASE_ID)
    assert resp3["status"] == "CONFLICTED"
    assert "financial" in resp3["answer"].lower()
    assert "social" in resp3["answer"].lower()
    assert "compound conflict" in resp3["answer"].lower()

    # 4. "What provenance supports this conclusion?"
    q4 = f"What provenance supports this conclusion in {FORENSIC_DEMO_CASE_ID}?"
    resp4 = copilot.ask(q4, case_id=FORENSIC_DEMO_CASE_ID)
    assert "provenance ledger" in resp4["answer"].lower() or "lineage" in resp4["answer"].lower()
    assert "integrity" in resp4["answer"].lower()

    # 5. "Prepare the forensic case summary."
    q5 = f"Prepare the forensic case summary for {FORENSIC_DEMO_CASE_ID}."
    resp5 = copilot.ask(q5, case_id=FORENSIC_DEMO_CASE_ID)
    assert resp5["status"] == "CONFLICTED"
    assert "forensic case packet" in resp5["answer"].lower()
