# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: End-to-End Test for 4-Domain Forensic Demonstration (M10-M14 Integration)

import json
import os
import pytest

from dfap.investigation.workspace import InvestigationWorkspaceBackend, CaseStatus
from dfap.investigation.four_domain_fixture import (
    register_four_domain_fixture,
    FOUR_DOMAIN_CASE_ID,
    FOUR_DOMAIN_ENTITY_ID,
    FND_4DOM_FUSED,
    EVD_4DOM_FIN,
    EVD_4DOM_CDR,
    EVD_4DOM_SOC,
    EVD_4DOM_IPDR,
    RAW_ID_CDR,
    RAW_ID_IPDR,
    RAW_ID_FIN,
    RAW_ID_SOC,
)
from dfap.wp4.cli import handle_m13_command
from dfap.investigation.copilot import InvestigationCopilot


@pytest.fixture
def backend():
    b = InvestigationWorkspaceBackend()
    register_four_domain_fixture(b)
    return b


def test_four_domain_identity_bridge(backend):
    """Verifies that the canonical entity is authoritatively mapped across all 4 domains with explicit provenance."""
    assert FOUR_DOMAIN_ENTITY_ID in backend.valid_entities
    
    bridge_sub = backend.bridge_df[backend.bridge_df["canonical_entity_id"] == FOUR_DOMAIN_ENTITY_ID]
    assert len(bridge_sub) == 4
    
    domains_mapped = set(bridge_sub["domain"].tolist())
    assert domains_mapped == {"CDR", "IPDR", "FINANCIAL", "SOCIAL"}
    
    # Check that raw identifiers are distinct and mapped with confidence >= 0.85
    for _, row in bridge_sub.iterrows():
        assert row["raw_identifier"] in (RAW_ID_CDR, RAW_ID_IPDR, RAW_ID_FIN, RAW_ID_SOC)
        assert float(row["confidence"]) >= 0.85
        assert str(row["evidence_ref"]).startswith("ref:bridge_")
        assert row["mapping_method"] in (
            "RESOLVED_PHONE_LINK",
            "AUTH_DEVICE_LINK",
            "EXACT_KYC_ACCOUNT",
            "VERIFIED_OAUTH_HANDLE",
        )

    # Aliases resolution must find all raw identifiers
    aliases = backend._resolve_entity_aliases(FOUR_DOMAIN_ENTITY_ID)
    assert RAW_ID_CDR in aliases
    assert RAW_ID_IPDR in aliases
    assert RAW_ID_FIN in aliases
    assert RAW_ID_SOC in aliases


def test_four_domain_timeline_events(backend):
    """Verifies timeline has 16 strictly chronological events spanning all 4 domains."""
    timeline = backend.get_timeline(FOUR_DOMAIN_ENTITY_ID)
    assert len(timeline) == 16

    domains_present = set(e["source_domain"] for e in timeline)
    assert domains_present == {"CDR", "IPDR", "FINANCIAL", "SOCIAL"}

    # Strict chronological monotonicity
    epoch_times = [float(e["epoch_time"]) for e in timeline]
    assert epoch_times == sorted(epoch_times)
    assert all(e["temporal_semantics"] == "OBSERVED_TIMESTAMP" for e in timeline)


def test_four_domain_fusion_and_conflict(backend):
    """Verifies M11 cross-domain fusion detects material evidential conflict and flags HUMAN_REVIEW."""
    finding = backend.get_finding(FND_4DOM_FUSED)
    assert finding["status"] == "CONFLICTED"
    assert finding["domain"] == "CROSS_DOMAIN"
    assert finding["supporting_evidence"] == [EVD_4DOM_FIN, EVD_4DOM_CDR]
    assert finding["contradicting_evidence"] == [EVD_4DOM_SOC]
    assert finding["contextual_evidence"] == [EVD_4DOM_IPDR]

    m11_info = finding["m11_fusion_info"]
    assert m11_info["independent_domain_count"] == 4
    assert m11_info["conflict_status"] == "CONFLICTED"
    assert m11_info["requires_human_review"] is True
    assert m11_info["required_action"] == "HUMAN_REVIEW"

    # Worst pair conflict must be FINANCIAL vs SOCIAL
    ev_conflict = m11_info["evidential_conflict"]
    assert set(ev_conflict["worst_pair"]) == {"FINANCIAL", "SOCIAL"}


def test_four_domain_motif_discovery(backend):
    """Verifies M10 Unsupervised Motif Discovery extracts the cross-domain recurring behavioral subsequence."""
    motifs = backend.discover_sequence_motifs(FOUR_DOMAIN_ENTITY_ID, min_length=3, max_length=4)
    assert len(motifs) >= 1

    # At least one motif must span all 4 domains
    multi_domain = [m for m in motifs if len(set(m.representative_domains)) == 4]
    assert len(multi_domain) >= 1
    target = multi_domain[0]
    assert target.cluster_size >= 3
    assert set(target.representative_domains) == {"CDR", "IPDR", "FINANCIAL", "SOCIAL"}


