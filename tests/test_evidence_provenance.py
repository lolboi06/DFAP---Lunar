# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: M12 Comprehensive Adversarial Test Suite (Tests A through O)

import copy
import json
import pytest
import numpy as np

from dfap.investigation.evidence_provenance import (
    CanonicalEvidenceRecord,
    EvidenceProvenanceEngine,
    EvidenceType,
    EvidenceStatus,
    ProvenanceIntegrityStatus
)
from dfap.investigation.cross_domain_fusion import CrossDomainFusionEngine


@pytest.fixture
def engine():
    return EvidenceProvenanceEngine()


def test_test_a_valid_evidence_chain_accepted(engine):
    """
    TEST A: valid evidence chain accepted.
    A complete lineage DAG: SOURCE_RECORD -> CANONICAL_EVENT -> FEATURE_RECORD -> ANOMALY_FINDING
    is registered and verified with cryptographic integrity.
    """
    # 1. Source record
    ev_src = CanonicalEvidenceRecord(
        evidence_type=EvidenceType.SOURCE_RECORD,
        source_domain="FINANCIAL",
        source_id="RAW_TX_101",
        source_file="data/sources/elliptic/tx.csv",
        source_row_index=101,
        canonical_entity_ids=["ENT_ALPHA"],
        event_ids=["EVT_TX_101"],
        observation_timestamp="2020-01-01T12:00:00Z",
        ingestion_timestamp="2020-01-01T12:05:00Z",
        derivation_method="SOURCE_INGESTION"
    )
    engine.register_evidence(ev_src)

    # 2. Canonical event
    ev_evt = CanonicalEvidenceRecord(
        evidence_type=EvidenceType.CANONICAL_EVENT,
        source_domain="FINANCIAL",
        source_id="EVT_TX_101",
        source_file="data/canonical/financial_canonical.parquet",
        source_row_index=42,
        canonical_entity_ids=["ENT_ALPHA"],
        event_ids=["EVT_TX_101"],
        observation_timestamp="2020-01-01T12:00:00Z",
        ingestion_timestamp="2020-01-01T12:05:00Z",
        derivation_method="SCHEMA_NORMALIZATION",
        parent_evidence_ids=[ev_src.evidence_id]
    )
    engine.register_evidence(ev_evt)

    # 3. Anomaly finding
    ev_fnd = CanonicalEvidenceRecord(
        evidence_type=EvidenceType.ANOMALY_FINDING,
        source_domain="FINANCIAL",
        source_id="FND_FIN_001",
        source_file="output/m3/findings/findings.parquet",
        source_row_index=5,
        canonical_entity_ids=["ENT_ALPHA"],
        event_ids=["EVT_TX_101"],
        observation_timestamp="2020-01-01T12:00:00Z",
        ingestion_timestamp="2020-01-01T12:05:00Z",
        derivation_method="ISOLATION_FOREST_DETECTION",
        parent_evidence_ids=[ev_evt.evidence_id]
    )
    engine.register_evidence(ev_fnd)

    engine.bind_finding_to_evidence("FND_FIN_001", "ENT_ALPHA", [ev_fnd.evidence_id])

    res = engine.verify_integrity(ev_fnd.evidence_id)
    assert res["is_valid"] is True
    assert res["status"] == ProvenanceIntegrityStatus.INTEGRITY_VERIFIED

    prov = engine.get_finding_provenance("FND_FIN_001")
    assert prov["evidence_count"] == 1
    # Upstream from finding node traverses: ev_fnd -> ev_evt -> ev_src (3 nodes)
    assert len(engine.get_upstream_lineage("FND_FIN_001")) == 3


def test_test_b_missing_provenance_rejected(engine):
    """
    TEST B: missing provenance rejected.
    Findings cannot exist without explicit evidence references.
    """
    with pytest.raises(ValueError) as exc:
        engine.bind_finding_to_evidence("FND_ORPHAN", "ENT_ALPHA", [])
    assert "cannot exist without evidence references" in str(exc.value)


def test_test_c_broken_parent_reference_rejected(engine):
    """
    TEST C: broken parent reference rejected.
    Evidence declaring an unregistered parent evidence ID fails closed.
    """
    broken_child = CanonicalEvidenceRecord(
        evidence_type=EvidenceType.FEATURE_RECORD,
        source_domain="TELECOM",
        source_id="FEAT_01",
        source_file="data/features.parquet",
        source_row_index=1,
        canonical_entity_ids=["ENT_ALPHA"],
        event_ids=["EVT_01"],
        observation_timestamp="2020-01-01T00:00:00Z",
        ingestion_timestamp="2020-01-01T00:05:00Z",
        derivation_method="FEATURE_EXTRACTION",
        parent_evidence_ids=["EVD-NON-EXISTENT-PARENT"]
    )
    with pytest.raises(ValueError) as exc:
        engine.register_evidence(broken_child)
    assert "parent evidence EVD-NON-EXISTENT-PARENT is not registered" in str(exc.value)


def test_test_d_tampered_evidence_hash_detected(engine):
    """
    TEST D: tampered evidence hash detected.
    Mutating any payload field triggers TAMPERED_RECORD_DETECTED.
    """
    ev = CanonicalEvidenceRecord(
        evidence_type=EvidenceType.SOURCE_RECORD,
        source_domain="SOCIAL",
        source_id="SO_POST_1",
        source_file="data/posts.csv",
        source_row_index=10,
        canonical_entity_ids=["ENT_ALPHA"],
        event_ids=["EVT_SO_1"],
        observation_timestamp="2020-01-01T00:00:00Z",
        ingestion_timestamp="2020-01-01T00:05:00Z",
        derivation_method="RAW_EXTRACT"
    )
    engine.register_evidence(ev)

    # Tamper with record payload in memory
    ev.source_file = "data/tampered_file.csv"
    res = engine.verify_integrity(ev)
    assert res["is_valid"] is False
    assert res["status"] == ProvenanceIntegrityStatus.TAMPERED_RECORD_DETECTED


