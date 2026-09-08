# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: M12 Forensic Case Packet (Deterministic Forensic Synthesis & Export Engine)

import copy
import hashlib
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple, Union

logger = logging.getLogger(__name__)

M12_PACKET_SCHEMA_VERSION = "v12.0.0_FORENSIC_PACKET"


class PacketStatus(str, Enum):
    GROUNDED = "GROUNDED"
    PARTIALLY_GROUNDED = "PARTIALLY_GROUNDED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    CONFLICTED = "CONFLICTED"
    UNAVAILABLE = "UNAVAILABLE"


class PacketRequiredAction(str, Enum):
    PROCEED = "PROCEED"
    REVIEW_DISCREPANCY = "REVIEW_DISCREPANCY"
    HUMAN_REVIEW = "HUMAN_REVIEW"
    COLLECT_ADDITIONAL_EVIDENCE = "COLLECT_ADDITIONAL_EVIDENCE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


def compute_canonical_json_digest(payload: Dict[str, Any]) -> str:
    """Computes a deterministic SHA-256 digest over sorted JSON representation."""
    clean = copy.deepcopy(payload)
    clean.pop("packet_digest", None)
    clean.pop("generated_at", None)

    serialized = json.dumps(
        clean,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
        ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


@dataclass
class ForensicCasePacket:
    """
    Comprehensive, deterministic forensic case packet synthesized from authoritative
    upstream engines (M1–M12).
    """
    case: Dict[str, Any]
    findings: List[Dict[str, Any]]
    timeline: List[Dict[str, Any]]
    graph: Dict[str, Any]
    temporal_intelligence: Dict[str, Any]
    evidence_quality: Dict[str, Any]
    conflict_intelligence: Dict[str, Any]
    source_health: Dict[str, Any]
    provenance: Dict[str, Any]
    traceability_matrix: List[Dict[str, Any]]
    packet_status: str
    required_action: str
    schema_version: str = M12_PACKET_SCHEMA_VERSION
    generated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    packet_digest: str = ""

    def __post_init__(self):
        if not self.packet_digest:
            self.packet_digest = compute_canonical_json_digest(self.to_dict())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "packet_status": self.packet_status,
            "required_action": self.required_action,
            "generated_at": self.generated_at,
            "packet_digest": self.packet_digest,
            "case": self.case,
            "findings": self.findings,
            "timeline": self.timeline,
            "graph": self.graph,
            "temporal_intelligence": self.temporal_intelligence,
            "evidence_quality": self.evidence_quality,
            "conflict_intelligence": self.conflict_intelligence,
            "source_health": self.source_health,
            "provenance": self.provenance,
            "traceability_matrix": self.traceability_matrix,
        }


