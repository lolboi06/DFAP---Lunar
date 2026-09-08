# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: M13 Network & 2-Hop Subgraph Backend with Deterministic Cytoscape Serializer

import json
from typing import Dict, List, Any, Optional, Set, Tuple
import pandas as pd
import igraph as ig

from dfap.graph import DFAPGraphService
from dfap.wp4.contracts import (
    ErrorCode,
    WorkspaceError,
    RelationshipStatus,
    CytoscapeGraph,
    CytoscapeNodeData,
    CytoscapeEdgeData,
)


class NetworkService:
    """
    M13 Network & Subgraph Extraction Service.
    Powered by the Member 2 DFAPGraphService backend.
    Note: KùzuDB remains an external physical graph integration target.
    Enforces strict 2-hop bounded traversals, independent distance verification,
    and byte-for-byte deterministic Cytoscape payload serialization.
    """

    def __init__(self, events_path: str = "output/canonical_events.parquet", entities_path: str = "output/resolved_entities.parquet"):
        self.graph_service = DFAPGraphService()
        self.events_path = events_path
        self.entities_path = entities_path
        self._load_graph()

    def _load_graph(self):
        self.graph_service.load_graph_from_parquet(self.events_path, self.entities_path)
        self.g = self.graph_service.g
        self.node_mapping = self.graph_service.node_mapping

    def get_entity_subgraph(
        self,
        entity_id: str,
        hops: int = 2,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Extracts subgraph up to hops distance (0 <= hops <= 2) for entity_id.
        Validates hop distance independently to prevent unbounded traversal.
        """
        if not isinstance(hops, int):
            raise WorkspaceError(f"Hops must be an integer, got: {type(hops).__name__}", ErrorCode.INVALID_HOP_COUNT)

        if hops < 0 or hops > 2:
            raise WorkspaceError(f"Hops must be in range [0, 2], got: {hops}", ErrorCode.INVALID_HOP_COUNT)

        ent_str = str(entity_id).strip()
        if ent_str not in self.node_mapping:
            return {"nodes": [], "edges": [], "hop_count": hops, "root_entity": ent_str}

        root_idx = self.node_mapping[ent_str]

        # 1. Independent BFS hop-distance calculation
        distances = self.g.distances(source=[root_idx], target=None, mode="all")[0]
        
        valid_node_indices: Set[int] = set()
        for v_idx, dist in enumerate(distances):
            if dist <= hops:
                valid_node_indices.add(v_idx)

        # 2. Extract nodes deterministically
        nodes: List[Dict[str, Any]] = []
        for v_idx in sorted(valid_node_indices):
            v = self.g.vs[v_idx]
            n_attrs = {k: v[k] for k in v.attributes()}
            node_id = str(v["name"])
            node_type = str(v["node_type"])
            nodes.append({
                "id": node_id,
                "label": node_id,
                "node_type": node_type,
                "hop_distance": distances[v_idx],
                "metadata": {k: v for k, v in n_attrs.items() if k not in ("name", "node_type")}
            })

        # 3. Extract edges where both endpoints are in valid_node_indices
        edges: List[Dict[str, Any]] = []
        seen_edges = set()

        for e in self.g.es:
            s_idx = e.source
            t_idx = e.target
            if s_idx in valid_node_indices and t_idx in valid_node_indices:
                s_name = str(self.g.vs[s_idx]["name"])
                t_name = str(self.g.vs[t_idx]["name"])
                rel_type = str(e["relationship_type"])
                rel_status = str(e["status"])

                # Validate relationship status
                if rel_status not in (RelationshipStatus.OBSERVED.value, RelationshipStatus.INFERRED.value):
                    raise WorkspaceError(
                        f"Unknown relationship status '{rel_status}' on edge {s_name} -> {t_name}",
                        ErrorCode.UNKNOWN_RELATIONSHIP_STATUS
                    )

                raw_ev_refs = e["evidence_refs"]
                if isinstance(raw_ev_refs, list):
                    ev_refs = tuple(sorted(str(r) for r in raw_ev_refs))
                else:
                    ev_refs = (str(raw_ev_refs),) if raw_ev_refs else ()

                edge_id = f"EDGE:{s_name}:{rel_type}:{t_name}:{rel_status}"
                if edge_id in seen_edges:
                    continue
                seen_edges.add(edge_id)

                edges.append({
                    "id": edge_id,
                    "source": s_name,
                    "target": t_name,
                    "relationship_type": rel_type,
                    "relationship_status": rel_status,
                    "evidence_event_ids": list(ev_refs),
                    "timestamp": str(e["timestamp"]) if "timestamp" in e.attributes() else None,
                    "metadata": {k: e[k] for k in e.attributes() if k not in ("relationship_type", "status", "evidence_refs", "timestamp")}
                })

        # Sort nodes and edges deterministically
        nodes.sort(key=lambda x: (x["hop_distance"], x["id"]))
        edges.sort(key=lambda x: (x["id"]))

        return {
            "root_entity": ent_str,
            "hop_count": hops,
            "node_count": len(nodes),
            "edge_count": len(edges),
            "nodes": nodes,
            "edges": edges,
        }

    @staticmethod
    def to_cytoscape_payload(subgraph_dict: Dict[str, Any]) -> CytoscapeGraph:
        """
        Converts subgraph dictionary to deterministic Cytoscape-compatible node/edge payload.
        Guarantees byte-for-byte identical output on identical inputs.
        """
        raw_nodes = subgraph_dict.get("nodes", [])
        raw_edges = subgraph_dict.get("edges", [])

        cy_nodes: List[Dict[str, Any]] = []
        cy_edges: List[Dict[str, Any]] = []

        seen_node_ids = set()
        for n in sorted(raw_nodes, key=lambda x: str(x.get("id", ""))):
            n_id = str(n.get("id", "")).strip()
            if not n_id or n_id in seen_node_ids:
                continue
            seen_node_ids.add(n_id)

            cy_nodes.append({
                "data": {
                    "id": n_id,
                    "label": str(n.get("label", n_id)),
                    "node_type": str(n.get("node_type", "Entity")),
                    "hop_distance": n.get("hop_distance", 0),
                    "metadata": n.get("metadata", {})
                }
            })

        seen_edge_ids = set()
        for e in sorted(raw_edges, key=lambda x: str(x.get("id", ""))):
            e_id = str(e.get("id", "")).strip()
            if not e_id or e_id in seen_edge_ids:
                continue
            seen_edge_ids.add(e_id)

            cy_edges.append({
                "data": {
                    "id": e_id,
                    "source": str(e.get("source", "")),
                    "target": str(e.get("target", "")),
                    "relationship_type": str(e.get("relationship_type", "ASSOCIATED_WITH")),
                    "relationship_status": str(e.get("relationship_status", "OBSERVED")),
                    "evidence_event_ids": sorted(list(e.get("evidence_event_ids", []))),
                    "timestamp": e.get("timestamp"),
                    "metadata": e.get("metadata", {})
                }
            })

        return CytoscapeGraph(
            nodes=tuple(cy_nodes),
            edges=tuple(cy_edges)
        )
