# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: M12 Evidence & Provenance Engine (Immutable Lineage, Tamper-Evident Graphs, Audit APIs)

import copy
import hashlib
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Set, Tuple, Union

from dfap.schemas import TemporalSemantics
from dfap.provenance import compute_canonical_row_hash

logger = logging.getLogger(__name__)

M12_SCHEMA_VERSION = "v12.0.0_PRODUCTION_AUDIT"


class EvidenceType:
    SOURCE_RECORD = "SOURCE_RECORD"
    CANONICAL_EVENT = "CANONICAL_EVENT"
    RESOLVED_ENTITY = "RESOLVED_ENTITY"
    FEATURE_RECORD = "FEATURE_RECORD"
    ANOMALY_FINDING = "ANOMALY_FINDING"
    FUSED_FINDING = "FUSED_FINDING"
    INVESTIGATION_CLAIM = "INVESTIGATION_CLAIM"


class EvidenceStatus:
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    TAMPERED = "TAMPERED"
    REVOKED = "REVOKED"


class ProvenanceIntegrityStatus:
    INTEGRITY_VERIFIED = "INTEGRITY_VERIFIED"
    TAMPERED_RECORD_DETECTED = "TAMPERED_RECORD_DETECTED"
    BROKEN_PROVENANCE_CHAIN = "BROKEN_PROVENANCE_CHAIN"
    MISSING_PARENT_EVIDENCE = "MISSING_PARENT_EVIDENCE"
    ENTITY_MISMATCH = "ENTITY_MISMATCH"