def test_test_e_foreign_entity_evidence_rejected(engine):
    """
    TEST E: foreign entity evidence rejected.
    Evidence bound to Entity B cannot be assigned to an Entity A finding.
    """
    ev_b = CanonicalEvidenceRecord(
        evidence_type=EvidenceType.CANONICAL_EVENT,
        source_domain="FINANCIAL",
        source_id="EVT_B",
        source_file="data/fin.parquet",
        source_row_index=1,
        canonical_entity_ids=["ENT_BETA"],  # Belongs to ENT_BETA
        event_ids=["EVT_B"],
        observation_timestamp="2020-01-01T00:00:00Z",
        ingestion_timestamp="2020-01-01T00:05:00Z",
        derivation_method="RAW_EXTRACT"
    )
    engine.register_evidence(ev_b)

    with pytest.raises(ValueError) as exc:
        engine.bind_finding_to_evidence("FND_ALPHA_01", "ENT_ALPHA", [ev_b.evidence_id])
    assert "Entity Mismatch" in str(exc.value)


def test_test_f_event_evidence_mismatch_rejected(engine):
    """
    TEST F: event/evidence mismatch rejected.
    Unregistered evidence IDs cannot be bound to findings.
    """
    with pytest.raises(ValueError) as exc:
        engine.bind_finding_to_evidence("FND_MISMATCH", "ENT_ALPHA", ["EVD-NON-EXISTENT-EVT"])
    assert "Missing Provenance" in str(exc.value)


def test_test_g_future_evidence_cannot_support_past_finding():
    """
    TEST G: future evidence cannot support past finding.
    Verifies that evidence occurring after observation cutoff is rejected from historical lineage.
    """
    fusion_engine = CrossDomainFusionEngine()
    t_past = 1421980000.0
    t_future = t_past + (30 * 86400.0)  # +30 days in future

    past_items = [
        {"finding_id": "F1", "source_domain": "TELECOM", "raw_identifier": "IP_10.0.1.1", "anomaly_score": 0.85, "epoch_time": t_past, "event_id": "E1", "evidence_ref": "ref:1"},
        {"finding_id": "F_FUTURE", "source_domain": "TELECOM", "raw_identifier": "IP_10.0.1.1", "anomaly_score": 0.99, "epoch_time": t_future, "event_id": "E_FUT", "evidence_ref": "ref:fut"}
    ]
    fused = fusion_engine.fuse_for_entity("ENT_CROSS_SYNDICATE_ALPHA", domain_evidence_items=past_items, temporal_window_name="TIGHT")
    assert "E_FUT" not in fused["trigger_events"]


def test_test_h_duplicate_evidence_does_not_create_duplicate_lineage(engine):
    """
    TEST H: duplicate evidence does not create duplicate lineage.
    Idempotent registration returns existing record and does not duplicate graph nodes.
    """
    ev = CanonicalEvidenceRecord(
        evidence_type=EvidenceType.SOURCE_RECORD,
        source_domain="IPDR",
        source_id="IP_ROW_1",
        source_file="data/ipdr.csv",
        source_row_index=5,
        canonical_entity_ids=["ENT_ALPHA"],
        event_ids=["EVT_IP_1"],
        observation_timestamp="2020-01-01T00:00:00Z",
        ingestion_timestamp="2020-01-01T00:05:00Z",
        derivation_method="RAW_EXTRACT"
    )
    reg1 = engine.register_evidence(ev)
    reg2 = engine.register_evidence(ev)
    assert reg1.evidence_id == reg2.evidence_id
    assert len(engine.evidence_store) == 1
    assert len(engine.graph.nodes) == 1


def test_test_i_conflicting_evidence_preserved_not_overwritten(engine):
    """
    TEST I: conflicting evidence is preserved, not overwritten.
    A finding retains both SUPPORTING and CONTRADICTING evidence.
    """
    ev_sup = CanonicalEvidenceRecord(
        evidence_type=EvidenceType.FEATURE_RECORD,
        source_domain="TELECOM",
        source_id="FEAT_HIGH_ANOMALY",
        source_file="data/features.parquet",
        source_row_index=1,
        canonical_entity_ids=["ENT_ALPHA"],
        event_ids=["EVT_1"],
        observation_timestamp="2020-01-01T00:00:00Z",
        ingestion_timestamp="2020-01-01T00:05:00Z",
        derivation_method="ANOMALY_FEATURE",
        evidence_category="SUPPORTING"
    )
    ev_con = CanonicalEvidenceRecord(
        evidence_type=EvidenceType.FEATURE_RECORD,
        source_domain="FINANCIAL",
        source_id="FEAT_NORMAL_BASELINE",
        source_file="data/features.parquet",
        source_row_index=2,
        canonical_entity_ids=["ENT_ALPHA"],
        event_ids=["EVT_2"],
        observation_timestamp="2020-01-01T00:00:00Z",
        ingestion_timestamp="2020-01-01T00:05:00Z",
        derivation_method="BASELINE_FEATURE",
        evidence_category="CONTRADICTING"
    )
    engine.register_evidence(ev_sup)
    engine.register_evidence(ev_con)

    engine.bind_finding_to_evidence("FND_CONFLICT", "ENT_ALPHA", [ev_sup.evidence_id, ev_con.evidence_id])

    prov = engine.get_finding_provenance("FND_CONFLICT")
    assert len(prov["supporting_evidence"]) == 1
    assert len(prov["contradicting_evidence"]) == 1
    assert prov["supporting_evidence"][0]["evidence_id"] == ev_sup.evidence_id
    assert prov["contradicting_evidence"][0]["evidence_id"] == ev_con.evidence_id


def test_test_j_provenance_survives_serialization_deserialization(engine):
    """
    TEST J: provenance survives serialization/deserialization.
    JSON export and re-import preserves 100% byte and hash integrity.
    """
    ev = CanonicalEvidenceRecord(
        evidence_type=EvidenceType.SOURCE_RECORD,
        source_domain="FINANCIAL",
        source_id="TX_SERIAL_01",
        source_file="data/sources/elliptic/tx.csv",
        source_row_index=999,
        canonical_entity_ids=["ENT_ALPHA"],
        event_ids=["EVT_999"],
        observation_timestamp="2020-01-01T00:00:00Z",
        ingestion_timestamp="2020-01-01T00:05:00Z",
        derivation_method="DIRECT"
    )
    d = ev.to_dict()
    json_str = json.dumps(d)

    deserialized_data = json.loads(json_str)
    reconstructed_ev = CanonicalEvidenceRecord.from_dict(deserialized_data)

    assert reconstructed_ev.evidence_id == ev.evidence_id
    assert reconstructed_ev.evidence_hash == ev.evidence_hash
    assert reconstructed_ev.verify_self_hash() is True


