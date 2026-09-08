# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: Test 8 — Contradictory Evidence & Conflict Handling Verification

import pytest
import pandas as pd
from typing import Dict, Any, List

from dfap.investigation.workspace import InvestigationWorkspaceBackend, CaseStatus
from dfap.investigation.copilot import InvestigationCopilot
from dfap.investigation.evidence_provenance import CanonicalEvidenceRecord, EvidenceStatus
from dfap.investigation.cross_domain_fusion import CrossDomainFusionEngine, ConflictStatus
from dfap.investigation.conflict_fixture import (
    CASE_CONFLICT_ID,
    CONFLICT_ENTITY_ID,
    SUPPORT_EVID_ID,
    CONTRA_EVID_ID,
    NEUTRAL_EVID_ID,
    CONFLICT_FINDING_ID,
    SUPPORT_PROV_REF,
    CONTRA_PROV_REF,
    NEUTRAL_PROV_REF,
    create_contradiction_evidence_records,
    run_m11_contradiction_fusion,
    register_contradiction_fixture,
)
from dfap.wp4.cli import handle_m13_command


@pytest.fixture
def workspace_with_conflict():
    """Sets up an InvestigationWorkspaceBackend pre-loaded with the Test 8 conflict fixture."""
    backend = InvestigationWorkspaceBackend(
        output_dir="output",
        canonical_dir="data/canonical",
        cases_dir="data/cases"
    )
    fixture_data = register_contradiction_fixture(backend)
    return backend, fixture_data


# ══════════════════════════════════════════════════════════════════════════════
# 1. FIXTURE INTEGRITY TESTS
# ══════════════════════════════════════════════════════════════════════════════

def test_fixture_evidence_records():
    """Verify the synthetic deterministic evidence records adhere to M12 contracts."""
    records = create_contradiction_evidence_records()
    assert len(records) == 3

    r_map = {r.evidence_id: r for r in records}
    assert SUPPORT_EVID_ID in r_map
    assert CONTRA_EVID_ID in r_map
    assert NEUTRAL_EVID_ID in r_map

    # Supporting record
    supp = r_map[SUPPORT_EVID_ID]
    assert supp.source_domain == "FINANCIAL"
    assert supp.evidence_category == "SUPPORTING"
    assert supp.canonical_entity_ids == [CONFLICT_ENTITY_ID]
    assert supp.metadata.get("anomaly_score") == 0.92
    assert supp.evidence_hash is not None and len(supp.evidence_hash) == 64

    # Contradicting record
    contra = r_map[CONTRA_EVID_ID]
    assert contra.source_domain == "SOCIAL"
    assert contra.evidence_category == "CONTRADICTING"
    assert contra.canonical_entity_ids == [CONFLICT_ENTITY_ID]
    assert contra.metadata.get("anomaly_score") == 0.08
    assert contra.evidence_hash is not None and len(contra.evidence_hash) == 64

    # Neutral record
    neutral = r_map[NEUTRAL_EVID_ID]
    assert neutral.source_domain == "IPDR"
    assert neutral.evidence_category == "CONTEXTUAL"
    assert neutral.metadata.get("anomaly_score") == 0.40


def test_fixture_registration_in_backend(workspace_with_conflict):
    """Verify the fixture registers correctly into the M13 workspace backend."""
    backend, fixture_data = workspace_with_conflict

    # Canonical entity registered
    assert CONFLICT_ENTITY_ID in backend.valid_entities

    # Case registered
    assert CASE_CONFLICT_ID in backend.cases
    case = backend.get_case(CASE_CONFLICT_ID)
    assert case.canonical_entity_id == CONFLICT_ENTITY_ID
    assert CONFLICT_FINDING_ID in case.finding_ids
    assert set(case.evidence_ids) >= {SUPPORT_EVID_ID, CONTRA_EVID_ID, NEUTRAL_EVID_ID}

    # Finding registered
    assert CONFLICT_FINDING_ID in backend.findings_by_id
    fnd = backend.get_finding(CONFLICT_FINDING_ID)
    assert fnd["status"] == "CONFLICTED"
    assert SUPPORT_EVID_ID in fnd["supporting_evidence"]
    assert CONTRA_EVID_ID in fnd["contradicting_evidence"]

    # Provenance graph nodes and edges
    graph = backend.evidence_engine.graph
    assert CONFLICT_FINDING_ID in graph.nodes
    assert any(e["parent_id"] == SUPPORT_EVID_ID and e["child_id"] == CONFLICT_FINDING_ID for e in graph.edges)
    assert any(e["parent_id"] == CONTRA_EVID_ID and e["child_id"] == CONFLICT_FINDING_ID for e in graph.edges)
    assert any(e["parent_id"] == NEUTRAL_EVID_ID and e["child_id"] == CONFLICT_FINDING_ID for e in graph.edges)


