# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: Forensic Graph Traversal, Causal Backtracking & Forward Tracking Engine

import json
import os
from typing import Dict, Any, List, Optional, Tuple, Set
import pandas as pd


class InvestigationGraphTraversal:
    """
    Forensic Graph Traversal Engine.
    Enforces strict temporal causality:
    - Backtracking: Traverses strictly backward in time (t_prev <= t_pivot).
    - Forward Tracking: Traverses strictly forward in time (t_next >= t_pivot).
    - Temporal Paths: Enforces monotonic non-decreasing timestamps along multi-hop chains.
    - Surrogate Semantics: Explicitly distinguishes SEQUENCE_ORDER_SURROGATE from OBSERVED_TIMESTAMP.
    All results include entity/event ID, relationship type, timestamp, dataset, and evidence reference.
    """

    def __init__(self, canonical_dir: str = "data/canonical"):
        self.canonical_dir = canonical_dir
        self.events_cache: Dict[str, pd.DataFrame] = {}

    def _get_events(self, dataset: str) -> pd.DataFrame:
        key = dataset.lower().strip()
        if key not in self.events_cache:
            p = f"{self.canonical_dir}/{key}_canonical.parquet"
            self.events_cache[key] = pd.read_parquet(p).sort_values("epoch_time").reset_index(drop=True)
        return self.events_cache[key]

    def validate_time_window(self, dataset: str, start_date: Optional[str] = None, end_date: Optional[str] = None):
        """Rejects date-range queries on surrogate temporal datasets."""
        if start_date or end_date:
            df = self._get_events(dataset)
            is_surrogate = (dataset.lower() == "unsw") or (
                "temporal_semantics" in df.columns and (df["temporal_semantics"] == "SEQUENCE_ORDER_SURROGATE").any()
            )
            if is_surrogate:
                raise ValueError(
                    f"Date-range queries are unsupported for dataset '{dataset}' because its temporal semantics are "
                    f"SEQUENCE_ORDER_SURROGATE. Real-world calendar dates cannot be evaluated on sequence-order surrogate time."
                )

    def backtrack(
        self,
        entity_id: str,
        pivot_timestamp: Optional[str] = None,
        dataset: str = "elliptic",
        max_hops: int = 2,
        max_results: int = 20,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Backtracking: "What happened before this?"
        Returns causal preceding chain leading up to the entity's event at pivot_timestamp.
        Distinguishes ORDER_BACKTRACK (surrogate) from BACKTRACK (observed).
        """
        self.validate_time_window(dataset, start_date, end_date)
        df = self._get_events(dataset)
        pivot_epoch = pd.to_datetime(pivot_timestamp).timestamp() if pivot_timestamp else float("inf")

        is_surrogate = (dataset.lower() == "unsw") or (
            "temporal_semantics" in df.columns and (df["temporal_semantics"] == "SEQUENCE_ORDER_SURROGATE").any()
        )
        query_mode = "ORDER_BACKTRACK" if is_surrogate else "BACKTRACK"
        analysis_type = "SEQUENCE_ORDER_ANALYSIS" if is_surrogate else "REAL_TIME_TEMPORAL_ANALYSIS"
        temporal_semantics = "SEQUENCE_ORDER_SURROGATE" if is_surrogate else "OBSERVED_TIMESTAMP"

        # Prior events involving entity as actor or target
        prior_mask = (df["epoch_time"] <= pivot_epoch) & ((df["actor_id"] == entity_id) | (df["target_id"] == entity_id))
        sub_df = df[prior_mask].sort_values("epoch_time", ascending=False).head(max_results)

        steps = []
        for _, r in sub_df.iterrows():
            is_actor = (r["actor_id"] == entity_id)
            rel = "OUTFLOW_TO" if is_actor else "INFLOW_FROM"
            counterparty = r["target_id"] if is_actor else r["actor_id"]

            steps.append({
                "direction": "BACKWARD",
                "timestamp": r["timestamp"],
                "epoch_time": r["epoch_time"],
                "event_id": r["event_id"],
                "source_entity": r["actor_id"],
                "relationship": rel,
                "target_entity": r["target_id"],
                "counterparty": counterparty,
                "amount": float(r.get("amount", 0.0)),
                "domain": r["source_domain"],
                "dataset": dataset,
                "temporal_semantics": r.get("temporal_semantics", temporal_semantics),
                "evidence_ref": f"hash:{r['sha256_hash'][:16]}"
            })

        return {
            "query": query_mode,
            "entity_id": entity_id,
            "pivot_timestamp": pivot_timestamp,
            "dataset": dataset,
            "temporal_semantics": temporal_semantics,
            "analysis_type": analysis_type,
            "preceding_steps_count": len(steps),
            "preceding_timeline": steps
        }

    def forwardtrack(
        self,
        entity_id: str,
        pivot_timestamp: Optional[str] = None,
        dataset: str = "elliptic",
        max_results: int = 20,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Forward Tracking: "What happened afterward?"
        Returns subsequent forward events radiating from entity after pivot_timestamp.
        Distinguishes ORDER_FORWARD_TRACK (surrogate) from FORWARDTRACK (observed).
        """
        self.validate_time_window(dataset, start_date, end_date)
        df = self._get_events(dataset)
        pivot_epoch = pd.to_datetime(pivot_timestamp).timestamp() if pivot_timestamp else 0.0

        is_surrogate = (dataset.lower() == "unsw") or (
            "temporal_semantics" in df.columns and (df["temporal_semantics"] == "SEQUENCE_ORDER_SURROGATE").any()
        )
        query_mode = "ORDER_FORWARD_TRACK" if is_surrogate else "FORWARDTRACK"
        analysis_type = "SEQUENCE_ORDER_ANALYSIS" if is_surrogate else "REAL_TIME_TEMPORAL_ANALYSIS"
        temporal_semantics = "SEQUENCE_ORDER_SURROGATE" if is_surrogate else "OBSERVED_TIMESTAMP"

        forward_mask = (df["epoch_time"] >= pivot_epoch) & ((df["actor_id"] == entity_id) | (df["target_id"] == entity_id))
        sub_df = df[forward_mask].sort_values("epoch_time", ascending=True).head(max_results)

        steps = []
        for _, r in sub_df.iterrows():
            is_actor = (r["actor_id"] == entity_id)
            rel = "OUTFLOW_TO" if is_actor else "INFLOW_FROM"
            counterparty = r["target_id"] if is_actor else r["actor_id"]

            steps.append({
                "direction": "FORWARD",
                "timestamp": r["timestamp"],
                "epoch_time": r["epoch_time"],
                "event_id": r["event_id"],
                "source_entity": r["actor_id"],
                "relationship": rel,
                "target_entity": r["target_id"],
                "counterparty": counterparty,
                "amount": float(r.get("amount", 0.0)),
                "domain": r["source_domain"],
                "dataset": dataset,
                "temporal_semantics": r.get("temporal_semantics", temporal_semantics),
                "evidence_ref": f"hash:{r['sha256_hash'][:16]}"
            })

        return {
            "query": query_mode,
            "entity_id": entity_id,
            "pivot_timestamp": pivot_timestamp,
            "dataset": dataset,
            "temporal_semantics": temporal_semantics,
            "analysis_type": analysis_type,
            "subsequent_steps_count": len(steps),
            "subsequent_timeline": steps
        }

    def backtrack_events(
        self,
        entity_id: str,
        pivot_timestamp: Optional[str] = None,
        events: Optional[List[Dict[str, Any]]] = None,
        max_results: int = 20
    ) -> Dict[str, Any]:
        """In-memory causal backtracking on observable case events ONLY."""
        df = pd.DataFrame(events) if events else pd.DataFrame()
        if df.empty:
            return {"query": "BACKTRACK", "entity_id": entity_id, "preceding_steps_count": 0, "preceding_timeline": []}

        is_surrogate = "temporal_semantics" in df.columns and (df["temporal_semantics"] == "SEQUENCE_ORDER_SURROGATE").any()
        query_mode = "ORDER_BACKTRACK" if is_surrogate else "BACKTRACK"
        analysis_type = "SEQUENCE_ORDER_ANALYSIS" if is_surrogate else "REAL_TIME_TEMPORAL_ANALYSIS"
        temporal_semantics = "SEQUENCE_ORDER_SURROGATE" if is_surrogate else "OBSERVED_TIMESTAMP"

        pivot_epoch = pd.to_datetime(pivot_timestamp).timestamp() if pivot_timestamp else float("inf")
        prior_mask = (df["epoch_time"] <= pivot_epoch) & ((df["actor_id"] == entity_id) | (df["target_id"] == entity_id))
        sub_df = df[prior_mask].sort_values("epoch_time", ascending=False).head(max_results)

        steps = []
        for _, r in sub_df.iterrows():
            is_actor = (r["actor_id"] == entity_id)
            rel = "OUTFLOW_TO" if is_actor else "INFLOW_FROM"
            counterparty = r.get("target_id") if is_actor else r.get("actor_id")

            steps.append({
                "direction": "BACKWARD",
                "timestamp": str(r["timestamp"]),
                "epoch_time": float(r["epoch_time"]),
                "event_id": str(r["event_id"]),
                "source_entity": str(r["actor_id"]),
                "relationship": rel,
                "target_entity": str(r.get("target_id", "")),
                "counterparty": str(counterparty),
                "amount": float(r.get("amount", 0.0)),
                "domain": str(r.get("source_domain", "")),
                "temporal_semantics": r.get("temporal_semantics", temporal_semantics),
                "evidence_ref": f"hash:{str(r.get('sha256_hash', ''))[:16]}"
            })

        return {
            "query": query_mode,
            "entity_id": entity_id,
            "pivot_timestamp": pivot_timestamp,
            "temporal_semantics": temporal_semantics,
            "analysis_type": analysis_type,
            "preceding_steps_count": len(steps),
            "preceding_timeline": steps
        }

    def forwardtrack_events(
        self,
        entity_id: str,
        pivot_timestamp: Optional[str] = None,
        events: Optional[List[Dict[str, Any]]] = None,
        max_results: int = 20
    ) -> Dict[str, Any]:
        """In-memory causal forward tracking on observable case events ONLY."""
        df = pd.DataFrame(events) if events else pd.DataFrame()
        if df.empty:
            return {"query": "FORWARDTRACK", "entity_id": entity_id, "subsequent_steps_count": 0, "subsequent_timeline": []}

        is_surrogate = "temporal_semantics" in df.columns and (df["temporal_semantics"] == "SEQUENCE_ORDER_SURROGATE").any()
        query_mode = "ORDER_FORWARD_TRACK" if is_surrogate else "FORWARDTRACK"
        analysis_type = "SEQUENCE_ORDER_ANALYSIS" if is_surrogate else "REAL_TIME_TEMPORAL_ANALYSIS"
        temporal_semantics = "SEQUENCE_ORDER_SURROGATE" if is_surrogate else "OBSERVED_TIMESTAMP"

        pivot_epoch = pd.to_datetime(pivot_timestamp).timestamp() if pivot_timestamp else 0.0
        forward_mask = (df["epoch_time"] >= pivot_epoch) & ((df["actor_id"] == entity_id) | (df["target_id"] == entity_id))
        sub_df = df[forward_mask].sort_values("epoch_time", ascending=True).head(max_results)

        steps = []
        for _, r in sub_df.iterrows():
            is_actor = (r["actor_id"] == entity_id)
            rel = "OUTFLOW_TO" if is_actor else "INFLOW_FROM"
            counterparty = r.get("target_id") if is_actor else r.get("actor_id")

            steps.append({
                "direction": "FORWARD",
                "timestamp": str(r["timestamp"]),
                "epoch_time": float(r["epoch_time"]),
                "event_id": str(r["event_id"]),
                "source_entity": str(r["actor_id"]),
                "relationship": rel,
                "target_entity": str(r.get("target_id", "")),
                "counterparty": str(counterparty),
                "amount": float(r.get("amount", 0.0)),
                "domain": str(r.get("source_domain", "")),
                "temporal_semantics": r.get("temporal_semantics", temporal_semantics),
                "evidence_ref": f"hash:{str(r.get('sha256_hash', ''))[:16]}"
            })

        return {
            "query": query_mode,
            "entity_id": entity_id,
            "pivot_timestamp": pivot_timestamp,
            "temporal_semantics": temporal_semantics,
            "analysis_type": analysis_type,
            "subsequent_steps_count": len(steps),
            "subsequent_timeline": steps
        }

    def get_2hop_subgraph(
        self,
        entity_id: str,
        dataset: Optional[str] = None,
        max_hops: int = 2,
        max_results: int = 20
    ) -> Dict[str, Any]:
        """
        Returns the canonical 1-hop and 2-hop neighborhood for an entity using real funding, telecom,
        social, or financial canonical events. The structure is intentionally compatible with the M13
        workspace and CLI contract.
        """
        if max_hops < 0:
            raise ValueError("max_hops must be >= 0")

        frames: List[pd.DataFrame] = []
        if dataset:
            frames.append(self._get_events(dataset))
        else:
            for name in sorted(os.listdir(self.canonical_dir)):
                if not name.endswith("_canonical.parquet"):
                    continue
                path = os.path.join(self.canonical_dir, name)
                try:
                    frames.append(pd.read_parquet(path))
                except Exception:
                    continue

        if not frames:
            return {
                "entity_id": entity_id,
                "dataset": dataset,
                "1hop_neighbors": [],
                "2hop_neighbors": [],
                "relationships": [],
                "hops": 0,
            }

        df = pd.concat(frames, ignore_index=True)
        if df.empty:
            return {
                "entity_id": entity_id,
                "dataset": dataset,
                "1hop_neighbors": [],
                "2hop_neighbors": [],
                "relationships": [],
                "hops": 0,
            }

        if "actor_id" not in df.columns or "target_id" not in df.columns:
            raise ValueError(f"Graph contract for '{entity_id}' is invalid: missing actor/target columns.")

        entity_id = str(entity_id)
        registry_values = set()
        for registry_path in [
            os.path.join("output", "resolved_entities.parquet"),
            os.path.join("data", "cases", "identity_bridge.parquet"),
        ]:
            if os.path.exists(registry_path):
                try:
                    reg_df = pd.read_parquet(registry_path)
                except Exception:
                    continue
                for col in ["canonical_entity_id", "raw_identifier"]:
                    if col in reg_df.columns:
                        registry_values.update(str(v).strip() for v in reg_df[col].dropna().tolist())

        entity_present = ((df["actor_id"].astype(str) == entity_id) | (df["target_id"].astype(str) == entity_id)).any()
        if entity_id not in registry_values and not entity_present:
            raise ValueError(f"Unknown graph entity '{entity_id}' in canonical event graph.")

        neighbors_1 = set()
        neighbors_2 = set()
        relationships: List[Dict[str, Any]] = []

        df = df[(df["actor_id"].astype(str).notna()) | (df["target_id"].astype(str).notna())].copy()

        def record_relationship(row, direction: str, counterpart: str, edge_type: str):
            relationships.append({
                "source": str(row.get("actor_id", "")),
                "target": str(row.get("target_id", "")),
                "direction": direction,
                "counterparty": counterpart,
                "relationship_type": edge_type,
                "event_id": str(row.get("event_id", "")),
                "timestamp": row.get("timestamp"),
                "epoch_time": float(row.get("epoch_time", 0.0)),
                "source_domain": str(row.get("source_domain", "")),
                "evidence_ref": f"hash:{str(row.get('sha256_hash',''))[:16]}",
            })

        for _, r in df.iterrows():
            actor = str(r.get("actor_id", ""))
            target = str(r.get("target_id", ""))
            if actor == entity_id:
                neighbors_1.add(target)
                record_relationship(r, "OUTFLOW_TO", target, r.get("event_type", "TRANSACTION"))
            elif target == entity_id:
                neighbors_1.add(actor)
                record_relationship(r, "INFLOW_FROM", actor, r.get("event_type", "TRANSACTION"))

        # Second hop via each direct neighbor
        for direct in sorted(neighbors_1):
            if direct == entity_id:
                continue
            direct_mask = ((df["actor_id"].astype(str) == direct) | (df["target_id"].astype(str) == direct))
            for _, r in df[direct_mask].iterrows():
                other = str(r.get("target_id", "")) if str(r.get("actor_id", "")) == direct else str(r.get("actor_id", ""))
                if other and other != entity_id and other != direct:
                    neighbors_2.add(other)

        ordered_1 = sorted([n for n in neighbors_1 if n and n != entity_id])[:max_results]
        ordered_2 = sorted([n for n in neighbors_2 if n and n != entity_id])[:max_results]

        return {
            "entity_id": entity_id,
            "dataset": dataset or "MULTI_DOMAIN",
            "1hop_neighbors": ordered_1,
            "2hop_neighbors": ordered_2,
            "relationships": relationships[:max_results],
            "hops": max_hops,
        }

    def find_temporal_paths(
        self,
        source_entity: str,
        target_entity: str,
        dataset: str = "elliptic",
        max_hops: int = 3,
        max_paths: int = 5
    ) -> List[List[Dict[str, Any]]]:
        """
        Finds paths from source to target entity where timestamps along the path
        are strictly monotonic non-decreasing (t_1 <= t_2 <= ... <= t_k).
        """
        df = self._get_events(dataset)

        # Build adjacency graph
        adj: Dict[str, List[Dict[str, Any]]] = {}
        for _, r in df.iterrows():
            u = r["actor_id"]
            v = r["target_id"]
            if u not in adj:
                adj[u] = []
            adj[u].append({
                "source": u,
                "target": v,
                "event_id": r["event_id"],
                "timestamp": r["timestamp"],
                "epoch_time": float(r["epoch_time"]),
                "domain": r["source_domain"],
                "amount": float(r.get("amount", 0.0)),
                "evidence_ref": f"hash:{r['sha256_hash'][:16]}"
            })

        # DFS search for temporal paths
        found_paths: List[List[Dict[str, Any]]] = []

        def dfs(current_node: str, current_path: List[Dict[str, Any]], last_epoch: float, visited_nodes: Set[str]):
            if len(found_paths) >= max_paths:
                return
            if current_node == target_entity and len(current_path) > 0:
                found_paths.append({
                    "hops": len(current_path),
                    "temporal_monotonic": True,
                    "sequence": list(current_path)
                })
                return
            if len(current_path) >= max_hops:
                return

            for edge in adj.get(current_node, []):
                next_node = edge["target"]
                edge_epoch = edge["epoch_time"]

                # Strict monotonic non-decreasing temporal ordering
                if edge_epoch >= last_epoch and next_node not in visited_nodes:
                    visited_nodes.add(next_node)
                    current_path.append(edge)
                    dfs(next_node, current_path, edge_epoch, visited_nodes)
                    current_path.pop()
                    visited_nodes.remove(next_node)

        dfs(source_entity, [], 0.0, {source_entity})
        return {
            "source_entity": source_entity,
            "target_entity": target_entity,
            "paths_count": len(found_paths),
            "paths": found_paths
        }

    def find_common_entities(
        self,
        entity_a: str,
        entity_b: str,
        dataset: str = "elliptic",
        max_hops: int = 2
    ) -> Dict[str, Any]:
        """
        Finds common counterparties or intermediary entities connecting entity_a and entity_b.
        """
        df = self._get_events(dataset)

        # Counterparties for entity_a
        mask_a = (df["actor_id"] == entity_a) | (df["target_id"] == entity_a)
        neighbors_a = set(df[mask_a]["actor_id"]).union(set(df[mask_a]["target_id"])) - {entity_a}

        # Counterparties for entity_b
        mask_b = (df["actor_id"] == entity_b) | (df["target_id"] == entity_b)
        neighbors_b = set(df[mask_b]["actor_id"]).union(set(df[mask_b]["target_id"])) - {entity_b}

        common = sorted(list(neighbors_a.intersection(neighbors_b)))

        connecting_evidence = []
        for ent in common:
            # Events connecting A to ent
            ev_a = df[((df["actor_id"] == entity_a) & (df["target_id"] == ent)) | ((df["actor_id"] == ent) & (df["target_id"] == entity_a))]
            # Events connecting ent to B
            ev_b = df[((df["actor_id"] == ent) & (df["target_id"] == entity_b)) | ((df["actor_id"] == entity_b) & (df["target_id"] == ent))]

            for _, r in ev_a.head(2).iterrows():
                connecting_evidence.append({
                    "intermediary": ent,
                    "event_id": r["event_id"],
                    "link": f"{entity_a} <-> {ent}",
                    "timestamp": r["timestamp"],
                    "evidence_ref": f"hash:{r['sha256_hash'][:16]}"
                })
            for _, r in ev_b.head(2).iterrows():
                connecting_evidence.append({
                    "intermediary": ent,
                    "event_id": r["event_id"],
                    "link": f"{ent} <-> {entity_b}",
                    "timestamp": r["timestamp"],
                    "evidence_ref": f"hash:{r['sha256_hash'][:16]}"
                })

        return {
            "entity_a": entity_a,
            "entity_b": entity_b,
            "dataset": dataset,
            "common_count": len(common),
            "common_entities": common,
            "connecting_evidence": connecting_evidence
        }