def test_test_k_same_inputs_produce_deterministic_provenance():
    """
    TEST K: same inputs/config produce deterministic provenance.
    Creating evidence records with same inputs yields identical hash and ID.
    """
    params = {
        "evidence_type": EvidenceType.CANONICAL_EVENT,
        "source_domain": "TELECOM",
        "source_id": "DETERMINISTIC_EVT_1",
        "source_file": "data/canonical/telecom.parquet",
        "source_row_index": 55,
        "canonical_entity_ids": ["ENT_ALPHA"],
        "event_ids": ["EVT_55"],
        "observation_timestamp": "2020-01-01T00:00:00Z",
        "ingestion_timestamp": "2020-01-01T00:05:00Z",
        "derivation_method": "DETERMINISTIC_MAP"
    }
    ev1 = CanonicalEvidenceRecord(**params)
    ev2 = CanonicalEvidenceRecord(**params)

    assert ev1.evidence_hash == ev2.evidence_hash
    assert ev1.evidence_id == ev2.evidence_id


def test_test_l_changing_upstream_evidence_changes_verification_status(engine):
    """
    TEST L: changing an upstream evidence record changes verification status.
    Tampering with a parent record flips child status to BROKEN_PROVENANCE_CHAIN.
    """
    ev_parent = CanonicalEvidenceRecord(
        evidence_type=EvidenceType.SOURCE_RECORD,
        source_domain="FINANCIAL",
        source_id="PARENT_1",
        source_file="data/parent.csv",
        source_row_index=1,
        canonical_entity_ids=["ENT_ALPHA"],
        event_ids=["EVT_P1"],
        observation_timestamp="2020-01-01T00:00:00Z",
        ingestion_timestamp="2020-01-01T00:05:00Z",
        derivation_method="PARENT_INGEST"
    )
    engine.register_evidence(ev_parent)

    ev_child = CanonicalEvidenceRecord(
        evidence_type=EvidenceType.FEATURE_RECORD,
        source_domain="FINANCIAL",
        source_id="CHILD_1",
        source_file="data/child.parquet",
        source_row_index=2,
        canonical_entity_ids=["ENT_ALPHA"],
        event_ids=["EVT_C1"],
        observation_timestamp="2020-01-01T00:00:00Z",
        ingestion_timestamp="2020-01-01T00:05:00Z",
        derivation_method="CHILD_DERIVATION",
        parent_evidence_ids=[ev_parent.evidence_id]
    )
    engine.register_evidence(ev_child)

    # Initial state is verified
    assert engine.verify_integrity(ev_child.evidence_id)["is_valid"] is True

    # Tamper with parent in store
    engine.evidence_store[ev_parent.evidence_id].source_file = "data/tampered_parent.csv"

    # Child verification fails with BROKEN_PROVENANCE_CHAIN
    res = engine.verify_integrity(ev_child.evidence_id)
    assert res["is_valid"] is False
    assert res["status"] == ProvenanceIntegrityStatus.BROKEN_PROVENANCE_CHAIN


def test_test_m_m11_fused_findings_retain_all_contributing_evidence(engine):
    """
    TEST M: M11 fused findings retain all contributing evidence.
    Fused finding retains distinct evidence across Telecom, Financial, and Social domains.
    """
    entity = "ENT_CROSS_SYNDICATE_ALPHA"
    ev_tel = CanonicalEvidenceRecord(
        evidence_type=EvidenceType.ANOMALY_FINDING,
        source_domain="TELECOM",
        source_id="FND_TEL_01",
        source_file="output/m3/findings/findings.parquet",
        source_row_index=10,
        canonical_entity_ids=[entity],
        event_ids=["EVT_TEL_01"],
        observation_timestamp="2015-01-23T00:00:00Z",
        ingestion_timestamp="2015-01-23T00:05:00Z",
        derivation_method="TELECOM_ANOMALY"
    )
    ev_fin = CanonicalEvidenceRecord(
        evidence_type=EvidenceType.ANOMALY_FINDING,
        source_domain="FINANCIAL",
        source_id="FND_FIN_01",
        source_file="output/m3/findings/findings.parquet",
        source_row_index=11,
        canonical_entity_ids=[entity],
        event_ids=["EVT_FIN_01"],
        observation_timestamp="2015-01-23T00:01:00Z",
        ingestion_timestamp="2015-01-23T00:05:00Z",
        derivation_method="FINANCIAL_ANOMALY"
    )
    ev_soc = CanonicalEvidenceRecord(
        evidence_type=EvidenceType.ANOMALY_FINDING,
        source_domain="SOCIAL",
        source_id="FND_SOC_01",
        source_file="output/m3/findings/findings.parquet",
        source_row_index=12,
        canonical_entity_ids=[entity],
        event_ids=["EVT_SOC_01"],
        observation_timestamp="2015-01-23T00:02:00Z",
        ingestion_timestamp="2015-01-23T00:05:00Z",
        derivation_method="SOCIAL_ANOMALY"
    )
    engine.register_evidence(ev_tel)
    engine.register_evidence(ev_fin)
    engine.register_evidence(ev_soc)

    engine.bind_finding_to_evidence(
        "FUS_CASE_01",
        entity,
        [ev_tel.evidence_id, ev_fin.evidence_id, ev_soc.evidence_id]
    )

    fused_prov = engine.get_finding_provenance("FUS_CASE_01")
    assert fused_prov["evidence_count"] == 3
    domains = [e["source_domain"] for e in fused_prov["all_evidence"]]
    assert set(domains) == {"TELECOM", "FINANCIAL", "SOCIAL"}


def test_test_n_unknown_timestamp_not_converted_to_fabricated_calendar_time():
    """
    TEST N: UNKNOWN_TIMESTAMP is not converted into fabricated calendar time.
    Explicitly stores UNKNOWN_TIMESTAMP without clock invention.
    """
    ev = CanonicalEvidenceRecord(
        evidence_type=EvidenceType.CANONICAL_EVENT,
        source_domain="IPDR",
        source_id="EVT_UNKNOWN_TS",
        source_file="data/unknown_source.csv",
        source_row_index=1,
        canonical_entity_ids=["ENT_ALPHA"],
        event_ids=["EVT_U"],
        observation_timestamp=None,
        ingestion_timestamp="2020-01-01T00:00:00Z",
        derivation_method="NO_TIMESTAMP_INGEST",
        temporal_semantics="UNKNOWN_TIMESTAMP"
    )
    assert ev.observation_timestamp is None
    assert ev.temporal_semantics == "UNKNOWN_TIMESTAMP"
    d = ev.to_dict()
    assert d["observation_timestamp"] is None


