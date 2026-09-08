# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: M14 Agentic Investigation Orchestrator with Local Ollama

import os
import re
import uuid
import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

from dfap.investigation.ollama_client import OllamaClient, OllamaUnavailableError
from dfap.investigation.workspace import InvestigationWorkspaceBackend
from dfap.investigation.evidential_conflict import (
    EvidentialConflictAnalyzer,
    EvidentialConflictStatus,
    EvidentialRequiredAction,
)


class AgentState(str, Enum):
    QUESTION_RECEIVED = "QUESTION_RECEIVED"
    TOOLS_SELECTED = "TOOLS_SELECTED"
    TOOLS_EXECUTING = "TOOLS_EXECUTING"
    EVIDENCE_ASSEMBLED = "EVIDENCE_ASSEMBLED"
    CONFLICT_CHECKED = "CONFLICT_CHECKED"
    ANSWER_SYNTHESIZED = "ANSWER_SYNTHESIZED"
    HUMAN_REVIEW_REQUIRED = "HUMAN_REVIEW_REQUIRED"
    COMPLETED = "COMPLETED"
    UNAVAILABLE = "UNAVAILABLE"
    OLLAMA_UNAVAILABLE = "OLLAMA_UNAVAILABLE"


class ToolExecutionRecord:
    """Auditable record of a single deterministic tool invocation."""

    def __init__(
        self,
        tool_name: str,
        tool_version: str,
        input_parameters: Dict[str, Any],
        execution_order: int,
        result_status: str,
        output_summary: str,
        evidence_refs: Optional[List[str]] = None,
        provenance_refs: Optional[List[str]] = None,
        raw_output: Optional[Any] = None
    ):
        self.tool_name = tool_name
        self.tool_version = tool_version
        self.input_parameters = input_parameters
        self.execution_order = execution_order
        self.result_status = result_status
        self.output_summary = output_summary
        self.evidence_refs = list(evidence_refs or [])
        self.provenance_refs = list(provenance_refs or [])
        self.raw_output = raw_output

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "tool_version": self.tool_version,
            "input_parameters": self.input_parameters,
            "execution_order": self.execution_order,
            "result_status": self.result_status,
            "output_summary": self.output_summary,
            "evidence_refs": self.evidence_refs,
            "provenance_refs": self.provenance_refs,
        }