# ══════════════════════════════════════════════════════════════════════════════
# 2. M11 CROSS-DOMAIN FUSION CONFLICT RESOLUTION TESTS
# ══════════════════════════════════════════════════════════════════════════════

def test_m11_cross_domain_fusion_conflict_detection():
    """Verify that M11 fusion detects conflict, identifies domains, and penalizes score."""
    fusion_result = run_m11_contradiction_fusion()

    assert fusion_result["conflict_status"] == ConflictStatus.CONFLICTED
    assert "FINANCIAL" in fusion_result["supporting_domains"]
    assert "SOCIAL" in fusion_result["contradicting_domains"]
    assert "IPDR" in fusion_result["abstaining_domains"]

    # Corroboration score must be significantly reduced from raw financial score (0.92)
    score = fusion_result["corroboration_score"]
    assert score < 0.50, f"Expected penalized score < 0.50, got {score}"
    assert score > 0.10, f"Expected non-zero score > 0.10, got {score}"

    # Conflict penalty parameter is active
    assert fusion_result["scoring_parameters"]["thresholds"]["conflict_penalty_weight"] >= 0.25


# ══════════════════════════════════════════════════════════════════════════════
# 3. M13 WORKSPACE CASE ISOLATION TESTS
# ══════════════════════════════════════════════════════════════════════════════

def test_m13_case_isolation(workspace_with_conflict):
    """Verify CASE-CONFLICT-001 is strictly isolated and doesn't leak into clean cases."""
    backend, _ = workspace_with_conflict

    # Create an independent clean case
    clean_entity = "ENT_1F405CAB3F4951DA"
    clean_case = backend.create_case(canonical_entity_id=clean_entity, case_id="CASE-CLEAN-001")

    # Clean case must have no conflict finding or conflict evidence
    assert CONFLICT_FINDING_ID not in clean_case.finding_ids
    assert SUPPORT_EVID_ID not in clean_case.evidence_ids
    assert CONTRA_EVID_ID not in clean_case.evidence_ids

    # Conflicted case must have conflict finding and evidence
    conflict_case = backend.get_case(CASE_CONFLICT_ID)
    assert CONFLICT_FINDING_ID in conflict_case.finding_ids
    assert SUPPORT_EVID_ID in conflict_case.evidence_ids
    assert CONTRA_EVID_ID in conflict_case.evidence_ids


# ══════════════════════════════════════════════════════════════════════════════
# 4. M14 COPILOT 5 GROUNDED CONFLICT QUESTIONS
# ══════════════════════════════════════════════════════════════════════════════

def test_m14_copilot_q1_supporting_evidence_only(workspace_with_conflict):
    """Q1: 'What evidence supports the current hypothesis?' -> supporting evidence ONLY."""
    backend, _ = workspace_with_conflict
    copilot = InvestigationCopilot(backend)

    res = copilot.ask("What evidence supports the current hypothesis?", case_id=CASE_CONFLICT_ID)
    assert res["status"] in ("GROUNDED", "PARTIALLY_GROUNDED")
    ev_refs = res["evidence_refs"]
    assert SUPPORT_EVID_ID in ev_refs, f"Expected {SUPPORT_EVID_ID} in {ev_refs}"
    assert CONTRA_EVID_ID not in ev_refs, f"Contradicting evidence {CONTRA_EVID_ID} must NOT be in Q1 supporting answer"
    assert "FINANCIAL" in res["answer"].upper() or "STRUCTURING" in res["answer"].upper()


def test_m14_copilot_q2_contradicting_evidence_only(workspace_with_conflict):
    """Q2: 'What evidence contradicts the current hypothesis?' -> contradicting evidence ONLY."""
    backend, _ = workspace_with_conflict
    copilot = InvestigationCopilot(backend)

    res = copilot.ask("What evidence contradicts the current hypothesis?", case_id=CASE_CONFLICT_ID)
    assert res["status"] in ("GROUNDED", "PARTIALLY_GROUNDED")
    ev_refs = res["evidence_refs"]
    assert CONTRA_EVID_ID in ev_refs, f"Expected {CONTRA_EVID_ID} in {ev_refs}"
    assert SUPPORT_EVID_ID not in ev_refs, f"Supporting evidence {SUPPORT_EVID_ID} must NOT be in Q2 contradiction answer"
    assert "SOCIAL" in res["answer"].upper() or "BASELINE" in res["answer"].upper() or "COMMUNITY" in res["answer"].upper()


