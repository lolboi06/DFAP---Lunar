# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: Canonical Temporal Investigation Engine (Observed vs Surrogate Semantics & Causal Rigor)

import json
import logging
import math
import os
from typing import Dict, Any, List, Optional, Tuple, Set, Union
import numpy as np
import pandas as pd

from dfap.schemas import TemporalSemantics

logger = logging.getLogger(__name__)

# Master Authoritative Hash for Controlled Identity Bridge
AUTHORITATIVE_IDENTITY_BRIDGE_SHA256 = "6c53bfaad8c425ac04fd70e324edb414ba91fba358bb965bd70b6176098be6a7"


def load_identity_bridge_readonly(bridge_path: str = "data/cases/identity_bridge.parquet") -> pd.DataFrame:
    """
    Loads controlled identity bridge in read-only mode with SHA-256 verification.
    Prevents unauthorized mutation by tests, benchmarks, or runtime tools.
    """
    if not os.path.exists(bridge_path):
        return pd.DataFrame()

    import hashlib
    with open(bridge_path, "rb") as f:
        actual_hash = hashlib.sha256(f.read()).hexdigest()

    if actual_hash != AUTHORITATIVE_IDENTITY_BRIDGE_SHA256:
        raise ValueError(
            f"MUTATION DETECTED: identity_bridge.parquet hash '{actual_hash}' differs from "
            f"authoritative hash '{AUTHORITATIVE_IDENTITY_BRIDGE_SHA256}'. Controlled case mappings are immutable!"
        )

    df = pd.read_parquet(bridge_path)
    return df.copy(deep=True)


