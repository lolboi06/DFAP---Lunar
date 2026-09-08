# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: M13 Investigation Workspace Backend (Case State Machine, Audit Log, Multi-Domain Orchestration)

import copy
import hashlib
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Set, Tuple, Union
import pandas as pd

from dfap.investigation.temporal_engine import TemporalEventEngine, load_identity_bridge_readonly
from dfap.investigation.cross_domain_fusion import CrossDomainFusionEngine
from dfap.investigation.evidence_provenance import (
    EvidenceProvenanceEngine,
    CanonicalEvidenceRecord,
    EvidenceType,
    EvidenceStatus,
    ProvenanceIntegrityStatus
)
from dfap.investigation.graph_traversal import InvestigationGraphTraversal
from dfap.investigation.temporal_sequence import (
    TemporalSequenceEngine,
    TemporalSequence,
    TemporalSequenceItem,
    TemporalWindowType,
    OrderingBasis,
    TemporalSequenceFeatures,
    TemporalTransition,
    MotifMatch,
    SequencePhase,
)

logger = logging.getLogger(__name__)

M13_WORKSPACE_SCHEMA_VERSION = "v13.0.0_PRODUCTION_WORKSPACE"


class CaseStatus:
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"
    ALL = {OPEN, UNDER_REVIEW, ESCALATED, RESOLVED, CLOSED}


class MatchStatus:
    CONFIRMED = "CONFIRMED"
    POSSIBLE = "POSSIBLE"
    REJECTED = "REJECTED"
    UNRESOLVED = "UNRESOLVED"


class InvestigationCase:
    """
    Canonical Investigation Case Model for M13.
    Preserves complete decision history, status transitions, and audit references.
    """

    def __init__(
        self,
        case_id: str,
        canonical_entity_id: str,
        status: str = CaseStatus.OPEN,
        created_at: Optional[str] = None,
        updated_at: Optional[str] = None,
        created_by: str = "INVESTIGATOR_CONSOLE",
        search_context: Optional[Dict[str, Any]] = None,
        finding_ids: Optional[List[str]] = None,
        evidence_ids: Optional[List[str]] = None,
        notes: Optional[List[Dict[str, Any]]] = None,
        decision_history: Optional[List[Dict[str, Any]]] = None,
        status_history: Optional[List[Dict[str, Any]]] = None,
        timeline_context: Optional[Dict[str, Any]] = None,
        provenance_refs: Optional[List[str]] = None,
        audit_log: Optional[List[Dict[str, Any]]] = None,
        mapping_status: Optional[str] = None,
        case_kind: Optional[str] = None,
        schema_version: str = M13_WORKSPACE_SCHEMA_VERSION
    ):
        self.case_id = str(case_id)
        self.canonical_entity_id = str(canonical_entity_id)
        if status not in CaseStatus.ALL:
            raise ValueError(f"Invalid case status '{status}'. Must be one of: {sorted(list(CaseStatus.ALL))}")
        self.status = status
        now_ts = datetime.now(timezone.utc).isoformat()
        self.created_at = created_at or now_ts
        self.updated_at = updated_at or now_ts
        self.created_by = created_by
        self.search_context = search_context or {}
        self.mapping_status = mapping_status or self.search_context.get("mapping_status") or "NATIVE_CASE"
        self.case_kind = case_kind or self.search_context.get("case_kind") or ("CONTROLLED_CASE_MAPPING" if self.mapping_status == "CONTROLLED_CASE_MAPPING" else "NATIVE_CASE")
        self.finding_ids = sorted(list(set(finding_ids or [])))
        self.evidence_ids = sorted(list(set(evidence_ids or [])))
        self.notes = notes or []
        self.decision_history = decision_history or []
        self.status_history = status_history or []
        self.timeline_context = timeline_context or {}
        self.provenance_refs = sorted(list(set(provenance_refs or [])))
        self.audit_log = audit_log or []
        self.schema_version = schema_version

    def record_audit_event(self, action: str, obj: str, actor: str = "INVESTIGATOR_CONSOLE", metadata: Optional[Dict[str, Any]] = None):
        """Appends an immutable audit trail entry."""
        entry = {
            "event_id": f"AUDIT-{len(self.audit_log) + 1:04d}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "actor": actor,
            "action": action,
            "object": obj,
            "metadata": metadata or {}
        }
        self.audit_log.append(entry)
        self.updated_at = entry["timestamp"]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "case_id": self.case_id,
            "canonical_entity_id": self.canonical_entity_id,
            "status": self.status,
            "mapping_status": self.mapping_status,
            "case_kind": self.case_kind,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "created_by": self.created_by,
            "search_context": self.search_context,
            "finding_ids": self.finding_ids,
            "evidence_ids": self.evidence_ids,
            "notes": self.notes,
            "decision_history": self.decision_history,
            "status_history": self.status_history,
            "timeline_context": self.timeline_context,
            "provenance_refs": self.provenance_refs,
            "audit_log": self.audit_log,
            "schema_version": self.schema_version
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "InvestigationCase":
        return cls(
            case_id=data["case_id"],
            canonical_entity_id=data["canonical_entity_id"],
            status=data.get("status", CaseStatus.OPEN),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
            created_by=data.get("created_by", "INVESTIGATOR_CONSOLE"),
            search_context=data.get("search_context", {}),
            finding_ids=data.get("finding_ids", []),
            evidence_ids=data.get("evidence_ids", []),
            notes=data.get("notes", []),
            decision_history=data.get("decision_history", []),
            status_history=data.get("status_history", []),
            timeline_context=data.get("timeline_context", {}),
            provenance_refs=data.get("provenance_refs", []),
            audit_log=data.get("audit_log", []),
            mapping_status=data.get("mapping_status") or data.get("search_context", {}).get("mapping_status"),
            case_kind=data.get("case_kind") or data.get("search_context", {}).get("case_kind"),
            schema_version=data.get("schema_version", M13_WORKSPACE_SCHEMA_VERSION)
        )


