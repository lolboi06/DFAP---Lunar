# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: M13 Triage Risk Prioritization Layer (Composite Case & Finding-Level Risk Scoring)

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import math
from typing import Any, Dict, List, Optional, Set, Tuple, Union
import numpy as np
import pandas as pd


RISK_SCORING_SCHEMA_VERSION = "v1.0.0_TRIAGE_RISK"


class PriorityLevel(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class MissingSignalPolicy(str, Enum):
    REDISTRIBUTE_ACTIVE_WEIGHTS = "REDISTRIBUTE_ACTIVE_WEIGHTS"
    ZERO_FILL = "ZERO_FILL"


# Explicit, versioned deterministic configuration: zero hidden constants
DEFAULT_RISK_SCORING_CONFIG: Dict[str, Any] = {
    "version": RISK_SCORING_SCHEMA_VERSION,
    "weights": {
        "anomaly": 0.35,              # Weight for raw detector anomaly score
        "graph_significance": 0.20,   # Weight for graph topology / entity degree centrality
        "fusion_confidence": 0.25,    # Weight for M11 cross-domain fusion corroboration
        "recency_clustering": 0.20,   # Weight for entity finding clustering and event recency
    },
    "graph_significance": {
        "degree_saturation": 10.0,    # Max neighbor count for degree normalization
        "default_isolated": 0.10,     # Significance assigned when entity is completely isolated
    },
    "recency_clustering": {
        "cluster_saturation": 5.0,    # Max findings on same entity for cluster saturation
        "halflife_seconds": 86400.0 * 30,  # 30-day time decay half-life
    },
    "priority_thresholds": {
        "high": 0.65,
        "medium": 0.40,
    },
    "missing_signal_policy": MissingSignalPolicy.REDISTRIBUTE_ACTIVE_WEIGHTS.value,
}


@dataclass
class FindingRiskEvaluation:
    """
    Structured, deterministic risk prioritization result for an investigative finding.
    Strictly free from subjective intent or criminal guilt claims.
    """
    finding_id: str
    case_id: Optional[str]
    entity_id: str
    risk_score: float
    priority_level: str
    priority_rank: int
    
    # Component breakdown (raw values and weighted contributions)
    anomaly_component: Dict[str, Any]
    graph_significance_component: Dict[str, Any]
    fusion_component: Dict[str, Any]
    recency_clustering_component: Dict[str, Any]
    
    # Metadata and provenance
    contributing_finding_ids: List[str]
    linked_evidence_ids: List[str]
    conflict_status: str
    requires_human_review: bool
    missing_signals: List[str]
    missing_signal_policy: str
    reason_codes: List[str]
    explanation: str
    schema_version: str = RISK_SCORING_SCHEMA_VERSION
    evaluated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "finding_id": self.finding_id,
            "case_id": self.case_id,
            "entity_id": self.entity_id,
            "risk_score": round(self.risk_score, 4),
            "priority_level": self.priority_level,
            "priority_rank": self.priority_rank,
            "anomaly_component": self.anomaly_component,
            "graph_significance_component": self.graph_significance_component,
            "fusion_component": self.fusion_component,
            "recency_clustering_component": self.recency_clustering_component,
            "contributing_finding_ids": self.contributing_finding_ids,
            "linked_evidence_ids": self.linked_evidence_ids,
            "conflict_status": self.conflict_status,
            "requires_human_review": self.requires_human_review,
            "missing_signals": self.missing_signals,
            "missing_signal_policy": self.missing_signal_policy,
            "reason_codes": self.reason_codes,
            "explanation": self.explanation,
            "evaluated_at": self.evaluated_at,
        }