class TemporalEventEngine:
    """
    Canonical Temporal Investigation Engine over REAL_PUBLIC_DATA records.
    Strictly differentiates:
      - OBSERVED_TIMESTAMP: genuine chronological timestamps (e.g. Stack Overflow)
      - SEQUENCE_ORDER_SURROGATE: discrete ordered event sequences without clock time (e.g. UNSW)
      - UNKNOWN_TIMESTAMP: unorderable events
    Zero future leakage: All profiles and baseline statistics use strictly past events (<= pivot).
    """

    def __init__(self, canonical_dir: str = "data/canonical"):
        self.canonical_dir = canonical_dir
        self.datasets: Dict[str, pd.DataFrame] = {}
        self._load_datasets()

    def _load_datasets(self):
        """Loads available canonical datasets."""
        for ds_name in ["stackoverflow", "unsw", "elliptic"]:
            p = os.path.join(self.canonical_dir, f"{ds_name}_canonical.parquet")
            if os.path.exists(p):
                df = pd.read_parquet(p)
                if "epoch_time" in df.columns:
                    df = df.sort_values("epoch_time").reset_index(drop=True)
                self.datasets[ds_name] = df

    def get_dataset_for_entity(self, entity_id: str, preferred_dataset: Optional[str] = None) -> Tuple[str, pd.DataFrame]:
        """Identifies the canonical dataset containing the entity."""
        if preferred_dataset and preferred_dataset.lower() in self.datasets:
            ds_key = preferred_dataset.lower()
            df = self.datasets[ds_key]
            if not df[(df["actor_id"] == entity_id) | (df["target_id"] == entity_id)].empty:
                return ds_key, df

        for ds_key, df in self.datasets.items():
            sub = df[(df["actor_id"] == entity_id) | (df["target_id"] == entity_id)]
            if not sub.empty:
                return ds_key, df

        # Return empty dataset key and DataFrame if entity not found in replay datasets
        if preferred_dataset and preferred_dataset.lower() in self.datasets:
            return preferred_dataset.lower(), pd.DataFrame()
        return "", pd.DataFrame()

    def events_for_entity(self, entity_id: str, dataset: Optional[str] = None) -> List[Dict[str, Any]]:
        """Returns all events involving the entity ordered by time/sequence."""
        ds_key, df = self.get_dataset_for_entity(entity_id, dataset)
        if df.empty:
            return []

        sub = df[(df["actor_id"] == entity_id) | (df["target_id"] == entity_id)].copy()
        sub = sub.sort_values("epoch_time").reset_index(drop=True)
        return sub.to_dict(orient="records")

    def events_between(
        self,
        entity_id: str,
        start: str,
        end: str,
        dataset: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Extracts events between start and end timestamps.
        CRITICAL: Rejects date-range queries for SEQUENCE_ORDER_SURROGATE datasets.
        """
        ds_key, df = self.get_dataset_for_entity(entity_id, dataset)
        if df.empty:
            return []

        # Check temporal semantics
        semantics = df["temporal_semantics"].iloc[0] if "temporal_semantics" in df.columns else TemporalSemantics.OBSERVED_TIMESTAMP
        if semantics == TemporalSemantics.SEQUENCE_ORDER_SURROGATE or ds_key == "unsw":
            raise ValueError(
                f"Date-range queries are unsupported for dataset '{ds_key}' because its temporal semantics are "
                f"SEQUENCE_ORDER_SURROGATE. Calendar date windows cannot be evaluated on sequence-order surrogate time."
            )

        start_epoch = pd.to_datetime(start, utc=True).timestamp()
        end_epoch = pd.to_datetime(end, utc=True).timestamp()

        sub = df[(df["actor_id"] == entity_id) | (df["target_id"] == entity_id)]
        mask = (sub["epoch_time"] >= start_epoch) & (sub["epoch_time"] <= end_epoch)
        return sub[mask].sort_values("epoch_time").to_dict(orient="records")

    def previous_events(
        self,
        entity_id: str,
        pivot: Union[str, float],
        max_events: int = 20,
        dataset: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Returns strictly preceding events before the pivot (temporal predecessor).
        Does NOT return the pivot event itself.
        """
        ds_key, df = self.get_dataset_for_entity(entity_id, dataset)
        if df.empty:
            return []

        try:
            pivot_epoch = float(pivot)
        except (ValueError, TypeError):
            pivot_epoch = pd.to_datetime(pivot, utc=True).timestamp() if pivot else float("inf")

        sub = df[(df["actor_id"] == entity_id) | (df["target_id"] == entity_id)]
        prior = sub[sub["epoch_time"] < pivot_epoch].sort_values("epoch_time", ascending=False).head(max_events)
        return prior.to_dict(orient="records")

    def next_events(
        self,
        entity_id: str,
        pivot: Union[str, float],
        max_events: int = 20,
        dataset: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Returns subsequent records after the pivot.
        Explicitly labeled OBSERVED_FUTURE_HISTORY (historical data after pivot, NOT a prediction).
        """
        ds_key, df = self.get_dataset_for_entity(entity_id, dataset)
        if df.empty:
            return []

        try:
            pivot_epoch = float(pivot)
        except (ValueError, TypeError):
            pivot_epoch = pd.to_datetime(pivot, utc=True).timestamp() if pivot else 0.0

        sub = df[(df["actor_id"] == entity_id) | (df["target_id"] == entity_id)]
        subsequent = sub[sub["epoch_time"] > pivot_epoch].sort_values("epoch_time", ascending=True).head(max_events)
        records = subsequent.to_dict(orient="records")
        for r in records:
            r["history_scope"] = "OBSERVED_FUTURE_HISTORY"
        return records

    def rolling_window(
        self,
        entity_id: str,
        pivot: Union[str, float],
        window_seconds: float = 3600.0,
        dataset: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Returns events in the trailing rolling window [pivot - window_seconds, pivot]."""
        ds_key, df = self.get_dataset_for_entity(entity_id, dataset)
        if df.empty:
            return []

        semantics = df["temporal_semantics"].iloc[0] if "temporal_semantics" in df.columns else TemporalSemantics.OBSERVED_TIMESTAMP
        if semantics == TemporalSemantics.SEQUENCE_ORDER_SURROGATE or ds_key == "unsw":
            raise ValueError(
                f"Time-duration rolling window is unsupported for dataset '{ds_key}' with SEQUENCE_ORDER_SURROGATE semantics."
            )

        pivot_epoch = float(pivot) if isinstance(pivot, (int, float)) else pd.to_datetime(pivot, utc=True).timestamp()
        sub = df[(df["actor_id"] == entity_id) | (df["target_id"] == entity_id)]
        mask = (sub["epoch_time"] >= (pivot_epoch - window_seconds)) & (sub["epoch_time"] <= pivot_epoch)
        return sub[mask].sort_values("epoch_time").to_dict(orient="records")

    def sequence(
        self,
        entity_id: str,
        start_idx: Optional[int] = None,
        end_idx: Optional[int] = None,
        dataset: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Returns discrete ordered event sequence by integer index."""
        evts = self.events_for_entity(entity_id, dataset)
        s = start_idx or 0
        e = end_idx if end_idx is not None else len(evts)
        return evts[s:e]

    def history(
        self,
        entity_id: str,
        pivot: Optional[Union[str, float]] = None,
        dataset: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Returns strict causal history for an entity prior to pivot T.
        Events strictly before pivot (epoch_time < T) are included.
        Events at or after pivot (epoch_time >= T) are EXCLUDED,
        unless authoritative sequence semantics explicitly place an equal-timestamp event before T.
        """
        ds_key, df = self.get_dataset_for_entity(entity_id, dataset)
        evts = self.events_for_entity(entity_id, ds_key)
        if pivot is None:
            return evts

        try:
            pivot_epoch = float(pivot)
        except (ValueError, TypeError):
            pivot_epoch = pd.to_datetime(pivot, utc=True).timestamp()

        filtered = []
        for e in evts:
            ep = e.get("epoch_time")
            if ep is None:
                continue
            if ep < pivot_epoch:
                filtered.append(e)
            elif ep == pivot_epoch:
                seq_num = e.get("sequence_number")
                pivot_seq = e.get("pivot_sequence_number")
                if seq_num is not None and pivot_seq is not None and seq_num < pivot_seq:
                    filtered.append(e)
        return filtered

    def validate_historical_evidence_set(
        self,
        events: List[Dict[str, Any]],
        pivot: Union[str, float]
    ) -> bool:
        """
        Temporal Guard: Rejects any attempt to include future events (epoch_time > pivot)
        or unsequenced equal-timestamp events (epoch_time == pivot without authoritative ordering)
        in a historical evidence set.
        Raises ValueError on violation.
        """
        try:
            pivot_epoch = float(pivot)
        except (ValueError, TypeError):
            pivot_epoch = pd.to_datetime(pivot, utc=True).timestamp()

        for e in events:
            ep = e.get("epoch_time")
            if ep is not None:
                if ep > pivot_epoch:
                    raise ValueError(
                        f"Temporal Guard Violation: Event '{e.get('event_id')}' with timestamp {ep} "
                        f"occurs in the future relative to pivot {pivot_epoch}. Future leakage rejected."
                    )
                if ep == pivot_epoch:
                    seq_num = e.get("sequence_number")
                    pivot_seq = e.get("pivot_sequence_number")
                    if seq_num is None or pivot_seq is None or seq_num >= pivot_seq:
                        raise ValueError(
                            f"Temporal Guard Violation: Event '{e.get('event_id')}' has timestamp equal to pivot {pivot_epoch} "
                            f"without authoritative prior sequence ordering. Equal-timestamp leakage rejected."
                        )
        return True

    def get_entity_history(self, entity_id: str, pivot: Optional[Union[str, float]] = None, dataset: Optional[str] = None) -> Dict[str, Any]:
        """
        Extracts comprehensive entity history summary.
        Distinguishes CHRONOLOGICAL_HISTORY from ORDERED_HISTORY.
        """
        ds_key, df = self.get_dataset_for_entity(entity_id, dataset)
        if pivot is not None:
            evts = self.history(entity_id, pivot=pivot, dataset=ds_key)
        else:
            evts = self.events_for_entity(entity_id, ds_key)
        if not evts:
            return {"entity_id": entity_id, "status": "UNKNOWN_ENTITY", "total_events": 0}

        semantics = evts[0].get("temporal_semantics", TemporalSemantics.OBSERVED_TIMESTAMP)
        history_type = "ORDERED_HISTORY" if semantics == TemporalSemantics.SEQUENCE_ORDER_SURROGATE else "CHRONOLOGICAL_HISTORY"

        first_act = evts[0]["timestamp"]
        last_act = evts[-1]["timestamp"]

        counterparties = set()
        domains = {}
        for e in evts:
            c = e["target_id"] if e["actor_id"] == entity_id else e["actor_id"]
            if c:
                counterparties.add(c)
            dom = e.get("source_domain", "UNKNOWN")
            domains[dom] = domains.get(dom, 0) + 1

        # Activity by hour/day
        time_dist = {}
        for e in evts[:100]:
            k = e["timestamp"][:10] if len(e["timestamp"]) >= 10 else "UNKNOWN"
            time_dist[k] = time_dist.get(k, 0) + 1

        return {
            "entity_id": entity_id,
            "dataset": ds_key,
            "temporal_semantics": semantics,
            "history_type": history_type,
            "total_events": len(evts),
            "first_activity": first_act,
            "last_activity": last_act,
            "unique_counterparties": sorted(list(counterparties)),
            "counterparty_count": len(counterparties),
            "activity_by_domain": domains,
            "activity_by_time": time_dist,
            "recent_activity": evts[-5:],
            "historical_activity": evts[:5]
        }

    def build_profile(
        self,
        entity_id: str,
        pivot: Union[str, float],
        dataset: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Builds causal behavioral profile snapshot at pivot.
        CRITICAL: Uses ONLY events <= pivot. Zero future information leakage.
        """
        try:
            pivot_epoch = float(pivot)
        except (ValueError, TypeError):
            pivot_epoch = pd.to_datetime(pivot, utc=True).timestamp() if pivot else float("inf")

        ds_key, df = self.get_dataset_for_entity(entity_id, dataset)
        evts = self.events_for_entity(entity_id, ds_key)
        # STRICT CAUSAL CUTOFF
        past_evts = [e for e in evts if e["epoch_time"] <= pivot_epoch]
        if not past_evts:
            return {
                "entity_id": entity_id,
                "observation_epoch": pivot_epoch,
                "status": "NO_PRIOR_HISTORY",
                "event_count_before_pivot": 0
            }

        semantics = past_evts[0].get("temporal_semantics", TemporalSemantics.OBSERVED_TIMESTAMP)
        amounts = [float(e.get("amount", 0.0)) for e in past_evts if float(e.get("amount", 0.0)) > 0]
        counterparties = set(e["target_id"] if e["actor_id"] == entity_id else e["actor_id"] for e in past_evts if e.get("target_id"))

        # Cadence: deltas between consecutive events
        epochs = sorted([e["epoch_time"] for e in past_evts])
        if len(epochs) >= 2:
            deltas = np.diff(epochs)
            mean_cadence = float(np.mean(deltas))
            std_cadence = float(np.std(deltas))
            burstiness = float((std_cadence - mean_cadence) / (std_cadence + mean_cadence)) if (std_cadence + mean_cadence) > 0 else 0.0
        else:
            mean_cadence = 0.0
            std_cadence = 0.0
            burstiness = 0.0

        # Domain distribution
        dom_counts = {}
        for e in past_evts:
            d = e.get("source_domain", "UNKNOWN")
            dom_counts[d] = dom_counts.get(d, 0) + 1

        total_n = len(past_evts)
        elapsed_sec = max(1.0, epochs[-1] - epochs[0]) if len(epochs) >= 2 else 3600.0
        events_per_hour = total_n / (elapsed_sec / 3600.0)

        return {
            "entity_id": entity_id,
            "pivot_epoch": pivot_epoch,
            "temporal_semantics": semantics,
            "event_count_before_pivot": total_n,
            "frequency_per_hour": round(events_per_hour, 4),
            "counterparty_count": len(counterparties),
            "counterparty_turnover": round(len(counterparties) / max(1, total_n), 3),
            "amount_distribution": {
                "mean": round(float(np.mean(amounts)), 2) if amounts else 0.0,
                "max": round(float(np.max(amounts)), 2) if amounts else 0.0,
                "std": round(float(np.std(amounts)), 2) if len(amounts) > 1 else 0.0,
                "sum": round(float(np.sum(amounts)), 2) if amounts else 0.0
            },
            "activity_cadence_mean_sec": round(mean_cadence, 2),
            "activity_cadence_std_sec": round(std_cadence, 2),
            "burstiness_index": round(burstiness, 3),
            "domain_mix": {k: round(v / total_n, 3) for k, v in dom_counts.items()},
            "historical_statistics": {
                "first_seen_epoch": epochs[0],
                "last_seen_epoch": epochs[-1],
                "active_span_hours": round(elapsed_sec / 3600.0, 2)
            }
        }

    def analyze_pivot(
        self,
        entity_id: str,
        pivot_event_id: str,
        dataset: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Compares historical profile before pivot VS the pivot event activity.
        Produces explicit deviation metrics with evidence references.
        """
        evts = self.events_for_entity(entity_id, dataset)
        pivot_evt = next((e for e in evts if e["event_id"] == pivot_event_id), None)
        if not pivot_evt:
            raise ValueError(f"Pivot event '{pivot_event_id}' not found for entity '{entity_id}'.")

        t_pivot = pivot_evt["epoch_time"]
        # Profile strictly strictly prior to pivot
        prior_evts = [e for e in evts if e["epoch_time"] < t_pivot]
        base_profile = self.build_profile(entity_id, pivot=t_pivot - 1e-6, dataset=dataset)

        deviations = []

        # 1. Amount deviation
        amt_obs = float(pivot_evt.get("amount", 0.0))
        amt_dist = base_profile.get("amount_distribution", {})
        mean_amt = amt_dist.get("mean", 0.0)
        std_amt = max(1.0, amt_dist.get("std", 1.0))
        if amt_obs > 0:
            diff = amt_obs - mean_amt
            z_score = diff / std_amt
            deviations.append({
                "metric": "amount_deviation",
                "baseline": mean_amt,
                "observed": amt_obs,
                "difference": round(diff, 2),
                "score": round(min(1.0, max(0.0, z_score / 5.0)), 3),
                "evidence_ref": f"hash:{pivot_evt['sha256_hash'][:16]}"
            })

        # 2. Counterparty novelty
        cp_obs = pivot_evt["target_id"] if pivot_evt["actor_id"] == entity_id else pivot_evt["actor_id"]
        prior_cps = set(e["target_id"] if e["actor_id"] == entity_id else e["actor_id"] for e in prior_evts)
        is_new_cp = cp_obs not in prior_cps
        deviations.append({
            "metric": "counterparty_novelty",
            "baseline": f"{len(prior_cps)} known contacts",
            "observed": cp_obs,
            "difference": "NEW_COUNTERPARTY" if is_new_cp else "RECURRENT_COUNTERPARTY",
            "score": 0.80 if is_new_cp else 0.10,
            "evidence_ref": f"hash:{pivot_evt['sha256_hash'][:16]}"
        })

        # 3. Burst deviation (events in trailing 10 minutes)
        t_10m = t_pivot - 600.0
        recent_10m = [e for e in prior_evts if e["epoch_time"] >= t_10m]
        deviations.append({
            "metric": "activity_burst",
            "baseline": "Historical cadence",
            "observed": f"{len(recent_10m)} events in trailing 10m",
            "difference": len(recent_10m),
            "score": round(min(1.0, len(recent_10m) / 10.0), 3),
            "evidence_ref": f"hash:{pivot_evt['sha256_hash'][:16]}"
        })

        return {
            "entity_id": entity_id,
            "pivot_event_id": pivot_event_id,
            "pivot_timestamp": pivot_evt["timestamp"],
            "pivot_epoch": t_pivot,
            "temporal_semantics": pivot_evt.get("temporal_semantics", "OBSERVED_TIMESTAMP"),
            "historical_events_before_pivot": len(prior_evts),
            "deviations": deviations,
            "max_deviation_score": max((d["score"] for d in deviations), default=0.0)
        }

    def backtrack(
        self,
        entity_id: str,
        pivot: Union[str, float],
        dataset: Optional[str] = None,
        max_events: int = 20
    ) -> Dict[str, Any]:
        """Backtracking: returns preceding events with explicit language safety."""
        ds_key, df = self.get_dataset_for_entity(entity_id, dataset)
        semantics = df["temporal_semantics"].iloc[0] if "temporal_semantics" in df.columns else TemporalSemantics.OBSERVED_TIMESTAMP

        prior = self.previous_events(entity_id, pivot, max_events=max_events, dataset=ds_key)
        query_type = "ORDER_BACKTRACK" if semantics == TemporalSemantics.SEQUENCE_ORDER_SURROGATE else "BACKTRACK"
        analysis_type = "SEQUENCE_ORDER_ANALYSIS" if semantics == TemporalSemantics.SEQUENCE_ORDER_SURROGATE else "REAL_TIME_TEMPORAL_ANALYSIS"

        return {
            "query": query_type,
            "entity_id": entity_id,
            "dataset": ds_key,
            "temporal_semantics": semantics,
            "analysis_type": analysis_type,
            "predecessor_count": len(prior),
            "ordered_predecessors": prior
        }

    def forwardtrack(
        self,
        entity_id: str,
        pivot: Union[str, float],
        dataset: Optional[str] = None,
        max_events: int = 20
    ) -> Dict[str, Any]:
        """Forward tracking: returns subsequent records labeled OBSERVED_FUTURE_HISTORY."""
        ds_key, df = self.get_dataset_for_entity(entity_id, dataset)
        semantics = df["temporal_semantics"].iloc[0] if "temporal_semantics" in df.columns else TemporalSemantics.OBSERVED_TIMESTAMP

        next_evts = self.next_events(entity_id, pivot, max_events=max_events, dataset=ds_key)
        query_type = "ORDER_FORWARD_TRACK" if semantics == TemporalSemantics.SEQUENCE_ORDER_SURROGATE else "FORWARDTRACK"
        analysis_type = "SEQUENCE_ORDER_ANALYSIS" if semantics == TemporalSemantics.SEQUENCE_ORDER_SURROGATE else "REAL_TIME_TEMPORAL_ANALYSIS"

        return {
            "query": query_type,
            "entity_id": entity_id,
            "dataset": ds_key,
            "temporal_semantics": semantics,
            "analysis_type": analysis_type,
            "history_scope": "OBSERVED_FUTURE_HISTORY",
            "successor_count": len(next_evts),
            "ordered_successors": next_evts
        }

    def find_temporal_paths(
        self,
        source_entity: str,
        target_entity: str,
        dataset: Optional[str] = None,
        max_hops: int = 3,
        max_paths: int = 5
    ) -> Dict[str, Any]:
        """
        Discovers multi-hop paths enforcing strict non-decreasing temporal ordering (t1 <= t2 <= ... <= tn).
        Handles timestamp equality, cycle avoidance, and disconnected graphs.
        """
        ds_key, df = self.get_dataset_for_entity(source_entity, dataset)
        if df.empty:
            return {"source_entity": source_entity, "target_entity": target_entity, "paths_count": 0, "paths": []}

        semantics = df["temporal_semantics"].iloc[0] if "temporal_semantics" in df.columns else TemporalSemantics.OBSERVED_TIMESTAMP

        # Build adjacency graph
        adj: Dict[str, List[Dict[str, Any]]] = {}
        for _, r in df.iterrows():
            u = r["actor_id"]
            v = r["target_id"]
            if pd.isna(v) or not v:
                continue
            if u not in adj:
                adj[u] = []
            adj[u].append({
                "source": u,
                "target": v,
                "event_id": r["event_id"],
                "timestamp": r["timestamp"],
                "epoch_time": float(r["epoch_time"]),
                "temporal_semantics": r.get("temporal_semantics", semantics),
                "domain": r["source_domain"],
                "evidence_ref": f"hash:{r['sha256_hash'][:16]}"
            })

        found_paths = []

        def dfs(curr: str, path: List[Dict[str, Any]], last_epoch: float, visited: Set[str]):
            if len(found_paths) >= max_paths:
                return
            if curr == target_entity and len(path) > 0:
                found_paths.append({
                    "hops": len(path),
                    "temporal_monotonic": True,
                    "temporal_semantics": semantics,
                    "sequence": list(path)
                })
                return
            if len(path) >= max_hops:
                return

            for edge in adj.get(curr, []):
                nxt = edge["target"]
                edge_epoch = edge["epoch_time"]
                # Non-decreasing monotonic constraint: t_next >= last_epoch
                if edge_epoch >= last_epoch and nxt not in visited:
                    visited.add(nxt)
                    path.append(edge)
                    dfs(nxt, path, edge_epoch, visited)
                    path.pop()
                    visited.remove(nxt)

        dfs(source_entity, [], 0.0, {source_entity})

        return {
            "source_entity": source_entity,
            "target_entity": target_entity,
            "dataset": ds_key,
            "temporal_semantics": semantics,
            "paths_count": len(found_paths),
            "paths": found_paths
        }