def test_m14_copilot_q3_conflicts_between_evidence(workspace_with_conflict):
    """Q3: 'Are there conflicts between the available evidence?' -> status CONFLICTED, surfaces both domains."""
    backend, _ = workspace_with_conflict
    copilot = InvestigationCopilot(backend)

    res = copilot.ask("Are there conflicts between the available evidence?", case_id=CASE_CONFLICT_ID)
    assert res["status"] == "CONFLICTED"
    ev_refs = res["evidence_refs"]
    assert SUPPORT_EVID_ID in ev_refs, f"Expected {SUPPORT_EVID_ID} in {ev_refs}"
    assert CONTRA_EVID_ID in ev_refs, f"Expected {CONTRA_EVID_ID} in {ev_refs}"
    claims_text = " ".join(c.get("claim", "") for c in res.get("claims", []))
    assert "FINANCIAL" in claims_text or "FINANCIAL" in res["answer"].upper()
    assert "SOCIAL" in claims_text or "SOCIAL" in res["answer"].upper()


def test_m14_copilot_q4_confidence_under_contradiction(workspace_with_conflict):
    """Q4: 'How confident should the investigator be given the conflicting evidence?' -> reduced confidence, CONFLICTED."""
    backend, _ = workspace_with_conflict
    copilot = InvestigationCopilot(backend)

    res = copilot.ask("How confident should the investigator be given the conflicting evidence?", case_id=CASE_CONFLICT_ID)
    assert res["status"] == "CONFLICTED"
    assert res["confidence"] <= 0.45, f"Expected low confidence <= 0.45 due to contradiction, got {res['confidence']}"
    assert "override" in res["answer"].lower() or "cannot override" in res["answer"].lower() or "not averaged away" in res["answer"].lower() or "paper over" in str(res["limitations"]).lower()


def test_m14_copilot_q5_what_should_be_verified_next(workspace_with_conflict):
    """Q5: 'What should be verified next?' -> concrete conflict adjudication steps."""
    backend, _ = workspace_with_conflict
    copilot = InvestigationCopilot(backend)

    res = copilot.ask("What should be verified next?", case_id=CASE_CONFLICT_ID)
    assert res["status"] == "CONFLICTED"
    steps = res.get("verification_steps") or res.get("suggested_next_actions")
    assert steps and len(steps) >= 2
    steps_str = " ".join(steps).lower()
    assert "adjudicate" in steps_str or "discrepancy" in steps_str or "verify" in steps_str or "reconcil" in steps_str


# ══════════════════════════════════════════════════════════════════════════════
# 5. NEGATIVE / ADVERSARIAL TESTS A THROUGH I
# ══════════════════════════════════════════════════════════════════════════════

def test_adversarial_a_support_only_no_conflict():
    """Test A: Supporting evidence only -> no contradiction, unpenalized fusion score."""
    engine = CrossDomainFusionEngine(identity_bridge_path="data/cases/identity_bridge.parquet")
    df_bridge = pd.DataFrame([{
        "case_id": "CASE-TEST-A",
        "canonical_entity_id": "ENT_TEST_A",
        "domain": "FINANCIAL",
        "raw_identifier": "WALLET_TEST_A",
        "mapping_method": "CONTROLLED_CASE_MAPPING",
        "confidence": 0.95,
        "evidence_ref": "ref:bridge_test_a"
    }])
    engine.bridge_df = pd.concat([engine.bridge_df, df_bridge], ignore_index=True)

    items = [{
        "finding_id": "FND_TEST_A",
        "source_domain": "FINANCIAL",
        "raw_identifier": "WALLET_TEST_A",
        "anomaly_score": 0.92,
        "epoch_time": 1700050000.0,
        "event_id": "EVT_A",
        "evidence_ref": "EVID-A"
    }]
    res = engine.fuse_for_entity("ENT_TEST_A", items)
    assert res["conflict_status"] != ConflictStatus.CONFLICTED
    assert "FINANCIAL" in res["supporting_domains"]
    assert len(res["contradicting_domains"]) == 0
    assert res["corroboration_score"] >= 0.70


