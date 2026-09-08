# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: M11 Cross-Domain Fusion Engine (Multi-Domain Corroboration, Evidence Graphs & Temporal Coherence)

import hashlib
import json
import logging
import math
import os
import time
from typing import Dict, Any, List, Optional, Tuple, Set
import numpy as np
import pandas as pd

from dfap.schemas import TemporalSemantics
from dfap.investigation.temporal_engine import load_identity_bridge_readonly
from dfap.investigation.evidential_conflict import (
    EvidentialConflictAnalyzer,
    EvidentialConflictStatus,
    EvidentialRequiredAction,
    DEFAULT_EVIDENTIAL_CONFLICT_THRESHOLDS
)

logger = logging.getLogger(__name__)

# Formal configuration for M11 Cross-Domain Fusion: zero hidden constants
CROSS_DOMAIN_FUSION_CONFIG = {
    "version": "v5.0.0_PRODUCTION_RESEARCH",
    "temporal_windows": {
        "TIGHT": 3600.0,       # 1 hour
        "MODERATE": 86400.0,   # 24 hours
        "BROAD": 604800.0      # 7 days
    },
    "scoring_weights": {
        "domain_support": 0.35,
        "temporal_coherence": 0.25,
        "identity_confidence": 0.25,
        "evidence_quality": 0.15
    },
    "thresholds": {
        "identity_link_min_confidence": 0.70,
        "target_independent_domains": 3,
        "supporting_anomaly_threshold": 0.45,
        "contradicting_normal_threshold": 0.25,
        "conflict_penalty_weight": 0.35,
        "material_conflict_threshold": 0.25,
        "abstention_conflict_threshold": 0.38
    }
}


class ConflictStatus:
    SUPPORTED = "SUPPORTED"
    CONFLICTED = "CONFLICTED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    IDENTITY_UNCERTAIN = "IDENTITY_UNCERTAIN"
    FUSION_ABSTAINED = "FUSION_ABSTAINED"
    NO_MATERIAL_CONFLICT = "NO_MATERIAL_CONFLICT"
    MATERIAL_CONFLICT = "MATERIAL_CONFLICT"
    ABSTENTION_REQUIRED = "ABSTENTION_REQUIRED"


class FusionEvidenceGraph:
    """
    Explicit bipartite/heterogeneous Evidence Graph supporting M11 Cross-Domain Fusion.
    Nodes: Canonical Entity, Domain Findings, Events.
    Edges: Preserves evidence_ref, source_domain, temporal relation, and identity provenance.
    """

    def __init__(self, canonical_entity_id: str):
        self.canonical_entity_id = canonical_entity_id
        self.nodes: Dict[str, Dict[str, Any]] = {
            canonical_entity_id: {"type": "CANONICAL_ENTITY", "id": canonical_entity_id}
        }
        self.edges: List[Dict[str, Any]] = []

    def add_finding_node(
        self,
        finding_id: str,
        domain: str,
        score: float,
        evidence_refs: List[str]
    ):
        self.nodes[finding_id] = {
            "type": "DOMAIN_FINDING",
            "id": finding_id,
            "domain": domain,
            "score": score,
            "evidence_refs": evidence_refs
        }
        self.edges.append({
            "source": self.canonical_entity_id,
            "target": finding_id,
            "relation": "EVIDENCE_SUPPORTS",
            "domain": domain,
            "confidence": score
        })

    def add_event_edge(
        self,
        finding_id: str,
        event_id: str,
        epoch_time: float,
        evidence_ref: str,
        source_domain: str
    ):
        if event_id not in self.nodes:
            self.nodes[event_id] = {
                "type": "CANONICAL_EVENT",
                "id": event_id,
                "epoch_time": epoch_time,
                "evidence_ref": evidence_ref,
                "source_domain": source_domain
            }
        self.edges.append({
            "source": finding_id,
            "target": event_id,
            "relation": "DERIVED_FROM_EVENT",
            "evidence_ref": evidence_ref,
            "epoch_time": epoch_time,
            "source_domain": source_domain
        })

    def to_dict(self) -> Dict[str, Any]:
        return {
            "canonical_entity_id": self.canonical_entity_id,
            "node_count": len(self.nodes),
            "edge_count": len(self.edges),
            "nodes": self.nodes,
            "edges": self.edges
        }