def test_test_o_sequence_order_surrogate_explicitly_labeled():
    """
    TEST O: SEQUENCE_ORDER_SURROGATE is explicitly labeled.
    UNSW surrogate sequence offset is never labeled as an observed timestamp.
    """
    ev = CanonicalEvidenceRecord(
        evidence_type=EvidenceType.CANONICAL_EVENT,
        source_domain="IPDR",
        source_id="EVT_UNSW_45000",
        source_file="data/sources/unsw_nb15/unsw_nb15_training-set.csv",
        source_row_index=45000,
        canonical_entity_ids=["FLOW_45000"],
        event_ids=["EVT_UNSW_45000"],
        observation_timestamp="45000",  # Sequence index
        ingestion_timestamp="2026-09-01T00:00:00Z",
        derivation_method="SEQUENCE_ORDER_SURROGATE",
        temporal_semantics="SEQUENCE_ORDER_SURROGATE"
    )
    assert ev.temporal_semantics == "SEQUENCE_ORDER_SURROGATE"
    assert ev.to_dict()["temporal_semantics"] == "SEQUENCE_ORDER_SURROGATE"


# =========================================================================
# M12 FIX #3: ADVERSARIAL TESTS P1 THROUGH P20
# =========================================================================

# --- BLOCKER 1: Enforce True DAG Semantics ---

def test_p1_direct_self_cycle_rejected(engine):
    """P1: direct self-cycle rejected."""
    engine.graph.add_node("NODE_A", EvidenceType.CANONICAL_EVENT, "FINANCIAL", {})
    with pytest.raises(ValueError) as exc:
        engine.graph.add_edge("NODE_A", "NODE_A", "DERIVED_FROM", "DIRECT")
    assert "direct self-loop" in str(exc.value)


def test_p2_two_node_cycle_rejected(engine):
    """P2: two-node cycle rejected (A -> B, then B -> A)."""
    engine.graph.add_node("NODE_A", EvidenceType.CANONICAL_EVENT, "FINANCIAL", {})
    engine.graph.add_node("NODE_B", EvidenceType.FEATURE_RECORD, "FINANCIAL", {})
    engine.graph.add_edge("NODE_A", "NODE_B", "DERIVED_FROM", "EXTRACT")

    with pytest.raises(ValueError) as exc:
        engine.graph.add_edge("NODE_B", "NODE_A", "DERIVED_FROM", "INVALID_CYCLE")
    assert "Cycle detected" in str(exc.value)


def test_p3_three_node_cycle_rejected(engine):
    """P3: three-node cycle rejected (A -> B -> C, then C -> A)."""
    engine.graph.add_node("NODE_A", EvidenceType.SOURCE_RECORD, "TELECOM", {})
    engine.graph.add_node("NODE_B", EvidenceType.CANONICAL_EVENT, "TELECOM", {})
    engine.graph.add_node("NODE_C", EvidenceType.FEATURE_RECORD, "TELECOM", {})

    engine.graph.add_edge("NODE_A", "NODE_B", "DERIVED_FROM", "NORM")
    engine.graph.add_edge("NODE_B", "NODE_C", "DERIVED_FROM", "FEAT")

    with pytest.raises(ValueError) as exc:
        engine.graph.add_edge("NODE_C", "NODE_A", "DERIVED_FROM", "CYCLE_BACK")
    assert "Cycle detected" in str(exc.value)


def test_p4_valid_dag_remains_accepted(engine):
    """P4: valid DAG (diamond structure: A -> B, A -> C, B -> D, C -> D) remains accepted."""
    for nid in ["A", "B", "C", "D"]:
        engine.graph.add_node(nid, EvidenceType.FEATURE_RECORD, "FINANCIAL", {})

    engine.graph.add_edge("A", "B", "REL", "M")
    engine.graph.add_edge("A", "C", "REL", "M")
    engine.graph.add_edge("B", "D", "REL", "M")
    engine.graph.add_edge("C", "D", "REL", "M")

    assert len(engine.graph.edges) == 4
    upstream_d = engine.graph.get_upstream_path("D")
    upstream_ids = [n["node_id"] for n in upstream_d]
    assert set(upstream_ids) == {"A", "B", "C"}


# --- BLOCKER 2: Truly Recursive Integrity Verification ---

def test_p5_tampered_grandparent_invalidates_child(engine):
    """P5: tampered grandparent invalidates child (G -> P -> C)."""
    g = CanonicalEvidenceRecord(
        evidence_type=EvidenceType.SOURCE_RECORD,
        source_domain="FINANCIAL",
        source_id="G1",
        source_file="data/source.csv",
        source_row_index=1,
        canonical_entity_ids=["ENT_1"],
        event_ids=["EVT_1"],
        observation_timestamp="2020-01-01T00:00:00Z",
        ingestion_timestamp="2020-01-01T00:05:00Z",
        derivation_method="SOURCE"
    )
    p = CanonicalEvidenceRecord(
        evidence_type=EvidenceType.CANONICAL_EVENT,
        source_domain="FINANCIAL",
        source_id="P1",
        source_file="data/canon.parquet",
        source_row_index=1,
        canonical_entity_ids=["ENT_1"],
        event_ids=["EVT_1"],
        observation_timestamp="2020-01-01T00:00:00Z",
        ingestion_timestamp="2020-01-01T00:05:00Z",
        derivation_method="CANON",
        parent_evidence_ids=[g.evidence_id]
    )
    engine.register_evidence(g)
    engine.register_evidence(p)

    c = CanonicalEvidenceRecord(
        evidence_type=EvidenceType.FEATURE_RECORD,
        source_domain="FINANCIAL",
        source_id="C1",
        source_file="data/feat.parquet",
        source_row_index=1,
        canonical_entity_ids=["ENT_1"],
        event_ids=["EVT_1"],
        observation_timestamp="2020-01-01T00:00:00Z",
        ingestion_timestamp="2020-01-01T00:05:00Z",
        derivation_method="FEAT",
        parent_evidence_ids=[p.evidence_id]
    )
    engine.register_evidence(c)

    # Initial state is verified
    assert engine.verify_integrity(c.evidence_id)["is_valid"] is True

    # Tamper with grandparent directly in internal store
    engine.evidence_store[g.evidence_id].source_file = "data/tampered_g.csv"

    res = engine.verify_integrity(c.evidence_id)
    assert res["is_valid"] is False
    assert res["status"] == ProvenanceIntegrityStatus.BROKEN_PROVENANCE_CHAIN
    assert res["broken_ancestor_id"] == g.evidence_id


