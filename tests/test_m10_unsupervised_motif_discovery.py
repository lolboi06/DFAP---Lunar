# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: M10 Unsupervised Motif Discovery Tests

import pytest
from dfap.investigation.temporal_sequence import (
    TemporalSequence,
    TemporalSequenceItem,
    TemporalSequenceEngine,
    OrderingBasis
)
from dfap.investigation.temporal_motif_discovery import (
    UnsupervisedMotifDiscoveryEngine,
    DiscoveredMotifClassification,
    extract_sliding_subsequences,
    compute_pairwise_subsequence_distance,
    build_subsequence_distance_matrix,
    cluster_subsequences_agglomerative,
    find_cluster_medoid
)
from dfap.investigation.workspace import InvestigationWorkspaceBackend
from dfap.investigation.motif_fixture import (
    register_motif_demo_fixture,
    DEMO_ENTITY_ID,
    DEMO_CASE_ID
)
from dfap.investigation.copilot import InvestigationCopilot
from dfap.wp4.cli import handle_m13_command


def test_sliding_subsequence_extraction():
    """Extracts sliding windows bounded by min_length and max_length, preserving order and evidence."""
    items = [
        TemporalSequenceItem(f"E{i}", "ENT1", f"2026-01-01T{i:02d}:00:00Z", 1000.0 + i * 60, "LOGIN", "IPDR", i, evidence_ref=f"ref:e{i}")
        for i in range(10)
    ]
    seq = TemporalSequence("ENT1", "CASE1", items, OrderingBasis.TIMESTAMP, True)

    subs = extract_sliding_subsequences(seq, min_length=3, max_length=5)
    # Length 3: 10 - 3 + 1 = 8
    # Length 4: 10 - 4 + 1 = 7
    # Length 5: 10 - 5 + 1 = 6
    # Total = 8 + 7 + 6 = 21
    assert len(subs) == 21
    assert all(3 <= s.length <= 5 for s in subs)
    assert subs[0].event_ids == ["E0", "E1", "E2"]
    assert subs[0].evidence_refs == ["ref:e0", "ref:e1", "ref:e2"]


def test_subsequence_pairwise_distance_and_dtw():
    """Pairwise subsequence distance is 0.0 for identical sequences and positive for divergent sequences."""
    engine = TemporalSequenceEngine()
    items_a = [
        TemporalSequenceItem("E1", "ENT1", "2026-01-01T00:00:00Z", 1000.0, "LOGIN", "IPDR", 0, time_delta_from_previous=0.0),
        TemporalSequenceItem("E2", "ENT1", "2026-01-01T00:02:00Z", 1120.0, "TRANSFER", "BANK", 1, time_delta_from_previous=120.0),
        TemporalSequenceItem("E3", "ENT1", "2026-01-01T00:04:00Z", 1240.0, "MESSAGE", "SOCIAL", 2, time_delta_from_previous=120.0),
    ]
    items_b = [
        TemporalSequenceItem("E4", "ENT1", "2026-01-01T01:00:00Z", 4600.0, "LOGIN", "IPDR", 0, time_delta_from_previous=0.0),
        TemporalSequenceItem("E5", "ENT1", "2026-01-01T01:02:00Z", 4720.0, "TRANSFER", "BANK", 1, time_delta_from_previous=120.0),
        TemporalSequenceItem("E6", "ENT1", "2026-01-01T01:04:00Z", 4840.0, "MESSAGE", "SOCIAL", 2, time_delta_from_previous=120.0),
    ]
    items_c = [
        TemporalSequenceItem("E7", "ENT1", "2026-01-01T02:00:00Z", 8200.0, "QUERY", "IPDR", 0, time_delta_from_previous=0.0),
        TemporalSequenceItem("E8", "ENT1", "2026-01-01T02:02:00Z", 8320.0, "CALL", "CDR", 1, time_delta_from_previous=120.0),
        TemporalSequenceItem("E9", "ENT1", "2026-01-01T02:04:00Z", 8440.0, "EXPORT", "SECURITY", 2, time_delta_from_previous=120.0),
    ]
    seq_a = TemporalSequence("ENT1", "CASE1", items_a, OrderingBasis.TIMESTAMP, True)
    seq_b = TemporalSequence("ENT1", "CASE1", items_b, OrderingBasis.TIMESTAMP, True)
    seq_c = TemporalSequence("ENT1", "CASE1", items_c, OrderingBasis.TIMESTAMP, True)

    subs_a = extract_sliding_subsequences(seq_a, min_length=3, max_length=3)
    subs_b = extract_sliding_subsequences(seq_b, min_length=3, max_length=3)
    subs_c = extract_sliding_subsequences(seq_c, min_length=3, max_length=3)

    dist_ab = compute_pairwise_subsequence_distance(engine, subs_a[0], subs_b[0])
    dist_ac = compute_pairwise_subsequence_distance(engine, subs_a[0], subs_c[0])

    assert dist_ab < 0.05  # identical event types and domains with identical delta
    assert dist_ac > 0.50  # completely divergent event types and domains


