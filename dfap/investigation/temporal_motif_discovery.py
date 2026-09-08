# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: M10 Unsupervised Motif Discovery (Sliding Subsequences, DTW Distance Matrix, Agglomerative Clustering & Medoid Selection)

from dataclasses import dataclass, field
from enum import Enum
import math
from typing import Any, Dict, List, Optional, Set, Tuple, Union
import numpy as np

from dfap.investigation.temporal_sequence import (
    TemporalSequence,
    TemporalSequenceItem,
    TemporalSequenceEngine,
    OrderingBasis,
    MotifMatch
)


class DiscoveredMotifClassification:
    EXISTING_MOTIF = "EXISTING_MOTIF"
    DISCOVERED_MOTIF = "DISCOVERED_MOTIF"


DEFAULT_MOTIF_DISCOVERY_CONFIG = {
    "min_length": 3,
    "max_length": 8,
    "distance_threshold": 0.25,
    "min_cluster_size": 3,
    "starting_motif_index": 5,
    "weights": {
        "event_type": 0.50,
        "domain": 0.30,
        "timing_dtw": 0.20
    }
}


@dataclass
class EventSubsequence:
    """
    Structured temporal subsequence extracted via sliding window.
    Retains ordered event IDs, event types, domains, timestamps, and evidence references.
    """
    subsequence_id: str
    entity_id: str
    start_index: int
    length: int
    items: List[TemporalSequenceItem]
    event_ids: List[str]
    event_types: List[str]
    domains: List[str]
    timestamps: List[str]
    epoch_times: List[float]
    evidence_refs: List[str]
    time_deltas: List[float]
    total_span: float
    source_case_id: Optional[str] = None

    def to_temporal_sequence(self) -> TemporalSequence:
        """Converts the subsequence to a standard TemporalSequence for existing DTW comparison."""
        return TemporalSequence(
            entity_id=self.entity_id,
            case_id=self.source_case_id,
            items=self.items,
            ordering_basis=OrderingBasis.TIMESTAMP,
            is_causally_valid=True
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "subsequence_id": self.subsequence_id,
            "entity_id": self.entity_id,
            "start_index": self.start_index,
            "length": self.length,
            "event_ids": self.event_ids,
            "event_types": self.event_types,
            "domains": self.domains,
            "timestamps": self.timestamps,
            "evidence_refs": self.evidence_refs,
            "total_span": self.total_span,
        }


@dataclass
class DiscoveredMotif:
    """
    Unsupervised recurring behavioral motif extracted from sequence clusters.
    Strictly free from subjective intent or guilt designations.
    """
    motif_id: str
    motif_type: str
    classification: str
    cluster_id: int
    cluster_size: int
    representative_sequence: str
    representative_event_types: List[str]
    representative_domains: List[str]
    representative_event_ids: List[str]
    distance_threshold: float
    medoid_total_distance: float
    member_subsequence_ids: List[str]
    temporal_statistics: Dict[str, Any]
    evidence_refs: List[str]
    source_entity_ids: List[str]
    explanation: str
    matched_catalog_motif: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "motif_id": self.motif_id,
            "motif_type": self.motif_type,
            "classification": self.classification,
            "cluster_id": self.cluster_id,
            "cluster_size": self.cluster_size,
            "representative_sequence": self.representative_sequence,
            "representative_event_types": self.representative_event_types,
            "representative_domains": self.representative_domains,
            "representative_event_ids": self.representative_event_ids,
            "distance_threshold": self.distance_threshold,
            "medoid_total_distance": round(float(self.medoid_total_distance), 4),
            "member_subsequence_ids": self.member_subsequence_ids,
            "temporal_statistics": self.temporal_statistics,
            "evidence_refs": self.evidence_refs,
            "source_entity_ids": self.source_entity_ids,
            "explanation": self.explanation,
            "matched_catalog_motif": self.matched_catalog_motif,
        }