def test_p6_missing_grandparent_invalidates_descendant(engine):
    """P6: missing grandparent invalidates descendant."""
    g = CanonicalEvidenceRecord(
        evidence_type=EvidenceType.SOURCE_RECORD,
        source_domain="FINANCIAL",
        source_id="G2",
        source_file="data/source2.csv",
        source_row_index=2,
        canonical_entity_ids=["ENT_1"],
        event_ids=["EVT_2"],
        observation_timestamp="2020-01-01T00:00:00Z",
        ingestion_timestamp="2020-01-01T00:05:00Z",
        derivation_method="SOURCE"
    )
    p = CanonicalEvidenceRecord(
        evidence_type=EvidenceType.CANONICAL_EVENT,
        source_domain="FINANCIAL",
        source_id="P2",
        source_file="data/canon2.parquet",
        source_row_index=2,
        canonical_entity_ids=["ENT_1"],
        event_ids=["EVT_2"],
        observation_timestamp="2020-01-01T00:00:00Z",
        ingestion_timestamp="2020-01-01T00:05:00Z",
        derivation_method="CANON",
        parent_evidence_ids=[g.evidence_id]
    )
    engine.register_evidence(g)
    engine.register_evidence(p)

    c = CanonicalEvidenceRecord(
        evidence_type=EvidenceType.FEATURE_RECORD,
        source_domain="FINANCIAL",
        source_id="C2",
        source_file="data/feat2.parquet",
        source_row_index=2,
        canonical_entity_ids=["ENT_1"],
        event_ids=["EVT_2"],
        observation_timestamp="2020-01-01T00:00:00Z",
        ingestion_timestamp="2020-01-01T00:05:00Z",
        derivation_method="FEAT",
        parent_evidence_ids=[p.evidence_id]
    )
    engine.register_evidence(c)

    # Delete grandparent from store
    del engine.evidence_store[g.evidence_id]

    res = engine.verify_integrity(c.evidence_id)
    assert res["is_valid"] is False
    assert res["status"] == ProvenanceIntegrityStatus.MISSING_PARENT_EVIDENCE
    assert res["broken_ancestor_id"] == g.evidence_id


def test_p7_four_plus_level_valid_chain_fully_verifies(engine):
    """P7: 4+ level valid chain (L1 -> L2 -> L3 -> L4 -> L5) fully verifies."""
    prev_id = None
    records = []
    for level in range(1, 6):
        rec = CanonicalEvidenceRecord(
            evidence_type=EvidenceType.FEATURE_RECORD if level > 1 else EvidenceType.SOURCE_RECORD,
            source_domain="TELECOM",
            source_id=f"LEV_{level}",
            source_file=f"data/level_{level}.parquet",
            source_row_index=level,
            canonical_entity_ids=["ENT_CHAIN"],
            event_ids=["EVT_CHAIN"],
            observation_timestamp="2020-01-01T00:00:00Z",
            ingestion_timestamp="2020-01-01T00:05:00Z",
            derivation_method=f"LEVEL_{level}",
            parent_evidence_ids=[prev_id] if prev_id else []
        )
        engine.register_evidence(rec)
        prev_id = rec.evidence_id
        records.append(rec)

    res = engine.verify_integrity(records[-1].evidence_id)
    assert res["is_valid"] is True
    assert res["status"] == ProvenanceIntegrityStatus.INTEGRITY_VERIFIED
    assert res["ancestors_verified_count"] == 4


def test_p8_deep_chain_with_one_broken_ancestor_reports_failure(engine):
    """P8: deep chain with one broken ancestor at Level 2 reports failure with broken_ancestor_id."""
    prev_id = None
    records = []
    for level in range(1, 6):
        rec = CanonicalEvidenceRecord(
            evidence_type=EvidenceType.FEATURE_RECORD if level > 1 else EvidenceType.SOURCE_RECORD,
            source_domain="TELECOM",
            source_id=f"LEV_{level}",
            source_file=f"data/level_{level}.parquet",
            source_row_index=level,
            canonical_entity_ids=["ENT_CHAIN"],
            event_ids=["EVT_CHAIN"],
            observation_timestamp="2020-01-01T00:00:00Z",
            ingestion_timestamp="2020-01-01T00:05:00Z",
            derivation_method=f"LEVEL_{level}",
            parent_evidence_ids=[prev_id] if prev_id else []
        )
        engine.register_evidence(rec)
        prev_id = rec.evidence_id
        records.append(rec)

    # Tamper with Level 2
    broken_id = records[1].evidence_id
    engine.evidence_store[broken_id].derivation_version = "TAMPERED_V99"

    res = engine.verify_integrity(records[-1].evidence_id)
    assert res["is_valid"] is False
    assert res["status"] == ProvenanceIntegrityStatus.BROKEN_PROVENANCE_CHAIN
    assert res["broken_ancestor_id"] == broken_id


# --- BLOCKER 3: Findings as Actual Provenance Graph Nodes ---

def test_p9_finding_node_exists_in_graph(engine):
    """P9: finding node exists in graph."""
    ev = CanonicalEvidenceRecord(
        evidence_type=EvidenceType.CANONICAL_EVENT,
        source_domain="TELECOM",
        source_id="EV_TEL_P9",
        source_file="data/tel.parquet",
        source_row_index=1,
        canonical_entity_ids=["ENT_P9"],
        event_ids=["EVT_P9"],
        observation_timestamp="2020-01-01T00:00:00Z",
        ingestion_timestamp="2020-01-01T00:05:00Z",
        derivation_method="CANON"
    )
    engine.register_evidence(ev)
    engine.bind_finding_to_evidence("FND_P9", "ENT_P9", [ev.evidence_id])

    assert "FND_P9" in engine.graph.nodes
    assert engine.graph.nodes["FND_P9"]["node_type"] == EvidenceType.ANOMALY_FINDING