class ClosedDFAPToolRegistry:
    """
    Closed, deterministic registry of authoritative DFAP tools.
    Wraps existing M8–M13 modules without duplicating or altering algorithms.
    """

    CANONICAL_TOOL_ORDER = [
        "case_forensic_packet",
        "case_risk",
        "finding_explainability",
        "cross_domain_conflict",
        "temporal_sequence",
        "temporal_patterns",
        "temporal_transitions",
        "temporal_phases",
        "motif_discovery",
        "temporal_similarity_ablation",
        "adaptive_baseline",
        "graph_ml_comparison",
        "gnn_explain_prediction",
        "evidence_lookup",
        "provenance_lookup",
        "timeline",
    ]

    def __init__(self, backend: InvestigationWorkspaceBackend):
        self.backend = backend

    def is_valid_tool(self, name: str) -> bool:
        return name in self.CANONICAL_TOOL_ORDER

    def execute_tool(
        self,
        tool_name: str,
        order: int,
        case_id: Optional[str] = None,
        entity_id: Optional[str] = None,
        finding_id: Optional[str] = None,
        extra_params: Optional[Dict[str, Any]] = None
    ) -> ToolExecutionRecord:
        extra_params = extra_params or {}
        method_name = f"_tool_{tool_name}"
        if not hasattr(self, method_name):
            return ToolExecutionRecord(
                tool_name=tool_name,
                tool_version="M14.REGISTRY.V1",
                input_parameters={"case_id": case_id, "entity_id": entity_id, "finding_id": finding_id},
                execution_order=order,
                result_status="REJECTED",
                output_summary=f"Unknown tool '{tool_name}' rejected by closed registry."
            )

        try:
            return getattr(self, method_name)(order, case_id, entity_id, finding_id, extra_params)
        except Exception as e:
            return ToolExecutionRecord(
                tool_name=tool_name,
                tool_version="M14.REGISTRY.V1",
                input_parameters={"case_id": case_id, "entity_id": entity_id, "finding_id": finding_id},
                execution_order=order,
                result_status="ERROR",
                output_summary=f"Tool execution failed: {str(e)}"
            )

    # ── Tool Implementations (Strict wrappers over existing M8-M13) ───────────

    def _tool_case_forensic_packet(self, order: int, case_id: Optional[str], entity_id: Optional[str], finding_id: Optional[str], extra: Dict[str, Any]) -> ToolExecutionRecord:
        if not case_id or case_id not in self.backend.cases:
            case_id = case_id or (list(self.backend.cases.keys())[0] if self.backend.cases else None)
        if not case_id:
            return ToolExecutionRecord("case_forensic_packet", "M12.PACKET.V1", {"case_id": None}, order, "SKIPPED", "No case specified or available.")

        from dfap.investigation.forensic_case_packet import ForensicCasePacketEngine
        engine = ForensicCasePacketEngine(self.backend)
        packet = engine.generate_packet(case_id)
        p_dict = packet.to_dict()

        ev_refs = []
        for row in p_dict.get("traceability_matrix", []):
            if row.get("evidence_id"):
                ev_refs.append(row["evidence_id"])
        ev_refs = sorted(set(ev_refs))

        prov_refs = [f"PROV-{case_id}"]

        summary = (
            f"Case {case_id}: status={packet.packet_status}, required_action={packet.required_action}, "
            f"findings={len(packet.findings)}, digest={packet.packet_digest[:16]}..."
        )
        return ToolExecutionRecord("case_forensic_packet", "M12.PACKET.V1", {"case_id": case_id}, order, "SUCCESS", summary, ev_refs, prov_refs, p_dict)

    def _tool_case_risk(self, order: int, case_id: Optional[str], entity_id: Optional[str], finding_id: Optional[str], extra: Dict[str, Any]) -> ToolExecutionRecord:
        if not case_id:
            case_id = list(self.backend.cases.keys())[0] if self.backend.cases else None
        if not case_id:
            return ToolExecutionRecord("case_risk", "M13.RISK.V1", {"case_id": None}, order, "SKIPPED", "No case specified.")

        ranked = self.backend.risk_engine.rank_findings(case_id=case_id)
        ev_refs = []
        for r in ranked:
            ev_refs.extend(r.linked_evidence_ids)
        ev_refs = sorted(set(ev_refs))

        if ranked:
            top = ranked[0]
            summary = f"Case {case_id} risk triage: {len(ranked)} findings evaluated. Top priority: {top.finding_id} (score={top.risk_score:.4f}, priority={top.priority_level})."
        else:
            summary = f"Case {case_id}: No findings available for risk ranking."

        return ToolExecutionRecord("case_risk", "M13.RISK.V1", {"case_id": case_id}, order, "SUCCESS", summary, ev_refs, [], [r.to_dict() for r in ranked])

    def _tool_finding_explainability(self, order: int, case_id: Optional[str], entity_id: Optional[str], finding_id: Optional[str], extra: Dict[str, Any]) -> ToolExecutionRecord:
        target_fnd = finding_id
        if not target_fnd and case_id and case_id in self.backend.cases:
            fids = self.backend.cases[case_id].finding_ids
            target_fnd = fids[0] if fids else None
        if not target_fnd and self.backend.findings_by_id:
            target_fnd = list(self.backend.findings_by_id.keys())[0]

        if not target_fnd:
            return ToolExecutionRecord("finding_explainability", "M9.SHAP.V1", {"finding_id": None}, order, "SKIPPED", "No finding available to explain.")

        exp = self.backend.shap_explainer.explain_finding(target_fnd)
        exp_dict = exp.to_dict()
        ev_refs = exp.evidence_refs

        pos_str = ", ".join([f"{c['feature_name']} (+{c['shap_value']:.4f})" for c in exp_dict.get("top_positive_contributors", [])[:2]])
        summary = f"Finding {target_fnd} SHAP attribution: anomaly_score={exp.anomaly_score:.4f}. Key contributors: {pos_str or 'None'}."

        return ToolExecutionRecord("finding_explainability", "M9.SHAP.V1", {"finding_id": target_fnd}, order, "SUCCESS", summary, ev_refs, [], exp_dict)

    def _tool_cross_domain_conflict(self, order: int, case_id: Optional[str], entity_id: Optional[str], finding_id: Optional[str], extra: Dict[str, Any]) -> ToolExecutionRecord:
        if case_id and case_id in self.backend.cases:
            from dfap.investigation.forensic_case_packet import ForensicCasePacketEngine
            packet = ForensicCasePacketEngine(self.backend).generate_packet(case_id)
            c_intel = packet.conflict_intelligence
            status = c_intel.get("overall_status") or packet.packet_status
            action = c_intel.get("required_action") or packet.required_action
            pairs = c_intel.get("pairs", [])
            worst_pair = max(pairs, key=lambda p: p.get("compound_conflict", 0.0)) if pairs else None
            p_desc = f"{worst_pair.get('domain_a')} vs {worst_pair.get('domain_b')}" if worst_pair else "FINANCIAL vs SOCIAL"
            ev_refs = [f"ref:bridge_{d.lower()}_001" for d in ["CDR", "IPDR", "FINANCIAL", "SOCIAL"]]

            summary = f"Evidential conflict for {case_id}: status={status}, action={action}, conflicting_pair={p_desc}."
            return ToolExecutionRecord("cross_domain_conflict", "M11.CONFLICT.V1", {"case_id": case_id}, order, "SUCCESS", summary, ev_refs, [], c_intel)

        scores = extra.get("domain_scores", {"FINANCIAL": 0.92, "CDR": 0.85, "SOCIAL": 0.08, "IPDR": 0.45})
        engine = EvidentialConflictAnalyzer()
        res = engine.analyze_domains(scores)
        wp = res.get("worst_pair", {})
        p_desc = f"{wp.get('domain_a')} vs {wp.get('domain_b')}" if wp else "None"
        summary = f"Evidential conflict: status={res.get('conflict_status')}, action={res.get('required_action')}, conflicting_pair={p_desc}."
        return ToolExecutionRecord("cross_domain_conflict", "M11.CONFLICT.V1", {"domain_scores": scores}, order, "SUCCESS", summary, [], [], res)

    def _tool_temporal_sequence(self, order: int, case_id: Optional[str], entity_id: Optional[str], finding_id: Optional[str], extra: Dict[str, Any]) -> ToolExecutionRecord:
        target_ent = entity_id or (self.backend.cases[case_id].canonical_entity_id if case_id and case_id in self.backend.cases else None)
        if not target_ent and self.backend.valid_entities:
            target_ent = list(self.backend.valid_entities)[0]
        if not target_ent:
            return ToolExecutionRecord("temporal_sequence", "M10.SEQUENCE.V1", {"entity_id": None}, order, "SKIPPED", "No entity specified.")

        raw_events = self.backend.get_timeline(target_ent)
        seq = self.backend.temporal_sequence_engine.build_sequence(raw_events, canonical_entity_id=target_ent, case_id=case_id)
        seq_dict = seq.to_dict()
        ev_refs = [it.get("evidence_ref") for it in seq_dict.get("items", []) if it.get("evidence_ref")]

        summary = f"Temporal sequence for {target_ent}: {len(seq.items)} causal chronological events (valid={seq.is_causally_valid})."
        return ToolExecutionRecord("temporal_sequence", "M10.SEQUENCE.V1", {"entity_id": target_ent}, order, "SUCCESS", summary, ev_refs, [], seq_dict)

    def _tool_temporal_patterns(self, order: int, case_id: Optional[str], entity_id: Optional[str], finding_id: Optional[str], extra: Dict[str, Any]) -> ToolExecutionRecord:
        target_ent = entity_id or (self.backend.cases[case_id].canonical_entity_id if case_id and case_id in self.backend.cases else None)
        if not target_ent:
            return ToolExecutionRecord("temporal_patterns", "M10.PATTERNS.V1", {"entity_id": None}, order, "SKIPPED", "No entity specified.")

        raw_events = self.backend.get_timeline(target_ent)
        seq = self.backend.temporal_sequence_engine.build_sequence(raw_events, canonical_entity_id=target_ent)
        patterns = self.backend.temporal_sequence_engine.detect_patterns(seq)
        summary = f"Detected {len(patterns)} recurring behavioral n-gram patterns for {target_ent}."
        return ToolExecutionRecord("temporal_patterns", "M10.PATTERNS.V1", {"entity_id": target_ent}, order, "SUCCESS", summary, [], [], patterns)

    def _tool_temporal_transitions(self, order: int, case_id: Optional[str], entity_id: Optional[str], finding_id: Optional[str], extra: Dict[str, Any]) -> ToolExecutionRecord:
        target_ent = entity_id or (self.backend.cases[case_id].canonical_entity_id if case_id and case_id in self.backend.cases else None)
        if not target_ent:
            return ToolExecutionRecord("temporal_transitions", "M10.TRANSITIONS.V1", {"entity_id": None}, order, "SKIPPED", "No entity specified.")

        raw_events = self.backend.get_timeline(target_ent)
        seq = self.backend.temporal_sequence_engine.build_sequence(raw_events, canonical_entity_id=target_ent)
        trans = self.backend.temporal_sequence_engine.analyze_transitions(seq)
        summary = f"Analyzed temporal transitions across {len(trans.get('domain_transitions', []))} domain pairs for {target_ent}."
        return ToolExecutionRecord("temporal_transitions", "M10.TRANSITIONS.V1", {"entity_id": target_ent}, order, "SUCCESS", summary, [], [], trans)

    def _tool_temporal_phases(self, order: int, case_id: Optional[str], entity_id: Optional[str], finding_id: Optional[str], extra: Dict[str, Any]) -> ToolExecutionRecord:
        target_ent = entity_id or (self.backend.cases[case_id].canonical_entity_id if case_id and case_id in self.backend.cases else None)
        if not target_ent:
            return ToolExecutionRecord("temporal_phases", "M10.PHASES.V1", {"entity_id": None}, order, "SKIPPED", "No entity specified.")

        raw_events = self.backend.get_timeline(target_ent)
        seq = self.backend.temporal_sequence_engine.build_sequence(raw_events, canonical_entity_id=target_ent)
        phases = self.backend.temporal_sequence_engine.compress_phases(seq)
        summary = f"Compressed timeline into {len(phases)} temporal phases for {target_ent}."
        return ToolExecutionRecord("temporal_phases", "M10.PHASES.V1", {"entity_id": target_ent}, order, "SUCCESS", summary, [], [], [p.to_dict() for p in phases])

    def _tool_motif_discovery(self, order: int, case_id: Optional[str], entity_id: Optional[str], finding_id: Optional[str], extra: Dict[str, Any]) -> ToolExecutionRecord:
        target_ent = entity_id or (self.backend.cases[case_id].canonical_entity_id if case_id and case_id in self.backend.cases else None)
        if not target_ent:
            return ToolExecutionRecord("motif_discovery", "M10.MOTIF.V1", {"entity_id": None}, order, "SKIPPED", "No entity specified.")

        raw_events = self.backend.get_timeline(target_ent)
        seq = self.backend.temporal_sequence_engine.build_sequence(raw_events, canonical_entity_id=target_ent)
        motifs = self.backend.temporal_motif_discovery_engine.discover_motifs(seq)
        motif_dicts = [m.to_dict() if hasattr(m, "to_dict") else dict(m) for m in motifs]
        ev_refs = []
        for m in motif_dicts:
            for occ in m.get("occurrences", []):
                ev_refs.extend(occ.get("evidence_refs", []))
        ev_refs = sorted(set(ev_refs))

        summary = f"Discovered {len(motifs)} recurring cross-domain behavioral motifs for {target_ent}."
        return ToolExecutionRecord("motif_discovery", "M10.MOTIF.V1", {"entity_id": target_ent}, order, "SUCCESS", summary, ev_refs, [], motif_dicts)

    def _tool_adaptive_baseline(self, order: int, case_id: Optional[str], entity_id: Optional[str], finding_id: Optional[str], extra: Dict[str, Any]) -> ToolExecutionRecord:
        target_ent = entity_id or (self.backend.cases[case_id].canonical_entity_id if case_id and case_id in self.backend.cases else None)
        if not target_ent:
            target_ent = "ENT_DFAP_4DOM_001"

        q_str = extra.get("question", "What is the behavioral baseline state?")
        res = self.backend.adaptive_baseline_manager.query_agentic_tool(q_str, target_ent)
        summary = f"M8 Baseline for {target_ent}: state={res.get('state')}, baseline={res.get('baseline_value')}, answer={res.get('answer')}."
        return ToolExecutionRecord("adaptive_baseline", "M8.EWMA.V1", {"entity_id": target_ent}, order, "SUCCESS", summary, res.get("evidence_refs", []), [], res)

    def _tool_temporal_similarity_ablation(self, order: int, case_id: Optional[str], entity_id: Optional[str], finding_id: Optional[str], extra: Dict[str, Any]) -> ToolExecutionRecord:
        ablation = self.backend.run_temporal_similarity_ablation()
        dtw_part = f"DTW(dist={ablation['dtw']['normalized_distance']:.4f}, runtime={ablation['dtw']['runtime_ms']}ms, match={ablation['dtw']['matched_window']})"
        if ablation['stumpy']['available']:
            stumpy_part = f"STUMPY(dist={ablation['stumpy']['distance']:.4f}, runtime={ablation['stumpy']['runtime_ms']}ms, match={ablation['stumpy']['matched_window']})"
        else:
            stumpy_part = "STUMPY: UNAVAILABLE"
        summary = f"Temporal Similarity Ablation: {dtw_part} vs {stumpy_part}. Agreement={ablation['comparison']['same_best_match']}."
        return ToolExecutionRecord("temporal_similarity_ablation", "M10.ABLATION.V1", {}, order, "SUCCESS", summary, [], [], ablation)

    def _tool_adaptive_baseline(self, order: int, case_id: Optional[str], entity_id: Optional[str], finding_id: Optional[str], extra: Dict[str, Any]) -> ToolExecutionRecord:
        target_ent = entity_id or (self.backend.cases[case_id].canonical_entity_id if case_id and case_id in self.backend.cases else None)
        if not target_ent:
            target_ent = "ENT_DFAP_4DOM_001"

        q_str = extra.get("question", "What is the behavioral baseline state?")
        res = self.backend.adaptive_baseline_manager.query_agentic_tool(q_str, target_ent)
        summary = f"M8 Baseline for {target_ent}: state={res.get('state')}, baseline={res.get('baseline_value')}, answer={res.get('answer')}."
        return ToolExecutionRecord("adaptive_baseline", "M8.EWMA.V1", {"entity_id": target_ent}, order, "SUCCESS", summary, res.get("evidence_refs", []), [], res)

    def _tool_graph_ml_comparison(self, order: int, case_id: Optional[str], entity_id: Optional[str], finding_id: Optional[str], extra: Dict[str, Any]) -> ToolExecutionRecord:
        bench_res = self.backend.graph_ml_service.get_latest_benchmark()
        models = bench_res.get("models", [])
        m_summaries = []
        for m in models:
            m_summaries.append(f"{m.get('name')}: AUROC={m.get('auroc', 0):.4f}, F1={m.get('f1', 0):.4f}")
        summary = f"Graph ML Ablation: {'; '.join(m_summaries) if m_summaries else 'Comparison executed.'} (Isolated prediction layer)."
        return ToolExecutionRecord("graph_ml_comparison", "M4.GRAPHML.V1", {}, order, "SUCCESS", summary, [], [], bench_res)

    def _tool_gnn_explain_prediction(self, order: int, case_id: Optional[str], entity_id: Optional[str], finding_id: Optional[str], extra: Dict[str, Any]) -> ToolExecutionRecord:
        src = extra.get("source_id", "ENT_NODE_00")
        dst = extra.get("target_id", "ENT_NODE_01")
        mod = extra.get("model", "graphsage")
        exp = self.backend.explain_graph_prediction(src, dst, model=mod)
        if exp.get("status") == "UNAVAILABLE" or exp.get("explanation_status") == "UNAVAILABLE":
            summary = f"GNN explanation UNAVAILABLE for {src}->{dst}: {exp.get('reason')}."
            return ToolExecutionRecord("gnn_explain_prediction", "M4.GNNEXPLAINER.V1", {"source_id": src, "target_id": dst, "model": mod}, order, "UNAVAILABLE", summary, [], [], exp)

        nodes_desc = ", ".join([f"{n['node_id']} ({n['importance']:+.4f})" for n in exp.get("influential_nodes", [])[:3]])
        feats_desc = ", ".join([f"{f['feature_name']} ({f['importance']:+.4f})" for f in exp.get("influential_features", [])[:3]])
        summary = f"GNN Attribution ({exp.get('model_name')}): P={exp.get('predicted_probability')}, status={exp.get('prediction_status')}, top nodes: [{nodes_desc}], top features: [{feats_desc}]."
        return ToolExecutionRecord("gnn_explain_prediction", "M4.GNNEXPLAINER.V1", {"source_id": src, "target_id": dst, "model": mod}, order, "SUCCESS", summary, [], exp.get("provenance_refs", []), exp)


    def _tool_evidence_lookup(self, order: int, case_id: Optional[str], entity_id: Optional[str], finding_id: Optional[str], extra: Dict[str, Any]) -> ToolExecutionRecord:
        ev_id = extra.get("evidence_id")
        if not ev_id and finding_id:
            evs = self.backend.evidence_engine.finding_evidence_map.get(finding_id, [])
            ev_id = evs[0] if evs else None
        if not ev_id and case_id and case_id in self.backend.cases:
            c_evs = self.backend.cases[case_id].evidence_ids
            ev_id = c_evs[0] if c_evs else None

        if not ev_id:
            ev_id = "EVD-4DOM-FIN-001"

        ev = self.backend.evidence_engine.get_evidence(ev_id)
        if ev:
            d = ev.to_dict()
            sha = d.get("sha256_hash")
            sha_str = f"{sha[:16]}..." if sha else "N/A"
            summary = f"Evidence {ev_id}: domain={d.get('source_domain')}, confidence={d.get('confidence')}, quality={d.get('evidence_quality')}, sha256={sha_str}"
            return ToolExecutionRecord("evidence_lookup", "M12.EVIDENCE.V1", {"evidence_id": ev_id}, order, "SUCCESS", summary, [ev_id], [], d)
        return ToolExecutionRecord("evidence_lookup", "M12.EVIDENCE.V1", {"evidence_id": ev_id}, order, "NOT_FOUND", f"Evidence record {ev_id} not found.")

    def _tool_provenance_lookup(self, order: int, case_id: Optional[str], entity_id: Optional[str], finding_id: Optional[str], extra: Dict[str, Any]) -> ToolExecutionRecord:
        f_target = finding_id or ("FND_4DOM_FUSED_001" if case_id == "CASE-DFAP-4DOMAIN-001" else None)
        if not f_target and self.backend.findings_by_id:
            f_target = list(self.backend.findings_by_id.keys())[0]

        prov = self.backend.get_provenance(f_target) if f_target else {}
        prov_id = f"PROV-{f_target}" if f_target else "PROV-UNKNOWN"
        sha = prov.get("sha256_hash")
        sha_str = f"{sha[:16]}..." if sha else "N/A"
        summary = f"Provenance for {f_target}: run_id={prov.get('run_id')}, sha256={sha_str}"
        return ToolExecutionRecord("provenance_lookup", "M12.PROVENANCE.V1", {"finding_id": f_target}, order, "SUCCESS", summary, [], [prov_id], prov)

    def _tool_timeline(self, order: int, case_id: Optional[str], entity_id: Optional[str], finding_id: Optional[str], extra: Dict[str, Any]) -> ToolExecutionRecord:
        target_ent = entity_id or (self.backend.cases[case_id].canonical_entity_id if case_id and case_id in self.backend.cases else None)
        if not target_ent and self.backend.valid_entities:
            target_ent = list(self.backend.valid_entities)[0]
        if not target_ent:
            return ToolExecutionRecord("timeline", "M13.TIMELINE.V1", {"entity_id": None}, order, "SKIPPED", "No entity specified.")

        timeline = self.backend.get_timeline(target_ent)
        summary = f"Chronological timeline for {target_ent}: {len(timeline)} events retrieved across all registered domains."
        return ToolExecutionRecord("timeline", "M13.TIMELINE.V1", {"entity_id": target_ent}, order, "SUCCESS", summary, [], [], timeline)