class InvestigationWorkspaceBackend:
    """
    M13 Investigation Workspace Backend Engine.
    Orchestrates authoritative upstream modules (M1-M12) without fabricating identity,
    scores, evidence, or graph relations.
    """

    def __init__(
        self,
        output_dir: str = "output",
        canonical_dir: str = "data/canonical",
        cases_dir: str = "data/cases"
    ):
        self.output_dir = output_dir
        self.canonical_dir = canonical_dir
        self.cases_dir = cases_dir

        # In-memory case repository
        self.cases: Dict[str, InvestigationCase] = {}
        self._case_counter = 0
        self.live_stream_events: List[Dict[str, Any]] = []

        # Subsystems
        self.temporal_engine = TemporalEventEngine(canonical_dir=self.canonical_dir)
        self.fusion_engine = CrossDomainFusionEngine()
        self.evidence_engine = EvidenceProvenanceEngine()
        self.graph_traversal = InvestigationGraphTraversal()
        self.temporal_sequence_engine = TemporalSequenceEngine(workspace_backend=self)
        from dfap.investigation.temporal_motif_discovery import UnsupervisedMotifDiscoveryEngine
        self.temporal_motif_discovery_engine = UnsupervisedMotifDiscoveryEngine(sequence_engine=self.temporal_sequence_engine)
        from dfap.investigation.risk_scoring import RiskScoringEngine
        self.risk_engine = RiskScoringEngine(self)
        from dfap.investigation.explainability import M9ShapExplainer
        self.shap_explainer = M9ShapExplainer(self)
        from dfap.graph_ml.service import GraphMLService
        self.graph_ml_service = GraphMLService(self)
        from dfap.investigation.adaptive_baseline import AdaptiveBaselineManager
        self.adaptive_baseline_manager = AdaptiveBaselineManager()

        # Load Authoritative Registries
        self._load_authoritative_registries()

    @staticmethod
    def _is_authoritative_entity_token(value: Any) -> bool:
        """Accept only true case-scoped identifiers used in DFAP investigations: canonical entity IDs and live flow IDs."""
        if value is None:
            return False
        text = str(value).strip()
        if not text:
            return False
        # Canonical entity IDs and live flow IDs are the only investigation-case entities.
        # Raw bank account numbers, phone numbers, IP addresses, and social handles are not case-scoped entities.
        return bool(re.fullmatch(r"(?:ENT|FLOW)_[A-Za-z0-9]+", text))

    def _load_authoritative_registries(self):
        """Loads certified upstream registries and index maps."""
        # 1. Identity Bridge
        bridge_path = os.path.join(self.cases_dir, "identity_bridge.parquet")
        self.bridge_df = load_identity_bridge_readonly(bridge_path) if os.path.exists(bridge_path) else pd.DataFrame()

        # 2. Resolved Entities
        entities_path = os.path.join(self.output_dir, "resolved_entities.parquet")
        self.entities_df = pd.read_parquet(entities_path) if os.path.exists(entities_path) else pd.DataFrame()
        # 2b. Entity Matches audit artifact (pairwise decisions)
        matches_path = os.path.join(self.output_dir, "entity_matches.parquet")
        self.entity_matches_df = pd.read_parquet(matches_path) if os.path.exists(matches_path) else pd.DataFrame()

        # 3. Canonical Events
        events_path = os.path.join(self.output_dir, "canonical_events.parquet")
        self.events_df = pd.read_parquet(events_path) if os.path.exists(events_path) else pd.DataFrame()

        # 4. Upstream Findings
        findings_path = os.path.join(self.output_dir, "m3/findings/findings.parquet")
        if os.path.exists(findings_path):
            df_f = pd.read_parquet(findings_path)
            self.findings_by_id = {r["finding_id"]: r for r in df_f.to_dict(orient="records")}
        else:
            self.findings_by_id = {}

        # In-memory and fixture source dataset registry for data quality evaluation
        self.source_datasets: Dict[str, pd.DataFrame] = {}

        # Set of authoritative canonical entities. Keep this restricted to real entity tokens rather than
        # arbitrary raw identifiers such as phone numbers or social handles, which can otherwise pollute
        # the alternate-entity ordering used in integrity tests while still keeping valid flow IDs like
        # FLOW_133 accepted for live case creation.
        self.valid_entities: Set[str] = set()
        if not self.entities_df.empty and "canonical_entity_id" in self.entities_df.columns:
            self.valid_entities.update(
                str(v).strip() for v in self.entities_df["canonical_entity_id"].dropna().astype(str).unique()
                if self._is_authoritative_entity_token(v)
            )
        if not self.bridge_df.empty and "canonical_entity_id" in self.bridge_df.columns:
            self.valid_entities.update(
                str(v).strip() for v in self.bridge_df["canonical_entity_id"].dropna().astype(str).unique()
                if self._is_authoritative_entity_token(v)
            )
        if not self.events_df.empty:
            for key in ["actor_id", "target_id"]:
                if key in self.events_df.columns:
                    self.valid_entities.update(
                        str(v).strip() for v in self.events_df[key].dropna().astype(str).unique()
                        if self._is_authoritative_entity_token(v)
                    )

        if os.path.isdir(self.canonical_dir):
            for fname in os.listdir(self.canonical_dir):
                if not fname.endswith("_canonical.parquet"):
                    continue
                path = os.path.join(self.canonical_dir, fname)
                try:
                    df = pd.read_parquet(path)
                except Exception:
                    continue
                for key in ["actor_id", "target_id"]:
                    if key in df.columns:
                        self.valid_entities.update(
                            str(v).strip() for v in df[key].dropna().astype(str).unique()
                            if self._is_authoritative_entity_token(v)
                        )

        self._entity_alias_to_canonical: Dict[str, str] = {}
        if not self.entities_df.empty and "raw_identifier" in self.entities_df.columns:
            for _, r in self.entities_df.iterrows():
                raw_id = str(r.get("raw_identifier", "")).strip()
                canon = str(r.get("canonical_entity_id", "")).strip()
                if raw_id and canon:
                    self._entity_alias_to_canonical[raw_id] = canon
                    self._entity_alias_to_canonical[canon] = canon
        if not self.bridge_df.empty:
            for _, r in self.bridge_df.iterrows():
                raw_id = str(r.get("raw_identifier", "")).strip()
                canon = str(r.get("canonical_entity_id", "")).strip()
                if raw_id and canon:
                    self._entity_alias_to_canonical[raw_id] = canon
                    self._entity_alias_to_canonical[canon] = canon

        self._evidence_by_hash: Dict[str, str] = {}
        self._bootstrap_m12_evidence_store()

    def _resolve_entity_aliases(self, entity_id: str) -> Set[str]:
        """Returns all raw identifiers and canonical aliases linked to an entity for timeline resolution."""
        raw_aliases = {str(entity_id).strip()}
        canonical = self._entity_alias_to_canonical.get(str(entity_id).strip(), str(entity_id).strip())
        raw_aliases.add(canonical)
        for raw, canon in self._entity_alias_to_canonical.items():
            if canon == canonical or raw == canonical:
                raw_aliases.add(raw)
        if canonical in self._entity_alias_to_canonical:
            raw_aliases.add(canonical)
        return {a for a in raw_aliases if a}

    def _bootstrap_m12_evidence_store(self):
        """Creates authoritative M12 evidence records from canonical events and their provenance ledger."""
        if self.events_df.empty:
            return

        prov_path = os.path.join(self.output_dir, "provenance_ledger.parquet")
        prov_df = pd.read_parquet(prov_path) if os.path.exists(prov_path) else pd.DataFrame()
        prov_by_hash = {}
        if not prov_df.empty and "sha256_hash" in prov_df.columns:
            for _, row in prov_df.iterrows():
                prov_by_hash[str(row.get("sha256_hash", ""))] = row.to_dict()

        for _, row in self.events_df.iterrows():
            event_id = str(row.get("event_id", ""))
            event_hash = str(row.get("sha256_hash", ""))
            if not event_hash:
                continue
            event_aliases = set()
            for key in [row.get("actor_id"), row.get("target_id")]:
                key = str(key).strip() if key is not None else ""
                if key:
                    event_aliases.add(key)
                    event_aliases.add(self._entity_alias_to_canonical.get(key, key))
            canonical_members = sorted({self._entity_alias_to_canonical.get(alias, alias) for alias in event_aliases if alias})
            if not canonical_members:
                canonical_members = [str(row.get("actor_id", "")), str(row.get("target_id", ""))]

            prov_meta = prov_by_hash.get(event_hash, {})
            payload = {
                "evidence_type": "CANONICAL_EVENT",
                "source_domain": str(row.get("source_domain", "UNKNOWN")).upper(),
                "source_id": event_id,
                "source_file": str(prov_meta.get("source_file", "canonical_events.parquet")),
                "source_row_index": int(prov_meta.get("source_row_index", 0) if pd.notna(prov_meta.get("source_row_index", 0)) else 0),
                "canonical_entity_ids": canonical_members,
                "event_ids": [event_id],
                "observation_timestamp": row.get("timestamp"),
                "ingestion_timestamp": str(prov_meta.get("ingestion_timestamp", datetime.now(timezone.utc).isoformat())),
                "derivation_method": "CANONICAL_EVENT_HASH",
                "derivation_version": "M12.EVIDENCE.V1",
                "confidence": 1.0,
                "evidence_quality": 1.0,
                "temporal_semantics": str(row.get("temporal_semantics", "OBSERVED_TIMESTAMP")),
                "parent_evidence_ids": [],
                "evidence_category": "SUPPORTING",
                "metadata": {"event_type": str(row.get("event_type", "")), "sha256_hash": event_hash},
            }
            record = CanonicalEvidenceRecord(
                evidence_type="CANONICAL_EVENT",
                source_domain=str(row.get("source_domain", "UNKNOWN")).upper(),
                source_id=event_id,
                source_file=str(prov_meta.get("source_file", "canonical_events.parquet")),
                source_row_index=int(prov_meta.get("source_row_index", 0) if pd.notna(prov_meta.get("source_row_index", 0)) else 0),
                canonical_entity_ids=canonical_members,
                event_ids=[event_id],
                observation_timestamp=row.get("timestamp"),
                ingestion_timestamp=str(prov_meta.get("ingestion_timestamp", datetime.now(timezone.utc).isoformat())),
                derivation_method="CANONICAL_EVENT_HASH",
                derivation_version="M12.EVIDENCE.V1",
                confidence=1.0,
                evidence_quality=1.0,
                temporal_semantics=str(row.get("temporal_semantics", "OBSERVED_TIMESTAMP")),
                evidence_category="SUPPORTING",
                metadata={"event_type": str(row.get("event_type", "")), "sha256_hash": event_hash},
            )
            self.evidence_engine.register_evidence(record)
            self._evidence_by_hash[event_hash] = record.evidence_id

        for finding_id, finding in self.findings_by_id.items():
            entity_id = str(finding.get("entity_id", ""))
            evidence_refs = finding.get("evidence_refs", [])
            if isinstance(evidence_refs, str):
                try:
                    evidence_refs = json.loads(evidence_refs)
                except Exception:
                    evidence_refs = [evidence_refs]
            evidence_ids = []
            for ref in evidence_refs:
                if not ref:
                    continue
                resolved = self._evidence_by_hash.get(str(ref), None)
                if resolved:
                    evidence_ids.append(resolved)
            if evidence_ids:
                try:
                    self.evidence_engine.bind_finding_to_evidence(
                        finding_id,
                        canonical_entity_id=entity_id,
                        evidence_ids=evidence_ids,
                        expected_event_ids=[str(ev) for ev in json.loads(finding.get("event_ids", "[]")) if isinstance(ev, str)] if isinstance(finding.get("event_ids", ""), str) else [],
                        metadata={"source_domain": "CROSS_DOMAIN", "status": str(finding.get("status", "ACTIVE"))},
                    )
                except Exception:
                    pass

    # ── 1. SEARCH APIS ─────────────────────────────────────────────────────────

    def search(self, query_val: str, query_type: str = "general", max_results: int = 20) -> List[Dict[str, Any]]:
        """
        Executes typed search across authoritative M1/M2 registries.
        Never collapses CONFIRMED, POSSIBLE, REJECTED, UNRESOLVED into a single result type.
        Never treats string similarity as identity.
        """
        q_clean = query_val.strip().lower()
        if not q_clean:
            return []

        results = []
        q_type = query_type.lower().strip()

        # Check case search first if requested
        if q_type == "case":
            for cid, c in self.cases.items():
                if q_clean in cid.lower() or q_clean in c.canonical_entity_id.lower():
                    results.append({
                        "canonical_entity_id": c.canonical_entity_id,
                        "raw_identifier": cid,
                        "identifier_type": "CASE",
                        "match_confidence": 1.0,
                        "match_method": "CASE_EXACT_LOOKUP",
                        "match_status": MatchStatus.CONFIRMED,
                        "summary": f"Case {cid} (Entity: {c.canonical_entity_id} | Status: {c.status})"
                    })
            return results

        # 1. Search in Controlled Identity Bridge (Authoritative M11/M12 Bridge)
        if not self.bridge_df.empty:
            for _, r in self.bridge_df.iterrows():
                raw_id = str(r["raw_identifier"])
                canon_id = str(r["canonical_entity_id"])
                dom = str(r.get("domain", "UNKNOWN")).upper()
                id_type = "IP" if "IP" in raw_id or dom == "IPDR" else ("WALLET" if "WALLET" in raw_id or dom == "FINANCIAL" else "SOCIAL")

                # Filter by query_type if specified
                if q_type == "ip" and id_type != "IP":
                    continue
                if q_type == "wallet" and id_type != "WALLET":
                    continue

                if q_clean in raw_id.lower() or q_clean in canon_id.lower():
                    is_exact = (q_clean == raw_id.lower() or q_clean == canon_id.lower())
                    results.append({
                        "canonical_entity_id": canon_id,
                        "raw_identifier": raw_id,
                        "identifier_type": id_type,
                        "match_confidence": float(r.get("confidence", 0.95)) if is_exact else 0.70,
                        "match_method": str(r.get("mapping_method", "CONTROLLED_CASE_MAPPING")),
                        "match_status": MatchStatus.CONFIRMED if is_exact else MatchStatus.POSSIBLE,
                        "evidence_ref": str(r.get("evidence_ref", ""))
                    })

        # 2. Search in Resolved Entities (Authoritative M2 Entity Registry)
        if not self.entities_df.empty:
            for _, r in self.entities_df.iterrows():
                raw_id = str(r.get("raw_identifier", ""))
                canon_id = str(r.get("canonical_entity_id", ""))
                id_type = str(r.get("identifier_type", "ENTITY")).upper()

                if q_type in ("ip", "wallet", "account", "device", "phone") and q_type not in id_type.lower():
                    continue

                if q_clean in raw_id.lower() or q_clean in canon_id.lower():
                    # Deduplicate if already present
                    if any(x["canonical_entity_id"] == canon_id and x["raw_identifier"] == raw_id for x in results):
                        continue

                    is_exact = (q_clean == raw_id.lower() or q_clean == canon_id.lower())
                    conf = float(r.get("match_confidence", 1.0)) if is_exact else 0.65
                    status = str(r.get("match_status", MatchStatus.CONFIRMED))
                    if not is_exact and status == MatchStatus.CONFIRMED:
                        status = MatchStatus.POSSIBLE

                    results.append({
                        "canonical_entity_id": canon_id,
                        "raw_identifier": raw_id,
                        "identifier_type": id_type,
                        "match_confidence": round(conf, 4),
                        "match_method": str(r.get("match_method", "EXACT")),
                        "match_status": status,
                        "evidence_ref": str(r.get("evidence", ""))[:64]
                    })

        # Sort by confidence descending
        results.sort(key=lambda x: x["match_confidence"], reverse=True)
        return results[:max_results]

    # ── 2. CASE CREATION & WORKSPACE APIS ──────────────────────────────────────

    def register_controlled_case(self, case_data: Dict[str, Any]) -> InvestigationCase:
        """Registers a controlled cross-domain case in M13 without inventing a native dataset identity."""
        case_id = str(case_data["case_id"])
        canonical_entity_id = str(case_data["canonical_entity_id"])
        mapping_status = str(case_data.get("mapping_status", "CONTROLLED_CASE_MAPPING"))
        search_context = dict(case_data.get("search_context", {})) if isinstance(case_data.get("search_context"), dict) else {}
        search_context.setdefault("mapping_status", mapping_status)
        search_context.setdefault("case_kind", "CONTROLLED_CASE_MAPPING")
        search_context.setdefault("canonical_entity_id", canonical_entity_id)
        if "domain_evidence_breakdown" in case_data:
            search_context["domain_evidence_breakdown"] = case_data.get("domain_evidence_breakdown", {})
        if "cross_domain_timeline" in case_data:
            search_context["cross_domain_timeline"] = case_data.get("cross_domain_timeline", [])
        if "fused_composite_score" in case_data:
            search_context["fused_composite_score"] = case_data.get("fused_composite_score")
        if "threat_classification" in case_data:
            search_context["threat_classification"] = case_data.get("threat_classification")
        if "domains_analyzed" in case_data:
            search_context["domains_analyzed"] = case_data.get("domains_analyzed", [])
        bridge_rows = self.bridge_df[self.bridge_df["case_id"] == case_id].to_dict(orient="records") if not self.bridge_df.empty else []
        bridge_refs = [str(r.get("evidence_ref", "")) for r in bridge_rows if str(r.get("evidence_ref", "")).strip()]
        if bridge_refs:
            search_context["bridge_evidence_refs"] = bridge_refs
            search_context["mapping_provenance"] = bridge_rows
        # Optional: accept an explicit case-scoped identity candidate set produced by the entity resolver.
        # This allows synthetic or investigator-supplied cases to carry authoritative match IDs
        # without the copilot performing an unrestricted global lookup.
        if "identity_candidate_match_ids" in case_data:
            ids = case_data.get("identity_candidate_match_ids") or []
            if isinstance(ids, (list, tuple)) and ids:
                # store in search context for downstream retrieval by M14 copilot
                search_context["identity_candidate_match_ids"] = [str(i) for i in ids]
                # audit record for traceability
                search_context.setdefault("identity_candidate_set_source", "ENTITY_RESOLVER")
                search_context.setdefault("identity_candidate_set_count", len(ids))
                # add an audit entry via metadata
                # (case created later will carry this in its search_context and audit log)
        case = InvestigationCase(
            case_id=case_id,
            canonical_entity_id=canonical_entity_id,
            created_by="INVESTIGATOR_CONSOLE",
            search_context=search_context,
            mapping_status=mapping_status,
            case_kind="CONTROLLED_CASE_MAPPING",
            provenance_refs=bridge_refs,
        )
        case.record_audit_event("CONTROLLED_CASE_REGISTERED", case_id, actor="INVESTIGATOR_CONSOLE", metadata={"mapping_status": mapping_status, "canonical_entity_id": canonical_entity_id})
        self.cases[case_id] = case
        return copy.deepcopy(case)

    def create_case(
        self,
        canonical_entity_id: str,
        created_by: str = "INVESTIGATOR_CONSOLE",
        case_id: Optional[str] = None,
        search_context: Optional[Dict[str, Any]] = None
    ) -> InvestigationCase:
        """
        Creates an investigative case for an authoritative canonical entity.
        Fails closed if the canonical entity is unknown.
        """
        if canonical_entity_id not in self.valid_entities:
            raise ValueError(f"Fail Closed: Canonical entity '{canonical_entity_id}' is unknown in authoritative registries.")

        if not case_id:
            self._case_counter += 1
            case_id = f"CASE-{self._case_counter:03d}"

        if case_id in self.cases:
            raise ValueError(f"Case with ID '{case_id}' already exists.")

        case = InvestigationCase(
            case_id=case_id,
            canonical_entity_id=canonical_entity_id,
            status=CaseStatus.OPEN,
            created_by=created_by,
            search_context=search_context or {}
        )

        case.record_audit_event("CASE_CREATED", case_id, actor=created_by)
        case.record_audit_event("TARGET_SELECTED", canonical_entity_id, actor=created_by)

        self.cases[case_id] = case
        return copy.deepcopy(case)

    def get_case(self, case_id: str) -> InvestigationCase:
        """Retrieves a case by ID. Fails closed if not found."""
        if case_id not in self.cases:
            raise KeyError(f"Case '{case_id}' not found in workspace.")
        return copy.deepcopy(self.cases[case_id])

    def list_cases(self) -> List[Dict[str, Any]]:
        """Lists all active investigation cases."""
        return [c.to_dict() for c in self.cases.values()]

    def update_case_status(
        self,
        case_id: str,
        new_status: str,
        reason: str = "",
        actor: str = "INVESTIGATOR_CONSOLE"
    ) -> InvestigationCase:
        """
        Transitions case status preserving complete audit history.
        Fails closed on invalid status.
        """
        if case_id not in self.cases:
            raise KeyError(f"Case '{case_id}' not found in workspace.")
        if new_status not in CaseStatus.ALL:
            raise ValueError(f"Invalid status '{new_status}'. Allowed: {sorted(list(CaseStatus.ALL))}")

        case = self.cases[case_id]
        old_status = case.status
        now_ts = datetime.now(timezone.utc).isoformat()

        # Update status history
        transition = {
            "from_status": old_status,
            "to_status": new_status,
            "timestamp": now_ts,
            "actor": actor,
            "reason": reason
        }
        case.status_history.append(transition)
        case.status = new_status
        case.updated_at = now_ts

        case.record_audit_event(
            action="STATUS_CHANGED",
            obj=case_id,
            actor=actor,
            metadata={"from": old_status, "to": new_status, "reason": reason}
        )

        return copy.deepcopy(case)

    def add_case_note(
        self,
        case_id: str,
        note_text: str,
        author: str = "INVESTIGATOR_CONSOLE"
    ) -> InvestigationCase:
        """Appends an investigator note to the case dossier."""
        if case_id not in self.cases:
            raise KeyError(f"Case '{case_id}' not found in workspace.")
        if not note_text.strip():
            raise ValueError("Note text cannot be empty.")

        case = self.cases[case_id]
        now_ts = datetime.now(timezone.utc).isoformat()
        note = {
            "note_id": f"NOTE-{len(case.notes) + 1:03d}",
            "timestamp": now_ts,
            "author": author,
            "text": note_text.strip()
        }
        case.notes.append(note)
        case.record_audit_event("NOTE_ADDED", note["note_id"], actor=author, metadata={"text": note_text[:64]})
        return copy.deepcopy(case)

    def attach_finding(
        self,
        case_id: str,
        finding_id: str,
        actor: str = "INVESTIGATOR_CONSOLE"
    ) -> InvestigationCase:
        """
        Attaches a finding to an investigation case.
        Enforces entity alignment: foreign findings belonging to a different entity are REJECTED.
        Idempotent: duplicate attachments do not create duplicate entries.
        """
        if case_id not in self.cases:
            raise KeyError(f"Case '{case_id}' not found in workspace.")

        case = self.cases[case_id]

        # Verify finding exists
        fnd = self.findings_by_id.get(finding_id)
        if not fnd:
            # Check if it's a registered finding in evidence engine
            fnd_prov = self.evidence_engine.finding_evidence_map.get(finding_id)
            if not fnd_prov:
                raise KeyError(f"Finding '{finding_id}' not found in authoritative finding ledgers.")
            # For finding from evidence_engine
            # Verified via evidence_engine

        # Foreign finding check
        if fnd:
            fnd_entity = str(fnd.get("entity_id", fnd.get("canonical_entity_id", "")))
            if fnd_entity and fnd_entity != case.canonical_entity_id:
                raise ValueError(
                    f"Foreign finding rejected: finding '{finding_id}' belongs to entity '{fnd_entity}', "
                    f"not case target '{case.canonical_entity_id}'."
                )

        if finding_id not in case.finding_ids:
            case.finding_ids.append(finding_id)
            case.finding_ids.sort()
            case.record_audit_event("FINDING_ATTACHED", finding_id, actor=actor)

        return copy.deepcopy(case)

    def attach_evidence(
        self,
        case_id: str,
        evidence_id: str,
        actor: str = "INVESTIGATOR_CONSOLE"
    ) -> InvestigationCase:
        """
        Attaches a canonical evidence item to an investigation case.
        Enforces entity alignment: foreign evidence is REJECTED.
        Idempotent: duplicate attachments do not create duplicates.
        """
        if case_id not in self.cases:
            raise KeyError(f"Case '{case_id}' not found in workspace.")

        case = self.cases[case_id]

        # Verify evidence exists in M12 store
        ev = self.evidence_engine.get_evidence(evidence_id)
        if not ev:
            raise KeyError(f"Evidence '{evidence_id}' not found in M12 evidence store.")

        # Foreign evidence check
        if case.canonical_entity_id not in ev.canonical_entity_ids:
            raise ValueError(
                f"Foreign evidence rejected: evidence '{evidence_id}' binds to entities {ev.canonical_entity_ids}, "
                f"not case target '{case.canonical_entity_id}'."
            )

        if evidence_id not in case.evidence_ids:
            case.evidence_ids.append(evidence_id)
            case.evidence_ids.sort()
            if ev.provenance_ref not in case.provenance_refs:
                case.provenance_refs.append(ev.provenance_ref)
                case.provenance_refs.sort()
            case.record_audit_event("EVIDENCE_ATTACHED", evidence_id, actor=actor)

        return copy.deepcopy(case)

    def get_case_audit(self, case_id: str) -> List[Dict[str, Any]]:
        """Returns the chronological audit log for a case."""
        if case_id not in self.cases:
            raise KeyError(f"Case '{case_id}' not found in workspace.")
        return copy.deepcopy(self.cases[case_id].audit_log)

    def export_case(self, case_id: str, export_format: str = "json") -> Any:
        """Exports an investigation case dossier deterministically without mutating case state."""
        if case_id not in self.cases:
            raise KeyError(f"Case '{case_id}' not found in workspace.")

        case = copy.deepcopy(self.cases[case_id])
        d = case.to_dict()

        # Keep export deterministic for unchanged cases. Export generation is a snapshot,
        # not a write to the case state history.
        if export_format == "dict":
            return d
        elif export_format == "json":
            return json.dumps(d, indent=2, sort_keys=True)
        else:
            raise ValueError(f"Unsupported export format '{export_format}'.")

    # ── 3. ENTITY & CROSS-DOMAIN INVESTIGATION ────────────────────────────────

    def investigate_entity(self, canonical_entity_id: str) -> Dict[str, Any]:
        """
        Executes deep multi-domain forensic investigation for an authoritative entity.
        Gathers identity, linked identifiers, timeline bounds, findings, M11 fused cases,
        graph relationships, active cases, and M12 provenance.
        """
        if canonical_entity_id not in self.valid_entities:
            raise ValueError(f"Fail Closed: Entity '{canonical_entity_id}' is unknown in authoritative registries.")

        # 1. Linked Identifiers
        linked_ids = []
        domains = set()
        if not self.bridge_df.empty:
            b_sub = self.bridge_df[self.bridge_df["canonical_entity_id"] == canonical_entity_id]
            for _, r in b_sub.iterrows():
                dom = str(r.get("domain", "UNKNOWN")).upper()
                domains.add(dom)
                linked_ids.append({
                    "raw_identifier": str(r["raw_identifier"]),
                    "domain": dom,
                    "mapping_method": str(r.get("mapping_method", "CONTROLLED_CASE_MAPPING")),
                    "confidence": float(r.get("confidence", 0.95)),
                    "evidence_ref": str(r.get("evidence_ref", ""))
                })

        if not self.entities_df.empty:
            e_sub = self.entities_df[self.entities_df["canonical_entity_id"] == canonical_entity_id]
            for _, r in e_sub.iterrows():
                raw = str(r.get("raw_identifier", ""))
                if not any(x["raw_identifier"] == raw for x in linked_ids):
                    linked_ids.append({
                        "raw_identifier": raw,
                        "domain": str(r.get("identifier_type", "UNKNOWN")).upper(),
                        "mapping_method": str(r.get("match_method", "EXACT")),
                        "confidence": float(r.get("match_confidence", 1.0)),
                        "evidence_ref": str(r.get("evidence", ""))[:64]
                    })

        # 2. Timeline Bounds
        tl = self.get_timeline(canonical_entity_id)
        time_bounds = {
            "total_events": len(tl),
            "start_time": tl[0]["timestamp"] if tl else None,
            "end_time": tl[-1]["timestamp"] if tl else None,
            "temporal_semantics": tl[0]["temporal_semantics"] if tl else "UNKNOWN_TIMESTAMP"
        }

        # 3. Findings
        entity_findings = [f for f in self.findings_by_id.values() if str(f.get("entity_id", "")) == canonical_entity_id]

        # 4. M11 Fused Findings
        fused_cases = []
        try:
            fused_res = self.fusion_engine.fuse_for_entity(canonical_entity_id)
            if fused_res.get("conflict_status") not in ("INSUFFICIENT_EVIDENCE", "IDENTITY_UNCERTAIN"):
                fused_cases.append(fused_res)
        except Exception:
            pass

        # 5. Graph Relationships
        try:
            graph_res = self.graph_traversal.get_2hop_subgraph(canonical_entity_id)
            graph_rel = {
                "direct_neighbors_count": len(graph_res.get("1hop_neighbors", [])),
                "two_hop_neighbors_count": len(graph_res.get("2hop_neighbors", [])),
                "direct_neighbors": graph_res.get("1hop_neighbors", [])[:10]
            }
        except Exception:
            graph_rel = {"direct_neighbors_count": 0, "direct_neighbors": []}

        # 6. Active Cases
        active_cases = [c.case_id for c in self.cases.values() if c.canonical_entity_id == canonical_entity_id]

        # 7. M12 Provenance References
        prov_refs = [x["evidence_ref"] for x in linked_ids if x.get("evidence_ref")]

        # 8. Identity status semantics: determine whether pairwise CONFIRMED evidence exists
        identity_status = "SINGLETON_CANONICALIZED"
        # gather canonical member event ids for pairwise match lookup
        canonical_raws = [x["raw_identifier"] for x in linked_ids]
        confirmed_pairwise = False
        try:
            if not self.entity_matches_df.empty and not self.events_df.empty:
                # find event ids that map to any of the canonical raw identifiers
                event_ids = set()
                for _, ev in self.events_df.iterrows():
                    if str(ev.get("actor_id", "")) in canonical_raws or str(ev.get("target_id", "")) in canonical_raws:
                        event_ids.add(str(ev.get("event_id", "")))
                if event_ids:
                    sub = self.entity_matches_df[self.entity_matches_df["match_status"] == "CONFIRMED"] if "match_status" in self.entity_matches_df.columns else pd.DataFrame()
                    for _, mrow in sub.iterrows():
                        l = str(mrow.get("left_record_id", ""))
                        r = str(mrow.get("right_record_id", ""))
                        if l in event_ids and r in event_ids:
                            confirmed_pairwise = True
                            break
        except Exception:
            confirmed_pairwise = False

        if confirmed_pairwise:
            identity_status = "PAIRWISE_CONFIRMED"
        else:
            # If there are multiple linked identifiers but no pairwise confirmation, mark as CLUSTER_UNCONFIRMED
            if len(linked_ids) > 1:
                identity_status = "CLUSTER_UNCONFIRMED"

        return {
            "canonical_entity_id": canonical_entity_id,
            "identity": {
                "canonical_entity_id": canonical_entity_id,
                "status": identity_status,
                "linked_identifiers_count": len(linked_ids)
            },
            "linked_identifiers": linked_ids,
            "domains": sorted(list(domains)),
            "timeline_bounds": time_bounds,
            "findings_count": len(entity_findings),
            "findings": entity_findings,
            "m11_fused_findings": fused_cases,
            "graph_relationships": graph_rel,
            "active_cases": active_cases,
            "provenance_refs": prov_refs
        }

    # ── 4. TEMPORAL INVESTIGATION APIS ─────────────────────────────────────────

    def set_live_stream_events(self, stream_events: List[Dict[str, Any]]) -> None:
        """Registers in-memory live events so the investigation workspace exposes them in the same timeline API as canonical history."""
        self.live_stream_events = []
        for ev in stream_events or []:
            if isinstance(ev, dict):
                self.live_stream_events.append(dict(ev))

    def get_timeline(
        self,
        canonical_entity_id: str,
        from_time: Optional[float] = None,
        to_time: Optional[float] = None,
        dataset: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Retrieves chronological timeline for an entity.
        Respects OBSERVED_TIMESTAMP, SEQUENCE_ORDER_SURROGATE, UNKNOWN_TIMESTAMP.
        Never fabricates UTC dates.
        """
        entity_aliases = self._resolve_entity_aliases(canonical_entity_id)
        events = []
        if not self.events_df.empty:
            mask = self.events_df["actor_id"].astype(str).isin(entity_aliases) | self.events_df["target_id"].astype(str).isin(entity_aliases)
            events = self.events_df[mask].copy().to_dict(orient="records")
        if not events:
            events = self.temporal_engine.events_for_entity(canonical_entity_id, dataset=dataset)

        live_matches = []
        for ev in self.live_stream_events:
            actor = str(ev.get("actor_id", "")).strip()
            target = str(ev.get("target_id", "")).strip()
            if actor in entity_aliases or target in entity_aliases or canonical_entity_id in {actor, target}:
                live_matches.append(dict(ev))

        if live_matches:
            if isinstance(events, list):
                events.extend(live_matches)
            else:
                events = list(live_matches)

        # normalize canonical event rows from the authoritative parquet schema to the timeline contract
        normalized = []
        for ev in events:
            normalized_ev = dict(ev)
            timestamp = ev.get("timestamp")
            normalized_ev["temporal_semantics"] = str(ev.get("temporal_semantics", "OBSERVED_TIMESTAMP"))
            normalized_ev["canonical_entity_id"] = canonical_entity_id
            if "actor_id" not in normalized_ev:
                normalized_ev["actor_id"] = str(ev.get("actor_id", ""))
            if "target_id" not in normalized_ev:
                normalized_ev["target_id"] = str(ev.get("target_id", ""))
            if "epoch_time" not in normalized_ev or normalized_ev.get("epoch_time") is None:
                if isinstance(timestamp, str) and timestamp.strip():
                    try:
                        normalized_ev["epoch_time"] = pd.to_datetime(timestamp, utc=True).timestamp()
                    except Exception:
                        normalized_ev["epoch_time"] = None
                else:
                    normalized_ev["epoch_time"] = None
            else:
                normalized_ev["epoch_time"] = float(normalized_ev["epoch_time"])
            normalized.append(normalized_ev)

        # Apply temporal filtering if requested
        filtered = []
        for ev in normalized:
            ep = ev.get("epoch_time")
            if from_time is not None and ep is not None and ep < from_time:
                continue
            if to_time is not None and ep is not None and ep > to_time:
                continue
            filtered.append(ev)

        filtered.sort(key=lambda e: (e.get("epoch_time") is None, e.get("epoch_time") if e.get("epoch_time") is not None else 0.0))
        return filtered

    def history(
        self,
        canonical_entity_id: str,
        pivot: Optional[Union[str, float]] = None,
        dataset: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Returns strict causal history for an entity prior to pivot T.
        Strictly enforces no future leakage:
        - epoch_time < pivot: included
        - epoch_time >= pivot: excluded (unless authoritative sequence ordering places it before pivot)
        """
        events = self.get_timeline(canonical_entity_id, dataset=dataset)
        if pivot is None:
            return events

        try:
            pivot_epoch = float(pivot)
        except (ValueError, TypeError):
            pivot_epoch = pd.to_datetime(pivot, utc=True).timestamp()

        causal_events = []
        for e in events:
            ep = e.get("epoch_time")
            if ep is None:
                continue
            if ep < pivot_epoch:
                causal_events.append(e)
            elif ep == pivot_epoch:
                seq_num = e.get("sequence_number")
                pivot_seq = e.get("pivot_sequence_number")
                if seq_num is not None and pivot_seq is not None and seq_num < pivot_seq:
                    causal_events.append(e)
        return causal_events

    def validate_historical_evidence_set(
        self,
        events_or_evidence: List[Dict[str, Any]],
        pivot: Union[str, float]
    ) -> bool:
        """
        Temporal Guard: Rejects any attempt to include future events or unsequenced equal-timestamp events
        into a historical evidence set at pivot T.
        """
        return self.temporal_engine.validate_historical_evidence_set(events_or_evidence, pivot)

    def backtrack(
        self,
        canonical_entity_id: str,
        window_seconds: Optional[float] = None,
        pivot: Optional[float] = None,
        dataset: Optional[str] = None
    ) -> Dict[str, Any]:
        """Causal backward chain strictly before pivot."""
        event_list = self.get_timeline(canonical_entity_id)
        if pivot is not None:
            pivot_val = float(pivot)
        else:
            pivot_candidates = [float(e.get("epoch_time", 0.0)) for e in event_list if e.get("epoch_time") is not None]
            pivot_val = max(pivot_candidates) if pivot_candidates else float("inf")

        res = self.temporal_engine.backtrack(canonical_entity_id, pivot=pivot_val, dataset=dataset)
        preceding = [
            {**e, "history_scope": "OBSERVED_PAST_HISTORY"}
            for e in event_list
            if e.get("epoch_time") is not None and e.get("epoch_time") < pivot_val
        ]
        res["preceding_events"] = preceding
        res["event_count"] = len(preceding)

        # Apply window filtering if specified
        if window_seconds is not None:
            min_time = pivot_val - window_seconds
            filtered = [e for e in res["preceding_events"] if e.get("epoch_time") is None or e.get("epoch_time") >= min_time]
            res["preceding_events"] = filtered
            res["event_count"] = len(filtered)

        return res

    def forwardtrack(
        self,
        canonical_entity_id: str,
        window_seconds: Optional[float] = None,
        pivot: Optional[float] = None,
        dataset: Optional[str] = None
    ) -> Dict[str, Any]:
        """Causal forward chain strictly after pivot."""
        event_list = self.get_timeline(canonical_entity_id)
        if pivot is not None:
            pivot_val = float(pivot)
        else:
            pivot_candidates = [float(e.get("epoch_time", 0.0)) for e in event_list if e.get("epoch_time") is not None]
            pivot_val = min(pivot_candidates) if pivot_candidates else 0.0

        res = self.temporal_engine.forwardtrack(canonical_entity_id, pivot=pivot_val, dataset=dataset)
        subsequent = [
            {**e, "history_scope": "OBSERVED_FUTURE_HISTORY"}
            for e in event_list
            if e.get("epoch_time") is not None and e.get("epoch_time") > pivot_val
        ]
        res["subsequent_events"] = subsequent
        res["event_count"] = len(subsequent)

        # Apply window filtering if specified
        if window_seconds is not None:
            max_time = pivot_val + window_seconds
            filtered = [e for e in res["subsequent_events"] if e.get("epoch_time") is None or e.get("epoch_time") <= max_time]
            res["subsequent_events"] = filtered
            res["event_count"] = len(filtered)

        return res

    def build_temporal_sequence(
        self,
        canonical_entity_id: str,
        case_id: Optional[str] = None,
        dataset: Optional[str] = None
    ) -> TemporalSequence:
        """
        Builds a validated, deterministic TemporalSequence for an entity.
        Delegates to TemporalSequenceEngine.
        """
        raw_events = self.get_timeline(canonical_entity_id, dataset=dataset)
        return self.temporal_sequence_engine.build_sequence(
            raw_events,
            canonical_entity_id=canonical_entity_id,
            case_id=case_id,
            dataset=dataset
        )

    def build_sequence(
        self,
        events: List[Dict[str, Any]],
        canonical_entity_id: Optional[str] = None,
        case_id: Optional[str] = None,
        dataset: Optional[str] = None
    ) -> TemporalSequence:
        """Alias to build_temporal_sequence using raw events directly."""
        return self.temporal_sequence_engine.build_sequence(
            events,
            canonical_entity_id=canonical_entity_id,
            case_id=case_id,
            dataset=dataset
        )

    def _resolve_seq(
        self,
        target: Union[str, TemporalSequence],
        case_id: Optional[str] = None,
        dataset: Optional[str] = None
    ) -> TemporalSequence:
        if isinstance(target, TemporalSequence):
            return target
        return self.build_temporal_sequence(str(target), case_id=case_id, dataset=dataset)

    def extract_sequence_features(
        self,
        canonical_entity_id_or_seq: Union[str, TemporalSequence],
        case_id: Optional[str] = None,
        dataset: Optional[str] = None
    ) -> TemporalSequenceFeatures:
        seq = self._resolve_seq(canonical_entity_id_or_seq, case_id=case_id, dataset=dataset)
        return self.temporal_sequence_engine.extract_features(seq)

    def analyze_sequence_transitions(
        self,
        canonical_entity_id_or_seq: Union[str, TemporalSequence],
        case_id: Optional[str] = None,
        dataset: Optional[str] = None
    ) -> Dict[str, List[TemporalTransition]]:
        seq = self._resolve_seq(canonical_entity_id_or_seq, case_id=case_id, dataset=dataset)
        return self.temporal_sequence_engine.analyze_transitions(seq)

    def detect_sequence_patterns(
        self,
        canonical_entity_id_or_seq: Union[str, TemporalSequence],
        min_len: int = 2,
        max_len: int = 4,
        min_count: int = 1,
        case_id: Optional[str] = None,
        dataset: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        seq = self._resolve_seq(canonical_entity_id_or_seq, case_id=case_id, dataset=dataset)
        return self.temporal_sequence_engine.detect_patterns(seq, min_len=min_len, max_len=max_len, min_count=min_count)

    def detect_sequence_motifs(
        self,
        canonical_entity_id_or_seq: Union[str, TemporalSequence],
        case_id: Optional[str] = None,
        dataset: Optional[str] = None
    ) -> List[MotifMatch]:
        seq = self._resolve_seq(canonical_entity_id_or_seq, case_id=case_id, dataset=dataset)
        return self.temporal_sequence_engine.detect_motifs(seq)

    def discover_sequence_motifs(
        self,
        canonical_entity_id_or_seq: Union[str, TemporalSequence],
        min_length: Optional[int] = None,
        max_length: Optional[int] = None,
        distance_threshold: Optional[float] = None,
        min_cluster_size: Optional[int] = None,
        starting_motif_index: Optional[int] = None,
        case_id: Optional[str] = None,
        dataset: Optional[str] = None
    ) -> List[Any]:
        seq = self._resolve_seq(canonical_entity_id_or_seq, case_id=case_id, dataset=dataset)
        return self.temporal_motif_discovery_engine.discover_motifs(
            seq,
            min_length=min_length,
            max_length=max_length,
            distance_threshold=distance_threshold,
            min_cluster_size=min_cluster_size,
            starting_motif_index=starting_motif_index
        )

    def compress_sequence_phases(
        self,
        canonical_entity_id_or_seq: Union[str, TemporalSequence],
        gap_threshold_seconds: Optional[float] = None,
        case_id: Optional[str] = None,
        dataset: Optional[str] = None
    ) -> List[SequencePhase]:
        seq = self._resolve_seq(canonical_entity_id_or_seq, case_id=case_id, dataset=dataset)
        return self.temporal_sequence_engine.compress_phases(seq, gap_threshold_seconds=gap_threshold_seconds)

    def build_sequence_transition_graph(
        self,
        canonical_entity_id_or_seq: Union[str, TemporalSequence],
        case_id: Optional[str] = None,
        dataset: Optional[str] = None
    ) -> Dict[str, Any]:
        seq = self._resolve_seq(canonical_entity_id_or_seq, case_id=case_id, dataset=dataset)
        return self.temporal_sequence_engine.build_transition_graph(seq)

    def format_investigator_timeline(
        self,
        canonical_entity_id_or_seq: Union[str, TemporalSequence],
        trigger_event_id: Optional[str] = None,
        case_id: Optional[str] = None,
        dataset: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        seq = self._resolve_seq(canonical_entity_id_or_seq, case_id=case_id, dataset=dataset)
        return self.temporal_sequence_engine.format_investigator_timeline(seq, trigger_event=trigger_event_id)

    def compare_temporal_sequences(
        self,
        entity_or_seq_a: Union[str, TemporalSequence],
        entity_or_seq_b: Union[str, TemporalSequence],
        case_id_a: Optional[str] = None,
        case_id_b: Optional[str] = None,
        dataset: Optional[str] = None
    ) -> Dict[str, Any]:
        seq_a = self._resolve_seq(entity_or_seq_a, case_id=case_id_a, dataset=dataset)
        seq_b = self._resolve_seq(entity_or_seq_b, case_id=case_id_b, dataset=dataset)
        return self.temporal_sequence_engine.compare_sequences(seq_a, seq_b)

    # ── 5. GRAPH PATHS & RELATIONSHIPS ─────────────────────────────────────────

    def get_paths(
        self,
        source_entity: str,
        target_entity: Optional[str] = None,
        dataset: Optional[str] = None,
        max_hops: int = 3
    ) -> List[Dict[str, Any]]:
        """Finds temporal paths enforcing monotonic non-decreasing sequence."""
        if not target_entity:
            # If single entity provided, return 1-hop and 2-hop graph neighbors
            res = self.graph_traversal.get_2hop_subgraph(source_entity)
            return [res]

        return self.temporal_engine.find_temporal_paths(
            source_entity, target_entity, dataset=dataset, max_hops=max_hops
        )

    # ── 6. PROVENANCE & FINDING INSPECTION ─────────────────────────────────────

    def get_finding(self, finding_id: str) -> Dict[str, Any]:
        """Inspects a finding with complete evidence, score, and provenance references."""
        fnd = self.findings_by_id.get(finding_id)
        if not fnd:
            raise KeyError(f"Finding '{finding_id}' not found in authoritative findings ledger.")

        ev_ref = fnd.get("evidence_ref") or fnd.get("evidence_id") or f"ref:fnd:{finding_id}"
        return {
            "finding_id": finding_id,
            "entity": fnd.get("entity_id", fnd.get("canonical_entity_id")),
            "domain": fnd.get("source_domain", fnd.get("dataset", "CROSS_DOMAIN")),
            "score": float(fnd.get("composite_score", fnd.get("anomaly_score", 0.0))),
            "confidence": float(fnd.get("confidence", 0.90)),
            "status": fnd.get("status", "ACTIVE"),
            "detector": fnd.get("anomaly_type", fnd.get("detector", "DETECTOR_M9")),
            "temporal_context": {
                "timestamp": fnd.get("timestamp"),
                "temporal_semantics": fnd.get("temporal_semantics", "OBSERVED_TIMESTAMP")
            },
            "supporting_evidence": fnd.get("supporting_evidence", [ev_ref]),
            "contradicting_evidence": fnd.get("contradicting_evidence", []),
            "contextual_evidence": fnd.get("contextual_evidence", []),
            "m11_fusion_info": fnd.get("m11_fusion_info", {}),
            "m12_provenance_ref": ev_ref
        }

    def get_provenance(self, finding_id: str) -> Dict[str, Any]:
        """Traverses the M12 lineage graph upstream from a finding to root source records."""
        if finding_id not in self.evidence_engine.graph.nodes and finding_id not in self.evidence_engine.finding_evidence_map:
            raise KeyError(f"Finding '{finding_id}' has no registered provenance mapping in the M12 lineage graph.")

        lineage = self.evidence_engine.get_upstream_lineage(finding_id)
        integrity = self.evidence_engine.verify_finding_integrity(finding_id)
        return {
            "finding_id": finding_id,
            "integrity_status": integrity["status"],
            "is_valid": integrity["is_valid"],
            "broken_ancestor_id": integrity.get("broken_ancestor_id"),
            "lineage_hops_count": len(lineage),
            "lineage_chain": lineage
        }

    def assess_finding_reliability(
        self,
        case_id: str,
        finding_id: str,
        config: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        Evaluates evidence quality and reliability for a finding scoped within an investigation case.
        Delegates to EvidenceQualityReliabilityEngine without modifying upstream state.
        """
        from dfap.investigation.reliability import EvidenceQualityReliabilityEngine
        engine = EvidenceQualityReliabilityEngine(self, config=config)
        assessment = engine.assess_finding(case_id, finding_id, config=config)
        return assessment.to_dict()

    def register_source_dataset(self, source_id: str, df: pd.DataFrame):
        """Registers an in-memory or fixture source dataset by source_id."""
        self.source_datasets[source_id] = df

    def assess_source_health(
        self,
        source_id: str,
        config: Optional[Any] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Evaluates data quality and source health across 12 dimensions for an underlying source.
        Delegates to DataQualitySourceHealthEngine without modifying upstream state.
        """
        from dfap.investigation.data_quality import DataQualitySourceHealthEngine
        engine = DataQualitySourceHealthEngine(self, config=config)
        if "df" not in kwargs and hasattr(self, "source_datasets") and source_id in self.source_datasets:
            kwargs["df"] = self.source_datasets[source_id]
        assessment = engine.assess_source_health(source_id, **kwargs)
        return assessment.to_dict()

    def assess_case_data_health(
        self,
        case_id: str,
        config: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        Evaluates data quality across all sources used by evidence in an investigation case.
        Delegates to DataQualitySourceHealthEngine without modifying upstream state.
        """
        from dfap.investigation.data_quality import DataQualitySourceHealthEngine
        engine = DataQualitySourceHealthEngine(self, config=config)
        assessment = engine.assess_case_data_health(case_id, config=config)
        return assessment.to_dict()

    def generate_forensic_packet(self, case_id: str) -> Any:
        """
        Synthesizes a complete, deterministic forensic packet for the specified case.
        Delegates to ForensicCasePacketEngine without mutating upstream state.
        """
        from dfap.investigation.forensic_case_packet import ForensicCasePacketEngine
        engine = ForensicCasePacketEngine(self)
        return engine.generate_packet(case_id)

    def export_forensic_packet(self, case_id: str, output_dir: str = "output/cases") -> Dict[str, str]:
        """
        Exports the deterministic forensic packet into JSON and Markdown reports.
        Delegates to ForensicCasePacketEngine without mutating upstream state.
        """
        from dfap.investigation.forensic_case_packet import ForensicCasePacketEngine
        engine = ForensicCasePacketEngine(self)
        return engine.export_packet(case_id, output_dir=output_dir)

    def evaluate_finding_risk(
        self,
        finding_id: str,
        case_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Evaluates deterministic composite risk score and triage priority for a finding.
        Delegates to RiskScoringEngine without mutating upstream state.
        """
        eval_res = self.risk_engine.evaluate_finding(finding_id, case_id=case_id)
        return eval_res.to_dict()

    def get_triage_queue(
        self,
        case_id: Optional[str] = None,
        finding_ids: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Returns an input-order-independent ranked triage queue of findings.
        Delegates to RiskScoringEngine without mutating upstream state.
        """
        ranked = self.risk_engine.rank_findings(finding_ids=finding_ids, case_id=case_id)
        return [r.to_dict() for r in ranked]

    def explain_finding_shap(
        self,
        finding_id: str,
        case_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Generates on-demand SHAP explanation for a flagged M9 finding.
        Delegates to M9ShapExplainer without mutating upstream state.
        """
        explanation = self.shap_explainer.explain_finding(finding_id, case_id=case_id)
        return explanation.to_dict()

    def run_graph_ml_benchmark(self, seed: Optional[int] = None) -> Dict[str, Any]:
        """Executes controlled chronological benchmark comparing GraphSAGE vs TGN."""
        return self.graph_ml_service.run_benchmark(seed=seed)

    def predict_graph_relationship(
        self,
        source_id: str,
        target_id: str,
        timestamp: Optional[float] = None,
        model: str = "tgn"
    ) -> Dict[str, Any]:
        """Predicts relationship probability tagged strictly with status PREDICTED."""
        return self.graph_ml_service.predict_relationship(
            source_id=source_id,
            target_id=target_id,
            timestamp=timestamp,
            model=model
        )

    def explain_graph_prediction(
        self,
        source_id: str,
        target_id: str,
        timestamp: Optional[float] = None,
        model: str = "graphsage"
    ) -> Dict[str, Any]:
        """Explains relationship prediction sensitivity tagged strictly with status PREDICTED."""
        return self.graph_ml_service.explain_prediction(
            source_id=source_id,
            target_id=target_id,
            timestamp=timestamp,
            model=model
        )

    def run_temporal_similarity_ablation(
        self,
        target_series: Optional[Any] = None,
        query_pattern: Optional[Any] = None,
        simulate_stumpy_unavailable: bool = False
    ) -> Dict[str, Any]:
        """Executes controlled temporal similarity ablation comparing STUMPY vs DTW."""
        from dfap.investigation.temporal_ablation import TemporalSimilarityAblation
        ablation = TemporalSimilarityAblation()
        return ablation.run_controlled_ablation(
            target_series=target_series,
            query_pattern=query_pattern,
            simulate_stumpy_unavailable=simulate_stumpy_unavailable
        )



    def get_adaptive_baseline_status(self, entity_id: str, feature_name: Optional[str] = None) -> Dict[str, Any]:
        """Returns M8 adaptive baseline status for an entity."""
        return self.adaptive_baseline_manager.get_status(entity_id, feature_name)

    def get_adaptive_baseline_history(self, entity_id: str, feature_name: Optional[str] = None) -> List[Dict[str, Any]]:
        """Returns M8 immutable historical baseline decisions for an entity."""
        return self.adaptive_baseline_manager.get_history(entity_id, feature_name)

    def observe_adaptive_baseline(
        self,
        entity_id: str,
        feature_name: str,
        value: float,
        timestamp: Optional[float] = None,
        evidence_refs: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Processes an observation through M8 adaptive baseline tracker."""
        rec = self.adaptive_baseline_manager.observe(
            entity_id=entity_id,
            feature_name=feature_name,
            value=value,
            timestamp=timestamp,
            evidence_refs=evidence_refs
        )
        return rec.to_dict()

    def query_adaptive_baseline_agentic(
        self,
        question: str,
        entity_id: str,
        feature_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """M14 agentic tool interface for behavioral baseline questions."""
        return self.adaptive_baseline_manager.query_agentic_tool(
            question=question,
            entity_id=entity_id,
            feature_name=feature_name
        )

    def run_agentic_investigation(
        self,
        question: str,
        case_id: Optional[str] = None,
        entity_id: Optional[str] = None,
        finding_id: Optional[str] = None
    ) -> Any:
        """Executes an evidence-grounded agentic investigation with local Ollama synthesis."""
        from dfap.investigation.agentic_orchestrator import AgenticInvestigationOrchestrator
        if not hasattr(self, "_agentic_orchestrator") or self._agentic_orchestrator is None:
            self._agentic_orchestrator = AgenticInvestigationOrchestrator(self)
        return self._agentic_orchestrator.investigate(
            question=question,
            case_id=case_id,
            entity_id=entity_id,
            finding_id=finding_id
        )