def test_adversarial_b_contradiction_only():
    """Test B: Contradicting evidence only -> no supporting domains, non-escalated status."""
    engine = CrossDomainFusionEngine(identity_bridge_path="data/cases/identity_bridge.parquet")
    df_bridge = pd.DataFrame([{
        "case_id": "CASE-TEST-B",
        "canonical_entity_id": "ENT_TEST_B",
        "domain": "SOCIAL",
        "raw_identifier": "SO_TEST_B",
        "mapping_method": "CONTROLLED_CASE_MAPPING",
        "confidence": 0.90,
        "evidence_ref": "ref:bridge_test_b"
    }])
    engine.bridge_df = pd.concat([engine.bridge_df, df_bridge], ignore_index=True)

    items = [{
        "finding_id": "FND_TEST_B",
        "source_domain": "SOCIAL",
        "raw_identifier": "SO_TEST_B",
        "anomaly_score": 0.05,
        "epoch_time": 1700050010.0,
        "event_id": "EVT_B",
        "evidence_ref": "EVID-B"
    }]
    res = engine.fuse_for_entity("ENT_TEST_B", items)
    assert len(res["supporting_domains"]) == 0
    assert "SOCIAL" in res["contradicting_domains"]
    assert res["conflict_status"] != ConflictStatus.SUPPORTED


def test_adversarial_c_weak_contradiction_above_threshold():
    """Test C: Second domain score is moderate (0.45), not low enough (<0.25) to trigger CONFLICTED."""
    engine = CrossDomainFusionEngine(identity_bridge_path="data/cases/identity_bridge.parquet")
    df_bridge = pd.DataFrame([
        {
            "case_id": "CASE-TEST-C",
            "canonical_entity_id": "ENT_TEST_C",
            "domain": "FINANCIAL",
            "raw_identifier": "WALLET_TEST_C",
            "mapping_method": "CONTROLLED_CASE_MAPPING",
            "confidence": 0.95,
            "evidence_ref": "ref:bridge_c_fin"
        },
        {
            "case_id": "CASE-TEST-C",
            "canonical_entity_id": "ENT_TEST_C",
            "domain": "SOCIAL",
            "raw_identifier": "SO_TEST_C",
            "mapping_method": "CONTROLLED_CASE_MAPPING",
            "confidence": 0.90,
            "evidence_ref": "ref:bridge_c_soc"
        }
    ])
    engine.bridge_df = pd.concat([engine.bridge_df, df_bridge], ignore_index=True)

    items = [
        {
            "finding_id": "FND_C_FIN",
            "source_domain": "FINANCIAL",
            "raw_identifier": "WALLET_TEST_C",
            "anomaly_score": 0.92,
            "epoch_time": 1700050000.0,
            "event_id": "EVT_C1",
            "evidence_ref": "EVID-C1"
        },
        {
            "finding_id": "FND_C_SOC",
            "source_domain": "SOCIAL",
            "raw_identifier": "SO_TEST_C",
            "anomaly_score": 0.45,
            "epoch_time": 1700050010.0,
            "event_id": "EVT_C2",
            "evidence_ref": "EVID-C2"
        }
    ]
    res = engine.fuse_for_entity("ENT_TEST_C", items)
    assert "SOCIAL" not in res["contradicting_domains"]
    assert res["conflict_status"] != ConflictStatus.CONFLICTED


def test_adversarial_d_unrelated_unmapped_evidence_rejected():
    """Test D: Evidence belonging to unmapped raw_identifier or unknown entity is abstained."""
    engine = CrossDomainFusionEngine(identity_bridge_path="data/cases/identity_bridge.parquet")
    items = [{
        "finding_id": "FND_UNMAPPED",
        "source_domain": "FINANCIAL",
        "raw_identifier": "UNKNOWN_WALLET_999",
        "anomaly_score": 0.99,
        "epoch_time": 1700050000.0,
        "event_id": "EVT_UNMAPPED",
        "evidence_ref": "EVID-UNMAPPED"
    }]
    # ENT_TEST_D has no bridge entry for UNKNOWN_WALLET_999
    res = engine.fuse_for_entity("ENT_TEST_D", items)
    assert res["conflict_status"] in (ConflictStatus.IDENTITY_UNCERTAIN, ConflictStatus.INSUFFICIENT_EVIDENCE)
    assert res["corroboration_score"] == 0.0


def test_adversarial_e_stale_finding_rejected(workspace_with_conflict):
    """Test E: Stale finding from unrelated entity/case is not leaked or used."""
    backend, _ = workspace_with_conflict
    copilot = InvestigationCopilot(backend)

    backend.valid_entities.add("ENT_EMPTY_TEST")
    empty_case = backend.create_case(canonical_entity_id="ENT_EMPTY_TEST", case_id="CASE-EMPTY-001")
    res = copilot.ask("Why was this case flagged?", case_id="CASE-EMPTY-001")
    assert res["status"] == "INSUFFICIENT_EVIDENCE"
    assert res["confidence"] == 0.0
    assert CONFLICT_FINDING_ID not in str(res)
    assert SUPPORT_EVID_ID not in res["evidence_refs"]