def test_p10_evidence_to_finding_edge_exists(engine):
    """P10: evidence -> finding edge exists in graph."""
    ev = CanonicalEvidenceRecord(
        evidence_type=EvidenceType.CANONICAL_EVENT,
        source_domain="TELECOM",
        source_id="EV_TEL_P10",
        source_file="data/tel.parquet",
        source_row_index=1,
        canonical_entity_ids=["ENT_P10"],
        event_ids=["EVT_P10"],
        observation_timestamp="2020-01-01T00:00:00Z",
        ingestion_timestamp="2020-01-01T00:05:00Z",
        derivation_method="CANON"
    )
    engine.register_evidence(ev)
    engine.bind_finding_to_evidence("FND_P10", "ENT_P10", [ev.evidence_id])

    edge_found = any(e["parent_id"] == ev.evidence_id and e["child_id"] == "FND_P10" for e in engine.graph.edges)
    assert edge_found is True


def test_p11_upstream_traversal_reaches_root_evidence(engine):
    """P11: upstream traversal from finding node reaches root evidence."""
    ev_src = CanonicalEvidenceRecord(
        evidence_type=EvidenceType.SOURCE_RECORD,
        source_domain="FINANCIAL",
        source_id="SRC_P11",
        source_file="data/src.csv",
        source_row_index=1,
        canonical_entity_ids=["ENT_P11"],
        event_ids=["EVT_P11"],
        observation_timestamp="2020-01-01T00:00:00Z",
        ingestion_timestamp="2020-01-01T00:05:00Z",
        derivation_method="RAW"
    )
    ev_evt = CanonicalEvidenceRecord(
        evidence_type=EvidenceType.CANONICAL_EVENT,
        source_domain="FINANCIAL",
        source_id="EVT_P11",
        source_file="data/evt.parquet",
        source_row_index=1,
        canonical_entity_ids=["ENT_P11"],
        event_ids=["EVT_P11"],
        observation_timestamp="2020-01-01T00:00:00Z",
        ingestion_timestamp="2020-01-01T00:05:00Z",
        derivation_method="CANON",
        parent_evidence_ids=[ev_src.evidence_id]
    )
    engine.register_evidence(ev_src)
    engine.register_evidence(ev_evt)
    engine.bind_finding_to_evidence("FND_P11", "ENT_P11", [ev_evt.evidence_id])

    lineage = engine.get_upstream_lineage("FND_P11")
    lineage_ids = [n["node_id"] for n in lineage]
    assert ev_evt.evidence_id in lineage_ids
    assert ev_src.evidence_id in lineage_ids


def test_p12_downstream_traversal_reaches_findings(engine):
    """P12: downstream traversal from evidence reaches findings."""
    ev = CanonicalEvidenceRecord(
        evidence_type=EvidenceType.SOURCE_RECORD,
        source_domain="SOCIAL",
        source_id="SRC_P12",
        source_file="data/soc.csv",
        source_row_index=1,
        canonical_entity_ids=["ENT_P12"],
        event_ids=["EVT_P12"],
        observation_timestamp="2020-01-01T00:00:00Z",
        ingestion_timestamp="2020-01-01T00:05:00Z",
        derivation_method="RAW"
    )
    engine.register_evidence(ev)
    engine.bind_finding_to_evidence("FND_P12", "ENT_P12", [ev.evidence_id])

    derivations = engine.get_downstream_derivations(ev.evidence_id)
    deriv_ids = [d["node_id"] for d in derivations]
    assert "FND_P12" in deriv_ids


def test_p13_m11_fused_finding_is_represented_as_graph_node(engine):
    """P13: M11 fused finding is represented as a graph node linked to individual domain findings."""
    ev1 = CanonicalEvidenceRecord(
        evidence_type=EvidenceType.ANOMALY_FINDING,
        source_domain="TELECOM",
        source_id="F1",
        source_file="data/t.parquet",
        source_row_index=1,
        canonical_entity_ids=["ENT_CROSS"],
        event_ids=["E1"],
        observation_timestamp="2020-01-01T00:00:00Z",
        ingestion_timestamp="2020-01-01T00:05:00Z",
        derivation_method="M5_TELECOM"
    )
    ev2 = CanonicalEvidenceRecord(
        evidence_type=EvidenceType.ANOMALY_FINDING,
        source_domain="FINANCIAL",
        source_id="F2",
        source_file="data/f.parquet",
        source_row_index=2,
        canonical_entity_ids=["ENT_CROSS"],
        event_ids=["E2"],
        observation_timestamp="2020-01-01T00:00:00Z",
        ingestion_timestamp="2020-01-01T00:05:00Z",
        derivation_method="M6_FINANCIAL"
    )
    engine.register_evidence(ev1)
    engine.register_evidence(ev2)

    engine.bind_finding_to_evidence(
        "FUS_M11_CASE_01",
        "ENT_CROSS",
        [ev1.evidence_id, ev2.evidence_id],
        finding_type=EvidenceType.FUSED_FINDING
    )

    assert "FUS_M11_CASE_01" in engine.graph.nodes
    assert engine.graph.nodes["FUS_M11_CASE_01"]["node_type"] == EvidenceType.FUSED_FINDING
    assert engine.graph.nodes["FUS_M11_CASE_01"]["domain"] == "CROSS_DOMAIN"


def test_p14_investigation_claim_node_preserves_upstream_lineage(engine):
    """P14: investigation claim node preserves complete upstream lineage."""
    ev = CanonicalEvidenceRecord(
        evidence_type=EvidenceType.CANONICAL_EVENT,
        source_domain="GRAPH",
        source_id="E_GRP",
        source_file="data/g.parquet",
        source_row_index=1,
        canonical_entity_ids=["ENT_CLAIM"],
        event_ids=["EVT_G"],
        observation_timestamp="2020-01-01T00:00:00Z",
        ingestion_timestamp="2020-01-01T00:05:00Z",
        derivation_method="GRAPH"
    )
    engine.register_evidence(ev)
    engine.bind_finding_to_evidence("FND_FOR_CLAIM", "ENT_CLAIM", [ev.evidence_id])

    engine.register_investigation_claim("CLAIM_SYNDICATE_01", "ENT_CLAIM", ["FND_FOR_CLAIM"])

    assert "CLAIM_SYNDICATE_01" in engine.graph.nodes
    upstream = engine.graph.get_upstream_path("CLAIM_SYNDICATE_01")
    up_ids = [u["node_id"] for u in upstream]
    assert "FND_FOR_CLAIM" in up_ids
    assert ev.evidence_id in up_ids