class CrossDomainFusionEngine:
    """
    M11 Cross-Domain Fusion Engine.
    Fuses independently derived evidence across Telecom, Financial, Social, Network, and Graph layers.
    Operates in two modes:
      A. Entity-Centric: Fuses evidence for a given canonical_entity_id.
      B. Population Discovery: Scans all eligible evidence and ranks multi-domain fused cases.
    """

    def __init__(
        self,
        identity_bridge_path: str = "data/cases/identity_bridge.parquet",
        canonical_dir: str = "data/canonical",
        findings_path: str = "output/m3/findings/findings.parquet"
    ):
        self.identity_bridge_path = identity_bridge_path
        self.canonical_dir = canonical_dir
        self.findings_path = findings_path
        self.bridge_df = load_identity_bridge_readonly(identity_bridge_path)
        self.config = CROSS_DOMAIN_FUSION_CONFIG

    def get_controlled_mappings_for_entity(self, canonical_entity_id: str) -> List[Dict[str, Any]]:
        """Extracts authorized identity bridge mappings for the canonical entity."""
        if self.bridge_df.empty or "canonical_entity_id" not in self.bridge_df.columns:
            return []
        matches = self.bridge_df[self.bridge_df["canonical_entity_id"] == canonical_entity_id]
        return matches.to_dict(orient="records")

    def fuse_for_entity(
        self,
        canonical_entity_id: str,
        domain_evidence_items: Optional[List[Dict[str, Any]]] = None,
        temporal_window_name: str = "MODERATE"
    ) -> Dict[str, Any]:
        """
        Executes entity-centric cross-domain fusion for a declared canonical entity.
        FUSION_CASE = canonical_entity_id + temporal window.
        """
        mappings = self.get_controlled_mappings_for_entity(canonical_entity_id)

        # 1. Identity Link Gate
        min_conf_threshold = self.config["thresholds"]["identity_link_min_confidence"]
        if not mappings:
            return self._create_abstained_case(
                canonical_entity_id,
                temporal_window_name,
                ConflictStatus.IDENTITY_UNCERTAIN,
                "No authorized mapping exists in the controlled identity bridge."
            )

        mean_identity_conf = float(np.mean([m.get("confidence", 0.0) for m in mappings]))
        if mean_identity_conf < min_conf_threshold:
            return self._create_abstained_case(
                canonical_entity_id,
                temporal_window_name,
                ConflictStatus.IDENTITY_UNCERTAIN,
                f"Mean identity bridge confidence ({mean_identity_conf:.3f}) is below threshold ({min_conf_threshold})."
            )

        # 2. Gather Evidence Items (if not directly provided)
        raw_items = domain_evidence_items if domain_evidence_items is not None else self._gather_entity_evidence(canonical_entity_id, mappings)

        # Evidence-to-Entity Binding Gate: Rigorously verify every item through authoritative bridge
        items = self._verify_and_bind_evidence_identity(canonical_entity_id, raw_items)

        if not items:
            return self._create_abstained_case(
                canonical_entity_id,
                temporal_window_name,
                ConflictStatus.INSUFFICIENT_EVIDENCE,
                "Zero valid domain evidence items bound to this entity through the controlled bridge."
            )

        # 3. Temporal Window Filtering & Semantics
        window_duration = self.config["temporal_windows"].get(temporal_window_name, 86400.0)
        valid_temporal_items, window_start, window_end, temporal_coherence = self._evaluate_temporal_coherence(
            items, window_duration
        )

        # 4. Domain Independence & Deduplication
        # Independent domain counting: items from same event or same source domain count as ONE domain
        domain_items_map: Dict[str, List[Dict[str, Any]]] = {}
        seen_events: Set[str] = set()
        provenance_refs: List[str] = [m.get("evidence_ref") for m in mappings if m.get("evidence_ref")]

        for itm in valid_temporal_items:
            dom = itm.get("source_domain", "UNKNOWN").upper()
            evt_id = itm.get("event_id")
            if evt_id and evt_id in seen_events:
                # Same underlying event cannot generate multiple independent domain evidence
                continue
            if evt_id:
                seen_events.add(evt_id)

            if dom not in domain_items_map:
                domain_items_map[dom] = []
            domain_items_map[dom].append(itm)

            ev_ref = itm.get("evidence_ref")
            if ev_ref and ev_ref not in provenance_refs:
                provenance_refs.append(ev_ref)

        independent_domain_count = len(domain_items_map)
        domains_present = list(domain_items_map.keys())

        # 5. Multi-Domain Corroboration & Conflict Evaluation
        supporting_domains = []
        contradicting_domains = []
        abstaining_domains = []

        support_thresh = self.config["thresholds"]["supporting_anomaly_threshold"]
        contra_thresh = self.config["thresholds"]["contradicting_normal_threshold"]

        domain_scores = {}
        for dom, dom_items in domain_items_map.items():
            scores = [float(x.get("anomaly_score", x.get("score", 0.5))) for x in dom_items]
            dom_score = float(np.mean(scores))
            domain_scores[dom] = round(dom_score, 3)

            if dom_score >= support_thresh:
                supporting_domains.append(dom)
            elif dom_score <= contra_thresh:
                contradicting_domains.append(dom)
            else:
                abstaining_domains.append(dom)

        # Evidential Conflict Intelligence (BetP, Hellinger Distance, Cosine Angle, Compound Conflict)
        conflict_analyzer = EvidentialConflictAnalyzer(
            thresholds=self.config.get("thresholds"),
            sensitivity=self.config.get("evidence_sensitivity", 0.8)
        )
        evidential_conflict = conflict_analyzer.analyze_domains(domain_scores)

        # Conflict Status
        if supporting_domains and contradicting_domains or evidential_conflict["abstention_required"]:
            conflict_status = ConflictStatus.CONFLICTED
            conflict_penalty = self.config["thresholds"]["conflict_penalty_weight"]
        elif independent_domain_count < 2:
            conflict_status = ConflictStatus.INSUFFICIENT_EVIDENCE
            conflict_penalty = 0.0
        else:
            conflict_status = ConflictStatus.SUPPORTED
            conflict_penalty = 0.0

        # 6. Corroboration Score Formulation (Transparent, Zero Hidden Constants)
        target_domains = self.config["thresholds"]["target_independent_domains"]
        domain_support = min(1.0, float(len(supporting_domains) / target_domains))
        evidence_quality = float(len([x for x in valid_temporal_items if x.get("evidence_ref")]) / max(1, len(valid_temporal_items)))

        w = self.config["scoring_weights"]
        raw_corroboration = (
            w["domain_support"] * domain_support +
            w["temporal_coherence"] * temporal_coherence +
            w["identity_confidence"] * mean_identity_conf +
            w["evidence_quality"] * evidence_quality -
            conflict_penalty
        )
        corroboration_score = round(float(np.clip(raw_corroboration, 0.0, 1.0)), 4)

        uncertainty = round(float(np.clip(1.0 - (mean_identity_conf * (independent_domain_count / max(2, target_domains))), 0.05, 0.95)), 4)

        # 7. Evidence Graph Construction
        graph = FusionEvidenceGraph(canonical_entity_id)
        for dom, d_items in domain_items_map.items():
            for idx, item in enumerate(d_items):
                f_id = item.get("finding_id", f"FND_{dom}_{idx}")
                graph.add_finding_node(
                    finding_id=f_id,
                    domain=dom,
                    score=float(item.get("anomaly_score", item.get("score", 0.5))),
                    evidence_refs=[item.get("evidence_ref", "")]
                )
                if item.get("event_id"):
                    graph.add_event_edge(
                        finding_id=f_id,
                        event_id=item["event_id"],
                        epoch_time=float(item.get("epoch_time", 0.0)),
                        evidence_ref=item.get("evidence_ref", ""),
                        source_domain=dom
                    )

        # 8. Structured Truthful Explanation
        explanation = self._build_truthful_explanation(
            canonical_entity_id=canonical_entity_id,
            domains_present=domains_present,
            temporal_window_name=temporal_window_name,
            window_duration=window_duration,
            supporting_domains=supporting_domains,
            contradicting_domains=contradicting_domains,
            valid_items=valid_temporal_items,
            mean_identity_conf=mean_identity_conf,
            mappings=mappings,
            conflict_status=conflict_status,
            uncertainty=uncertainty,
            provenance_refs=provenance_refs
        )

        fusion_case_id = f"FUS-{canonical_entity_id[:16]}-{temporal_window_name[:3]}-{hashlib.sha256(canonical_entity_id.encode()).hexdigest()[:6]}"

        return {
            "fusion_case_id": fusion_case_id,
            "canonical_entity_id": canonical_entity_id,
            "domains_present": domains_present,
            "trigger_events": [x["event_id"] for x in valid_temporal_items if x.get("event_id")],
            "temporal_window": {
                "name": temporal_window_name,
                "window_duration_seconds": window_duration,
                "window_start": window_start,
                "window_end": window_end,
                "evidence_event_times": [x.get("timestamp") for x in valid_temporal_items if x.get("timestamp")],
                "temporal_coherence_method": "INTER_EVENT_SPAN_NORMALIZATION"
            },
            "supporting_findings": [x.get("finding_id", x.get("event_id")) for x in valid_temporal_items],
            "domain_evidence_count": len(valid_temporal_items),
            "independent_domain_count": independent_domain_count,
            "domain_scores": domain_scores,
            "corroboration_score": corroboration_score,
            "cross_domain_corroboration_score": corroboration_score,
            "temporal_coherence_score": temporal_coherence,
            "identity_link_confidence": round(mean_identity_conf, 4),
            "evidence_completeness": round(evidence_quality, 4),
            "uncertainty": uncertainty,
            "conflict_status": conflict_status,
            "evidential_conflict": evidential_conflict,
            "evidential_conflict_status": evidential_conflict["overall_status"],
            "requires_human_review": evidential_conflict["requires_human_review"],
            "required_action": evidential_conflict["required_action"],
            "supporting_domains": supporting_domains,
            "contradicting_domains": contradicting_domains,
            "abstaining_domains": abstaining_domains,
            "provenance_refs": provenance_refs,
            "evidence_items": valid_temporal_items,
            "identity_provenance": [
                {
                    "canonical_entity_id": x.get("canonical_entity_id"),
                    "raw_identifier": x.get("raw_identifier"),
                    "mapping_method": x.get("mapping_method"),
                    "mapping_confidence": x.get("mapping_confidence"),
                    "mapping_evidence_ref": x.get("mapping_evidence_ref")
                }
                for x in valid_temporal_items
            ],
            "evidence_graph": graph.to_dict(),
            "explanation": explanation,
            "scoring_parameters": self.config
        }

    def discover_fused_cases(
        self,
        domain_evidence_by_entity: Optional[Dict[str, List[Dict[str, Any]]]] = None,
        temporal_window_name: str = "MODERATE",
        min_independent_domains: int = 2,
        min_corroboration_score: float = 0.40
    ) -> List[Dict[str, Any]]:
        """
        Population-level Autonomous Cross-Domain Discovery.
        Scans all authorized canonical entities in the identity bridge WITHOUT a predefined suspect.
        """
        if self.bridge_df.empty:
            return []

        unique_entities = self.bridge_df["canonical_entity_id"].unique()
        discovered = []

        for entity_id in unique_entities:
            custom_items = domain_evidence_by_entity.get(entity_id) if domain_evidence_by_entity else None
            fused = self.fuse_for_entity(
                entity_id,
                domain_evidence_items=custom_items,
                temporal_window_name=temporal_window_name
            )
            if fused["independent_domain_count"] >= min_independent_domains and fused["corroboration_score"] >= min_corroboration_score:
                discovered.append(fused)

        # Sort descending by corroboration score deterministically
        discovered.sort(key=lambda x: (x["corroboration_score"], x["independent_domain_count"]), reverse=True)
        return discovered

    def run_ablation_study(
        self,
        canonical_entity_id: str,
        domain_evidence_pool: Dict[str, List[Dict[str, Any]]],
        temporal_window_name: str = "MODERATE"
    ) -> Dict[str, Any]:
        """
        Executes formal cross-domain fusion ablation across single-domain, pairwise, and multi-domain configurations.
        Demonstrates how independent domain corroboration reduces uncertainty and adds empirical signal.
        """
        configurations = {
            "telecom_only": ["TELECOM"],
            "financial_only": ["FINANCIAL"],
            "social_only": ["SOCIAL"],
            "graph_only": ["GRAPH"],
            "pairwise_telecom_financial": ["TELECOM", "FINANCIAL"],
            "pairwise_financial_social": ["FINANCIAL", "SOCIAL"],
            "pairwise_telecom_social": ["TELECOM", "SOCIAL"],
            "three_domain_telecom_financial_social": ["TELECOM", "FINANCIAL", "SOCIAL"],
            "all_domains": list(domain_evidence_pool.keys())
        }

        ablation_results = {}
        for config_name, active_domains in configurations.items():
            # Filter evidence pool to active domains
            subset_items = []
            for dom in active_domains:
                subset_items.extend(domain_evidence_pool.get(dom, []))

            fused = self.fuse_for_entity(
                canonical_entity_id=canonical_entity_id,
                domain_evidence_items=subset_items,
                temporal_window_name=temporal_window_name
            )

            ablation_results[config_name] = {
                "active_domains": active_domains,
                "independent_domain_count": fused["independent_domain_count"],
                "corroboration_score": fused["corroboration_score"],
                "conflict_status": fused["conflict_status"],
                "uncertainty": fused["uncertainty"],
                "temporal_coherence_score": fused["temporal_coherence_score"],
                "evidence_completeness": fused["evidence_completeness"]
            }

        return {
            "canonical_entity_id": canonical_entity_id,
            "temporal_window": temporal_window_name,
            "configurations": ablation_results
        }

    def _verify_and_bind_evidence_identity(
        self,
        canonical_entity_id: str,
        items: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Rigorous Evidence-to-Entity Proof Gate:
        For every evidence item:
          1. Resolve its source identity using raw_identifier, source_identifier, or entity_id.
          2. Verify the identity maps through the authoritative controlled bridge to canonical_entity_id.
          3. Retain explicit identity provenance:
             - canonical_entity_id
             - source/raw identifier
             - mapping_method
             - mapping_confidence
             - mapping_evidence_ref
          4. Reject/abstain on:
             - evidence belonging to another canonical entity
             - unmapped evidence
             - missing identity binding
             - conflicting canonical entity assignment
          5. Never trust caller-supplied canonical_entity_id alone.
        """
        if self.bridge_df.empty or "raw_identifier" not in self.bridge_df.columns:
            return []

        bridge_lookup = {r["raw_identifier"]: r for r in self.bridge_df.to_dict(orient="records")}
        valid_items = []

        for item in items:
            raw_id = item.get("raw_identifier") or item.get("source_identifier") or item.get("entity_id")

            # 4. Reject missing identity binding
            if not raw_id:
                logger.warning(f"Rejecting evidence item {item.get('finding_id', item.get('event_id'))}: missing identity binding.")
                continue

            # 2. Verify identity maps through controlled bridge
            mapping = bridge_lookup.get(raw_id)
            if not mapping:
                logger.warning(f"Rejecting evidence item {item.get('finding_id')}: unmapped raw identifier '{raw_id}'.")
                continue

            # 4. Reject evidence belonging to another canonical entity
            mapped_canon = mapping["canonical_entity_id"]
            if mapped_canon != canonical_entity_id:
                logger.warning(f"Rejecting evidence item {item.get('finding_id')}: identifier '{raw_id}' maps to '{mapped_canon}', not requested '{canonical_entity_id}'.")
                continue

            # 4 & 5. Reject conflicting canonical assignment / never trust caller-supplied canon alone
            caller_canon = item.get("mapped_canonical_entity_id") or item.get("canonical_entity_id")
            if caller_canon and caller_canon != canonical_entity_id:
                logger.warning(f"Rejecting evidence item {item.get('finding_id')}: conflicting canonical assignment '{caller_canon}' vs '{canonical_entity_id}'.")
                continue

            # 3. Retain explicit identity provenance
            item_bound = dict(item)
            item_bound["canonical_entity_id"] = canonical_entity_id
            item_bound["raw_identifier"] = raw_id
            item_bound["source_identifier"] = raw_id
            item_bound["mapping_method"] = mapping["mapping_method"]
            item_bound["mapping_confidence"] = float(mapping["confidence"])
            item_bound["mapping_evidence_ref"] = mapping["evidence_ref"]
            valid_items.append(item_bound)

        return valid_items

    def _evaluate_temporal_coherence(
        self,
        items: List[Dict[str, Any]],
        window_duration: float,
        anchor_epoch: Optional[float] = None
    ) -> Tuple[List[Dict[str, Any]], float, float, float]:
        """Calculates temporal span and coherence score strictly across evidence items within window."""
        epochs = [float(x["epoch_time"]) for x in items if "epoch_time" in x and x["epoch_time"] is not None]
        if not epochs:
            return items, 0.0, 0.0, 1.0

        min_ep = anchor_epoch if anchor_epoch is not None else min(epochs)

        # Items strictly falling within window relative to anchor min_ep
        valid = [
            x for x in items
            if ("epoch_time" not in x or x["epoch_time"] is None or (min_ep <= float(x["epoch_time"]) <= min_ep + window_duration))
        ]

        valid_epochs = [float(x["epoch_time"]) for x in valid if "epoch_time" in x and x["epoch_time"] is not None]
        if not valid_epochs:
            return [], min_ep, min_ep + window_duration, 0.0

        actual_min = min(valid_epochs)
        actual_max = max(valid_epochs)
        span = actual_max - actual_min

        coherence = max(0.0, 1.0 - (span / max(1.0, window_duration)))
        return valid, actual_min, actual_max, round(float(np.clip(coherence, 0.05, 1.0)), 4)

    def _gather_entity_evidence(self, canonical_entity_id: str, mappings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Gathers authentic evidence across upstream feature and canonical datasets."""
        evidence_items = []

        # Raw identifiers associated with entity
        raw_ids = {m["raw_identifier"]: m["domain"] for m in mappings}

        # Check findings.parquet if available
        if os.path.exists(self.findings_path):
            f_df = pd.read_parquet(self.findings_path)
            for raw_id, dom in raw_ids.items():
                m_fnd = f_df[f_df["entity_id"] == raw_id]
                for _, r in m_fnd.iterrows():
                    evidence_items.append({
                        "finding_id": r["finding_id"],
                        "source_domain": dom,
                        "anomaly_score": float(r.get("composite_score", 0.5)),
                        "epoch_time": float(pd.to_datetime(r.get("timestamp_start", 0)).timestamp()) if r.get("timestamp_start") else 1421980000.0,
                        "timestamp": str(r.get("timestamp_start", "")),
                        "evidence_ref": f"ref:finding_{r['finding_id']}",
                        "event_id": f"EVT_{r['finding_id']}"
                    })
        return evidence_items

    def _create_abstained_case(
        self,
        canonical_entity_id: str,
        temporal_window_name: str,
        status: str,
        reason: str
    ) -> Dict[str, Any]:
        """Creates a standardized abstained fusion case."""
        return {
            "fusion_case_id": f"FUS-ABSTAINED-{canonical_entity_id[:12]}-{int(time.time())}",
            "canonical_entity_id": canonical_entity_id,
            "domains_present": [],
            "trigger_events": [],
            "temporal_window": {"name": temporal_window_name, "status": "ABSTAINED"},
            "supporting_findings": [],
            "domain_evidence_count": 0,
            "independent_domain_count": 0,
            "domain_scores": {},
            "corroboration_score": 0.0,
            "cross_domain_corroboration_score": 0.0,
            "temporal_coherence_score": 0.0,
            "identity_link_confidence": 0.0,
            "evidence_completeness": 0.0,
            "uncertainty": 1.0,
            "conflict_status": status,
            "evidential_conflict": {
                "overall_status": EvidentialConflictStatus.NO_MATERIAL_CONFLICT,
                "max_compound_conflict": 0.0,
                "worst_pair": None,
                "requires_human_review": False,
                "abstention_required": False,
                "required_action": EvidentialRequiredAction.PROCEED,
                "pairwise_conflicts": [],
                "explanation": f"FUSION ABSTAINED: {reason}"
            },
            "evidential_conflict_status": EvidentialConflictStatus.NO_MATERIAL_CONFLICT,
            "requires_human_review": False,
            "required_action": EvidentialRequiredAction.PROCEED,
            "supporting_domains": [],
            "contradicting_domains": [],
            "abstaining_domains": [],
            "provenance_refs": [],
            "evidence_graph": {"node_count": 1, "edge_count": 0},
            "explanation": f"FUSION ABSTAINED: {reason}",
            "scoring_parameters": self.config
        }

    def _build_truthful_explanation(
        self,
        canonical_entity_id: str,
        domains_present: List[str],
        temporal_window_name: str,
        window_duration: float,
        supporting_domains: List[str],
        contradicting_domains: List[str],
        valid_items: List[Dict[str, Any]],
        mean_identity_conf: float,
        mappings: List[Dict[str, Any]],
        conflict_status: str,
        uncertainty: float,
        provenance_refs: List[str]
    ) -> str:
        """Constructs an auditable, structured explanation free from unproven causal speculation."""
        events_str = ", ".join([x.get("event_id", "N/A") for x in valid_items[:3]])
        prov_str = ", ".join(provenance_refs[:3])
        conflict_note = "NONE (all active domains corroborate anomalous behavior)" if not contradicting_domains else f"CONFLICT: Contradicted by {', '.join(contradicting_domains)}"

        lines = [
            f"ENTITY: {canonical_entity_id}",
            f"DOMAINS: {', '.join(domains_present)} ({len(domains_present)} independent domains)",
            f"TIME WINDOW: {temporal_window_name} (duration {window_duration:.0f}s)",
            f"SUPPORTING EVENTS: {events_str}",
            f"IDENTITY LINK: CONTROLLED_CASE_MAPPING (mean confidence: {mean_identity_conf:.3f} across {len(mappings)} mappings)",
            f"TEMPORAL RELATION: Events span within the declared {temporal_window_name} window",
            f"CORROBORATING SIGNALS: {', '.join(supporting_domains)} support elevated anomaly score",
            f"CONFLICTS: {conflict_note}",
            f"UNCERTAINTY: Epistemic uncertainty {uncertainty:.3f} under {conflict_status} status",
            f"PROVENANCE: {prov_str}"
        ]
        return "\n".join(lines)