def test_clustering_min_cluster_size_threshold():
    """Agglomerative clustering filters clusters with size < min_cluster_size (default 3)."""
    # 2 identical items + 1 different item
    # min_cluster_size = 3 will yield zero clusters
    import numpy as np
    dist_mat = np.array([
        [0.0, 0.02, 0.90],
        [0.02, 0.0, 0.90],
        [0.90, 0.90, 0.0]
    ])
    clusters = cluster_subsequences_agglomerative(dist_mat, distance_threshold=0.25, min_cluster_size=3)
    assert len(clusters) == 0

    # 3 similar items with distance <= 0.25
    dist_mat_3 = np.array([
        [0.0, 0.05, 0.08],
        [0.05, 0.0, 0.06],
        [0.08, 0.06, 0.0]
    ])
    clusters_3 = cluster_subsequences_agglomerative(dist_mat_3, distance_threshold=0.25, min_cluster_size=3)
    assert len(clusters_3) == 1
    assert set(clusters_3[0]) == {0, 1, 2}


def test_unsupervised_motif_discovery_synthetic_demo():
    """Unsupervised motif discovery extracts novel repeating pattern and assigns DISCOVERED_MOTIF_005."""
    backend = InvestigationWorkspaceBackend()
    res = register_motif_demo_fixture(backend)

    discovered = res["discovered_motifs"]
    assert len(discovered) > 0

    # Find the novel discovered motif
    novel = [m for m in discovered if m.classification == DiscoveredMotifClassification.DISCOVERED_MOTIF]
    assert len(novel) > 0
    m1 = novel[0]

    assert m1.motif_id == "DISCOVERED_MOTIF_005"
    assert m1.cluster_size >= 3
    assert len(m1.representative_event_types) >= 3
    assert len(m1.representative_domains) >= 2
    assert m1.medoid_total_distance >= 0.0
    assert len(m1.evidence_refs) >= 3
    assert "no existing predefined motif sufficiently matched" in m1.explanation

    # Verify no intent or criminal assertions
    forbidden = ["fraud", "criminal", "malicious", "illicit", "guilty", "perpetrator"]
    for word in forbidden:
        assert word not in m1.explanation.lower()


def test_m9_m11_feature_extraction_interface():
    """Discovered motifs expose analytical features for M9/M11 without altering scoring."""
    backend = InvestigationWorkspaceBackend()
    res = register_motif_demo_fixture(backend)
    seq = res["sequence"]

    features = backend.extract_sequence_features(seq)
    feats_dict = features.to_dict()

    # Features are populated cleanly
    assert "sequence_length" in feats_dict
    assert "discovered_motif_count" in feats_dict
    assert "discovered_motif_membership" in feats_dict
    assert "discovered_motif_frequency" in feats_dict
    assert "discovered_motif_cross_domain" in feats_dict

    # Check with explicitly passed discovered motifs
    feat_with_motifs = backend.temporal_sequence_engine.extract_features(seq, discovered_motifs=res["discovered_motifs"])
    assert feat_with_motifs.discovered_motif_count == len(res["discovered_motifs"])
    assert "DISCOVERED_MOTIF_005" in feat_with_motifs.discovered_motif_membership


def test_m14_copilot_motif_grounded_queries():
    """M14 Copilot answers queries about recurring and novel motifs without forbidden terminology."""
    backend = InvestigationWorkspaceBackend()
    register_motif_demo_fixture(backend)
    copilot = InvestigationCopilot(backend)

    # Q1: Recurring patterns
    res1 = copilot.ask("What recurring patterns were discovered?", case_id=DEMO_CASE_ID)
    assert res1["status"] == "GROUNDED"
    assert "DFAP discovered a recurring temporal subsequence" in res1["answer"]
    assert "predefined motif catalog" in res1["answer"]
    assert "discovered_motifs" in res1

    # Q2: Multi-domain motifs
    res2 = copilot.ask("Which discovered motif involves multiple domains?", case_id=DEMO_CASE_ID)
    assert res2["status"] == "GROUNDED"
    assert "involves multiple domains" in res2["answer"].lower()
    assert "DISCOVERED_MOTIF_" in res2["answer"]

    # Strictly no criminal / malicious allegations
    for forbidden in ["clandestine", "criminal tradecraft", "fraud pattern", "malicious sequence", "likely offender"]:
        assert forbidden not in res1["answer"].lower()
        assert forbidden not in res2["answer"].lower()


def test_cli_sequence_motifs_and_help():
    """CLI sequence motifs command outputs both predefined and discovered motifs; help lists command."""
    backend = InvestigationWorkspaceBackend()
    register_motif_demo_fixture(backend)

    # 1. sequence motifs command
    out = handle_m13_command(backend, f"sequence motifs {DEMO_ENTITY_ID}")
    assert "SEQUENCE MOTIFS" in out
    assert "predefined_motifs" in out
    assert "discovered_motifs" in out
    assert "DISCOVERED_MOTIF_005" in out

    # 2. help output
    help_out = handle_m13_command(backend, "help")
    assert "sequence motifs" in help_out