def test_adversarial_f_empty_evidence_insufficient_evidence():
    """Test F: Empty evidence items for an authorized bridge entity -> INSUFFICIENT_EVIDENCE with corroboration_score=0.0."""
    engine = CrossDomainFusionEngine(identity_bridge_path="data/cases/identity_bridge.parquet")
    df_bridge = pd.DataFrame([{
        "case_id": CASE_CONFLICT_ID,
        "canonical_entity_id": CONFLICT_ENTITY_ID,
        "domain": "FINANCIAL",
        "raw_identifier": "WALLET_CONFLICT_SUPPORT_001",
        "mapping_method": "CONTROLLED_CASE_MAPPING",
        "confidence": 0.95,
        "evidence_ref": "ref:bridge_conflict_fin"
    }])
    engine.bridge_df = pd.concat([engine.bridge_df, df_bridge], ignore_index=True)

    res = engine.fuse_for_entity(CONFLICT_ENTITY_ID, [])
    assert res["conflict_status"] == ConflictStatus.INSUFFICIENT_EVIDENCE
    assert res["corroboration_score"] == 0.0


def test_adversarial_g_caller_canonical_override_rejected():
    """Test G: Caller-supplied canonical_entity_id alone is not trusted without bridge proof."""
    engine = CrossDomainFusionEngine(identity_bridge_path="data/cases/identity_bridge.parquet")
    df_bridge = pd.DataFrame([{
        "case_id": CASE_CONFLICT_ID,
        "canonical_entity_id": CONFLICT_ENTITY_ID,
        "domain": "FINANCIAL",
        "raw_identifier": "WALLET_CONFLICT_SUPPORT_001",
        "mapping_method": "CONTROLLED_CASE_MAPPING",
        "confidence": 0.95,
        "evidence_ref": "ref:bridge_conflict_fin"
    }])
    engine.bridge_df = pd.concat([engine.bridge_df, df_bridge], ignore_index=True)

    items = [{
        "finding_id": "FND_SPOOF",
        "source_domain": "FINANCIAL",
        "raw_identifier": "SPOOFED_RAW_ID",
        "mapped_canonical_entity_id": CONFLICT_ENTITY_ID,
        "anomaly_score": 0.95,
        "epoch_time": 1700050000.0,
        "event_id": "EVT_SPOOF",
        "evidence_ref": "EVID-SPOOF"
    }]
    res = engine.fuse_for_entity(CONFLICT_ENTITY_ID, items)
    assert res["conflict_status"] == ConflictStatus.INSUFFICIENT_EVIDENCE
    assert res["corroboration_score"] == 0.0


def test_adversarial_h_temporal_future_event_rejected(workspace_with_conflict):
    """Test H: Post-trigger events cannot serve as causal evidence for earlier trigger."""
    backend, _ = workspace_with_conflict
    copilot = InvestigationCopilot(backend)

    res = copilot.ask("Do events after the trigger event justify why it was suspicious?", case_id=CASE_CONFLICT_ID)
    assert "No" in res["answer"]
    assert "strict temporal causality" in res["answer"].lower() or "temporal causality" in res["answer"].lower()


def test_adversarial_i_cli_command_integration(workspace_with_conflict):
    """Test I: CLI command handlers correctly process CASE-CONFLICT-001 and copilot questions."""
    backend, _ = workspace_with_conflict

    case_out = handle_m13_command(backend, "case show CASE-CONFLICT-001")
    assert "CASE-CONFLICT-001" in case_out
    assert CONFLICT_ENTITY_ID in case_out

    fnd_out = handle_m13_command(backend, "finding show FND_CONFLICT_001")
    assert "FND_CONFLICT_001" in fnd_out

    ev_out = handle_m13_command(backend, "evidence show EVID-CONFLICT-SUPPORT-001")
    assert "EVID-CONFLICT-SUPPORT-001" in ev_out

    q1_out = handle_m13_command(backend, 'copilot ask "What evidence supports the current hypothesis?"', active_case_id=CASE_CONFLICT_ID)
    assert SUPPORT_EVID_ID in q1_out
    assert CONTRA_EVID_ID not in q1_out

    q2_out = handle_m13_command(backend, 'copilot ask "What evidence contradicts the current hypothesis?"', active_case_id=CASE_CONFLICT_ID)
    assert CONTRA_EVID_ID in q2_out
    assert SUPPORT_EVID_ID not in q2_out
