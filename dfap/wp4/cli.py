# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: Member 4 Investigation Console & Live M1->M2->M3 Real-Time Streaming Layer

import argparse
import json
import os
import re
import shlex
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from typing import List, Any, Dict, Optional
import pandas as pd

from dfap.investigation.evidence_provenance import CanonicalEvidenceRecord
from dfap.investigation.workspace import InvestigationWorkspaceBackend
from dfap.wp4.service import WP4Service
from dfap.wp4.stream import RealtimeM1M2M3Pipeline
from dfap.wp4.contracts import (
    EvidenceChainError,
    WorkspaceError,
    UpstreamContractError,
    UpstreamIntegrityError,
)
from dfap.data.dataset_registry import DatasetRegistry
from dfap.investigation.replay import HistoricalReplayEngine, ReplayState
from dfap.investigation.auto_discovery import AutoDiscoveryEngine
from dfap.investigation.behavioral_profile import BehavioralProfiler
from dfap.investigation.graph_traversal import InvestigationGraphTraversal
from dfap.investigation.cross_domain import CrossDomainInvestigator
from dfap.investigation.search import TargetedSearchEngine
from dfap.investigation.case_export import CaseDossierExporter
from dfap.investigation.temporal_engine import TemporalEventEngine, load_identity_bridge_readonly
from dfap.investigation.conflict_fixture import register_contradiction_fixture
from dfap.investigation.reliability_fixture import register_reliability_fixture
from dfap.investigation.data_quality_fixture import register_data_quality_fixture
from dfap.investigation.four_domain_fixture import register_four_domain_fixture


def format_json(obj: Any) -> str:
    return json.dumps(obj, indent=2, sort_keys=True)