def extract_sliding_subsequences(
    sequence: TemporalSequence,
    min_length: int = 3,
    max_length: int = 8
) -> List[EventSubsequence]:
    """
    Extracts sliding subsequences of lengths min_length through max_length from sequence.
    Preserves deterministic ordering, event IDs, types, domains, and evidence references.
    """
    n = len(sequence.items)
    if n < min_length:
        return []

    eff_max = min(max_length, n)
    subsequences: List[EventSubsequence] = []

    for length in range(min_length, eff_max + 1):
        for start_idx in range(n - length + 1):
            sub_items = sequence.items[start_idx : start_idx + length]
            ev_ids = [it.event_id for it in sub_items]
            ev_types = [it.event_type for it in sub_items]
            domains = [it.source_domain for it in sub_items]
            timestamps = [it.timestamp for it in sub_items]
            epoch_times = [it.epoch_time if it.epoch_time is not None else 0.0 for it in sub_items]
            evidence_refs = [it.evidence_ref for it in sub_items if it.evidence_ref]
            deltas = [it.time_delta_from_previous if it.time_delta_from_previous is not None else 1.0 for it in sub_items]

            span = 0.0
            if epoch_times and len(epoch_times) > 1:
                span = max(0.0, epoch_times[-1] - epoch_times[0])

            sub_id = f"SUB_{sequence.entity_id}_{start_idx}_L{length}"
            subsequences.append(EventSubsequence(
                subsequence_id=sub_id,
                entity_id=sequence.entity_id,
                start_index=start_idx,
                length=length,
                items=sub_items,
                event_ids=ev_ids,
                event_types=ev_types,
                domains=domains,
                timestamps=timestamps,
                epoch_times=epoch_times,
                evidence_refs=sorted(list(dict.fromkeys(evidence_refs))),
                time_deltas=deltas,
                total_span=round(span, 4),
                source_case_id=sequence.case_id
            ))

    # Deterministic ordering by start index, then length
    subsequences.sort(key=lambda s: (s.start_index, s.length))
    return subsequences


def compute_pairwise_subsequence_distance(
    engine: TemporalSequenceEngine,
    sub_a: EventSubsequence,
    sub_b: EventSubsequence,
    weights: Optional[Dict[str, float]] = None
) -> float:
    """
    Computes deterministic pairwise distance between two subsequences combining
    event-type alignment (Levenshtein), domain alignment, and DTW inter-event timing.
    Reuses existing TemporalSequenceEngine alignment implementation.
    Bounded in [0.0, 1.0].
    """
    w = dict(DEFAULT_MOTIF_DISCOVERY_CONFIG["weights"])
    if weights:
        w.update(weights)

    seq_a = sub_a.to_temporal_sequence()
    seq_b = sub_b.to_temporal_sequence()

    # Reuse existing engine sequence comparison (normalized Levenshtein + DTW on deltas)
    comp = engine.compare_sequences(seq_a, seq_b)

    # 1. Event type distance (Levenshtein normalized)
    type_dist = comp.get("edit_distance_normalized", 0.0)

    # 2. Domain sequence distance (normalized Levenshtein)
    doms_a = sub_a.domains
    doms_b = sub_b.domains
    len_da, len_db = len(doms_a), len(doms_b)
    dp_dom = [[0] * (len_db + 1) for _ in range(len_da + 1)]
    for i in range(len_da + 1):
        dp_dom[i][0] = i
    for j in range(len_db + 1):
        dp_dom[0][j] = j
    for i in range(1, len_da + 1):
        for j in range(1, len_db + 1):
            cost = 0 if doms_a[i - 1].upper() == doms_b[j - 1].upper() else 1
            dp_dom[i][j] = min(dp_dom[i - 1][j] + 1, dp_dom[i][j - 1] + 1, dp_dom[i - 1][j - 1] + cost)
    dom_dist = dp_dom[len_da][len_db] / max(len_da, len_db, 1)

    # 3. Normalized DTW timing distance
    raw_dtw = comp.get("dtw_distance", 0.0)
    # Normalize timing gap using dynamic range scaling
    avg_span = max(1.0, (sub_a.total_span + sub_b.total_span) / 2.0)
    norm_dtw = float(np.clip(raw_dtw / (raw_dtw + avg_span + 10.0), 0.0, 1.0))

    composite_dist = (
        w.get("event_type", 0.50) * type_dist +
        w.get("domain", 0.30) * dom_dist +
        w.get("timing_dtw", 0.20) * norm_dtw
    )

    return round(float(np.clip(composite_dist, 0.0, 1.0)), 6)