def test_four_domain_forensic_packet_generation_and_export(backend, tmp_path):
    """Verifies deterministic synthesis of forensic packet, digest, and export."""
    packet = backend.generate_forensic_packet(FOUR_DOMAIN_CASE_ID)
    assert packet.packet_status == "CONFLICTED"
    assert packet.required_action == "HUMAN_REVIEW"
    assert len(packet.traceability_matrix) == 4
    assert packet.packet_digest is not None
    assert len(packet.packet_digest) == 64  # Valid SHA-256

    # Test export
    out_dir = str(tmp_path / "forensic_export")
    paths = backend.export_forensic_packet(FOUR_DOMAIN_CASE_ID, output_dir=out_dir)
    assert os.path.exists(paths["json_path"])
    assert os.path.exists(paths["markdown_path"])

    with open(paths["json_path"], "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["packet_status"] == "CONFLICTED"
    assert data["required_action"] == "HUMAN_REVIEW"
    assert len(data["traceability_matrix"]) == 4


def test_four_domain_cli_commands(backend):
    """Verifies M13 CLI commands: case show, case forensic, timeline, finding show, evidence show."""
    # 1. case show
    out_case = handle_m13_command(backend, f"case show {FOUR_DOMAIN_CASE_ID}")
    assert FOUR_DOMAIN_CASE_ID in out_case
    assert FOUR_DOMAIN_ENTITY_ID in out_case

    # 2. case forensic
    out_forensic = handle_m13_command(backend, f"case forensic {FOUR_DOMAIN_CASE_ID}")
    assert "FORENSIC CASE PACKET" in out_forensic
    assert "Status: CONFLICTED" in out_forensic
    assert "Domains: CDR, CROSS_DOMAIN, FINANCIAL, IPDR, SOCIAL" in out_forensic

    # 3. timeline
    out_timeline = handle_m13_command(backend, f"timeline {FOUR_DOMAIN_ENTITY_ID}")
    assert "TIMELINE ENT_DFAP_4DOM_001" in out_timeline
    assert "EVT_4DOM_001" in out_timeline

    # 4. finding show
    out_finding = handle_m13_command(backend, f"finding show {FND_4DOM_FUSED}")
    assert FND_4DOM_FUSED in out_finding
    assert "CONFLICTED" in out_finding

    # 5. evidence show
    out_ev = handle_m13_command(backend, f"evidence show {EVD_4DOM_FIN}")
    assert EVD_4DOM_FIN in out_ev
    assert "STRUCTURING_ANOMALY_DETECTOR" in out_ev


def test_four_domain_copilot_8_questions(backend):
    """Verifies all 8 required Copilot queries answer truthfully, grounded in evidence, with no guilt claims."""
    copilot = InvestigationCopilot(backend)
    cid = FOUR_DOMAIN_CASE_ID
    eid = FOUR_DOMAIN_ENTITY_ID

    # Q1: Status of this case
    r1 = copilot.ask("What is the status of this case?", case_id=cid, entity_id=eid)
    assert "OPEN" in r1["answer"]
    assert "CONFLICTED" in r1["answer"]
    assert "HUMAN_REVIEW" in r1["answer"]

    # Q2: Forensic case packet report
    r2 = copilot.ask("What does the forensic case packet report?", case_id=cid, entity_id=eid)
    assert r2["status"] == "CONFLICTED"
    assert "HUMAN_REVIEW" in r2["answer"]
    assert "16 timeline event(s)" in r2["answer"]

    # Q3: Which domains contribute evidence
    r3 = copilot.ask("Which domains contribute evidence?", case_id=cid, entity_id=eid)
    for d in ["CDR", "FINANCIAL", "IPDR", "SOCIAL"]:
        assert d in r3["answer"]

    # Q4: How is canonical entity mapped across raw domain identifiers
    r4 = copilot.ask("How is the canonical entity mapped across raw domain identifiers?", case_id=cid, entity_id=eid)
    for raw in [RAW_ID_CDR, RAW_ID_IPDR, RAW_ID_FIN, RAW_ID_SOC]:
        assert raw in r4["answer"]
    assert "never blindly equated" in r4["answer"]

    # Q5: What evidential conflict exists in this case
    r5 = copilot.ask("What evidential conflict exists in this case?", case_id=cid, entity_id=eid)
    assert r5["status"] == "CONFLICTED"
    assert "FINANCIAL" in r5["answer"]
    assert "SOCIAL" in r5["answer"]
    assert "Hellinger distance" in r5["answer"] or "compound conflict" in r5["answer"]

    # Q6: What temporal motifs were discovered
    r6 = copilot.ask("What temporal motifs were discovered?", case_id=cid, entity_id=eid)
    assert "discovered a recurring temporal subsequence" in r6["answer"] or "DISCOVERED_MOTIF" in r6["answer"]

    # Q7: What is the recommended next action
    r7 = copilot.ask("What is the recommended next action?", case_id=cid, entity_id=eid)
    assert "HUMAN_REVIEW" in r7["answer"] or "adjudicating the contradiction" in r7["answer"]

    # Q8: Can you prove the suspect is guilty
    r8 = copilot.ask("Can you prove the suspect is guilty?", case_id=cid, entity_id=eid)
    assert "No." in r8["answer"]
    assert "does not assert criminal guilt" in r8["answer"]
    assert "human investigator review is required" in r8["answer"]
