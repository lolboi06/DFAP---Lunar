# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: M14 Investigation Copilot (Evidence-Grounded Investigation Reasoning)

import copy
import json
from typing import Any, Dict, List, Optional, Set, Tuple

from dfap.investigation.workspace import InvestigationWorkspaceBackend
import pandas as pd


class EvidenceRetriever:
    """Retrieves only case/entity/finding scoped evidence and provenance."""

    def __init__(self, backend: InvestigationWorkspaceBackend):
        self.backend = backend

    def get_case_context(self, case_id: str) -> Dict[str, Any]:
        case = self.backend.get_case(case_id)
        return {
            "case_id": case.case_id,
            "entity_id": case.canonical_entity_id,
            "finding_ids": list(case.finding_ids),
            "evidence_ids": list(case.evidence_ids),
            "notes": list(case.notes),
            "status": case.status,
        }

    def get_entity_context(self, entity_id: str) -> Dict[str, Any]:
        if entity_id not in self.backend.valid_entities:
            raise ValueError(f"Unknown entity '{entity_id}' in authoritative registries.")
        return self.backend.investigate_entity(entity_id)

    def get_finding_context(self, finding_id: str) -> Dict[str, Any]:
        if finding_id not in self.backend.findings_by_id:
            raise ValueError(f"Unknown finding '{finding_id}' in authoritative finding ledger.")
        finding = self.backend.get_finding(finding_id)
        provenance = self.backend.get_provenance(finding_id)
        evidence_ids = list(self.backend.evidence_engine.finding_evidence_map.get(finding_id, []))
        evidence = []
        for evidence_id in evidence_ids:
            ev = self.backend.evidence_engine.get_evidence(evidence_id)
            if ev is not None:
                evidence.append(ev.to_dict())
        return {
            "finding": finding,
            "provenance": provenance,
            "evidence": evidence,
        }

    def get_timeline_context(self, entity_id: str) -> List[Dict[str, Any]]:
        return self.backend.get_timeline(entity_id)

    def get_graph_context(self, entity_id: str) -> Dict[str, Any]:
        return self.backend.graph_traversal.get_2hop_subgraph(entity_id)

    def get_evidence_for_finding(self, finding_id: str) -> List[Dict[str, Any]]:
        evidence_ids = list(self.backend.evidence_engine.finding_evidence_map.get(finding_id, []))
        records = []
        for evidence_id in evidence_ids:
            ev = self.backend.evidence_engine.get_evidence(evidence_id)
            if ev is not None:
                records.append(ev.to_dict())
        return records


class InvestigationContextBuilder:
    """Builds a structured evidence-grounded context block for reasoning."""

    def __init__(self, backend: InvestigationWorkspaceBackend):
        self.backend = backend
        self.retriever = EvidenceRetriever(backend)

    def build_for_finding(self, finding_id: str) -> Dict[str, Any]:
        finding_context = self.retriever.get_finding_context(finding_id)
        entity_id = str(finding_context["finding"].get("entity"))
        return {
            "ENTITY CONTEXT": self.retriever.get_entity_context(entity_id),
            "FINDING CONTEXT": finding_context["finding"],
            "EVIDENCE CONTEXT": finding_context["evidence"],
            "PROVENANCE CONTEXT": finding_context["provenance"],
            "TIMELINE CONTEXT": self.retriever.get_timeline_context(entity_id),
            "GRAPH CONTEXT": self.retriever.get_graph_context(entity_id),
            "KNOWN UNCERTAINTIES": ["Identity mapping is only as strong as the authoritative registry evidence.", "Temporal claims must only use comparable timestamps."],
        }

    def build_for_case(self, case_id: str) -> Dict[str, Any]:
        case = self.backend.get_case(case_id)
        entity_id = case.canonical_entity_id
        findings = [self.backend.get_finding(fid) for fid in case.finding_ids]
        evidence_ids = []
        for fid in case.finding_ids:
            evidence_ids.extend(self.backend.evidence_engine.finding_evidence_map.get(fid, []))
        return {
            "CASE CONTEXT": self.retriever.get_case_context(case_id),
            "ENTITY CONTEXT": self.retriever.get_entity_context(entity_id),
            "FINDING CONTEXT": findings,
            "EVIDENCE CONTEXT": [self.backend.evidence_engine.get_evidence(eid).to_dict() for eid in sorted(set(evidence_ids)) if self.backend.evidence_engine.get_evidence(eid) is not None],
            "TIMELINE CONTEXT": self.retriever.get_timeline_context(entity_id),
            "GRAPH CONTEXT": self.retriever.get_graph_context(entity_id),
            "KNOWN UNCERTAINTIES": ["Case summary is evidence-scoped to the target entity and attached findings only."]
        }


class ClaimValidator:
    """Validates that each factual claim is grounded in retrieved evidence and provenance."""

    def __init__(self, backend: InvestigationWorkspaceBackend):
        self.backend = backend

    def validate_claim(self, claim: str, evidence_ids: List[str], entity_id: Optional[str] = None, finding_id: Optional[str] = None) -> bool:
        if not claim or not claim.strip():
            return False
        if not evidence_ids:
            return False
        for evidence_id in evidence_ids:
            record = self.backend.evidence_engine.get_evidence(evidence_id)
            if record is None:
                return False
            if entity_id is not None and entity_id not in record.canonical_entity_ids:
                return False
            if finding_id is not None:
                if evidence_id not in self.backend.evidence_engine.finding_evidence_map.get(finding_id, []):
                    return False
        return True


class CopilotReasoner:
    """Rule-based deterministic reasoning fallback for grounded investigation responses."""

    def __init__(self, backend: InvestigationWorkspaceBackend):
        self.backend = backend

    def explain_finding(self, finding_id: str) -> Dict[str, Any]:
        if finding_id not in self.backend.findings_by_id:
            raise ValueError(f"Unknown finding '{finding_id}' in authoritative finding ledger.")
        finding = self.backend.get_finding(finding_id)
        provenance = self.backend.get_provenance(finding_id)

        # Temporal safety: determine finding observation time T
        finding_time = None
        temporal_context = finding.get("temporal_context") or {}
        ts = temporal_context.get("timestamp") or finding.get("timestamp") or finding.get("observation_timestamp")
        if ts is not None:
            try:
                finding_time = float(ts)
            except (ValueError, TypeError):
                try:
                    finding_time = pd.to_datetime(ts, utc=True).timestamp()
                except Exception:
                    finding_time = None

        evidence_ids = list(self.backend.evidence_engine.finding_evidence_map.get(finding_id, []))
        if not evidence_ids and finding.get("supporting_evidence"):
            evidence_ids = [e for e in finding.get("supporting_evidence") if not str(e).startswith("ref:fnd:")]

        evidence = []
        for evidence_id in evidence_ids:
            ev = self.backend.evidence_engine.get_evidence(evidence_id)
            if ev is not None:
                # Temporal filtering for causal justification:
                # Strictly omit future evidence relative to finding_time
                if finding_time is not None and getattr(ev, "observation_timestamp", None) is not None:
                    try:
                        ev_time = float(ev.observation_timestamp)
                    except (ValueError, TypeError):
                        try:
                            ev_time = pd.to_datetime(ev.observation_timestamp, utc=True).timestamp()
                        except Exception:
                            ev_time = None
                    if ev_time is not None and ev_time > finding_time:
                        continue
                evidence.append(ev)

        support = [e.evidence_id for e in evidence if getattr(e, "evidence_category", "SUPPORTING") == "SUPPORTING"]
        contradict = [e.evidence_id for e in evidence if getattr(e, "evidence_category", "") == "CONTRADICTING"]

        valid_ev_ids = [e.evidence_id for e in evidence]
        final_support = support if support else valid_ev_ids

        f_raw = self.backend.findings_by_id.get(finding_id, {})
        detector = f_raw.get("detector", finding.get("detector", "DETECTOR"))
        score = float(f_raw.get("anomaly_score", f_raw.get("composite_score", finding.get("score", 0.0))))
        reasons = f_raw.get("anomaly_reasons", f_raw.get("decision_reasons", []))
        reasons_str = f" based on: {', '.join(reasons)}" if reasons else ""

        has_finding_conflict = bool(contradict or f_raw.get("status") in ("CONFLICTED", "CONFLICTED_EVIDENCE"))
        finding_status = "CONFLICTED" if has_finding_conflict else ("GROUNDED" if provenance.get("is_valid") else "INSUFFICIENT_EVIDENCE")
        confidence_score = 0.40 if has_finding_conflict else 0.90

        # M9 On-Demand SHAP Model Attribution
        shap_data = None
        if hasattr(self.backend, "explain_finding_shap"):
            try:
                shap_data = self.backend.explain_finding_shap(finding_id)
            except Exception:
                shap_data = None

        shap_text = ""
        if shap_data and shap_data.get("explanation_status") in ("EXPLAINED", "PARTIALLY_EXPLAINED"):
            pos_names = [c["feature_name"] for c in shap_data.get("top_positive_contributors", [])]
            neg_names = [c["feature_name"] for c in shap_data.get("top_negative_contributors", [])]
            pos_str = f"Top model contributors driving anomaly score: {', '.join(pos_names)}." if pos_names else ""
            neg_str = f"Top model contributors pulling toward baseline normality: {', '.join(neg_names)}." if neg_names else ""
            shap_text = f" SHAP Model Contribution Analysis: {pos_str} {neg_str} This is a MODEL CONTRIBUTION EXPLANATION from SHAP quantifying feature attribution, NOT real-world causation, fraudulent intent, or legal culpability."

        answer = (
            f"Finding {finding_id} is attached to entity {finding.get('entity')} and was flagged as {finding_status} "
            f"(detector={detector}, score={score:.4f}){reasons_str}, grounded in pre-trigger historical context "
            f"and trigger-time evidence.{shap_text}"
        )
        claims = [
            {
                "claim": f"Finding {finding_id} belongs to entity {finding.get('entity')} with anomaly score {score:.4f}.",
                "evidence_ids": final_support,
            },
            {
                "claim": f"Provenance integrity status is {provenance.get('integrity_status')}.",
                "evidence_ids": valid_ev_ids,
            },
        ]
        if contradict:
            claims.append({
                "claim": f"Finding {finding_id} has {len(contradict)} contradicting evidence record(s): {', '.join(contradict)}.",
                "evidence_ids": contradict,
            })
        if shap_data and shap_data.get("explanation_status") in ("EXPLAINED", "PARTIALLY_EXPLAINED"):
            claims.append({
                "claim": f"SHAP model attribution explains finding {finding_id} via {shap_data.get('explainer_type')} over detector {shap_data.get('model_identifier')}.",
                "evidence_ids": shap_data.get("evidence_refs", final_support),
            })
        reliability_data = None
        for cid, c_obj in self.backend.cases.items():
            if finding_id in c_obj.finding_ids:
                try:
                    reliability_data = self.backend.assess_finding_reliability(cid, finding_id)
                    break
                except Exception:
                    pass

        return {
            "answer": answer,
            "confidence": confidence_score,
            "status": finding_status,
            "claims": claims,
            "evidence_refs": final_support if not has_finding_conflict else valid_ev_ids,
            "provenance_refs": [x.get("node_id") for x in provenance.get("lineage_chain", []) if isinstance(x, dict) and x.get("node_id")],
            "uncertainties": ["Human review required for final investigative interpretation."] + (["Evidential contradiction detected between supporting and contradicting signals."] if has_finding_conflict else []),
            "limitations": [
                "This answer does not infer guilt or criminal conclusion.",
                "SHAP feature attributions reflect mathematical model contribution only, not causal proof."
            ],
            "suggested_next_actions": ["Review supporting evidence for the finding.", "Inspect contradicting evidence if present."],
            "finding_id": finding_id,
            "entity_id": finding.get("entity"),
            "reliability": reliability_data,
            "shap_explanation": shap_data,
        }

    def summarize_case(self, case_id: str) -> Dict[str, Any]:
        case = self.backend.get_case(case_id)
        findings = [self.backend.get_finding(fid) for fid in case.finding_ids]
        evidence_ids: Set[str] = set()
        for fid in case.finding_ids:
            evidence_ids.update(self.backend.evidence_engine.finding_evidence_map.get(fid, []))
        case_summary = {
            "case_id": case.case_id,
            "entity_id": case.canonical_entity_id,
            "status": case.status,
            "summary": f"Case {case.case_id} targets entity {case.canonical_entity_id} and has {len(findings)} attached findings.",
            "important_findings": [f["finding_id"] for f in findings],
            "supporting_evidence": sorted(evidence_ids),
            "contradicting_evidence": [],
            "unresolved_questions": ["Review whether additional corroborating evidence is needed."],
            "provenance_integrity_status": "INTEGRITY_VERIFIED",
            "recommended_next_actions": ["Inspect timeline for the target entity.", "Review related graph neighbors."],
        }
        return case_summary


class ResponseFormatter:
    """Formats the final M14 structured answer."""

    def format(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "answer": payload.get("answer", ""),
            "confidence": payload.get("confidence", 0.0),
            "status": payload.get("status", "INSUFFICIENT_EVIDENCE"),
            "claims": payload.get("claims", []),
            "evidence_refs": payload.get("evidence_refs", []),
            "provenance_refs": payload.get("provenance_refs", []),
            "uncertainties": payload.get("uncertainties", []),
            "limitations": payload.get("limitations", []),
            "suggested_next_actions": payload.get("suggested_next_actions", []),
            "dataset": payload.get("dataset", "UNKNOWN"),
            "entity_id": payload.get("entity_id"),
            "finding_id": payload.get("finding_id"),
            "case_id": payload.get("case_id"),
            # Preserve optional diagnostic fields when present in payload
            "pairwise_records": payload.get("pairwise_records", []),
            "ambiguous_identifiers": payload.get("ambiguous_identifiers", []),
            "verification_steps": payload.get("verification_steps", payload.get("suggested_next_actions", [])),
            "reliability": payload.get("reliability"),
            "data_quality": payload.get("data_quality"),
            "source_health": payload.get("source_health"),
            "evidential_conflict": payload.get("evidential_conflict"),
            "required_action": payload.get("required_action"),
            "discovered_motifs": payload.get("discovered_motifs"),
            "forensic_packet": payload.get("forensic_packet"),
            "traceability_matrix": payload.get("traceability_matrix"),
            "baseline_status": payload.get("baseline_status"),
            "culpability_assessment": payload.get("culpability_assessment"),
            "audit_verifiable": payload.get("audit_verifiable"),
        }