def build_subsequence_distance_matrix(
    engine: TemporalSequenceEngine,
    subsequences: List[EventSubsequence],
    weights: Optional[Dict[str, float]] = None
) -> np.ndarray:
    """
    Constructs a symmetric N x N pairwise distance matrix over all subsequences.
    Zero-diagonal, deterministic input handling.
    """
    m = len(subsequences)
    if m == 0:
        return np.zeros((0, 0), dtype=float)

    mat = np.zeros((m, m), dtype=float)
    for i in range(m):
        for j in range(i + 1, m):
            d = compute_pairwise_subsequence_distance(engine, subsequences[i], subsequences[j], weights=weights)
            mat[i, j] = d
            mat[j, i] = d

    return mat


def cluster_subsequences_agglomerative(
    distance_matrix: np.ndarray,
    distance_threshold: float = 0.25,
    min_cluster_size: int = 3
) -> List[List[int]]:
    """
    Unsupervised agglomerative hierarchical clustering with complete linkage.
    D(A, B) = max_{u in A, v in B} dist(u, v).
    Stops when min inter-cluster distance exceeds distance_threshold.
    Filters out clusters with size < min_cluster_size.
    Uses deterministic tie-breaking.
    """
    n = distance_matrix.shape[0]
    if n < min_cluster_size:
        return []

    # Initialize each item in its own cluster
    clusters = [[i] for i in range(n)]

    while len(clusters) > 1:
        best_dist = float("inf")
        best_pair = None

        for i in range(len(clusters)):
            for j in range(i + 1, len(clusters)):
                c1 = clusters[i]
                c2 = clusters[j]
                # Complete linkage: maximum distance between any member pair
                linkage_dist = max(distance_matrix[u, v] for u in c1 for v in c2)

                if linkage_dist < best_dist:
                    best_dist = linkage_dist
                    best_pair = (i, j)
                elif abs(linkage_dist - best_dist) < 1e-9:
                    # Deterministic tie-breaking by lowest index
                    if best_pair is None or (min(c1), min(c2)) < (min(clusters[best_pair[0]]), min(clusters[best_pair[1]])):
                        best_pair = (i, j)

        if best_pair is None or best_dist > distance_threshold:
            break

        # Merge clusters best_pair[0] and best_pair[1]
        i, j = best_pair
        merged = sorted(clusters[i] + clusters[j])
        new_clusters = [c for idx, c in enumerate(clusters) if idx not in (i, j)]
        new_clusters.append(merged)
        clusters = new_clusters

    # Filter by minimum cluster size and sort deterministically
    qualifying = [sorted(c) for c in clusters if len(c) >= min_cluster_size]
    qualifying.sort(key=lambda c: (-len(c), c[0]))
    return qualifying


def find_cluster_medoid(
    cluster_indices: List[int],
    distance_matrix: np.ndarray,
    subsequences: List[EventSubsequence]
) -> Tuple[int, float]:
    """
    Determines the cluster medoid: member with minimal sum of distances to other members.
    Deterministic tie-breaking on start_index and length.
    """
    best_idx = cluster_indices[0]
    best_total_dist = float("inf")

    for i in cluster_indices:
        tot_dist = sum(distance_matrix[i, j] for j in cluster_indices)
        if tot_dist < best_total_dist - 1e-9:
            best_total_dist = tot_dist
            best_idx = i
        elif abs(tot_dist - best_total_dist) <= 1e-9:
            # Deterministic tie-break
            sub_curr = subsequences[i]
            sub_best = subsequences[best_idx]
            if (sub_curr.start_index, sub_curr.length) < (sub_best.start_index, sub_best.length):
                best_idx = i

    return best_idx, round(float(best_total_dist), 4)


SPECIFIC_CATALOG_MOTIFS = {
    "ACCESS_CHANGE_TRANSFER",
    "TRANSFER_BURST",
    "RAPID_TRANSACTION_BURST",
    "REPEATED_ACTION_SEQUENCE"
}


