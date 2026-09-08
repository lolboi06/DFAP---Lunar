# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: Enterprise-Scale Analytical Graph Service & Pluggable Storage Backend Architecture

import json
import logging
import os
import sqlite3
import sys
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple, Set

from dateutil.parser import isoparse
import duckdb
import igraph as ig
import pandas as pd

logger = logging.getLogger(__name__)


class GraphStateBackend(ABC):
    """
    Abstract analytical graph state backend interface.
    Decouples in-memory analytical graph traversal from persistent storage.
    """

    def __init__(self):
        self.g: ig.Graph = ig.Graph(directed=True)
        self.node_mapping: Dict[str, int] = {}
        self.eviction_count: int = 0

    @abstractmethod
    def record_node(self, name: str, node_type: str, **kwargs) -> int:
        pass

    @abstractmethod
    def record_edge(
        self,
        source_name: str,
        target_name: str,
        rel_type: str,
        status: str,
        timestamp: str,
        epoch_time: float,
        evidence_refs: List[str]
    ):
        pass

    @abstractmethod
    def evict_if_needed(self) -> int:
        pass

    @abstractmethod
    def persist_state(self, path: Optional[str] = None):
        pass

    @abstractmethod
    def recover_state(self, path: Optional[str] = None):
        pass


class InMemoryGraphBackend(GraphStateBackend):
    """Default unbounded in-memory graph backend for test execution and small batches."""

    def __init__(self):
        super().__init__()

    def record_node(self, name: str, node_type: str, **kwargs) -> int:
        if name in self.node_mapping:
            return self.node_mapping[name]
        v = self.g.add_vertex(name=name, node_type=node_type, **kwargs)
        self.node_mapping[name] = v.index
        return v.index

    def record_edge(
        self,
        source_name: str,
        target_name: str,
        rel_type: str,
        status: str,
        timestamp: str,
        epoch_time: float,
        evidence_refs: List[str]
    ):
        s_idx = self.node_mapping.get(source_name)
        t_idx = self.node_mapping.get(target_name)
        if s_idx is not None and t_idx is not None:
            self.g.add_edge(
                s_idx,
                t_idx,
                relationship_type=rel_type,
                status=status,
                timestamp=timestamp,
                epoch_time=epoch_time,
                evidence_refs=evidence_refs
            )

    def evict_if_needed(self) -> int:
        return 0

    def persist_state(self, path: Optional[str] = None):
        pass

    def recover_state(self, path: Optional[str] = None):
        pass