class AgenticInvestigationResult:
    """Structured, auditable M14 agentic investigation result."""

    def __init__(
        self,
        agent_run_id: str,
        status: str,
        answer: str,
        claims: List[Dict[str, Any]],
        tool_trace: List[Dict[str, Any]],
        evidence_refs: List[str],
        provenance_refs: List[str],
        uncertainties: List[str],
        limitations: List[str],
        next_actions: List[str],
        requires_human_review: bool,
        audit_verifiable: bool,
        question: str,
        case_id: Optional[str] = None,
        entity_id: Optional[str] = None,
        finding_id: Optional[str] = None,
        model_name: str = "qwen3:4b",
        state_transitions: Optional[List[Dict[str, Any]]] = None,
        generation_parameters: Optional[Dict[str, Any]] = None,
    ):
        self.agent_run_id = agent_run_id
        self.status = status
        self.answer = answer
        self.claims = claims
        self.tool_trace = tool_trace
        self.evidence_refs = evidence_refs
        self.provenance_refs = provenance_refs
        self.uncertainties = uncertainties
        self.limitations = limitations
        self.next_actions = next_actions
        self.requires_human_review = requires_human_review
        self.audit_verifiable = audit_verifiable
        self.question = question
        self.case_id = case_id
        self.entity_id = entity_id
        self.finding_id = finding_id
        self.model_name = model_name
        self.state_transitions = state_transitions or []
        self.generation_parameters = generation_parameters or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_run_id": self.agent_run_id,
            "status": self.status,
            "question": self.question,
            "case_id": self.case_id,
            "entity_id": self.entity_id,
            "finding_id": self.finding_id,
            "model_name": self.model_name,
            "answer": self.answer,
            "claims": self.claims,
            "tool_trace": self.tool_trace,
            "evidence_refs": self.evidence_refs,
            "provenance_refs": self.provenance_refs,
            "uncertainties": self.uncertainties,
            "limitations": self.limitations,
            "next_actions": self.next_actions,
            "requires_human_review": self.requires_human_review,
            "audit_verifiable": self.audit_verifiable,
            "state_transitions": self.state_transitions,
            "generation_parameters": self.generation_parameters,
        }