# --- BLOCKER 4: Semantic Event and Entity Verification ---

def test_p15_valid_entity_and_event_accepted(engine):
    """P15: valid entity+event accepted."""
    ev = CanonicalEvidenceRecord(
        evidence_type=EvidenceType.CANONICAL_EVENT,
        source_domain="TELECOM",
        source_id="EVT_VALID_15",
        source_file="data/t.parquet",
        source_row_index=1,
        canonical_entity_ids=["ENT_VALID"],
        event_ids=["EVT_15"],
        observation_timestamp="2020-01-01T00:00:00Z",
        ingestion_timestamp="2020-01-01T00:05:00Z",
        derivation_method="CANON"
    )
    engine.register_evidence(ev)
    # Both entity and event match
    engine.bind_finding_to_evidence(
        "FND_P15",
        "ENT_VALID",
        [ev.evidence_id],
        expected_event_ids=["EVT_15"]
    )
    assert "FND_P15" in engine.finding_evidence_map


def test_p16_valid_entity_but_wrong_event_rejected(engine):
    """P16: valid entity but wrong event rejected."""
    ev = CanonicalEvidenceRecord(
        evidence_type=EvidenceType.CANONICAL_EVENT,
        source_domain="TELECOM",
        source_id="EVT_VALID_16",
        source_file="data/t.parquet",
        source_row_index=1,
        canonical_entity_ids=["ENT_VALID"],
        event_ids=["EVT_16_A"],
        observation_timestamp="2020-01-01T00:00:00Z",
        ingestion_timestamp="2020-01-01T00:05:00Z",
        derivation_method="CANON"
    )
    engine.register_evidence(ev)

    # Finding expects event EVT_16_B, but evidence contains EVT_16_A
    with pytest.raises(ValueError) as exc:
        engine.bind_finding_to_evidence(
            "FND_P16",
            "ENT_VALID",
            [ev.evidence_id],
            expected_event_ids=["EVT_16_B"]
        )
    assert "Event Mismatch" in str(exc.value)


def test_p17_wrong_entity_rejected(engine):
    """P17: wrong entity rejected."""
    ev = CanonicalEvidenceRecord(
        evidence_type=EvidenceType.CANONICAL_EVENT,
        source_domain="TELECOM",
        source_id="EVT_17",
        source_file="data/t.parquet",
        source_row_index=1,
        canonical_entity_ids=["ENT_BETA"],
        event_ids=["EVT_17"],
        observation_timestamp="2020-01-01T00:00:00Z",
        ingestion_timestamp="2020-01-01T00:05:00Z",
        derivation_method="CANON"
    )
    engine.register_evidence(ev)

    with pytest.raises(ValueError) as exc:
        engine.bind_finding_to_evidence("FND_P17", "ENT_ALPHA", [ev.evidence_id])
    assert "Entity Mismatch" in str(exc.value)


def test_p18_same_timestamp_score_but_wrong_event_entity_rejected(engine):
    """P18: same timestamp/score but wrong event/entity rejected."""
    ev = CanonicalEvidenceRecord(
        evidence_type=EvidenceType.CANONICAL_EVENT,
        source_domain="FINANCIAL",
        source_id="EVT_18",
        source_file="data/fin.parquet",
        source_row_index=1,
        canonical_entity_ids=["ENT_OTHER"],
        event_ids=["EVT_OTHER_99"],
        observation_timestamp="2020-01-01T12:00:00Z",  # matching timestamp
        ingestion_timestamp="2020-01-01T12:05:00Z",
        confidence=0.95,                              # matching confidence
        derivation_method="FIN"
    )
    engine.register_evidence(ev)

    with pytest.raises(ValueError) as exc:
        engine.bind_finding_to_evidence("FND_P18", "ENT_TARGET", [ev.evidence_id], expected_event_ids=["EVT_TARGET_01"])
    # Fails closed on entity/event validation
    assert "Entity Mismatch" in str(exc.value) or "Event Mismatch" in str(exc.value)


# --- IMMUTABILITY / API SAFETY ---

def test_p19_mutate_object_returned_from_get_evidence_does_not_alter_trusted_store(engine):
    """P19: mutate object returned from get_evidence() does not alter trusted store."""
    ev = CanonicalEvidenceRecord(
        evidence_type=EvidenceType.SOURCE_RECORD,
        source_domain="TELECOM",
        source_id="SRC_P19",
        source_file="data/immutable.csv",
        source_row_index=1,
        canonical_entity_ids=["ENT_P19"],
        event_ids=["EVT_P19"],
        observation_timestamp="2020-01-01T00:00:00Z",
        ingestion_timestamp="2020-01-01T00:05:00Z",
        derivation_method="DIRECT"
    )
    engine.register_evidence(ev)

    # Caller gets evidence and mutates the returned Python object
    external_obj = engine.get_evidence(ev.evidence_id)
    external_obj.source_file = "data/mutated_by_caller.csv"
    external_obj.canonical_entity_ids.append("ENT_INTRUDER")

    # Internal store remains untouched
    internal_obj = engine.evidence_store[ev.evidence_id]
    assert internal_obj.source_file == "data/immutable.csv"
    assert "ENT_INTRUDER" not in internal_obj.canonical_entity_ids
    assert engine.verify_integrity(ev.evidence_id)["is_valid"] is True


def test_p20_tamper_after_registration_is_detected_on_verification(engine):
    """P20: tamper after registration is detected on verification."""
    ev = CanonicalEvidenceRecord(
        evidence_type=EvidenceType.CANONICAL_EVENT,
        source_domain="FINANCIAL",
        source_id="EVT_P20",
        source_file="data/f.parquet",
        source_row_index=1,
        canonical_entity_ids=["ENT_P20"],
        event_ids=["EVT_P20"],
        observation_timestamp="2020-01-01T00:00:00Z",
        ingestion_timestamp="2020-01-01T00:05:00Z",
        derivation_method="CANON"
    )
    engine.register_evidence(ev)
    assert engine.verify_integrity(ev.evidence_id)["is_valid"] is True

    # Malicious tampering with internal state
    engine.evidence_store[ev.evidence_id].source_row_index = 99999

    # Verification must flag TAMPERED_RECORD_DETECTED
    res = engine.verify_integrity(ev.evidence_id)
    assert res["is_valid"] is False
    assert res["status"] == ProvenanceIntegrityStatus.TAMPERED_RECORD_DETECTED