def match_against_motif_catalog(
    engine: TemporalSequenceEngine,
    medoid_subsequence: EventSubsequence
) -> Tuple[str, Optional[str]]:
    """
    Evaluates representative medoid subsequence against canonical predefined DFAP motifs.
    Returns (classification, matched_motif_id).
    If matched: (DiscoveredMotifClassification.EXISTING_MOTIF, catalog_motif_id)
    If novel: (DiscoveredMotifClassification.DISCOVERED_MOTIF, None)
    """
    medoid_seq = medoid_subsequence.to_temporal_sequence()
    catalog_matches = engine.detect_motifs(medoid_seq)

    for m in catalog_matches:
        if m.motif_id in SPECIFIC_CATALOG_MOTIFS and m.matched and m.fit_score >= 0.80:
            return DiscoveredMotifClassification.EXISTING_MOTIF, m.motif_id

    return DiscoveredMotifClassification.DISCOVERED_MOTIF, None


def compute_motif_temporal_statistics(
    cluster_subsequences: List[EventSubsequence],
    medoid_subsequence: EventSubsequence
) -> Dict[str, Any]:
    """
    Calculates empirical temporal properties from all cluster members.
    Strictly factual; does not infer intent.
    """
    spans = [s.total_span for s in cluster_subsequences]
    mean_span = round(float(np.mean(spans)), 2) if spans else 0.0
    median_span = round(float(np.median(spans)), 2) if spans else 0.0

    all_gaps: List[float] = []
    for s in cluster_subsequences:
        if len(s.epoch_times) > 1:
            for i in range(1, len(s.epoch_times)):
                all_gaps.append(max(0.0, s.epoch_times[i] - s.epoch_times[i - 1]))
        elif s.time_deltas:
            all_gaps.extend(s.time_deltas)

    if all_gaps:
        mean_gap = round(float(np.mean(all_gaps)), 2)
        median_gap = round(float(np.median(all_gaps)), 2)
        min_gap = round(float(np.min(all_gaps)), 2)
        max_gap = round(float(np.max(all_gaps)), 2)
    else:
        mean_gap = 0.0
        median_gap = 0.0
        min_gap = 0.0
        max_gap = 0.0

    unique_domains = len(set(d for s in cluster_subsequences for d in s.domains))
    unique_types = len(set(t for s in cluster_subsequences for t in s.event_types))

    return {
        "mean_span_seconds": mean_span,
        "median_span_seconds": median_span,
        "mean_inter_event_gap_seconds": mean_gap,
        "median_inter_event_gap_seconds": median_gap,
        "min_inter_event_gap_seconds": min_gap,
        "max_inter_event_gap_seconds": max_gap,
        "domain_count": unique_domains,
        "event_type_count": unique_types,
        "member_count": len(cluster_subsequences)
    }