class RiskScoringEngine:
    """
    Deterministic Finding & Case-Level Risk Prioritization Engine.
    Synthesizes M9 raw anomaly score, M4 graph significance, M11 cross-domain fusion,
    and finding recency/clustering into a ranked triage score.
    """

    def __init__(self, workspace_backend: Any, config: Optional[Dict[str, Any]] = None):
        self.backend = workspace_backend
        self.config = config or DEFAULT_RISK_SCORING_CONFIG

    def evaluate_finding(
        self,
        finding_id: str,
        case_id: Optional[str] = None,
        entity_findings_pool: Optional[List[Dict[str, Any]]] = None
    ) -> FindingRiskEvaluation:
        """Evaluates composite triage risk for a single finding deterministically."""
        # 1. Retrieve Finding
        finding = self.backend.findings_by_id.get(finding_id)
        if not finding:
            # Fall back to get_finding if available
            try:
                finding = self.backend.get_finding(finding_id)
            except Exception:
                raise KeyError(f"Finding '{finding_id}' not found in authoritative workspace findings.")

        entity_id = finding.get("entity_id") or finding.get("canonical_entity_id") or finding.get("entity", "UNKNOWN_ENTITY")
        case_id = case_id or finding.get("case_id")
        
        # If case_id not explicitly attached, check if any active case contains this finding
        if not case_id and hasattr(self.backend, "cases"):
            for cid, c_obj in self.backend.cases.items():
                if finding_id in c_obj.finding_ids:
                    case_id = cid
                    break

        weights = self.config["weights"]
        missing_signals: List[str] = []
        reason_codes: List[str] = []

        # ── SIGNAL 1: M9 Raw Anomaly Score ─────────────────────────────────────────
        raw_anomaly = None
        for k in ["anomaly_score", "score", "composite_score"]:
            if k in finding and finding[k] is not None:
                try:
                    raw_anomaly = float(finding[k])
                    break
                except (ValueError, TypeError):
                    continue

        if raw_anomaly is None:
            missing_signals.append("ANOMALY_SCORE_UNAVAILABLE")
            raw_anomaly_val = 0.0
            anomaly_available = False
        else:
            raw_anomaly_val = float(np.clip(raw_anomaly, 0.0, 1.0))
            anomaly_available = True
            if raw_anomaly_val >= 0.80:
                reason_codes.append("HIGH_ANOMALY_SCORE")
            elif raw_anomaly_val >= 0.50:
                reason_codes.append("MODERATE_ANOMALY_SCORE")

        # ── SIGNAL 2: M4 Graph Significance / Topology Centrality ──────────────────
        graph_sig_val = None
        graph_available = False
        neighbor_count = 0

        # Try to determine entity degree in events_df or graph traversal
        entity_aliases = self.backend._resolve_entity_aliases(entity_id) if hasattr(self.backend, "_resolve_entity_aliases") else {entity_id}
        if hasattr(self.backend, "events_df") and not self.backend.events_df.empty:
            mask = self.backend.events_df["actor_id"].astype(str).isin(entity_aliases) | self.backend.events_df["target_id"].astype(str).isin(entity_aliases)
            matched_events = self.backend.events_df[mask]
            if not matched_events.empty:
                connected_nodes = set()
                for _, r in matched_events.iterrows():
                    act = str(r.get("actor_id", "")).strip()
                    tgt = str(r.get("target_id", "")).strip()
                    if act and act not in entity_aliases:
                        connected_nodes.add(act)
                    if tgt and tgt not in entity_aliases:
                        connected_nodes.add(tgt)
                neighbor_count = len(connected_nodes)
                sat = float(self.config["graph_significance"]["degree_saturation"])
                graph_sig_val = float(np.clip(neighbor_count / sat, 0.0, 1.0))
                graph_available = True

        if graph_sig_val is None:
            # Check if backend evidence graph has degree info
            if hasattr(self.backend, "evidence_engine") and hasattr(self.backend.evidence_engine, "graph"):
                g = self.backend.evidence_engine.graph
                if entity_id in g.nodes:
                    # count connected edges
                    degree = len([e for e in g.edges if e.get("source") == entity_id or e.get("target") == entity_id])
                    neighbor_count = degree
                    sat = float(self.config["graph_significance"]["degree_saturation"])
                    graph_sig_val = float(np.clip(neighbor_count / sat, 0.0, 1.0))
                    graph_available = True

        if not graph_available:
            missing_signals.append("GRAPH_TOPOLOGY_UNAVAILABLE")
            graph_sig_val = float(self.config["graph_significance"].get("default_isolated", 0.10))
        else:
            if neighbor_count >= 5:
                reason_codes.append("HIGH_GRAPH_CONNECTIVITY")
            elif neighbor_count >= 2:
                reason_codes.append("MULTI_PARTY_NETWORK")

        # ── SIGNAL 3: M11 Cross-Domain Fusion Confidence ──────────────────────────
        fusion_val = None
        fusion_available = False
        m11_info = finding.get("m11_fusion_info", {})
        conflict_status = finding.get("status", "ACTIVE")
        requires_human_review = False

        if m11_info and isinstance(m11_info, dict):
            c_score = m11_info.get("corroboration_score") or m11_info.get("cross_domain_corroboration_score")
            if c_score is not None:
                fusion_val = float(np.clip(c_score, 0.0, 1.0))
                fusion_available = True
            
            f_conf_stat = m11_info.get("conflict_status")
            if f_conf_stat:
                conflict_status = f_conf_stat
            if m11_info.get("requires_human_review", False) or conflict_status in ("CONFLICTED", "ABSTENTION_REQUIRED"):
                requires_human_review = True
                reason_codes.append("EVIDENTIAL_CONFLICT_DETECTED")
            
            ind_domains = m11_info.get("independent_domain_count", 0)
            if ind_domains >= 3:
                reason_codes.append("CROSS_DOMAIN_MULTI_TELEMETRY")
        elif finding.get("source_domain") == "CROSS_DOMAIN":
            # Finding is cross-domain, check score
            f_score = finding.get("composite_score") or finding.get("score")
            if f_score is not None:
                fusion_val = float(np.clip(f_score, 0.0, 1.0))
                fusion_available = True

        if not fusion_available:
            missing_signals.append("FUSION_CONFIDENCE_UNAVAILABLE")
            fusion_val = 0.0
        else:
            if fusion_val >= 0.60:
                reason_codes.append("HIGH_FUSION_CORROBORATION")

        # ── SIGNAL 4: Recency & Clustering Density ─────────────────────────────────
        recency_val = 0.50
        all_pool = entity_findings_pool if entity_findings_pool is not None else [
            f for f in self.backend.findings_by_id.values()
            if (f.get("entity_id") == entity_id or f.get("canonical_entity_id") == entity_id or f.get("entity") == entity_id)
        ]
        cluster_size = len(all_pool)
        cluster_sat = float(self.config["recency_clustering"]["cluster_saturation"])
        cluster_score = float(np.clip(cluster_size / cluster_sat, 0.0, 1.0))

        # Evaluate time recency relative to latest observed event in case
        time_score = 1.0
        finding_ts = finding.get("timestamp") or finding.get("temporal_context", {}).get("timestamp")
        if finding_ts and hasattr(self.backend, "events_df") and not self.backend.events_df.empty:
            try:
                f_epoch = pd.to_datetime(finding_ts, utc=True).timestamp()
                max_epoch = float(self.backend.events_df["epoch_time"].max())
                delta = max(0.0, max_epoch - f_epoch)
                halflife = float(self.config["recency_clustering"]["halflife_seconds"])
                time_score = math.exp(-0.693147 * (delta / max(1.0, halflife)))
            except Exception:
                time_score = 0.80

        recency_val = float(np.clip(0.5 * cluster_score + 0.5 * time_score, 0.0, 1.0))
        if cluster_size >= 2:
            reason_codes.append(f"FINDING_CLUSTER_SIZE_{cluster_size}")

        # ── SCORE AGGREGATION & MISSING SIGNAL POLICY ──────────────────────────────
        components = {
            "anomaly": (raw_anomaly_val, anomaly_available),
            "graph_significance": (graph_sig_val, graph_available),
            "fusion_confidence": (fusion_val, fusion_available),
            "recency_clustering": (recency_val, True),
        }

        policy = self.config.get("missing_signal_policy", MissingSignalPolicy.REDISTRIBUTE_ACTIVE_WEIGHTS.value)
        active_weight_sum = sum(weights[k] for k, (_, avail) in components.items() if (avail or policy == MissingSignalPolicy.ZERO_FILL.value))

        weighted_sum = 0.0
        contributions: Dict[str, float] = {}

        for k, (val, avail) in components.items():
            w = weights[k]
            if not avail and policy == MissingSignalPolicy.REDISTRIBUTE_ACTIVE_WEIGHTS.value:
                contributions[k] = 0.0
            else:
                contributions[k] = round(w * val, 4)
                weighted_sum += w * val

        if policy == MissingSignalPolicy.REDISTRIBUTE_ACTIVE_WEIGHTS.value and active_weight_sum > 0:
            final_risk = float(np.clip(weighted_sum / active_weight_sum, 0.0, 1.0))
        else:
            final_risk = float(np.clip(weighted_sum, 0.0, 1.0))

        # Priority Level Assignment
        high_th = float(self.config["priority_thresholds"]["high"])
        med_th = float(self.config["priority_thresholds"]["medium"])
        if final_risk >= high_th:
            priority_lvl = PriorityLevel.HIGH.value
        elif final_risk >= med_th:
            priority_lvl = PriorityLevel.MEDIUM.value
        else:
            priority_lvl = PriorityLevel.LOW.value

        # Collect linked evidence IDs
        linked_ev = []
        for ek in ["supporting_evidence", "contradicting_evidence", "contextual_evidence"]:
            ev_list = finding.get(ek, [])
            if isinstance(ev_list, list):
                linked_ev.extend([str(x) for x in ev_list if not str(x).startswith("ref:fnd:")])
        linked_ev = sorted(list(set(linked_ev)))

        # Explanation formulation
        reasons_summary = ", ".join(reason_codes) if reason_codes else "BASELINE_MONITORING"
        explanation = (
            f"Finding {finding_id} assigned triage risk score {final_risk:.4f} (Priority: {priority_lvl}). "
            f"Component drivers: raw anomaly={raw_anomaly_val:.2f}, graph topology={graph_sig_val:.2f} ({neighbor_count} connected peers), "
            f"fusion confidence={fusion_val:.2f}, recency/clustering={recency_val:.2f}. "
            f"Active signals: [{reasons_summary}]. "
            "Note: Triage score establishes investigative prioritization order and does not infer guilt, fraudulent intent, or legal culpability."
        )
        if requires_human_review or conflict_status in ("CONFLICTED", "ABSTENTION_REQUIRED"):
            explanation += " Evidential conflict detected between independent reporting domains; human review is required prior to escalation."

        return FindingRiskEvaluation(
            finding_id=finding_id,
            case_id=case_id,
            entity_id=entity_id,
            risk_score=final_risk,
            priority_level=priority_lvl,
            priority_rank=1,  # Populated during queue ranking
            anomaly_component={
                "raw_value": round(raw_anomaly_val, 4) if anomaly_available else None,
                "weight": weights["anomaly"],
                "weighted_contribution": contributions["anomaly"],
                "is_available": anomaly_available,
            },
            graph_significance_component={
                "raw_value": round(graph_sig_val, 4) if graph_available else None,
                "neighbor_count": neighbor_count,
                "weight": weights["graph_significance"],
                "weighted_contribution": contributions["graph_significance"],
                "is_available": graph_available,
            },
            fusion_component={
                "raw_value": round(fusion_val, 4) if fusion_available else None,
                "weight": weights["fusion_confidence"],
                "weighted_contribution": contributions["fusion_confidence"],
                "is_available": fusion_available,
            },
            recency_clustering_component={
                "raw_value": round(recency_val, 4),
                "cluster_size": cluster_size,
                "weight": weights["recency_clustering"],
                "weighted_contribution": contributions["recency_clustering"],
                "is_available": True,
            },
            contributing_finding_ids=[finding_id],
            linked_evidence_ids=linked_ev,
            conflict_status=conflict_status,
            requires_human_review=requires_human_review,
            missing_signals=missing_signals,
            missing_signal_policy=policy,
            reason_codes=reason_codes,
            explanation=explanation,
        )

    def rank_findings(
        self,
        finding_ids: Optional[List[str]] = None,
        case_id: Optional[str] = None
    ) -> List[FindingRiskEvaluation]:
        """
        Generates an input-order-independent, deterministically ranked triage queue.
        Sorting: risk_score descending, then finding_id ascending (for strict tie-breaking).
        """
        # Resolve target finding IDs
        if finding_ids is None:
            if case_id and hasattr(self.backend, "cases") and case_id in self.backend.cases:
                finding_ids = sorted(list(self.backend.cases[case_id].finding_ids))
            else:
                finding_ids = sorted(list(self.backend.findings_by_id.keys()))

        evaluations: List[FindingRiskEvaluation] = []
        for fid in finding_ids:
            try:
                ev = self.evaluate_finding(fid, case_id=case_id)
                evaluations.append(ev)
            except Exception:
                continue

        # Deterministic sort: risk_score DESC, finding_id ASC
        evaluations.sort(key=lambda x: (-x.risk_score, x.finding_id))

        # Assign priority ranks (1-indexed)
        for idx, item in enumerate(evaluations, 1):
            item.priority_rank = idx

        return evaluations