# =========================================================================
# SECTION F INTEGRITY PROPERTY PROOF
# =========================================================================

def test_end_to_end_six_stage_lineage_and_tamper_propagation(engine):
    """
    SECTION F PROPERTY PROOF:
    SOURCE -> EVENT -> FEATURE -> FINDING -> FUSED_FINDING -> INVESTIGATION_CLAIM
    1. Fully traversable upstream and downstream across all 6 stages.
    2. Tamper SOURCE -> invalidates EVENT, FEATURE, FINDING, FUSED_FINDING, and INVESTIGATION_CLAIM.
    """
    # 1. SOURCE
    ev_src = CanonicalEvidenceRecord(
        evidence_type=EvidenceType.SOURCE_RECORD,
        source_domain="FINANCIAL",
        source_id="SRC_ROOT_01",
        source_file="data/root_source.csv",
        source_row_index=1,
        canonical_entity_ids=["ENT_CASE_F"],
        event_ids=["EVT_CASE_F"],
        observation_timestamp="2020-01-01T00:00:00Z",
        ingestion_timestamp="2020-01-01T00:05:00Z",
        derivation_method="ROOT_INGESTION"
    )
    engine.register_evidence(ev_src)

    # 2. EVENT
    ev_evt = CanonicalEvidenceRecord(
        evidence_type=EvidenceType.CANONICAL_EVENT,
        source_domain="FINANCIAL",
        source_id="EVT_CASE_F",
        source_file="data/canonical.parquet",
        source_row_index=1,
        canonical_entity_ids=["ENT_CASE_F"],
        event_ids=["EVT_CASE_F"],
        observation_timestamp="2020-01-01T00:00:00Z",
        ingestion_timestamp="2020-01-01T00:05:00Z",
        derivation_method="SCHEMA_NORM",
        parent_evidence_ids=[ev_src.evidence_id]
    )
    engine.register_evidence(ev_evt)

    # 3. FEATURE
    ev_feat = CanonicalEvidenceRecord(
        evidence_type=EvidenceType.FEATURE_RECORD,
        source_domain="FINANCIAL",
        source_id="FEAT_CASE_F",
        source_file="data/features.parquet",
        source_row_index=1,
        canonical_entity_ids=["ENT_CASE_F"],
        event_ids=["EVT_CASE_F"],
        observation_timestamp="2020-01-01T00:00:00Z",
        ingestion_timestamp="2020-01-01T00:05:00Z",
        derivation_method="FEATURE_ENG",
        parent_evidence_ids=[ev_evt.evidence_id]
    )
    engine.register_evidence(ev_feat)

    # 4. FINDING
    engine.bind_finding_to_evidence(
        "FND_STAGE_4",
        "ENT_CASE_F",
        [ev_feat.evidence_id],
        expected_event_ids=["EVT_CASE_F"],
        finding_type=EvidenceType.ANOMALY_FINDING
    )

    # 5. FUSED FINDING
    engine.bind_finding_to_evidence(
        "FUS_STAGE_5",
        "ENT_CASE_F",
        [ev_feat.evidence_id],
        expected_event_ids=["EVT_CASE_F"],
        finding_type=EvidenceType.FUSED_FINDING,
        parent_finding_ids=["FND_STAGE_4"]
    )

    # 6. INVESTIGATION CLAIM
    engine.register_investigation_claim(
        "CLAIM_STAGE_6",
        "ENT_CASE_F",
        ["FUS_STAGE_5"]
    )

    # Upstream Traversal from Claim reaches root SOURCE
    upstream = engine.graph.get_upstream_path("CLAIM_STAGE_6")
    up_ids = [u["node_id"] for u in upstream]
    assert "FUS_STAGE_5" in up_ids
    assert "FND_STAGE_4" in up_ids
    assert ev_feat.evidence_id in up_ids
    assert ev_evt.evidence_id in up_ids
    assert ev_src.evidence_id in up_ids

    # Downstream Traversal from root SOURCE reaches Claim
    downstream = engine.graph.get_downstream_path(ev_src.evidence_id)
    down_ids = [d["node_id"] for d in downstream]
    assert ev_evt.evidence_id in down_ids
    assert ev_feat.evidence_id in down_ids
    assert "FND_STAGE_4" in down_ids
    assert "FUS_STAGE_5" in down_ids
    assert "CLAIM_STAGE_6" in down_ids

    # Initial state is verified
    assert engine.verify_integrity(ev_feat.evidence_id)["is_valid"] is True
    assert engine.verify_finding_integrity("FND_STAGE_4")["is_valid"] is True
    assert engine.verify_finding_integrity("FUS_STAGE_5")["is_valid"] is True
    assert engine.verify_finding_integrity("CLAIM_STAGE_6")["is_valid"] is True

    # Tamper root SOURCE
    engine.evidence_store[ev_src.evidence_id].source_file = "data/malicious_tamper.csv"

    # Verifications fail with BROKEN_PROVENANCE_CHAIN
    res_feat = engine.verify_integrity(ev_feat.evidence_id)
    assert res_feat["is_valid"] is False
    assert res_feat["status"] == ProvenanceIntegrityStatus.BROKEN_PROVENANCE_CHAIN
    assert res_feat["broken_ancestor_id"] == ev_src.evidence_id

    res_fnd = engine.verify_finding_integrity("FND_STAGE_4")
    assert res_fnd["is_valid"] is False
    assert res_fnd["status"] == ProvenanceIntegrityStatus.BROKEN_PROVENANCE_CHAIN
    assert res_fnd["broken_ancestor_id"] == ev_src.evidence_id

    res_fus = engine.verify_finding_integrity("FUS_STAGE_5")
    assert res_fus["is_valid"] is False
    assert res_fus["status"] == ProvenanceIntegrityStatus.BROKEN_PROVENANCE_CHAIN
    assert res_fus["broken_ancestor_id"] == ev_src.evidence_id

    res_claim = engine.verify_finding_integrity("CLAIM_STAGE_6")
    assert res_claim["is_valid"] is False
    assert res_claim["status"] == ProvenanceIntegrityStatus.BROKEN_PROVENANCE_CHAIN
    assert res_claim["broken_ancestor_id"] == ev_src.evidence_id
