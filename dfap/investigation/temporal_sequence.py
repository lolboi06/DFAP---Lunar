# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: Temporal Sequence Engine (Deterministic Sequencing, Strict Causality & Windows)

from dataclasses import dataclass, field
from enum import Enum
import json
import logging
from typing import Dict, Any, List, Optional, Tuple, Set, Union
import numpy as np
import pandas as pd

from dfap.schemas import TemporalSemantics

logger = logging.getLogger(__name__)


class OrderingBasis(str, Enum):
    TIMESTAMP = "TIMESTAMP"
    AUTHORITATIVE_SEQUENCE = "AUTHORITATIVE_SEQUENCE"
    UNRESOLVED = "UNRESOLVED"


class TemporalWindowType(str, Enum):
    TIGHT = "TIGHT"          # 3600.0 seconds (1 hour)
    MODERATE = "MODERATE"    # 86400.0 seconds (24 hours)
    BROAD = "BROAD"          # 604800.0 seconds (7 days)


WINDOW_DURATIONS: Dict[TemporalWindowType, float] = {
    TemporalWindowType.TIGHT: 3600.0,
    TemporalWindowType.MODERATE: 86400.0,
    TemporalWindowType.BROAD: 604800.0,
}


@dataclass
class TemporalSequenceItem:
    """
    Standardized, immutable representation of an ordered event in a temporal sequence.
    """
    event_id: str
    canonical_entity_id: str
    timestamp: str
    epoch_time: Optional[float]
    event_type: str
    source_domain: str
    sequence_index: int
    evidence_ref: Optional[str] = None
    time_delta_from_previous: Optional[float] = None
    window_id: Optional[str] = None
    ordering_basis: OrderingBasis = OrderingBasis.TIMESTAMP
    sequence_number: Optional[int] = None
    actor_id: Optional[str] = None
    target_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "canonical_entity_id": self.canonical_entity_id,
            "actor_id": self.actor_id,
            "target_id": self.target_id,
            "timestamp": self.timestamp,
            "epoch_time": self.epoch_time,
            "event_type": self.event_type,
            "source_domain": self.source_domain,
            "sequence_index": self.sequence_index,
            "evidence_ref": self.evidence_ref,
            "time_delta_from_previous": self.time_delta_from_previous,
            "window_id": self.window_id,
            "ordering_basis": self.ordering_basis.value,
            "sequence_number": self.sequence_number,
            "metadata": self.metadata,
        }


class ValidationResult(dict):
    """Result object for sequence validation supporting both dict and tuple semantics."""
    def __init__(self, is_valid: bool, issues: List[str]):
        super().__init__(is_valid=is_valid, issues=issues)
        self.is_valid = is_valid
        self.issues = issues

    def __iter__(self):
        return iter((self.is_valid, self.issues))


@dataclass
class TemporalSequence:
    """
    Encapsulates a deterministically ordered sequence of events for an entity and case.
    """
    entity_id: str
    case_id: Optional[str]
    items: List[TemporalSequenceItem]
    ordering_basis: OrderingBasis
    is_causally_valid: bool
    unresolved_ties: List[str] = field(default_factory=list)
    dataset: Optional[str] = None
    temporal_semantics: Optional[str] = None

    @property
    def canonical_entity_id(self) -> str:
        return self.entity_id

    def __len__(self) -> int:
        return len(self.items)

    def __iter__(self):
        return iter(self.items)

    def __getitem__(self, index):
        return self.items[index]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "case_id": self.case_id,
            "dataset": self.dataset,
            "temporal_semantics": self.temporal_semantics,
            "ordering_basis": self.ordering_basis.value,
            "is_causally_valid": self.is_causally_valid,
            "unresolved_ties": self.unresolved_ties,
            "item_count": len(self.items),
            "items": [item.to_dict() for item in self.items],
        }

    def extract_features(self, rapid_threshold_seconds: float = 60.0) -> "TemporalSequenceFeatures":
        engine = TemporalSequenceEngine()
        return engine.extract_features(self, rapid_threshold_seconds=rapid_threshold_seconds)

    def analyze_transitions(self) -> Dict[str, List["TemporalTransition"]]:
        engine = TemporalSequenceEngine()
        return engine.analyze_transitions(self)

    def detect_patterns(self, min_len: int = 2, max_len: int = 4, min_count: int = 1) -> List[Dict[str, Any]]:
        engine = TemporalSequenceEngine()
        return engine.detect_patterns(self, min_len=min_len, max_len=max_len, min_count=min_count)

    def detect_motifs(self) -> List["MotifMatch"]:
        engine = TemporalSequenceEngine()
        return engine.detect_motifs(self)

    def discover_motifs(
        self,
        min_length: int = 3,
        max_length: int = 8,
        distance_threshold: float = 0.25,
        min_cluster_size: int = 3,
        starting_motif_index: int = 5
    ) -> List[Any]:
        engine = TemporalSequenceEngine()
        return engine.discover_motifs(
            self,
            min_length=min_length,
            max_length=max_length,
            distance_threshold=distance_threshold,
            min_cluster_size=min_cluster_size,
            starting_motif_index=starting_motif_index
        )

    def compress_phases(self, gap_threshold_seconds: Optional[float] = None) -> List["SequencePhase"]:
        engine = TemporalSequenceEngine()
        return engine.compress_phases(self, gap_threshold_seconds=gap_threshold_seconds)

    def build_transition_graph(self) -> Dict[str, Any]:
        engine = TemporalSequenceEngine()
        return engine.build_transition_graph(self)

    def format_investigator_timeline(self, trigger_event: Optional[Union[TemporalSequenceItem, str, Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
        engine = TemporalSequenceEngine()
        return engine.format_investigator_timeline(self, trigger_event=trigger_event)


@dataclass
class TemporalSequenceFeatures:
    """
    Structured feature vector extracted from an entity's temporal sequence.
    Used for downstream M9/M11 analytical models without assigning guilt.
    """
    sequence_length: int
    unique_event_types: int
    unique_domains: int
    mean_inter_event_time: float
    median_inter_event_time: float
    max_inter_event_gap: float
    min_inter_event_gap: float
    rapid_transition_count: int
    repeated_transition_count: int
    cross_domain_transition_count: int
    unique_transition_count: int = 0
    novel_transition_count: Optional[int] = None
    discovered_motif_count: int = 0
    discovered_motif_membership: List[str] = field(default_factory=list)
    discovered_motif_frequency: Dict[str, int] = field(default_factory=dict)
    discovered_motif_cross_domain: int = 0
    features_dict: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "sequence_length": self.sequence_length,
            "unique_event_types": self.unique_event_types,
            "unique_domains": self.unique_domains,
            "mean_inter_event_time": self.mean_inter_event_time,
            "median_inter_event_time": self.median_inter_event_time,
            "max_inter_event_gap": self.max_inter_event_gap,
            "min_inter_event_gap": self.min_inter_event_gap,
            "rapid_transition_count": self.rapid_transition_count,
            "repeated_transition_count": self.repeated_transition_count,
            "cross_domain_transition_count": self.cross_domain_transition_count,
            "unique_transition_count": self.unique_transition_count,
            "discovered_motif_count": self.discovered_motif_count,
            "discovered_motif_membership": self.discovered_motif_membership,
            "discovered_motif_frequency": self.discovered_motif_frequency,
            "discovered_motif_cross_domain": self.discovered_motif_cross_domain,
        }
        if self.novel_transition_count is not None:
            d["novel_transition_count"] = self.novel_transition_count
        if self.features_dict:
            d["features_dict"] = self.features_dict
        return d


@dataclass
class TemporalTransition:
    """Observed transition between successive events or domains."""
    source: str
    target: str
    transition_type: str  # "event_to_event", "domain_to_domain", "domain_to_event"
    count: int
    mean_gap: float
    median_gap: float
    min_gap: float
    max_gap: float
    participating_domains: List[str]
    evidence_refs: List[str]

    @property
    def source_event_type(self) -> str:
        return self.source

    @property
    def target_event_type(self) -> str:
        return self.target

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "target": self.target,
            "source_event_type": self.source,
            "target_event_type": self.target,
            "transition_type": self.transition_type,
            "count": self.count,
            "mean_gap": self.mean_gap,
            "median_gap": self.median_gap,
            "min_gap": self.min_gap,
            "max_gap": self.max_gap,
            "participating_domains": self.participating_domains,
            "evidence_refs": self.evidence_refs,
        }


@dataclass
class MotifMatch:
    """Evaluated match against a canonical DFAP behavioral motif."""
    motif_id: str
    matched: bool
    fit_score: float
    matching_event_ids: List[str]
    temporal_span: float
    participating_domains: List[str]
    evidence_refs: List[str]
    description: str

    @property
    def motif_type(self) -> str:
        return self.motif_id

    @property
    def time_span_seconds(self) -> float:
        return self.temporal_span

    @property
    def event_count(self) -> int:
        return len(self.matching_event_ids)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "motif_id": self.motif_id,
            "motif_type": self.motif_id,
            "matched": self.matched,
            "fit_score": self.fit_score,
            "matching_event_ids": self.matching_event_ids,
            "temporal_span": self.temporal_span,
            "time_span_seconds": self.temporal_span,
            "event_count": len(self.matching_event_ids),
            "participating_domains": self.participating_domains,
            "evidence_refs": self.evidence_refs,
            "description": self.description,
        }


