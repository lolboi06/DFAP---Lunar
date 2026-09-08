# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
"""
M10 — Temporal Sequence Engine.

Three complementary mechanisms:

1. MOTIF MATCHER — Deterministic temporal motif matching.
   Requires: t_1 <= t_2 <= ... <= t_n  (monotonic time)
             t_n - t_1 <= max_duration  (bounded window)
             each event within evaluation window
   Output:  motif_matches per entity.

2. PREFIX-SPAN SEQUENTIAL MINER — Deterministic frequent sequential pattern
   mining over canonical event type sequences.
   Implements: support counting, frequency, recurrence, novelty detection.
   No external black-box library.

3. LOCAL DTW ENGINE — Pure-NumPy Dynamic Time Warping.
   Input representation: each event → 5-dimensional numerical vector:
     [event_type_enc, domain_enc, rel_time_norm, amount_norm, duration_norm]
   Local distance: squared Euclidean (L2^2).
   Boundary constraints: standard (i=0, j=0) → (m-1, n-1) forced.
   Warping path: traced back through DP table.
   DTW distance is NOT a probability.
   Normalized DTW: dtw_distance / len(warping_path)  (path-length normalization).

Mathematical reference for DTW:
  D[0,0] = dist(s[0], t[0])
  D[i,0] = dist(s[i], t[0]) + D[i-1, 0]
  D[0,j] = dist(s[0], t[j]) + D[0, j-1]
  D[i,j] = dist(s[i], t[j]) + min(D[i-1,j], D[i,j-1], D[i-1,j-1])
  DTW = D[m-1, n-1]
"""
import json
import uuid
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

MODEL_VERSION = "M10_SEQUENCE_v1.0"

# ── Event encoding maps ───────────────────────────────────────────────────────
EVENT_TYPE_ENC = {
    "CALL": 0, "IP_SESSION": 1, "TRANSACTION": 2,
    "LOGIN": 3, "SOCIAL": 4, "DEVICE_EVENT": 5, "LOCATION_EVENT": 6,
}
DOMAIN_ENC = {"CDR": 0, "IPDR": 1, "BANK": 2, "SOCIAL": 3}


# ══════════════════════════════════════════════════════════════════════════════
# 1. MOTIF CATALOG & MATCHER
# ══════════════════════════════════════════════════════════════════════════════

DEFAULT_MOTIF_CATALOG = [
    {
        "motif_id": "MOT_001",
        "name": "CALL_THEN_TRANSFER",
        "description": "Phone call followed by a financial transaction",
        "event_types": ["CALL", "TRANSACTION"],
        "required_domains": ["CDR", "BANK"],
        "maximum_duration_seconds": 3600,
        "allowed_gap_ranges": [[0, 3600]],
        "minimum_events": 2,
        "note": "Temporal pattern only — not proof of coordination",
    },
    {
        "motif_id": "MOT_002",
        "name": "LOGIN_THEN_TRANSACTION",
        "description": "Login event followed by a financial transaction",
        "event_types": ["LOGIN", "TRANSACTION"],
        "required_domains": ["SOCIAL", "BANK"],
        "maximum_duration_seconds": 1800,
        "allowed_gap_ranges": [[0, 1800]],
        "minimum_events": 2,
        "note": "Temporal pattern only",
    },
    {
        "motif_id": "MOT_003",
        "name": "CALL_IP_LOGIN_TRANSFER",
        "description": "Multi-domain sequence: Call → IP session → Login → Transaction",
        "event_types": ["CALL", "IP_SESSION", "LOGIN", "TRANSACTION"],
        "required_domains": ["CDR", "IPDR", "SOCIAL", "BANK"],
        "maximum_duration_seconds": 7200,
        "allowed_gap_ranges": [[0, 3600], [0, 3600], [0, 3600]],
        "minimum_events": 4,
        "note": "Complex multi-domain temporal pattern — not proof of malice",
    },
    {
        "motif_id": "MOT_004",
        "name": "RAPID_MULTI_TRANSACTION",
        "description": "Multiple transactions within a short window",
        "event_types": ["TRANSACTION", "TRANSACTION"],
        "required_domains": ["BANK", "BANK"],
        "maximum_duration_seconds": 300,
        "allowed_gap_ranges": [[0, 300]],
        "minimum_events": 2,
        "note": "Pattern only — could be legitimate batch processing",
    },
]