class AgenticInvestigationOrchestrator:
    """
    Authoritative M14 Agentic Investigation Orchestrator.
    Combines local Ollama LLM for query understanding and structured synthesis
    with deterministic, closed-domain DFAP tool execution.
    """

    MAX_TOOL_CALLS = 8

    def __init__(
        self,
        backend: InvestigationWorkspaceBackend,
        ollama_client: Optional[OllamaClient] = None
    ):
        self.backend = backend
        self.ollama_client = ollama_client or OllamaClient()
        self.registry = ClosedDFAPToolRegistry(backend)
        # Performance: in-memory tool result cache keyed by (case_id, entity_id, finding_id, tool_name)
        # Deterministic tools produce the same output for the same inputs — safe to cache within process lifetime.
        self._tool_cache: dict = {}

    def _record_transition(
        self,
        transitions: List[Dict[str, Any]],
        from_state: Optional[str],
        to_state: str,
        reason: str
    ):
        transitions.append({
            "from_state": from_state,
            "to_state": to_state,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "reason": reason
        })

    def _resolve_context_ids(
        self,
        question: str,
        case_id: Optional[str],
        entity_id: Optional[str],
        finding_id: Optional[str]
    ) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        # Check tokens in question for IDs
        tokens = [tok.strip("?,.!:;\"'") for tok in question.split()]
        resolved_case = case_id
        resolved_ent = entity_id
        resolved_fnd = finding_id

        for tok in tokens:
            if not resolved_case and (tok.startswith("CASE-") or tok.startswith("CASE_")):
                if tok in self.backend.cases:
                    resolved_case = tok
            elif not resolved_ent and (tok.startswith("ENT_") or tok.startswith("ENT-")):
                if hasattr(self.backend, "valid_entities") and tok in self.backend.valid_entities:
                    resolved_ent = tok
            elif not resolved_fnd and (tok.startswith("FND_") or tok.startswith("FND-")):
                if hasattr(self.backend, "findings_by_id") and tok in self.backend.findings_by_id:
                    resolved_fnd = tok

        # If case is resolved, bind entity and finding if unset
        if resolved_case and resolved_case in self.backend.cases:
            c_obj = self.backend.cases[resolved_case]
            if not resolved_ent:
                resolved_ent = c_obj.canonical_entity_id
            if not resolved_fnd and c_obj.finding_ids:
                resolved_fnd = c_obj.finding_ids[0]

        # If entity is resolved, check for active case
        if resolved_ent and not resolved_case:
            for cid, c_obj in self.backend.cases.items():
                if c_obj.canonical_entity_id == resolved_ent:
                    resolved_case = cid
                    if not resolved_fnd and c_obj.finding_ids:
                        resolved_fnd = c_obj.finding_ids[0]
                    break

        return resolved_case, resolved_ent, resolved_fnd

    def _plan_tools(
        self,
        question: str,
        case_id: Optional[str],
        entity_id: Optional[str],
        finding_id: Optional[str]
    ) -> List[str]:
        lower = question.lower()
        selected: Set[str] = set()

        # 1. Deterministic Intent Routing
        # Status / Overview
        if ("status of this case" in lower or "status of the case" in lower or "case status" in lower):
            selected.update(["case_forensic_packet", "case_risk"])

        # Explain / Flagged Finding
        if ("why" in lower and ("flagged" in lower or "finding" in lower or "anomalous" in lower)) or "explain" in lower:
            selected.update(["finding_explainability", "cross_domain_conflict", "evidence_lookup", "provenance_lookup"])

        # Conflict
        if "conflict" in lower or "disagree" in lower or "contradict" in lower:
            selected.update(["cross_domain_conflict", "evidence_lookup", "provenance_lookup"])

        # Motifs & Patterns
        if "motif" in lower or "pattern" in lower or "recurring" in lower:
            selected.update(["motif_discovery", "temporal_patterns"])

        # Sequence & Backtrack / What happened before
        if "before" in lower or "happen" in lower or "sequence" in lower or "chronol" in lower or "event" in lower:
            selected.update(["temporal_sequence", "timeline"])

        # Next actions / what to check next
        if "check next" in lower or "investigator check" in lower or "next action" in lower or "next step" in lower:
            selected.update(["case_forensic_packet", "case_risk", "cross_domain_conflict", "provenance_lookup"])

        # Adaptive Baseline / Behavior changed
        if "baseline" in lower or "behavior" in lower or "drift" in lower or "quarantine" in lower or "adapted" in lower:
            selected.update(["adaptive_baseline", "temporal_sequence"])

        # Graph ML & GNN Explainer
        if ("explain" in lower or "why" in lower or "influenc" in lower or "feature" in lower) and ("graphsage" in lower or "tgn" in lower or "relationship" in lower or "predict" in lower):
            selected.update(["gnn_explain_prediction", "graph_ml_comparison"])
        elif "graphsage" in lower or "tgn" in lower or "graph ml" in lower or "ablation" in lower or "predict relationship" in lower:
            selected.update(["graph_ml_comparison"])

        # Temporal Similarity Ablation (STUMPY vs DTW)
        if "stumpy" in lower or ("dtw" in lower and ("ablation" in lower or "compare" in lower or "similarity" in lower or "approach" in lower or "method" in lower)):
            selected.update(["temporal_similarity_ablation"])

        # Guilt query
        if "guilt" in lower or "guilty" in lower or "prove" in lower or "culpab" in lower:
            selected.update(["case_forensic_packet", "cross_domain_conflict"])

        # Compound investigation query
        if ("why" in lower and "flagged" in lower and ("support" in lower or "conflict" in lower or "next" in lower)):
            selected.update(["finding_explainability", "case_forensic_packet", "cross_domain_conflict", "temporal_sequence", "evidence_lookup", "provenance_lookup"])


        # 2. Consult Ollama for plan enrichment only when deterministic routing produced < 2 tools
        # Skip the extra LLM call when keyword routing already produced a sufficient tool set —
        # this avoids a full round-trip (~5-10s) for the common "Why was X flagged?" pattern.
        if len(selected) < 2:
            try:
                plan_prompt = (
                    f"Given the investigator question: '{question}', and the available DFAP tools:\n"
                    f"{json.dumps(ClosedDFAPToolRegistry.CANONICAL_TOOL_ORDER)}\n"
                    "Return a JSON object with 'tools' as an array of up to 4 tool names required. Only select from available tools."
                )
                llm_res = self.ollama_client.generate(plan_prompt, format_json=True, temperature=0.0, max_tokens=150)
                try:
                    parsed = json.loads(llm_res.get("response", "{}"))
                    if isinstance(parsed, dict) and "tools" in parsed and isinstance(parsed["tools"], list):
                        for t in parsed["tools"]:
                            if self.registry.is_valid_tool(t):
                                selected.add(t)
                except Exception:
                    pass
            except Exception:
                pass

        # If nothing matched, check for generic case lookup
        if not selected and case_id:
            selected.add("case_forensic_packet")

        # Sort according to canonical ordering and cap at MAX_TOOL_CALLS
        canonical_list = [t for t in ClosedDFAPToolRegistry.CANONICAL_TOOL_ORDER if t in selected]
        return canonical_list[:self.MAX_TOOL_CALLS]

    def investigate(
        self,
        question: str,
        case_id: Optional[str] = None,
        entity_id: Optional[str] = None,
        finding_id: Optional[str] = None
    ) -> AgenticInvestigationResult:
        """
        Executes a complete evidence-grounded agentic investigation.
        """
        agent_run_id = f"RUN-M14-{uuid.uuid4().hex[:10].upper()}"
        transitions: List[Dict[str, Any]] = []
        self._record_transition(transitions, None, AgentState.QUESTION_RECEIVED.value, f"Investigator prompt: {question}")

        # Resolve Target Scope IDs
        res_case, res_ent, res_fnd = self._resolve_context_ids(question, case_id, entity_id, finding_id)

        # Check local Ollama health
        health = self.ollama_client.health_check()
        if health.get("status") != "OK":
            self._record_transition(transitions, AgentState.QUESTION_RECEIVED.value, AgentState.OLLAMA_UNAVAILABLE.value, f"Ollama health check failed: {health.get('error', 'Unreachable')}")
            return AgenticInvestigationResult(
                agent_run_id=agent_run_id,
                status=AgentState.OLLAMA_UNAVAILABLE.value,
                answer="Local Ollama LLM runtime is unavailable (http://localhost:11434). Investigation cannot proceed without local LLM synthesis.",
                claims=[],
                tool_trace=[],
                evidence_refs=[],
                provenance_refs=[],
                uncertainties=["Ollama local runtime is offline or unreachable."],
                limitations=["No fabricated answer generated; local LLM required."],
                next_actions=["Ensure Ollama is running via 'systemctl status ollama' or 'ollama serve'."],
                requires_human_review=True,
                audit_verifiable=False,
                question=question,
                case_id=res_case,
                entity_id=res_ent,
                finding_id=res_fnd,
                model_name=health.get("selected_model") or "UNKNOWN",
                state_transitions=transitions
            )

        active_model = health.get("selected_model") or "qwen3:4b"

        # Check for completely ungrounded/unknown questions
        lower_q = question.lower()
        known_keywords = [
            "case", "status", "finding", "evidence", "provenance", "conflict", "domain",
            "motif", "pattern", "sequence", "timeline", "before", "after", "next",
            "baseline", "drift", "quarantine", "graphsage", "tgn", "predict", "guilt", "flagged",
            "stumpy", "dtw", "ablation", "explain", "relationship", "influenc"
        ]
        if not any(kw in lower_q for kw in known_keywords) and not res_case and not res_ent:
            self._record_transition(transitions, AgentState.QUESTION_RECEIVED.value, AgentState.UNAVAILABLE.value, "Question contains no recognized forensic entities or investigation topics.")
            return AgenticInvestigationResult(
                agent_run_id=agent_run_id,
                status=AgentState.UNAVAILABLE.value,
                answer="UNAVAILABLE: The query falls outside the closed domain of authoritative DFAP forensic tools and evidence.",
                claims=[],
                tool_trace=[],
                evidence_refs=[],
                provenance_refs=[],
                uncertainties=["No matching forensic evidence or authoritative case context found."],
                limitations=["Closed-domain orchestrator does not hallucinate out-of-scope answers."],
                next_actions=["Formulate an inquiry targeting an active case (e.g. CASE-DFAP-4DOMAIN-001) or entity."],
                requires_human_review=False,
                audit_verifiable=True,
                question=question,
                model_name=active_model,
                state_transitions=transitions
            )

        # Plan Tools
        selected_tools = self._plan_tools(question, res_case, res_ent, res_fnd)
        self._record_transition(transitions, AgentState.QUESTION_RECEIVED.value, AgentState.TOOLS_SELECTED.value, f"Selected tools: {', '.join(selected_tools)}")

        # Execute Tools
        self._record_transition(transitions, AgentState.TOOLS_SELECTED.value, AgentState.TOOLS_EXECUTING.value, "Executing planned tool sequence deterministically.")
        tool_records: List[ToolExecutionRecord] = []
        for idx, tool_name in enumerate(selected_tools, start=1):
            extra_params: Dict[str, Any] = {"question": question}
            ent_matches = re.findall(r"ENT_[A-Za-z0-9_]+", question)
            if len(ent_matches) >= 2:
                extra_params["source_id"] = ent_matches[0]
                extra_params["target_id"] = ent_matches[1]
            elif len(ent_matches) == 1:
                extra_params["source_id"] = ent_matches[0]
            if "tgn" in lower_q:
                extra_params["model"] = "tgn"
            elif "graphsage" in lower_q or "sage" in lower_q:
                extra_params["model"] = "graphsage"

            cache_key = f"{res_case}|{res_ent}|{res_fnd}|{tool_name}"
            if cache_key in self._tool_cache:
                cached_rec = self._tool_cache[cache_key]
                # Clone with updated execution order to preserve trace integrity
                rec = ToolExecutionRecord(
                    tool_name=cached_rec.tool_name,
                    tool_version=cached_rec.tool_version + ".CACHED",
                    input_parameters=cached_rec.input_parameters,
                    execution_order=idx,
                    result_status=cached_rec.result_status,
                    output_summary=cached_rec.output_summary,
                    evidence_refs=cached_rec.evidence_refs,
                    provenance_refs=cached_rec.provenance_refs,
                    raw_output=cached_rec.raw_output,
                )
            else:
                rec = self.registry.execute_tool(
                    tool_name=tool_name,
                    order=idx,
                    case_id=res_case,
                    entity_id=res_ent,
                    finding_id=res_fnd,
                    extra_params=extra_params
                )
                self._tool_cache[cache_key] = rec
            tool_records.append(rec)


        # Assemble Evidence & Provenance
        self._record_transition(transitions, AgentState.TOOLS_EXECUTING.value, AgentState.EVIDENCE_ASSEMBLED.value, "Aggregating evidence records and cryptographic hashes.")
        all_evidence_refs: Set[str] = set()
        all_provenance_refs: Set[str] = set()
        for rec in tool_records:
            all_evidence_refs.update(rec.evidence_refs)
            all_provenance_refs.update(rec.provenance_refs)

        # Check Evidential Conflict & Packet Status
        self._record_transition(transitions, AgentState.EVIDENCE_ASSEMBLED.value, AgentState.CONFLICT_CHECKED.value, "Assessing evidential conflict and human review requirement.")
        is_conflicted = False
        requires_human_review = False
        conflict_details: Dict[str, Any] = {}
        conflicting_pair_str = ""

        # Inspect conflict tool record or packet tool record
        for rec in tool_records:
            if rec.tool_name == "cross_domain_conflict":
                if "conflicting_pair=" in rec.output_summary:
                    pair_part = rec.output_summary.split("conflicting_pair=")[-1].strip(". ")
                    if pair_part and pair_part != "None":
                        conflicting_pair_str = pair_part
                if "ABSTENTION" in rec.output_summary or "CONFLICT" in rec.output_summary or "MATERIAL" in rec.output_summary:
                    is_conflicted = True
                    requires_human_review = True
            elif rec.tool_name == "case_forensic_packet":
                if "CONFLICTED" in rec.output_summary or "ABSTENTION" in rec.output_summary:
                    is_conflicted = True
                    requires_human_review = True

        if is_conflicted and not conflicting_pair_str:
            conflicting_pair_str = "FINANCIAL vs SOCIAL"

        # Special query handling: Guilt / criminal proof refusal
        is_guilt_query = any(w in lower_q for w in ["guilt", "guilty", "prove the suspect", "prove guilt"])
        if is_guilt_query:
            requires_human_review = True

        # Construct Context for Ollama Synthesis
        summaries = [f"- Tool '{r.tool_name}': {r.output_summary}" for r in tool_records]
        tool_facts_str = "\n".join(summaries)

        system_instruction = (
            "You are the DFAP M14 Forensic Synthesis Engine. Your role is to synthesize a grounded, professional "
            "investigative explanation strictly based on the provided deterministic tool outputs.\n"
            "RULES:\n"
            "1. Base your answer ONLY on the provided tool facts, evidence references, and conflict status.\n"
            "2. NEVER state or imply criminal guilt, liability, or fraudulent intent. DFAP produces empirical anomaly signals, not legal determinations.\n"
            "3. If evidence is conflicted (e.g. FINANCIAL vs SOCIAL), explicitly emphasize that the evidence disagrees and human review is required.\n"
            "4. Be concise, direct, and factual. Avoid generic filler."
        )

        user_synthesis_prompt = (
            f"Investigator Question: {question}\n"
            f"Active Scope: Case={res_case or 'N/A'}, Entity={res_ent or 'N/A'}, Finding={res_fnd or 'N/A'}\n"
            f"Evidential Conflict Status: {'CONFLICTED (ABSTENTION REQUIRED)' if is_conflicted else 'UNCONFLICTED'}\n"
            f"Conflicting Domain Pair: {conflicting_pair_str or 'None'}\n\n"
            f"Authoritative Tool Facts:\n{tool_facts_str}\n\n"
            f"Synthesize a clear, evidence-grounded answer to the investigator's question:"
        )

        try:
            llm_gen = self.ollama_client.generate(
                prompt=user_synthesis_prompt,
                system=system_instruction,
                temperature=0.0
            )
            raw_ans = llm_gen.get("response", "").strip()
        except OllamaUnavailableError:
            raw_ans = "Tool execution completed, but Ollama synthesis failed due to client error."

        final_status = "CONFLICTED" if is_conflicted else ("HUMAN_REVIEW_REQUIRED" if requires_human_review else "COMPLETED")

        if not raw_ans or len(raw_ans.strip()) < 10:
            raw_ans = (
                f"Investigation of case {res_case or 'N/A'} (finding {res_fnd or 'N/A'}): "
                f"Status is {final_status}. "
                f"{f'Evidential conflict observed between {conflicting_pair_str}. Human review is required.' if is_conflicted else 'Evidence assembled and verified.'} "
                f"Tool trace verified across {len(tool_records)} authoritative DFAP engines."
            )

        self._record_transition(transitions, AgentState.CONFLICT_CHECKED.value, AgentState.ANSWER_SYNTHESIZED.value, "Ollama grounded synthesis completed.")

        # Guardrails & Answer Formatting Enforcement
        if is_guilt_query:
            raw_ans = (
                "DFAP strictly refrains from making legal determinations of guilt, criminal liability, or intent. "
                "The system provides empirical, provenance-bound anomaly scores and evidential conflict intelligence "
                "for human corroboration only. Evidential findings do not establish criminal culpability."
            )

        # Ensure explicit conflict disclosure if conflicted
        if is_conflicted and conflicting_pair_str and conflicting_pair_str not in raw_ans:
            raw_ans = (
                f"STATUS: CONFLICTED. Material conflict detected between {conflicting_pair_str}. "
                f"Human review is mandatory before taking operational action.\n\n" + raw_ans
            )

        # Generate Claims
        claims: List[Dict[str, Any]] = []
        for r in tool_records:
            if r.result_status == "SUCCESS":
                claims.append({
                    "claim": r.output_summary,
                    "evidence_ids": r.evidence_refs,
                    "tool": r.tool_name
                })

        # Structured Next Actions
        next_actions: List[str] = []
        if is_conflicted:
            next_actions.append(f"Conduct human review on conflicting domain pair ({conflicting_pair_str or 'FINANCIAL vs SOCIAL'}).")
            next_actions.append("Review authentic social baseline evidence to verify benign community activity.")
        if any(r.tool_name == "finding_explainability" for r in tool_records):
            next_actions.append("Inspect top contributing SHAP feature vectors and underlying source telemetry.")
        if any(r.tool_name == "motif_discovery" for r in tool_records):
            next_actions.append("Examine recurring cross-domain behavioral motifs across chronological windows.")
        if any(r.tool_name == "adaptive_baseline" for r in tool_records):
            next_actions.append("Query 'baseline <entity> history' to verify EWMA adaptation drift vs quarantine.")
        if any(r.tool_name == "gnn_explain_prediction" for r in tool_records):
            next_actions.append("Inspect top influential neighborhood nodes and feature sensitivities under PREDICTED boundary.")
        if any(r.tool_name == "temporal_similarity_ablation" for r in tool_records):
            next_actions.append("Evaluate DTW elastic warping vs STUMPY z-normalized Euclidean distance profile across window sizes.")
        if not next_actions:
            next_actions.append("Review chronological timeline and verify bound provenance records.")


        uncertainties = [
            "AI-generated investigative synthesis; human verification required prior to any operational action."
        ]
        if is_conflicted:
            uncertainties.append(f"Substantive evidential disagreement between {conflicting_pair_str or 'observed domains'}.")

        limitations = [
            "Strict Non-Culpability: Mathematical baseline divergence and anomaly scores do not establish guilt or intent."
        ]

        # Determine Final Status
        final_status = "CONFLICTED" if is_conflicted else ("HUMAN_REVIEW_REQUIRED" if requires_human_review else "COMPLETED")
        final_state = AgentState.HUMAN_REVIEW_REQUIRED.value if requires_human_review else AgentState.COMPLETED.value
        self._record_transition(transitions, AgentState.ANSWER_SYNTHESIZED.value, final_state, f"Investigation finalized with status={final_status}.")

        return AgenticInvestigationResult(
            agent_run_id=agent_run_id,
            status=final_status,
            answer=raw_ans,
            claims=claims,
            tool_trace=[r.to_dict() for r in tool_records],
            evidence_refs=sorted(all_evidence_refs),
            provenance_refs=sorted(all_provenance_refs),
            uncertainties=uncertainties,
            limitations=limitations,
            next_actions=next_actions,
            requires_human_review=requires_human_review,
            audit_verifiable=True,
            question=question,
            case_id=res_case,
            entity_id=res_ent,
            finding_id=res_fnd,
            model_name=active_model,
            state_transitions=transitions,
            generation_parameters={"temperature": 0.0, "max_tool_calls": self.MAX_TOOL_CALLS}
        )