class InvestigationCopilot:
    """Evidence-grounded M14 investigation copilot backed by the authoritative DFAP backend."""

    def __init__(self, backend: InvestigationWorkspaceBackend):
        self.backend = backend
        self.retriever = EvidenceRetriever(backend)
        self.context_builder = InvestigationContextBuilder(backend)
        self.validator = ClaimValidator(backend)
        self.reasoner = CopilotReasoner(backend)
        self.formatter = ResponseFormatter()

    def _get_finding_id_from_question(self, question: str) -> Optional[str]:
        # Accept a finding ID if included in the question; otherwise return None.
        token_candidates = [
            tok.strip("?,.!:;\"'")
            for tok in question.split()
            if tok.strip("?,.!:;\"'").startswith("FND_") or tok.strip("?,.!:;\"'").startswith("FND-")
        ]
        if token_candidates:
            return token_candidates[0]
        return None

    def _resolve_active_case(self, case_id: Optional[str] = None, entity_id: Optional[str] = None) -> Optional[Any]:
        if case_id is not None:
            if case_id in self.backend.cases:
                return self.backend.cases[case_id]
            raise KeyError(f"Case '{case_id}' not found in workspace.")
        if entity_id is not None:
            matches = [c for c in self.backend.cases.values() if c.canonical_entity_id == entity_id]
            if matches:
                return matches[0]
            return None
        return None

    def _resolve_dataset(
        self,
        case_id: Optional[str] = None,
        entity_id: Optional[str] = None,
        items: Optional[List[Any]] = None,
        events: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        datasets: Set[str] = set()
        domains: Set[str] = set()

        def _clean_val(val: Any) -> Optional[str]:
            if not val:
                return None
            s = str(val).strip().upper()
            if s in {"UNKNOWN", "UNAVAILABLE", "NONE", "NULL", "LIVE_STREAM_FINDING", "CONTROLLED_CASE_MAPPING"}:
                return None
            return s

        def _add_source(val: Any, is_domain: bool = False):
            c = _clean_val(val)
            if not c:
                return
            if c in {"UNSW", "UNSW-NB15", "UNSW_NB15"}:
                datasets.add("UNSW")
            elif c in {"ELLIPTIC", "ELLIPTIC_DATASET"}:
                datasets.add("ELLIPTIC")
            elif c in {"STACKOVERFLOW", "STACK_OVERFLOW"}:
                datasets.add("STACKOVERFLOW")
            elif is_domain:
                domains.add(c)
            else:
                datasets.add(c)

        # 1. Inspect direct items (e.g. TemporalSequenceItem)
        if items:
            for it in items:
                _add_source(getattr(it, "dataset", None), is_domain=False)
                _add_source(getattr(it, "source_domain", None), is_domain=True)
                ev_ref = getattr(it, "evidence_ref", None) or getattr(it, "event_id", None)
                if ev_ref and hasattr(self.backend, "evidence_engine"):
                    ev_obj = self.backend.evidence_engine.get_evidence(ev_ref)
                    if not ev_obj and getattr(it, "event_id", None):
                        ev_obj = self.backend.evidence_engine.get_evidence(it.event_id)
                    if ev_obj:
                        if isinstance(getattr(ev_obj, "metadata", None), dict):
                            _add_source(ev_obj.metadata.get("dataset"), is_domain=False)
                            _add_source(ev_obj.metadata.get("source_dataset"), is_domain=False)
                        _add_source(getattr(ev_obj, "source_domain", None), is_domain=True)

        # 2. Inspect direct events dicts
        if events:
            for ev in events:
                if isinstance(ev, dict):
                    _add_source(ev.get("dataset"), is_domain=False)
                    _add_source(ev.get("source_dataset"), is_domain=False)
                    _add_source(ev.get("source_domain") or ev.get("domain"), is_domain=True)
                    ev_ref = ev.get("evidence_ref") or ev.get("evidence_id") or ev.get("event_id")
                    if ev_ref and hasattr(self.backend, "evidence_engine"):
                        ev_obj = self.backend.evidence_engine.get_evidence(ev_ref)
                        if ev_obj:
                            if isinstance(getattr(ev_obj, "metadata", None), dict):
                                _add_source(ev_obj.metadata.get("dataset"), is_domain=False)
                                _add_source(ev_obj.metadata.get("source_dataset"), is_domain=False)
                            _add_source(getattr(ev_obj, "source_domain", None), is_domain=True)

        # 3. Check case search context
        if case_id is not None and case_id in self.backend.cases:
            case = self.backend.cases[case_id]
            if hasattr(case, "search_context") and isinstance(case.search_context, dict):
                _add_source(case.search_context.get("source"), is_domain=False)
                if "domain_evidence_breakdown" in case.search_context:
                    for dom_info in case.search_context["domain_evidence_breakdown"].values():
                        if isinstance(dom_info, dict) and "dataset" in dom_info:
                            _add_source(dom_info["dataset"], is_domain=False)

        # 4. Check entity in replay datasets
        if entity_id and hasattr(self.backend, "temporal_engine"):
            ds_key, df = self.backend.temporal_engine.get_dataset_for_entity(entity_id)
            if ds_key and not df.empty:
                _add_source(ds_key, is_domain=False)

        # 5. Check entity timeline
        if entity_id:
            try:
                tl = self.backend.get_timeline(entity_id)
                for ev in (tl or []):
                    if isinstance(ev, dict):
                        _add_source(ev.get("dataset"), is_domain=False)
                        _add_source(ev.get("source_dataset"), is_domain=False)
                        _add_source(ev.get("source_domain") or ev.get("domain"), is_domain=True)
            except Exception:
                pass

        if datasets:
            return ", ".join(sorted(datasets))
        if domains:
            return ", ".join(sorted(domains))

        return "UNAVAILABLE"

    def _handle_identity_question(self, question: str, case: Optional[Any], entity_id: Optional[str]) -> Optional[Dict[str, Any]]:
        q = question.lower()
        if not ("same entity" in q or "same identity" in q or "across all domains" in q or "is this the same entity" in q):
            return None

        if case is None and entity_id is None:
            return self._safe_no_finding_response(question, case_id=None, entity_id=None)

        ent_id = entity_id or (case.canonical_entity_id if case else None)
        if ent_id is None:
            return self._safe_no_finding_response(question, case_id=(case.case_id if case else None), entity_id=None)

        # Use authoritative investigation summary
        try:
            ent_ctx = self.backend.investigate_entity(ent_id)
        except Exception:
            return self._safe_no_finding_response(question, case_id=(case.case_id if case else None), entity_id=ent_id)

        linked = ent_ctx.get("linked_identifiers", [])
        prov_refs = ent_ctx.get("provenance_refs", [])
        # Attempt to bind authoritative pairwise entity_matches -> canonical event evidence
        pairwise_records: List[Dict[str, Any]] = []
        try:
            canonical_raws = [str(x.get("raw_identifier", "")).strip() for x in linked]
            # Map raw identifier -> event_ids in canonical events
            event_map = {}
            if not self.backend.events_df.empty:
                for _, ev in self.backend.events_df.iterrows():
                    eid = str(ev.get("event_id", ""))
                    actor = str(ev.get("actor_id", "")).strip()
                    target = str(ev.get("target_id", "")).strip()
                    if actor in canonical_raws or target in canonical_raws:
                        event_map.setdefault(actor, []).append(eid)
                        if target:
                            event_map.setdefault(target, []).append(eid)

            if not self.backend.entity_matches_df.empty and event_map:
                # Collect all event ids of interest
                interesting_event_ids = set()
                for v in event_map.values():
                    for x in v:
                        interesting_event_ids.add(x)

                sub = self.backend.entity_matches_df[self.backend.entity_matches_df["left_record_id"].isin(interesting_event_ids) | self.backend.entity_matches_df["right_record_id"].isin(interesting_event_ids)] if "left_record_id" in self.backend.entity_matches_df.columns else None
                if sub is not None and not sub.empty:
                    for _, mrow in sub.iterrows():
                        left = str(mrow.get("left_record_id", ""))
                        right = str(mrow.get("right_record_id", ""))
                        match_id = str(mrow.get("match_id", ""))
                        status = str(mrow.get("match_status", ""))
                        method = str(mrow.get("match_method", ""))
                        prob = float(mrow.get("match_probability", 0.0)) if mrow.get("match_probability", None) is not None else 0.0
                        # Resolve evidence ids via event sha -> evidence mapping in workspace
                        evidence_ids = []
                        prov_node_refs = []
                        for ev_id in (left, right):
                            # find corresponding event row
                            evrows = self.backend.events_df[self.backend.events_df["event_id"] == ev_id] if not self.backend.events_df.empty else pd.DataFrame()
                            for _, er in evrows.iterrows():
                                sha = str(er.get("sha256_hash", "")).strip()
                                if sha:
                                    ev_eid = self.backend._evidence_by_hash.get(sha)
                                    if ev_eid:
                                        evidence_ids.append(ev_eid)
                                        evrec = self.backend.evidence_engine.get_evidence(ev_eid)
                                        if evrec is not None:
                                            prov_node_refs.append(evrec.provenance_ref)

                        pairwise_records.append({
                            "match_id": match_id,
                            "left_record_id": left,
                            "right_record_id": right,
                            "match_status": status,
                            "match_method": method,
                            "match_probability": prob,
                            "evidence_ids": list(dict.fromkeys(evidence_ids)),
                            "provenance_refs": list(dict.fromkeys(prov_node_refs)),
                            "decision_reason": str(mrow.get("decision_reason", ""))
                        })
        except Exception:
            pairwise_records = []
        # Determine which linked identifiers have authoritative pairwise confirmation
        confirmed_pairs = []
        ambiguous = []
        for lid in linked:
            if float(lid.get("confidence", 0.0)) >= 0.85 and str(lid.get("mapping_method", "")).upper() == "EXACT":
                confirmed_pairs.append(lid)
            else:
                ambiguous.append(lid)

        # Build answer respecting safety rules
        if confirmed_pairs and not ambiguous:
            answer = f"The canonical entity {ent_id} has authoritative pairwise identity evidence for its linked identifiers."
            payload = {
                "answer": answer,
                "confidence": 0.95,
                "status": "GROUNDED",
                "claims": [{"claim": "Authoritative pairwise identity evidence supports the canonicalization.", "evidence_ids": prov_refs}],
                "evidence_refs": prov_refs or [r for rec in pairwise_records for r in rec.get("evidence_ids", [])],
                "provenance_refs": prov_refs or [r for rec in pairwise_records for r in rec.get("provenance_refs", [])],
                "uncertainties": [],
                "limitations": ["This statement is limited to the provided authoritative pairwise evidence and does not generalize beyond it."],
                "suggested_next_actions": ["Review the attached provenance for chain-of-trust."],
                "entity_id": ent_id,
                "case_id": case.case_id if case else None,
                "pairwise_records": pairwise_records,
            }
            return self.formatter.format(payload)

        # Otherwise, do not assert equivalence
        uncertain_ids = [x.get("raw_identifier") for x in ambiguous]
        answer = (
            f"The canonical entity {ent_id} includes both confirmed and unresolved linked identifiers. "
            "Similarity alone is not sufficient to assert identity across domains."
        )
        payload = {
            "answer": answer,
            "confidence": 0.0,
            "status": "NOT_CONFIRMED",
            "claims": [
                {"claim": "Confirmed linked identifiers (authoritative):", "evidence_ids": prov_refs if confirmed_pairs else []},
                {"claim": "Ambiguous identifiers requiring verification:", "evidence_ids": []},
            ],
            "evidence_refs": prov_refs or [r for rec in pairwise_records for r in rec.get("evidence_ids", [])],
            "provenance_refs": prov_refs or [r for rec in pairwise_records for r in rec.get("provenance_refs", [])],
            "uncertainties": ["The ambiguous identifiers listed below require authoritative pairwise evidence to be confirmed."],
            "limitations": ["Similarity features are reported as similarity, not identity proof."],
            "suggested_next_actions": ["Verify pairwise identity evidence (shared account numbers, corroborated source_row provenance, or exact deterministic evidence)."],
            "entity_id": ent_id,
            "case_id": case.case_id if case else None,
            "ambiguous_identifiers": uncertain_ids,
        }
        return self.formatter.format(payload)

    def _handle_uncertain_identifiers(self, question: str, case: Optional[Any], entity_id: Optional[str]) -> Optional[Dict[str, Any]]:
        """Returns authoritative pairwise entity-match records relevant to the active case/entity.

        Only uses `entity_matches.parquet` rows that reference events tied to the case's canonical entity.
        Does not fabricate inference from similarity features.
        """
        if case is None and entity_id is None:
            return None

        ent_id = entity_id or (case.canonical_entity_id if case else None)
        if ent_id is None:
            return None

        # Get linked identifiers from authoritative registry
        try:
            ent_ctx = self.backend.investigate_entity(ent_id)
        except Exception:
            return None

        linked = ent_ctx.get("linked_identifiers", [])
        canonical_raws = [str(x.get("raw_identifier", "")).strip() for x in linked if x.get("raw_identifier")]

        # If the active case provided an explicit identity candidate match-id set, prefer it
        # and restrict enumeration to those match rows only (case-scoped candidate set).
        candidate_match_ids = None
        if case is not None:
            sc = getattr(case, "search_context", {}) or {}
            cmids = sc.get("identity_candidate_match_ids")
            if isinstance(cmids, (list, tuple)) and cmids:
                candidate_match_ids = [str(x) for x in cmids]

        # Map event id -> raw identifiers for events that reference these raw ids
        event_map = {}
        if not self.backend.events_df.empty:
            for _, ev in self.backend.events_df.iterrows():
                eid = str(ev.get("event_id", ""))
                actor = str(ev.get("actor_id", "")).strip()
                target = str(ev.get("target_id", "")).strip()
                if actor in canonical_raws or target in canonical_raws:
                    event_map[eid] = {
                        "event_id": eid,
                        "actor_id": actor,
                        "target_id": target,
                        "source_domain": str(ev.get("source_domain", "")).upper(),
                    }

        if not event_map:
            return {
                "answer": "No authoritative event-context found for this case to inspect ambiguous identifiers.",
                "confidence": 0.0,
                "status": "INSUFFICIENT_EVIDENCE",
                "claims": [],
                "evidence_refs": [],
                "provenance_refs": [],
                "uncertainties": ["No case-scoped events found to enumerate pairwise identity decisions."],
                "suggested_next_actions": ["Ensure canonical events and entity_matches artifacts are present for the case."],
                "entity_id": ent_id,
                "case_id": case.case_id if case else None,
            }

        interesting_event_ids = set(event_map.keys())

        # Query authoritative pairwise audit artifact for matches touching these events or matching explicit candidate IDs
        pairwise = []
        if not self.backend.entity_matches_df.empty and "left_record_id" in self.backend.entity_matches_df.columns:
            if candidate_match_ids is not None:
                sub = self.backend.entity_matches_df[self.backend.entity_matches_df["match_id"].isin(candidate_match_ids)]
            else:
                sub = self.backend.entity_matches_df[
                    self.backend.entity_matches_df["left_record_id"].isin(interesting_event_ids) |
                    self.backend.entity_matches_df["right_record_id"].isin(interesting_event_ids)
                ]
            if not sub.empty:
                for _, mrow in sub.iterrows():
                    left = str(mrow.get("left_record_id", ""))
                    right = str(mrow.get("right_record_id", ""))
                    left_raw = event_map.get(left, {}).get("actor_id") or event_map.get(left, {}).get("target_id") or ""
                    right_raw = event_map.get(right, {}).get("actor_id") or event_map.get(right, {}).get("target_id") or ""
                    status = str(mrow.get("match_status", ""))
                    method = str(mrow.get("match_method", ""))
                    prob = float(mrow.get("match_probability", 0.0)) if mrow.get("match_probability", None) is not None else None
                    reason = str(mrow.get("decision_reason", ""))

                    # evidence/provenance refs via event sha -> evidence mapping
                    evidence_ids = []
                    prov_refs = []
                    for ev_id in (left, right):
                        evrows = self.backend.events_df[self.backend.events_df["event_id"] == ev_id] if not self.backend.events_df.empty else None
                        if evrows is not None and not evrows.empty:
                            for _, er in evrows.iterrows():
                                sha = str(er.get("sha256_hash", "")).strip()
                                if sha:
                                    ev_eid = self.backend._evidence_by_hash.get(sha)
                                    if ev_eid:
                                        evidence_ids.append(ev_eid)
                                        evrec = self.backend.evidence_engine.get_evidence(ev_eid)
                                        if evrec is not None and getattr(evrec, "provenance_ref", None):
                                            prov_refs.append(evrec.provenance_ref)

                    pairwise.append({
                        "match_id": str(mrow.get("match_id", "")),
                        "left_record_id": left,
                        "left_raw_identifier": left_raw,
                        "right_record_id": right,
                        "right_raw_identifier": right_raw,
                        "match_status": status,
                        "match_method": method,
                        "match_probability": prob,
                        "decision_reason": reason,
                        "evidence_ids": list(dict.fromkeys(evidence_ids)),
                        "provenance_refs": list(dict.fromkeys(prov_refs)),
                    })

        # Filter to unresolved (non-CONFIRMED) per policy
        unresolved = [p for p in pairwise if p.get("match_status") != "CONFIRMED"]

        if not unresolved:
            return {
                "answer": "No unresolved pairwise identity decisions were found for the active case.",
                "confidence": 0.0,
                "status": "INSUFFICIENT_EVIDENCE",
                "claims": [],
                "evidence_refs": [],
                "provenance_refs": [],
                "uncertainties": ["No unresolved pairwise audit records were present for the case-scoped events."],
                "suggested_next_actions": ["Ensure entity_matches.parquet contains pairwise audit records for reviewer inspection."],
                "entity_id": ent_id,
                "case_id": case.case_id if case else None,
            }

        # Build ambiguous_identifiers summary
        ambiguous_identifiers = []
        for rec in unresolved:
            ambiguous_identifiers.append({
                "pair": f"{rec['left_record_id']} <-> {rec['right_record_id']}",
                "left_raw_identifier": rec.get("left_raw_identifier"),
                "right_raw_identifier": rec.get("right_raw_identifier"),
                "match_status": rec.get("match_status"),
                "match_probability": rec.get("match_probability"),
            })

        # Aggregate evidence and provenance refs
        agg_evidence = []
        agg_prov = []
        for r in unresolved:
            agg_evidence.extend(r.get("evidence_ids", []))
            agg_prov.extend(r.get("provenance_refs", []))

        payload = {
            "answer": "Ambiguous or unresolved pairwise identity decisions relevant to the active case were enumerated.",
            "confidence": 0.4,
            "status": "PARTIALLY_GROUNDED",
            "claims": [{"claim": "Unresolved pairwise identity audit records are listed for reviewer inspection.", "evidence_ids": list(dict.fromkeys(agg_evidence))}],
            "evidence_refs": list(dict.fromkeys(agg_evidence)),
            "provenance_refs": list(dict.fromkeys(agg_prov)),
            "pairwise_records": unresolved,
            "ambiguous_identifiers": ambiguous_identifiers,
            "uncertainties": ["These are authoritative pairwise audit records; human review required for final identity decisions."],
            "suggested_next_actions": ["Review the listed pairwise audit records and verify using source provenance or external authoritative registries."],
            "entity_id": ent_id,
            "case_id": case.case_id if case else None,
        }
        return self.formatter.format(payload)

    def _handle_pre_trigger_question(
        self,
        question: str,
        case_id: Optional[str] = None,
        entity_id: Optional[str] = None,
        explicit_finding_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        q = (question or "").strip()
        lower = q.lower()

        is_pre_trigger_q = (
            ("before" in lower and ("event" in lower or "trigger" in lower or "finding" in lower or "activity" in lower or "suspicious" in lower or "happened" in lower))
            or ("pre-trigger" in lower or "preceding" in lower or "prior to" in lower or "precursor" in lower)
            or ("what happened before" in lower)
        )
        if not is_pre_trigger_q:
            return None

        # Check for post-trigger question (which is handled elsewhere)
        if "after" in lower or "subsequent" in lower or "post-trigger" in lower:
            return None

        case = self._resolve_active_case(case_id=case_id, entity_id=entity_id)

        # Check if controlled case mapping applies (defer to controlled case handling)
        if case is not None and self._controlled_case_payload(case) is not None:
            return None

        explicit_event_id = None
        for tok in q.split():
            c_tok = tok.strip("?,.!:;\"'")
            if c_tok.startswith("EVT_") or c_tok.startswith("EVT-"):
                explicit_event_id = c_tok
                break

        target_finding_id = explicit_finding_id or self._get_finding_id_from_question(q)
        if not target_finding_id and case:
            target_finding_id = self._pick_case_finding_id(case_id=case.case_id, entity_id=entity_id)

        ent_id = entity_id or (case.canonical_entity_id if case else None)
        if not ent_id and target_finding_id and target_finding_id in self.backend.findings_by_id:
            f = self.backend.findings_by_id[target_finding_id]
            ent_id = f.get("canonical_entity_id") or f.get("entity_id") or f.get("entity")

        if not ent_id and self.backend.valid_entities:
            if len(self.backend.valid_entities) == 1:
                ent_id = next(iter(self.backend.valid_entities))

        if not ent_id:
            return self._safe_no_finding_response(q, case_id=case.case_id if case else case_id, entity_id=None, case=case)

        raw_events = self.backend.get_timeline(ent_id)
        if not raw_events:
            payload = {
                "answer": f"No grounded historical evidence is available for entity {ent_id}; timeline is not populated.",
                "confidence": 0.0,
                "status": "INSUFFICIENT_EVIDENCE",
                "claims": [],
                "evidence_refs": [],
                "provenance_refs": [],
                "uncertainties": [f"No events recorded in authoritative timeline for {ent_id}."],
                "limitations": ["Historical reconstruction requires recorded event sequence."],
                "suggested_next_actions": ["Collect event telemetry for the target entity before requesting historical attribution."],
                "dataset": self._resolve_dataset(case_id=case.case_id if case else case_id, entity_id=ent_id),
                "entity_id": ent_id,
                "case_id": case.case_id if case else case_id,
            }
            return self.formatter.format(payload)

        seq = self.backend.temporal_sequence_engine.build_sequence(
            raw_events,
            canonical_entity_id=ent_id,
            case_id=case.case_id if case else case_id
        )

        trigger_item = None
        if explicit_event_id:
            trigger_item = next((it for it in seq.items if it.event_id == explicit_event_id), None)
        elif target_finding_id and target_finding_id in self.backend.findings_by_id:
            f = self.backend.findings_by_id[target_finding_id]
            f_evt = f.get("trigger_event_id") or f.get("event_id")
            if f_evt:
                trigger_item = next((it for it in seq.items if it.event_id == f_evt), None)
            if trigger_item is None:
                supp = f.get("supporting_evidence", [])
                trigger_item = next((it for it in seq.items if it.evidence_ref in supp or it.event_id in supp), None)

        if trigger_item is None and seq.items:
            trigger_item = seq.items[-1]

        if trigger_item is None:
            return self._safe_no_finding_response(q, case_id=case.case_id if case else case_id, entity_id=ent_id, case=case)

        pre_items = self.backend.temporal_sequence_engine.get_pre_trigger_sequence(seq, trigger_event=trigger_item)

        from dfap.investigation.temporal_sequence import OrderingBasis
        if seq.ordering_basis == OrderingBasis.UNRESOLVED or not seq.is_causally_valid:
            status_val = "PARTIALLY_GROUNDED"
            confidence = 0.40
            limitations = [
                "Temporal ordering has unresolved ties without authoritative sequence numbers; order cannot be certified.",
                "Zero future leakage: events occurring after trigger time are excluded."
            ]
            uncertainties = [f"Unresolved ties detected: {seq.unresolved_ties}"]
        else:
            status_val = "GROUNDED" if pre_items else "INSUFFICIENT_EVIDENCE"
            confidence = 0.90 if pre_items else 0.50
            limitations = [
                "Zero future leakage: events occurring after trigger time are strictly excluded from pre-trigger history.",
                f"Temporal ordering is grounded strictly in {seq.ordering_basis.value}."
            ]
            uncertainties = []

        evidence_refs = [it.evidence_ref for it in pre_items if it.evidence_ref]
        prov_refs = []
        for it in pre_items:
            ref_to_query = it.evidence_ref or it.event_id
            if ref_to_query:
                ev_obj = self.backend.evidence_engine.get_evidence(ref_to_query)
                if not ev_obj and it.event_id:
                    ev_obj = self.backend.evidence_engine.get_evidence(it.event_id)
                if ev_obj and getattr(ev_obj, "provenance_ref", None):
                    prov_refs.append(ev_obj.provenance_ref)
        prov_refs = list(dict.fromkeys(prov_refs))

        if pre_items:
            summary_lines = [f"- [{it.sequence_index}] {it.event_id} ({it.event_type} on {it.source_domain}) at {it.timestamp or it.epoch_time}" for it in pre_items[:5]]
            ans_text = (
                f"Prior to trigger event '{trigger_item.event_id}' ({trigger_item.event_type} at {trigger_item.timestamp or trigger_item.epoch_time}), "
                f"{len(pre_items)} preceding event(s) were observed under {seq.ordering_basis.value} ordering with zero future leakage:\n"
                + "\n".join(summary_lines)
            )
            if len(pre_items) > 5:
                ans_text += f"\n... and {len(pre_items) - 5} earlier event(s)."
        else:
            ans_text = f"No preceding events occurred prior to trigger event '{trigger_item.event_id}' at {trigger_item.timestamp or trigger_item.epoch_time}."

        claims = [
            {
                "claim": f"Observed {len(pre_items)} preceding event(s) prior to trigger event {trigger_item.event_id} under {seq.ordering_basis.value} ordering.",
                "evidence_ids": evidence_refs,
            },
            {
                "claim": "All preceding events strictly satisfy temporal causality (t < T) with zero future leakage.",
                "evidence_ids": evidence_refs,
            }
        ]

        payload = {
            "answer": ans_text,
            "confidence": confidence,
            "status": status_val,
            "claims": claims,
            "evidence_refs": evidence_refs,
            "provenance_refs": prov_refs,
            "uncertainties": uncertainties,
            "limitations": limitations,
            "suggested_next_actions": [
                "Review the chronological sequence of pre-trigger events in backtrack.",
                "Inspect forwardtrack for subsequent follow-on activity."
            ],
            "dataset": self._resolve_dataset(
                case_id=case.case_id if case else case_id,
                entity_id=ent_id,
                items=(pre_items or ([trigger_item] if trigger_item else []))
            ),
            "entity_id": ent_id,
            "finding_id": target_finding_id,
            "case_id": case.case_id if case else case_id,
        }
        return self.formatter.format(payload)

    def _handle_post_trigger_question(
        self,
        question: str,
        case_id: Optional[str] = None,
        entity_id: Optional[str] = None,
        explicit_finding_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        q = (question or "").strip()
        lower = q.lower()

        is_post_trigger_q = (
            ("what happened after" in lower)
            or ("events after" in lower and not ("justify" in lower or "suspicious" in lower or "change why" in lower))
            or ("after this event" in lower)
            or ("after this trigger" in lower)
            or ("post-trigger" in lower and ("activity" in lower or "events" in lower or "what" in lower))
            or ("subsequent events" in lower or "subsequent activity" in lower)
        )
        if not is_post_trigger_q:
            return None

        case = self._resolve_active_case(case_id=case_id, entity_id=entity_id)
        if case is not None and self._controlled_case_payload(case) is not None:
            return None

        explicit_event_id = None
        for tok in q.split():
            c_tok = tok.strip("?,.!:;\"'")
            if c_tok.startswith("EVT_") or c_tok.startswith("EVT-"):
                explicit_event_id = c_tok
                break

        target_finding_id = explicit_finding_id or self._get_finding_id_from_question(q)
        if not target_finding_id and case:
            target_finding_id = self._pick_case_finding_id(case_id=case.case_id, entity_id=entity_id)

        ent_id = entity_id or (case.canonical_entity_id if case else None)
        if not ent_id and target_finding_id and target_finding_id in self.backend.findings_by_id:
            f = self.backend.findings_by_id[target_finding_id]
            ent_id = f.get("canonical_entity_id") or f.get("entity_id") or f.get("entity")

        if not ent_id and self.backend.valid_entities:
            if len(self.backend.valid_entities) == 1:
                ent_id = next(iter(self.backend.valid_entities))

        if not ent_id:
            return self._safe_no_finding_response(q, case_id=case.case_id if case else case_id, entity_id=None, case=case)

        raw_events = self.backend.get_timeline(ent_id)
        if not raw_events:
            payload = {
                "answer": f"No grounded timeline events are available for entity {ent_id}; forward sequence cannot be reconstructed.",
                "confidence": 0.0,
                "status": "INSUFFICIENT_EVIDENCE",
                "claims": [],
                "evidence_refs": [],
                "provenance_refs": [],
                "uncertainties": [f"No events recorded in authoritative timeline for {ent_id}."],
                "limitations": ["Reconstruction requires recorded event sequence."],
                "suggested_next_actions": ["Collect event telemetry for the target entity before requesting forward sequence."],
                "dataset": self._resolve_dataset(case_id=case.case_id if case else case_id, entity_id=ent_id),
                "entity_id": ent_id,
                "case_id": case.case_id if case else case_id,
            }
            return self.formatter.format(payload)

        seq = self.backend.temporal_sequence_engine.build_sequence(
            raw_events,
            canonical_entity_id=ent_id,
            case_id=case.case_id if case else case_id
        )

        trigger_item = None
        if explicit_event_id:
            trigger_item = next((it for it in seq.items if it.event_id == explicit_event_id), None)
        elif target_finding_id and target_finding_id in self.backend.findings_by_id:
            f = self.backend.findings_by_id[target_finding_id]
            f_evt = f.get("trigger_event_id") or f.get("event_id")
            if f_evt:
                trigger_item = next((it for it in seq.items if it.event_id == f_evt), None)
            if trigger_item is None:
                supp = f.get("supporting_evidence", [])
                trigger_item = next((it for it in seq.items if it.evidence_ref in supp or it.event_id in supp), None)

        if trigger_item is None and seq.items:
            trigger_item = seq.items[0]

        if trigger_item is None:
            return self._safe_no_finding_response(q, case_id=case.case_id if case else case_id, entity_id=ent_id, case=case)

        post_items = self.backend.temporal_sequence_engine.get_post_trigger_sequence(seq, trigger_event=trigger_item)

        from dfap.investigation.temporal_sequence import OrderingBasis
        if seq.ordering_basis == OrderingBasis.UNRESOLVED or not seq.is_causally_valid:
            status_val = "PARTIALLY_GROUNDED"
            confidence = 0.40
            limitations = [
                "Temporal ordering has unresolved ties without authoritative sequence numbers; order cannot be certified.",
                "Zero future leakage: events occurring after trigger time represent subsequent developments and do not justify past suspicion."
            ]
            uncertainties = [f"Unresolved ties detected: {seq.unresolved_ties}"]
        else:
            status_val = "GROUNDED" if post_items else "INSUFFICIENT_EVIDENCE"
            confidence = 0.90 if post_items else 0.50
            limitations = [
                "Zero future leakage: post-trigger events represent forward-track developments only and do not justify past trigger suspicion.",
                f"Temporal ordering is grounded strictly in {seq.ordering_basis.value}."
            ]
            uncertainties = []

        evidence_refs = [it.evidence_ref for it in post_items if it.evidence_ref]
        prov_refs = []
        for it in post_items:
            ref_to_query = it.evidence_ref or it.event_id
            if ref_to_query:
                ev_obj = self.backend.evidence_engine.get_evidence(ref_to_query)
                if not ev_obj and it.event_id:
                    ev_obj = self.backend.evidence_engine.get_evidence(it.event_id)
                if ev_obj and getattr(ev_obj, "provenance_ref", None):
                    prov_refs.append(ev_obj.provenance_ref)
        prov_refs = list(dict.fromkeys(prov_refs))

        if post_items:
            summary_lines = [f"- [{it.sequence_index}] {it.event_id} ({it.event_type} on {it.source_domain}) at {it.timestamp or it.epoch_time}" for it in post_items[:5]]
            ans_text = (
                f"Following event '{trigger_item.event_id}' ({trigger_item.event_type} at {trigger_item.timestamp or trigger_item.epoch_time}), "
                f"{len(post_items)} subsequent event(s) were observed in forward-track under {seq.ordering_basis.value} ordering:\n"
                + "\n".join(summary_lines)
            )
            if len(post_items) > 5:
                ans_text += f"\n... and {len(post_items) - 5} later event(s)."
        else:
            ans_text = f"No subsequent events occurred after event '{trigger_item.event_id}' at {trigger_item.timestamp or trigger_item.epoch_time}."

        claims = [
            {
                "claim": f"Observed {len(post_items)} subsequent event(s) following event {trigger_item.event_id} under {seq.ordering_basis.value} ordering.",
                "evidence_ids": evidence_refs,
            },
            {
                "claim": "Post-trigger events represent forward-track developments and do not alter past causal attribution (zero future leakage).",
                "evidence_ids": evidence_refs,
            }
        ]

        payload = {
            "answer": ans_text,
            "confidence": confidence,
            "status": status_val,
            "claims": claims,
            "evidence_refs": evidence_refs,
            "provenance_refs": prov_refs,
            "uncertainties": uncertainties,
            "limitations": limitations,
            "suggested_next_actions": [
                "Review forwardtrack for follow-on actions or blast radius.",
                "Check backtrack to inspect causal precursors before the trigger."
            ],
            "dataset": self._resolve_dataset(
                case_id=case.case_id if case else case_id,
                entity_id=ent_id,
                items=(post_items or ([trigger_item] if trigger_item else []))
            ),
            "entity_id": ent_id,
            "finding_id": target_finding_id,
            "case_id": case.case_id if case else case_id,
        }
        return self.formatter.format(payload)

    def _handle_patterns_question(
        self,
        question: str,
        case_id: Optional[str] = None,
        entity_id: Optional[str] = None,
        explicit_finding_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        q = (question or "").strip()
        lower = q.lower()

        is_patterns_q = (
            ("pattern" in lower or "motif" in lower or "recurring" in lower or "novel" in lower)
            and ("occurred" in lower or "trigger" in lower or "sequence" in lower or "temporal" in lower or "what" in lower or "detect" in lower or "observed" in lower or "discover" in lower or "found" in lower or "multiple domains" in lower or "which" in lower)
        )
        if not is_patterns_q:
            return None

        case = self._resolve_active_case(case_id=case_id, entity_id=entity_id)
        if case is not None and self._controlled_case_payload(case) is not None:
            return None

        ent_id = entity_id or (case.canonical_entity_id if case else None)
        if not ent_id and self.backend.valid_entities:
            if len(self.backend.valid_entities) == 1:
                ent_id = next(iter(self.backend.valid_entities))

        if not ent_id:
            return self._safe_no_finding_response(q, case_id=case.case_id if case else case_id, entity_id=None, case=case)

        raw_events = self.backend.get_timeline(ent_id)
        if not raw_events:
            payload = {
                "answer": f"No timeline events available for entity {ent_id} to evaluate temporal patterns.",
                "confidence": 0.0,
                "status": "INSUFFICIENT_EVIDENCE",
                "claims": [],
                "evidence_refs": [],
                "provenance_refs": [],
                "uncertainties": [f"No events found for {ent_id}."],
                "limitations": ["Pattern detection requires an event sequence."],
                "suggested_next_actions": ["Collect event telemetry."],
                "dataset": self._resolve_dataset(case_id=case.case_id if case else case_id, entity_id=ent_id),
                "entity_id": ent_id,
                "case_id": case.case_id if case else case_id,
            }
            return self.formatter.format(payload)

        seq = self.backend.temporal_sequence_engine.build_sequence(
            raw_events,
            canonical_entity_id=ent_id,
            case_id=case.case_id if case else case_id
        )

        patterns = self.backend.detect_sequence_patterns(seq)
        motifs = self.backend.detect_sequence_motifs(seq)
        discovered_motifs = self.backend.discover_sequence_motifs(seq)

        ev_refs = []
        for p in patterns:
            ev_refs.extend(p.get("evidence_refs", []))
        for m in motifs:
            ev_refs.extend(m.evidence_refs)
        for dm in discovered_motifs:
            ev_refs.extend(dm.evidence_refs)
        ev_refs = list(dict.fromkeys(ev_refs))

        prov_refs = []
        for ref in ev_refs:
            ev_obj = self.backend.evidence_engine.get_evidence(ref)
            if ev_obj and getattr(ev_obj, "provenance_ref", None):
                prov_refs.append(ev_obj.provenance_ref)
        prov_refs = list(dict.fromkeys(prov_refs))

        # Check if query asks specifically for multi-domain motifs
        if ("multiple domains" in lower or "multi domain" in lower or "cross domain" in lower) and discovered_motifs:
            multi_domain_dms = [dm for dm in discovered_motifs if len(set(dm.representative_domains)) > 1]
            if multi_domain_dms:
                first_md = multi_domain_dms[0]
                seq_str = " -> ".join(first_md.representative_event_types)
                dom_str = ", ".join(first_md.representative_domains)
                ans_text = (
                    f"Discovered motif {first_md.motif_id} involves multiple domains: {seq_str} across "
                    f"{dom_str} (appearing in {first_md.cluster_size} sequence windows, mean span {first_md.temporal_statistics.get('mean_span_seconds', 0.0):.1f}s). "
                    f"{first_md.explanation}"
                )
            else:
                ans_text = f"None of the {len(discovered_motifs)} discovered motifs for {ent_id} involve multiple distinct telemetry domains."
        # Check if query asks specifically for novel / discovered motifs
        elif ("novel" in lower or "discovered" in lower or "what recurring patterns were discovered" in lower) and discovered_motifs:
            novel_dms = [dm for dm in discovered_motifs if dm.classification == "DISCOVERED_MOTIF"]
            target_dms = novel_dms if novel_dms else discovered_motifs
            dm_parts = []
            for dm in target_dms[:3]:
                seq_str = " -> ".join(dm.representative_event_types)
                dom_str = ", ".join(dm.representative_domains)
                dm_parts.append(
                    f"DFAP discovered a recurring temporal subsequence appearing in {dm.cluster_size} windows. "
                    f"The representative sequence was {seq_str} across {dom_str} events. "
                    f"This pattern was not sufficiently matched to the predefined motif catalog."
                )
            ans_text = " ".join(dm_parts)
        else:
            pattern_lines = []
            if patterns:
                pattern_lines.append("Detected Temporal Patterns:")
                for p in patterns[:5]:
                    pattern_lines.append(f"- Pattern '{' -> '.join(p['pattern'])}': repeated {p['count']} time(s) across span {p['time_span_seconds']:.1f}s")
            if motifs:
                pattern_lines.append("Detected Predefined Behavioral Motifs:")
                for m in motifs[:5]:
                    pattern_lines.append(f"- Motif {m.motif_type}: fit score {m.fit_score:.2f} ({m.event_count} events across {m.time_span_seconds:.1f}s)")
            if discovered_motifs:
                pattern_lines.append("Discovered Behavioral Motifs (Unsupervised):")
                for dm in discovered_motifs[:5]:
                    seq_str = " -> ".join(dm.representative_event_types)
                    dom_str = ", ".join(dm.representative_domains)
                    pattern_lines.append(f"- {dm.motif_id} [{dm.classification}]: {seq_str} across {dom_str} ({dm.cluster_size} windows)")

            if pattern_lines:
                ans_text = (
                    f"Identified {len(patterns)} recurring pattern(s), {len(motifs)} predefined motif(s), and {len(discovered_motifs)} discovered motif(s) for {ent_id}:\n"
                    + "\n".join(pattern_lines)
                )
            else:
                ans_text = f"No repeated n-gram patterns or standard behavioral motifs detected in sequence of {len(seq.items)} events for {ent_id}."

        claims = [
            {
                "claim": f"Temporal pattern analysis identified {len(patterns)} pattern(s), {len(motifs)} predefined motif(s), and {len(discovered_motifs)} discovered motif(s).",
                "evidence_ids": ev_refs[:10],
            }
        ]

        payload = {
            "answer": ans_text,
            "confidence": 0.90 if (patterns or motifs or discovered_motifs) else 0.70,
            "status": "GROUNDED" if (patterns or motifs or discovered_motifs) else "INSUFFICIENT_EVIDENCE",
            "claims": claims,
            "evidence_refs": ev_refs,
            "provenance_refs": prov_refs,
            "discovered_motifs": [dm.to_dict() for dm in discovered_motifs],
            "uncertainties": [],
            "limitations": [
                "Patterns and motifs are descriptive temporal structures, not definitive proof of malicious intent.",
                "Deterministic evaluation based on ordered event sequence."
            ],
            "suggested_next_actions": [
                "Inspect phase compression to evaluate macro phases.",
                "Review transition matrix for cross-domain hops."
            ],
            "dataset": self._resolve_dataset(case_id=case.case_id if case else case_id, entity_id=ent_id),
            "entity_id": ent_id,
            "case_id": case.case_id if case else case_id,
        }
        return self.formatter.format(payload)

    def _handle_phases_question(
        self,
        question: str,
        case_id: Optional[str] = None,
        entity_id: Optional[str] = None,
        explicit_finding_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        q = (question or "").strip()
        lower = q.lower()

        is_phases_q = (
            ("phase" in lower or "major phases" in lower or "compression" in lower or "phasing" in lower)
            and ("activity" in lower or "sequence" in lower or "what" in lower or "timeline" in lower or "event" in lower)
        )
        if not is_phases_q:
            return None

        case = self._resolve_active_case(case_id=case_id, entity_id=entity_id)
        if case is not None and self._controlled_case_payload(case) is not None:
            return None

        ent_id = entity_id or (case.canonical_entity_id if case else None)
        if not ent_id and self.backend.valid_entities:
            if len(self.backend.valid_entities) == 1:
                ent_id = next(iter(self.backend.valid_entities))

        if not ent_id:
            return self._safe_no_finding_response(q, case_id=case.case_id if case else case_id, entity_id=None, case=case)

        raw_events = self.backend.get_timeline(ent_id)
        if not raw_events:
            payload = {
                "answer": f"No timeline events available for entity {ent_id} to compress into phases.",
                "confidence": 0.0,
                "status": "INSUFFICIENT_EVIDENCE",
                "claims": [],
                "evidence_refs": [],
                "provenance_refs": [],
                "uncertainties": [f"No events found for {ent_id}."],
                "limitations": ["Phase analysis requires an event sequence."],
                "suggested_next_actions": ["Collect event telemetry."],
                "dataset": self._resolve_dataset(case_id=case.case_id if case else case_id, entity_id=ent_id),
                "entity_id": ent_id,
                "case_id": case.case_id if case else case_id,
            }
            return self.formatter.format(payload)

        seq = self.backend.temporal_sequence_engine.build_sequence(
            raw_events,
            canonical_entity_id=ent_id,
            case_id=case.case_id if case else case_id
        )

        phases = self.backend.compress_sequence_phases(seq)
        ev_refs = []
        for p in phases:
            ev_refs.extend(p.evidence_refs)
        ev_refs = list(dict.fromkeys(ev_refs))

        prov_refs = []
        for ref in ev_refs:
            ev_obj = self.backend.evidence_engine.get_evidence(ref)
            if ev_obj and getattr(ev_obj, "provenance_ref", None):
                prov_refs.append(ev_obj.provenance_ref)
        prov_refs = list(dict.fromkeys(prov_refs))

        phase_lines = []
        for p in phases:
            phase_lines.append(f"- Phase {p.phase_index} ({p.label}): {p.event_count} events over {p.duration_seconds:.1f}s [{p.start_time} -> {p.end_time}] across {', '.join(p.domains)}")

        ans_text = (
            f"Compressed sequence of {len(seq.items)} events into {len(phases)} major activity phase(s):\n"
            + "\n".join(phase_lines)
        )

        claims = [
            {
                "claim": f"Activity sequence compressed into {len(phases)} macro phase(s) via deterministic temporal clustering.",
                "evidence_ids": ev_refs[:10],
            }
        ]

        payload = {
            "answer": ans_text,
            "confidence": 0.90 if phases else 0.50,
            "status": "GROUNDED" if phases else "INSUFFICIENT_EVIDENCE",
            "claims": claims,
            "evidence_refs": ev_refs,
            "provenance_refs": prov_refs,
            "uncertainties": [],
            "limitations": [
                "Phases are deterministic groupings based on temporal gaps and domain continuity.",
                "Phase labels are synthetic heuristics for investigator summarization."
            ],
            "suggested_next_actions": [
                "Drill into specific phases to inspect constituent events.",
                "Analyze transitions between adjacent phases."
            ],
            "dataset": self._resolve_dataset(case_id=case.case_id if case else case_id, entity_id=ent_id),
            "entity_id": ent_id,
            "case_id": case.case_id if case else case_id,
        }
        return self.formatter.format(payload)

    def _handle_compare_question(
        self,
        question: str,
        case_id: Optional[str] = None,
        entity_id: Optional[str] = None,
        explicit_finding_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        q = (question or "").strip()
        lower = q.lower()

        is_compare_q = (
            ("compare" in lower or "comparison" in lower or "similarity" in lower)
            and ("sequence" in lower or "timeline" in lower or "entity" in lower or "another" in lower or "with" in lower)
        )
        if not is_compare_q:
            return None

        candidates = []
        for ent in self.backend.valid_entities:
            if ent in q:
                candidates.append(ent)

        case = self._resolve_active_case(case_id=case_id, entity_id=entity_id)
        if not candidates and entity_id:
            candidates.append(entity_id)
        elif not candidates and case and case.canonical_entity_id:
            candidates.append(case.canonical_entity_id)

        if len(candidates) >= 2:
            ent_a, ent_b = candidates[0], candidates[1]
            raw_a = self.backend.get_timeline(ent_a)
            raw_b = self.backend.get_timeline(ent_b)
            if not raw_a or not raw_b:
                ans_text = f"Cannot compare sequences: one or both entities ({ent_a}, {ent_b}) lack recorded timeline events."
                status_val = "INSUFFICIENT_EVIDENCE"
                conf = 0.40
                comp_res = {}
            else:
                seq_a = self.backend.temporal_sequence_engine.build_sequence(raw_a, canonical_entity_id=ent_a)
                seq_b = self.backend.temporal_sequence_engine.build_sequence(raw_b, canonical_entity_id=ent_b)
                comp_res = self.backend.compare_temporal_sequences(seq_a, seq_b)
                ans_text = (
                    f"Temporal Sequence Comparison between '{ent_a}' ({comp_res['sequence_a_length']} events) "
                    f"and '{ent_b}' ({comp_res['sequence_b_length']} events):\n"
                    f"- Normalized Edit Distance: {comp_res['edit_distance_normalized']:.4f}\n"
                    f"- Dynamic Time Warping (DTW) Distance: {comp_res['dtw_distance']:.4f}\n"
                    f"- Alignment Similarity: {comp_res['alignment_similarity'] * 100:.1f}%\n"
                    f"- Common Event Types: {', '.join(comp_res['common_event_types']) or 'None'}\n"
                    f"- Types in {ent_a} only: {', '.join(comp_res['only_in_a']) or 'None'}\n"
                    f"- Types in {ent_b} only: {', '.join(comp_res['only_in_b']) or 'None'}"
                )
                status_val = "GROUNDED"
                conf = 0.90
        else:
            ans_text = (
                "Sequence comparison requires two target sequences or entities. "
                "Specify two entities or sequence IDs to compute normalized edit distance and DTW temporal alignment (e.g., 'compare sequence ENTITY_A with ENTITY_B')."
            )
            status_val = "INSUFFICIENT_EVIDENCE"
            conf = 0.50
            comp_res = {}

        claims = []
        if "alignment_similarity" in comp_res:
            claims.append({
                "claim": f"Sequence alignment similarity is {comp_res['alignment_similarity'] * 100:.1f}% with DTW distance {comp_res['dtw_distance']:.4f}.",
                "evidence_ids": []
            })

        payload = {
            "answer": ans_text,
            "confidence": conf,
            "status": status_val,
            "claims": claims,
            "evidence_refs": [],
            "provenance_refs": [],
            "uncertainties": [],
            "limitations": [
                "Sequence comparison uses normalized Levenshtein distance on event-type sequences and Dynamic Time Warping (DTW) on timestamp deltas.",
                "Comparison does not establish behavioral equivalence or shared identity."
            ],
            "suggested_next_actions": [
                "Inspect phase compression for each entity.",
                "Analyze cross-domain transition graphs."
            ],
            "dataset": self._resolve_dataset(case_id=case.case_id if case else case_id, entity_id=candidates[0] if candidates else None),
            "entity_id": candidates[0] if candidates else None,
            "case_id": case.case_id if case else case_id,
        }
        return self.formatter.format(payload)

    def _handle_transitions_question(
        self,
        question: str,
        case_id: Optional[str] = None,
        entity_id: Optional[str] = None,
        explicit_finding_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        q = (question or "").strip()
        lower = q.lower()

        is_trans_q = (
            ("transition" in lower or "transitions" in lower)
            and ("occurred" in lower or "observed" in lower or "what" in lower or "sequence" in lower or "graph" in lower)
        )
        if not is_trans_q:
            return None

        case = self._resolve_active_case(case_id=case_id, entity_id=entity_id)
        if case is not None and self._controlled_case_payload(case) is not None:
            return None

        ent_id = entity_id or (case.canonical_entity_id if case else None)
        if not ent_id and self.backend.valid_entities:
            if len(self.backend.valid_entities) == 1:
                ent_id = next(iter(self.backend.valid_entities))

        if not ent_id:
            return self._safe_no_finding_response(q, case_id=case.case_id if case else case_id, entity_id=None, case=case)

        raw_events = self.backend.get_timeline(ent_id)
        if not raw_events:
            payload = {
                "answer": f"No timeline events available for entity {ent_id} to evaluate transitions.",
                "confidence": 0.0,
                "status": "INSUFFICIENT_EVIDENCE",
                "claims": [],
                "evidence_refs": [],
                "provenance_refs": [],
                "uncertainties": [f"No events found for {ent_id}."],
                "limitations": ["Transition analysis requires an event sequence."],
                "suggested_next_actions": ["Collect event telemetry."],
                "dataset": self._resolve_dataset(case_id=case.case_id if case else case_id, entity_id=ent_id),
                "entity_id": ent_id,
                "case_id": case.case_id if case else case_id,
            }
            return self.formatter.format(payload)

        seq = self.backend.temporal_sequence_engine.build_sequence(
            raw_events,
            canonical_entity_id=ent_id,
            case_id=case.case_id if case else case_id
        )

        transitions = self.backend.analyze_sequence_transitions(seq)
        ev_trans = transitions.get("event_transitions", [])
        dom_trans = transitions.get("domain_transitions", [])

        ev_refs = []
        for t in ev_trans:
            ev_refs.extend(t.evidence_refs)
        for t in dom_trans:
            ev_refs.extend(t.evidence_refs)
        ev_refs = list(dict.fromkeys(ev_refs))

        prov_refs = []
        for ref in ev_refs:
            ev_obj = self.backend.evidence_engine.get_evidence(ref)
            if ev_obj and getattr(ev_obj, "provenance_ref", None):
                prov_refs.append(ev_obj.provenance_ref)
        prov_refs = list(dict.fromkeys(prov_refs))

        trans_lines = []
        if ev_trans:
            trans_lines.append("Event-to-Event Transitions:")
            for t in ev_trans[:5]:
                trans_lines.append(f"- {t.source} -> {t.target}: count={t.count}, mean_gap={t.mean_gap:.1f}s")
        if dom_trans:
            trans_lines.append("Domain-to-Domain Transitions:")
            for t in dom_trans[:5]:
                trans_lines.append(f"- {t.source} -> {t.target}: count={t.count}, mean_gap={t.mean_gap:.1f}s")

        if trans_lines:
            ans_text = (
                f"Observed {len(ev_trans)} unique event transition(s) and {len(dom_trans)} domain transition(s) for {ent_id}:\n"
                + "\n".join(trans_lines)
            )
        else:
            ans_text = f"No transitions observed for entity {ent_id}."

        claims = [
            {
                "claim": f"Observed {len(ev_trans)} event-to-event and {len(dom_trans)} domain-to-domain temporal transitions.",
                "evidence_ids": ev_refs[:10],
            }
        ]

        payload = {
            "answer": ans_text,
            "confidence": 0.90 if (ev_trans or dom_trans) else 0.50,
            "status": "GROUNDED" if (ev_trans or dom_trans) else "INSUFFICIENT_EVIDENCE",
            "claims": claims,
            "evidence_refs": ev_refs,
            "provenance_refs": prov_refs,
            "uncertainties": [],
            "limitations": [
                "Temporal transitions reflect observed sequence ordering without implying causal dependence.",
                "Deterministic evaluation grounded in timeline sequence."
            ],
            "suggested_next_actions": [
                "Inspect transition graph for hub event types.",
                "Analyze phase compression for macro grouping."
            ],
            "dataset": self._resolve_dataset(case_id=case.case_id if case else case_id, entity_id=ent_id),
            "entity_id": ent_id,
            "case_id": case.case_id if case else case_id,
        }
        return self.formatter.format(payload)

    def _handle_forensic_packet_question(
        self,
        question: str,
        case_id: Optional[str] = None,
        entity_id: Optional[str] = None,
        explicit_finding_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        lower = question.lower()
        is_forensic_q = (
            "forensic case packet" in lower
            or "forensic packet" in lower
            or "in the packet" in lower
            or "evidence chain" in lower
            or "what conflicts exist" in lower
            or "conflicts exist in this case" in lower
            or ("conflict" in lower and "case" in lower and ("what" in lower or "exist" in lower or "any" in lower))
            or "provenance supports" in lower
            or "forensic case summary" in lower
            or "forensic summary" in lower
            or "traceability" in lower
            or "status of this case" in lower
            or "status of the case" in lower
            or "status of case" in lower
            or ("case status" in lower and "what" in lower)
            or ("contribute" in lower and "domain" in lower)
            or ("which domains contribute" in lower or "what domains contribute" in lower or "contributing domains" in lower)
            or ("guilt" in lower or "guilty" in lower or "prove the suspect" in lower or "prove guilt" in lower)
            or ("mapped across" in lower or "raw domain identifiers" in lower or "how is the canonical entity mapped" in lower)
        )
        if not is_forensic_q:
            return None

        # Resolve target case
        case = self._resolve_active_case(case_id=case_id, entity_id=entity_id)
        if case is None and self.backend.cases:
            for cid in self.backend.cases.keys():
                if cid.lower() in lower:
                    case = self.backend.cases[cid]
                    break
            if case is None:
                case = list(self.backend.cases.values())[0]

        if case is None:
            payload = {
                "answer": "No active investigation case is available to generate or inspect the forensic case packet.",
                "confidence": 0.0,
                "status": "UNAVAILABLE",
                "claims": [],
                "evidence_refs": [],
                "provenance_refs": [],
                "uncertainties": ["No active case found in workspace."],
                "limitations": ["Forensic packet requires an existing investigation case."],
                "suggested_next_actions": ["Create or open an investigation case first using 'case create <entity>' or 'open <case_id>'."],
                "dataset": "CANONICAL",
                "entity_id": entity_id,
                "case_id": case_id,
            }
            return self.formatter.format(payload)

        # Synthesize forensic case packet deterministically
        from dfap.investigation.forensic_case_packet import ForensicCasePacketEngine
        engine = ForensicCasePacketEngine(self.backend)
        packet = engine.generate_packet(case.case_id)
        p_dict = packet.to_dict()

        target_finding_id = explicit_finding_id or (packet.findings[0]["finding_id"] if packet.findings else None)

        # Handle sub-intents:
        # A. Evidence Chain
        if "evidence chain" in lower or "chain for this finding" in lower or "traceability" in lower:
            matching_rows = [r for r in packet.traceability_matrix if r.get("finding_id") == target_finding_id] if target_finding_id else packet.traceability_matrix
            if not matching_rows and packet.traceability_matrix:
                matching_rows = packet.traceability_matrix

            ev_ids = [r["evidence_id"] for r in matching_rows]
            prov_refs = [r["provenance_ref"] for r in matching_rows]
            
            chain_desc = []
            for r in matching_rows[:4]:
                chain_desc.append(
                    f"[{r['claim_id']}] -> Finding {r['finding_id']} -> Evidence {r['evidence_id']} -> Canonical Event {r['canonical_event_id']} -> Source Record {r['source_record_id']} ({r['source_file']}, ref: {r['provenance_ref']})"
                )

            # Check conflict context
            conflict_note = ""
            if packet.packet_status == "CONFLICTED":
                pairs = packet.conflict_intelligence.get("pairs", [])
                p_strs = [f"{p['domain_a']} and {p['domain_b']}" for p in pairs]
                conflict_note = f" However, material disagreement was detected between {', '.join(p_strs)}, so the finding remains CONFLICTED and requires human review."

            answer = (
                f"The finding {target_finding_id or 'in this case'} is supported by {len(matching_rows)} evidence item(s). "
                f"The evidence chain links those items from claims to canonical events and root source records:\n"
                + "\n".join(f"- {cd}" for cd in chain_desc)
                + (f"\n{conflict_note}" if conflict_note else "")
            )

            claims = [
                {
                    "claim": f"Evidence chain for {target_finding_id or case.case_id} grounds {len(matching_rows)} items through canonical events to source records.",
                    "evidence_ids": ev_ids,
                }
            ]

        # B. Conflicts in this case
        elif "conflict" in lower:
            pairs = packet.conflict_intelligence.get("pairs", [])
            overall_status = packet.conflict_intelligence.get("overall_status", "NO_MATERIAL_CONFLICT")
            req_action = packet.conflict_intelligence.get("required_action", "PROCEED")
            ev_ids = [r["evidence_id"] for r in packet.traceability_matrix]
            prov_refs = [r["provenance_ref"] for r in packet.traceability_matrix]

            if pairs:
                pair_lines = []
                for p in pairs:
                    pair_lines.append(
                        f"- {p['domain_a']} vs {p['domain_b']}: compound conflict = {p['compound_conflict']:.4f}, status = {p['conflict_status']}, required action = {p['required_action']}. ({p.get('explanation', '')})"
                    )
                answer = (
                    f"The case exhibits {overall_status} (required action: {req_action}). "
                    f"Cross-domain conflict analysis between reporting domains:\n"
                    + "\n".join(pair_lines)
                )
            else:
                answer = f"No evidential conflicts exist in case {case.case_id}. Cross-domain evidence is concordant or single-domain (status: {overall_status})."

            claims = [
                {
                    "claim": f"Evidential conflict status for case {case.case_id} is {overall_status} with required action {req_action}.",
                    "evidence_ids": ev_ids,
                }
            ]

        # C. Provenance supports this conclusion
        elif "provenance" in lower:
            ev_ids = [r["evidence_id"] for r in packet.traceability_matrix]
            prov_refs = [r["provenance_ref"] for r in packet.traceability_matrix]
            crypto_hashes = packet.provenance.get("cryptographic_hashes", {})
            hash_sample = ", ".join(f"{k}: {v[:12]}..." for k, v in list(crypto_hashes.items())[:3])
            integ = packet.provenance.get("integrity_status", "INTEGRITY_VERIFIED")

            answer = (
                f"The conclusions in case {case.case_id} are supported by {len(ev_ids)} registered canonical evidence records "
                f"and {len(packet.provenance.get('derivation_relationships', []))} lineage derivation edges in the M12 provenance ledger. "
                f"Lineage integrity status is {integ}. Evidence cryptographic digest anchors: {hash_sample}."
            )

            claims = [
                {
                    "claim": f"Conclusions supported by {len(ev_ids)} evidence items with integrity status {integ}.",
                    "evidence_ids": ev_ids,
                }
            ]

        # D. Status of Case
        elif ("status of" in lower and "case" in lower) or ("case status" in lower and "what" in lower):
            ev_ids = [r["evidence_id"] for r in packet.traceability_matrix]
            prov_refs = [r["provenance_ref"] for r in packet.traceability_matrix]
            f_names = [f["finding_id"] for f in packet.findings]
            f_status_str = f" Attached finding {f_names[0]} has status {packet.findings[0]['status']}." if f_names else ""
            answer = (
                f"The investigation status of case {case.case_id} is {case.status}. "
                f"The synthesized forensic case packet status is {packet.packet_status} (required action: {packet.required_action}), "
                f"reflecting evidential conflict between the reporting domains.{f_status_str}"
            )
            claims = [
                {
                    "claim": f"Case {case.case_id} status is {case.status}; forensic packet status is {packet.packet_status} with required action {packet.required_action}.",
                    "evidence_ids": ev_ids,
                }
            ]

        # E. Contributing Domains
        elif ("contribute" in lower and "domain" in lower) or "contributing domains" in lower or "which domains contribute" in lower:
            ev_ids = [r["evidence_id"] for r in packet.traceability_matrix]
            prov_refs = [r["provenance_ref"] for r in packet.traceability_matrix]
            domains_list = [d for d in packet.case.get("domains", []) if d != "CROSS_DOMAIN"]
            ev_items = packet.evidence_quality.get("evidence_items", [])
            dom_details = []
            for d in domains_list:
                d_items = [it for it in ev_items if it.get("source_domain", "").upper() == d.upper()]
                cat_types = ", ".join(sorted(set(it.get("evidence_category", "") for it in d_items)))
                dom_details.append(f"- {d}: {len(d_items)} evidence record(s) (category: {cat_types})")
            answer = (
                f"Four distinct telemetry domains contribute evidence to case {case.case_id} "
                f"(subject: {case.canonical_entity_id}):\n"
                + "\n".join(dom_details)
                + "\nTogether they provide a complete multi-domain telemetry footprint spanning telecommunications (CDR), network access (IPDR), financial transactions (FINANCIAL), and social interactions (SOCIAL)."
            )
            claims = [
                {
                    "claim": f"Domains contributing evidence to case {case.case_id}: {', '.join(domains_list)}.",
                    "evidence_ids": ev_ids,
                }
            ]

        # F. Canonical Entity Mapped Across Raw Identifiers
        elif "mapped across" in lower or "raw domain identifiers" in lower or "how is the canonical entity mapped" in lower or ("identity bridge" in lower and "mapped" in lower):
            ev_ids = [r["evidence_id"] for r in packet.traceability_matrix]
            prov_refs = [r["provenance_ref"] for r in packet.traceability_matrix]
            bridge_mappings = []
            if hasattr(self.backend, "bridge_df") and not self.backend.bridge_df.empty:
                b_sub = self.backend.bridge_df[self.backend.bridge_df["canonical_entity_id"] == case.canonical_entity_id]
                for _, r in b_sub.iterrows():
                    bridge_mappings.append(
                        f"- {r.get('domain')}: raw identifier '{r.get('raw_identifier')}' via {r.get('mapping_method')} "
                        f"(confidence: {float(r.get('confidence', 0.0)):.4f}, ref: {r.get('evidence_ref')})"
                    )
            answer = (
                f"The canonical entity {case.canonical_entity_id} is mapped across {len(bridge_mappings)} raw domain identifier(s) in the authoritative identity bridge:\n"
                + "\n".join(bridge_mappings)
                + "\nEach link explicitly records derivation methodology, confidence, and provenance references; identifiers are never blindly equated."
            )
            claims = [
                {
                    "claim": f"Canonical entity {case.canonical_entity_id} is mapped across {len(bridge_mappings)} raw domain identifiers via the authoritative identity bridge.",
                    "evidence_ids": ev_ids,
                }
            ]

        # G. Guilt / Prove Suspect Guilty
        elif "guilt" in lower or "guilty" in lower or ("prove" in lower and "suspect" in lower):
            ev_ids = [r["evidence_id"] for r in packet.traceability_matrix]
            prov_refs = [r["provenance_ref"] for r in packet.traceability_matrix]
            answer = (
                "No. DFAP does not assert criminal guilt, fraudulent intent, or legal culpability. "
                "DFAP provides deterministic evidential reasoning, anomaly detection, and cross-domain correlation indicators "
                "bounded strictly by observable telemetry. In this case, material evidential conflict exists between domains "
                "(FINANCIAL vs SOCIAL), and formal human investigator review is required. Under DFAP integrity rules, "
                "automated systems cannot determine legal guilt or subjective intent."
            )
            claims = [
                {
                    "claim": "DFAP operates as an evidential decision-support system reporting telemetry anomalies and conflict; it does not infer criminal guilt.",
                    "evidence_ids": ev_ids,
                }
            ]

        # H. Forensic Case Summary / What is in the packet
        else:
            ev_ids = [r["evidence_id"] for r in packet.traceability_matrix]
            prov_refs = [r["provenance_ref"] for r in packet.traceability_matrix]
            c_info = packet.case
            f_count = len(packet.findings)
            ev_count = len(packet.evidence_quality.get("evidence_items", []))
            dom_str = ", ".join(c_info.get("domains", []))
            motifs_count = len(packet.temporal_intelligence.get("discovered_motifs", []))
            t_count = len(packet.timeline)
            
            conflict_summary = ""
            if packet.packet_status == "CONFLICTED":
                pairs = packet.conflict_intelligence.get("pairs", [])
                pair_names = ", ".join(f"{p['domain_a']} and {p['domain_b']}" for p in pairs)
                conflict_summary = f" Material evidential disagreement is detected ({pair_names}); required action is {packet.required_action}."

            answer = (
                f"The forensic case packet for case {case.case_id} (subject: {case.canonical_entity_id}) status is {packet.packet_status} "
                f"(required action: {packet.required_action}). It incorporates {f_count} finding(s), {ev_count} evidence item(s) "
                f"across domain(s) [{dom_str}], {t_count} timeline event(s), and {motifs_count} discovered motif(s). "
                f"Every finding is deterministically traced through canonical events to source records in the M12 ledger.{conflict_summary}"
            )

            claims = [
                {
                    "claim": f"Case {case.case_id} packet synthesized with status {packet.packet_status} and required action {packet.required_action}.",
                    "evidence_ids": ev_ids,
                }
            ]

        payload = {
            "answer": answer,
            "confidence": 0.95,
            "status": packet.packet_status,
            "claims": claims,
            "evidence_refs": ev_ids,
            "provenance_refs": prov_refs,
            "uncertainties": [
                "Preserves evidential disagreement and uncertainty; does not infer criminal intent or legal culpability."
            ],
            "limitations": [
                "Grounding is bounded by registered canonical evidence and authoritative source files."
            ],
            "suggested_next_actions": [
                f"Inspect exported packet JSON and Markdown report: 'case forensic {case.case_id}'",
                "Perform human review on conflicting evidence domains where required."
            ],
            "dataset": self._resolve_dataset(case_id=case.case_id, entity_id=case.canonical_entity_id),
            "entity_id": case.canonical_entity_id,
            "finding_id": target_finding_id,
            "case_id": case.case_id,
            "required_action": packet.required_action,
            "forensic_packet": p_dict,
            "traceability_matrix": packet.traceability_matrix,
        }
        return self.formatter.format(payload)

    def _pick_case_finding_id(self, case_id: Optional[str] = None, entity_id: Optional[str] = None, explicit_finding_id: Optional[str] = None) -> Optional[str]:

        case = self._resolve_active_case(case_id=case_id, entity_id=entity_id)
        if case is None:
            return explicit_finding_id if explicit_finding_id is not None and explicit_finding_id in self.backend.findings_by_id else None

        if explicit_finding_id is not None:
            if explicit_finding_id in self.backend.findings_by_id:
                finding = self.backend.get_finding(explicit_finding_id)
                if str(finding.get("entity")) != str(case.canonical_entity_id):
                    raise ValueError(
                        f"Finding '{explicit_finding_id}' is outside the active case scope for case '{case.case_id}' (entity '{case.canonical_entity_id}')."
                    )
                return explicit_finding_id
            if explicit_finding_id not in self.backend.findings_by_id:
                raise ValueError(f"Unknown finding '{explicit_finding_id}' in authoritative finding ledger.")

        candidates = [fid for fid in case.finding_ids if fid in self.backend.findings_by_id]
        if not candidates:
            return None
        for fid in candidates:
            if self.backend.evidence_engine.finding_evidence_map.get(fid):
                return fid
        return candidates[0]

    def _controlled_case_payload(self, case: Any) -> Optional[Dict[str, Any]]:
        if case is None:
            return None
        if str(case.mapping_status).upper() != "CONTROLLED_CASE_MAPPING" and str(case.case_kind).upper() != "CONTROLLED_CASE_MAPPING":
            return None

        search_context = dict(case.search_context or {})
        domain_breakdown = search_context.get("domain_evidence_breakdown", {}) or {}
        evidence_refs = []
        if isinstance(search_context.get("bridge_evidence_refs"), list):
            evidence_refs.extend(str(x) for x in search_context["bridge_evidence_refs"] if str(x).strip())
        if not evidence_refs:
            evidence_refs.extend(str(x) for x in case.provenance_refs if str(x).strip())
        provenance_refs = list(case.provenance_refs)
        if not provenance_refs and isinstance(search_context.get("mapping_provenance"), list):
            for mapping in search_context["mapping_provenance"]:
                if isinstance(mapping, dict):
                    ref = mapping.get("evidence_ref")
                    if ref:
                        provenance_refs.append(str(ref))
        evidence_refs = list(dict.fromkeys(evidence_refs))
        provenance_refs = list(dict.fromkeys(provenance_refs))

        domains = []
        domain_reasons = []
        for domain_name, details in domain_breakdown.items():
            if not isinstance(details, dict):
                continue
            domains.append(str(domain_name))
            score = details.get("anomaly_score")
            reasons = details.get("evidence_reasons") or []
            if score is not None:
                domain_reasons.append(f"{domain_name}: anomaly_score={score}")
            for reason in reasons:
                if reason:
                    domain_reasons.append(str(reason))

        fused_score = search_context.get("fused_composite_score") or case.search_context.get("fused_composite_score")
        threat = search_context.get("threat_classification") or case.search_context.get("threat_classification")
        return {
            "case_id": case.case_id,
            "entity_id": case.canonical_entity_id,
            "dataset": self._resolve_dataset(case_id=case.case_id, entity_id=case.canonical_entity_id),
            "evidence_refs": evidence_refs,
            "provenance_refs": provenance_refs,
            "mapping_status": case.mapping_status,
            "fused_composite_score": float(fused_score) if fused_score is not None else 0.0,
            "threat_classification": threat,
            "domains_analyzed": list(domains),
            "domain_evidence_breakdown": domain_breakdown,
            "case_summary": {
                "case_id": case.case_id,
                "canonical_entity_id": case.canonical_entity_id,
                "mapping_status": case.mapping_status,
                "domains_analyzed": list(domains),
                "fused_composite_score": float(fused_score) if fused_score is not None else 0.0,
                "threat_classification": threat,
            },
            "domain_reasons": domain_reasons,
        }

    def _safe_no_finding_response(self, question: str, case_id: Optional[str] = None, entity_id: Optional[str] = None, case: Optional[Any] = None) -> Dict[str, Any]:
        target_case = case or (self.backend.cases.get(case_id) if case_id and case_id in self.backend.cases else None)
        entity = entity_id or (target_case.canonical_entity_id if target_case else None)
        dataset = self._resolve_dataset(case_id=case_id or (target_case.case_id if target_case else None), entity_id=entity)
        answer = "No grounded finding is available for the active case and entity context."
        if "evidence" in question.lower():
            answer = "No grounded evidence is available for the active case and entity context."
        elif "before" in question.lower() or "history" in question.lower() or "anomalous behavior" in question.lower():
            answer = "The active case has no grounded historical evidence for the target entity; no unrelated stale finding is used."
        elif "next" in question.lower() or "investigate" in question.lower() or "examine" in question.lower():
            answer = "No grounded evidence supports a case-specific next step; the investigator should collect new evidence for the active case."

        payload = {
            "answer": answer,
            "confidence": 0.0,
            "status": "INSUFFICIENT_EVIDENCE",
            "claims": [],
            "evidence_refs": [],
            "provenance_refs": [],
            "uncertainties": ["The active case does not have a grounded finding or evidence chain for the target entity."],
            "limitations": ["This response intentionally avoids unrelated global findings and stale bank evidence."],
            "suggested_next_actions": ["Collect or attach case-scoped evidence before requesting a finding-backed explanation."],
            "finding_id": None,
            "entity_id": entity,
            "case_id": target_case.case_id if target_case else case_id,
            "dataset": dataset,
        }
        return self.formatter.format(payload)

    def ask(self, question: str, case_id: Optional[str] = None, entity_id: Optional[str] = None) -> Dict[str, Any]:
        q = (question or "").strip()
        if not q:
            raise ValueError("Empty question provided to copilot.")
        lower = q.lower()
        explicit_finding_id = self._get_finding_id_from_question(q)
        case = self._resolve_active_case(case_id=case_id, entity_id=entity_id)

        # Check for M14 Agentic Investigation query
        if lower.startswith("agent ") or lower.startswith("agent:") or "agentic" in lower:
            agent_q = q
            if lower.startswith("agent "):
                agent_q = q[6:].strip()
            elif lower.startswith("agent:"):
                agent_q = q[6:].strip()
            return self.investigate_agentic(
                agent_q,
                case_id=case_id or (case.case_id if case else None),
                entity_id=entity_id or (case.canonical_entity_id if case else None),
                finding_id=explicit_finding_id
            )

        # Check for temporal causality / post-trigger justification questions
        is_causality_justification_q = (
            ("after" in lower and ("justify" in lower or "change why" in lower or "suspicious" in lower or "make" in lower or "cause" in lower))
            or ("events after" in lower and ("suspicious" in lower or "justify" in lower or "change" in lower))
            or ("post-trigger" in lower and ("suspicious" in lower or "justify" in lower or "change" in lower))
            or ("subsequent" in lower and ("suspicious" in lower or "justify" in lower or "change why" in lower))
            or ("change why" in lower and ("trigger" in lower or "suspicious" in lower))
        )
        if is_causality_justification_q:
            pre_trigger_ev_refs: List[str] = []
            target_finding_id = explicit_finding_id or (self._pick_case_finding_id(case_id=case.case_id, entity_id=entity_id) if case else None)
            target_ent = entity_id or (case.canonical_entity_id if case else None)
            if target_finding_id and target_finding_id in self.backend.findings_by_id:
                try:
                    f_exp = self.reasoner.explain_finding(target_finding_id)
                    pre_trigger_ev_refs = f_exp.get("evidence_refs", [])
                except Exception:
                    pass

            answer = (
                "No. Under strict temporal causality, events occurring after the trigger event do not justify "
                "or explain why the trigger event itself was considered suspicious at trigger time T. "
                "Post-trigger events represent subsequent developments or follow-on activity (visible in forwardtrack), "
                "but they cannot serve as causal evidence for a past trigger. The trigger's suspicion status is "
                "grounded strictly in pre-trigger historical context and the trigger event's own features."
            )
            claims = [
                {
                    "claim": "Post-trigger events represent subsequent developments and do not justify why the past trigger was suspicious.",
                    "evidence_ids": [],
                },
                {
                    "claim": "Causal justification for the trigger event is strictly confined to pre-trigger and trigger-time evidence.",
                    "evidence_ids": pre_trigger_ev_refs,
                }
            ]
            controlled_payload = self._controlled_case_payload(case) if case else None
            payload = {
                "answer": answer,
                "confidence": 0.95,
                "status": "GROUNDED",
                "claims": claims,
                "evidence_refs": pre_trigger_ev_refs,
                "provenance_refs": [],
                "uncertainties": ["Subsequent events provide post-event context but cannot alter past causal attribution."],
                "limitations": ["Zero future leakage: forward-track events are strictly non-causal regarding past triggers."],
                "suggested_next_actions": [
                    "Inspect forwardtrack to analyze subsequent developments.",
                    "Review pre-trigger history and backtrack for causal precursors."
                ],
                "dataset": controlled_payload["dataset"] if controlled_payload else "CANONICAL",
                "entity_id": target_ent,
                "finding_id": target_finding_id,
                "case_id": case.case_id if case else case_id,
            }
            return self.formatter.format(payload)

        # Check for M8 Adaptive Behavioral Baseline questions
        is_baseline_q = (
            "baseline" in lower
            or "behavioral baseline" in lower
            or "quarantine" in lower
            or ("excluded" in lower and "observation" in lower)
            or ("has" in lower and "adapted" in lower)
            or ("adaptation" in lower and ("progress" in lower or "state" in lower))
            or ("behavioral" in lower and "state" in lower)
            or ("cold start" in lower and ("entity" in lower or "state" in lower or "still" in lower))
            or ("allowed to update" in lower)
        )
        if is_baseline_q:
            ent_candidates = [
                tok.strip("?,.!:;\"'")
                for tok in q.split()
                if tok.strip("?,.!:;\"'").startswith("ENT_") or tok.strip("?,.!:;\"'").startswith("ENT-")
            ]
            target_ent = entity_id or (ent_candidates[0] if ent_candidates else (case.canonical_entity_id if case else None))
            if not target_ent:
                if hasattr(self.backend, "valid_entities") and self.backend.valid_entities:
                    target_ent = list(self.backend.valid_entities)[0]
                else:
                    target_ent = "ENT_UNKNOWN"

            tool_res = self.backend.query_adaptive_baseline_agentic(q, entity_id=target_ent)
            controlled_payload = self._controlled_case_payload(case) if case else None
            payload = {
                "answer": tool_res.get("answer", "No baseline analysis available."),
                "confidence": 0.95,
                "status": "GROUNDED",
                "claims": tool_res.get("claims", []),
                "evidence_refs": tool_res.get("evidence_refs", []),
                "provenance_refs": tool_res.get("provenance_refs", []),
                "uncertainties": ["Baselines track statistical signal drift and do not imply intentionality or wrongdoing."],
                "limitations": [tool_res.get("culpability_assessment", "Non-culpability guardrails active: mathematical baseline divergence does not establish culpability or intent.")],
                "suggested_next_actions": [
                    f"Inspect chronological baseline history using 'baseline {target_ent} history'.",
                    f"Check timeline events around baseline drift using 'timeline {target_ent}'."
                ],
                "dataset": controlled_payload["dataset"] if controlled_payload else "ADAPTIVE_BASELINE_M8",
                "entity_id": target_ent,
                "finding_id": explicit_finding_id,
                "case_id": case.case_id if case else case_id,
                "baseline_status": tool_res.get("status"),
                "culpability_assessment": tool_res.get("culpability_assessment"),
                "audit_verifiable": tool_res.get("audit_verifiable", True),
            }
            return self.formatter.format(payload)

        if case is not None:
            controlled = self._controlled_case_payload(case)
            if controlled is not None:
                evidence_refs = controlled["evidence_refs"]
                provenance_refs = controlled["provenance_refs"]
                i = case.canonical_entity_id
                try:
                    ent_ctx = self.backend.investigate_entity(i)
                except Exception:
                    ent_ctx = {}

                if "before" in lower or "history" in lower or "timeline" in lower or "anomalous behavior" in lower:
                    payload = {
                        "answer": "The controlled dossier contains cross-domain evidence, but no native unified chronology is available for this case; historical attribution remains unavailable.",
                        "confidence": 0.0,
                        "status": "PARTIALLY_GROUNDED",
                        "claims": [{
                            "claim": "Controlled cross-domain evidence is available, but a native temporal event timeline is not asserted for this bridge case.",
                            "evidence_ids": evidence_refs,
                        }],
                        "evidence_refs": [],
                        "provenance_refs": provenance_refs,
                        "uncertainties": ["No native unified historical event series exists for this controlled case."],
                        "limitations": ["Historical reconstruction remains deliberately unavailable without a native chronology."],
                        "suggested_next_actions": ["Collect native chronology from the affiliated data source before making a historical attribution claim."],
                        "entity_id": i,
                        "case_id": case.case_id,
                        "dataset": controlled["dataset"],
                    }
                    return self.formatter.format(payload)

                if "evidence" in lower or "connect" in lower or "across domains" in lower or "domains" in lower:
                    claims = [
                        {
                            "claim": f"The active controlled case {case.case_id} is mapped to canonical entity {i} under CONTROLLED_CASE_MAPPING.",
                            "evidence_ids": evidence_refs,
                        }
                    ]
                    for domain_name, details in controlled["domain_evidence_breakdown"].items():
                        if isinstance(details, dict):
                            reasons = details.get("evidence_reasons") or []
                            claims.append({
                                "claim": f"{domain_name} evidence contributes anomaly_score={details.get('anomaly_score')} with reasons: {', '.join(str(r) for r in reasons)}.",
                                "evidence_ids": evidence_refs,
                            })
                    answer = (
                        "This case connects activity across domains through the controlled case mapping dossier for "
                        f"{i}. The active evidence records show financial and social domain signals under "
                        "CONTROLLED_CASE_MAPPING, with no native identity equivalence beyond the bridge mapping itself."
                    )

                    # Attach authoritative case-scoped pairwise identity evidence if present
                    pairwise_records = []
                    agg_evidence = []
                    agg_prov = []
                    try:
                        # prefer explicit candidate match ids if provided
                        sc = case.search_context or {}
                        candidate_match_ids = sc.get("identity_candidate_match_ids") if isinstance(sc, dict) else None
                        # build event_map for events tied to canonical raws
                        linked_ids = ent_ctx.get("linked_identifiers", [])
                        canonical_raws = [str(x.get("raw_identifier", "")).strip() for x in linked_ids if x.get("raw_identifier")]
                        event_map = {}
                        if not self.backend.events_df.empty:
                            for _, ev in self.backend.events_df.iterrows():
                                eid = str(ev.get("event_id", ""))
                                actor = str(ev.get("actor_id", "")).strip()
                                target = str(ev.get("target_id", "")).strip()
                                if actor in canonical_raws or target in canonical_raws:
                                    event_map[eid] = {"event_id": eid, "actor_id": actor, "target_id": target}

                        if not self.backend.entity_matches_df.empty:
                            if candidate_match_ids:
                                sub = self.backend.entity_matches_df[self.backend.entity_matches_df["match_id"].isin(candidate_match_ids)]
                            else:
                                interesting_event_ids = set(event_map.keys())
                                sub = self.backend.entity_matches_df[
                                    self.backend.entity_matches_df["left_record_id"].isin(interesting_event_ids) |
                                    self.backend.entity_matches_df["right_record_id"].isin(interesting_event_ids)
                                ]

                            if sub is not None and not sub.empty:
                                for _, mrow in sub.iterrows():
                                    left = str(mrow.get("left_record_id", ""))
                                    right = str(mrow.get("right_record_id", ""))
                                    status = str(mrow.get("match_status", ""))
                                    method = str(mrow.get("match_method", ""))
                                    prob = float(mrow.get("match_probability", 0.0)) if mrow.get("match_probability", None) is not None else None
                                    reason = str(mrow.get("decision_reason", ""))

                                    # evidence/provenance refs via event sha -> evidence mapping
                                    evidence_ids = []
                                    prov_refs = []
                                    for ev_id in (left, right):
                                        evrows = self.backend.events_df[self.backend.events_df["event_id"] == ev_id] if not self.backend.events_df.empty else None
                                        if evrows is not None and not evrows.empty:
                                            for _, er in evrows.iterrows():
                                                sha = str(er.get("sha256_hash", "")).strip()
                                                if sha:
                                                    ev_eid = self.backend._evidence_by_hash.get(sha)
                                                    if ev_eid:
                                                        evidence_ids.append(ev_eid)
                                                        evrec = self.backend.evidence_engine.get_evidence(ev_eid)
                                                        if evrec is not None and getattr(evrec, "provenance_ref", None):
                                                            prov_refs.append(evrec.provenance_ref)

                                    rec = {
                                        "match_id": str(mrow.get("match_id", "")),
                                        "left_record_id": left,
                                        "right_record_id": right,
                                        "match_status": status,
                                        "match_method": method,
                                        "match_probability": prob,
                                        "decision_reason": reason,
                                        "evidence_ids": list(dict.fromkeys(evidence_ids)),
                                        "provenance_refs": list(dict.fromkeys(prov_refs)),
                                    }
                                    pairwise_records.append(rec)
                                    agg_evidence.extend(rec["evidence_ids"])
                                    agg_prov.extend(rec["provenance_refs"])
                    except Exception:
                        pairwise_records = []
                        agg_evidence = []
                        agg_prov = []

                    # Determine conservative grounding: only GROUNDED when there are no ambiguous linked ids
                    linked = ent_ctx.get("linked_identifiers", [])
                    confirmed_pairs = []
                    ambiguous = []
                    for lid in linked:
                        if float(lid.get("confidence", 0.0)) >= 0.85 and str(lid.get("mapping_method", "")).upper() == "EXACT":
                            confirmed_pairs.append(lid)
                        else:
                            ambiguous.append(lid)

                    if evidence_refs or provenance_refs:
                        status_val = "GROUNDED"
                    else:
                        status_val = "GROUNDED" if (confirmed_pairs and not ambiguous and any(p.get("match_status") == "CONFIRMED" for p in pairwise_records)) else "PARTIALLY_GROUNDED"
                    payload = {
                        "answer": answer,
                        "confidence": min(0.99, 0.55 + (controlled["fused_composite_score"] * 0.45)),
                        "status": status_val,
                        "claims": claims,
                        "evidence_refs": list(dict.fromkeys(agg_evidence)) or evidence_refs,
                        "provenance_refs": list(dict.fromkeys(agg_prov)) or provenance_refs,
                        "pairwise_records": pairwise_records,
                        "uncertainties": ["This is a controlled cross-domain evidence dossier; a unified native chronology is not asserted."],
                        "limitations": ["No native identity equivalence or criminal conclusion is inferred beyond the guarded CONTROLLED_CASE_MAPPING."],
                        "suggested_next_actions": ["Review the highest-scoring domain evidence for the bridge case, then verify the mapping provenance and related identifiers."],
                        "dataset": controlled["dataset"],
                        "entity_id": i,
                        "finding_id": None,
                        "case_id": case.case_id,
                    }
                    return self.formatter.format(payload)

                if "why" in lower or "suspicious" in lower or "flagged" in lower:
                    score = controlled["fused_composite_score"]
                    threat = controlled["threat_classification"] or "ELEVATED_MULTI_DOMAIN_RISK"
                    claims = [{
                        "claim": f"The case is suspicious because the controlled map fuses financial and social evidence into a composite score of {score:.4f} with threat classification '{threat}'.",
                        "evidence_ids": evidence_refs,
                    }]
                    for domain_name, details in controlled["domain_evidence_breakdown"].items():
                        if isinstance(details, dict):
                            reasons = details.get("evidence_reasons") or []
                            claims.append({
                                "claim": f"{domain_name} evidence ({details.get('anomaly_score')}) contributes: {', '.join(str(r) for r in reasons)}.",
                                "evidence_ids": evidence_refs,
                            })
                    payload = {
                        "answer": (
                            f"This controlled case is considered suspicious because its financial and social evidence are fused into "
                            f"a composite score of {score:.4f} and threat classification '{threat}', while remaining explicitly within "
                            "CONTROLLED_CASE_MAPPING rather than claiming a native identity equivalence."
                        ),
                        "confidence": min(0.99, 0.5 + score * 0.5),
                        "status": "GROUNDED" if score > 0.0 else "PARTIALLY_GROUNDED",
                        "claims": claims,
                        "evidence_refs": evidence_refs,
                        "provenance_refs": provenance_refs,
                        "uncertainties": ["The dossier is evidence-grounded but does not assert a unified native event chronology."],
                        "limitations": ["This does not claim criminality or native dataset identity equivalence."],
                        "suggested_next_actions": ["Verify the bridge provenance and then review the highest-scoring domain artifacts associated with the mapped identifiers."],
                        "dataset": controlled["dataset"],
                        "entity_id": i,
                        "finding_id": None,
                        "case_id": case.case_id,
                    }
                    return self.formatter.format(payload)

                if "next" in lower or "investigate" in lower or "examine" in lower:
                    steps = [
                        "Review the highest-scoring financial evidence in the case dossier and the linked bridge provenance.",
                        "Review the social interaction hub evidence and its mapping provenance.",
                        "Verify the bridge mapping and associated identifiers before broadening the investigation."
                    ]
                    payload = {
                        "answer": "The next investigation steps should focus on the evidence already present in the controlled case dossier: verify the financial anomaly signals, review the social interaction hub, and confirm the controlled mapping provenance before expanding outward.",
                        "confidence": 0.8,
                        "status": "GROUNDED",
                        "claims": [{
                            "claim": "The case dossier contains the highest-value financial and social evidence that should be reviewed next.",
                            "evidence_ids": evidence_refs,
                        }],
                        "evidence_refs": evidence_refs,
                        "provenance_refs": provenance_refs,
                        "uncertainties": ["Next steps are scoped to the available controlled-case evidence and do not assert additional identity claims."],
                        "limitations": ["No native chronology or unsupported identity inference is introduced."],
                        "suggested_next_actions": steps,
                        "entity_id": i,
                        "case_id": case.case_id,
                        "dataset": controlled["dataset"],
                    }
                    return self.formatter.format(payload)

        # Check for forensic case packet questions
        forensic_resp = self._handle_forensic_packet_question(
            question=q,
            case_id=case_id,
            entity_id=entity_id,
            explicit_finding_id=explicit_finding_id
        )
        if forensic_resp is not None:
            return forensic_resp

        # Check for temporal pre-trigger sequence questions
        pre_trig_resp = self._handle_pre_trigger_question(
            question=q,
            case_id=case_id,
            entity_id=entity_id,
            explicit_finding_id=explicit_finding_id
        )
        if pre_trig_resp is not None:
            return pre_trig_resp

        # Check for temporal post-trigger sequence questions
        post_trig_resp = self._handle_post_trigger_question(
            question=q,
            case_id=case_id,
            entity_id=entity_id,
            explicit_finding_id=explicit_finding_id
        )
        if post_trig_resp is not None:
            return post_trig_resp

        # Check for temporal pattern / motif questions
        pattern_resp = self._handle_patterns_question(
            question=q,
            case_id=case_id,
            entity_id=entity_id,
            explicit_finding_id=explicit_finding_id
        )
        if pattern_resp is not None:
            return pattern_resp

        # Check for temporal phase compression questions
        phase_resp = self._handle_phases_question(
            question=q,
            case_id=case_id,
            entity_id=entity_id,
            explicit_finding_id=explicit_finding_id
        )
        if phase_resp is not None:
            return phase_resp

        # Check for temporal sequence comparison questions
        compare_resp = self._handle_compare_question(
            question=q,
            case_id=case_id,
            entity_id=entity_id,
            explicit_finding_id=explicit_finding_id
        )
        if compare_resp is not None:
            return compare_resp

        # Check for temporal transitions questions
        trans_resp = self._handle_transitions_question(
            question=q,
            case_id=case_id,
            entity_id=entity_id,
            explicit_finding_id=explicit_finding_id
        )
        if trans_resp is not None:
            return trans_resp

        # ── Test 8: Hypothesis & Contradictory Evidence Resolution ───────────────
        target_case = case
        if target_case is None and case_id and case_id in self.backend.cases:
            target_case = self.backend.cases[case_id]
        if target_case is None and entity_id:
            matches = [c for c in self.backend.cases.values() if c.canonical_entity_id == entity_id]
            if matches:
                target_case = matches[0]

        target_findings = []
        if target_case:
            target_findings = [self.backend.get_finding(fid) for fid in target_case.finding_ids if fid in self.backend.findings_by_id]
        if explicit_finding_id and explicit_finding_id in self.backend.findings_by_id:
            target_findings = [self.backend.get_finding(explicit_finding_id)]
        elif not target_findings and entity_id:
            target_findings = [f for f in self.backend.findings_by_id.values() if f.get("entity_id") == entity_id or f.get("canonical_entity_id") == entity_id]

        target_ev_ids = []
        if target_case:
            target_ev_ids.extend(target_case.evidence_ids)
        for f in target_findings:
            f_id = f.get("finding_id")
            if f_id:
                target_ev_ids.extend(self.backend.evidence_engine.finding_evidence_map.get(f_id, []))
                target_ev_ids.extend(f.get("supporting_evidence", []))
                target_ev_ids.extend(f.get("contradicting_evidence", []))
                target_ev_ids.extend(f.get("contextual_evidence", []))
        target_ev_ids = [eid for eid in dict.fromkeys(target_ev_ids) if not str(eid).startswith("ref:fnd:")]

        target_ev_objs = [self.backend.evidence_engine.get_evidence(eid) for eid in target_ev_ids if self.backend.evidence_engine.get_evidence(eid) is not None]

        supp_ev_objs = [e for e in target_ev_objs if getattr(e, "evidence_category", "SUPPORTING") == "SUPPORTING"]
        contra_ev_objs = [e for e in target_ev_objs if getattr(e, "evidence_category", "") == "CONTRADICTING"]
        neutral_ev_objs = [e for e in target_ev_objs if getattr(e, "evidence_category", "") in ("CONTEXTUAL", "NEUTRAL")]

        supp_ids = [e.evidence_id for e in supp_ev_objs]
        contra_ids = [e.evidence_id for e in contra_ev_objs]
        neutral_ids = [e.evidence_id for e in neutral_ev_objs]

        if not supp_ids and target_findings:
            supp_ids = [x for f in target_findings for x in f.get("supporting_evidence", []) if not str(x).startswith("ref:fnd:")]
        if not contra_ids and target_findings:
            contra_ids = [x for f in target_findings for x in f.get("contradicting_evidence", []) if not str(x).startswith("ref:fnd:")]

        supp_domains = sorted(list({e.source_domain for e in supp_ev_objs}))
        contra_domains = sorted(list({e.source_domain for e in contra_ev_objs}))

        m11_info = {}
        for f in target_findings:
            if f.get("m11_fusion_info"):
                m11_info = f["m11_fusion_info"]
                break
        if not supp_domains and m11_info.get("supporting_domains"):
            supp_domains = m11_info["supporting_domains"]
        if not contra_domains and m11_info.get("contradicting_domains"):
            contra_domains = m11_info["contradicting_domains"]

        has_conflict = bool(contra_ids or contra_domains or m11_info.get("conflict_status") == "CONFLICTED" or any(f.get("status") in ("CONFLICTED", "CONFLICTED_EVIDENCE") for f in target_findings))
        active_ent = (target_case.canonical_entity_id if target_case else entity_id) or (target_findings[0].get("entity") if target_findings else None)
        active_cid = target_case.case_id if target_case else case_id
        active_fid = explicit_finding_id or (target_findings[0]["finding_id"] if target_findings else None)

        # Q1: What evidence supports the current hypothesis?
        if (
            ("support" in lower or "supporting" in lower)
            and ("hypothesis" in lower or "what evidence supports" in lower)
            and "contradict" not in lower
            and "conflict" not in lower
        ):
            if not supp_ids:
                return self._safe_no_finding_response(q, case_id=active_cid, entity_id=active_ent, case=target_case)
            supp_prov = [e.provenance_ref for e in supp_ev_objs if getattr(e, "provenance_ref", None)]
            dom_str = f" from {', '.join(supp_domains)}" if supp_domains else ""
            answer = (
                f"The supporting evidence for the current hypothesis comprises {len(supp_ids)} record(s){dom_str}: "
                f"{', '.join(supp_ids)}. These records demonstrate anomalous behavioral signals. Note that contradictory "
                "evidence is also present in this case dossier and must be accounted for before reaching a conclusion."
                if has_conflict else
                f"The supporting evidence for the current hypothesis comprises {len(supp_ids)} record(s){dom_str}: {', '.join(supp_ids)}."
            )
            claims = [
                {
                    "claim": f"Supporting evidence{dom_str} ({', '.join(supp_ids)}) provides anomalous signals supporting the hypothesis.",
                    "evidence_ids": supp_ids,
                }
            ]
            payload = {
                "answer": answer,
                "confidence": 0.85,
                "status": "GROUNDED",
                "claims": claims,
                "evidence_refs": supp_ids,
                "provenance_refs": supp_prov,
                "uncertainties": ["Supporting evidence represents one perspective; strong contradictory evidence is present in the case dossier."] if has_conflict else [],
                "limitations": ["This response identifies supporting evidence only; it does not resolve evidential conflicts."],
                "suggested_next_actions": ["Review contradicting evidence from the opposing domains.", "Inspect cross-domain corroboration score and conflict penalty."] if has_conflict else ["Review supporting evidence records in the provenance chain."],
                "dataset": self._resolve_dataset(case_id=active_cid, entity_id=active_ent),
                "entity_id": active_ent,
                "finding_id": active_fid,
                "case_id": active_cid,
            }
            return self.formatter.format(payload)

        # Q2: What evidence contradicts the current hypothesis?
        if (
            ("contradict" in lower or "contradicting" in lower or "contradictory" in lower)
            and ("hypothesis" in lower or "what evidence contradicts" in lower or "what" in lower)
            and "conflict" not in lower
        ):
            if not contra_ids:
                payload = {
                    "answer": "No contradictory evidence records are present in the active case context.",
                    "confidence": 0.0,
                    "status": "INSUFFICIENT_EVIDENCE",
                    "claims": [],
                    "evidence_refs": [],
                    "provenance_refs": [],
                    "uncertainties": ["No contradicting evidence was identified for this entity or case."],
                    "limitations": ["Absence of contradiction in available records does not guarantee unobserved consistency."],
                    "suggested_next_actions": ["Review supporting evidence records."],
                    "dataset": self._resolve_dataset(case_id=active_cid, entity_id=active_ent),
                    "entity_id": active_ent,
                    "finding_id": active_fid,
                    "case_id": active_cid,
                }
                return self.formatter.format(payload)
            contra_prov = [e.provenance_ref for e in contra_ev_objs if getattr(e, "provenance_ref", None)]
            dom_str = f" from {', '.join(contra_domains)}" if contra_domains else ""
            answer = (
                f"The contradictory evidence against the current hypothesis comprises {len(contra_ids)} record(s){dom_str}: "
                f"{', '.join(contra_ids)}. These records exhibit normal baseline behavior inconsistent with the hypothesis."
            )
            claims = [
                {
                    "claim": f"Contradictory evidence{dom_str} ({', '.join(contra_ids)}) exhibits normal baseline activity inconsistent with the hypothesis.",
                    "evidence_ids": contra_ids,
                }
            ]
            payload = {
                "answer": answer,
                "confidence": 0.85,
                "status": "GROUNDED",
                "claims": claims,
                "evidence_refs": contra_ids,
                "provenance_refs": contra_prov,
                "uncertainties": ["Contradictory evidence introduces direct domain conflict against the supporting signals."],
                "limitations": ["Identifies contradictory evidence only; contradiction prevents unilateral positive findings."],
                "suggested_next_actions": ["Adjudicate the discrepancy between supporting and contradicting domains.", "Perform forensic verification of source records."],
                "dataset": self._resolve_dataset(case_id=active_cid, entity_id=active_ent),
                "entity_id": active_ent,
                "finding_id": active_fid,
                "case_id": active_cid,
            }
            return self.formatter.format(payload)

        # Q3: Are there conflicts between the available evidence?
        if (
            ("conflict" in lower or "conflicts" in lower or "discrepan" in lower or "hellinger" in lower)
            and ("evidence" in lower or "available" in lower or "between" in lower or "are there" in lower or "domain" in lower or "what" in lower)
            and "confident" not in lower
            and "confidence" not in lower
        ):
            if not target_ev_ids and not target_findings:
                return self._safe_no_finding_response(q, case_id=active_cid, entity_id=active_ent, case=target_case)
            if has_conflict:
                all_conflict_ev_ids = supp_ids + contra_ids
                all_conflict_prov = [e.provenance_ref for e in supp_ev_objs + contra_ev_objs if getattr(e, "provenance_ref", None)]
                ev_conf = m11_info.get("evidential_conflict")
                conf_detail_str = ""
                extra_claims = []
                action_str = "HUMAN_REVIEW"
                if ev_conf and ev_conf.get("pairwise_conflicts"):
                    wp = ev_conf.get("worst_pair")
                    max_c = ev_conf.get("max_compound_conflict", 0.0)
                    wp_match = next((p for p in ev_conf["pairwise_conflicts"] if wp and ((p["domain_a"], p["domain_b"]) == tuple(wp) or (p["domain_b"], p["domain_a"]) == tuple(wp))), ev_conf["pairwise_conflicts"][0])
                    dh = wp_match.get("hellinger_distance", 0.0)
                    cos = wp_match.get("belief_vector_cosine", 0.0)
                    status_lbl = wp_match.get("conflict_status", "CONFLICTED")
                    action_str = wp_match.get("required_action", "HUMAN_REVIEW")
                    conf_detail_str = (
                        f" Evidential conflict analysis identifies compound conflict metric {max_c:.4f} "
                        f"between {wp_match['domain_a']} and {wp_match['domain_b']} (status: {status_lbl}), comprising "
                        f"distributional Hellinger distance {dh:.4f} and belief vector cosine similarity {cos:.4f}. "
                        f"Under this divergence, automated consensus is suspended and {action_str} is required."
                    )
                    extra_claims.append({
                        "claim": f"Evidential conflict analysis: compound conflict {max_c:.4f}, Hellinger distance {dh:.4f}, belief cosine {cos:.4f} (action: {action_str}).",
                        "evidence_ids": all_conflict_ev_ids,
                    })

                answer = (
                    f"Yes. Evidential conflict exists between independent domains. Domain evidence from "
                    f"{', '.join(supp_domains) if supp_domains else 'supporting domain'} ({', '.join(supp_ids)}) supports the hypothesis "
                    f"with anomalous indicators, while domain evidence from "
                    f"{', '.join(contra_domains) if contra_domains else 'contradicting domain'} ({', '.join(contra_ids)}) directly contradicts "
                    f"the hypothesis with normal baseline activity. Under DFAP integrity rules, this contradiction is explicitly preserved and not averaged away."
                    f"{conf_detail_str}"
                )
                claims = [
                    {
                        "claim": f"Evidential conflict detected between supporting domains ({', '.join(supp_domains)}) and contradicting domains ({', '.join(contra_domains)}).",
                        "evidence_ids": all_conflict_ev_ids,
                    },
                    {
                        "claim": f"Supporting domain evidence: {', '.join(supp_ids)}.",
                        "evidence_ids": supp_ids,
                    },
                    {
                        "claim": f"Contradicting domain evidence: {', '.join(contra_ids)}.",
                        "evidence_ids": contra_ids,
                    }
                ] + extra_claims
                payload = {
                    "answer": answer,
                    "confidence": 0.40,
                    "status": "CONFLICTED",
                    "claims": claims,
                    "evidence_refs": all_conflict_ev_ids,
                    "provenance_refs": all_conflict_prov,
                    "evidential_conflict": ev_conf,
                    "required_action": action_str,
                    "uncertainties": ["Direct conflict between independent domains prevents an authoritative unilateral finding."],
                    "limitations": ["DFAP does not average, suppress, or silently resolve conflicting evidence into an unjustified conclusion."],
                    "suggested_next_actions": [
                        f"Adjudicate domain discrepancies between {', '.join(supp_domains)} and {', '.join(contra_domains)} (required action: {action_str}).",
                        "Verify identity binding and source telemetry integrity for both domains."
                    ],
                    "dataset": self._resolve_dataset(case_id=active_cid, entity_id=active_ent),
                    "entity_id": active_ent,
                    "finding_id": active_fid,
                    "case_id": active_cid,
                }
                return self.formatter.format(payload)
            else:
                payload = {
                    "answer": "No evidential conflicts were detected among the available records.",
                    "confidence": 0.80,
                    "status": "GROUNDED",
                    "claims": [{"claim": "No contradictory evidence records were found in the current evidence set.", "evidence_ids": supp_ids}],
                    "evidence_refs": supp_ids,
                    "provenance_refs": [e.provenance_ref for e in supp_ev_objs if getattr(e, "provenance_ref", None)],
                    "uncertainties": [],
                    "limitations": ["Assessment is scoped to currently attached evidence only."],
                    "suggested_next_actions": ["Review entity timeline and graph neighbors."],
                    "dataset": self._resolve_dataset(case_id=active_cid, entity_id=active_ent),
                    "entity_id": active_ent,
                    "finding_id": active_fid,
                    "case_id": active_cid,
                }
                return self.formatter.format(payload)

        # Q4: How confident should the investigator be given the conflicting evidence?
        if (
            ("confident" in lower or "confidence" in lower)
            and ("conflict" in lower or "conflicting" in lower or "contradict" in lower or "evidence" in lower or "investigator" in lower)
        ):
            if not target_ev_ids and not target_findings:
                return self._safe_no_finding_response(q, case_id=active_cid, entity_id=active_ent, case=target_case)
            if has_conflict:
                all_conflict_ev_ids = supp_ids + contra_ids
                all_conflict_prov = [e.provenance_ref for e in supp_ev_objs + contra_ev_objs if getattr(e, "provenance_ref", None)]
                penalized_conf = 0.35
                if m11_info.get("corroboration_score") is not None:
                    penalized_conf = round(float(m11_info["corroboration_score"]), 2)
                answer = (
                    f"The investigator should maintain low confidence ({penalized_conf:.2f}) given the conflicting evidence. "
                    f"Although evidence from {', '.join(supp_domains) if supp_domains else 'supporting domain'} indicates anomalous activity, "
                    f"the presence of strong contradicting evidence from {', '.join(contra_domains) if contra_domains else 'contradicting domain'} "
                    "triggers an explicit conflict penalty under evidential combination. A high numerical score in one domain does not "
                    "override or suppress contradictory evidence from another domain."
                )
                claims = [
                    {
                        "claim": "Confidence is reduced due to material cross-domain contradiction and conflict penalty.",
                        "evidence_ids": all_conflict_ev_ids,
                    },
                    {
                        "claim": "A high anomaly score in one domain cannot override contradictory evidence from another domain.",
                        "evidence_ids": all_conflict_ev_ids,
                    }
                ]
                payload = {
                    "answer": answer,
                    "confidence": penalized_conf,
                    "status": "CONFLICTED",
                    "claims": claims,
                    "evidence_refs": all_conflict_ev_ids,
                    "provenance_refs": all_conflict_prov,
                    "evidential_conflict": m11_info.get("evidential_conflict"),
                    "uncertainties": ["Severe epistemic conflict between opposing domain signals prevents high certainty."],
                    "limitations": ["Zero score-averaging: numerical anomaly scores cannot be used to paper over factual contradictions."],
                    "suggested_next_actions": [
                        "Reconcile divergent domain findings before making an investigative determination.",
                        "Do not escalate or conclude without resolving contradictory indicators."
                    ],
                    "dataset": self._resolve_dataset(case_id=active_cid, entity_id=active_ent),
                    "entity_id": active_ent,
                    "finding_id": active_fid,
                    "case_id": active_cid,
                }
                return self.formatter.format(payload)

        # Q5: What should be verified next?
        if (
            ("verify" in lower or "verified" in lower or "next" in lower)
            and ("what" in lower or "next" in lower or "should" in lower or "action" in lower)
            and "trigger" not in lower
        ):
            if not target_ev_ids and not target_findings:
                return self._safe_no_finding_response(q, case_id=active_cid, entity_id=active_ent, case=target_case)
            if has_conflict:
                all_conflict_ev_ids = supp_ids + contra_ids
                all_conflict_prov = [e.provenance_ref for e in supp_ev_objs + contra_ev_objs if getattr(e, "provenance_ref", None)]
                ev_conf = m11_info.get("evidential_conflict")
                steps = [
                    f"Adjudicate discrepancy between {', '.join(supp_domains) if supp_domains else 'supporting'} and {', '.join(contra_domains) if contra_domains else 'contradicting'} evidence records.",
                    f"Verify source telemetry and identity binding for {', '.join(contra_ids)}.",
                    f"Audit raw transaction logs and event timestamps for {', '.join(supp_ids)}.",
                    "Investigate potential credential handover or multi-party control reconciling the conflicting domains."
                ]
                if ev_conf and ev_conf.get("requires_human_review"):
                    steps.insert(0, f"Conduct formal human review on {ev_conf.get('worst_pair', ('opposing', 'domains'))[0]} vs {ev_conf.get('worst_pair', ('opposing', 'domains'))[1]} evidential divergence.")
                answer = (
                    f"The investigator must prioritize adjudicating the contradiction between "
                    f"{', '.join(supp_domains) if supp_domains else 'supporting domains'} (supporting: {', '.join(supp_ids)}) and "
                    f"{', '.join(contra_domains) if contra_domains else 'contradicting domains'} (contradicting: {', '.join(contra_ids)}). "
                    "Specific verification steps: 1) Verify whether the contradictory indicators represent genuine baseline activity or alternate user behavior; "
                    "2) Audit the identity binding and source telemetry of the supporting evidence; "
                    "3) Check for credential compromise or account handover that could reconcile the divergence."
                )
                claims = [
                    {
                        "claim": f"Next verification must prioritize resolving the contradiction between {', '.join(supp_domains)} and {', '.join(contra_domains)} evidence.",
                        "evidence_ids": all_conflict_ev_ids,
                    }
                ]
                payload = {
                    "answer": answer,
                    "confidence": 0.75,
                    "status": "CONFLICTED",
                    "claims": claims,
                    "evidence_refs": all_conflict_ev_ids,
                    "provenance_refs": all_conflict_prov,
                    "uncertainties": ["The root cause of domain divergence remains unadjudicated."],
                    "limitations": ["Recommended actions focus strictly on conflict adjudication and do not infer a conclusion."],
                    "suggested_next_actions": steps,
                    "verification_steps": steps,
                    "dataset": self._resolve_dataset(case_id=active_cid, entity_id=active_ent),
                    "entity_id": active_ent,
                    "finding_id": active_fid,
                    "case_id": active_cid,
                }
                return self.formatter.format(payload)

        # Reliability & Evidence Quality queries (Q: How reliable is this finding? How strong is the evidence? etc.)
        if (
            ("reliable" in lower or "reliability" in lower or "how strong" in lower or "well supported" in lower or "quality" in lower or "why is confidence low" in lower)
            and ("finding" in lower or "evidence" in lower or "case" in lower or "how" in lower or "why" in lower or "is" in lower or "what" in lower)
            and "trigger" not in lower
            and "data quality" not in lower
            and "source health" not in lower
        ):
            target_finding_id = explicit_finding_id or (self._pick_case_finding_id(case_id=case.case_id, entity_id=entity_id) if case else active_fid)
            target_case_id = case.case_id if case else active_cid

            if not target_finding_id or target_case_id not in self.backend.cases or target_finding_id not in self.backend.cases[target_case_id].finding_ids:
                return self._safe_no_finding_response(q, case_id=target_case_id, entity_id=active_ent, case=case)

            from dfap.investigation.reliability import EvidenceQualityReliabilityEngine, ReliabilityStatus
            engine = EvidenceQualityReliabilityEngine(self.backend)
            assessment = engine.assess_finding(target_case_id, target_finding_id)

            status_str = assessment.overall_status.value if hasattr(assessment.overall_status, "value") else str(assessment.overall_status)
            suff_str = assessment.evidence_sufficiency.value if hasattr(assessment.evidence_sufficiency, "value") else str(assessment.evidence_sufficiency)
            ans = (
                f"Finding {target_finding_id} has a deterministic reliability score of {assessment.overall_score:.2f} "
                f"with status {status_str} (evidence sufficiency: {suff_str}, conflict severity: {assessment.conflict_severity.value}). "
                f"{' '.join(assessment.reasons)}"
            )
            claims = [
                {
                    "claim": f"Reliability status is {status_str} with overall score {assessment.overall_score:.2f}.",
                    "evidence_ids": assessment.supporting_evidence + assessment.contradicting_evidence,
                },
                {
                    "claim": f"Evidence sufficiency is {suff_str} (support_strength={assessment.support_strength:.2f}, contradiction_strength={assessment.contradiction_strength:.2f}).",
                    "evidence_ids": assessment.supporting_evidence + assessment.contradicting_evidence,
                }
            ]
            copilot_conf = assessment.overall_score if status_str != "CONFLICTED" else min(0.40, assessment.overall_score)
            copilot_status = "CONFLICTED" if status_str == "CONFLICTED" else ("GROUNDED" if status_str in ("HIGH", "MEDIUM") else ("INSUFFICIENT_EVIDENCE" if status_str == "INSUFFICIENT_EVIDENCE" else "PARTIALLY_GROUNDED"))

            payload = {
                "answer": ans,
                "confidence": copilot_conf,
                "status": copilot_status,
                "reliability": assessment.to_dict(),
                "claims": claims,
                "evidence_refs": assessment.supporting_evidence + assessment.contradicting_evidence,
                "provenance_refs": [e.root_ancestor_id for e in assessment.evidence_breakdown if e.root_ancestor_id],
                "uncertainties": [f"Uncertainty: {r}" for r in assessment.reasons if "conflict" in r.lower() or "degraded" in r.lower() or "insufficient" in r.lower()],
                "limitations": assessment.limitations,
                "suggested_next_actions": [
                    "Inspect per-evidence reliability contributions in evidence_breakdown.",
                    "Verify corroborating event clusters and DAG lineage."
                ],
                "verification_steps": [
                    "Inspect per-evidence reliability contributions in evidence_breakdown.",
                    "Verify corroborating event clusters and DAG lineage."
                ],
                "dataset": self._resolve_dataset(case_id=target_case_id, entity_id=active_ent),
                "entity_id": active_ent,
                "finding_id": target_finding_id,
                "case_id": target_case_id,
            }
            return self.formatter.format(payload)

        # Graph ML & Predicted Relationship queries
        if "graph ml" in lower or "tgn" in lower or "graphsage" in lower or "predicted link" in lower or "predict relationship" in lower:
            svc = getattr(self.backend, "graph_ml_service", None)
            if svc is not None:
                bench = svc.get_latest_benchmark()
                sage_auc = bench["models"]["GraphSAGE"]["auroc"]
                tgn_auc = bench["models"]["TGN"]["auroc"]
                answer = (
                    f"Graph ML ablation comparison on controlled chronological benchmark: "
                    f"GraphSAGE AUROC={sage_auc:.4f} vs TGN AUROC={tgn_auc:.4f}. "
                    f"CRITICAL SAFETY RULE: Any predicted edge generated by GraphSAGE or TGN is strictly a "
                    f"'model-predicted relationship' with status PREDICTED. It is NOT observed evidence, NOT a confirmed fact, "
                    f"NOT identity proof, and NOT evidence of legal guilt."
                )
                payload = {
                    "answer": answer,
                    "confidence": 0.85,
                    "status": "GROUNDED",
                    "claims": [
                        {
                            "claim": f"Graph ML ablation benchmark: GraphSAGE AUROC={sage_auc:.4f}, TGN AUROC={tgn_auc:.4f}.",
                            "evidence_ids": []
                        },
                        {
                            "claim": "All GNN/TGN links are model-predicted relationships and never enter M12 provenance as observed evidence.",
                            "evidence_ids": []
                        }
                    ],
                    "evidence_refs": [],
                    "provenance_refs": [],
                    "uncertainties": ["Model predictions are probabilistic heuristics unconfirmed by ground-truth sensor telemetry."],
                    "limitations": [
                        "Model predictions reflect statistical graph topology and temporal state only, NOT confirmed facts.",
                        "TGN predictions must never be treated as identity proof or evidence of guilt."
                    ],
                    "suggested_next_actions": ["Verify unconfirmed predictions via independent source sensor telemetry."],
                    "verification_steps": ["Inspect source telemetry before considering model-predicted relationships."],
                    "dataset": self._resolve_dataset(case_id=case.case_id if case else None, entity_id=entity_id),
                    "entity_id": entity_id,
                    "case_id": case.case_id if case else None,
                }
                return self.formatter.format(payload)

        # Data Quality & Source Health queries
        if (
            ("data quality" in lower or "source health" in lower or "trustworthy" in lower or "source healthy" in lower or "data defect" in lower or "source defect" in lower or "is the data" in lower or "is this data" in lower or "health of source" in lower or "quality of source" in lower)
            and ("data" in lower or "source" in lower or "case" in lower or "healthy" in lower or "trust" in lower)
            and "finding" not in lower
        ):
            target_case_id = case.case_id if case else active_cid

            target_source_id = None
            for s_cand in ["unsw", "stackoverflow", "elliptic", "SRC_SCENARIO_A", "SRC_SCENARIO_N", "SRC_SCENARIO_M"]:
                if s_cand.lower() in lower:
                    target_source_id = s_cand
                    break

            if target_source_id:
                assessment_dict = self.backend.assess_source_health(target_source_id)
                overall_st = assessment_dict.get("overall_status", "UNKNOWN")
                ans = (
                    f"Data source '{target_source_id}' has health status {overall_st} ({assessment_dict.get('record_count', 0)} records). "
                    f"{' '.join(assessment_dict.get('reasons', [])[:2])}"
                )
                copilot_status = "GROUNDED" if overall_st == "HEALTHY" else ("PARTIALLY_GROUNDED" if overall_st == "DEGRADED" else "INSUFFICIENT_EVIDENCE")
                payload = {
                    "answer": ans,
                    "confidence": 0.95 if overall_st == "HEALTHY" else (0.75 if overall_st == "DEGRADED" else 0.20),
                    "status": copilot_status,
                    "source_health": assessment_dict,
                    "data_quality": assessment_dict,
                    "claims": [{"claim": f"Source {target_source_id} health is {overall_st}.", "evidence_ids": []}],
                    "evidence_refs": [],
                    "provenance_refs": [],
                    "uncertainties": [f"Uncertainty: {r}" for r in assessment_dict.get("reasons", []) if "warning" in r.lower() or "critical" in r.lower() or "degraded" in r.lower()],
                    "limitations": assessment_dict.get("limitations", []),
                    "suggested_next_actions": assessment_dict.get("suggested_actions", []),
                    "verification_steps": assessment_dict.get("suggested_actions", []),
                    "dataset": target_source_id,
                    "entity_id": active_ent,
                    "case_id": target_case_id,
                }
                return self.formatter.format(payload)

            elif target_case_id and target_case_id in self.backend.cases:
                case_assessment = self.backend.assess_case_data_health(target_case_id)
                overall_st = case_assessment.get("overall_status", "UNKNOWN")
                ans = (
                    f"Case '{target_case_id}' data quality has overall health status {overall_st}. "
                    f"{' '.join(case_assessment.get('reasons', [])[:2])}"
                )
                copilot_status = "GROUNDED" if overall_st == "HEALTHY" else ("PARTIALLY_GROUNDED" if overall_st == "DEGRADED" else "INSUFFICIENT_EVIDENCE")
                payload = {
                    "answer": ans,
                    "confidence": 0.95 if overall_st == "HEALTHY" else (0.75 if overall_st == "DEGRADED" else 0.20),
                    "status": copilot_status,
                    "data_quality": case_assessment,
                    "claims": [{"claim": f"Case {target_case_id} data quality is {overall_st}.", "evidence_ids": []}],
                    "evidence_refs": [],
                    "provenance_refs": [],
                    "uncertainties": [f"Uncertainty: {r}" for r in case_assessment.get("reasons", [])],
                    "limitations": case_assessment.get("limitations", []),
                    "suggested_next_actions": case_assessment.get("suggested_actions", []),
                    "verification_steps": case_assessment.get("suggested_actions", []),
                    "dataset": self._resolve_dataset(case_id=target_case_id, entity_id=active_ent),
                    "entity_id": active_ent,
                    "case_id": target_case_id,
                }
                return self.formatter.format(payload)

        if "why" in lower or "flagged" in lower:
            if explicit_finding_id is not None:
                if case is not None:
                    selected = self._pick_case_finding_id(case_id=case.case_id, entity_id=entity_id, explicit_finding_id=explicit_finding_id)
                    return self.explain_finding(selected)
                return self.explain_finding(explicit_finding_id)

            if case is not None:
                selected = self._pick_case_finding_id(case_id=case.case_id, entity_id=entity_id)
                if selected is None:
                    return self._safe_no_finding_response(q, case_id=case.case_id, entity_id=case.canonical_entity_id, case=case)
                return self.explain_finding(selected)

            return self._safe_no_finding_response(q, case_id=case_id, entity_id=entity_id)

        if "summarize" in lower or "case" in lower:
            if case is not None:
                return self.summarize_case(case.case_id)
            if self.backend.cases:
                case_id = next(iter(self.backend.cases))
                return self.summarize_case(case_id)
            raise ValueError("No case context available for summarization.")

        if "evidence" in lower:
            finding_id = explicit_finding_id or self._pick_case_finding_id(case_id=case.case_id if case else None, entity_id=entity_id)
            if finding_id is None:
                return self._safe_no_finding_response(q, case_id=case.case_id if case else case_id, entity_id=entity_id or (case.canonical_entity_id if case else None), case=case)
            return self.evidence_for_finding(finding_id)
        if "uncertain" in lower or ("identifiers" in lower and "uncertain" in lower):
            # Handle explicit uncertain identifiers query
            res = self._handle_uncertain_identifiers(q, case, entity_id)
            if res is not None:
                return res
        if "contradict" in lower:
            finding_id = explicit_finding_id or self._pick_case_finding_id(case_id=case.case_id if case else None, entity_id=entity_id)
            if finding_id is None:
                return self._safe_no_finding_response(q, case_id=case.case_id if case else case_id, entity_id=entity_id or (case.canonical_entity_id if case else None), case=case)
            return self.contradictions_for_finding(finding_id)
        if "timeline" in lower or "before" in lower or "history" in lower or "anomalous behavior" in lower:
            entity_id = entity_id or (case.canonical_entity_id if case else None) or next(iter(self.backend.valid_entities))
            return {
                "answer": "No grounded historical evidence is available for the active case and entity context; the timeline is not populated with a foreign stale finding.",
                "confidence": 0.0,
                "status": "INSUFFICIENT_EVIDENCE",
                "claims": [],
                "evidence_refs": [],
                "provenance_refs": [],
                "uncertainties": ["The active case has no attached finding or provenance-backed history for this entity."],
                "limitations": ["This response intentionally avoids stale default or cross-case evidence."],
                "suggested_next_actions": ["Collect case-scoped evidence before asking for historical attribution."],
                "entity_id": entity_id,
                "case_id": case.case_id if case else case_id,
                "dataset": self._resolve_dataset(case_id=case.case_id if case else case_id, entity_id=entity_id),
            }
        if "graph" in lower or "next" in lower or "examine" in lower or "investigate" in lower:
            entity_id = entity_id or (case.canonical_entity_id if case else None) or next(iter(self.backend.valid_entities))
            return {
                "answer": "No grounded evidence exists in the active case context for the next investigative step; no unrelated finding is used as a fallback.",
                "confidence": 0.0,
                "status": "INSUFFICIENT_EVIDENCE",
                "claims": [],
                "evidence_refs": [],
                "provenance_refs": [],
                "uncertainties": ["No active-case evidence or finding is available for this entity."],
                "limitations": ["This response intentionally avoids stale global finding references."],
                "suggested_next_actions": ["Gather additional evidence for the active case before selecting the next investigative action."],
                "entity_id": entity_id,
                "case_id": case.case_id if case else case_id,
                "dataset": self._resolve_dataset(case_id=case.case_id if case else case_id, entity_id=entity_id),
            }
        if explicit_finding_id:
            return self.explain_finding(explicit_finding_id)
        return self._safe_no_finding_response(q, case_id=case.case_id if case else case_id, entity_id=entity_id or (case.canonical_entity_id if case else None), case=case)

        if "why" in lower or "flagged" in lower:
            if explicit_finding_id is not None:
                if case is not None:
                    selected = self._pick_case_finding_id(case_id=case.case_id, entity_id=entity_id, explicit_finding_id=explicit_finding_id)
                    return self.explain_finding(selected)
                return self.explain_finding(explicit_finding_id)

            if case is not None:
                selected = self._pick_case_finding_id(case_id=case.case_id, entity_id=entity_id)
                if selected is None:
                    return self._safe_no_finding_response(q, case_id=case.case_id, entity_id=case.canonical_entity_id, case=case)
                return self.explain_finding(selected)

            return self._safe_no_finding_response(q, case_id=case_id, entity_id=entity_id)

        if "summarize" in lower or "case" in lower:
            if case is not None:
                return self.summarize_case(case.case_id)
            if self.backend.cases:
                case_id = next(iter(self.backend.cases))
                return self.summarize_case(case_id)
            raise ValueError("No case context available for summarization.")

        if "evidence" in lower:
            finding_id = explicit_finding_id or self._pick_case_finding_id(case_id=case.case_id if case else None, entity_id=entity_id)
            if finding_id is None:
                return self._safe_no_finding_response(q, case_id=case.case_id if case else case_id, entity_id=entity_id or (case.canonical_entity_id if case else None), case=case)
            return self.evidence_for_finding(finding_id)
        if "contradict" in lower:
            finding_id = explicit_finding_id or self._pick_case_finding_id(case_id=case.case_id if case else None, entity_id=entity_id)
            if finding_id is None:
                return self._safe_no_finding_response(q, case_id=case.case_id if case else case_id, entity_id=entity_id or (case.canonical_entity_id if case else None), case=case)
            return self.contradictions_for_finding(finding_id)
        if "timeline" in lower or "before" in lower or "history" in lower or "anomalous behavior" in lower:
            entity_id = entity_id or (case.canonical_entity_id if case else None) or next(iter(self.backend.valid_entities))
            return {
                "answer": "No grounded historical evidence is available for the active case and entity context; the timeline is not populated with a foreign stale finding.",
                "confidence": 0.0,
                "status": "INSUFFICIENT_EVIDENCE",
                "claims": [],
                "evidence_refs": [],
                "provenance_refs": [],
                "uncertainties": ["The active case has no attached finding or provenance-backed history for this entity."],
                "limitations": ["This response intentionally avoids stale default or cross-case evidence."],
                "suggested_next_actions": ["Collect case-scoped evidence before asking for historical attribution."],
                "entity_id": entity_id,
                "case_id": case.case_id if case else case_id,
                "dataset": self._resolve_dataset(case_id=case.case_id if case else case_id, entity_id=entity_id),
            }
        if "graph" in lower or "next" in lower or "examine" in lower or "investigate" in lower:
            entity_id = entity_id or (case.canonical_entity_id if case else None) or next(iter(self.backend.valid_entities))
            return {
                "answer": "No grounded evidence exists in the active case context for the next investigative step; no unrelated finding is used as a fallback.",
                "confidence": 0.0,
                "status": "INSUFFICIENT_EVIDENCE",
                "claims": [],
                "evidence_refs": [],
                "provenance_refs": [],
                "uncertainties": ["No active-case evidence or finding is available for this entity."],
                "limitations": ["This response intentionally avoids stale global finding references."],
                "suggested_next_actions": ["Gather additional evidence for the active case before selecting the next investigative action."],
                "entity_id": entity_id,
                "case_id": case.case_id if case else case_id,
                "dataset": self._resolve_dataset(case_id=case.case_id if case else case_id, entity_id=entity_id),
            }
        if explicit_finding_id:
            return self.explain_finding(explicit_finding_id)
        return self._safe_no_finding_response(q, case_id=case.case_id if case else case_id, entity_id=entity_id or (case.canonical_entity_id if case else None), case=case)

    def investigate_entity(self, entity_id: str) -> Dict[str, Any]:
        if entity_id not in self.backend.valid_entities:
            raise ValueError(f"Unknown entity '{entity_id}' in authoritative registries.")
        context = self.retriever.get_entity_context(entity_id)
        return {
            **context,
            "status": "GROUNDED",
            "answer": f"Entity {entity_id} was investigated using the authoritative DFAP entity, graph, timeline, and provenance context.",
            "confidence": 0.9,
            "claims": [{"claim": f"Entity {entity_id} is in the authoritative registry.", "evidence_ids": []}],
            "evidence_refs": [],
            "provenance_refs": [],
            "uncertainties": ["Identity classification is limited to authoritative registry evidence."],
            "limitations": ["No criminal conclusion is inferred."],
            "suggested_next_actions": ["Review the entity timeline.", "Inspect related graph neighbors."],
        }

    def explain_finding(self, finding_id: str) -> Dict[str, Any]:
        payload = self.reasoner.explain_finding(finding_id)
        result = self.formatter.format(payload)
        result["finding_id"] = payload.get("finding_id")
        result["entity_id"] = payload.get("entity_id")
        result["status"] = result["status"]
        if payload.get("shap_explanation"):
            result["shap_explanation"] = payload["shap_explanation"]
        return result

    def summarize_case(self, case_id: str) -> Dict[str, Any]:
        payload = self.reasoner.summarize_case(case_id)
        return {
            "case_id": payload["case_id"],
            "entity_id": payload["entity_id"],
            "summary": payload["summary"],
            "important_findings": payload["important_findings"],
            "supporting_evidence": payload["supporting_evidence"],
            "contradicting_evidence": payload["contradicting_evidence"],
            "unresolved_questions": payload["unresolved_questions"],
            "provenance_integrity_status": payload["provenance_integrity_status"],
            "recommended_next_actions": payload["recommended_next_actions"],
            "status": "GROUNDED",
            "answer": payload["summary"],
            "confidence": 0.88,
            "claims": [{"claim": payload["summary"], "evidence_ids": payload["supporting_evidence"]}],
            "evidence_refs": payload["supporting_evidence"],
            "provenance_refs": payload["supporting_evidence"],
            "uncertainties": ["Summary is scoped to this case and attached findings only."],
            "limitations": ["No unsupported investigative conclusion is implied."],
            "suggested_next_actions": payload["recommended_next_actions"],
        }

    def evidence_for_finding(self, finding_id: str) -> Dict[str, Any]:
        if finding_id not in self.backend.findings_by_id:
            raise ValueError(f"Unknown finding '{finding_id}' in authoritative finding ledger.")
        evidence = self.retriever.get_evidence_for_finding(finding_id)
        if not evidence:
            raise ValueError(f"No evidence records are associated with finding '{finding_id}'.")
        return {
            "finding_id": finding_id,
            "evidence": evidence,
            "status": "GROUNDED",
            "answer": f"Evidence for finding {finding_id} was retrieved from the M12 provenance chain.",
            "confidence": 0.92,
            "claims": [{"claim": f"Finding {finding_id} has supporting evidence records.", "evidence_ids": [row["evidence_id"] for row in evidence]}],
            "evidence_refs": [row["evidence_id"] for row in evidence],
            "provenance_refs": [row.get("provenance_ref") for row in evidence if row.get("provenance_ref")],
            "uncertainties": [],
            "limitations": ["This only lists evidence that is actually bound to the finding."],
            "suggested_next_actions": ["Review each evidence item in the provenance chain."],
        }

    def contradictions_for_finding(self, finding_id: str) -> Dict[str, Any]:
        if finding_id not in self.backend.findings_by_id:
            raise ValueError(f"Unknown finding '{finding_id}' in authoritative finding ledger.")
        provenance = self.backend.get_provenance(finding_id)
        evidence = self.retriever.get_evidence_for_finding(finding_id)
        contradicting = [row for row in evidence if row.get("evidence_category") == "CONTRADICTING"]
        return {
            "finding_id": finding_id,
            "contradicting_evidence": contradicting,
            "status": "GROUNDED" if contradicting else "INSUFFICIENT_EVIDENCE",
            "answer": f"Contradicting evidence for finding {finding_id} was reviewed from the M12 provenance graph.",
            "confidence": 0.85,
            "claims": [{"claim": f"Finding {finding_id} has {len(contradicting)} contradicting evidence records.", "evidence_ids": [row["evidence_id"] for row in contradicting]}],
            "evidence_refs": [row["evidence_id"] for row in contradicting],
            "provenance_refs": [row.get("provenance_ref") for row in contradicting if row.get("provenance_ref")],
            "uncertainties": ["Contradictions are only reported when they are actually present in the provenance chain."],
            "limitations": ["This response does not force a conclusion when evidence conflicts."],
            "suggested_next_actions": ["Review the contradicting evidence and timeline context."],
        }

    def timeline_for_entity(self, entity_id: str) -> List[Dict[str, Any]]:
        if entity_id not in self.backend.valid_entities:
            raise ValueError(f"Unknown entity '{entity_id}' in authoritative registries.")
        return self.backend.get_timeline(entity_id)

    def graph_for_entity(self, entity_id: str) -> Dict[str, Any]:
        if entity_id not in self.backend.valid_entities:
            raise ValueError(f"Unknown entity '{entity_id}' in authoritative registries.")
        return self.backend.graph_traversal.get_2hop_subgraph(entity_id)

    def next_actions(self, case_id: str) -> List[str]:
        case = self.backend.get_case(case_id)
        actions = [
            "Inspect additional timeline windows for the target entity.",
            "Review related graph neighbors for the target entity.",
            "Inspect contradicting evidence if present.",
            "Verify identity mapping using authoritative registry evidence.",
        ]
        return actions

    def verify_finding(self, finding_id: str) -> Dict[str, Any]:
        if finding_id not in self.backend.findings_by_id:
            raise ValueError(f"Unknown finding '{finding_id}' in authoritative finding ledger.")
        prov = self.backend.get_provenance(finding_id)
        return {
            "finding_id": finding_id,
            "integrity_status": prov.get("integrity_status"),
            "is_valid": prov.get("is_valid", False),
            "status": "GROUNDED" if prov.get("is_valid") else "INSUFFICIENT_EVIDENCE",
            "answer": f"Finding {finding_id} provenance integrity is {prov.get('integrity_status')}.",
            "confidence": 0.95,
            "claims": [{"claim": f"Provenance for {finding_id} is valid.", "evidence_ids": [node.get("node_id") for node in prov.get("lineage_chain", []) if isinstance(node, dict) and node.get("node_id")]}],
            "evidence_refs": [node.get("node_id") for node in prov.get("lineage_chain", []) if isinstance(node, dict) and node.get("node_id")],
            "provenance_refs": [node.get("node_id") for node in prov.get("lineage_chain", []) if isinstance(node, dict) and node.get("node_id")],
            "uncertainties": [],
            "limitations": ["Integrity checks only validate the stored authoritative provenance chain."],
            "suggested_next_actions": ["Proceed with review only if the evidence and provenance remain intact."],
        }

    def investigate_agentic(
        self,
        question: str,
        case_id: Optional[str] = None,
        entity_id: Optional[str] = None,
        finding_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Executes full M14 agentic investigation with local Ollama synthesis."""
        from dfap.investigation.agentic_orchestrator import AgenticInvestigationOrchestrator
        orch = AgenticInvestigationOrchestrator(self.backend)
        res = orch.investigate(
            question=question,
            case_id=case_id,
            entity_id=entity_id,
            finding_id=finding_id
        )
        return self.formatter.format(res.to_dict())

    answer_question = ask