class MotifMatcher:
    """Deterministic temporal motif matching over an entity's sorted event list."""

    def __init__(self, motif_catalog: Optional[List[Dict]] = None):
        self.catalog = motif_catalog or DEFAULT_MOTIF_CATALOG

    def match_entity(
        self,
        entity_id: str,
        events: pd.DataFrame,
    ) -> List[Dict]:
        """
        Returns all motif matches for an entity.
        Events must be sorted by timestamp ascending.
        """
        matches = []
        if events.empty:
            return matches

        # Convert timestamps to epoch seconds for arithmetic
        events = events.copy()
        events["_epoch"] = pd.to_datetime(
            events["timestamp"], utc=True
        ).apply(lambda dt: dt.timestamp())

        for motif in self.catalog:
            motif_matches = self._match_motif(entity_id, events, motif)
            matches.extend(motif_matches)

        return matches

    def _match_motif(
        self, entity_id: str, events: pd.DataFrame, motif: Dict
    ) -> List[Dict]:
        """
        Sliding-window motif matching.
        Requires strict temporal order: t_1 ≤ t_2 ≤ ... ≤ t_n.
        Requires total duration: t_n - t_1 ≤ max_duration_seconds.
        """
        required_types = motif["event_types"]
        max_dur = motif["maximum_duration_seconds"]
        n = len(required_types)

        # Filter to relevant event types
        relevant = events[events["event_type"].isin(required_types)].reset_index(drop=True)
        if len(relevant) < n:
            return []

        results = []
        rows = relevant.to_dict("records")

        # Enumerate all n-tuples in temporal order
        def recurse(pos: int, seq_so_far: List, type_idx: int):
            if type_idx == n:
                # Full match found
                t_start = seq_so_far[0]["_epoch"]
                t_end = seq_so_far[-1]["_epoch"]
                dur = t_end - t_start
                if dur <= max_dur:
                    # Validate gap constraints
                    gap_ok = True
                    gaps = []
                    for k in range(len(seq_so_far) - 1):
                        gap = seq_so_far[k + 1]["_epoch"] - seq_so_far[k]["_epoch"]
                        gaps.append(gap)
                        if motif.get("allowed_gap_ranges"):
                            lo, hi = motif["allowed_gap_ranges"][
                                min(k, len(motif["allowed_gap_ranges"]) - 1)
                            ]
                            if not (lo <= gap <= hi):
                                gap_ok = False
                                break
                    if gap_ok:
                        match_id = f"MTH_{uuid.uuid4().hex[:10].upper()}"
                        results.append({
                            "match_id": match_id,
                            "motif_id": motif["motif_id"],
                            "entity_id": entity_id,
                            "event_ids": [e["event_id"] for e in seq_so_far],
                            "event_types": [e["event_type"] for e in seq_so_far],
                            "timestamp_start": seq_so_far[0]["timestamp"],
                            "timestamp_end": seq_so_far[-1]["timestamp"],
                            "duration_seconds": float(dur),
                            "gaps_seconds": [float(g) for g in gaps],
                            "evidence_refs": [e.get("sha256_hash", "") for e in seq_so_far],
                        })
                return

            needed_type = required_types[type_idx]
            for i in range(pos, len(rows)):
                row = rows[i]
                if row["event_type"] != needed_type:
                    continue
                # Monotonic time check
                if seq_so_far and row["_epoch"] < seq_so_far[-1]["_epoch"]:
                    continue
                recurse(i + 1, seq_so_far + [row], type_idx + 1)

        recurse(0, [], 0)
        return results


# ══════════════════════════════════════════════════════════════════════════════
# 2. PREFIX-SPAN SEQUENTIAL PATTERN MINER
# ══════════════════════════════════════════════════════════════════════════════