def compute_deterministic_evidence_hash(payload: Dict[str, Any]) -> str:
    """
    Computes a deterministic SHA-256 evidence hash committing to the entire evidence record payload.
    Excludes volatile fields such as the evidence_hash itself.
    """
    clean_payload = {}
    for k in sorted(payload.keys()):
        if k in ["evidence_hash", "status_detail"]:
            continue
        v = payload[k]
        if isinstance(v, (list, tuple)):
            clean_payload[k] = list(v)
        elif isinstance(v, dict):
            clean_payload[k] = {dk: str(dv) for dk, dv in sorted(v.items())}
        elif v is None:
            clean_payload[k] = None
        else:
            clean_payload[k] = str(v)

    serialized = json.dumps(
        clean_payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


class CanonicalEvidenceRecord:
    """
    Canonical Immutable Evidence Record for M12.
    Represents an atomic, auditable item of evidence in the DFAP investigation lifecycle.
    """

    def __init__(
        self,
        evidence_type: str,
        source_domain: str,
        source_id: str,
        source_file: str,
        source_row_index: int,
        canonical_entity_ids: List[str],
        event_ids: List[str],
        observation_timestamp: Optional[Union[str, float]],
        ingestion_timestamp: str,
        derivation_method: str,
        derivation_version: str = M12_SCHEMA_VERSION,
        confidence: float = 1.0,
        evidence_quality: float = 1.0,
        temporal_semantics: str = "OBSERVED_TIMESTAMP",
        parent_evidence_ids: Optional[List[str]] = None,
        evidence_category: str = "SUPPORTING",  # SUPPORTING, CONTRADICTING, CONTEXTUAL
        metadata: Optional[Dict[str, Any]] = None,
        evidence_id: Optional[str] = None,
        evidence_hash: Optional[str] = None,
        created_at: Optional[str] = None,
        status: str = EvidenceStatus.ACTIVE
    ):
        self.evidence_type = evidence_type
        self.source_domain = source_domain.upper()
        self.source_id = str(source_id)
        self.source_file = str(source_file)
        self.source_row_index = int(source_row_index)
        self.canonical_entity_ids = sorted(list(set(canonical_entity_ids)))
        self.event_ids = sorted(list(set(event_ids)))
        self.observation_timestamp = observation_timestamp
        self.ingestion_timestamp = ingestion_timestamp
        self.derivation_method = derivation_method
        self.derivation_version = derivation_version
        self.confidence = float(np.clip(confidence, 0.0, 1.0)) if "np" in globals() else float(confidence)
        self.evidence_quality = float(evidence_quality)
        self.temporal_semantics = temporal_semantics
        self.parent_evidence_ids = sorted(list(set(parent_evidence_ids or [])))
        self.evidence_category = evidence_category.upper()
        self.metadata = metadata or {}
        self.status = status
        self.created_at = created_at or datetime.now(timezone.utc).isoformat()

        # Compute deterministic evidence_hash
        payload_for_hash = self._get_hash_payload()
        computed_hash = compute_deterministic_evidence_hash(payload_for_hash)
        self.evidence_hash = evidence_hash or computed_hash

        # Unique immutable evidence_id
        type_prefix = self.evidence_type[:3]
        self.evidence_id = evidence_id or f"EVD-{type_prefix}-{self.evidence_hash[:12]}"
        self.provenance_ref = f"ref:evd:{self.evidence_id}"

    def _get_hash_payload(self) -> Dict[str, Any]:
        return {
            "evidence_type": self.evidence_type,
            "source_domain": self.source_domain,
            "source_id": self.source_id,
            "source_file": self.source_file,
            "source_row_index": self.source_row_index,
            "canonical_entity_ids": self.canonical_entity_ids,
            "event_ids": self.event_ids,
            "observation_timestamp": self.observation_timestamp,
            "ingestion_timestamp": self.ingestion_timestamp,
            "derivation_method": self.derivation_method,
            "derivation_version": self.derivation_version,
            "confidence": round(self.confidence, 4),
            "evidence_quality": round(self.evidence_quality, 4),
            "temporal_semantics": self.temporal_semantics,
            "parent_evidence_ids": self.parent_evidence_ids,
            "evidence_category": self.evidence_category,
            "metadata": self.metadata
        }

    def verify_self_hash(self) -> bool:
        """Verifies that the evidence_hash matches the payload."""
        expected = compute_deterministic_evidence_hash(self._get_hash_payload())
        return self.evidence_hash == expected

    def to_dict(self) -> Dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "provenance_ref": self.provenance_ref,
            "evidence_type": self.evidence_type,
            "source_domain": self.source_domain,
            "source_id": self.source_id,
            "source_file": self.source_file,
            "source_row_index": self.source_row_index,
            "canonical_entity_ids": self.canonical_entity_ids,
            "event_ids": self.event_ids,
            "observation_timestamp": self.observation_timestamp,
            "ingestion_timestamp": self.ingestion_timestamp,
            "evidence_hash": self.evidence_hash,
            "derivation_method": self.derivation_method,
            "derivation_version": self.derivation_version,
            "confidence": self.confidence,
            "evidence_quality": self.evidence_quality,
            "temporal_semantics": self.temporal_semantics,
            "parent_evidence_ids": self.parent_evidence_ids,
            "evidence_category": self.evidence_category,
            "status": self.status,
            "created_at": self.created_at,
            "metadata": self.metadata
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CanonicalEvidenceRecord":
        return cls(
            evidence_id=data.get("evidence_id"),
            evidence_type=data["evidence_type"],
            source_domain=data["source_domain"],
            source_id=data["source_id"],
            source_file=data["source_file"],
            source_row_index=data["source_row_index"],
            canonical_entity_ids=data.get("canonical_entity_ids", []),
            event_ids=data.get("event_ids", []),
            observation_timestamp=data.get("observation_timestamp"),
            ingestion_timestamp=data.get("ingestion_timestamp", ""),
            derivation_method=data.get("derivation_method", "DIRECT"),
            derivation_version=data.get("derivation_version", M12_SCHEMA_VERSION),
            confidence=data.get("confidence", 1.0),
            evidence_quality=data.get("evidence_quality", 1.0),
            temporal_semantics=data.get("temporal_semantics", "OBSERVED_TIMESTAMP"),
            parent_evidence_ids=data.get("parent_evidence_ids", []),
            evidence_category=data.get("evidence_category", "SUPPORTING"),
            metadata=data.get("metadata", {}),
            evidence_hash=data.get("evidence_hash"),
            created_at=data.get("created_at"),
            status=data.get("status", EvidenceStatus.ACTIVE)
        )


class ProvenanceGraph:
    """
    Multi-stage Directed Acyclic Lineage Graph (DAG) for M12.
    Models the lineage sequence:
      SOURCE_FILE -> RAW_RECORD -> CANONICAL_EVENT -> RESOLVED_ENTITY -> FEATURE -> FINDING -> FUSED_FINDING -> CLAIM
    Enforces strict cycle detection (rejects self-loops, 2-node, and n-node cycles).
    """

    def __init__(self):
        self.nodes: Dict[str, Dict[str, Any]] = {}
        self.edges: List[Dict[str, Any]] = []
        self._adjacency_out: Dict[str, List[str]] = {}
        self._adjacency_in: Dict[str, List[str]] = {}

    def add_node(self, node_id: str, node_type: str, domain: str, metadata: Dict[str, Any]):
        if node_id not in self.nodes:
            self.nodes[node_id] = {
                "node_id": node_id,
                "node_type": node_type,
                "domain": domain,
                "metadata": metadata
            }
            self._adjacency_out[node_id] = []
            self._adjacency_in[node_id] = []
        else:
            # Update metadata if needed
            self.nodes[node_id]["metadata"].update(metadata)

    def add_edge(self, parent_id: str, child_id: str, relation: str, method: str):
        if parent_id not in self.nodes or child_id not in self.nodes:
            raise ValueError(f"Cannot add edge between missing nodes: {parent_id} -> {child_id}")

        # Cycle Detection: Reject direct self-cycle (P1)
        if parent_id == child_id:
            raise ValueError(f"Cycle detected: direct self-loop on node '{parent_id}' is strictly forbidden in a DAG.")

        # Cycle Detection: Check if parent_id is reachable from child_id (P2, P3)
        visited = set()
        queue = [child_id]
        while queue:
            curr = queue.pop(0)
            if curr == parent_id:
                raise ValueError(
                    f"Cycle detected: adding edge '{parent_id}' -> '{child_id}' would create a directed cycle in the lineage DAG."
                )
            if curr not in visited:
                visited.add(curr)
                queue.extend(self._adjacency_out.get(curr, []))

        # Check duplicate edge
        for e in self.edges:
            if e["parent_id"] == parent_id and e["child_id"] == child_id:
                return

        edge = {
            "parent_id": parent_id,
            "child_id": child_id,
            "relation": relation,
            "method": method
        }
        self.edges.append(edge)
        self._adjacency_out[parent_id].append(child_id)
        self._adjacency_in[child_id].append(parent_id)

    def get_upstream_path(self, node_id: str) -> List[Dict[str, Any]]:
        """Returns topological upstream ancestry of node_id."""
        ancestors = []
        visited = set()
        queue = list(self._adjacency_in.get(node_id, []))

        while queue:
            curr = queue.pop(0)
            if curr in visited:
                continue
            visited.add(curr)
            if curr in self.nodes:
                ancestors.append(self.nodes[curr])
            queue.extend(self._adjacency_in.get(curr, []))

        return ancestors

    def get_downstream_path(self, node_id: str) -> List[Dict[str, Any]]:
        """Returns all downstream derivations originating from node_id."""
        descendants = []
        visited = set()
        queue = list(self._adjacency_out.get(node_id, []))

        while queue:
            curr = queue.pop(0)
            if curr in visited:
                continue
            visited.add(curr)
            if curr in self.nodes:
                descendants.append(self.nodes[curr])
            queue.extend(self._adjacency_out.get(curr, []))

        return descendants

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_count": len(self.nodes),
            "edge_count": len(self.edges),
            "nodes": self.nodes,
            "edges": self.edges
        }