class UnsupervisedMotifDiscoveryEngine:
    """
    Unsupervised Temporal Motif Discovery Engine for M10 Temporal Intelligence.
    Extracts sliding subsequences, executes complete-linkage agglomerative clustering,
    identifies cluster medoids, and reconciles patterns against the canonical motif catalog.
    """

    def __init__(self, sequence_engine: Optional[TemporalSequenceEngine] = None, config: Optional[Dict[str, Any]] = None):
        self.sequence_engine = sequence_engine or TemporalSequenceEngine()
        self.config = dict(DEFAULT_MOTIF_DISCOVERY_CONFIG)
        if config:
            self.config.update(config)

    def discover_motifs(
        self,
        sequence: TemporalSequence,
        min_length: Optional[int] = None,
        max_length: Optional[int] = None,
        distance_threshold: Optional[float] = None,
        min_cluster_size: Optional[int] = None,
        starting_motif_index: Optional[int] = None
    ) -> List[DiscoveredMotif]:
        """
        Executes end-to-end unsupervised motif discovery on an entity sequence.
        """
        min_len = min_length if min_length is not None else self.config["min_length"]
        max_len = max_length if max_length is not None else self.config["max_length"]
        thresh = distance_threshold if distance_threshold is not None else self.config["distance_threshold"]
        min_size = min_cluster_size if min_cluster_size is not None else self.config["min_cluster_size"]
        motif_idx_counter = starting_motif_index if starting_motif_index is not None else self.config["starting_motif_index"]

        # 1. Sliding Subsequence Extraction
        subsequences = extract_sliding_subsequences(sequence, min_length=min_len, max_length=max_len)
        if len(subsequences) < min_size:
            return []

        # 2. Pairwise Subsequence Distance Matrix (DTW + Alignment)
        dist_mat = build_subsequence_distance_matrix(
            self.sequence_engine,
            subsequences,
            weights=self.config.get("weights")
        )

        # 3. Agglomerative Complete-Linkage Clustering
        clusters = cluster_subsequences_agglomerative(
            dist_mat,
            distance_threshold=thresh,
            min_cluster_size=min_size
        )

        discovered_motifs: List[DiscoveredMotif] = []

        # 4. Medoid Selection & Catalog Reconcilation per Cluster
        for c_id, cluster_members in enumerate(clusters):
            medoid_idx, medoid_tot_dist = find_cluster_medoid(cluster_members, dist_mat, subsequences)
            medoid_sub = subsequences[medoid_idx]
            member_subs = [subsequences[i] for i in cluster_members]

            # Reconcile with Catalog
            classification, catalog_id = match_against_motif_catalog(self.sequence_engine, medoid_sub)

            if classification == DiscoveredMotifClassification.EXISTING_MOTIF:
                motif_id = f"DISCOVERED_EXISTING_{catalog_id}"
                motif_type = catalog_id or "EXISTING_CATALOG_MOTIF"
                explanation = (
                    f"Recurring temporal subsequence discovered across {len(cluster_members)} sequence windows; "
                    f"matches predefined catalog motif '{catalog_id}'."
                )
            else:
                motif_id = f"DISCOVERED_MOTIF_{motif_idx_counter:03d}"
                motif_type = "UNSUPERVISED_RECURRING_SUBSEQUENCE"
                explanation = (
                    f"Recurring temporal subsequence discovered across {len(cluster_members)} sequence windows; "
                    f"no existing predefined motif sufficiently matched the representative sequence."
                )
                motif_idx_counter += 1

            # Temporal Statistics
            stats = compute_motif_temporal_statistics(member_subs, medoid_sub)

            # Evidence & Provenance Binding
            all_ev_refs = sorted(list(set(ref for s in member_subs for ref in s.evidence_refs)))
            all_event_ids = sorted(list(set(eid for s in member_subs for eid in s.event_ids)))
            source_entities = sorted(list(set(s.entity_id for s in member_subs)))

            motif = DiscoveredMotif(
                motif_id=motif_id,
                motif_type=motif_type,
                classification=classification,
                cluster_id=c_id,
                cluster_size=len(cluster_members),
                representative_sequence=" -> ".join(medoid_sub.event_types),
                representative_event_types=medoid_sub.event_types,
                representative_domains=medoid_sub.domains,
                representative_event_ids=medoid_sub.event_ids,
                distance_threshold=thresh,
                medoid_total_distance=medoid_tot_dist,
                member_subsequence_ids=[s.subsequence_id for s in member_subs],
                temporal_statistics=stats,
                evidence_refs=all_ev_refs,
                source_entity_ids=source_entities,
                explanation=explanation,
                matched_catalog_motif=catalog_id
            )
            discovered_motifs.append(motif)

        return discovered_motifs

    def extract_motif_features(
        self,
        sequence: TemporalSequence,
        discovered_motifs: Optional[List[DiscoveredMotif]] = None
    ) -> Dict[str, Any]:
        """
        Exposes discovered motif summary as deterministic features for downstream M9/M11 ingestion.
        Additive only; does NOT alter scoring directly.
        """
        motifs = discovered_motifs if discovered_motifs is not None else self.discover_motifs(sequence)

        count = len(motifs)
        membership = [m.motif_id for m in motifs]
        frequency = {m.motif_id: m.cluster_size for m in motifs}
        cross_domain_count = sum(1 for m in motifs if len(set(m.representative_domains)) > 1)

        return {
            "discovered_motif_count": count,
            "discovered_motif_membership": membership,
            "discovered_motif_frequency": frequency,
            "discovered_motif_cross_domain": cross_domain_count,
        }