class PrefixSpanMiner:
    """
    Deterministic sequential pattern miner inspired by PrefixSpan.

    Algorithm:
      1. Build event-type sequences per entity, ordered by timestamp.
      2. Find all frequent subsequences with support >= min_support.
      3. Report: pattern, support, frequency, recurrence, novelty.

    Support: number of entities whose sequence contains the pattern.
    Frequency: total occurrences across all sequences.
    Recurrence: frequency > support (pattern repeats within same entity).
    Novelty: pattern not seen in training corpus.

    Time complexity: O(|sequences| * |alphabet|^max_len) — bounded.
    """

    def __init__(self, min_support: int = 2, max_pattern_length: int = 4):
        self.min_support = min_support
        self.max_pattern_length = max_pattern_length
        self._training_patterns: Optional[Dict[Tuple, Dict]] = None

    def fit(self, sequences: List[List[str]]):
        """Learn frequent patterns from training sequences."""
        self._training_patterns = self._mine(sequences)

    def find_patterns(self, sequences: List[List[str]]) -> pd.DataFrame:
        """Mine patterns from sequences and compare against training corpus."""
        patterns = self._mine(sequences)
        rows = []
        for pat, stats in sorted(patterns.items(), key=lambda x: -x[1]["support"]):
            known = self._training_patterns is not None and pat in self._training_patterns
            rows.append({
                "pattern": list(pat),
                "pattern_str": " → ".join(pat),
                "length": len(pat),
                "support": stats["support"],
                "frequency": stats["frequency"],
                "recurrence": stats["frequency"] > stats["support"],
                "novel": not known,
                "model_version": MODEL_VERSION,
            })
        return pd.DataFrame(rows)

    def _mine(self, sequences: List[List[str]]) -> Dict[Tuple, Dict]:
        """
        Core prefix-span mining loop.
        Returns dict: pattern_tuple → {support, frequency}
        """
        from collections import defaultdict

        patterns: Dict[Tuple, Dict] = {}
        alphabet = sorted(set(e for seq in sequences for e in seq))

        # Initialise with length-1 patterns
        queue: List[Tuple[Tuple, List[List[str]]]] = []
        for item in alphabet:
            projected = self._project(sequences, (), item)
            if len(projected) >= self.min_support:
                queue.append(((item,), projected))

        while queue:
            prefix, proj_seqs = queue.pop()
            # Count support and frequency
            support = len(proj_seqs)
            frequency = sum(
                seq.count(prefix[-1]) for orig, seq in
                zip(sequences, [self._flatten(p) for p in proj_seqs])
            )
            patterns[prefix] = {"support": support, "frequency": frequency}

            if len(prefix) >= self.max_pattern_length:
                continue

            # Extend prefix
            for item in alphabet:
                extended = self._project(proj_seqs, (), item)
                if len(extended) >= self.min_support:
                    queue.append((prefix + (item,), extended))

        return patterns

    @staticmethod
    def _project(
        sequences: List[List[str]], _prefix: Tuple, item: str
    ) -> List[List[str]]:
        """Projected database: suffix after first occurrence of item."""
        result = []
        for seq in sequences:
            try:
                idx = seq.index(item)
                result.append(seq[idx + 1:])
            except ValueError:
                pass
        return result

    @staticmethod
    def _flatten(seq: List[str]) -> List[str]:
        return seq


# ══════════════════════════════════════════════════════════════════════════════
# 3. LOCAL DTW ENGINE
# ══════════════════════════════════════════════════════════════════════════════