@dataclass
class SequencePhase:
    """Compressed high-level phase grouping contiguous activity."""
    phase_index: int
    phase_id: str
    name: str
    start_time: str
    end_time: str
    span_seconds: float
    event_count: int
    event_ids: List[str]
    event_types: List[str]
    domains: List[str]
    evidence_refs: List[str]

    @property
    def label(self) -> str:
        return self.name

    @property
    def duration_seconds(self) -> float:
        return self.span_seconds

    def to_dict(self) -> Dict[str, Any]:
        return {
            "phase_index": self.phase_index,
            "phase_id": self.phase_id,
            "name": self.name,
            "label": self.name,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "span_seconds": self.span_seconds,
            "duration_seconds": self.span_seconds,
            "event_count": self.event_count,
            "event_ids": self.event_ids,
            "event_types": self.event_types,
            "domains": self.domains,
            "evidence_refs": self.evidence_refs,
        }


class TemporalSequenceEngine:
    """
    M10 Deterministic Temporal Sequence Engine.
    Provides strict causal ordering, boundary isolation, standardized windowing,
    and sequence summarization for M13 Console and M14 Copilot.
    """

    @staticmethod
    def _is_canonical_entity_token(text: Optional[str]) -> bool:
        if not text:
            return False
        return bool(re.fullmatch(r"(?:ENT|FLOW)_[A-Za-z0-9]+", str(text).strip()))

    def __init__(self, workspace_backend: Optional[Any] = None):
        self.backend = workspace_backend

    # -------------------------------------------------------------------------
    # Core Sequence Construction
    # -------------------------------------------------------------------------

    def build_sequence(
        self,
        events: Union[List[Dict[str, Any]], pd.DataFrame],
        entity_id: Optional[str] = None,
        canonical_entity_id: Optional[str] = None,
        case_id: Optional[str] = None,
        dataset: Optional[str] = None,
        require_strict_order: bool = True
    ) -> TemporalSequence:
        """
        Constructs a deterministic sequence of events independent of input row order.
        Never infers ordering from row order, string similarity, or graph proximity.
        """
        effective_entity_id = canonical_entity_id or entity_id

        if isinstance(events, pd.DataFrame):
            raw_records = events.to_dict(orient="records")
        else:
            raw_records = [dict(e) for e in events]

        if not raw_records:
            return TemporalSequence(
                entity_id=effective_entity_id or "UNKNOWN_ENTITY",
                case_id=case_id,
                items=[],
                ordering_basis=OrderingBasis.TIMESTAMP,
                is_causally_valid=True,
                unresolved_ties=[],
                dataset=dataset,
            )

        # Detect dataset / semantics
        detected_semantics = None
        for r in raw_records:
            sem = r.get("temporal_semantics")
            if sem:
                detected_semantics = str(sem)
                break

        has_authoritative_seqs = (
            len(raw_records) > 0
            and all(r.get("sequence_number") is not None for r in raw_records)
        )
        all_equal_epochs = len({r.get("epoch_time") for r in raw_records}) <= 1

        is_surrogate = (
            detected_semantics == TemporalSemantics.SEQUENCE_ORDER_SURROGATE
            or (dataset is not None and str(dataset).lower() == "unsw")
            or (has_authoritative_seqs and all_equal_epochs)
        )

        ordering_basis = (
            OrderingBasis.AUTHORITATIVE_SEQUENCE
            if is_surrogate
            else OrderingBasis.TIMESTAMP
        )

        # Entity scoping if entity_id provided
        scoped_records = []
        for r in raw_records:
            if entity_id is not None:
                ent = entity_id.strip()
                actor = str(r.get("actor_id", "")).strip()
                target = str(r.get("target_id", "")).strip()
                ent_field = str(r.get("canonical_entity_id", "")).strip()
                # Check entity match
                if ent not in {actor, target, ent_field}:
                    # Check backend entity aliases if available
                    if self.backend and hasattr(self.backend, "_entity_alias_to_canonical"):
                        c1 = self.backend._entity_alias_to_canonical.get(actor)
                        c2 = self.backend._entity_alias_to_canonical.get(target)
                        if ent not in {c1, c2}:
                            continue
                    else:
                        continue
            scoped_records.append(r)

        # Pre-process records into sortable tuples
        # Key: (primary_time_or_seq, authoritative_seq, event_id)
        sortable = []
        unresolved_ties: List[str] = []

        for r in scoped_records:
            ev_id = str(r.get("event_id", "")).strip()
            # Resolve epoch_time
            ep = r.get("epoch_time")
            if ep is None:
                ts = r.get("timestamp")
                if ts is not None:
                    try:
                        ep = float(ts)
                    except (ValueError, TypeError):
                        try:
                            ep = pd.to_datetime(ts, utc=True).timestamp()
                        except Exception:
                            ep = None

            # Resolve sequence number if present
            seq_num = r.get("sequence_number")
            if seq_num is None:
                seq_num = r.get("source_row_index")
            try:
                seq_num = int(seq_num) if seq_num is not None else None
            except (ValueError, TypeError):
                seq_num = None

            is_surrogate = (
                str(r.get("temporal_semantics", "")).upper() == "SEQUENCE_ORDER_SURROGATE"
            )

            # Sort key determination:
            # - Under sequence surrogate: sequence_number takes absolute precedence
            # - Under timestamp ordering: epoch_time takes precedence; sequence_number breaks ties
            if is_surrogate:
                primary_order = (seq_num if seq_num is not None else float("inf"))
                secondary_order = (ep if ep is not None else 0.0)
            else:
                primary_order = (ep if ep is not None else float("inf"))
                secondary_order = (seq_num if seq_num is not None else -1)

            sortable.append({
                "record": r,
                "event_id": ev_id,
                "epoch_time": ep,
                "sequence_number": seq_num,
                "primary_order": primary_order,
                "secondary_order": secondary_order,
                "is_surrogate": is_surrogate,
            })

        # Detect unresolved equal-timestamp ties before sorting
        for i in range(len(sortable)):
            for j in range(i + 1, len(sortable)):
                a, b = sortable[i], sortable[j]
                if not a["is_surrogate"] and not b["is_surrogate"]:
                    if (
                        a["epoch_time"] is not None
                        and b["epoch_time"] is not None
                        and a["epoch_time"] == b["epoch_time"]
                    ):
                        # Equal timestamp: check if authoritative secondary sequence breaks the tie
                        a_seq = a["sequence_number"]
                        b_seq = b["sequence_number"]
                        if a_seq is None or b_seq is None or a_seq == b_seq:
                            # Unresolvable tie - cannot break arbitrarily
                            if a["event_id"] not in unresolved_ties:
                                unresolved_ties.append(a["event_id"])
                            if b["event_id"] not in unresolved_ties:
                                unresolved_ties.append(b["event_id"])

        has_unresolved_tie = bool(unresolved_ties)

        # Deterministic sort using strictly authoritative fields
        def _sort_key(item):
            return (
                item["primary_order"],
                item["secondary_order"],
                item["event_id"],
            )

        sorted_items_meta = sorted(sortable, key=_sort_key)

        # Build TemporalSequenceItem list with sequence_index and time_delta
        sequence_items: List[TemporalSequenceItem] = []
        prev_epoch: Optional[float] = None

        for idx, s_meta in enumerate(sorted_items_meta):
            r = s_meta["record"]
            ev_id = s_meta["event_id"]
            ep = s_meta["epoch_time"]
            sn = s_meta["sequence_number"]
            is_surrogate = s_meta["is_surrogate"]

            # Compute time delta from previous
            delta = None
            if prev_epoch is not None and ep is not None and not is_surrogate:
                delta = round(ep - prev_epoch, 4)
            if ep is not None and not is_surrogate:
                prev_epoch = ep

            actor_raw = str(r.get("actor_id", "")).strip() if r.get("actor_id") is not None else ""
            target_raw = str(r.get("target_id", "")).strip() if r.get("target_id") is not None else ""

            # Authoritative canonical entity resolution
            c_ent = None
            if effective_entity_id:
                ent = effective_entity_id.strip()
                ent_field = str(r.get("canonical_entity_id", "")).strip()
                if ent in {actor_raw, target_raw, ent_field}:
                    c_ent = ent
                elif self.backend and hasattr(self.backend, "_resolve_entity_aliases"):
                    aliases = self.backend._resolve_entity_aliases(ent)
                    if actor_raw in aliases or target_raw in aliases or ent_field in aliases:
                        c_ent = ent
                elif self.backend and hasattr(self.backend, "_entity_alias_to_canonical"):
                    c1 = self.backend._entity_alias_to_canonical.get(actor_raw)
                    c2 = self.backend._entity_alias_to_canonical.get(target_raw)
                    c3 = self.backend._entity_alias_to_canonical.get(ent_field)
                    if ent in {c1, c2, c3}:
                        c_ent = ent

                if c_ent is None:
                    # Item belongs to a foreign entity; resolve its true canonical entity
                    if ent_field and self._is_canonical_entity_token(ent_field):
                        c_ent = ent_field
                    elif self.backend and hasattr(self.backend, "_entity_alias_to_canonical"):
                        c_ent = self.backend._entity_alias_to_canonical.get(actor_raw) or self.backend._entity_alias_to_canonical.get(target_raw) or actor_raw
                    else:
                        c_ent = actor_raw or "UNKNOWN_ENTITY"
            else:
                # No effective_entity_id provided
                ent_field = str(r.get("canonical_entity_id", "")).strip()
                if ent_field and self._is_canonical_entity_token(ent_field):
                    c_ent = ent_field
                elif self.backend and hasattr(self.backend, "_entity_alias_to_canonical"):
                    c_ent = self.backend._entity_alias_to_canonical.get(actor_raw) or self.backend._entity_alias_to_canonical.get(target_raw) or "UNRESOLVED_ENTITY"
                else:
                    c_ent = ent_field or "UNKNOWN_ENTITY"

            # Resolve evidence ref
            ev_ref = (
                r.get("evidence_ref")
                or r.get("evidence_id")
                or (f"hash:{r['sha256_hash'][:16]}" if r.get("sha256_hash") else None)
            )

            ts_str = str(r.get("timestamp", "")) if r.get("timestamp") else (
                pd.to_datetime(ep, unit="s", utc=True).isoformat() if ep is not None else ""
            )

            item_meta = {k: v for k, v in r.items() if k not in {
                "event_id", "timestamp", "epoch_time", "actor_id", "target_id",
                "event_type", "source_domain", "sha256_hash"
            }}
            item_meta["actor_id"] = actor_raw
            item_meta["target_id"] = target_raw
            if "case_id" in r:
                item_meta["case_id"] = r["case_id"]
            elif case_id:
                item_meta["case_id"] = case_id

            item = TemporalSequenceItem(
                event_id=ev_id,
                canonical_entity_id=c_ent,
                timestamp=ts_str,
                epoch_time=ep,
                event_type=str(r.get("event_type", "EVENT")),
                source_domain=str(r.get("source_domain", "UNKNOWN")),
                sequence_index=idx,
                evidence_ref=ev_ref,
                time_delta_from_previous=delta,
                ordering_basis=ordering_basis if not (ev_id in unresolved_ties) else OrderingBasis.UNRESOLVED,
                sequence_number=sn,
                actor_id=actor_raw,
                target_id=target_raw,
                metadata=item_meta,
            )
            sequence_items.append(item)

        is_valid = not has_unresolved_tie if require_strict_order else True

        return TemporalSequence(
            entity_id=effective_entity_id or (sequence_items[0].canonical_entity_id if sequence_items else "UNKNOWN_ENTITY"),
            case_id=case_id,
            items=sequence_items,
            ordering_basis=ordering_basis if not has_unresolved_tie else OrderingBasis.UNRESOLVED,
            is_causally_valid=is_valid,
            unresolved_ties=sorted(list(set(unresolved_ties))),
            dataset=dataset,
            temporal_semantics=detected_semantics,
        )

    # -------------------------------------------------------------------------
    # Pre-Trigger and Post-Trigger Sequences
    # -------------------------------------------------------------------------

    def get_pre_trigger_sequence(
        self,
        sequence: TemporalSequence,
        trigger_event_id: Optional[Union[str, TemporalSequenceItem, Dict[str, Any]]] = None,
        trigger_event: Optional[Union[TemporalSequenceItem, str, Dict[str, Any]]] = None,
        window_type: Optional[Union[TemporalWindowType, str]] = None,
        window_seconds: Optional[float] = None
    ) -> List[TemporalSequenceItem]:
        """
        Extracts strict causal history preceding trigger event T.
        Guarantees:
          1. event_timestamp < T
          2. event_timestamp > T MUST NOT appear
          3. event_timestamp == T MUST NOT appear unless authoritative sequence is strictly < trigger sequence
          4. Events lacking temporal ordering are excluded
        """
        t_target = trigger_event if trigger_event is not None else trigger_event_id
        if t_target is None:
            raise ValueError("Either trigger_event or trigger_event_id must be provided.")

        if isinstance(t_target, TemporalSequenceItem):
            target_id = t_target.event_id
        elif isinstance(t_target, dict) and "event_id" in t_target:
            target_id = t_target["event_id"]
        else:
            target_id = str(t_target)

        trigger_item = next((it for it in sequence.items if it.event_id == target_id), None)
        if not trigger_item:
            raise ValueError(f"Trigger event '{target_id}' not found in temporal sequence.")

        t_epoch = trigger_item.epoch_time
        t_seq = trigger_item.sequence_number

        # Resolve window duration
        duration: Optional[float] = None
        if window_type is not None:
            wt = TemporalWindowType(window_type) if isinstance(window_type, str) else window_type
            duration = WINDOW_DURATIONS.get(wt)
        elif window_seconds is not None:
            duration = float(window_seconds)

        min_time = (t_epoch - duration) if (duration is not None and t_epoch is not None) else None

        pre_trigger_items: List[TemporalSequenceItem] = []

        for it in sequence.items:
            # Skip trigger itself
            if it.event_id == target_id:
                continue

            # Check strict causality
            if sequence.ordering_basis == OrderingBasis.AUTHORITATIVE_SEQUENCE:
                if t_seq is not None and it.sequence_number is not None:
                    if it.sequence_number < t_seq:
                        pre_trigger_items.append(it)
                else:
                    if it.sequence_index < trigger_item.sequence_index:
                        pre_trigger_items.append(it)
                continue

            if it.epoch_time is None or t_epoch is None:
                continue

            # Rule 1 & 2: epoch_time < T
            if it.epoch_time < t_epoch:
                if min_time is not None and it.epoch_time < min_time:
                    continue
                if window_type is not None:
                    it.window_id = f"PRE_{window_type if isinstance(window_type, str) else window_type.value}"
                pre_trigger_items.append(it)
            elif it.epoch_time == t_epoch:
                # Rule 3 & 4: Only include equal timestamp if authoritative sequence exists and is strictly lower
                if (
                    it.sequence_number is not None
                    and t_seq is not None
                    and it.sequence_number < t_seq
                ):
                    if window_type is not None:
                        it.window_id = f"PRE_{window_type if isinstance(window_type, str) else window_type.value}"
                    pre_trigger_items.append(it)
                else:
                    continue

        return pre_trigger_items

    def get_post_trigger_sequence(
        self,
        sequence: TemporalSequence,
        trigger_event_id: Optional[Union[str, TemporalSequenceItem, Dict[str, Any]]] = None,
        trigger_event: Optional[Union[TemporalSequenceItem, str, Dict[str, Any]]] = None,
        window_type: Optional[Union[TemporalWindowType, str]] = None,
        window_seconds: Optional[float] = None
    ) -> List[TemporalSequenceItem]:
        """
        Extracts subsequent events strictly after trigger event T.
        Items are strictly labeled OBSERVED_FUTURE_HISTORY and never represented as causal history.
        """
        t_target = trigger_event if trigger_event is not None else trigger_event_id
        if t_target is None:
            raise ValueError("Either trigger_event or trigger_event_id must be provided.")

        if isinstance(t_target, TemporalSequenceItem):
            target_id = t_target.event_id
        elif isinstance(t_target, dict) and "event_id" in t_target:
            target_id = t_target["event_id"]
        else:
            target_id = str(t_target)

        trigger_item = next((it for it in sequence.items if it.event_id == target_id), None)
        if not trigger_item:
            raise ValueError(f"Trigger event '{target_id}' not found in temporal sequence.")

        t_epoch = trigger_item.epoch_time
        t_seq = trigger_item.sequence_number

        duration: Optional[float] = None
        if window_type is not None:
            wt = TemporalWindowType(window_type) if isinstance(window_type, str) else window_type
            duration = WINDOW_DURATIONS.get(wt)
        elif window_seconds is not None:
            duration = float(window_seconds)

        max_time = (t_epoch + duration) if (duration is not None and t_epoch is not None) else None

        post_trigger_items: List[TemporalSequenceItem] = []

        for it in sequence.items:
            if it.event_id == target_id:
                continue

            if sequence.ordering_basis == OrderingBasis.AUTHORITATIVE_SEQUENCE:
                if t_seq is not None and it.sequence_number is not None:
                    if it.sequence_number > t_seq:
                        post_trigger_items.append(it)
                else:
                    if it.sequence_index > trigger_item.sequence_index:
                        post_trigger_items.append(it)
                continue

            if it.epoch_time is None or t_epoch is None:
                continue

            # Strict subsequent: epoch_time > T
            if it.epoch_time > t_epoch:
                if max_time is not None and it.epoch_time > max_time:
                    continue
                if window_type is not None:
                    it.window_id = f"POST_{window_type if isinstance(window_type, str) else window_type.value}"
                post_trigger_items.append(it)
            elif it.epoch_time == t_epoch:
                if (
                    it.sequence_number is not None
                    and t_seq is not None
                    and it.sequence_number > t_seq
                ):
                    if window_type is not None:
                        it.window_id = f"POST_{window_type if isinstance(window_type, str) else window_type.value}"
                    post_trigger_items.append(it)

        return post_trigger_items

    # -------------------------------------------------------------------------
    # Window Generation
    # -------------------------------------------------------------------------

    def generate_windows(
        self,
        sequence: TemporalSequence,
        trigger_event_id: Optional[Union[str, TemporalSequenceItem, Dict[str, Any]]] = None,
        trigger_event: Optional[Union[TemporalSequenceItem, str, Dict[str, Any]]] = None
    ) -> Dict[str, List[TemporalSequenceItem]]:
        """
        Partitions sequence into canonical DFAP windows relative to trigger:
          - TIGHT: 3600s (1h)
          - MODERATE: 86400s (24h)
          - BROAD: 604800s (7d)
        """
        windows: Dict[str, List[TemporalSequenceItem]] = {}

        for w_type in [TemporalWindowType.TIGHT, TemporalWindowType.MODERATE, TemporalWindowType.BROAD]:
            pre = self.get_pre_trigger_sequence(sequence, trigger_event_id=trigger_event_id, trigger_event=trigger_event, window_type=w_type)
            post = self.get_post_trigger_sequence(sequence, trigger_event_id=trigger_event_id, trigger_event=trigger_event, window_type=w_type)
            windows[f"PRE_{w_type.value}"] = pre
            windows[f"POST_{w_type.value}"] = post

        return windows

    # -------------------------------------------------------------------------
    # Sequence Validation
    # -------------------------------------------------------------------------

    def validate_sequence(
        self,
        sequence: TemporalSequence,
        case_id: Optional[str] = None,
        entity_id: Optional[str] = None,
        canonical_entity_id: Optional[str] = None,
    ) -> ValidationResult:
        """
        Validates temporal safety, monotonicity, absence of unresolved ties,
        and boundary isolation (no cross-entity or cross-case leakage).
        """
        violations: List[str] = []

        target_entity = canonical_entity_id or entity_id or sequence.entity_id
        target_case = case_id or sequence.case_id

        # 1. Entity and Case Isolation
        if entity_id is not None and sequence.entity_id != entity_id:
            violations.append(
                f"Entity boundary violation: sequence entity '{sequence.entity_id}' differs from expected '{entity_id}'."
            )

        if case_id is not None and sequence.case_id is not None and sequence.case_id != case_id:
            violations.append(
                f"Case boundary violation: sequence case '{sequence.case_id}' differs from expected '{case_id}'."
            )

        for it in sequence.items:
            if target_entity and it.canonical_entity_id and it.canonical_entity_id != target_entity:
                violations.append(
                    f"Entity mismatch: item '{it.event_id}' has entity '{it.canonical_entity_id}' "
                    f"different from expected entity '{target_entity}'."
                )
            item_case = it.metadata.get("case_id") if it.metadata else None
            if target_case and item_case and item_case != target_case:
                violations.append(
                    f"Case mismatch: item '{it.event_id}' has case '{item_case}' "
                    f"different from expected case '{target_case}'."
                )

        # 2. Monotonic Non-Decreasing Ordering
        if sequence.ordering_basis == OrderingBasis.TIMESTAMP:
            prev_time = -float("inf")
            for it in sequence.items:
                if it.epoch_time is not None:
                    if it.epoch_time < prev_time:
                        violations.append(
                            f"Monotonicity violation: item '{it.event_id}' with timestamp {it.epoch_time} "
                            f"is smaller than predecessor timestamp {prev_time}."
                        )
                    prev_time = it.epoch_time

        elif sequence.ordering_basis == OrderingBasis.AUTHORITATIVE_SEQUENCE:
            prev_seq = -1
            for it in sequence.items:
                if it.sequence_number is not None:
                    if it.sequence_number < prev_seq:
                        violations.append(
                            f"Sequence monotonicity violation: item '{it.event_id}' seq {it.sequence_number} "
                            f"< previous seq {prev_seq}."
                        )
                    prev_seq = it.sequence_number

        # 3. Unresolved Ties
        if sequence.unresolved_ties:
            violations.append(
                f"Unresolved equal-timestamp ties detected without authoritative sequence proof: "
                f"{', '.join(sequence.unresolved_ties)}."
            )

        return ValidationResult(is_valid=(len(violations) == 0), issues=violations)

    # -------------------------------------------------------------------------
    # Explainable Sequence Summary
    # -------------------------------------------------------------------------

    def summarize_sequence(
        self,
        sequence: TemporalSequence,
        trigger_event: Optional[Union[TemporalSequenceItem, str, Dict[str, Any]]] = None,
        trigger_event_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Builds a structured, explainable causal sequence summary:
          Trigger: E4
          History: E1 -> E2 -> E3
          Forward: E5 -> E6
        """
        if not sequence.items:
            return {
                "entity_id": sequence.entity_id,
                "case_id": sequence.case_id,
                "trigger_event": None,
                "history_items": [],
                "preceding_history": [],
                "forward_items": [],
                "subsequent_events": [],
                "evidence_refs": [],
                "provenance_refs": [],
                "text_summary": "Empty temporal sequence: zero events observed.",
            }

        # Select trigger: specified, or last item, or middle
        trigger_item = None
        if trigger_event_id:
            trigger_item = next((it for it in sequence.items if it.event_id == trigger_event_id), None)
        elif trigger_event is not None:
            if isinstance(trigger_event, TemporalSequenceItem):
                trigger_item = trigger_event
            elif isinstance(trigger_event, dict) and "event_id" in trigger_event:
                trigger_item = next((it for it in sequence.items if it.event_id == trigger_event["event_id"]), None)
            elif isinstance(trigger_event, str):
                trigger_item = next((it for it in sequence.items if it.event_id == trigger_event), None)

        if not trigger_item and sequence.items:
            trigger_item = sequence.items[-1]

        t_id = trigger_item.event_id if trigger_item else None
        pre_items = self.get_pre_trigger_sequence(sequence, trigger_item) if trigger_item else []
        post_items = self.get_post_trigger_sequence(sequence, trigger_item) if trigger_item else []

        all_ev_refs = [
            it.evidence_ref for it in (([trigger_item] if trigger_item else []) + pre_items + post_items)
            if it.evidence_ref
        ]

        # Format chain strings
        hist_chain = " -> ".join(it.event_id for it in pre_items) if pre_items else "NONE"
        fwd_chain = " -> ".join(it.event_id for it in post_items) if post_items else "NONE"

        text_summary = (
            f"Temporal Sequence Summary for entity '{sequence.entity_id}':\n"
            f"  History (Pre-Trigger): {hist_chain}\n"
            f"  Trigger: {trigger_item.event_id if trigger_item else 'NONE'} ({trigger_item.event_type if trigger_item else ''} @ {trigger_item.timestamp if trigger_item else ''})\n"
            f"  Forward (Observed Subsequent): {fwd_chain}\n"
            f"  Ordering Basis: {sequence.ordering_basis.value}\n"
            f"  Temporal Semantics: {sequence.temporal_semantics or 'OBSERVED_TIMESTAMP'}"
        )

        pre_list = [it.to_dict() for it in pre_items]
        post_list = [it.to_dict() for it in post_items]

        return {
            "entity_id": sequence.entity_id,
            "case_id": sequence.case_id,
            "trigger_event": trigger_item.to_dict() if trigger_item else None,
            "history_items": pre_list,
            "preceding_history": pre_list,
            "forward_items": post_list,
            "subsequent_events": post_list,
            "history_chain": hist_chain,
            "forward_chain": fwd_chain,
            "evidence_refs": sorted(list(set(all_ev_refs))),
            "provenance_refs": sorted(list(set(all_ev_refs))),
            "ordering_basis": sequence.ordering_basis.value,
            "is_causally_valid": sequence.is_causally_valid,
            "unresolved_ties": sequence.unresolved_ties,
            "text_summary": text_summary,
        }

    # -------------------------------------------------------------------------
    # Sequence Feature Extraction
    # -------------------------------------------------------------------------

    def extract_features(
        self,
        sequence: TemporalSequence,
        rapid_threshold_seconds: float = 60.0,
        reference_sequence: Optional[TemporalSequence] = None,
        discovered_motifs: Optional[List[Any]] = None
    ) -> TemporalSequenceFeatures:
        """
        Extracts deterministic structural and inter-event timing features for downstream M9/M11 consumption.
        Does not assign guilt or maliciousness.
        """
        n = len(sequence.items)
        if n == 0:
            return TemporalSequenceFeatures(
                sequence_length=0,
                unique_event_types=0,
                unique_domains=0,
                mean_inter_event_time=0.0,
                median_inter_event_time=0.0,
                max_inter_event_gap=0.0,
                min_inter_event_gap=0.0,
                rapid_transition_count=0,
                repeated_transition_count=0,
                cross_domain_transition_count=0,
                unique_transition_count=0,
                novel_transition_count=None,
            )

        unique_types = len(set(it.event_type for it in sequence.items))
        unique_domains = len(set(it.source_domain for it in sequence.items))

        gaps: List[float] = []
        for i in range(1, n):
            prev = sequence.items[i - 1]
            curr = sequence.items[i]
            if curr.epoch_time is not None and prev.epoch_time is not None:
                gap = max(0.0, curr.epoch_time - prev.epoch_time)
            elif curr.time_delta_from_previous is not None:
                gap = max(0.0, curr.time_delta_from_previous)
            else:
                gap = 1.0
            gaps.append(round(gap, 4))

        if gaps:
            mean_gap = round(float(np.mean(gaps)), 4)
            median_gap = round(float(np.median(gaps)), 4)
            max_gap = round(float(np.max(gaps)), 4)
            min_gap = round(float(np.min(gaps)), 4)
            rapid_count = sum(1 for g in gaps if g <= rapid_threshold_seconds)
        else:
            mean_gap = 0.0
            median_gap = 0.0
            max_gap = 0.0
            min_gap = 0.0
            rapid_count = 0

        repeated_count = 0
        cross_domain_count = 0
        observed_transitions = set()

        for i in range(1, n):
            prev = sequence.items[i - 1]
            curr = sequence.items[i]
            if curr.event_type == prev.event_type:
                repeated_count += 1
            if curr.source_domain != prev.source_domain:
                cross_domain_count += 1
            observed_transitions.add((prev.event_type, curr.event_type))

        unique_trans_count = len(observed_transitions)
        novel_trans_count = None
        if reference_sequence is not None and len(reference_sequence.items) > 1:
            ref_transitions = set()
            for i in range(1, len(reference_sequence.items)):
                ref_transitions.add((reference_sequence.items[i - 1].event_type, reference_sequence.items[i].event_type))
            novel_trans_count = len(observed_transitions - ref_transitions)

        motif_count = 0
        motif_membership = []
        motif_freq = {}
        motif_cross_dom = 0
        if discovered_motifs:
            motif_count = len(discovered_motifs)
            motif_membership = [m.motif_id for m in discovered_motifs]
            motif_freq = {m.motif_id: m.cluster_size for m in discovered_motifs}
            motif_cross_dom = sum(1 for m in discovered_motifs if len(set(m.representative_domains)) > 1)

        features_dict = {
            "sequence_length": n,
            "unique_event_types": unique_types,
            "unique_domains": unique_domains,
            "mean_inter_event_time": mean_gap,
            "median_inter_event_time": median_gap,
            "max_inter_event_gap": max_gap,
            "min_inter_event_gap": min_gap,
            "rapid_transition_count": rapid_count,
            "repeated_transition_count": repeated_count,
            "cross_domain_transition_count": cross_domain_count,
            "unique_transition_count": unique_trans_count,
        }
        if novel_trans_count is not None:
            features_dict["novel_transition_count"] = novel_trans_count
        if motif_count > 0:
            features_dict["discovered_motif_count"] = motif_count
            features_dict["discovered_motif_membership"] = motif_membership
            features_dict["discovered_motif_frequency"] = motif_freq
            features_dict["discovered_motif_cross_domain"] = motif_cross_dom

        return TemporalSequenceFeatures(
            sequence_length=n,
            unique_event_types=unique_types,
            unique_domains=unique_domains,
            mean_inter_event_time=mean_gap,
            median_inter_event_time=median_gap,
            max_inter_event_gap=max_gap,
            min_inter_event_gap=min_gap,
            rapid_transition_count=rapid_count,
            repeated_transition_count=repeated_count,
            cross_domain_transition_count=cross_domain_count,
            unique_transition_count=unique_trans_count,
            novel_transition_count=novel_trans_count,
            discovered_motif_count=motif_count,
            discovered_motif_membership=motif_membership,
            discovered_motif_frequency=motif_freq,
            discovered_motif_cross_domain=motif_cross_dom,
            features_dict=features_dict,
        )

    # -------------------------------------------------------------------------
    # Temporal Transition Analysis
    # -------------------------------------------------------------------------

    def analyze_transitions(
        self,
        sequence: TemporalSequence
    ) -> Dict[str, List[TemporalTransition]]:
        """
        Derives deterministic transition profiles:
          event_type -> event_type
          domain -> domain
          domain -> event_type
        """
        n = len(sequence.items)
        ev_map: Dict[Tuple[str, str], Dict[str, Any]] = {}
        dom_map: Dict[Tuple[str, str], Dict[str, Any]] = {}
        dom_ev_map: Dict[Tuple[str, str], Dict[str, Any]] = {}

        for i in range(1, n):
            prev = sequence.items[i - 1]
            curr = sequence.items[i]
            if curr.epoch_time is not None and prev.epoch_time is not None:
                gap = max(0.0, curr.epoch_time - prev.epoch_time)
            elif curr.time_delta_from_previous is not None:
                gap = max(0.0, curr.time_delta_from_previous)
            else:
                gap = 1.0

            doms = sorted(list({prev.source_domain, curr.source_domain}))
            ev_refs = [r for r in [prev.evidence_ref, curr.evidence_ref] if r]

            # 1. Event -> Event
            k_ev = (prev.event_type, curr.event_type)
            if k_ev not in ev_map:
                ev_map[k_ev] = {"gaps": [], "domains": set(), "evidence_refs": set()}
            ev_map[k_ev]["gaps"].append(gap)
            ev_map[k_ev]["domains"].update(doms)
            ev_map[k_ev]["evidence_refs"].update(ev_refs)

            # 2. Domain -> Domain
            k_dom = (prev.source_domain, curr.source_domain)
            if k_dom not in dom_map:
                dom_map[k_dom] = {"gaps": [], "domains": set(), "evidence_refs": set()}
            dom_map[k_dom]["gaps"].append(gap)
            dom_map[k_dom]["domains"].update(doms)
            dom_map[k_dom]["evidence_refs"].update(ev_refs)

            # 3. Domain -> Event
            k_de = (prev.source_domain, curr.event_type)
            if k_de not in dom_ev_map:
                dom_ev_map[k_de] = {"gaps": [], "domains": set(), "evidence_refs": set()}
            dom_ev_map[k_de]["gaps"].append(gap)
            dom_ev_map[k_de]["domains"].update(doms)
            dom_ev_map[k_de]["evidence_refs"].update(ev_refs)

        def _build_transitions(m: Dict[Tuple[str, str], Dict[str, Any]], t_type: str) -> List[TemporalTransition]:
            result = []
            for (src, tgt), d in m.items():
                gaps = d["gaps"]
                tr = TemporalTransition(
                    source=src,
                    target=tgt,
                    transition_type=t_type,
                    count=len(gaps),
                    mean_gap=round(float(np.mean(gaps)), 4) if gaps else 0.0,
                    median_gap=round(float(np.median(gaps)), 4) if gaps else 0.0,
                    min_gap=round(float(np.min(gaps)), 4) if gaps else 0.0,
                    max_gap=round(float(np.max(gaps)), 4) if gaps else 0.0,
                    participating_domains=sorted(list(d["domains"])),
                    evidence_refs=sorted(list(d["evidence_refs"])),
                )
                result.append(tr)
            result.sort(key=lambda x: (-x.count, x.source, x.target))
            return result

        de_transitions = _build_transitions(dom_ev_map, "domain_to_event")
        return {
            "event_transitions": _build_transitions(ev_map, "event_to_event"),
            "domain_transitions": _build_transitions(dom_map, "domain_to_domain"),
            "domain_event_transitions": de_transitions,
            "domain_to_event": de_transitions,
        }

    # -------------------------------------------------------------------------
    # Temporal Pattern Detection
    # -------------------------------------------------------------------------

    def detect_patterns(
        self,
        sequence: TemporalSequence,
        min_len: int = 2,
        max_len: int = 4,
        min_count: int = 1
    ) -> List[Dict[str, Any]]:
        """
        Detects repeated sub-sequences and n-grams without assigning threat verdicts.
        """
        n = len(sequence.items)
        if n < min_len:
            return []

        pattern_matches: Dict[Tuple[str, ...], List[List[TemporalSequenceItem]]] = {}

        for length in range(min_len, min(max_len + 1, n + 1)):
            for i in range(n - length + 1):
                window = sequence.items[i : i + length]
                pat_key = tuple(it.event_type for it in window)
                if pat_key not in pattern_matches:
                    pattern_matches[pat_key] = []
                pattern_matches[pat_key].append(window)

        results = []
        for pat_key, occurrences in pattern_matches.items():
            if len(occurrences) < min_count:
                continue

            all_event_ids = []
            all_ev_refs = set()
            start_times = []
            end_times = []
            spans = []

            for occ in occurrences:
                all_event_ids.extend(it.event_id for it in occ)
                for it in occ:
                    if it.evidence_ref:
                        all_ev_refs.add(it.evidence_ref)
                start_ts = occ[0].timestamp or (str(occ[0].epoch_time) if occ[0].epoch_time is not None else "")
                end_ts = occ[-1].timestamp or (str(occ[-1].epoch_time) if occ[-1].epoch_time is not None else "")
                start_times.append(start_ts)
                end_times.append(end_ts)
                if occ[-1].epoch_time is not None and occ[0].epoch_time is not None:
                    spans.append(max(0.0, occ[-1].epoch_time - occ[0].epoch_time))
                else:
                    spans.append(float(len(occ) - 1))

            results.append({
                "matched_pattern": " -> ".join(pat_key),
                "pattern": list(pat_key),
                "pattern_tuple": list(pat_key),
                "count": len(occurrences),
                "matching_event_ids": sorted(list(set(all_event_ids))),
                "start_time": start_times[0] if start_times else None,
                "end_time": end_times[-1] if end_times else None,
                "span_seconds": round(float(np.mean(spans)), 4) if spans else 0.0,
                "time_span_seconds": round(float(np.mean(spans)), 4) if spans else 0.0,
                "evidence_refs": sorted(list(all_ev_refs)),
            })

        results.sort(key=lambda p: (-p["count"], -len(p["pattern_tuple"]), p["matched_pattern"]))
        return results

    # -------------------------------------------------------------------------
    # Reusable Temporal Motifs
    # -------------------------------------------------------------------------

    def detect_motifs(
        self,
        sequence: TemporalSequence
    ) -> List[MotifMatch]:
        """
        Evaluates sequence against canonical DFAP motifs:
          - ACCESS_CHANGE_TRANSFER
          - TRANSFER_BURST
          - MULTI_DOMAIN_ACTIVITY
          - RAPID_TRANSACTION_BURST
          - REPEATED_ACTION_SEQUENCE
        Does not assign threat verdicts.
        """
        items = sequence.items
        n = len(items)
        motifs: List[MotifMatch] = []

        # 1. ACCESS_CHANGE_TRANSFER
        auth_types = {"LOGIN", "AUTH", "AUTHENTICATE", "SIGNON", "SESSION_START"}
        change_types = {"KEY_ROTATION", "ROTATION", "PASSWORD_CHANGE", "CREDENTIAL_UPDATE", "CONFIG_CHANGE", "PRIVILEGE_ESCALATION", "API_KEY_ROTATION"}
        action_types = {"TRANSFER", "PAYMENT", "UNAUTHORIZED_EXPORT", "EXPORT", "EXFILTRATION", "WITHDRAWAL", "TRANSACTION"}

        act_match_ids = []
        act_ev_refs = set()
        act_domains = set()
        has_auth, has_change, has_action = False, False, False

        for it in items:
            t = it.event_type.upper()
            if not has_auth and (t in auth_types or it.source_domain.upper() == "AUTH"):
                has_auth = True
                act_match_ids.append(it.event_id)
                act_domains.add(it.source_domain)
                if it.evidence_ref:
                    act_ev_refs.add(it.evidence_ref)
            elif has_auth and not has_change and (t in change_types or it.source_domain.upper() in {"IAM", "SECURITY"}):
                has_change = True
                act_match_ids.append(it.event_id)
                act_domains.add(it.source_domain)
                if it.evidence_ref:
                    act_ev_refs.add(it.evidence_ref)
            elif has_auth and has_change and not has_action and (t in action_types or it.source_domain.upper() in {"FINANCIAL", "SECURITY"}):
                has_action = True
                act_match_ids.append(it.event_id)
                act_domains.add(it.source_domain)
                if it.evidence_ref:
                    act_ev_refs.add(it.evidence_ref)

        act_matched = has_auth and has_change and has_action
        act_fit = 1.0 if act_matched else (0.66 if (has_auth and (has_change or has_action)) else 0.0)
        span_act = 0.0
        if act_matched and act_match_ids:
            first_it = next((it for it in items if it.event_id == act_match_ids[0]), None)
            last_it = next((it for it in items if it.event_id == act_match_ids[-1]), None)
            if last_it and first_it and last_it.epoch_time is not None and first_it.epoch_time is not None:
                span_act = max(0.0, last_it.epoch_time - first_it.epoch_time)

        motifs.append(MotifMatch(
            motif_id="ACCESS_CHANGE_TRANSFER",
            matched=act_matched,
            fit_score=act_fit,
            matching_event_ids=act_match_ids if act_matched else [],
            temporal_span=span_act,
            participating_domains=sorted(list(act_domains)) if act_matched else [],
            evidence_refs=sorted(list(act_ev_refs)) if act_matched else [],
            description="Access authentication followed sequentially by credential/key modification and subsequent transfer or export activity."
        ))

        # 2. TRANSFER_BURST
        transfer_items = [it for it in items if it.event_type.upper() in action_types or it.source_domain.upper() == "FINANCIAL"]
        tb_matched = False
        tb_ids = []
        tb_domains = set()
        tb_ev_refs = set()
        tb_span = 0.0

        if len(transfer_items) >= 3:
            for i in range(len(transfer_items) - 2):
                w = transfer_items[i : i + 3]
                if w[-1].epoch_time is not None and w[0].epoch_time is not None:
                    diff = w[-1].epoch_time - w[0].epoch_time
                    if diff <= 3600.0:
                        tb_matched = True
                        tb_ids = [it.event_id for it in w]
                        tb_domains = {it.source_domain for it in w}
                        tb_ev_refs = {it.evidence_ref for it in w if it.evidence_ref}
                        tb_span = diff
                        break

        motifs.append(MotifMatch(
            motif_id="TRANSFER_BURST",
            matched=tb_matched,
            fit_score=1.0 if tb_matched else min(1.0, len(transfer_items) / 3.0),
            matching_event_ids=tb_ids,
            temporal_span=tb_span,
            participating_domains=sorted(list(tb_domains)),
            evidence_refs=sorted(list(tb_ev_refs)),
            description="Three or more transfer/financial activity events occurring within a concentrated one-hour window."
        ))

        # 3. MULTI_DOMAIN_ACTIVITY
        distinct_domains = sorted(list(set(it.source_domain for it in items)))
        mda_matched = len(distinct_domains) >= 3
        mda_ids = [it.event_id for it in items] if mda_matched else []
        mda_ev = [it.evidence_ref for it in items if it.evidence_ref] if mda_matched else []
        mda_span = (items[-1].epoch_time - items[0].epoch_time) if (n > 1 and items[-1].epoch_time is not None and items[0].epoch_time is not None) else 0.0

        motifs.append(MotifMatch(
            motif_id="MULTI_DOMAIN_ACTIVITY",
            matched=mda_matched,
            fit_score=min(1.0, len(distinct_domains) / 3.0),
            matching_event_ids=mda_ids,
            temporal_span=mda_span,
            participating_domains=distinct_domains,
            evidence_refs=sorted(list(set(mda_ev))),
            description="Activity sequence traversing three or more distinct telemetry source domains."
        ))

        # 4. RAPID_TRANSACTION_BURST
        rtb_matched = False
        rtb_ids = []
        rtb_ev = set()
        rtb_domains = set()
        rtb_span = 0.0

        for i in range(n - 2):
            w = items[i : i + 3]
            g1 = (w[1].epoch_time - w[0].epoch_time) if (w[1].epoch_time is not None and w[0].epoch_time is not None) else None
            g2 = (w[2].epoch_time - w[1].epoch_time) if (w[2].epoch_time is not None and w[1].epoch_time is not None) else None
            if g1 is not None and g2 is not None and g1 <= 60.0 and g2 <= 60.0:
                rtb_matched = True
                rtb_ids = [it.event_id for it in w]
                rtb_domains = {it.source_domain for it in w}
                rtb_ev = {it.evidence_ref for it in w if it.evidence_ref}
                rtb_span = g1 + g2
                break

        motifs.append(MotifMatch(
            motif_id="RAPID_TRANSACTION_BURST",
            matched=rtb_matched,
            fit_score=1.0 if rtb_matched else 0.0,
            matching_event_ids=rtb_ids,
            temporal_span=rtb_span,
            participating_domains=sorted(list(rtb_domains)),
            evidence_refs=sorted(list(rtb_ev)),
            description="Three or more successive events occurring with inter-event gap <= 60s."
        ))

        # 5. REPEATED_ACTION_SEQUENCE
        ras_matched = False
        ras_ids = []
        ras_domains = set()
        ras_ev = set()
        ras_span = 0.0

        for i in range(n - 2):
            if items[i].event_type == items[i + 1].event_type == items[i + 2].event_type:
                ras_matched = True
                w = items[i : i + 3]
                ras_ids = [it.event_id for it in w]
                ras_domains = {it.source_domain for it in w}
                ras_ev = {it.evidence_ref for it in w if it.evidence_ref}
                if w[-1].epoch_time is not None and w[0].epoch_time is not None:
                    ras_span = max(0.0, w[-1].epoch_time - w[0].epoch_time)
                break

        if not ras_matched:
            action_seqs = self.detect_patterns(sequence, min_len=2, max_len=3, min_count=2)
            if action_seqs:
                ras_matched = True
                top_pat = action_seqs[0]
                ras_ids = top_pat["matching_event_ids"]
                ras_ev = set(top_pat["evidence_refs"])
                ras_span = top_pat["span_seconds"]
                for eid in ras_ids:
                    it = next((item for item in items if item.event_id == eid), None)
                    if it:
                        ras_domains.add(it.source_domain)

        motifs.append(MotifMatch(
            motif_id="REPEATED_ACTION_SEQUENCE",
            matched=ras_matched,
            fit_score=1.0 if ras_matched else 0.0,
            matching_event_ids=ras_ids,
            temporal_span=ras_span,
            participating_domains=sorted(list(ras_domains)),
            evidence_refs=sorted(list(ras_ev)),
            description="Three or more consecutive identical event types or repeated action sequence across the observation window."
        ))

        return motifs

    def discover_motifs(
        self,
        sequence: TemporalSequence,
        min_length: Optional[int] = None,
        max_length: Optional[int] = None,
        distance_threshold: Optional[float] = None,
        min_cluster_size: Optional[int] = None,
        starting_motif_index: Optional[int] = None
    ):
        """
        Unsupervised motif discovery: extracts recurring subsequences, computes DTW distance matrix,
        executes agglomerative clustering, and reconciles patterns against catalog.
        """
        from dfap.investigation.temporal_motif_discovery import UnsupervisedMotifDiscoveryEngine
        engine = UnsupervisedMotifDiscoveryEngine(sequence_engine=self)
        return engine.discover_motifs(
            sequence=sequence,
            min_length=min_length,
            max_length=max_length,
            distance_threshold=distance_threshold,
            min_cluster_size=min_cluster_size,
            starting_motif_index=starting_motif_index
        )

    # -------------------------------------------------------------------------
    # Sequence Comparison (Levenshtein + DTW)
    # -------------------------------------------------------------------------

    def compare_sequences(
        self,
        seq_a: TemporalSequence,
        seq_b: TemporalSequence
    ) -> Dict[str, Any]:
        """
        Compares two temporal sequences using normalized edit distance (structural)
        and Dynamic Time Warping (timing).
        """
        types_a = [it.event_type for it in seq_a.items]
        types_b = [it.event_type for it in seq_b.items]

        # 1. Structural Edit Distance (Levenshtein)
        len_a, len_b = len(types_a), len(types_b)
        dp = [[0] * (len_b + 1) for _ in range(len_a + 1)]
        for i in range(len_a + 1):
            dp[i][0] = i
        for j in range(len_b + 1):
            dp[0][j] = j

        for i in range(1, len_a + 1):
            for j in range(1, len_b + 1):
                cost = 0 if types_a[i - 1] == types_b[j - 1] else 1
                dp[i][j] = min(
                    dp[i - 1][j] + 1,      # deletion
                    dp[i][j - 1] + 1,      # insertion
                    dp[i - 1][j - 1] + cost # substitution
                )
        edit_dist = dp[len_a][len_b]
        max_len = max(len_a, len_b, 1)
        sim_score = round(1.0 - (edit_dist / max_len), 4)

        # 2. Timestamp / DTW Distance
        deltas_a = [it.time_delta_from_previous if it.time_delta_from_previous is not None else 1.0 for it in seq_a.items]
        deltas_b = [it.time_delta_from_previous if it.time_delta_from_previous is not None else 1.0 for it in seq_b.items]

        dtw_dist = 0.0
        if deltas_a and deltas_b:
            dtw_mat = [[float("inf")] * (len(deltas_b) + 1) for _ in range(len(deltas_a) + 1)]
            dtw_mat[0][0] = 0.0
            for i in range(1, len(deltas_a) + 1):
                for j in range(1, len(deltas_b) + 1):
                    cost = abs(deltas_a[i - 1] - deltas_b[j - 1])
                    dtw_mat[i][j] = cost + min(dtw_mat[i - 1][j], dtw_mat[i][j - 1], dtw_mat[i - 1][j - 1])
            dtw_dist = round(dtw_mat[len(deltas_a)][len(deltas_b)] / (len(deltas_a) + len(deltas_b)), 4)

        # 3. Differences
        set_a = set(types_a)
        set_b = set(types_b)
        missing_in_b = sorted(list(set_a - set_b))
        extra_in_b = sorted(list(set_b - set_a))

        def _get_2grams(s):
            return {" -> ".join((s[i], s[i + 1])) for i in range(len(s) - 1)}

        common_pats = sorted(list(_get_2grams(types_a) & _get_2grams(types_b)))

        mean_gap_a = float(np.mean(deltas_a)) if deltas_a else 0.0
        mean_gap_b = float(np.mean(deltas_b)) if deltas_b else 0.0

        return {
            "similarity_score": sim_score,
            "alignment_similarity": sim_score,
            "structural_distance": edit_dist,
            "timing_distance": dtw_dist if (deltas_a and deltas_b) else None,
            "edit_distance": edit_dist,
            "edit_distance_normalized": round(edit_dist / max_len, 4),
            "dtw_distance": dtw_dist,
            "common_patterns": common_pats,
            "common_event_types": sorted(list(set_a & set_b)),
            "only_in_a": missing_in_b,
            "only_in_b": extra_in_b,
            "missing_in_b": missing_in_b,
            "extra_in_b": extra_in_b,
            "sequence_a_length": len_a,
            "sequence_b_length": len_b,
            "ordering_differences": f"Sequence A ({len_a} events) and B ({len_b} events) differ by {edit_dist} edit operations.",
            "timing_differences": f"Mean inter-event gap: A={mean_gap_a:.1f}s vs B={mean_gap_b:.1f}s (DTW cost={dtw_dist}).",
        }

    # -------------------------------------------------------------------------
    # Sequence Phasing / Compression
    # -------------------------------------------------------------------------

    def compress_phases(
        self,
        sequence: TemporalSequence,
        gap_threshold_seconds: Optional[float] = None
    ) -> List[SequencePhase]:
        """
        Deterministically groups contiguous activity into explainable phases
        based on temporal gaps and domain continuity.
        """
        items = sequence.items
        n = len(items)
        if n == 0:
            return []

        if gap_threshold_seconds is None:
            gaps = [it.time_delta_from_previous for it in items if it.time_delta_from_previous is not None]
            med = float(np.median(gaps)) if gaps else 60.0
            gap_threshold_seconds = max(3600.0, 3.0 * med)

        phases: List[SequencePhase] = []
        curr_items = [items[0]]

        for i in range(1, n):
            it = items[i]
            delta = it.time_delta_from_previous
            is_large_gap = (delta is not None and delta > gap_threshold_seconds)
            is_domain_shift = (it.source_domain != curr_items[-1].source_domain and len(curr_items) >= 3)

            if is_large_gap or is_domain_shift:
                p_idx = len(phases) + 1
                doms = sorted(list({x.source_domain for x in curr_items}))
                primary_dom = curr_items[0].source_domain if len(doms) == 1 else "MULTI_DOMAIN"
                s_time = curr_items[0].timestamp or str(curr_items[0].epoch_time)
                e_time = curr_items[-1].timestamp or str(curr_items[-1].epoch_time)
                span = (curr_items[-1].epoch_time - curr_items[0].epoch_time) if (curr_items[-1].epoch_time is not None and curr_items[0].epoch_time is not None) else float(len(curr_items))

                phases.append(SequencePhase(
                    phase_index=p_idx,
                    phase_id=f"PHASE_{p_idx:02d}",
                    name=f"Phase {p_idx}: {primary_dom} ({len(curr_items)} events)",
                    start_time=s_time,
                    end_time=e_time,
                    span_seconds=max(0.0, span),
                    event_count=len(curr_items),
                    event_ids=[x.event_id for x in curr_items],
                    event_types=[x.event_type for x in curr_items],
                    domains=doms,
                    evidence_refs=sorted(list({x.evidence_ref for x in curr_items if x.evidence_ref})),
                ))
                curr_items = [it]
            else:
                curr_items.append(it)

        if curr_items:
            p_idx = len(phases) + 1
            doms = sorted(list({x.source_domain for x in curr_items}))
            primary_dom = curr_items[0].source_domain if len(doms) == 1 else "MULTI_DOMAIN"
            s_time = curr_items[0].timestamp or str(curr_items[0].epoch_time)
            e_time = curr_items[-1].timestamp or str(curr_items[-1].epoch_time)
            span = (curr_items[-1].epoch_time - curr_items[0].epoch_time) if (curr_items[-1].epoch_time is not None and curr_items[0].epoch_time is not None) else float(len(curr_items))

            phases.append(SequencePhase(
                phase_index=p_idx,
                phase_id=f"PHASE_{p_idx:02d}",
                name=f"Phase {p_idx}: {primary_dom} ({len(curr_items)} events)",
                start_time=s_time,
                end_time=e_time,
                span_seconds=max(0.0, span),
                event_count=len(curr_items),
                event_ids=[x.event_id for x in curr_items],
                event_types=[x.event_type for x in curr_items],
                domains=doms,
                evidence_refs=sorted(list({x.evidence_ref for x in curr_items if x.evidence_ref})),
            ))

        return phases

    # -------------------------------------------------------------------------
    # Temporal Transition Graph
    # -------------------------------------------------------------------------

    def build_transition_graph(
        self,
        sequence: TemporalSequence
    ) -> Dict[str, Any]:
        """
        Constructs a directed graph representing observed transitions between event types and domains.
        """
        analysis = self.analyze_transitions(sequence)
        ev_trans = analysis["event_transitions"]

        node_counts: Dict[str, int] = {}
        for it in sequence.items:
            node_counts[it.event_type] = node_counts.get(it.event_type, 0) + 1

        nodes = [
            {"id": et, "label": et, "type": "event_type", "frequency": count}
            for et, count in node_counts.items()
        ]

        edges = [
            {
                "source": t.source,
                "target": t.target,
                "weight": t.count,
                "mean_gap": t.mean_gap,
                "min_gap": t.min_gap,
                "max_gap": t.max_gap,
                "participating_domains": t.participating_domains,
                "evidence_refs": t.evidence_refs,
            }
            for t in ev_trans
        ]

        return {
            "entity_id": sequence.entity_id,
            "case_id": sequence.case_id,
            "nodes": nodes,
            "edges": edges,
            "node_count": len(nodes),
            "edge_count": len(edges),
        }

    # -------------------------------------------------------------------------
    # Investigator-Ready Timeline View
    # -------------------------------------------------------------------------

    def format_investigator_timeline(
        self,
        sequence: TemporalSequence,
        trigger_event: Optional[Union[TemporalSequenceItem, str, Dict[str, Any]]] = None
    ) -> List[Dict[str, Any]]:
        """
        Generates an investigator-oriented chronological timeline with humanized deltas
        and optional trigger-relative deltas.
        """
        trig_item = None
        if trigger_event is not None:
            if isinstance(trigger_event, TemporalSequenceItem):
                trig_item = trigger_event
            elif isinstance(trigger_event, dict) and "event_id" in trigger_event:
                trig_item = next((it for it in sequence.items if it.event_id == trigger_event["event_id"]), None)
            elif isinstance(trigger_event, str):
                trig_item = next((it for it in sequence.items if it.event_id == trigger_event), None)
            if trig_item is None:
                raise ValueError(
                    f"Cross-entity event reference rejected: trigger event '{trigger_event}' "
                    f"does not belong to sequence for entity '{sequence.entity_id}'."
                )

        timeline_rows: List[Dict[str, Any]] = []

        for it in sequence.items:
            if it.time_delta_from_previous is None:
                since_prev = "FIRST"
            else:
                d = it.time_delta_from_previous
                if d < 60:
                    since_prev = f"+{d:.1f}s"
                elif d < 3600:
                    since_prev = f"+{d/60:.1f}m"
                else:
                    since_prev = f"+{d/3600:.1f}h"

            if trig_item is None:
                rel_trig = "N/A"
            elif it.event_id == trig_item.event_id:
                rel_trig = "TRIGGER (0s)"
            elif it.epoch_time is not None and trig_item.epoch_time is not None:
                diff = it.epoch_time - trig_item.epoch_time
                sign = "+" if diff > 0 else "-"
                abs_diff = abs(diff)
                if abs_diff < 60:
                    rel_trig = f"{sign}{abs_diff:.1f}s"
                elif abs_diff < 3600:
                    rel_trig = f"{sign}{abs_diff/60:.1f}m"
                else:
                    rel_trig = f"{sign}{abs_diff/3600:.1f}h"
            else:
                diff_idx = it.sequence_index - trig_item.sequence_index
                rel_trig = f"{'+' if diff_idx > 0 else ''}{diff_idx} steps"

            ts_display = it.timestamp or (f"epoch:{it.epoch_time}" if it.epoch_time is not None else f"seq:{it.sequence_number}")
            short_ts = ts_display.split("T")[-1].replace("Z", "")[:8] if "T" in ts_display else ts_display
            console_line = f"{short_ts} {it.event_type} | {it.source_domain} | {it.evidence_ref or 'no-ref'}"
            if since_prev != "FIRST":
                console_line += f" | {since_prev}"
            line = f"{ts_display:<24} | {it.event_type:<20} | {it.source_domain:<12} | prev:{since_prev:<8} | trig:{rel_trig:<14} | [{it.evidence_ref or 'no-ref'}]"

            prov_ref = it.evidence_ref
            if self.backend and hasattr(self.backend, "evidence_engine"):
                ev_obj = self.backend.evidence_engine.get_evidence(it.evidence_ref or it.event_id)
                if not ev_obj and it.event_id:
                    ev_obj = self.backend.evidence_engine.get_evidence(it.event_id)
                if ev_obj and getattr(ev_obj, "provenance_ref", None):
                    prov_ref = ev_obj.provenance_ref

            timeline_rows.append({
                "timestamp": ts_display,
                "event_id": it.event_id,
                "event_type": it.event_type,
                "domain": it.source_domain,
                "source_domain": it.source_domain,
                "actor_id": it.actor_id or it.metadata.get("actor_id", ""),
                "target_id": it.target_id or it.metadata.get("target_id", ""),
                "canonical_entity_id": it.canonical_entity_id,
                "time_since_previous": since_prev,
                "relative_delta_from_trigger": rel_trig,
                "relative_to_trigger": rel_trig,
                "evidence_ref": it.evidence_ref,
                "provenance_ref": prov_ref,
                "ordering_basis": it.ordering_basis.value if hasattr(it.ordering_basis, "value") else str(it.ordering_basis),
                "formatted_line": line,
                "formatted_summary": line,
                "console_line": console_line,
            })

        return timeline_rows