class EvidenceProvenanceEngine:
    """
    M12 Evidence & Provenance Engine.
    Provides production-grade registration, lineage tracking, recursive integrity verification,
    and investigation-facing APIs.
    """

    def __init__(self):
        self.evidence_store: Dict[str, CanonicalEvidenceRecord] = {}
        self.finding_evidence_map: Dict[str, List[str]] = {}  # finding_id -> [evidence_ids]
        self.graph = ProvenanceGraph()

    def register_evidence(self, record: CanonicalEvidenceRecord) -> CanonicalEvidenceRecord:
        """Registers a canonical evidence record into immutable store."""
        # Fail closed on hash invalidity
        if not record.verify_self_hash():
            raise ValueError(f"Integrity Error: evidence_hash {record.evidence_hash} does not match record payload!")

        # Duplicate check: deterministic idempotency
        if record.evidence_id in self.evidence_store:
            existing = self.evidence_store[record.evidence_id]
            if existing.evidence_hash != record.evidence_hash:
                raise ValueError(f"Integrity Collision: record {record.evidence_id} already registered with different hash!")
            return copy.deepcopy(existing)

        # Verify parent references exist if declared
        for p_id in record.parent_evidence_ids:
            if p_id not in self.evidence_store:
                raise ValueError(f"Broken Lineage: parent evidence {p_id} is not registered in store!")

        # Defensive copy into store
        stored_record = copy.deepcopy(record)
        self.evidence_store[record.evidence_id] = stored_record

        # Register in lineage graph
        self.graph.add_node(
            node_id=record.evidence_id,
            node_type=record.evidence_type,
            domain=record.source_domain,
            metadata={
                "source_file": record.source_file,
                "source_row": record.source_row_index,
                "evidence_hash": record.evidence_hash,
                "entities": record.canonical_entity_ids,
                "events": record.event_ids,
                "temporal_semantics": record.temporal_semantics,
                "evidence_category": record.evidence_category
            }
        )

        # Add graph edges from parents (with cycle rejection)
        for p_id in record.parent_evidence_ids:
            self.graph.add_edge(
                parent_id=p_id,
                child_id=record.evidence_id,
                relation="DERIVED_FROM",
                method=record.derivation_method
            )

        return copy.deepcopy(stored_record)

    def bind_finding_to_evidence(
        self,
        finding_id: str,
        canonical_entity_id: str,
        evidence_ids: List[str],
        expected_event_ids: Optional[List[str]] = None,
        finding_type: str = EvidenceType.ANOMALY_FINDING,
        parent_finding_ids: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """
        Binds an investigative finding to its exact supporting/contradicting evidence.
        Fails closed if any evidence reference is missing, belongs to a foreign entity,
        or fails event correspondence.
        Creates an explicit finding node in the provenance graph with evidence->finding edges.
        """
        if not evidence_ids:
            raise ValueError(f"Lineage Violation: finding {finding_id} cannot exist without evidence references!")

        for ev_id in evidence_ids:
            if ev_id not in self.evidence_store:
                raise ValueError(f"Missing Provenance: evidence {ev_id} cannot be resolved in evidence store!")
            ev = self.evidence_store[ev_id]

            # 1. Semantic Entity Validation (P17)
            if canonical_entity_id not in ev.canonical_entity_ids:
                raise ValueError(
                    f"Entity Mismatch: evidence {ev_id} binds to {ev.canonical_entity_ids}, not requested {canonical_entity_id}!"
                )

            # 2. Semantic Event Validation (P16)
            if expected_event_ids is not None:
                if not set(expected_event_ids).intersection(set(ev.event_ids)):
                    raise ValueError(
                        f"Event Mismatch: evidence {ev_id} events {ev.event_ids} do not match expected finding events {expected_event_ids}!"
                    )

        self.finding_evidence_map[finding_id] = sorted(list(set(evidence_ids)))

        # Register Finding as an explicit node in the Lineage Graph (P9, P13)
        domains = list(set(self.evidence_store[eid].source_domain for eid in evidence_ids))
        f_domain = domains[0] if len(domains) == 1 else "CROSS_DOMAIN"
        meta = metadata or {}
        meta.update({
            "canonical_entity_id": canonical_entity_id,
            "evidence_count": len(evidence_ids),
            "expected_events": expected_event_ids or []
        })

        self.graph.add_node(
            node_id=finding_id,
            node_type=finding_type,
            domain=f_domain,
            metadata=meta
        )

        # Create evidence -> finding edges (P10)
        for ev_id in evidence_ids:
            self.graph.add_edge(
                parent_id=ev_id,
                child_id=finding_id,
                relation="SUPPORTS_FINDING",
                method="EVIDENCE_CORROBORATION"
            )

        # Create finding -> fused finding edges if parent findings exist
        if parent_finding_ids:
            for pf_id in parent_finding_ids:
                if pf_id in self.graph.nodes:
                    self.graph.add_edge(
                        parent_id=pf_id,
                        child_id=finding_id,
                        relation="DERIVED_FINDING",
                        method="CROSS_DOMAIN_FUSION"
                    )

    def register_investigation_claim(
        self,
        claim_id: str,
        canonical_entity_id: str,
        parent_finding_ids: List[str],
        metadata: Optional[Dict[str, Any]] = None
    ):
        """Registers a terminal Investigation Claim node in the provenance graph (P14)."""
        if not parent_finding_ids:
            raise ValueError("Lineage Violation: Investigation claim must reference at least one supporting finding!")

        for fid in parent_finding_ids:
            if fid not in self.graph.nodes:
                raise ValueError(f"Missing finding: finding {fid} not found in provenance graph!")

        meta = metadata or {}
        meta["canonical_entity_id"] = canonical_entity_id

        self.graph.add_node(
            node_id=claim_id,
            node_type=EvidenceType.INVESTIGATION_CLAIM,
            domain="CROSS_DOMAIN",
            metadata=meta
        )

        for fid in parent_finding_ids:
            self.graph.add_edge(
                parent_id=fid,
                child_id=claim_id,
                relation="SUPPORTS_CLAIM",
                method="FORENSIC_DOSSIER_ASSERTION"
            )

    def get_evidence(self, evidence_id: str) -> Optional[CanonicalEvidenceRecord]:
        """
        API: Retrieves an evidence record by ID, provenance ref, hash prefix, or associated event ID.
        Returns a defensive deep copy to ensure in-memory API safety (P19).
        """
        if not evidence_id:
            return None

        # 1. Exact key match
        rec = self.evidence_store.get(evidence_id)
        if rec is not None:
            return copy.deepcopy(rec)

        # 2. Match ref:evd:<id>
        if evidence_id.startswith("ref:evd:"):
            clean_id = evidence_id[len("ref:evd:"):]
            rec = self.evidence_store.get(clean_id)
            if rec is not None:
                return copy.deepcopy(rec)

        # 3. Match by hash or hash prefix (e.g. hash:56d9c6c7c95955bd)
        clean_hash = evidence_id[5:] if evidence_id.startswith("hash:") else evidence_id
        if len(clean_hash) >= 8:
            for r in self.evidence_store.values():
                meta_hash = (r.metadata.get("sha256_hash") or "") if isinstance(r.metadata, dict) else ""
                ev_hash = getattr(r, "evidence_hash", "") or ""
                if (meta_hash and (meta_hash.startswith(clean_hash) or clean_hash.startswith(meta_hash))) or \
                   (ev_hash and (ev_hash.startswith(clean_hash) or clean_hash.startswith(ev_hash))):
                    return copy.deepcopy(r)

        # 4. Match by event_ids or source_id
        for r in self.evidence_store.values():
            if evidence_id in r.event_ids or evidence_id == r.source_id:
                return copy.deepcopy(r)

        return None

    def get_finding_provenance(self, finding_id: str) -> Dict[str, Any]:
        """API: Retrieves complete supporting evidence and lineage metadata for a finding."""
        if finding_id not in self.finding_evidence_map:
            raise KeyError(f"Finding {finding_id} has no registered provenance mapping.")

        ev_ids = self.finding_evidence_map[finding_id]
        evidence_items = [self.evidence_store[e_id].to_dict() for e_id in ev_ids]

        supporting = [e for e in evidence_items if e["evidence_category"] == "SUPPORTING"]
        contradicting = [e for e in evidence_items if e["evidence_category"] == "CONTRADICTING"]
        contextual = [e for e in evidence_items if e["evidence_category"] == "CONTEXTUAL"]

        return {
            "finding_id": finding_id,
            "evidence_count": len(evidence_items),
            "evidence_ids": ev_ids,
            "supporting_evidence": supporting,
            "contradicting_evidence": contradicting,
            "contextual_evidence": contextual,
            "all_evidence": evidence_items
        }

    def get_upstream_lineage(self, finding_id: str) -> List[Dict[str, Any]]:
        """
        API: Traverses the lineage graph upstream starting directly from the finding node (P11).
        """
        if finding_id not in self.graph.nodes:
            raise KeyError(f"Finding {finding_id} not registered in provenance graph.")

        return self.graph.get_upstream_path(finding_id)

    def get_downstream_derivations(self, evidence_id: str) -> List[Dict[str, Any]]:
        """
        API: Traverses the lineage graph downstream to all derived findings and claims (P12).
        """
        if evidence_id not in self.graph.nodes:
            raise KeyError(f"Evidence {evidence_id} not found in lineage graph.")

        return self.graph.get_downstream_path(evidence_id)

    def verify_integrity(self, record_or_id: Union[str, CanonicalEvidenceRecord]) -> Dict[str, Any]:
        """
        API: Truly recursive SHA-256 hash and lineage chain verification (P5, P6, P7, P8).
        Traverses complete ancestor tree: record -> parent -> grandparent -> ... -> root.
        Fails if any ancestor is missing or failed verification.
        """
        if isinstance(record_or_id, str):
            if record_or_id not in self.evidence_store:
                return {
                    "evidence_id": record_or_id,
                    "status": ProvenanceIntegrityStatus.MISSING_PARENT_EVIDENCE,
                    "is_valid": False,
                    "broken_ancestor_id": record_or_id,
                    "broken_reason": f"Evidence ID '{record_or_id}' is not registered in store",
                    "reason": f"Evidence ID '{record_or_id}' is not registered in store"
                }
            record = self.evidence_store[record_or_id]
        else:
            record = record_or_id

        # 1. Verify self hash
        if not record.verify_self_hash():
            return {
                "evidence_id": record.evidence_id,
                "status": ProvenanceIntegrityStatus.TAMPERED_RECORD_DETECTED,
                "is_valid": False,
                "broken_ancestor_id": record.evidence_id,
                "broken_reason": f"Self evidence_hash ({record.evidence_hash}) does not match computed payload hash",
                "reason": f"Self evidence_hash ({record.evidence_hash}) does not match computed payload hash"
            }

        # 2. Complete Recursive Ancestor Traversal (P5, P6, P7, P8)
        visited = set([record.evidence_id])
        queue = list(record.parent_evidence_ids)

        while queue:
            ancestor_id = queue.pop(0)
            if ancestor_id in visited:
                continue
            visited.add(ancestor_id)

            if ancestor_id not in self.evidence_store:
                return {
                    "evidence_id": record.evidence_id,
                    "status": ProvenanceIntegrityStatus.MISSING_PARENT_EVIDENCE,
                    "is_valid": False,
                    "broken_ancestor_id": ancestor_id,
                    "broken_reason": f"Ancestor evidence '{ancestor_id}' is missing from store",
                    "reason": f"Ancestor evidence '{ancestor_id}' is missing from store"
                }

            anc_rec = self.evidence_store[ancestor_id]
            if not anc_rec.verify_self_hash():
                return {
                    "evidence_id": record.evidence_id,
                    "status": ProvenanceIntegrityStatus.BROKEN_PROVENANCE_CHAIN,
                    "is_valid": False,
                    "broken_ancestor_id": ancestor_id,
                    "broken_reason": f"Ancestor evidence '{ancestor_id}' failed SHA-256 integrity verification",
                    "reason": f"Ancestor evidence '{ancestor_id}' failed SHA-256 integrity verification"
                }

            for gp_id in anc_rec.parent_evidence_ids:
                if gp_id not in visited:
                    queue.append(gp_id)

        return {
            "evidence_id": record.evidence_id,
            "status": ProvenanceIntegrityStatus.INTEGRITY_VERIFIED,
            "is_valid": True,
            "broken_ancestor_id": None,
            "broken_reason": None,
            "ancestors_verified_count": len(visited) - 1,
            "reason": "Cryptographic SHA-256 hash and complete recursive parent lineage verified"
        }

    def verify_finding_integrity(self, finding_id: str) -> Dict[str, Any]:
        """
        API: Verifies that all evidence items bound to a finding or claim, as well as all their
        recursive ancestor chains, have valid SHA-256 integrity and unbroken lineage.
        """
        if finding_id not in self.finding_evidence_map:
            if finding_id not in self.graph.nodes:
                return {
                    "finding_id": finding_id,
                    "status": ProvenanceIntegrityStatus.MISSING_PARENT_EVIDENCE,
                    "is_valid": False,
                    "broken_ancestor_id": finding_id,
                    "broken_reason": f"Finding or claim '{finding_id}' not found in graph.",
                    "reason": f"Finding or claim '{finding_id}' not found in graph."
                }
            ancestor_nodes = self.graph.get_upstream_path(finding_id)
            ev_ids = [n["node_id"] for n in ancestor_nodes if n["node_id"] in self.evidence_store]
        else:
            ev_ids = self.finding_evidence_map[finding_id]

        if not ev_ids:
            return {
                "finding_id": finding_id,
                "status": ProvenanceIntegrityStatus.MISSING_PARENT_EVIDENCE,
                "is_valid": False,
                "broken_ancestor_id": finding_id,
                "broken_reason": "Finding has no associated evidence records.",
                "reason": "Finding has no associated evidence records."
            }

        for eid in ev_ids:
            ev_res = self.verify_integrity(eid)
            if not ev_res["is_valid"]:
                return {
                    "finding_id": finding_id,
                    "status": ev_res["status"],
                    "is_valid": False,
                    "broken_ancestor_id": ev_res.get("broken_ancestor_id"),
                    "broken_reason": ev_res.get("broken_reason"),
                    "reason": f"Evidence {eid} failed integrity: {ev_res.get('reason')}"
                }

        return {
            "finding_id": finding_id,
            "status": ProvenanceIntegrityStatus.INTEGRITY_VERIFIED,
            "is_valid": True,
            "broken_ancestor_id": None,
            "broken_reason": None,
            "reason": "All supporting evidence and recursive ancestor lineage verified."
        }

    def explain_finding(self, finding_id: str) -> str:
        """
        API: Answers the investigator's question:
        'Why was this entity/finding flagged?' with exact evidence and lineage chain.
        """
        prov = self.get_finding_provenance(finding_id)
        ev_items = prov["all_evidence"]

        lines = [
            f"FINDING AUDIT: {finding_id}",
            f"TOTAL EVIDENCE ITEMS: {prov['evidence_count']}",
            f"SUPPORTING ITEMS: {len(prov['supporting_evidence'])}",
            f"CONTRADICTING ITEMS: {len(prov['contradicting_evidence'])}",
            "EVIDENCE LINEAGE CHAIN:"
        ]

        for i, ev in enumerate(ev_items, 1):
            lines.append(
                f"  [{i}] Type={ev['evidence_type']} | Domain={ev['source_domain']} | "
                f"SourceFile={os.path.basename(ev['source_file'])}:L{ev['source_row_index']} | "
                f"Quality={ev['evidence_quality']} | TemporalSemantics={ev['temporal_semantics']} | "
                f"Hash={ev['evidence_hash'][:12]}... | Ref={ev['provenance_ref']}"
            )

        return "\n".join(lines)

    def export_provenance(
        self,
        finding_id_or_evidence_id: str,
        export_format: str = "json"
    ) -> Any:
        """
        API: Exports provenance in json, dot, or dict format.
        """
        if finding_id_or_evidence_id in self.finding_evidence_map:
            payload = self.get_finding_provenance(finding_id_or_evidence_id)
        elif finding_id_or_evidence_id in self.evidence_store:
            payload = self.evidence_store[finding_id_or_evidence_id].to_dict()
        else:
            raise KeyError(f"Identifier {finding_id_or_evidence_id} not found in findings or evidence store.")

        if export_format == "dict":
            return payload
        elif export_format == "json":
            return json.dumps(payload, indent=2, sort_keys=True)
        elif export_format == "dot":
            # Generate Graphviz DOT representation
            dot_lines = ["digraph ProvenanceGraph {", "  rankdir=LR;"]
            for n_id, n in self.graph.nodes.items():
                dot_lines.append(f'  "{n_id}" [label="{n["node_type"]}\\n{n["domain"]}"];')
            for e in self.graph.edges:
                dot_lines.append(f'  "{e["parent_id"]}" -> "{e["child_id"]}" [label="{e["relation"]}"];')
            dot_lines.append("}")
            return "\n".join(dot_lines)
        else:
            raise ValueError(f"Unsupported export format: {export_format}")