class LocalDTW:
    """
    Pure-NumPy Dynamic Time Warping implementation.

    Event representation (5-dimensional vector):
      [0] event_type_enc     : integer encoding from EVENT_TYPE_ENC (0-6), normalised /6
      [1] domain_enc         : integer encoding from DOMAIN_ENC (0-3), normalised /3
      [2] rel_time_norm      : (t - t_min) / (t_max - t_min + ε) in [0, 1]
      [3] amount_norm        : transaction amount / amount_scale  (0 if unavailable)
      [4] duration_norm      : call duration / duration_scale     (0 if unavailable)

    Local distance: squared Euclidean distance (L2²).
    Boundary: D[0,0] = dist(s[0],t[0]),  goal = D[m-1,n-1].
    Normalization: normalized_dtw = dtw_distance / len(warping_path).

    DTW distance is NOT a probability.
    Score transformation: sequence_score = exp(-normalized_dtw)  in (0,1].
      Lower distance → higher score. This is a similarity proxy, not a probability.
    """

    def __init__(self, amount_scale: float = 100_000.0, duration_scale: float = 3600.0):
        self.amount_scale = amount_scale
        self.duration_scale = duration_scale

    def encode_sequence(
        self,
        events: pd.DataFrame,
    ) -> np.ndarray:
        """
        Encode a sorted event DataFrame into a (n_events × 5) numerical matrix.
        """
        if events.empty:
            return np.zeros((0, 5))

        times = pd.to_datetime(events["timestamp"], utc=True).apply(lambda dt: dt.timestamp()).values
        t_min = float(times.min())
        t_max = float(times.max())
        t_range = max(t_max - t_min, 1e-9)

        rows = []
        for _, ev in events.iterrows():
            attrs = {}
            try:
                raw = json.loads(ev.get("attributes", "{}"))
                attrs = raw.get("raw_source_attributes", raw)
            except Exception:
                pass

            et_enc = EVENT_TYPE_ENC.get(ev.get("event_type", "CALL"), 0) / 6.0
            dom_enc = DOMAIN_ENC.get(ev.get("source_domain", "CDR"), 0) / 3.0
            epoch = pd.to_datetime(ev["timestamp"], utc=True).timestamp()
            rel_t = float(np.clip((epoch - t_min) / t_range, 0.0, 1.0))
            amt = float(attrs.get("amount", 0.0) or 0.0) / self.amount_scale
            dur = float(attrs.get("duration_sec", attrs.get("duration", 0.0)) or 0.0) / self.duration_scale

            rows.append([et_enc, dom_enc, rel_t, min(amt, 1.0), min(dur, 1.0)])

        return np.array(rows, dtype=np.float64)

    def dtw_distance(
        self, seq_a: np.ndarray, seq_b: np.ndarray
    ) -> Tuple[float, float, List[Tuple[int, int]]]:
        """
        Compute DTW distance between two encoded sequences.
        Returns (dtw_dist, normalized_dtw_dist, warping_path).

        DP recurrence:
          D[i,j] = dist(a[i], b[j]) + min(D[i-1,j], D[i,j-1], D[i-1,j-1])
        """
        m, n = len(seq_a), len(seq_b)
        if m == 0 or n == 0:
            return float("inf"), float("inf"), []

        # Fill DP table
        D = np.full((m, n), np.inf, dtype=np.float64)
        D[0, 0] = self._local_dist(seq_a[0], seq_b[0])

        for i in range(1, m):
            D[i, 0] = self._local_dist(seq_a[i], seq_b[0]) + D[i - 1, 0]
        for j in range(1, n):
            D[0, j] = self._local_dist(seq_a[0], seq_b[j]) + D[0, j - 1]
        for i in range(1, m):
            for j in range(1, n):
                D[i, j] = self._local_dist(seq_a[i], seq_b[j]) + min(
                    D[i - 1, j], D[i, j - 1], D[i - 1, j - 1]
                )

        dtw_dist = float(D[m - 1, n - 1])

        # Trace warping path (back-trace)
        path = self._backtrace(D)
        norm_dtw = dtw_dist / max(len(path), 1)

        return dtw_dist, norm_dtw, path

    @staticmethod
    def _local_dist(a: np.ndarray, b: np.ndarray) -> float:
        """Local distance: squared Euclidean (L2²)."""
        diff = a - b
        return float(np.dot(diff, diff))

    @staticmethod
    def _backtrace(D: np.ndarray) -> List[Tuple[int, int]]:
        """Trace optimal warping path from (m-1, n-1) back to (0, 0)."""
        m, n = D.shape
        i, j = m - 1, n - 1
        path = [(i, j)]
        while i > 0 or j > 0:
            if i == 0:
                j -= 1
            elif j == 0:
                i -= 1
            else:
                step = np.argmin([D[i - 1, j], D[i, j - 1], D[i - 1, j - 1]])
                if step == 0:
                    i -= 1
                elif step == 1:
                    j -= 1
                else:
                    i -= 1
                    j -= 1
            path.append((i, j))
        return list(reversed(path))