class PersistentGraphBackend(GraphStateBackend):
    """
    Enterprise-Scale Bounded Persistent Graph Backend:
    - Bounded active memory: maintains a rolling active graph window in igraph.
    - Persistent SQLite storage: preserves all nodes, edges, and evidence refs permanently.
    - Evidence preservation: evicts older event vertices from RAM while retaining evidence chains in DB.
    - Process restart recovery: restores active window state after crash/kill.
    """

    def __init__(self, db_path: str = ":memory:", max_active_nodes: int = 5000):
        super().__init__()
        self.db_path = db_path
        self.max_active_nodes = max_active_nodes
        self.conn = sqlite3.connect(self.db_path)
        self._init_db()

    def _init_db(self):
        with self.conn:
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS graph_nodes (
                    name TEXT PRIMARY KEY,
                    node_type TEXT,
                    attributes TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS graph_edges (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_name TEXT,
                    target_name TEXT,
                    relationship_type TEXT,
                    status TEXT,
                    timestamp TEXT,
                    epoch_time REAL,
                    evidence_refs TEXT
                )
            """)
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_edges_source ON graph_edges(source_name)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_edges_target ON graph_edges(target_name)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_edges_epoch ON graph_edges(epoch_time)")

    def record_node(self, name: str, node_type: str, **kwargs) -> int:
        attrs_json = json.dumps(kwargs, default=str)
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO graph_nodes (name, node_type, attributes) VALUES (?, ?, ?)",
                (name, node_type, attrs_json)
            )

        if name not in self.node_mapping:
            v = self.g.add_vertex(name=name, node_type=node_type, **kwargs)
            self.node_mapping[name] = v.index
            self.evict_if_needed()
            return self.node_mapping.get(name, -1)
        return self.node_mapping.get(name, -1)

    def record_edge(
        self,
        source_name: str,
        target_name: str,
        rel_type: str,
        status: str,
        timestamp: str,
        epoch_time: float,
        evidence_refs: List[str]
    ):
        refs_json = json.dumps(evidence_refs)
        with self.conn:
            self.conn.execute(
                "INSERT INTO graph_edges (source_name, target_name, relationship_type, status, timestamp, epoch_time, evidence_refs) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (source_name, target_name, rel_type, status, timestamp, epoch_time, refs_json)
            )

        s_idx = self.node_mapping.get(source_name)
        t_idx = self.node_mapping.get(target_name)
        if s_idx is not None and t_idx is not None:
            self.g.add_edge(
                s_idx,
                t_idx,
                relationship_type=rel_type,
                status=status,
                timestamp=timestamp,
                epoch_time=epoch_time,
                evidence_refs=evidence_refs
            )

    def evict_if_needed(self) -> int:
        """Evicts oldest Event nodes when active vertex count exceeds max_active_nodes."""
        if self.g.vcount() <= self.max_active_nodes:
            return 0

        # Keep permanent entity nodes (Phone, Account, Person); evict oldest Event nodes
        event_nodes = [v for v in self.g.vs if v["node_type"] == "Event"]
        target_eviction = len(event_nodes) - (self.max_active_nodes // 2)
        if target_eviction <= 0:
            return 0

        # Sort events by epoch_time ascending (oldest first)
        event_nodes.sort(key=lambda x: x.attributes().get("epoch_time", 0.0) or 0.0)
        to_delete_indices = [v.index for v in event_nodes[:target_eviction]]

        num_evicted = len(to_delete_indices)
        self.g.delete_vertices(to_delete_indices)
        self.node_mapping = {v["name"]: v.index for v in self.g.vs}
        self.eviction_count += num_evicted
        return num_evicted

    def persist_state(self, path: Optional[str] = None):
        """Forces WAL checkpoint of persistent SQLite storage."""
        with self.conn:
            self.conn.execute("PRAGMA wal_checkpoint(FULL)")

    def recover_state(self, path: Optional[str] = None):
        """Restores active memory window from persistent SQLite database."""
        if path and path != self.db_path:
            self.db_path = path
            self.conn = sqlite3.connect(self.db_path)
            self._init_db()

        self.g = ig.Graph(directed=True)
        self.node_mapping.clear()

        # Load entity nodes first
        cursor = self.conn.cursor()
        cursor.execute("SELECT name, node_type, attributes FROM graph_nodes WHERE node_type != 'Event'")
        for name, n_type, attrs_str in cursor.fetchall():
            attrs = json.loads(attrs_str) if attrs_str else {}
            v = self.g.add_vertex(name=name, node_type=n_type, **attrs)
            self.node_mapping[name] = v.index

        # Load most recent Event nodes up to active threshold
        cursor.execute(
            "SELECT name, node_type, attributes FROM graph_nodes WHERE node_type = 'Event' ORDER BY rowid DESC LIMIT ?",
            (self.max_active_nodes // 2,)
        )
        for name, n_type, attrs_str in cursor.fetchall():
            attrs = json.loads(attrs_str) if attrs_str else {}
            v = self.g.add_vertex(name=name, node_type=n_type, **attrs)
            self.node_mapping[name] = v.index

        # Load active edges incident to active vertices
        active_names = tuple(self.node_mapping.keys())
        if active_names:
            placeholders = ",".join(["?"] * len(active_names))
            cursor.execute(f"""
                SELECT source_name, target_name, relationship_type, status, timestamp, epoch_time, evidence_refs
                FROM graph_edges
                WHERE source_name IN ({placeholders}) AND target_name IN ({placeholders})
                ORDER BY id ASC
            """, active_names + active_names)

            edge_list = []
            edge_attrs = {
                'relationship_type': [], 'status': [], 'timestamp': [],
                'epoch_time': [], 'evidence_refs': []
            }
            for s_name, t_name, rel, stat, ts, ep, refs in cursor.fetchall():
                edge_list.append((self.node_mapping[s_name], self.node_mapping[t_name]))
                edge_attrs['relationship_type'].append(rel)
                edge_attrs['status'].append(stat)
                edge_attrs['timestamp'].append(ts)
                edge_attrs['epoch_time'].append(ep)
                edge_attrs['evidence_refs'].append(json.loads(refs) if refs else [])

            if edge_list:
                self.g.add_edges(edge_list, attributes=edge_attrs)


class DFAPGraphService:
    """
    Production Analytical Graph Service backed by pluggable GraphStateBackend:
    - Default: InMemoryGraphBackend for backwards compatibility and zero-configuration testing.
    - Persistent: PersistentGraphBackend for enterprise-scale bounded memory and recovery.
    """

    def __init__(self, backend: Optional[GraphStateBackend] = None):
        self.backend = backend if backend is not None else InMemoryGraphBackend()
        self.g = self.backend.g
        self.node_mapping = self.backend.node_mapping

    def _get_epoch(self, ts: str) -> float:
        try:
            return isoparse(ts).timestamp()
        except Exception:
            return 0.0

    def load_graph_from_parquet(self, events_path: str, entities_path: str):
        logger.info(f"Loading M4 Graph from {events_path} and {entities_path}")
        con = duckdb.connect(database=':memory:')
        con.execute(f"CREATE TABLE events AS SELECT * FROM read_parquet('{events_path}')")
        con.execute(f"CREATE TABLE entities AS SELECT * FROM read_parquet('{entities_path}')")
        self._build_graph_from_duckdb(con)

    def load_graph_from_dataframes(self, events_df: pd.DataFrame, entities_df: pd.DataFrame):
        con = duckdb.connect(database=':memory:')
        con.register('df_events_view', events_df)
        con.register('df_entities_view', entities_df)
        con.execute("CREATE TABLE events AS SELECT * FROM df_events_view")
        con.execute("CREATE TABLE entities AS SELECT * FROM df_entities_view")
        self._build_graph_from_duckdb(con)

    def _build_graph_from_duckdb(self, con: duckdb.DuckDBPyConnection):
        entities_df = con.execute("""
            SELECT DISTINCT canonical_entity_id, identifier_type, match_status
            FROM entities
        """).df()

        type_mapping = {
            'PHONE': 'Phone', 'ACCOUNT': 'Account', 'IP': 'IP',
            'DEVICE': 'Device', 'HANDLE': 'SocialAccount', 'USER_ID': 'Person'
        }

        for _, row in entities_df.iterrows():
            eid = row['canonical_entity_id']
            if eid not in self.node_mapping:
                n_type = type_mapping.get(row['identifier_type'], 'Person')
                self.backend.record_node(
                    name=eid,
                    node_type=n_type,
                    original_type=row['identifier_type'],
                    match_status=row['match_status']
                )

        events_df = con.execute("""
            SELECT event_id, timestamp, event_type, source_domain, sha256_hash, attributes
            FROM events
        """).df()

        for _, row in events_df.iterrows():
            evid = row['event_id']
            if evid not in self.node_mapping:
                epoch = self._get_epoch(row['timestamp'])
                self.backend.record_node(
                    name=evid,
                    node_type="Event",
                    timestamp=row['timestamp'],
                    epoch_time=epoch,
                    event_type=row['event_type'],
                    source_domain=row['source_domain'],
                    sha256_hash=row['sha256_hash'],
                    attributes=row['attributes']
                )

        actor_edges = con.execute("""
            SELECT ent.canonical_entity_id, evt.event_id, evt.timestamp, evt.event_type
            FROM events evt JOIN entities ent ON evt.actor_id = ent.raw_identifier
        """).df()
        target_edges = con.execute("""
            SELECT ent.canonical_entity_id, evt.event_id, evt.timestamp, evt.event_type
            FROM events evt JOIN entities ent ON evt.target_id = ent.raw_identifier
        """).df()

        def get_rel(etype, role):
            if etype == 'CALL': return 'CALLS' if role == 'actor' else 'RECEIVES'
            if etype == 'TRANSACTION': return 'SENDS' if role == 'actor' else 'RECEIVES'
            if etype == 'LOGIN': return 'LOGGED_IN_FROM'
            if etype == 'SOCIAL': return 'POSTED' if role == 'actor' else 'INTERACTED_WITH'
            if etype == 'IP_SESSION': return 'CONNECTS_TO'
            return 'ASSOCIATED_WITH'

        for _, row in actor_edges.iterrows():
            eid = row['canonical_entity_id']
            evid = row['event_id']
            epoch = self._get_epoch(row['timestamp'])
            rel = get_rel(row['event_type'], 'actor')
            self.backend.record_edge(eid, evid, rel, 'OBSERVED', row['timestamp'], epoch, [evid])

        for _, row in target_edges.iterrows():
            eid = row['canonical_entity_id']
            evid = row['event_id']
            epoch = self._get_epoch(row['timestamp'])
            rel = get_rel(row['event_type'], 'target')
            self.backend.record_edge(evid, eid, rel, 'OBSERVED', row['timestamp'], epoch, [evid])

        # 4. Create INFERRED Relationships for IP_SESSION
        ip_sessions = con.execute("""
            SELECT evt.event_id, ent_a.canonical_entity_id as actor_eid, ent_t.canonical_entity_id as target_eid, evt.timestamp
            FROM events evt
            JOIN entities ent_a ON evt.actor_id = ent_a.raw_identifier
            JOIN entities ent_t ON evt.target_id = ent_t.raw_identifier
            WHERE evt.event_type = 'IP_SESSION'
        """).df()
        for _, row in ip_sessions.iterrows():
            epoch = self._get_epoch(row['timestamp'])
            self.backend.record_edge(row['actor_eid'], row['target_eid'], 'ASSOCIATED_WITH', 'INFERRED', row['timestamp'], epoch, [row['event_id']])

        # Synchronize local references
        self.g = self.backend.g
        self.node_mapping = self.backend.node_mapping

    def _in_window(self, epoch: float, start_time: float, end_time: float) -> bool:
        if start_time is not None and epoch < start_time:
            return False
        if end_time is not None and epoch > end_time:
            return False
        return True

    def get_entity_profile(self, node_name: str) -> Dict[str, Any]:
        """Returns vertex attributes dictionary for a given node name."""
        if node_name not in self.node_mapping:
            return {}
        v = self.g.vs[self.node_mapping[node_name]]
        return {k: v[k] for k in v.attributes()}

    def get_subgraph(self, entity_id: str, hops: int = 2, start_time: float = None, end_time: float = None) -> ig.Graph:
        """Extracts bounded k-hop subgraph around target entity."""
        if entity_id not in self.node_mapping:
            return ig.Graph(directed=True)

        v_idx = self.node_mapping[entity_id]
        visited = {v_idx}
        current_level = {v_idx}

        for _ in range(hops):
            next_level = set()
            for node in current_level:
                for neighbor in self.g.neighbors(node, mode="all"):
                    if neighbor not in visited:
                        visited.add(neighbor)
                        next_level.add(neighbor)
            current_level = next_level

        sub = self.g.induced_subgraph(list(visited))

        edges_to_delete = []
        for i, edge in enumerate(sub.es):
            if not self._in_window(edge['epoch_time'], start_time, end_time):
                edges_to_delete.append(i)
        sub.delete_edges(edges_to_delete)

        # Filter Event vertices that fall outside time window
        nodes_to_delete = []
        for i, v in enumerate(sub.vs):
            if v['node_type'] == 'Event':
                ep = v.attributes().get('epoch_time')
                if ep is not None and not self._in_window(ep, start_time, end_time):
                    nodes_to_delete.append(i)
        if nodes_to_delete:
            sub.delete_vertices(nodes_to_delete)

        return sub

    def get_2hop_neighborhood(self, entity_id: str, start_time: float = None, end_time: float = None) -> Dict:
        """Formal structured return for <= 2 hops."""
        sub = self.get_subgraph(entity_id, hops=2, start_time=start_time, end_time=end_time)

        nodes, rels, events = [], [], []
        for v in sub.vs:
            n_dict = {k: v[k] for k in v.attributes()}
            nodes.append(n_dict)
            if v['node_type'] == 'Event':
                events.append(n_dict)

        for e in sub.es:
            rels.append({
                'source': sub.vs[e.source]['name'],
                'target': sub.vs[e.target]['name'],
                'relationship_type': e['relationship_type'],
                'status': e['status'],
                'timestamp': e['timestamp'],
                'evidence_refs': e['evidence_refs']
            })

        return {
            'nodes': nodes,
            'relationships': rels,
            'events': events
        }

    def get_temporal_path(self, start_entity: str, end_entity: str, start_time: float = None, end_time: float = None) -> List[str]:
        """Monotonic temporal path finding."""
        if start_entity not in self.node_mapping or end_entity not in self.node_mapping:
            return []

        start_v = self.node_mapping[start_entity]
        end_v = self.node_mapping[end_entity]

        queue = [(start_v, [self.g.vs[start_v]['name']], 0.0)]
        visited = set()

        while queue:
            curr_v, path, last_time = queue.pop(0)

            if curr_v == end_v and len(path) > 1:
                return path

            if len(path) > 12:
                continue

            for e_idx in self.g.incident(curr_v, mode="all"):
                edge = self.g.es[e_idx]
                next_v = edge.target if edge.source == curr_v else edge.source

                next_name = self.g.vs[next_v]['name']
                if next_name in path:
                    continue

                edge_time = edge['epoch_time']

                if not self._in_window(edge_time, start_time, end_time):
                    continue

                if last_time > 0.0 and edge_time < last_time:
                    continue

                state = (next_v, edge_time)
                if state not in visited:
                    visited.add(state)
                    queue.append((next_v, path + [next_name], edge_time))

        return []