def _parse_window_seconds(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text:
        return None
    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        return float(text)
    match = re.fullmatch(r"(\d+(?:\.\d+)?)([smhd])", text)
    if not match:
        raise ValueError(f"Unsupported time window '{value}'. Use seconds, minutes, hours, or days (e.g. 24h).")
    number = float(match.group(1))
    unit = match.group(2)
    if unit == "s":
        return number
    if unit == "m":
        return number * 60.0
    if unit == "h":
        return number * 3600.0
    if unit == "d":
        return number * 86400.0
    raise ValueError(f"Unsupported time unit '{unit}' for window '{value}'.")


def _multiline_summary(title: str, body: Any) -> str:
    if isinstance(body, (dict, list)):
        return f"{title}\n{format_json(body)}"
    return f"{title}\n{body}"


def _format_finding_risk_summary(res: Dict[str, Any]) -> str:
    lines = [
        "FINDING RISK EVALUATION",
        f"Finding ID:        {res.get('finding_id')}",
        f"Entity ID:         {res.get('entity_id')}",
        f"Case ID:           {res.get('case_id') or 'N/A'}",
        f"Risk Score:        {float(res.get('risk_score', 0.0)):.4f}",
        f"Priority Level:    {res.get('priority_level')}",
        f"Priority Rank:     {res.get('priority_rank', 1)}",
        f"Conflict Status:   {res.get('conflict_status', 'N/A')}",
        f"Human Review Req:  {res.get('requires_human_review', False)}",
        "",
        "Component Breakdown:",
        f"  Anomaly (w={res.get('anomaly_component', {}).get('weight', 0.35)}):            raw={res.get('anomaly_component', {}).get('raw_value')}  contrib={res.get('anomaly_component', {}).get('weighted_contribution')}",
        f"  Graph Significance (w={res.get('graph_significance_component', {}).get('weight', 0.20)}): raw={res.get('graph_significance_component', {}).get('raw_value')} (peers={res.get('graph_significance_component', {}).get('neighbor_count', 0)}) contrib={res.get('graph_significance_component', {}).get('weighted_contribution')}",
        f"  Fusion Confidence (w={res.get('fusion_component', {}).get('weight', 0.25)}):  raw={res.get('fusion_component', {}).get('raw_value')}  contrib={res.get('fusion_component', {}).get('weighted_contribution')}",
        f"  Recency/Clustering (w={res.get('recency_clustering_component', {}).get('weight', 0.20)}): raw={res.get('recency_clustering_component', {}).get('raw_value')} (cluster={res.get('recency_clustering_component', {}).get('cluster_size', 1)}) contrib={res.get('recency_clustering_component', {}).get('weighted_contribution')}",
        "",
        f"Missing Signals:     {', '.join(res.get('missing_signals', [])) if res.get('missing_signals') else 'None'}",
        f"Active Reasons:      {', '.join(res.get('reason_codes', [])) if res.get('reason_codes') else 'BASELINE_MONITORING'}",
        f"Explanation:         {res.get('explanation', '')}"
    ]
    return "\n".join(lines)


def _format_risk_queue_summary(title: str, queue: List[Dict[str, Any]]) -> str:
    if not queue:
        return f"{title}\nNo findings available for triage."
    lines = [
        f"=== {title} ===",
        f"{'Rank':<5} {'Finding ID':<24} {'Risk Score':<12} {'Priority':<10} {'Human Review':<14} {'Reasons':<30}",
        "-" * 100
    ]
    for item in queue:
        reasons = ",".join(item.get('reason_codes', [])[:2])
        score_str = f"{float(item.get('risk_score', 0.0)):.4f}"
        lines.append(
            f"{item.get('priority_rank', 1):<5} "
            f"{item.get('finding_id', ''):<24} "
            f"{score_str:<12} "
            f"{item.get('priority_level', ''):<10} "
            f"{str(item.get('requires_human_review', False)):<14} "
            f"{reasons:<30}"
        )
    lines.append("")
    lines.append("Note: Triage priority directs investigative sequence; it does not infer guilt or legal culpability.")
    return "\n".join(lines)


def _format_shap_explanation_summary(exp: Dict[str, Any]) -> str:
    lines = [
        "M9 ON-DEMAND SHAP ANOMALY EXPLANATION",
        f"Finding ID:        {exp.get('finding_id')}",
        f"Entity ID:         {exp.get('entity_id')}",
        f"Anomaly Score:     {float(exp.get('anomaly_score', 0.0)):.4f}",
        f"Model/Detector:    {exp.get('model_identifier')}",
        f"Explainer Type:    {exp.get('explainer_type')}",
        f"Status:            {exp.get('explanation_status')}",
        f"Base Value:        {exp.get('base_value')}",
        "",
        "Top Positive Contributors (Driving Anomaly Score):",
    ]
    pos = exp.get("top_positive_contributors", [])
    if pos:
        for c in pos:
            ref_str = f" [Evidence: {c['evidence_ref']}]" if c.get("evidence_ref") else ""
            lines.append(f"  (+) {c['feature_name']:<24} shap={c['shap_value']:+.4f}  (val={c.get('feature_value')}){ref_str}")
    else:
        lines.append("  None")

    lines.append("")
    lines.append("Top Negative Contributors (Pulling Toward Baseline Normality):")
    neg = exp.get("top_negative_contributors", [])
    if neg:
        for c in neg:
            ref_str = f" [Evidence: {c['evidence_ref']}]" if c.get("evidence_ref") else ""
            lines.append(f"  (-) {c['feature_name']:<24} shap={c['shap_value']:+.4f}  (val={c.get('feature_value')}){ref_str}")
    else:
        lines.append("  None")

    lines.append("")
    ev_refs = exp.get("evidence_refs", [])
    lines.append(f"Bound Evidence Refs: {', '.join(ev_refs) if ev_refs else 'None'}")
    lines.append("")
    lines.append(f"Explanation:         {exp.get('explanation')}")
    lines.append("")
    lines.append("Limitations & Non-Culpability:")
    for lim in exp.get("limitations", []):
        lines.append(f"  * {lim}")
    return "\n".join(lines)




def _register_live_stream_finding_to_workspace(
    backend: InvestigationWorkspaceBackend,
    pipeline: RealtimeM1M2M3Pipeline,
    entity_id: str
) -> Optional[str]:
    if not pipeline or not pipeline.live_finding:
        return None

    finding = pipeline.live_finding
    finding_id = str(finding.get("finding_id"))
    if not finding_id:
        return None

    backend.set_live_stream_events([e.to_dict() for e in pipeline.canonical_events])

    if finding_id not in backend.findings_by_id:
        backend.findings_by_id[finding_id] = {
            "finding_id": finding_id,
            "entity_id": entity_id,
            "target_entity_id": finding.get("target_entity_id", entity_id),
            "primary_entity_id": finding.get("primary_entity_id", entity_id),
            "related_entities": finding.get("related_entities", [entity_id]),
            "anomaly_type": finding.get("anomaly_type", "LIVE_STREAM_ANOMALY"),
            "composite_score": float(finding.get("composite_score", 0.0)),
            "status": "ACTIVE",
            "timestamp": finding.get("created_at"),
            "event_ids": finding.get("event_ids", []),
            "evidence_refs": finding.get("evidence_refs", []),
            "graph_refs": finding.get("graph_refs", []),
            "domains": finding.get("domains", []),
            "model_versions": finding.get("model_versions", {}),
            "feature_snapshot": finding.get("feature_snapshot", {}),
        }

    evidence_ids = []
    for event in pipeline.canonical_events:
        canonical_entity_ids = [entity_id]
        if event.actor_id and event.actor_id not in canonical_entity_ids:
            canonical_entity_ids.append(event.actor_id)
        if event.target_id and event.target_id not in canonical_entity_ids:
            canonical_entity_ids.append(event.target_id)

        record = CanonicalEvidenceRecord(
            evidence_type="CANONICAL_EVENT",
            source_domain=event.source_domain,
            source_id=event.event_id,
            source_file=event.source_file or "live_stream.csv",
            source_row_index=int(event.source_row_index) if event.source_row_index is not None else 0,
            canonical_entity_ids=canonical_entity_ids,
            event_ids=[event.event_id],
            observation_timestamp=event.timestamp,
            ingestion_timestamp=datetime.now(timezone.utc).isoformat(),
            derivation_method="LIVE_STREAM_EVENT",
            derivation_version="M12.LIVE_STREAM.V1",
            confidence=1.0,
            evidence_quality=1.0,
            temporal_semantics="OBSERVED_TIMESTAMP",
            parent_evidence_ids=[],
            evidence_category="SUPPORTING",
            metadata={
                "run_id": pipeline.run_id,
                "source_domain": event.source_domain,
                "event_type": event.event_type,
                "sha256_hash": event.sha256_hash,
            },
        )
        evidence_ids.append(backend.evidence_engine.register_evidence(record).evidence_id)

    try:
        backend.evidence_engine.bind_finding_to_evidence(
            finding_id,
            canonical_entity_id=entity_id,
            evidence_ids=evidence_ids,
            expected_event_ids=[e.event_id for e in pipeline.canonical_events],
            metadata={"run_id": pipeline.run_id, "source": "LIVE_STREAM"},
        )
    except ValueError:
        pass

    for case_id, case in list(backend.cases.items()):
        if case.canonical_entity_id == entity_id and case.search_context.get("source") == "LIVE_STREAM_FINDING":
            if finding_id in case.finding_ids:
                return case_id
            try:
                backend.attach_finding(case_id, finding_id)
            except ValueError:
                pass
            for ev_id in evidence_ids:
                try:
                    backend.attach_evidence(case_id, ev_id)
                except ValueError:
                    pass
            return case_id

    live_case_id = f"CASE-LIVE-{pipeline.run_id.split('_')[-1].upper()}"
    case = backend.create_case(
        entity_id,
        case_id=live_case_id,
        search_context={"source": "LIVE_STREAM_FINDING", "finding_id": finding_id, "run_id": pipeline.run_id},
    )
    backend.attach_finding(case.case_id, finding_id)
    for ev_id in evidence_ids:
        try:
            backend.attach_evidence(case.case_id, ev_id)
        except ValueError:
            pass
    return case.case_id


def handle_m13_command(
    backend: InvestigationWorkspaceBackend,
    command_text: str,
    active_case_id: Optional[str] = None,
    active_entity_id: Optional[str] = None,
) -> str:
    if not command_text or not command_text.strip():
        return "No command provided."

    parts = shlex.split(command_text)
    if not parts:
        return "No command provided."

    cmd = parts[0].lower()

    try:
        if cmd == "help":
            return "\n".join([
                "DFAP M13 INVESTIGATION COMMANDS",
                "search entity <query>",
                "search ip <query>",
                "search wallet <query>",
                "search account <query>",
                "search device <query>",
                "search phone <query>",
                "search case <query>",
                "timeline <entity>",
                "history <entity> [pivot]",
                "findings <entity>",
                "finding <finding_id>",
                "finding show <finding_id>",
                "evidence show <evidence_id>",
                "provenance <finding_id>",
                "backtrack <entity> <window>",
                "forwardtrack <entity> <window>",
                "paths <entity>",
                "case create <entity>",
                "case show <case_id>",
                "case attach-finding <case_id> <finding_id>",
                "case attach-evidence <case_id> <evidence_id>",
                "case note <case_id> \"text\"",
                "case status <case_id> <status>",
                "case audit <case_id>",
                "case export <case_id>",
                "case forensic <case_id>",
                "case risk <case_id>",
                "finding risk <finding_id>",
                "finding explain <finding_id>",
                "explain anomaly <finding_id>",
                "risk queue [case_id]",
                "export forensic <case_id>",
                "copilot ask \"question\"",
                "copilot explain <finding_id>",
                "copilot summarize <case_id>",
                "copilot next <case_id>",
                "copilot verify <finding_id>",
                "sequence <entity> [--around <event>]",
                "sequence motifs <entity>",
                "sequence patterns <entity>",
                "sequence features <entity>",
                "sequence transitions <entity>",
                "sequence phases <entity>",
                "sequence compare <seq_a> <seq_b>",
                "sequence ablation stumpy-dtw",
                "graphml compare",
                "graph ml benchmark",
                "graph ml predict <source_id> <target_id> [tgn|graphsage]",
                "graph ml explain <source_id> <target_id> [graphsage|tgn]",
                "baseline <entity>",
                "baseline <entity> status",
                "baseline <entity> history",
                "agent investigate \"<question>\" [case_id]",
                "agent trace \"<question>\" [case_id]",
            ])


        if cmd == "search":
            if len(parts) < 3:
                return "Usage: search <entity|ip|wallet|account|device|phone|case> <query>"
            qtype = parts[1].lower()
            qvalue = " ".join(parts[2:])
            valid = {"entity", "ip", "wallet", "account", "device", "phone", "case"}
            if qtype not in valid:
                return f"Unsupported search type '{qtype}'. Supported: {sorted(valid)}"
            results = backend.search(qvalue, query_type=qtype, max_results=20)
            if not results:
                return f"NO RESULTS: {qtype.upper()} search for '{qvalue}'"
            return _multiline_summary(f"SEARCH {qtype.upper()}: {qvalue}", results)

        if cmd == "timeline":
            entity_id = parts[1] if (len(parts) > 1 and not parts[1].startswith("--")) else (active_entity_id or (backend.cases[active_case_id].canonical_entity_id if active_case_id and active_case_id in backend.cases else None))
            if not entity_id:
                return "Usage: timeline <entity_id> [--from <time>] [--to <time>]"
            from_time = None
            to_time = None
            if "--from" in parts:
                idx = parts.index("--from")
                if idx + 1 < len(parts):
                    try:
                        from_time = float(parts[idx + 1])
                    except ValueError:
                        from_time = pd.to_datetime(parts[idx + 1], utc=True).timestamp()
            if "--to" in parts:
                idx = parts.index("--to")
                if idx + 1 < len(parts):
                    try:
                        to_time = float(parts[idx + 1])
                    except ValueError:
                        to_time = pd.to_datetime(parts[idx + 1], utc=True).timestamp()
            events = backend.get_timeline(entity_id, from_time=from_time, to_time=to_time)
            if not events:
                return f"NO TIMELINE: no events for {entity_id}"
            semantics = sorted({str(e.get("temporal_semantics", "OBSERVED_TIMESTAMP")) for e in events if e.get("temporal_semantics")})
            semantics_label = semantics[0] if semantics else "OBSERVED_TIMESTAMP"
            return _multiline_summary(f"TIMELINE {entity_id} TEMPORAL_SEMANTICS={semantics_label}", events)

        if cmd == "findings":
            entity_id = parts[1] if len(parts) > 1 else None
            if not entity_id:
                return "Usage: findings <entity_id>"
            matches = [f for f in backend.findings_by_id.values() if str(f.get("entity_id")) == entity_id]
            return _multiline_summary(f"FINDINGS {entity_id}", matches)

        if cmd == "finding":
            if len(parts) > 2 and parts[1].lower() in ("explain", "shap"):
                finding_id = parts[2]
                res = backend.explain_finding_shap(finding_id, case_id=active_case_id)
                return _format_shap_explanation_summary(res)
            if len(parts) > 2 and parts[1].lower() in ("risk", "triage"):
                finding_id = parts[2]
                res = backend.evaluate_finding_risk(finding_id, case_id=active_case_id)
                return _format_finding_risk_summary(res)
            if len(parts) == 2:
                finding_id = parts[1]
                return _multiline_summary(f"FINDING: {finding_id}", backend.get_finding(finding_id))
            if len(parts) > 2 and parts[1].lower() == "show":
                finding_id = parts[2]
                return _multiline_summary(f"FINDING: {finding_id}", backend.get_finding(finding_id))
            return "Usage: finding <finding_id> | finding show <finding_id> | finding risk <finding_id> | finding explain <finding_id>"

        if cmd == "evidence":
            if len(parts) == 2:
                evidence_id = parts[1]
                ev = backend.evidence_engine.get_evidence(evidence_id)
                if ev is None:
                    raise KeyError(f"Evidence '{evidence_id}' not found in M12 evidence store.")
                return _multiline_summary(f"EVIDENCE: {evidence_id}", ev.to_dict())
            if len(parts) > 2 and parts[1].lower() == "show":
                evidence_id = parts[2]
                ev = backend.evidence_engine.get_evidence(evidence_id)
                if ev is None:
                    raise KeyError(f"Evidence '{evidence_id}' not found in M12 evidence store.")
                return _multiline_summary(f"EVIDENCE: {evidence_id}", ev.to_dict())
            return "Usage: evidence <evidence_id> | evidence show <evidence_id>"

        if cmd == "provenance":
            finding_id = parts[1] if len(parts) > 1 else None
            if not finding_id:
                return "Usage: provenance <finding_id>"
            res = backend.get_provenance(finding_id)
            lineage_summary = res.get("lineage_chain", [])
            lineage_label = "LINEAGE" if lineage_summary else "FINDING"
            return _multiline_summary(f"PROVENANCE {finding_id} {lineage_label}", res)

        if cmd == "history":
            entity_id = parts[1] if (len(parts) > 1 and not parts[1].startswith("--")) else (active_entity_id or (backend.cases[active_case_id].canonical_entity_id if active_case_id and active_case_id in backend.cases else None))
            if not entity_id:
                return "Usage: history <entity_id> [pivot]"
            pivot = None
            if len(parts) > 2:
                try:
                    pivot = float(parts[2])
                except ValueError:
                    pivot = parts[2]
            res = backend.history(entity_id, pivot=pivot)
            return _multiline_summary(f"HISTORY {entity_id} PIVOT={pivot}", {"entity_id": entity_id, "event_count": len(res), "events": res})

        if cmd == "backtrack":
            if len(parts) < 3:
                return "Usage: backtrack <entity_id> <window> [pivot]"
            entity_id = parts[1]
            window_seconds = _parse_window_seconds(parts[2])
            pivot = None
            if len(parts) > 3:
                try:
                    pivot = float(parts[3])
                except ValueError:
                    pivot = parts[3]
            if pivot is None:
                history = backend.get_timeline(entity_id)
                if not history:
                    return f"NO BACKTRACK: {entity_id} has no timeline history."
                pivot = max(float(e.get("epoch_time", 0.0)) for e in history if e.get("epoch_time") is not None)
            result = backend.backtrack(entity_id, window_seconds=window_seconds, pivot=pivot)
            return _multiline_summary(f"BACKTRACK {entity_id} WINDOW={parts[2]}", result)

        if cmd == "forwardtrack":
            if len(parts) < 3:
                return "Usage: forwardtrack <entity_id> <window> [pivot]"
            entity_id = parts[1]
            window_seconds = _parse_window_seconds(parts[2])
            pivot = None
            if len(parts) > 3:
                try:
                    pivot = float(parts[3])
                except ValueError:
                    pivot = parts[3]
            if pivot is None:
                history = backend.get_timeline(entity_id)
                if not history:
                    return f"NO FORWARDTRACK: {entity_id} has no timeline history."
                pivot = min(float(e.get("epoch_time", 0.0)) for e in history if e.get("epoch_time") is not None)
            result = backend.forwardtrack(entity_id, window_seconds=window_seconds, pivot=pivot)
            return _multiline_summary(f"FORWARDTRACK {entity_id} WINDOW={parts[2]}", result)

        if cmd == "paths":
            entity_id = parts[1] if len(parts) > 1 else None
            if not entity_id:
                return "Usage: paths <entity_id>"
            return _multiline_summary(f"PATHS {entity_id}", backend.get_paths(entity_id))

        if cmd == "ldrm":
            from dfap.ldrm.cli import handle_ldrm_command
            return handle_ldrm_command(backend, parts[1:])

        if cmd == "case":
            if len(parts) == 2:
                case_id = parts[1]
                case = backend.get_case(case_id)
                return _multiline_summary(f"CASE {case.case_id}", case.to_dict())
            if len(parts) < 3:
                return "Usage: case <create|show|findings|evidence|attach-finding|attach-evidence|note|status|audit|export> ..."
            action = parts[1].lower()
            if action == "create":
                entity_id = parts[2]
                case = backend.create_case(entity_id)
                return _multiline_summary(f"CASE CREATED: {case.case_id}", case.to_dict())
            if action == "show":
                case = backend.get_case(parts[2])
                return _multiline_summary(f"CASE {case.case_id}", case.to_dict())
            if action == "findings":
                case_id = parts[2]
                case = backend.get_case(case_id)
                findings = [backend.findings_by_id[fid] for fid in case.finding_ids if fid in backend.findings_by_id]
                return _multiline_summary(f"CASE FINDINGS {case_id}", findings)
            if action == "evidence":
                case_id = parts[2]
                case = backend.get_case(case_id)
                ev_items = [backend.evidence_engine.get_evidence(eid).to_dict() for eid in case.evidence_ids if backend.evidence_engine.get_evidence(eid)]
                return _multiline_summary(f"CASE EVIDENCE {case_id}", ev_items)
            if action == "attach-finding":
                case_id = parts[2]
                finding_id = parts[3]
                case = backend.attach_finding(case_id, finding_id)
                return _multiline_summary(f"CASE FINDING ATTACHED: {case_id}", case.to_dict())
            if action == "attach-evidence":
                case_id = parts[2]
                evidence_id = parts[3]
                case = backend.attach_evidence(case_id, evidence_id)
                return _multiline_summary(f"CASE EVIDENCE ATTACHED: {case_id}", case.to_dict())
            if action == "note":
                case_id = parts[2]
                note_text = " ".join(parts[3:])
                if not note_text:
                    return "Usage: case note <case_id> \"text\""
                case = backend.add_case_note(case_id, note_text)
                return _multiline_summary(f"CASE NOTE ADDED: {case_id}", case.to_dict())
            if action == "status":
                case_id = parts[2]
                new_status = parts[3].upper() if len(parts) > 3 else None
                if not new_status:
                    return "Usage: case status <case_id> <OPEN|UNDER_REVIEW|ESCALATED|RESOLVED|CLOSED>"
                case = backend.update_case_status(case_id, new_status)
                return _multiline_summary(f"CASE STATUS UPDATED: {case_id}", case.to_dict())
            if action == "audit":
                case_id = parts[2]
                return _multiline_summary(f"CASE AUDIT {case_id}", backend.get_case_audit(case_id))
            if action == "export":
                case_id = parts[2]
                export_text = backend.export_case(case_id, export_format="json")
                return _multiline_summary(f"CASE EXPORT {case_id}", json.loads(export_text))
            if action == "forensic":
                case_id = parts[2] if len(parts) > 2 else active_case_id
                if not case_id:
                    return "Usage: case forensic <case_id>"
                export_res = backend.export_forensic_packet(case_id)
                packet = backend.generate_forensic_packet(case_id)
                lines = [
                    "FORENSIC CASE PACKET",
                    f"Case: {case_id}",
                    f"Status: {packet.packet_status}",
                    "",
                    f"Findings: {len(packet.findings)}",
                    f"Evidence items: {len(packet.evidence_quality.get('evidence_items', []))}",
                    f"Domains: {', '.join(packet.case.get('domains', []))}",
                    f"Conflicts: {len(packet.conflict_intelligence.get('pairs', []))}",
                    f"Discovered motifs: {len(packet.temporal_intelligence.get('discovered_motifs', []))}",
                    f"Provenance links: {len(packet.traceability_matrix)}",
                    "",
                    "Exported:",
                    f"  {export_res['json_filename']}",
                    f"  {export_res['markdown_filename']}"
                ]
                return "\n".join(lines)
            if action in ("risk", "triage"):
                case_id = parts[2] if len(parts) > 2 else active_case_id
                if not case_id:
                    return "Usage: case risk <case_id>"
                queue = backend.get_triage_queue(case_id=case_id)
                return _format_risk_queue_summary(f"CASE RISK TRIAGE QUEUE: {case_id}", queue)
            return f"Unsupported case action '{action}'."

        if cmd in ("risk", "triage"):
            if len(parts) > 1 and parts[1].lower() == "queue":
                case_id = parts[2] if len(parts) > 2 else active_case_id
                queue = backend.get_triage_queue(case_id=case_id)
                title = f"RISK TRIAGE QUEUE (Case: {case_id})" if case_id else "GLOBAL RISK TRIAGE QUEUE"
                return _format_risk_queue_summary(title, queue)
            if len(parts) > 2 and parts[1].lower() == "finding":
                finding_id = parts[2]
                res = backend.evaluate_finding_risk(finding_id, case_id=active_case_id)
                return _format_finding_risk_summary(res)
            if len(parts) > 2 and parts[1].lower() == "case":
                case_id = parts[2]
                queue = backend.get_triage_queue(case_id=case_id)
                return _format_risk_queue_summary(f"CASE RISK TRIAGE QUEUE: {case_id}", queue)
            if len(parts) > 1 and parts[1] in backend.findings_by_id:
                res = backend.evaluate_finding_risk(parts[1], case_id=active_case_id)
                return _format_finding_risk_summary(res)
            case_id = parts[1] if len(parts) > 1 else active_case_id
            queue = backend.get_triage_queue(case_id=case_id)
            title = f"RISK TRIAGE QUEUE (Case: {case_id})" if case_id else "GLOBAL RISK TRIAGE QUEUE"
            return _format_risk_queue_summary(title, queue)

        if cmd == "explain":
            if len(parts) > 2 and parts[1].lower() == "anomaly":
                finding_id = parts[2]
            elif len(parts) > 1:
                finding_id = parts[1]
            else:
                return "Usage: explain anomaly <finding_id> | finding explain <finding_id>"
            res = backend.explain_finding_shap(finding_id, case_id=active_case_id)
            return _format_shap_explanation_summary(res)

        if cmd == "export" and len(parts) > 1 and parts[1].lower() == "forensic":
            case_id = parts[2] if len(parts) > 2 else active_case_id
            if not case_id:
                return "Usage: export forensic <case_id>"
            export_res = backend.export_forensic_packet(case_id)
            packet = backend.generate_forensic_packet(case_id)
            lines = [
                "FORENSIC CASE PACKET",
                f"Case: {case_id}",
                f"Status: {packet.packet_status}",
                "",
                f"Findings: {len(packet.findings)}",
                f"Evidence items: {len(packet.evidence_quality.get('evidence_items', []))}",
                f"Domains: {', '.join(packet.case.get('domains', []))}",
                f"Conflicts: {len(packet.conflict_intelligence.get('pairs', []))}",
                f"Discovered motifs: {len(packet.temporal_intelligence.get('discovered_motifs', []))}",
                f"Provenance links: {len(packet.traceability_matrix)}",
                "",
                "Exported:",
                f"  {export_res['json_filename']}",
                f"  {export_res['markdown_filename']}"
            ]
            return "\n".join(lines)


        if cmd in {"investigate", "entity"}:
            entity_id = parts[1] if len(parts) > 1 else None
            if not entity_id:
                return "Usage: investigate <entity_id>"
            return _multiline_summary(f"ENTITY INVESTIGATION {entity_id}", backend.investigate_entity(entity_id))

        if cmd == "graphml" or (cmd == "graph" and len(parts) > 1 and parts[1].lower() == "ml"):
            sub_parts = parts[2:] if (cmd == "graph" and len(parts) > 1 and parts[1].lower() == "ml") else parts[1:]
            sub = sub_parts[0].lower() if sub_parts else "compare"
            if sub in ["compare", "benchmark"]:
                bench = backend.run_graph_ml_benchmark()
                return (
                    f"GRAPH ML ABLATION BENCHMARK (GraphSAGE vs TGN)\n\n"
                    f"{bench['table_markdown']}\n\n"
                    f"Dataset: {bench['dataset_summary']['num_nodes']} nodes, "
                    f"{bench['dataset_summary']['total_train_events']} train events, "
                    f"{bench['dataset_summary']['total_val_events']} val events, "
                    f"{bench['dataset_summary']['total_test_events']} test events "
                    f"({bench['dataset_summary']['test_eval_samples']} eval samples).\n"
                    f"Chronological Split: Train {bench['dataset_summary']['temporal_split']['train_range']} < "
                    f"Val {bench['dataset_summary']['temporal_split']['val_range']} < "
                    f"Test {bench['dataset_summary']['temporal_split']['test_range']}.\n\n"
                    f"NOTE: {bench['disclaimer']}"
                )
            if sub == "predict":
                if len(sub_parts) < 3:
                    return "Usage: graph ml predict <source_id> <target_id> [tgn|graphsage]"
                src = sub_parts[1]
                dst = sub_parts[2]
                mod = sub_parts[3].lower() if len(sub_parts) > 3 else "tgn"
                pred = backend.predict_graph_relationship(src, dst, model=mod)
                if pred.get("status") == "UNAVAILABLE" or pred.get("prediction_status") == "UNAVAILABLE":
                    return (
                        f"GRAPH ML LINK PREDICTION\n"
                        f"Model:            {pred['model_name']}\n"
                        f"Source:           {pred['source_id']}\n"
                        f"Target:           {pred['target_id']}\n"
                        f"Status:           UNAVAILABLE\n"
                        f"Probability:      None\n"
                        f"Reason:           {pred.get('reason', 'Identifier is outside the trained benchmark graph.')}\n"
                        f"Disclaimer:       {pred.get('disclaimer', 'No model prediction was produced.')}"
                    )
                prob_str = f"{pred['prediction_probability']:.4f}" if pred.get("prediction_probability") is not None else "None"
                return (
                    f"GRAPH ML LINK PREDICTION\n"
                    f"Model:            {pred['model_name']}\n"
                    f"Source:           {pred['source_id']}\n"
                    f"Target:           {pred['target_id']}\n"
                    f"Probability:      {prob_str}\n"
                    f"Status:           {pred['prediction_status']}\n"
                    f"Type:             {pred['prediction_type']}\n"
                    f"Temporal Context: {pred['temporal_context']}\n"
                    f"Ordering Basis:   {pred['ordering_basis']}\n"
                    f"Evidence Refs:    {pred['evidence_refs']} (Zero: model prediction is not observed evidence)\n"
                    f"Disclaimer:       {pred['disclaimer']}"
                )
            if sub == "explain":
                if len(sub_parts) < 3:
                    return "Usage: graph ml explain <source_id> <target_id> [graphsage|tgn]"
                src = sub_parts[1]
                dst = sub_parts[2]
                mod = sub_parts[3].lower() if len(sub_parts) > 3 else "graphsage"
                exp = backend.explain_graph_prediction(src, dst, model=mod)
                if exp.get("status") == "UNAVAILABLE" or exp.get("explanation_status") == "UNAVAILABLE":
                    return (
                        f"GRAPH ML GNNEXPLAINER ATTRIBUTION\n"
                        f"Model:                    {exp['model_name']}\n"
                        f"Source:                   {exp['source_entity']}\n"
                        f"Target:                   {exp['target_entity']}\n"
                        f"Status:                   UNAVAILABLE\n"
                        f"Reason:                   {exp.get('reason', 'Identifier is outside the trained benchmark graph.')}\n"
                        f"Limitations:              {'; '.join(exp.get('limitations', []))}"
                    )
                prob_str = f"{exp['predicted_probability']:.4f}" if exp.get("predicted_probability") is not None else "None"
                nodes_str = ", ".join([f"{n['node_id']} ({n['importance']:+.4f})" for n in exp.get("influential_nodes", [])[:5]]) or "None"
                edges_str = ", ".join([f"({e['source']}->{e['target']}: {e['importance']:+.4f})" for e in exp.get("influential_edges", [])[:5]]) or "None"
                feats_str = ", ".join([f"{f['node_id']}.{f['feature_name']} ({f['importance']:+.4f})" for f in exp.get("influential_features", [])[:5]]) or "None"

                return (
                    f"GRAPH ML GNNEXPLAINER ATTRIBUTION\n"
                    f"MODEL:                    {exp['model_name']} ({exp['model_version']})\n"
                    f"SOURCE:                   {exp['source_entity']}\n"
                    f"TARGET:                   {exp['target_entity']}\n"
                    f"PREDICTION:               {prob_str}\n"
                    f"STATUS:                   {exp['prediction_status']}\n"
                    f"TYPE:                     {exp['prediction_type']}\n"
                    f"METHOD:                   {exp['explanation_method']}\n"
                    f"TOP INFLUENTIAL NODES:    {nodes_str}\n"
                    f"TOP INFLUENTIAL EDGES:    {edges_str}\n"
                    f"FEATURE CONTRIBUTIONS:    {feats_str}\n"
                    f"LIMITATIONS:              {'; '.join(exp.get('limitations', []))}"
                )
            return "Usage: graphml <compare|benchmark|predict <src> <dst>|explain <src> <dst> [graphsage|tgn]>"


        if cmd == "baseline":
            if len(parts) < 2:
                return "Usage: baseline <entity> [status|history]"
            ent_arg = parts[1]
            sub = parts[2].lower() if len(parts) > 2 else "status"

            if sub == "history":
                history = backend.get_adaptive_baseline_history(ent_arg)
                if not history:
                    return f"No adaptive baseline history on record for entity '{ent_arg}'."
                lines = [f"ADAPTIVE BASELINE HISTORY: {ent_arg}"]
                lines.append(f"{'Step':<6} {'Feature':<18} {'Value':<10} {'PrevBase':<10} {'NewBase':<10} {'Dev':<8} {'State':<22} {'Decision':<24} {'Reason'}")
                lines.append("-" * 120)
                for h in history:
                    lines.append(
                        f"{h['step_index']:<6} {h['feature_name']:<18} {h['observation_value']:<10.2f} "
                        f"{h['previous_baseline']:<10.2f} {h['new_baseline']:<10.2f} {h['deviation']:<8.2f} "
                        f"{h['state_after']:<22} {h['update_decision']:<24} {h['update_reason']}"
                    )
                return "\n".join(lines)
            else:
                # status or default summary
                st = backend.get_adaptive_baseline_status(ent_arg)
                if "features" in st:
                    lines = [f"ADAPTIVE BASELINE STATUS: {ent_arg} ({st['features_count']} features)"]
                    for fname, fst in st["features"].items():
                        lines.append(
                            f"\nFeature:          {fname}\n"
                            f"State:            {fst['state']}\n"
                            f"Baseline:         {fst['current_baseline']:.4f}\n"
                            f"Variance / Std:   {fst['current_variance']:.4f} / {fst['current_std']:.4f}\n"
                            f"Observations:     {fst['observation_count']} (adaptations: {fst['adaptation_count']}, excluded: {fst['excluded_count']}, quarantined: {fst['quarantined_count']})\n"
                            f"Parameters:       alpha={fst['alpha']}, min_obs={fst['min_observations']}, dev_thresh={fst['deviation_threshold']}sigma, drift_thresh={fst['drift_threshold']}sigma"
                        )
                    return "\n".join(lines)
                else:
                    hist = backend.get_adaptive_baseline_history(ent_arg)
                    latest = hist[-1] if hist else {}
                    curr_val = latest.get("observation_value", "N/A")
                    dev_val = latest.get("deviation", "N/A")
                    dec = latest.get("update_decision", "N/A")
                    reason = latest.get("update_reason", st.get("reason", "No observations."))
                    updated = "True" if dec in ["UPDATED_BASELINE", "DRIFT_ADAPTED", "COLD_START_ACCUMULATION"] else "False"

                    return (
                        f"ADAPTIVE BASELINE: {ent_arg}\n"
                        f"Entity:            {ent_arg}\n"
                        f"Feature:           {st.get('feature_name', 'PRIMARY')}\n"
                        f"Current Value:     {curr_val}\n"
                        f"Baseline:          {st.get('current_baseline', 0.0):.4f}\n"
                        f"Deviation:         {dev_val}\n"
                        f"State:             {st.get('state', 'UNKNOWN')}\n"
                        f"Observation Count: {st.get('observation_count', 0)}\n"
                        f"Updated?:          {updated}\n"
                        f"Update Decision:   {dec}\n"
                        f"Reason:            {reason}"
                    )

        if cmd == "agent":
            if len(parts) < 2:
                return "Usage: agent <investigate|ask|trace> \"<question>\" [case_id]"
            subcmd = parts[1].lower()
            if subcmd not in ("investigate", "ask", "trace"):
                question = " ".join(parts[1:])
                target_case = active_case_id
                subcmd = "investigate"
            else:
                if len(parts) < 3:
                    return f"Usage: agent {subcmd} \"<question>\" [case_id]"
                question = parts[2]
                target_case = parts[3] if len(parts) > 3 else active_case_id

            res = backend.run_agentic_investigation(
                question=question,
                case_id=target_case,
                entity_id=active_entity_id
            )

            if subcmd == "trace":
                lines = [
                    "=" * 80,
                    f"  AGENTIC INVESTIGATION TRACE: {res.agent_run_id}",
                    "=" * 80,
                    f"Question:              {res.question}",
                    f"Status:                {res.status}",
                    f"Model:                 {res.model_name}",
                    f"Requires Human Review: {'REQUIRED' if res.requires_human_review else 'NOT REQUIRED'}",
                    "\nDeterministic Tool Execution Trace:"
                ]
                for t in res.tool_trace:
                    lines.append(f"  [{t['execution_order']}] {t['tool_name']} ({t['tool_version']}) -> {t['result_status']}")
                    lines.append(f"      Summary: {t['output_summary']}")
                    if t.get('evidence_refs'):
                        lines.append(f"      Evidence: {', '.join(t['evidence_refs'])}")
                lines.append("\nState Transitions:")
                for st in res.state_transitions:
                    lines.append(f"  {st.get('from_state', 'START')} -> {st.get('to_state')} ({st.get('reason')})")
                return "\n".join(lines)

            # Standard investigate / ask output
            lines = [
                "=" * 80,
                "  AGENTIC INVESTIGATION",
                "=" * 80,
                f"Question: {res.question}",
                f"Status:   {res.status}",
                f"Model:    {res.model_name}",
                "\nTool Trace:"
            ]
            for t in res.tool_trace:
                lines.append(f"  {t['execution_order']}. {t['tool_name']}: {t['output_summary']}")

            lines.append("\nEvidence:")
            if res.evidence_refs:
                lines.append("  " + ", ".join(res.evidence_refs))
            else:
                lines.append("  None")

            lines.append(f"\nAnswer:\n{res.answer}")

            lines.append("\nUncertainties:")
            for u in res.uncertainties:
                lines.append(f"  - {u}")

            lines.append(f"\nHuman Review:\n  {'REQUIRED' if res.requires_human_review else 'NOT REQUIRED'}")

            lines.append("\nNext Actions:")
            for idx, act in enumerate(res.next_actions, 1):
                lines.append(f"  {idx}. {act}")

            return "\n".join(lines)

        if cmd == "graph" and len(parts) > 2 and parts[1].lower() == "neighbors":
            entity_id = parts[2]
            return _multiline_summary(f"GRAPH NEIGHBORS {entity_id}", backend.get_paths(entity_id))

        if cmd == "copilot":
            if len(parts) < 2:
                return "Usage: copilot <ask|investigate|explain|summarize|evidence|contradictions|timeline|graph|why|next|verify|export> ..."
            from dfap.investigation.copilot import InvestigationCopilot
            copilot = InvestigationCopilot(backend)
            sub = parts[1].lower()
            try:
                if sub == "ask":
                    question = " ".join(parts[2:])
                    return format_json(copilot.ask(question, case_id=active_case_id, entity_id=active_entity_id))
                if sub == "investigate":
                    entity_id = parts[2] if len(parts) > 2 else None
                    if not entity_id:
                        return "Usage: copilot investigate <entity_id>"
                    return format_json(copilot.investigate_entity(entity_id))
                if sub == "explain":
                    finding_id = parts[2] if len(parts) > 2 else None
                    if not finding_id:
                        return "Usage: copilot explain <finding_id>"
                    return format_json(copilot.explain_finding(finding_id))
                if sub == "summarize":
                    case_id = parts[2] if len(parts) > 2 else None
                    if not case_id:
                        return "Usage: copilot summarize <case_id>"
                    return format_json(copilot.summarize_case(case_id))
                if sub == "evidence":
                    finding_id = parts[2] if len(parts) > 2 else None
                    if not finding_id:
                        return "Usage: copilot evidence <finding_id>"
                    return format_json(copilot.evidence_for_finding(finding_id))
                if sub == "contradictions":
                    finding_id = parts[2] if len(parts) > 2 else None
                    if not finding_id:
                        return "Usage: copilot contradictions <finding_id>"
                    return format_json(copilot.contradictions_for_finding(finding_id))
                if sub == "timeline":
                    entity_id = parts[2] if len(parts) > 2 else None
                    if not entity_id:
                        return "Usage: copilot timeline <entity_id>"
                    return format_json(copilot.timeline_for_entity(entity_id))
                if sub == "graph":
                    entity_id = parts[2] if len(parts) > 2 else None
                    if not entity_id:
                        return "Usage: copilot graph <entity_id>"
                    return format_json(copilot.graph_for_entity(entity_id))
                if sub == "why":
                    finding_id = parts[2] if len(parts) > 2 else None
                    if not finding_id:
                        return "Usage: copilot why <finding_id>"
                    return format_json(copilot.explain_finding(finding_id))
                if sub == "next":
                    case_id = parts[2] if len(parts) > 2 else None
                    if not case_id:
                        return "Usage: copilot next <case_id>"
                    return format_json({"case_id": case_id, "suggested_next_actions": copilot.next_actions(case_id)})
                if sub == "verify":
                    finding_id = parts[2] if len(parts) > 2 else None
                    if not finding_id:
                        return "Usage: copilot verify <finding_id>"
                    return format_json(copilot.verify_finding(finding_id))
                if sub == "reliability":
                    finding_id = parts[2] if len(parts) > 2 else None
                    if not finding_id:
                        return "Usage: copilot reliability <finding_id> [case_id]"
                    case_id = parts[3] if len(parts) > 3 else (active_case_id or None)
                    if not case_id:
                        for cid, c_obj in backend.cases.items():
                            if finding_id in c_obj.finding_ids:
                                case_id = cid
                                break
                    if not case_id:
                        return f"No active case containing finding '{finding_id}'."
                    from dfap.investigation.reliability import EvidenceQualityReliabilityEngine
                    engine = EvidenceQualityReliabilityEngine(backend)
                    assessment = engine.assess_finding(case_id, finding_id)
                    return format_json(assessment.to_dict())
                if sub == "source-health":
                    source_id = parts[2] if len(parts) > 2 else None
                    if not source_id:
                        return "Usage: copilot source-health <source_id>"
                    assessment = backend.assess_source_health(source_id)
                    return format_json(assessment)
                if sub == "data-quality":
                    case_id = parts[2] if len(parts) > 2 else (active_case_id or None)
                    if not case_id:
                        return "Usage: copilot data-quality <case_id>"
                    assessment = backend.assess_case_data_health(case_id)
                    return format_json(assessment)
                if sub == "export":
                    case_id = parts[2] if len(parts) > 2 else None
                    if not case_id:
                        return "Usage: copilot export <case_id>"
                    exported = backend.export_case(case_id, export_format="json")
                    return format_json({"case_id": case_id, "export": json.loads(exported)})
                if sub in ("risk", "triage"):
                    target_id = parts[2] if len(parts) > 2 else (active_case_id or None)
                    if not target_id:
                        return "Usage: copilot risk <finding_id|case_id>"
                    if target_id in backend.findings_by_id:
                        res = backend.evaluate_finding_risk(target_id)
                        return format_json(res)
                    else:
                        queue = backend.get_triage_queue(case_id=target_id)
                        return format_json({"case_id": target_id, "triage_queue": queue})
                return f"Unsupported M14 copilot action '{sub}'."
            except Exception as exc:
                return f"ERROR: {exc}"

        if cmd in ("sequence", "temporal"):
            def _resolve_ent(candidate: Optional[str]) -> Optional[str]:
                if candidate and not candidate.startswith("--"):
                    return candidate
                if active_entity_id:
                    return active_entity_id
                if active_case_id and active_case_id in backend.cases:
                    return backend.cases[active_case_id].canonical_entity_id
                return None

            def _no_sequence_error(ent_id: Optional[str]) -> str:
                target = f"entity {ent_id}" if ent_id else "unspecified entity"
                return (
                    f"NO SEQUENCE:\n"
                    f"No temporal events found for {target}.\n\n"
                    f"Guidance to locate valid investigation entities:\n"
                    f"  - Use 'search entity <query>' to locate entities across domains.\n"
                    f"  - Use 'findings' to inspect flagged entities with recorded telemetry.\n"
                    f"  - Use 'timeline <entity_id>' to verify timeline availability.\n"
                    f"  - Use 'cases' or 'scan' to inspect discovered investigation cases."
                )

            sub = parts[1].lower() if len(parts) > 1 else ""
            if sub in ("ablation", "stumpy-dtw") or (sub == "compare" and any("stumpy" in p.lower() for p in parts[2:])):
                ablation = backend.run_temporal_similarity_ablation()
                return (
                    f"TEMPORAL SIMILARITY ABLATION (STUMPY vs DTW)\n\n"
                    f"{ablation['table_markdown']}\n\n"
                    f"Series Length: {ablation['series_length']} events, Query Window: {ablation['window_length']} events.\n"
                    f"Agreement: Same best match window={ablation['comparison']['same_best_match']} "
                    f"(DTW window={ablation['dtw']['matched_window']}, STUMPY window={ablation['stumpy']['matched_window']}).\n\n"
                    f"LIMITATIONS:\n" + "\n".join([f"- {lim}" for lim in ablation['limitations']])
                )

            if sub == "compare":
                if len(parts) < 4:
                    return "Usage: sequence compare <seq_a|entity_a> <seq_b|entity_b>"
                ent_a, ent_b = parts[2], parts[3]
                raw_a = backend.get_timeline(ent_a)
                raw_b = backend.get_timeline(ent_b)
                if not raw_a:
                    return _no_sequence_error(ent_a)
                if not raw_b:
                    return _no_sequence_error(ent_b)
                comp_result = backend.compare_temporal_sequences(ent_a, ent_b)
                return _multiline_summary(f"SEQUENCE COMPARISON: {ent_a} vs {ent_b}", comp_result)


            if sub in ("motifs", "motif"):
                candidate = parts[2] if len(parts) > 2 else None
                ent = _resolve_ent(candidate)
                if not ent:
                    return _no_sequence_error(None)
                raw_events = backend.get_timeline(ent)
                if not raw_events:
                    return _no_sequence_error(ent)
                seq = backend.build_sequence(raw_events, canonical_entity_id=ent)
                predefined = [m.to_dict() for m in backend.detect_sequence_motifs(seq)]
                discovered = [m.to_dict() for m in backend.discover_sequence_motifs(seq)]
                return _multiline_summary(f"SEQUENCE MOTIFS {ent}", {
                    "predefined_motifs": predefined,
                    "discovered_motifs": discovered
                })

            if sub == "patterns":
                candidate = parts[2] if len(parts) > 2 else None
                ent = _resolve_ent(candidate)
                if not ent:
                    return _no_sequence_error(None)
                raw_events = backend.get_timeline(ent)
                if not raw_events:
                    return _no_sequence_error(ent)
                seq = backend.build_sequence(raw_events, canonical_entity_id=ent)
                patterns = backend.detect_sequence_patterns(seq)
                motifs = [m.to_dict() for m in backend.detect_sequence_motifs(seq)]
                discovered = [m.to_dict() for m in backend.discover_sequence_motifs(seq)]
                return _multiline_summary(f"SEQUENCE PATTERNS {ent}", {
                    "patterns": patterns,
                    "predefined_motifs": motifs,
                    "discovered_motifs": discovered
                })

            if sub == "features":
                candidate = parts[2] if len(parts) > 2 else None
                ent = _resolve_ent(candidate)
                if not ent:
                    return _no_sequence_error(None)
                raw_events = backend.get_timeline(ent)
                if not raw_events:
                    return _no_sequence_error(ent)
                seq = backend.build_sequence(raw_events, canonical_entity_id=ent)
                feats = backend.extract_sequence_features(seq)
                return _multiline_summary(f"SEQUENCE FEATURES {ent}", feats.to_dict())

            if sub == "transitions":
                candidate = parts[2] if len(parts) > 2 else None
                ent = _resolve_ent(candidate)
                if not ent:
                    return _no_sequence_error(None)
                raw_events = backend.get_timeline(ent)
                if not raw_events:
                    return _no_sequence_error(ent)
                seq = backend.build_sequence(raw_events, canonical_entity_id=ent)
                transitions = backend.analyze_sequence_transitions(seq)
                serialized = {
                    cat: [t.to_dict() for t in t_list]
                    for cat, t_list in transitions.items()
                }
                return _multiline_summary(f"SEQUENCE TRANSITIONS {ent}", serialized)

            if sub == "phases":
                candidate = parts[2] if len(parts) > 2 else None
                ent = _resolve_ent(candidate)
                if not ent:
                    return _no_sequence_error(None)
                raw_events = backend.get_timeline(ent)
                if not raw_events:
                    return _no_sequence_error(ent)
                seq = backend.build_sequence(raw_events, canonical_entity_id=ent)
                phases = [p.to_dict() for p in backend.compress_sequence_phases(seq)]
                return _multiline_summary(f"SEQUENCE PHASES {ent}", phases)

            # Otherwise: sequence [entity] [--around <event>]
            around_event = None
            candidate = None
            if "--around" in parts:
                idx = parts.index("--around")
                if idx + 1 < len(parts):
                    around_event = parts[idx + 1]
                if idx > 1:
                    candidate = parts[1]
                elif len(parts) > idx + 2:
                    candidate = parts[idx + 2]
            elif len(parts) > 1:
                candidate = parts[1]

            ent = _resolve_ent(candidate)
            if not ent:
                return _no_sequence_error(None)

            raw_events = backend.get_timeline(ent)
            if not raw_events:
                return _no_sequence_error(ent)

            if around_event:
                event_ids = {e.get("event_id") for e in raw_events}
                if around_event not in event_ids:
                    return f"REJECTED: Event '{around_event}' does not belong to entity '{ent}' through the authoritative identity model."

            seq = backend.build_sequence(raw_events, canonical_entity_id=ent)
            timeline_items = backend.format_investigator_timeline(seq, trigger_event_id=around_event)
            title = f"SEQUENCE TIMELINE {ent}" + (f" AROUND {around_event}" if around_event else "")
            return _multiline_summary(title, timeline_items)

        return f"Unsupported M13 command '{cmd}'. Type 'help' for command reference."
    except Exception as exc:
        return f"ERROR: {exc}"


def search_production_data(service: WP4Service, query: str) -> List[Dict[str, Any]]:
    q = query.strip().strip('"').strip("'").lower()
    if not q:
        return []

    results = []

    # 1. Search Findings
    for fid, fnd in service.evidence_engine.findings_by_id.items():
        f_text = f"{fid} {fnd.get('anomaly_type', '')} {fnd.get('entity_id', '')} {fnd.get('status', '')}".lower()
        if q in f_text:
            results.append({
                "type": "Finding",
                "id": fid,
                "entity_id": fnd.get("entity_id"),
                "anomaly_type": fnd.get("anomaly_type"),
                "composite_score": float(fnd.get("composite_score", 0.0)),
                "summary": f"Finding {fid} (Entity: {fnd.get('entity_id')} | Anomaly: {fnd.get('anomaly_type')} | Score: {float(fnd.get('composite_score', 0.0)):.4f})"
            })

    # 2. Search Canonical Events & Actor Names
    for ev_id, ev in service.evidence_engine.events_by_id.items():
        attr_str = json.dumps(ev.get("attributes", {})) if isinstance(ev.get("attributes"), (dict, list)) else str(ev.get("attributes", ""))
        ev_text = f"{ev_id} {ev.get('actor_id', '')} {ev.get('target_id', '')} {ev.get('source_domain', '')} {ev.get('event_type', '')} {attr_str}".lower()
        if q in ev_text:
            actor_name = ""
            attr = ev.get("attributes")
            if isinstance(attr, dict):
                actor_name = attr.get("actor_name") or attr.get("raw_source_attributes", {}).get("caller_name") or ""
            elif isinstance(attr, str):
                try:
                    parsed_attr = json.loads(attr)
                    actor_name = parsed_attr.get("actor_name") or parsed_attr.get("raw_source_attributes", {}).get("caller_name") or ""
                except Exception:
                    pass

            results.append({
                "type": "Event",
                "id": ev_id,
                "actor_id": ev.get("actor_id"),
                "actor_name": actor_name,
                "event_type": ev.get("event_type"),
                "source_domain": ev.get("source_domain"),
                "summary": f"Event {ev_id} (Type: {ev.get('event_type')} | Domain: {ev.get('source_domain')} | Actor: {actor_name or ev.get('actor_id')})"
            })

    # 3. Search Entities
    for _, row in service.evidence_engine.df_entities.iterrows():
        eid = str(row.get("canonical_entity_id", "")).strip()
        row_str = " ".join(str(v) for v in row.values).lower()
        if q in row_str or q in eid.lower():
            if not any(r["type"] == "Entity" and r["id"] == eid for r in results):
                results.append({
                    "type": "Entity",
                    "id": eid,
                    "summary": f"Entity {eid}"
                })

    for ev in results:
        if ev["type"] == "Event" and ev.get("actor_id"):
            actor_id = ev.get("actor_id")
            for fid, fnd in service.evidence_engine.findings_by_id.items():
                e_id = fnd.get("entity_id")
                if e_id and not any(r["type"] == "Entity" and r["id"] == e_id for r in results):
                    raw_eids = fnd.get("event_ids", "[]")
                    if ev["id"] in raw_eids:
                        results.append({
                            "type": "Entity",
                            "id": e_id,
                            "summary": f"Entity {e_id} (Associated Actor: {ev.get('actor_name') or actor_id})"
                        })

    type_order = {"Entity": 0, "Finding": 1, "Event": 2}
    results.sort(key=lambda x: (type_order.get(x["type"], 9), x["id"]))
    return results


def run_interactive_console(service: WP4Service, initial_scenario: str = "escalation"):
    """Starts the interactive terminal investigation & real-data demonstration shell."""
    print("=" * 80)
    print("  DFAP ENTERPRISE INVESTIGATION & REAL PUBLIC DATA REPLAY CONSOLE")
    print("  Version: WP1-WP4 Enterprise Release | Author: Sam Roger X")
    print("=" * 80)
    print("Type 'help' for commands, 'datasets' to view public datasets, 'exit' to quit.\n")

    # Core engines
    pipeline = RealtimeM1M2M3Pipeline(target_entity_id="ENT_1F405CAB3F4951DA", scenario=initial_scenario, seed=42)
    dataset_registry = DatasetRegistry()
    replay_engine = HistoricalReplayEngine(pipeline=pipeline)
    discovery_engine = AutoDiscoveryEngine()
    search_engine = TargetedSearchEngine()
    traversal_engine = InvestigationGraphTraversal()
    cross_investigator = CrossDomainInvestigator()
    case_exporter = CaseDossierExporter()

    # Session State
    active_entity_id = "ENT_1F405CAB3F4951DA"
    active_finding_id = None
    active_case_id = None
    active_dataset = "elliptic"
    discovered_cases_cache: Dict[str, Dict[str, Any]] = {}
    last_search_results = []
    is_paused = False
    m13_backend = InvestigationWorkspaceBackend(output_dir="output", canonical_dir="data/canonical", cases_dir="data/cases")
    register_contradiction_fixture(m13_backend)
    register_reliability_fixture(m13_backend)
    register_data_quality_fixture(m13_backend)
    register_four_domain_fixture(m13_backend)

    while True:
        try:
            prompt_ctx = []
            if active_case_id:
                prompt_ctx.append(f"case:{active_case_id}")
            if active_entity_id:
                prompt_ctx.append(f"entity:{active_entity_id}")
            if replay_engine.active_dataset:
                prompt_ctx.append(f"source:{replay_engine.active_dataset}")
            else:
                prompt_ctx.append(f"scenario:{pipeline.scenario}")
            ctx_str = f" [{', '.join(prompt_ctx)}]"

            line = input(f"\nDFAP{ctx_str} > ").strip()
            if not line:
                continue

            parts = shlex.split(line)
            cmd = parts[0].lower()
            arg = parts[1] if len(parts) > 1 else ""

            if cmd in ("exit", "quit", "q"):
                print("Exiting DFAP Investigation Console.")
                break

            elif cmd in ("help", "?"):
                print("\nAVAILABLE CONSOLE COMMANDS:")
                print("  --- REAL PUBLIC DATASET REPLAY & INVESTIGATION ---")
                print("  datasets                     - List registered public research datasets")
                print("  source <dataset>             - Select dataset for replay & investigation (elliptic | unsw | stackoverflow)")
                print("  scan [dataset] [threshold]   - Run autonomous unsupervised anomaly discovery without pre-defined suspects")
                print("  cases                        - List all discovered and controlled cross-domain investigation cases")
                print("  open <case_id>               - Open and inspect an investigation case dossier")
                print("  profile [entity]             - Compute multi-domain causal behavioral baseline profile (< epoch t)")
                print("  history [entity]             - View chronological event history for an entity")
                print("  backtrack [entity] [ts]      - Forensic Backtracking: 'What happened before this?' (causal backward chain)")
                print("  forwardtrack [entity] [ts]   - Forward Tracking: 'What happened afterward?' (causal subsequent chain)")
                print("  paths <source> <target>      - Find temporal monotonic paths enforcing non-decreasing timestamps")
                print("  common <ent_a> <ent_b>       - Identify shared counterparties or co-occurring nodes")
                print("  why [case_id]                - Explain evidential root-cause and multi-domain contributions")
                print("  evidence [case_id]           - Show cryptographic evidence chain and SHA-256 hashes")
                print("  export [case_id]             - Export case dossier to JSON, Markdown, and Parquet")
                print("  case forensic [case_id]      - Export deterministic forensic case packet (JSON & Markdown)")
                print("  --- M10 TEMPORAL SEQUENCE & INTELLIGENCE ---")
                print("  sequence [entity]            - Deterministic chronological sequence with relative deltas")
                print("  sequence [entity] --around <event> - Sequence centered around a specific trigger event")
                print("  sequence motifs [entity]     - Predefined and unsupervised discovered temporal motifs")
                print("  sequence features [entity]   - Deterministic structural and inter-event timing features")
                print("  sequence patterns [entity]   - Repeated n-gram patterns and behavioral motifs")
                print("  sequence transitions [entity]- Observed event and domain temporal transitions")
                print("  sequence phases [entity]     - Group activity into compressed macro phases")
                print("  sequence compare <ent_a> <ent_b> - Normalized edit-distance & DTW sequence comparison")
                print("  --- REAL-TIME STREAMING & FORENSICS ---")
                print("  stream start [speed/delay]   - Start streaming events (simulated scenario or real public data replay)")
                print("  stream step [n]              - Advance stream by n events")
                print("  stream pause                 - Pause streaming")
                print("  stream resume                - Resume streaming")
                print("  stream stop                  - Stop streaming")
                print("  stream status                - Show streaming pipeline / replay status")
                print("  watch <entity_id>            - Set watch entity for streaming & analysis")
                print("  scenario <name>              - Select simulation scenario (normal | anomaly | escalation)")
                print("  analyze                      - Run real-time Dempster-Shafer evidential fusion across active stream")
                print("  predict                      - Supervised ML multi-horizon (+15m, +30m, +60m) next-state risk projection")
                print("  --- TARGETED SEARCH & PRODUCTION ARTIFACTS ---")
                print("  search <type> <query>        - Targeted search across: name, wallet, ip, account, device, entity")
                print("  select <index | ID>          - Select an item from search results")
                print("  finding [id]                 - Show finding metadata")
                print("  timeline [entity_id]         - Show chronological event timeline")
                print("  network [entity_id]          - Show 2-hop bounded network graph")
                print("  copilot ask \"question\"       - Ask a grounded investigation question")
                print("  copilot explain <finding_id> - Explain why a finding was flagged")
                print("  copilot summarize <case_id>  - Summarize a case with evidence scopes")
                print("  copilot next <case_id>       - Suggest next grounded investigative actions")
                print("  baseline <entity> [status|history] - M8 adaptive behavioral baseline tracking")
                print("  agent investigate \"<question>\" [case_id] - M14 agentic investigation with local Ollama")
                print("  integrity / health           - Verify cryptographic integrity of all 8 frozen baseline contracts")
                print("  exit / quit                  - Exit console")

            # ── 1. DATASETS & SOURCES ─────────────────────────────────────────
            elif cmd == "datasets":
                ds_list = dataset_registry.list_datasets()
                print("\nREGISTERED PUBLIC RESEARCH DATASETS:")
                print(f"{'KEY':14s} | {'NAME':36s} | {'DOMAIN':8s} | {'RECORDS':8s} | {'STATUS'}")
                print("-" * 80)
                for d in ds_list:
                    # Fail-safe record count display: prefer ingested count, fall back to known provenance fields
                    record_count = d.get('ingested_record_count')
                    if record_count is None:
                        # Try other provenance-style keys if present
                        record_count = (
                            d.get('canonical_record_count')
                            or d.get('processed_record_count')
                            or d.get('raw_record_count')
                            or 0
                        )
                    status_str = f"INGESTED ({d.get('ingested_record_count', record_count)} canonical rows)" if d.get('is_ingested') else "RAW ONLY (run 'ingest')"
                    print(f"{d['key']:14s} | {d['name']:36s} | {d['domain']:8s} | {record_count:8d} | {status_str}")

            elif cmd == "source":
                if not arg:
                    print("Usage: source <elliptic | unsw | stackoverflow>")
                    continue
                try:
                    res = replay_engine.load_dataset(arg)
                    active_dataset = arg.lower()
                    print(f"\n[REAL PUBLIC DATA REPLAY LOADED: {arg.upper()}]")
                    print(f"  Total Canonical Events: {res['total_events']:,}")
                    print(f"  Time Range:            {res['start_time']} -> {res['end_time']}")
                    print(f"  Unique Actors:         {res['actors_count']:,}")
                    print("Type 'stream start [1|10|100|1000]' to begin replay, or 'scan' to discover anomalies.")
                except Exception as e:
                    print(f"ERROR loading dataset: {e}")

            # ── 2. AUTO-DISCOVERY & CASES ──────────────────────────────────────
            elif cmd == "scan":
                target_ds = arg.lower() if arg else active_dataset
                thresh = float(parts[2]) if len(parts) > 2 else 0.35
                print(f"\nScanning '{target_ds.upper()}' for emergent behavioral and graph anomalies (threshold={thresh})...")
                cases = discovery_engine.scan_dataset(target_ds, risk_threshold=thresh, max_cases=15)
                if not cases:
                    print("No anomalies crossed the risk threshold in this dataset.")
                else:
                    print(f"\nDISCOVERED {len(cases)} SUSPICIOUS CASES (Ground-truth hidden during detection):")
                    print(f"{'CASE ID':14s} | {'ENTITY ID':32s} | {'RISK':6s} | {'ANOMALY TYPE'}")
                    print("-" * 80)
                    for c in cases:
                        discovered_cases_cache[c["case_id"]] = c
                        print(f"{c['case_id']:14s} | {c['entity_id'][:32]:32s} | {c['risk_score']:6.2f} | {c['anomaly_type']}")
                    print("\nType 'open <case_id>' to investigate any flagged case.")

            elif cmd == "cases":
                cross_cases = cross_investigator.list_cases()
                live_cases = m13_backend.list_cases()
                print("\nALL ACTIVE INVESTIGATION CASES:")
                print("--- Controlled Cross-Domain Cases ---")
                for cc in cross_cases:
                    print(f"  {cc['case_id']:16s} -> Canonical Entity: {cc['canonical_entity_id']} ({', '.join(cc['linked_domains'])}) [CONTROLLED_CASE_MAPPING]")
                if live_cases:
                    print("--- Live Stream & Workspace Cases ---")
                    for case_data in live_cases:
                        case_id = case_data.get("case_id")
                        entity_id = case_data.get("canonical_entity_id")
                        source = case_data.get("search_context", {}).get("source", "WORKSPACE")
                        finding_ids = case_data.get("finding_ids", [])
                        print(f"  {case_id:16s} -> Entity: {entity_id} | Source: {source} | Findings: {finding_ids}")
                if discovered_cases_cache:
                    print("--- Autonomously Discovered Cases ---")
                    for cid, c in discovered_cases_cache.items():
                        print(f"  {cid:16s} -> Entity: {c['entity_id'][:30]} | Risk: {c['risk_score']} | {c['anomaly_type']}")
                print("\nType 'open <case_id>' to inspect.")

            elif cmd == "open":
                if not arg:
                    print("Usage: open <CASE_ID>  (e.g. open CASE-CROSS-001 or open CASE-ELL-001)")
                    continue
                cid = arg.strip().upper()
                if cid.startswith("CASE-CROSS-"):
                    try:
                        res = cross_investigator.investigate_case(cid)
                        active_case_id = cid
                        active_entity_id = res["canonical_entity_id"]
                        try:
                            m13_backend.register_controlled_case({
                                "case_id": cid,
                                "canonical_entity_id": res["canonical_entity_id"],
                                "mapping_status": res["mapping_status"],
                                "search_context": {
                                    "source": "CONTROLLED_CASE_MAPPING",
                                    "mapping_status": res["mapping_status"],
                                    "case_kind": "CONTROLLED_CASE_MAPPING",
                                    "domains_analyzed": res["domains_analyzed"],
                                    "threat_classification": res["threat_classification"],
                                    "fused_composite_score": res["fused_composite_score"],
                                    "domain_evidence_breakdown": res["domain_evidence_breakdown"],
                                    "cross_domain_timeline": res.get("cross_domain_timeline", []),
                                },
                                "fused_composite_score": res["fused_composite_score"],
                                "threat_classification": res["threat_classification"],
                                "domain_evidence_breakdown": res["domain_evidence_breakdown"],
                                "cross_domain_timeline": res.get("cross_domain_timeline", []),
                            })
                        except ValueError:
                            pass
                        print(f"\n=== CONTROLLED CROSS-DOMAIN CASE DOSSIER: {cid} ===")
                        print(f"  Canonical Entity:       {res['canonical_entity_id']}")
                        print(f"  Mapping Status:         {res['mapping_status']}")
                        print(f"  Fused Composite Score:  {res['fused_composite_score']:.4f}")
                        print(f"  Threat Classification:  {res['threat_classification']}")
                        print(f"  Conflict Metric k:      {res['evidential_conflict_metric_k']}")
                        print(f"  Linked Domains:         {res['domains_analyzed']}")
                        print("\nEvidential Contributions:")
                        for dom, ev in res["domain_evidence_breakdown"].items():
                            print(f"  [{dom.upper()}] Score={ev['anomaly_score']:.2f} ({ev['events_count']} events): {', '.join(ev['evidence_reasons'])}")
                        print("\nType 'why', 'profile', 'backtrack', or 'export' to proceed.")
                    except Exception as e:
                        print(f"Error opening cross-domain case: {e}")
                elif cid in discovered_cases_cache:
                    c = discovered_cases_cache[cid]
                    active_case_id = cid
                    active_entity_id = c["entity_id"]
                    if cid not in m13_backend.cases:
                        try:
                            m13_backend.create_case(
                                active_entity_id,
                                case_id=cid,
                                search_context={
                                    "source": str(c.get("dataset", "UNKNOWN")).upper(),
                                    "discovery_run": "AUTO_DISCOVERY",
                                    "anomaly_type": c.get("anomaly_type"),
                                    "risk_score": c.get("risk_score"),
                                },
                            )
                        except Exception:
                            pass
                    print(f"\n=== INVESTIGATION CASE: {cid} ===")
                    print(f"  Entity ID:              {c['entity_id']}")
                    print(f"  Dataset:                {c['dataset'].upper()}")
                    print(f"  Detected Risk Score:    {c['risk_score']}")
                    print(f"  Anomaly Classification: {c['anomaly_type']}")
                    print(f"  Trigger Event ID:       {c['trigger_event_id']} at {c['trigger_timestamp']}")
                    print("  Top Detection Reasons:")
                    for r in c["top_reasons"]:
                        print(f"    - {r}")
                    audit = discovery_engine.reconcile_with_ground_truth(cid)
                    print(f"\n  [Forensic Ground Truth Audit]: {audit['verdict']} (is_anomaly={audit['ground_truth_confirmed_anomaly']})")
                elif cid in m13_backend.cases:
                    c_obj = m13_backend.get_case(cid)
                    active_case_id = cid
                    active_entity_id = c_obj.canonical_entity_id
                    status_val = c_obj.status.value if hasattr(c_obj.status, "value") else c_obj.status
                    print(f"\n=== INVESTIGATION CASE: {cid} ===")
                    print(f"  Entity ID:              {c_obj.canonical_entity_id}")
                    print(f"  Status:                 {status_val}")
                    print(f"  Findings:               {c_obj.finding_ids}")
                    print(f"  Evidence IDs:           {c_obj.evidence_ids}")
                    print(f"  Search Context:         {c_obj.search_context}")
                    print("\nType 'why', 'evidence', or 'copilot' to proceed.")
                else:
                    print(f"Case '{cid}' not found. Run 'scan' or 'cases' to view available cases.")

            # ── 3. BEHAVIORAL PROFILES & TRAVERSAL ────────────────────────────
            elif cmd == "profile":
                target_ent = arg if arg else active_entity_id
                if not target_ent:
                    print("No entity specified or active.")
                    continue
                # Load events from canonical dataset
                can_file = f"data/canonical/{active_dataset}_canonical.parquet"
                if os.path.exists(can_file):
                    df_can = pd.read_parquet(can_file)
                    ent_evts = df_can[(df_can["actor_id"] == target_ent) | (df_can["target_id"] == target_ent)].to_dict(orient="records")
                    if ent_evts:
                        t_max = max(e["epoch_time"] for e in ent_evts)
                        prof = BehavioralProfiler.compute_composite_profile(ent_evts, t_max)
                        print(f"\n=== CAUSAL BEHAVIORAL PROFILE: {target_ent} ===")
                        print(format_json(prof))
                    else:
                        print(f"No events found for entity '{target_ent}' in dataset '{active_dataset}'.")
                else:
                    print(f"Dataset '{active_dataset}' canonical file not found.")

            elif cmd == "history":
                target_ent = arg if arg else active_entity_id
                if pipeline.canonical_events:
                    m13_backend.set_live_stream_events([e.to_dict() for e in pipeline.canonical_events])
                if target_ent:
                    m13_events = m13_backend.get_timeline(target_ent)
                    if m13_events or not os.path.exists(f"data/canonical/{active_dataset}_canonical.parquet"):
                        pivot_arg = f" {parts[2]}" if len(parts) > 2 else ""
                        print(handle_m13_command(m13_backend, f"history {target_ent}{pivot_arg}", active_case_id=active_case_id, active_entity_id=active_entity_id))
                        continue
                can_file = f"data/canonical/{active_dataset}_canonical.parquet"
                if os.path.exists(can_file):
                    df_can = pd.read_parquet(can_file)
                    ent_evts = df_can[(df_can["actor_id"] == target_ent) | (df_can["target_id"] == target_ent)].head(20)
                    print(f"\n=== RECENT HISTORY FOR {target_ent} ({len(ent_evts)} events) ===")
                    print(format_json(ent_evts.to_dict(orient="records")))
                else:
                    print(f"Dataset '{active_dataset}' not found.")

            elif cmd == "backtrack":
                if len(parts) >= 3 and parts[2] and re.fullmatch(r"\d+(?:\.\d+)?[smhd]", str(parts[2]).lower()):
                    print(handle_m13_command(m13_backend, line))
                    continue
                target_ent = arg if arg else active_entity_id
                m13_backend.set_live_stream_events([e.to_dict() for e in pipeline.canonical_events])
                if pipeline.canonical_events:
                    timeline = m13_backend.get_timeline(target_ent)
                    pivot = max(float(e.get("epoch_time", 0.0)) for e in timeline if e.get("epoch_time") is not None) if timeline else None
                    res = {"entity_id": target_ent, "pivot": pivot, "preceding_events": [e for e in timeline if e.get("epoch_time") is not None and (pivot is None or e.get("epoch_time") < pivot)], "event_count": 0, "source": "LIVE_STREAM"}
                    res["event_count"] = len(res["preceding_events"])
                    print(f"\n=== LIVE STREAM BACKTRACK: 'What happened before this?' ===")
                    print(format_json(res))
                    continue
                ts = parts[2] if len(parts) > 2 else None
                res = traversal_engine.backtrack(target_ent, pivot_timestamp=ts, dataset=active_dataset)
                print(f"\n=== FORENSIC BACKTRACKING: 'What happened before this?' ===")
                print(format_json(res))

            elif cmd == "forwardtrack":
                if len(parts) >= 3 and parts[2] and re.fullmatch(r"\d+(?:\.\d+)?[smhd]", str(parts[2]).lower()):
                    print(handle_m13_command(m13_backend, line))
                    continue
                target_ent = arg if arg else active_entity_id
                m13_backend.set_live_stream_events([e.to_dict() for e in pipeline.canonical_events])
                if pipeline.canonical_events:
                    timeline = m13_backend.get_timeline(target_ent)
                    pivot = min(float(e.get("epoch_time", 0.0)) for e in timeline if e.get("epoch_time") is not None) if timeline else None
                    res = {"entity_id": target_ent, "pivot": pivot, "subsequent_events": [e for e in timeline if e.get("epoch_time") is not None and (pivot is None or e.get("epoch_time") > pivot)], "event_count": 0, "source": "LIVE_STREAM"}
                    res["event_count"] = len(res["subsequent_events"])
                    print(f"\n=== LIVE STREAM FORWARDTRACK: 'What happened afterward?' ===")
                    print(format_json(res))
                    continue
                ts = parts[2] if len(parts) > 2 else None
                res = traversal_engine.forwardtrack(target_ent, pivot_timestamp=ts, dataset=active_dataset)
                print(f"\n=== FORWARD TRACKING: 'What happened afterward?' ===")
                print(format_json(res))

            elif cmd == "paths":
                if len(parts) == 2:
                    print(handle_m13_command(m13_backend, line))
                    continue
                if len(parts) < 3:
                    print("Usage: paths <source_entity> <target_entity>")
                    continue
                src = parts[1]
                tgt = parts[2]
                res = traversal_engine.find_temporal_paths(src, tgt, dataset=active_dataset)
                print(f"\n=== TEMPORAL MONOTONIC PATHS ({src} -> {tgt}) ===")
                print(format_json(res))

            elif cmd == "common":
                if len(parts) < 3:
                    print("Usage: common <entity_a> <entity_b>")
                    continue
                res = traversal_engine.find_common_entities(parts[1], parts[2], dataset=active_dataset)
                print(f"\n=== SHARED COUNTERPARTIES / NODES ===")
                print(format_json(res))

            # ── 4. TARGETED SEARCH ────────────────────────────────────────────
            elif cmd == "search":
                if len(parts) >= 3 and parts[1].lower() in ("name", "wallet", "ip", "account", "device", "entity", "phone", "case"):
                    print(handle_m13_command(m13_backend, line))
                    continue
                if not arg:
                    print("Usage: search [name|wallet|ip|account|device|entity] <query>")
                    continue

                if len(parts) >= 3 and parts[1].lower() in ("name", "wallet", "ip", "account", "device", "entity"):
                    q_type = parts[1].lower()
                    q_term = " ".join(parts[2:])
                    t_results = search_engine.search(q_type, q_term)
                    print(f"\nTARGETED SEARCH [{q_type.upper()}]: Found {len(t_results)} match(es):")
                    for idx, tr in enumerate(t_results, start=1):
                        print(f"  [{idx}] {tr['query_type']:14s} : {tr['candidate']} -> {tr['canonical_entity']} (Conf: {tr['confidence']})")
                        print(f"       Dataset: {tr['dataset']} | Evidence: {tr['match_evidence']}")
                else:
                    query_str = " ".join(parts[1:])
                    last_search_results = search_production_data(service, query_str)
                    if not last_search_results:
                        t_fallback = search_engine.search("general", query_str)
                        if t_fallback:
                            print(f"\nTargeted Search Matches ({len(t_fallback)}):")
                            for idx, tr in enumerate(t_fallback, start=1):
                                print(f"  [{idx}] {tr['query_type']:14s} : {tr['candidate']} -> {tr['canonical_entity']} (Conf: {tr['confidence']})")
                        else:
                            print(f"No results found matching: '{query_str}'")
                    else:
                        print(f"\nProduction Matches ({len(last_search_results)}):")
                        for idx, res in enumerate(last_search_results, start=1):
                            print(f"  [{idx}] {res['type']:7s} : {res['id']}  -->  {res['summary']}")

            elif cmd == "export":
                target_case = arg.upper() if arg else active_case_id
                if not target_case:
                    print("No active case to export. Run 'open <case_id>' first.")
                    continue
                if target_case.startswith("CASE-CROSS-"):
                    c_data = cross_investigator.investigate_case(target_case)
                elif target_case in discovered_cases_cache:
                    c_data = discovered_cases_cache[target_case]
                else:
                    print(f"Unknown case: {target_case}")
                    continue
                exp_paths = case_exporter.export_case(c_data, target_case)
                print(f"\n[CASE DOSSIER EXPORTED SUCCESSFULLY]")
                print(f"  JSON:     {exp_paths['json_path']}")
                print(f"  Markdown: {exp_paths['markdown_path']}")
                print(f"  Parquet:  {exp_paths['parquet_path']}")

            # ── 5. STREAM & REPLAY ────────────────────────────────────────────
            elif cmd == "stream":
                subcmd = arg.lower() if arg else "help"
                if subcmd == "start":
                    if replay_engine.active_dataset:
                        sp_val = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 100
                        replay_engine.start(speed=sp_val)
                        print(f"\n[REAL PUBLIC DATA REPLAY: {replay_engine.active_dataset.upper()}] Speed: {sp_val}x")
                        print("Replaying original historical records chronologically...")
                        batch = replay_engine.step(n_events=5)
                        for b in batch:
                            e_info = b.get("event") or b
                            print(f"  [REPLAY EVENT] {e_info.get('event_id')} | {e_info.get('domain')} | {e_info.get('timestamp')} -> {e_info.get('actor_id')}")
                        print(f"Processed 5 events. Cursor: {replay_engine.cursor}/{len(replay_engine.events_df)}. Type 'stream step' to advance.")
                    else:
                        delay = float(parts[2]) if len(parts) > 2 else 0.5
                        pipeline.metrics.state = "RUNNING"
                        is_paused = False
                        print(f"\n[STREAMING REAL-TIME PIPELINE | RUN: {pipeline.run_id} | SCENARIO: {pipeline.scenario.upper()}]")
                        while pipeline.has_next() and not is_paused:
                            step_result = pipeline.process_next_event()
                            if step_result["status"] in ("REJECTED", "DEAD_LETTER"):
                                continue
                            evt = step_result["event"]
                            m1 = step_result["m1"]
                            m2 = step_result["m2"]
                            m3 = step_result["m3"]
                            print(f"[EVENT] {evt['domain']} {evt['type']} -> M1 {m1['canonical_event_id']} | M2 Nodes {m2['graph_nodes_count']} | M3 Score {m3['composite_score']:.3f}")
                            time.sleep(delay)

                elif subcmd == "step":
                    n_step = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 1
                    if replay_engine.active_dataset:
                        batch = replay_engine.step(n_events=n_step)
                        for b in batch:
                            e_info = b.get("event") or b
                            print(f"  [REPLAY EVENT] {e_info.get('event_id')} | {e_info.get('domain')} | {e_info.get('timestamp')} -> {e_info.get('actor_id')}")
                    else:
                        step_result = pipeline.process_next_event()
                        print(format_json(step_result))

                elif subcmd == "pause":
                    if replay_engine.active_dataset:
                        print(format_json(replay_engine.pause()))
                    else:
                        pipeline.metrics.state = "PAUSED"
                        print("Stream PAUSED.")

                elif subcmd == "resume":
                    if replay_engine.active_dataset:
                        print(format_json(replay_engine.resume()))
                    else:
                        pipeline.metrics.state = "RUNNING"
                        print("Stream RESUMED.")

                elif subcmd == "stop":
                    if replay_engine.active_dataset:
                        print(format_json(replay_engine.stop()))
                    else:
                        pipeline.metrics.state = "STOPPED"
                        print("Stream STOPPED.")

                elif subcmd == "status":
                    if replay_engine.active_dataset:
                        print(format_json(replay_engine.status()))
                    else:
                        print(format_json(asdict(pipeline.metrics)))

            # ── 6. EXISTING PIPELINE & BASELINE COMMANDS ──────────────────────
            elif cmd == "watch":
                active_entity_id = arg.strip()
                pipeline = RealtimeM1M2M3Pipeline(target_entity_id=active_entity_id, scenario=pipeline.scenario, seed=pipeline.seed)
                print(f"Now watching entity: {active_entity_id}")

            elif cmd == "scenario":
                pipeline = RealtimeM1M2M3Pipeline(target_entity_id=active_entity_id, scenario=arg, seed=pipeline.seed)
                print(f"Switched scenario to: {arg.upper()}")

            elif cmd == "analyze":
                analysis = pipeline.analyze()
                if pipeline.live_finding:
                    _register_live_stream_finding_to_workspace(m13_backend, pipeline, active_entity_id)
                    case_id = None
                    for cid, case in m13_backend.cases.items():
                        if case.canonical_entity_id == active_entity_id and case.search_context.get("source") == "LIVE_STREAM_FINDING":
                            case_id = cid
                            break
                    if case_id is not None:
                        active_case_id = case_id
                        analysis["live_case_id"] = case_id
                print(format_json(analysis))

            elif cmd == "predict":
                print(format_json(pipeline.predict_next_state()))

            elif cmd == "why":
                target_case_id = arg if arg and arg in m13_backend.cases else (active_case_id if active_case_id and active_case_id in m13_backend.cases else None)
                if target_case_id is not None:
                    case = m13_backend.get_case(target_case_id)
                    if target_case_id.startswith("CASE-CROSS-") and case.search_context.get("mapping_status") == "CONTROLLED_CASE_MAPPING":
                        res = cross_investigator.investigate_case(target_case_id)
                        case_summary = {
                            "case_id": target_case_id,
                            "canonical_entity_id": case.canonical_entity_id,
                            "mapping_status": "CONTROLLED_CASE_MAPPING",
                            "status": case.status,
                            "fused_composite_score": res.get("fused_composite_score"),
                            "threat_classification": res.get("threat_classification"),
                            "domain_evidence_breakdown": res.get("domain_evidence_breakdown", {}),
                            "cross_domain_timeline": res.get("cross_domain_timeline", []),
                            "answer": "This controlled cross-domain case is suspicious because it combines domain-specific evidence and the fusion engine signal under a controlled case mapping proxy.",
                            "confidence": float(res.get("fused_composite_score", 0.0)),
                            "status": "PARTIALLY_GROUNDED",
                            "evidence_refs": list({ev.get("evidence_ref") for dom in res.get("domain_evidence_breakdown", {}).values() for ev in [dom]}) if False else [],
                            "provenance_refs": case.provenance_refs,
                            "mapping_provenance": case.search_context.get("mapping_provenance", []),
                            "domains_analyzed": res.get("domains_analyzed", []),
                            "notes": "Native dataset event history is not asserted for this bridge entity; only controlled cross-domain evidence is available."
                        }
                        print(format_json(case_summary))
                        continue
                    if case.finding_ids:
                        print(format_json({"case_id": target_case_id, "entity_id": case.canonical_entity_id, "findings": [m13_backend.get_finding(fid) for fid in case.finding_ids], "evidence": [m13_backend.evidence_engine.get_evidence(eid).to_dict() for eid in sorted(set(sum([m13_backend.evidence_engine.finding_evidence_map.get(fid, []) for fid in case.finding_ids], []))) if m13_backend.evidence_engine.get_evidence(eid) is not None]}))
                        continue
                    case_summary = {
                        "case_id": target_case_id,
                        "entity_id": case.canonical_entity_id,
                        "status": case.status,
                        "dataset": str(case.search_context.get("source", active_dataset)).upper(),
                        "anomaly_type": case.search_context.get("anomaly_type"),
                        "risk_score": case.search_context.get("risk_score"),
                        "findings": [],
                        "evidence": [],
                        "answer": "The active case exists but has no grounded attached finding or evidence chain; no unrelated stale finding is used.",
                        "confidence": 0.0,
                        "status_code": "INSUFFICIENT_EVIDENCE",
                    }
                    print(format_json(case_summary))
                    continue
                if active_case_id and active_case_id.startswith("CASE-CROSS-"):
                    res = cross_investigator.investigate_case(active_case_id)
                    print(format_json(res["domain_evidence_breakdown"]))
                elif pipeline.canonical_events:
                    print(format_json(pipeline.why()))
                elif active_finding_id:
                    print(format_json(service.get_evidence_chain(active_finding_id)))
                else:
                    print("No active anomaly, case, or finding to explain.")

            elif cmd == "evidence":
                fid = arg or active_finding_id or active_case_id
                if fid and fid in m13_backend.cases and not fid.startswith("CASE-CROSS-"):
                    case = m13_backend.get_case(fid)
                    evidence_ids = list(case.evidence_ids)
                    for finding_id in case.finding_ids:
                        evidence_ids.extend(m13_backend.evidence_engine.finding_evidence_map.get(finding_id, []))
                    evidence_ids = sorted(set(evidence_ids))
                    print(format_json({"case_id": fid, "entity_id": case.canonical_entity_id, "finding_ids": case.finding_ids, "evidence_ids": evidence_ids, "evidence": [m13_backend.evidence_engine.get_evidence(eid).to_dict() for eid in evidence_ids if m13_backend.evidence_engine.get_evidence(eid) is not None]}))
                    continue
                if fid and fid.startswith("CASE-CROSS-"):
                    case = m13_backend.get_case(fid) if fid in m13_backend.cases else m13_backend.register_controlled_case({
                        "case_id": fid,
                        "canonical_entity_id": cross_investigator.investigate_case(fid)["canonical_entity_id"],
                        "mapping_status": "CONTROLLED_CASE_MAPPING",
                        "search_context": {"source": "CONTROLLED_CASE_MAPPING", "mapping_status": "CONTROLLED_CASE_MAPPING"},
                    })
                    res = cross_investigator.investigate_case(fid)
                    print(format_json({
                        "case_id": fid,
                        "canonical_entity_id": case.canonical_entity_id,
                        "mapping_status": "CONTROLLED_CASE_MAPPING",
                        "domain_evidence_breakdown": res.get("domain_evidence_breakdown", {}),
                        "cross_domain_timeline": res.get("cross_domain_timeline", []),
                        "evidence": res.get("domain_evidence_breakdown", {}),
                        "status": "CONTROLLED_CASE_MAPPING",
                    }))
                    continue
                if fid and fid.startswith("FND_"):
                    print(format_json(service.get_evidence_chain(fid)))
                elif fid and fid.startswith("CASE-"):
                    if fid.startswith("CASE-CROSS-"):
                        print(format_json(cross_investigator.investigate_case(fid)))
                    else:
                        print(format_json(discovery_engine.reconcile_with_ground_truth(fid)))
                else:
                    print("Usage: evidence <finding_id | case_id>")

            elif cmd == "timeline":
                if len(parts) >= 2 and parts[1] and not parts[1].startswith("--"):
                    print(handle_m13_command(m13_backend, line, active_case_id=active_case_id, active_entity_id=active_entity_id))
                    continue
                target_ent = arg if arg else active_entity_id
                if pipeline.canonical_events:
                    print(format_json(pipeline.get_timeline()))
                elif target_ent:
                    print(handle_m13_command(m13_backend, f"timeline {target_ent}", active_case_id=active_case_id, active_entity_id=active_entity_id))

            elif cmd in ("network", "subgraph"):
                target_ent = arg if arg else active_entity_id
                if pipeline.canonical_events:
                    print(format_json(pipeline.get_network()))
                elif target_ent:
                    print(format_json(service.get_entity_subgraph(target_ent, hops=2)))

            elif cmd in ("provenance", "prov"):
                if len(parts) >= 2:
                    print(handle_m13_command(m13_backend, line))
                    continue
                fid = arg or active_finding_id
                if fid:
                    chain = service.get_evidence_chain(fid)
                    print(format_json(chain.get("prov_o_document", {})))

            elif cmd in ("findings", "list"):
                if len(parts) >= 2:
                    print(handle_m13_command(m13_backend, line))
                    continue
                print(format_json(service.list_findings()))

            elif cmd in ("integrity", "health"):
                print(format_json(service.verify_upstream_integrity()))

            elif cmd == "select":
                if not arg:
                    print("Usage: select <result_number | ID>")
                    continue
                if arg.isdigit() and last_search_results:
                    num = int(arg)
                    selected_item = last_search_results[num - 1]
                    if selected_item["type"] == "Finding":
                        active_finding_id = selected_item["id"]
                    elif selected_item["type"] == "Entity":
                        active_entity_id = selected_item["id"]
                    print(f"Selected: {selected_item['type']} {selected_item['id']}")
                else:
                    print("Invalid selection.")

            elif cmd == "case":
                if len(parts) == 2:
                    print(handle_m13_command(m13_backend, f"case show {parts[1]}", active_case_id=active_case_id, active_entity_id=active_entity_id))
                    continue
                print(handle_m13_command(m13_backend, line, active_case_id=active_case_id, active_entity_id=active_entity_id))

            elif cmd == "finding":
                if len(parts) == 2:
                    print(handle_m13_command(m13_backend, f"finding show {parts[1]}", active_case_id=active_case_id, active_entity_id=active_entity_id))
                    continue
                print(handle_m13_command(m13_backend, line, active_case_id=active_case_id, active_entity_id=active_entity_id))

            elif cmd in ("risk", "triage", "explain", "graphml"):
                print(handle_m13_command(m13_backend, line, active_case_id=active_case_id, active_entity_id=active_entity_id))

            elif cmd == "evidence":
                if len(parts) == 2:
                    print(handle_m13_command(m13_backend, f"evidence show {parts[1]}", active_case_id=active_case_id, active_entity_id=active_entity_id))
                    continue
                print(handle_m13_command(m13_backend, line, active_case_id=active_case_id, active_entity_id=active_entity_id))

            elif cmd == "copilot":
                print(handle_m13_command(m13_backend, line, active_case_id=active_case_id, active_entity_id=active_entity_id))

            elif cmd == "sequence":
                if pipeline.canonical_events:
                    m13_backend.set_live_stream_events([e.to_dict() for e in pipeline.canonical_events])
                if len(parts) >= 2:
                    potential_ent = None
                    if parts[1].lower() in ("features", "patterns", "transitions", "phases"):
                        if len(parts) >= 3 and not parts[2].startswith("--"):
                            potential_ent = parts[2]
                    elif not parts[1].startswith("--") and parts[1].lower() != "compare":
                        potential_ent = parts[1]
                    if potential_ent and m13_backend.get_timeline(potential_ent):
                        active_entity_id = potential_ent
                print(handle_m13_command(m13_backend, line, active_case_id=active_case_id, active_entity_id=active_entity_id))

            elif cmd == "baseline":
                print(handle_m13_command(m13_backend, line, active_case_id=active_case_id, active_entity_id=active_entity_id))

            elif cmd == "agent":
                print(handle_m13_command(m13_backend, line, active_case_id=active_case_id, active_entity_id=active_entity_id))

            else:
                print(f"Unknown command: '{cmd}'. Type 'help' for available commands.")

        except Exception as e:
            print(f"ERROR: {str(e)}", file=sys.stderr)


def main(args: List[str] = None):
    if args is None:
        args = sys.argv[1:]


    if args and args[0] in ("language", "prompts"):
        from dfap.investigation.cli_features5_6 import main as features5_6_main
        sys.argv = [sys.argv[0]] + args
        features5_6_main()
        return
    if args and args[0] == "query":
        from dfap.investigation.cli_feature1 import main as query_main
        query_main(args[1:])
        return
    if args and args[0] == "narrative":
        from dfap.investigation.cli_feature2 import run_smoke_test as narrative_main
        narrative_main()
        return
    if args and args[0] in ("decision", "events"):
        from dfap.investigation.cli_event_sourcing import main as event_sourcing_main
        event_sourcing_main(args[1:])
        return
    if args and args[0] == "paper3":
        from dfap.experiments.cli_paper3 import main as paper3_main
        paper3_main(args[1:])
        return
    if args and args[0] == "experiment":
        if len(args) > 1 and args[1] == "paper1":
            from dfap.experiments.cli_paper1 import main as paper1_main
            paper1_main(args[2:])
            return
        elif len(args) > 1 and args[1] == "paper3":
            from dfap.experiments.cli_paper3 import main as paper3_main
            paper3_main(args[2:])
            return

    # ── M13 Non-interactive CLI dispatch ─────────────────────────────────────
    # Commands implemented in handle_m13_command() were only reachable via the
    # interactive console. These dispatch blocks expose them as top-level CLI
    # subcommands without changing any business logic.
    #
    # Covered: case, sequence, agent, graph, graphml, baseline, explain,
    #          risk/triage, copilot, and the 'finding explain'/'finding risk'
    #          subcommands of finding.
    #
    # The existing argparse subcommands (console, health, findings, ingest,
    # search, finding <id>, evidence, timeline, subgraph, datasets, scan,
    # profile, history, backtrack, forwardtrack, paths, why) are all
    # preserved unchanged below.
    _M13_TOP_COMMANDS = {
        "case", "sequence", "agent", "graph", "graphml",
        "baseline", "explain", "copilot", "ldrm",
    }
    _M13_RISK_ALIASES = {"risk", "triage"}

    def _make_m13_backend():
        """Initialise the M13 backend with the four-domain fixture (same as interactive console)."""
        from dfap.investigation.workspace import InvestigationWorkspaceBackend
        from dfap.investigation.conflict_fixture import register_contradiction_fixture
        from dfap.investigation.reliability_fixture import register_reliability_fixture
        from dfap.investigation.data_quality_fixture import register_data_quality_fixture
        from dfap.investigation.four_domain_fixture import register_four_domain_fixture
        backend = InvestigationWorkspaceBackend(
            output_dir="output",
            canonical_dir="data/canonical",
            cases_dir="data/cases",
        )
        register_contradiction_fixture(backend)
        register_reliability_fixture(backend)
        register_data_quality_fixture(backend)
        register_four_domain_fixture(backend)
        return backend

    if args and args[0] in _M13_TOP_COMMANDS:
        cmd_line = shlex.join(args)
        m13_backend = _make_m13_backend()
        result = handle_m13_command(m13_backend, cmd_line)
        print(result)
        return

    if args and args[0] in _M13_RISK_ALIASES:
        cmd_line = shlex.join(args)
    
        result = handle_m13_command(m13_backend, cmd_line)
        print(result)
        return

    # 'finding' already has an argparse subcommand for 'finding <id>' (simple lookup).
    # Extend it here to also handle 'finding explain <id>' and 'finding risk <id>'
    # which are M13 subcommands not registered in argparse.
    if (
        args
        and args[0] == "finding"
        and len(args) >= 2
        and args[1].lower() in ("explain", "risk", "shap", "triage")
    ):
        cmd_line = shlex.join(args)
    
        result = handle_m13_command(m13_backend, cmd_line)
        print(result)
        return

    parser = argparse.ArgumentParser(
        prog="dfap.wp4.cli",
        description="DFAP Investigation Workspace & Real Public Data Replay Console"
    )
    parser.add_argument("--data-dir", default="output", help="Path to DFAP output artifacts directory")
    parser.add_argument("--scenario", default="escalation", choices=["normal", "anomaly", "escalation"])

    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    subparsers.add_parser("console", help="Starts interactive investigation console")
    subparsers.add_parser("interactive", help="Alias for console")
    subparsers.add_parser("health", help="Verifies system health and baseline contract integrity")
    subparsers.add_parser("integrity", help="Verifies baseline integrity")
    subparsers.add_parser("findings", help="Lists production findings")

    # Ingest subcommand (Phase 3)
    p_ingest = subparsers.add_parser("ingest", help="Ingests real public datasets into data/canonical/")
    p_ingest.add_argument("dataset", choices=["elliptic", "unsw", "stackoverflow", "all"], help="Dataset to ingest")

    # Search
    p_search = subparsers.add_parser("search", help="Searches findings, entities, wallets, IPs, and names")
    p_search.add_argument("query", help="Search query")

    # Finding

    # M13 Commands
    subparsers.add_parser("case", help="Case-level forensic and risk commands")
    subparsers.add_parser("sequence", help="Temporal and sequence commands")
    subparsers.add_parser("agent", help="Agentic investigation commands")
    subparsers.add_parser("graph", help="Graph ML commands")
    subparsers.add_parser("graphml", help="Graph ML benchmark commands")
    subparsers.add_parser("risk", help="Risk triage commands")
    subparsers.add_parser("explain", help="Explainability commands")
    subparsers.add_parser("copilot", help="Copilot commands")

    p_finding = subparsers.add_parser("finding", help="Retrieves finding metadata")
    p_finding.add_argument("finding_id", help="Finding ID")

    # Evidence
    p_evidence = subparsers.add_parser("evidence", help="Resolves full evidence chain")
    p_evidence.add_argument("finding_id", help="Finding ID")

    # Timeline
    p_timeline = subparsers.add_parser("timeline", help="Extracts timeline for entity")
    p_timeline.add_argument("entity_id", help="Entity ID")
    p_timeline.add_argument("--start", default=None)
    p_timeline.add_argument("--end", default=None)

    # Subgraph
    p_subgraph = subparsers.add_parser("subgraph", help="Extracts bounded 2-hop subgraph")
    p_subgraph.add_argument("entity_id", help="Entity ID")
    p_subgraph.add_argument("--hops", type=int, default=2)
    p_subgraph.add_argument("--cytoscape", action="store_true")

    # Phase 3 Temporal Investigation Subcommands
    subparsers.add_parser("datasets", help="Lists canonical datasets with temporal semantics and provenance")

    p_scan = subparsers.add_parser("scan", help="Runs unsupervised anomaly discovery over canonical dataset")
    p_scan.add_argument("dataset", choices=["elliptic", "unsw", "stackoverflow"], help="Dataset name")
    p_scan.add_argument("--threshold", type=float, default=0.35, help="Anomaly risk threshold")
    p_scan.add_argument("--max-cases", type=int, default=10, help="Maximum discovered cases")

    p_prof = subparsers.add_parser("profile", help="Extracts causal behavioral profile snapshot at pivot")
    p_prof.add_argument("entity_id", help="Entity ID")
    p_prof.add_argument("--pivot", default=None, help="Pivot timestamp or epoch (events <= pivot)")
    p_prof.add_argument("--dataset", default=None, help="Canonical dataset name")

    p_hist = subparsers.add_parser("history", help="Extracts entity history (Ordered vs Chronological)")
    p_hist.add_argument("entity_id", help="Entity ID")
    p_hist.add_argument("--dataset", default=None, help="Canonical dataset name")

    p_back = subparsers.add_parser("backtrack", help="Preceding event traversal (Backtracking)")
    p_back.add_argument("entity_id", help="Entity ID")
    p_back.add_argument("--pivot", default=None, help="Pivot timestamp/epoch")
    p_back.add_argument("--dataset", default=None, help="Canonical dataset name")

    p_fwd = subparsers.add_parser("forwardtrack", help="Subsequent event traversal (Observed Future History)")
    p_fwd.add_argument("entity_id", help="Entity ID")
    p_fwd.add_argument("--pivot", default=None, help="Pivot timestamp/epoch")
    p_fwd.add_argument("--dataset", default=None, help="Canonical dataset name")

    p_paths = subparsers.add_parser("paths", help="Finds monotonic temporal paths between two entities")
    p_paths.add_argument("source_entity", help="Source entity ID")
    p_paths.add_argument("target_entity", help="Target entity ID")
    p_paths.add_argument("--dataset", default=None, help="Canonical dataset name")
    p_paths.add_argument("--max-hops", type=int, default=3, help="Max hops")

    p_why = subparsers.add_parser("why", help="Explains deviations and evidence for entity or finding")
    p_why.add_argument("target", help="Entity ID or Finding ID")
    p_why.add_argument("--dataset", default=None, help="Canonical dataset name")

    parsed = parser.parse_args(args)

    try:
        service = WP4Service(data_dir=parsed.data_dir)

        if parsed.command is None or parsed.command in ("console", "interactive"):
            run_interactive_console(service, initial_scenario=getattr(parsed, "scenario", "escalation"))

        elif parsed.command == "ingest":
            from dfap.data.dataset_registry import MissingRealDatasetError
            reg = DatasetRegistry()
            targets = ["elliptic", "unsw", "stackoverflow"] if parsed.dataset == "all" else [parsed.dataset]
            for t in targets:
                try:
                    res = reg.ingest(t)
                    print(f"[{t.upper()} INGESTION SUCCESSFUL]")
                    print(f"  Provenance Tier:         {res['provenance_tier']}")
                    print(f"  Canonical Records Count: {res['canonical_records_count']:,}")
                    print(f"  Canonical SHA-256:       {res['canonical_sha256']}")
                    print(f"  Source File Hashes:      {res['source_file_hashes']}")
                    print(f"  Schema Fingerprint:      {res['schema_fingerprint']}")
                    print(f"  Manifest Saved:          {res['provenance_manifest_path']}\n")
                except MissingRealDatasetError as e:
                    print(f"[{t.upper()} FAIL-CLOSED - AUTHENTIC SOURCE MISSING]")
                    print(f"  Error: {e}\n")

        elif parsed.command in ("health", "integrity"):
            print(format_json(service.verify_upstream_integrity()))

        elif parsed.command == "findings":
            print(format_json(service.list_findings()))

        elif parsed.command == "search":
            print(format_json(search_production_data(service, parsed.query)))

        elif parsed.command == "finding":
            print(format_json(service.get_finding(parsed.finding_id)))

        elif parsed.command == "evidence":
            target = parsed.finding_id
            if target.startswith("EVT_"):
                engine = TemporalEventEngine()
                found_evt = None
                for ds_key, df in engine.datasets.items():
                    sub = df[df["event_id"] == target]
                    if not sub.empty:
                        found_evt = sub.iloc[0].to_dict()
                        found_evt["dataset"] = ds_key
                        break
                if not found_evt:
                    prod_ev = service.evidence_engine.events_by_id.get(target)
                    if prod_ev:
                        found_evt = dict(prod_ev)
                        found_evt["dataset"] = "DFAP Production Baseline"
                if found_evt:
                    print(format_json({
                        "query_type": "EVENT_EVIDENCE",
                        "event_id": target,
                        "dataset": found_evt.get("dataset"),
                        "temporal_semantics": found_evt.get("temporal_semantics", "OBSERVED_TIMESTAMP"),
                        "evidence_ref": f"hash:{str(found_evt.get('sha256_hash', ''))[:16]}",
                        "event_record": found_evt
                    }))
                else:
                    print(format_json({"error": f"Event '{target}' not found in canonical ledgers."}))
            else:
                print(format_json(service.get_evidence_chain(target)))

        elif parsed.command == "timeline":
            print(format_json(service.get_entity_timeline(parsed.entity_id, start=parsed.start, end=parsed.end)))

        elif parsed.command == "subgraph":
            if parsed.cytoscape:
                print(format_json(service.get_cytoscape_payload(parsed.entity_id, hops=parsed.hops)))
            else:
                print(format_json(service.get_entity_subgraph(parsed.entity_id, hops=parsed.hops)))

        elif parsed.command == "datasets":
            engine = TemporalEventEngine()
            results = []
            for ds_name in ["stackoverflow", "unsw", "elliptic"]:
                p = f"data/canonical/{ds_name}_canonical.parquet"
                manifest_p = f"data/canonical/{ds_name}_provenance_manifest.json"
                if os.path.exists(p):
                    df = pd.read_parquet(p)
                    sem = df["temporal_semantics"].iloc[0] if "temporal_semantics" in df.columns else "OBSERVED_TIMESTAMP"
                    manifest = json.load(open(manifest_p)) if os.path.exists(manifest_p) else {}
                    results.append({
                        "dataset": ds_name.upper(),
                        "status": "AVAILABLE",
                        "provenance_tier": manifest.get("provenance_tier", "REAL_PUBLIC_DATA"),
                        "canonical_records": len(df),
                        "temporal_semantics": sem,
                        "temporal_nature": "CHRONOLOGICAL_TIME" if sem == "OBSERVED_TIMESTAMP" else "ORDERED_SEQUENCE_SURROGATE",
                        "source_sha256": manifest.get("source_file_hashes", {}),
                        "canonical_path": p
                    })
                else:
                    results.append({
                        "dataset": ds_name.upper(),
                        "status": "FAIL_CLOSED_MISSING_REAL_SOURCE",
                        "temporal_semantics": "UNKNOWN_TIMESTAMP",
                        "note": "Operator manual acquisition pending."
                    })
            print(format_json(results))

        elif parsed.command == "scan":
            disc = AutoDiscoveryEngine()
            cases = disc.scan_dataset(parsed.dataset, risk_threshold=parsed.threshold, max_cases=parsed.max_cases)
            print(format_json(cases))

        elif parsed.command == "profile":
            engine = TemporalEventEngine()
            prof = engine.build_profile(parsed.entity_id, pivot=parsed.pivot or float("inf"), dataset=parsed.dataset)
            print(format_json(prof))

        elif parsed.command == "history":
            engine = TemporalEventEngine()
            hist = engine.get_entity_history(parsed.entity_id, dataset=parsed.dataset)
            print(format_json(hist))

        elif parsed.command == "backtrack":
            engine = TemporalEventEngine()
            bt = engine.backtrack(parsed.entity_id, pivot=parsed.pivot or float("inf"), dataset=parsed.dataset)
            print(format_json(bt))

        elif parsed.command == "forwardtrack":
            engine = TemporalEventEngine()
            ft = engine.forwardtrack(parsed.entity_id, pivot=parsed.pivot or 0.0, dataset=parsed.dataset)
            print(format_json(ft))

        elif parsed.command == "paths":
            engine = TemporalEventEngine()
            res = engine.find_temporal_paths(parsed.source_entity, parsed.target_entity, dataset=parsed.dataset, max_hops=parsed.max_hops)
            print(format_json(res))

        elif parsed.command == "why":
            target = parsed.target
            fnd = service.evidence_engine.findings_by_id.get(target)
            if fnd:
                print(format_json({
                    "target_type": "FINDING",
                    "finding_id": target,
                    "entity_id": fnd.get("entity_id"),
                    "anomaly_type": fnd.get("anomaly_type"),
                    "composite_score": fnd.get("composite_score"),
                    "explanation": fnd.get("reasons", []),
                    "evidence_chain": service.get_evidence_chain(target)
                }))
            else:
                engine = TemporalEventEngine()
                hist = engine.get_entity_history(target, dataset=parsed.dataset)
                evts = engine.events_for_entity(target, dataset=parsed.dataset)
                if evts:
                    pivot_evt = evts[-1]
                    pivot_analysis = engine.analyze_pivot(target, pivot_event_id=pivot_evt["event_id"], dataset=parsed.dataset)
                    print(format_json({
                        "target_type": "ENTITY_DEVIATION_ANALYSIS",
                        "entity_id": target,
                        "history_summary": hist,
                        "pivot_analysis": pivot_analysis
                    }))
                else:
                    print(format_json({"error": f"Target '{target}' not found in findings or canonical datasets."}))

    except Exception as e:
        print(f"ERROR: {str(e)}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