# ══════════════════════════════════════════════════════════════════════════════
# SEQUENCE ENGINE — top-level orchestrator
# ══════════════════════════════════════════════════════════════════════════════

class SequenceEngine:
    """
    Orchestrates M10: motif matching, sequential pattern mining, and DTW.
    """

    def __init__(
        self,
        motif_catalog: Optional[List[Dict]] = None,
        min_support: int = 2,
        max_pattern_length: int = 4,
        random_state: int = 42,
    ):
        self.motif_matcher = MotifMatcher(motif_catalog)
        self.pattern_miner = PrefixSpanMiner(min_support, max_pattern_length)
        self.dtw = LocalDTW()
        self.random_state = random_state
        self._training_sequences: List[List[str]] = []

    def fit(self, events_df: pd.DataFrame):
        """Fit sequential miner on historical event sequences."""
        seqs = self._build_sequences(events_df)
        self._training_sequences = seqs
        if len(seqs) >= 2:
            self.pattern_miner.fit(seqs)

    def analyze(
        self,
        entity_id: str,
        events_df: pd.DataFrame,
        motif_ref_events: Optional[pd.DataFrame] = None,
    ) -> Dict[str, Any]:
        """
        Run full M10 analysis for a single entity.
        Returns dict with motif_matches, pattern_matches, dtw_results.
        """
        e_events = events_df[
            (events_df["actor_id"] == entity_id) |
            (events_df["target_id"] == entity_id)
        ].sort_values("timestamp").reset_index(drop=True)

        # 1. Motif matching
        motif_matches = self.motif_matcher.match_entity(entity_id, e_events)

        # 2. Sequential pattern mining
        entity_seq = e_events["event_type"].tolist()
        all_seqs = self._build_sequences(events_df)
        pattern_df = pd.DataFrame()
        if len(all_seqs) >= self.pattern_miner.min_support:
            pattern_df = self.pattern_miner.find_patterns(all_seqs)

        # 3. DTW against motif reference sequences
        dtw_results = []
        if motif_ref_events is not None and not motif_ref_events.empty and not e_events.empty:
            seq_a = self.dtw.encode_sequence(e_events)
            seq_b = self.dtw.encode_sequence(motif_ref_events)
            if len(seq_a) > 0 and len(seq_b) > 0:
                dtw_dist, norm_dtw, wpath = self.dtw.dtw_distance(seq_a, seq_b)
                seq_score = float(np.exp(-norm_dtw))  # similarity proxy, NOT probability
                dtw_results.append({
                    "sequence_id": f"DTW_{uuid.uuid4().hex[:10].upper()}",
                    "entity_id": entity_id,
                    "event_ids": e_events["event_id"].tolist(),
                    "timestamp_start": e_events["timestamp"].min(),
                    "timestamp_end": e_events["timestamp"].max(),
                    "duration_seconds": float(
                        (pd.to_datetime(e_events["timestamp"].max(), utc=True)
                         - pd.to_datetime(e_events["timestamp"].min(), utc=True)
                        ).total_seconds()
                    ),
                    "dtw_distance": dtw_dist,
                    "normalized_dtw_distance": norm_dtw,
                    "warping_path_length": len(wpath),
                    "sequence_score": seq_score,
                    "score_semantics": "exp(-normalized_dtw) — similarity proxy, NOT probability",
                    "evidence_refs": e_events["sha256_hash"].tolist(),
                    "model_version": MODEL_VERSION,
                })

        return {
            "entity_id": entity_id,
            "motif_matches": motif_matches,
            "pattern_df": pattern_df,
            "dtw_results": dtw_results,
        }

    @staticmethod
    def _build_sequences(events_df: pd.DataFrame) -> List[List[str]]:
        """Build one event-type sequence per entity, sorted by timestamp."""
        seqs = []
        for actor, grp in events_df.sort_values("timestamp").groupby("actor_id"):
            seq = grp["event_type"].tolist()
            if seq:
                seqs.append(seq)
        return seqs