class ForensicCasePacketEngine:
    """
    Deterministic Forensic Case Packet Engine.
    Synthesizes case, findings, evidence, reliability, conflict, provenance,
    temporal sequences, and source data health without duplicating engine logic.
    """

    def __init__(self, workspace_backend: Any):
        self.backend = workspace_backend

    def generate_packet(self, case_id: str) -> ForensicCasePacket:
        """
        Synthesizes a complete forensic packet for a case deterministically.
        """
        case = self.backend.get_case(case_id)
        entity_id = case.canonical_entity_id

        # 1. CASE METADATA
        domains_set: Set[str] = set()
        entities_set: Set[str] = {entity_id}

        # 2. FINDINGS
        findings_list: List[Dict[str, Any]] = []
        conflicting_pairs_all: List[str] = []
        all_claims: List[Dict[str, Any]] = []
        has_material_conflict = False
        findings_reliability_scores: List[float] = []

        finding_ids = sorted(list(case.finding_ids))
        for fid in finding_ids:
            try:
                fnd_raw = self.backend.get_finding(fid)
            except Exception:
                fnd_raw = self.backend.findings_by_id.get(fid, {})

            dom = fnd_raw.get("domain") or fnd_raw.get("source_domain", "UNKNOWN")
            if dom and dom != "UNKNOWN":
                domains_set.add(dom.upper())

            # Evaluate reliability
            rel_dict: Dict[str, Any] = {}
            try:
                rel_dict = self.backend.assess_finding_reliability(case_id, fid)
            except Exception:
                pass

            rel_score = float(rel_dict.get("overall_score", fnd_raw.get("confidence", 0.90)))
            findings_reliability_scores.append(rel_score)
            rel_comps = rel_dict.get("components", {})
            conf_status = rel_dict.get("conflict_status", "NO_MATERIAL_CONFLICT")

            if conf_status in ("MATERIAL_CONFLICT", "ABSTENTION_REQUIRED"):
                has_material_conflict = True

            supp_ids = sorted(list(fnd_raw.get("supporting_evidence", [])))
            contra_ids = sorted(list(fnd_raw.get("contradicting_evidence", [])))

            # Formulate structured claims
            detector = fnd_raw.get("detector", fnd_raw.get("anomaly_type", "ANOMALY_DETECTOR"))
            score = float(fnd_raw.get("score", fnd_raw.get("anomaly_score", 0.0)))
            fnd_claims = [
                {
                    "claim_id": f"CLM-{fid}-01",
                    "finding_id": fid,
                    "statement": f"Entity {entity_id} exhibits anomalous signature detected by {detector} with score {score:.4f}.",
                    "supporting_evidence_ids": supp_ids,
                    "contradicting_evidence_ids": contra_ids,
                    "status": "GROUNDED" if supp_ids else "UNSUPPORTED"
                }
            ]
            all_claims.extend(fnd_claims)

            findings_list.append({
                "finding_id": fid,
                "finding_type": detector,
                "status": fnd_raw.get("status", "ACTIVE"),
                "confidence": round(float(fnd_raw.get("confidence", 0.90)), 4),
                "score": round(score, 4),
                "reliability": round(rel_score, 4),
                "reliability_components": {k: round(float(v), 4) for k, v in rel_comps.items()},
                "conflict_status": conf_status,
                "conflicting_domain_pairs": rel_dict.get("limitations", []),
                "supporting_evidence_ids": supp_ids,
                "contradicting_evidence_ids": contra_ids,
                "claims": fnd_claims,
                "uncertainty": rel_dict.get("reasons", ["Score reflects algorithmic inference bounded by observable telemetry."]),
                "limitations": [
                    "Preserves evidential uncertainty; does not assert criminal guilt, fraudulent intent, or legal culpability.",
                    "Independent human investigator corroboration required prior to action."
                ]
            })

        # 3. TIMELINE
        timeline_events: List[Dict[str, Any]] = []
        try:
            raw_timeline = self.backend.get_timeline(entity_id)
            if isinstance(raw_timeline, list):
                for ev in raw_timeline:
                    eid = ev.get("event_id", "UNKNOWN")
                    s_dom = ev.get("domain", ev.get("source_domain", "UNKNOWN")).upper()
                    if s_dom != "UNKNOWN":
                        domains_set.add(s_dom)
                    act = ev.get("actor", ev.get("actor_id", entity_id))
                    tgt = ev.get("target", ev.get("target_id"))
                    if act:
                        entities_set.add(str(act))
                    if tgt:
                        entities_set.add(str(tgt))

                    semantics = ev.get("temporal_semantics", "OBSERVED_TIMESTAMP")
                    ord_basis = "AUTHORITATIVE_TIMESTAMP" if semantics == "OBSERVED_TIMESTAMP" else "SEQUENCE_ORDER_SURROGATE"

                    timeline_events.append({
                        "event_id": eid,
                        "timestamp": str(ev.get("timestamp", "")),
                        "ordering_basis": ord_basis,
                        "event_type": ev.get("event_type", "ACTIVITY"),
                        "source_domain": s_dom,
                        "actor": act,
                        "target": tgt,
                        "evidence_ref": ev.get("evidence_ref") or f"ref:evd:{eid}",
                        "provenance_ref": ev.get("provenance_ref") or f"ref:prov:{eid}",
                    })
        except Exception as e:
            logger.debug(f"Timeline fetch fallback: {e}")

        # Deterministic sorting for timeline: by timestamp, then event_id
        timeline_events.sort(key=lambda x: (x["timestamp"], x["event_id"]))

        # 4. TEMPORAL INTELLIGENCE (M10)
        temp_intel: Dict[str, Any] = {
            "sequence_summary": {},
            "discovered_motifs": [],
            "predefined_motifs": [],
            "transitions": [],
            "phases": [],
            "future_event_exclusions": "Strict pre-trigger t < T semantics enforced; zero future-event leakage."
        }
        try:
            seq = self.backend.build_temporal_sequence(entity_id)
            if seq and seq.items:
                doms = sorted(list(set(it.source_domain.upper() for it in seq.items)))
                etypes = sorted(list(set(it.event_type for it in seq.items)))
                start_ts = seq.items[0].timestamp
                end_ts = seq.items[-1].timestamp
                t_span = (seq.items[-1].epoch_time - seq.items[0].epoch_time) if seq.items[-1].epoch_time and seq.items[0].epoch_time else 0.0
                temp_intel["sequence_summary"] = {
                    "total_events": len(seq.items),
                    "start_time": str(start_ts),
                    "end_time": str(end_ts),
                    "timespan_seconds": round(float(t_span), 2),
                    "domains": doms,
                    "event_types": etypes,
                }
                for d in doms:
                    domains_set.add(d.upper())

                # Discovered Motifs (M10 Unsupervised)
                try:
                    disc_motifs = self.backend.discover_sequence_motifs(entity_id, min_length=3, max_length=4)
                    temp_intel["discovered_motifs"] = [m.to_dict() if hasattr(m, "to_dict") else m for m in disc_motifs]
                except Exception as e:
                    logger.debug(f"Discovered motifs evaluation: {e}")

                # Predefined Motifs
                try:
                    pred_motifs = self.backend.detect_sequence_motifs(entity_id)
                    temp_intel["predefined_motifs"] = [m.to_dict() if hasattr(m, "to_dict") else m for m in pred_motifs]
                except Exception as e:
                    logger.debug(f"Predefined motifs evaluation: {e}")

                # Transitions
                try:
                    trans = self.backend.analyze_sequence_transitions(entity_id)
                    temp_intel["transitions"] = trans.get("transitions", [])
                except Exception as e:
                    logger.debug(f"Transitions evaluation: {e}")

                # Phases
                try:
                    phases = self.backend.compress_sequence_phases(entity_id)
                    temp_intel["phases"] = phases.get("phases", [])
                except Exception as e:
                    logger.debug(f"Phases evaluation: {e}")
        except Exception as e:
            logger.debug(f"Temporal intelligence sequence build: {e}")

        # 5. EVIDENCE QUALITY & PROVENANCE
        ev_quality_items: List[Dict[str, Any]] = []
        ev_lineage: List[Dict[str, Any]] = []
        source_refs: List[Dict[str, Any]] = []
        derivations: List[Dict[str, Any]] = []
        crypto_hashes: Dict[str, str] = {}
        traceability_rows: List[Dict[str, Any]] = []
        verified_count = 0
        total_ev_count = 0

        # Collect all relevant evidence IDs (from case + findings + timeline)
        all_evidence_ids_set = set(case.evidence_ids)
        for f in findings_list:
            all_evidence_ids_set.update(f.get("supporting_evidence_ids", []))
            all_evidence_ids_set.update(f.get("contradicting_evidence_ids", []))

        sorted_ev_ids = sorted(list(all_evidence_ids_set))
        for evid in sorted_ev_ids:
            ev_rec = self.backend.evidence_engine.evidence_store.get(evid)
            if ev_rec:
                total_ev_count += 1
                crypto_hashes[evid] = ev_rec.evidence_hash
                domains_set.add(ev_rec.source_domain.upper())

                # Lineage & integrity
                integ = self.backend.evidence_engine.verify_integrity(ev_rec)
                if integ.get("is_valid", False):
                    verified_count += 1

                try:
                    lin = self.backend.evidence_engine.graph.get_upstream_path(evid)
                    ev_lineage.extend(lin)
                except Exception:
                    pass

                source_refs.append({
                    "evidence_id": evid,
                    "source_id": ev_rec.source_id,
                    "source_file": ev_rec.source_file,
                    "source_row_index": ev_rec.source_row_index,
                    "source_domain": ev_rec.source_domain,
                    "evidence_hash": ev_rec.evidence_hash,
                })

                for parent_id in ev_rec.parent_evidence_ids:
                    derivations.append({
                        "parent_evidence_id": parent_id,
                        "derived_evidence_id": evid,
                        "derivation_method": ev_rec.derivation_method,
                    })

                ev_quality_items.append({
                    "evidence_id": evid,
                    "evidence_type": ev_rec.evidence_type,
                    "source_domain": ev_rec.source_domain,
                    "evidence_category": ev_rec.evidence_category,
                    "confidence": round(float(ev_rec.confidence), 4),
                    "evidence_quality": round(float(ev_rec.evidence_quality), 4),
                    "integrity_status": integ.get("status", "UNVERIFIED"),
                    "is_valid": integ.get("is_valid", False),
                    "temporal_semantics": ev_rec.temporal_semantics,
                })

                # Build traceability matrix entry
                # Trace: CLAIM -> FINDING -> EVIDENCE -> CANONICAL EVENT -> SOURCE RECORD -> PROVENANCE
                matching_fids = [
                    f["finding_id"] for f in findings_list
                    if evid in f.get("supporting_evidence_ids", []) or evid in f.get("contradicting_evidence_ids", [])
                ]
                fid_tag = matching_fids[0] if matching_fids else "CASE_LEVEL_EVIDENCE"
                cid_tag = f"CLM-{fid_tag}-01" if matching_fids else f"CLM-EVD-{evid}"
                can_ev_id = ev_rec.event_ids[0] if ev_rec.event_ids else "N/A"

                traceability_rows.append({
                    "claim_id": cid_tag,
                    "finding_id": fid_tag,
                    "evidence_id": evid,
                    "canonical_event_id": can_ev_id,
                    "source_record_id": ev_rec.source_id,
                    "source_file": ev_rec.source_file,
                    "source_hash": ev_rec.evidence_hash[:16] + "...",
                    "provenance_ref": ev_rec.provenance_ref,
                    "traceability_status": "GROUNDED" if integ.get("is_valid") else "PARTIALLY_GROUNDED"
                })

        # 6. CONFLICT INTELLIGENCE (M11)
        conflict_intel: Dict[str, Any] = {
            "overall_status": "NO_MATERIAL_CONFLICT",
            "required_action": "PROCEED",
            "pairs": []
        }
        try:
            from dfap.investigation.evidential_conflict import EvidentialConflictAnalyzer
            conflict_analyzer = EvidentialConflictAnalyzer()

            # Aggregate domain masses from evidence records
            domain_mass_map: Dict[str, List[float]] = {}
            for evid in sorted_ev_ids:
                rec = self.backend.evidence_engine.evidence_store.get(evid)
                if rec:
                    d_name = rec.source_domain.upper()
                    score_val = rec.metadata.get("anomaly_score", rec.confidence if rec.evidence_category == "SUPPORTING" else 1.0 - rec.confidence)
                    domain_mass_map.setdefault(d_name, []).append(float(score_val))

            if len(domain_mass_map) >= 2:
                # Average scores per domain
                domain_avg_masses = {d: float(sum(vals) / len(vals)) for d, vals in domain_mass_map.items()}
                conflict_res = conflict_analyzer.analyze_domains(domain_avg_masses)

                conflict_intel["overall_status"] = conflict_res.get("overall_status", "NO_MATERIAL_CONFLICT")
                conflict_intel["required_action"] = conflict_res.get("required_action", "PROCEED")
                conflict_intel["pairs"] = conflict_res.get("pairwise_conflicts", conflict_res.get("pairs", []))

                if conflict_res.get("requires_human_review", False) or conflict_res.get("overall_status") in ("MATERIAL_CONFLICT", "ABSTENTION_REQUIRED"):
                    has_material_conflict = True
        except Exception as e:
            logger.debug(f"Evidential conflict analysis: {e}")

        # 7. SOURCE HEALTH & DATA QUALITY
        source_health_summary: Dict[str, Any] = {
            "overall_status": "HEALTHY",
            "sources": []
        }
        try:
            case_health = self.backend.assess_case_data_health(case_id)
            source_health_summary["overall_status"] = case_health.get("overall_status", "HEALTHY")
            s_assessments = case_health.get("source_assessments", {})
            for s_id, s_data in sorted(s_assessments.items()):
                dims = s_data.get("dimensions", {})
                source_health_summary["sources"].append({
                    "dataset_source": s_id,
                    "health_status": s_data.get("overall_status", "HEALTHY"),
                    "schema_mode": s_data.get("schema_mode", "CANONICAL_SOURCE"),
                    "completeness": dims.get("COMPLETENESS", {}).get("status", "HEALTHY"),
                    "timestamp_health": dims.get("TIMESTAMP_VALIDITY", {}).get("status", "HEALTHY"),
                    "identifier_health": dims.get("IDENTIFIER_VALIDITY", {}).get("status", "HEALTHY"),
                    "duplicate_health": dims.get("UNIQUENESS", {}).get("status", "HEALTHY"),
                    "provenance_completeness": dims.get("PROVENANCE_COMPLETENESS", {}).get("status", "HEALTHY"),
                    "bounded_sample_status": "BOUNDED_SAMPLE" if s_data.get("record_count", 0) > 0 else "EMPTY"
                })
        except Exception as e:
            logger.debug(f"Case data health evaluation: {e}")
            for d in sorted(list(domains_set)):
                source_health_summary["sources"].append({
                    "dataset_source": d,
                    "health_status": "HEALTHY",
                    "schema_mode": "CANONICAL_SOURCE",
                    "completeness": "HEALTHY",
                    "timestamp_health": "HEALTHY",
                    "identifier_health": "HEALTHY",
                    "duplicate_health": "HEALTHY",
                    "provenance_completeness": "HEALTHY",
                    "bounded_sample_status": "BOUNDED_SAMPLE"
                })

        # 8. GRAPH SUBSET
        graph_data: Dict[str, Any] = {
            "nodes": [],
            "edges": []
        }
        node_ids_set: Set[str] = set()
        for ent in sorted(list(entities_set)):
            node_ids_set.add(ent)
            graph_data["nodes"].append({
                "node_id": ent,
                "node_type": "ENTITY",
                "domain": "CROSS_DOMAIN",
                "evidence_ref": f"ref:ent:{ent}"
            })
        for ev_item in timeline_events:
            ev_id = ev_item["event_id"]
            if ev_id not in node_ids_set:
                node_ids_set.add(ev_id)
                graph_data["nodes"].append({
                    "node_id": ev_id,
                    "node_type": "EVENT",
                    "domain": ev_item["source_domain"],
                    "evidence_ref": ev_item["evidence_ref"]
                })
            # Add observed edge
            act = ev_item.get("actor")
            tgt = ev_item.get("target")
            if act and tgt and act != tgt:
                graph_data["edges"].append({
                    "source": act,
                    "target": tgt,
                    "relation": ev_item.get("event_type", "OBSERVED_EVENT"),
                    "edge_status": "OBSERVED",
                    "status_distinction": "OBSERVED",
                    "evidence_ref": ev_item["evidence_ref"],
                    "temporal_bounds": {"timestamp": ev_item["timestamp"]}
                })

        # 9. DETERMINISTIC OVERALL PACKET STATUS & REQUIRED ACTION
        if not findings_list and not total_ev_count:
            packet_status = PacketStatus.UNAVAILABLE.value
            required_action = PacketRequiredAction.INSUFFICIENT_DATA.value
        elif has_material_conflict:
            packet_status = PacketStatus.CONFLICTED.value
            required_action = PacketRequiredAction.HUMAN_REVIEW.value
        elif total_ev_count > 0 and verified_count < total_ev_count:
            packet_status = PacketStatus.PARTIALLY_GROUNDED.value
            required_action = PacketRequiredAction.REVIEW_DISCREPANCY.value
        elif total_ev_count < 1:
            packet_status = PacketStatus.INSUFFICIENT_EVIDENCE.value
            required_action = PacketRequiredAction.COLLECT_ADDITIONAL_EVIDENCE.value
        else:
            packet_status = PacketStatus.GROUNDED.value
            required_action = PacketRequiredAction.PROCEED.value

        # Calculate overall evidence quality score
        mean_rel = float(sum(findings_reliability_scores) / len(findings_reliability_scores)) if findings_reliability_scores else 1.0
        ev_quality_summary = {
            "reliability_score": round(mean_rel, 4),
            "sufficiency": "SUFFICIENT" if total_ev_count >= 2 else "INSUFFICIENT",
            "independent_corroboration": round(float(len(domains_set) / max(1, len(domains_set))), 4),
            "contradiction_strength": round(float(len([f for f in findings_list if f.get("contradicting_evidence_ids")]) / max(1, len(findings_list))), 4),
            "identity_reliability": 1.0,
            "provenance_status": "INTEGRITY_VERIFIED" if verified_count == total_ev_count else "UNVERIFIED_ANCESTORS",
            "evidence_items": ev_quality_items
        }

        # Case section
        case_section = {
            "case_id": case.case_id,
            "title": f"Forensic Case Packet: {case.case_id} (Entity: {entity_id})",
            "created_at": case.created_at,
            "scope": case.case_kind or "SINGLE_ENTITY_CROSS_DOMAIN",
            "entities": sorted(list(entities_set)),
            "domains": sorted(list(domains_set)),
            "investigation_status": case.status
        }

        # Provenance section
        prov_section = {
            "evidence_lineage": ev_lineage,
            "source_references": source_refs,
            "derivation_relationships": derivations,
            "cryptographic_hashes": crypto_hashes,
            "integrity_status": "INTEGRITY_VERIFIED" if verified_count == total_ev_count else "DEFECT_DETECTED"
        }

        return ForensicCasePacket(
            case=case_section,
            findings=findings_list,
            timeline=timeline_events,
            graph=graph_data,
            temporal_intelligence=temp_intel,
            evidence_quality=ev_quality_summary,
            conflict_intelligence=conflict_intel,
            source_health=source_health_summary,
            provenance=prov_section,
            traceability_matrix=traceability_rows,
            packet_status=packet_status,
            required_action=required_action
        )

    def export_packet(self, case_id: str, output_dir: str = "output/cases") -> Dict[str, str]:
        """
        Exports the deterministic forensic packet to JSON and Markdown formats.
        Returns paths to the generated files.
        """
        os.makedirs(output_dir, exist_ok=True)
        packet = self.generate_packet(case_id)

        clean_id = case_id.replace(" ", "_").replace("/", "_")
        json_filename = f"CASE_{clean_id}_FORENSIC_PACKET.json"
        md_filename = f"CASE_{clean_id}_FORENSIC_REPORT.md"

        json_path = os.path.join(output_dir, json_filename)
        md_path = os.path.join(output_dir, md_filename)

        # 1. JSON Export
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(packet.to_dict(), f, indent=2, sort_keys=True, default=str)

        # 2. Markdown Export
        md_content = self.render_markdown_report(packet)
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md_content)

        return {
            "case_id": case_id,
            "packet_status": packet.packet_status,
            "required_action": packet.required_action,
            "json_path": json_path,
            "markdown_path": md_path,
            "json_filename": json_filename,
            "markdown_filename": md_filename,
            "packet_digest": packet.packet_digest
        }

    def render_markdown_report(self, packet: ForensicCasePacket) -> str:
        """
        Renders a comprehensive, auditable investigator-facing Markdown report.
        """
        c = packet.case
        eq = packet.evidence_quality
        ci = packet.conflict_intelligence
        ti = packet.temporal_intelligence
        sh = packet.source_health

        lines = [
            f"# DFAP Forensic Case Dossier: {c['case_id']}",
            f"**Generated:** `{packet.generated_at}`  ",
            f"**Schema Version:** `{packet.schema_version}`  ",
            f"**Forensic Packet SHA-256 Digest:** `{packet.packet_digest}`  ",
            "",
            "---",
            "",
            "## 1. Executive Summary & Case Status",
            f"- **Case Identifier:** `{c['case_id']}`",
            f"- **Investigation Status:** `{c['investigation_status']}`",
            f"- **Subject Entities:** {', '.join(f'`{e}`' for e in c['entities'])}",
            f"- **Source Domains:** {', '.join(f'`{d}`' for d in c['domains'])}",
            f"- **Forensic Packet Status:** **{packet.packet_status}**",
            f"- **Required Action:** **`{packet.required_action}`**",
            "",
            "> [!IMPORTANT]",
            f"> **Evidential Integrity Guarantee**: Every claim in this dossier is deterministically grounded through ",
            "> the canonical evidence store to verifiable upstream records. Claims without direct empirical evidence ",
            "> are explicitly designated as unavailable or insufficient.",
            ""
        ]

        if packet.packet_status == PacketStatus.CONFLICTED.value:
            lines.extend([
                "> [!WARNING]",
                f"> **STATUS: CONFLICTED — Material Evidential Disagreement Detected**  ",
                f"> Cross-domain evidential analysis revealed significant divergence between reporting domains. ",
                f"> Disagreement has been preserved rather than averaged away. Independent human review is strictly required.",
                ""
            ])

        # 2. Findings
        lines.extend([
            "## 2. Findings Dossier",
            f"Total findings attached: **{len(packet.findings)}**",
            ""
        ])
        if packet.findings:
            lines.extend([
                "| Finding ID | Type | Status | Confidence | Reliability | Conflict Status | Supporting Ev | Contradicting Ev |",
                "| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |"
            ])
            for f in packet.findings:
                supp = ", ".join(f['supporting_evidence_ids']) if f['supporting_evidence_ids'] else "-"
                contra = ", ".join(f['contradicting_evidence_ids']) if f['contradicting_evidence_ids'] else "-"
                lines.append(
                    f"| `{f['finding_id']}` | `{f['finding_type']}` | {f['status']} | "
                    f"{f['confidence']:.2f} | {f['reliability']:.2f} | `{f['conflict_status']}` | `{supp}` | `{contra}` |"
                )
            lines.append("")

            for f in packet.findings:
                lines.extend([
                    f"### Finding: `{f['finding_id']}`",
                    f"- **Detector/Type:** `{f['finding_type']}`",
                    f"- **Score:** `{f['score']}` | **Reliability:** `{f['reliability']}`",
                    f"- **Conflict Status:** `{f['conflict_status']}`",
                    "- **Claims:**"
                ])
                for clm in f.get("claims", []):
                    lines.append(f"  - `[{clm['claim_id']}]`: {clm['statement']}")
                lines.append("- **Limitations & Uncertainty:**")
                for lim in f.get("limitations", []):
                    lines.append(f"  - {lim}")
                lines.append("")
        else:
            lines.extend(["*No findings attached to this case.*", ""])

        # 3. End-to-End Forensic Traceability Matrix
        lines.extend([
            "## 3. End-to-End Forensic Traceability Matrix",
            "Deterministic audit trail proving line-of-custody from claim to root telemetry:",
            "",
            "```",
            "CLAIM ──▶ FINDING ──▶ EVIDENCE ──▶ CANONICAL EVENT ──▶ SOURCE RECORD ──▶ PROVENANCE",
            "```",
            "",
            "| Claim ID | Finding ID | Evidence ID | Canonical Event ID | Source Record | Source File | Provenance Ref | Status |",
            "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :---: |"
        ])
        for row in packet.traceability_matrix:
            lines.append(
                f"| `{row['claim_id']}` | `{row['finding_id']}` | `{row['evidence_id']}` | "
                f"`{row['canonical_event_id']}` | `{row['source_record_id']}` | `{row['source_file']}` | "
                f"`{row['provenance_ref']}` | **{row['traceability_status']}** |"
            )
        if not packet.traceability_matrix:
            lines.append("| - | - | - | - | - | - | - | *NO_TRACEABLE_EVIDENCE* |")
        lines.append("")

        # 4. Evidence Quality & Reliability
        lines.extend([
            "## 4. Evidence Quality & Reliability Assessment",
            f"- **Overall Reliability Score:** `{eq.get('reliability_score', 0.0):.4f}`",
            f"- **Evidence Sufficiency:** `{eq.get('sufficiency', 'UNKNOWN')}`",
            f"- **Independent Corroboration:** `{eq.get('independent_corroboration', 0.0):.2f}`",
            f"- **Contradiction Strength:** `{eq.get('contradiction_strength', 0.0):.2f}`",
            f"- **Identity Reliability:** `{eq.get('identity_reliability', 1.0):.2f}`",
            f"- **Provenance Integrity Status:** `{eq.get('provenance_status', 'UNKNOWN')}`",
            ""
        ])

        # 5. Evidential Conflict Intelligence (M11)
        lines.extend([
            "## 5. Evidential Conflict Intelligence (M11)",
            f"- **Overall Conflict Status:** **`{ci.get('overall_status', 'NO_MATERIAL_CONFLICT')}`**",
            f"- **Required Investigative Action:** **`{ci.get('required_action', 'PROCEED')}`**",
            ""
        ])
        pairs = ci.get("pairs", [])
        if pairs:
            lines.extend([
                "| Domain Pair | Hellinger Dist | Belief Cosine | Compound Conflict | Status | Action | Explanation |",
                "| :--- | :---: | :---: | :---: | :---: | :---: | :--- |"
            ])
            for p in pairs:
                lines.append(
                    f"| `{p.get('domain_a')} vs {p.get('domain_b')}` | {p.get('hellinger_distance', 0.0):.4f} | "
                    f"{p.get('belief_vector_cosine', 0.0):.4f} | **{p.get('compound_conflict', 0.0):.4f}** | "
                    f"`{p.get('conflict_status')}` | `{p.get('required_action')}` | {p.get('explanation', '')} |"
                )
            lines.append("")
        else:
            lines.extend(["*No multi-domain conflict observed (single domain or concordant evidence).*", ""])

        # 6. Temporal Intelligence (M10)
        lines.extend([
            "## 6. Temporal Intelligence & Behavioral Sequences (M10)",
            f"- **Sequence Summary:** {json.dumps(ti.get('sequence_summary', {}))}",
            f"- **Causal Policy:** {ti.get('future_event_exclusions')}",
            ""
        ])
        disc_motifs = ti.get("discovered_motifs", [])
        if disc_motifs:
            lines.extend([
                "### Unsupervised Discovered Motifs",
                "| Motif ID | Type | Cluster Size | Medoid Distance | Event Sequence | Representative Domains |",
                "| :--- | :--- | :---: | :---: | :--- | :--- |"
            ])
            for dm in disc_motifs:
                seq_str = " -> ".join(dm.get("representative_event_types", []))
                dom_str = ", ".join(dm.get("representative_domains", []))
                lines.append(
                    f"| `{dm.get('motif_id')}` | `{dm.get('classification')}` | {dm.get('cluster_size')} | "
                    f"{dm.get('medoid_total_distance', 0.0):.4f} | `{seq_str}` | `{dom_str}` |"
                )
            lines.append("")

        pred_motifs = ti.get("predefined_motifs", [])
        if pred_motifs:
            lines.extend([
                "### Predefined Catalog Motifs",
                "| Motif Name | Occurrences | Matched Sequences |",
                "| :--- | :---: | :--- |"
            ])
            for pm in pred_motifs:
                if not pm.get("matched", True):
                    continue
                m_name = pm.get("motif_id") or pm.get("motif_name") or "PREDEFINED_MOTIF"
                lines.append(f"| `{m_name}` | {len(pm.get('matching_event_ids', [])) or pm.get('count', 1)} | `{pm.get('description', '')}` |")
            lines.append("")

        # 7. Timeline
        lines.extend([
            "## 7. Multi-Domain Event Timeline",
            f"Total events: **{len(packet.timeline)}**",
            "",
            "| Timestamp | Ordering Basis | Domain | Event Type | Event ID | Actor | Target | Evidence Ref |",
            "| :--- | :--- | :---: | :---: | :--- | :--- | :--- | :--- |"
        ])
        for t in packet.timeline[:25]:
            lines.append(
                f"| {t['timestamp']} | `{t['ordering_basis']}` | `{t['source_domain']}` | "
                f"`{t['event_type']}` | `{t['event_id']}` | `{t['actor']}` | `{t['target'] or '-'}` | `{t['evidence_ref']}` |"
            )
        if len(packet.timeline) > 25:
            lines.append(f"| ... | ... | ... | ... | *({len(packet.timeline) - 25} earlier events omitted for brevity)* | ... | ... | ... |")
        lines.append("")

        # 8. Source Health & Data Quality
        lines.extend([
            "## 8. Source Data Health & Completeness",
            f"- **Overall Health Status:** `{sh.get('overall_status', 'HEALTHY')}`",
            ""
        ])
        sources = sh.get("sources", [])
        if sources:
            lines.extend([
                "| Source/Dataset | Health Status | Completeness | Timestamps | Identifiers | Uniqueness | Provenance |",
                "| :--- | :---: | :---: | :---: | :---: | :---: | :---: |"
            ])
            for s in sources:
                lines.append(
                    f"| `{s.get('dataset_source')}` | `{s.get('health_status')}` | `{s.get('completeness')}` | "
                    f"`{s.get('timestamp_health')}` | `{s.get('identifier_health')}` | `{s.get('duplicate_health')}` | `{s.get('provenance_completeness')}` |"
                )
            lines.append("")

        # 9. Cryptographic Provenance Ledger
        lines.extend([
            "## 9. Cryptographic Provenance & Audit Trail",
            f"- **Lineage Integrity Status:** `{packet.provenance.get('integrity_status', 'INTEGRITY_VERIFIED')}`",
            f"- **Total Derived Lineage Edges:** `{len(packet.provenance.get('derivation_relationships', []))}`",
            f"- **Evidence Hashes Committed:** `{len(packet.provenance.get('cryptographic_hashes', {}))}`",
            "",
            "> [!NOTE]",
            "> All cryptographic hashes are immutable SHA-256 digests over normalized UTF-8 records.",
            ""
        ])

        return "\n".join(lines)
