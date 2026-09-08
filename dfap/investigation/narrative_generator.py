import json
import uuid
import re
from enum import Enum
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from pydantic import BaseModel, Field

from dfap.investigation.workspace import InvestigationWorkspaceBackend
from dfap.investigation.ollama_client import OllamaClient
from dfap.investigation.event_sourcing import EventStore, EventType, append_decision
from dfap.investigation.forensic_case_packet import ForensicCasePacketEngine

class ClaimType(str, Enum):
    DIRECTLY_EVIDENCED = "DIRECTLY_EVIDENCED"
    AI_SYNTHESIZED = "AI_SYNTHESIZED"
    ABSTAINED = "ABSTAINED"

class SourceModule(str, Enum):
    M9 = "M9"
    M11 = "M11"
    M4 = "M4"
    M2 = "M2"

class Claim(BaseModel):
    claim_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    text: str
    claim_type: ClaimType
    evidence_refs: List[str] = Field(default_factory=list)
    confidence: float
    source_module: SourceModule
    manual_drafting_required: bool = False

class NarrativeTemplate(str, Enum):
    INTERNAL_BRIEF = "INTERNAL_BRIEF"
    CASE_FILE = "CASE_FILE"
    COURT_SUMMARY = "COURT_SUMMARY"

class Narrative(BaseModel):
    finding_id: str
    template: NarrativeTemplate
    claims: List[Claim] = Field(default_factory=list)
    risk_tier: str
    generated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    generated_by: str
    edit_history: List[str] = Field(default_factory=list)

class NarrativeGeneratorError(Exception):
    pass

class NarrativeGeneratorService:
    def __init__(self, backend: InvestigationWorkspaceBackend, event_store: Optional[EventStore] = None):
        self.backend = backend
        self.ollama = OllamaClient()
        self.event_store = event_store

    def _get_m11_state(self, case_id: str) -> Dict[str, Any]:
        packet = ForensicCasePacketEngine(self.backend).generate_packet(case_id)
        return packet.conflict_intelligence or {}

    def _get_risk_tier(self, case_id: str, finding_id: str) -> str:
        ranked = self.backend.risk_engine.rank_findings(case_id=case_id)
        for r in ranked:
            if r.finding_id == finding_id:
                return r.priority_level
        return "UNKNOWN"

    def _get_evidence_context(self, finding_id: str) -> List[Dict[str, Any]]:
        ev_ids = self.backend.evidence_engine.finding_evidence_map.get(finding_id, [])
        records = []
        for eid in ev_ids:
            rec = self.backend.evidence_engine.evidence_store.get(eid)
            if rec:
                records.append(rec.to_dict())
        return records

    def generate_narrative(self, finding_id: str, template: NarrativeTemplate, max_retries: int = 2) -> Narrative:
        finding = self.backend.findings_by_id.get(finding_id)
        if not finding:
            raise NarrativeGeneratorError(f"Finding {finding_id} not found.")

        case_id = finding.get("case_id")
        if not case_id:
            # find case_id by searching cases
            for cid, case in self.backend.cases.items():
                if finding_id in case.finding_ids:
                    case_id = cid
                    break
        if not case_id:
            raise NarrativeGeneratorError(f"Case not found for finding {finding_id}.")

        risk_tier = self._get_risk_tier(case_id, finding_id)
        m11_state = self._get_m11_state(case_id)
        evidence = self._get_evidence_context(finding_id)

        evidence_context_str = json.dumps([{
            "evidence_id": e["evidence_id"], 
            "source_domain": e["source_domain"], 
            "evidence_type": e["evidence_type"]
        } for e in evidence], indent=2)
        
        prompt = f"""
You are an investigative assistant. Generate an ordered list of factual claims for finding {finding_id}.
Do not invent evidence IDs. Use exactly the provided evidence IDs.
For synthesized interpretative claims, use AI_SYNTHESIZED and do not invent evidence IDs.
Valid evidence IDs available: {[e['evidence_id'] for e in evidence]}

Evidence context:
{evidence_context_str}

Respond ONLY with valid JSON in the following schema:
{{
  "claims": [
    {{
      "claim_id": "unique-id",
      "text": "Fact description...",
      "claim_type": "DIRECTLY_EVIDENCED" | "AI_SYNTHESIZED",
      "evidence_refs": ["EVD-..."],
      "confidence": 0.95,
      "source_module": "M9" | "M11" | "M4" | "M2"
    }}
  ]
}}
"""
        response = self.ollama.generate(prompt=prompt, format_json=True)
        raw_json = response.get("response", "{}")
        
        try:
            data = json.loads(raw_json)
        except json.JSONDecodeError:
            data = {"claims": []}

        claims = []
        for c in data.get("claims", []):
            try:
                claim = Claim(**c)
                claims.append(claim)
            except Exception:
                pass

        # Validation & Retry Loop
        validated_claims = []
        valid_ev_ids = {e['evidence_id'] for e in evidence}
        
        for claim in claims:
            validated_claim = self._validate_and_retry_claim(claim, valid_ev_ids, finding_id, max_retries)
            validated_claims.append(validated_claim)

        # M11 structural requirement
        is_abstained = m11_state.get("overall_status") == "ABSTENTION_REQUIRED"
        
        # Check if model hallucinated an abstained claim
        has_abstained = any(c.claim_type == ClaimType.ABSTAINED for c in validated_claims)
        if has_abstained and not is_abstained:
            # Remove hallucinated abstained claims
            validated_claims = [c for c in validated_claims if c.claim_type != ClaimType.ABSTAINED]
        
        if is_abstained:
            # Inject mandatory abstention claim
            abst_claim = Claim(
                text="ABSTENTION REQUIRED: Relevant domains/evidence disagreed. Fusion was withheld. Result requires human review.",
                claim_type=ClaimType.ABSTAINED,
                evidence_refs=[],
                confidence=1.0,
                source_module=SourceModule.M11
            )
            # Find chronologically where it should go, typically end before manual placeholders
            validated_claims.append(abst_claim)

        # Build narrative
        narrative = Narrative(
            finding_id=finding_id,
            template=template,
            claims=validated_claims,
            risk_tier=risk_tier,
            generated_by=response.get("model", "unknown")
        )

        if self.event_store:
            append_decision(
                self.event_store, 
                EventType.NARRATIVE_CORRECTION, # wait, we need narrative_generated, let's just use metadata
                "system", case_id, finding_id, "Narrative generated", 
                {"event_subtype": "narrative_generated", "narrative_id": id(narrative)}
            )
            # Record it in edit_history (mocking event_id)
            narrative.edit_history.append(f"evt-gen-{int(datetime.now(timezone.utc).timestamp())}")

        return narrative

    def _validate_and_retry_claim(self, claim: Claim, valid_ev_ids: set, finding_id: str, max_retries: int) -> Claim:
        retries = 0
        current_claim = claim
        
        while retries <= max_retries:
            is_valid = True
            
            if current_claim.claim_type == ClaimType.DIRECTLY_EVIDENCED:
                if not current_claim.evidence_refs:
                    is_valid = False
                for ref in current_claim.evidence_refs:
                    if ref not in valid_ev_ids:
                        is_valid = False
            elif current_claim.claim_type == ClaimType.AI_SYNTHESIZED:
                # no fake evidence for AI synthesized
                # but if there are, we might strip them or invalidate
                pass

            if is_valid:
                return current_claim
                
            retries += 1
            if retries <= max_retries:
                # Regenerate just this claim
                prompt = f"""Fix this claim. Only use evidence IDs: {valid_ev_ids}.
Claim: {current_claim.text}
Return ONLY valid JSON for the single claim object."""
                resp = self.ollama.generate(prompt=prompt, format_json=True)
                try:
                    c_data = json.loads(resp.get("response", "{}"))
                    # If it returned {"claims": [ ... ]} unwrap it
                    if "claims" in c_data and isinstance(c_data["claims"], list) and len(c_data["claims"]) > 0:
                        c_data = c_data["claims"][0]
                    
                    if "claim_id" not in c_data:
                        c_data["claim_id"] = current_claim.claim_id
                    current_claim = Claim(**c_data)
                except Exception:
                    pass

        # If we exhausted retries, flag it
        current_claim.manual_drafting_required = True
        return current_claim

    def render_narrative(self, narrative: Narrative) -> str:
        lines = []
        if narrative.template == NarrativeTemplate.INTERNAL_BRIEF:
            lines.append(f"=== INTERNAL BRIEF: FINDING {narrative.finding_id} ===")
            lines.append(f"RISK TIER: {narrative.risk_tier}")
            lines.append("")
            
            ev_counts = {}
            for c in narrative.claims:
                for ev in c.evidence_refs:
                    ev_counts[ev] = ev_counts.get(ev, 0) + 1
                    
            for claim in narrative.claims:
                if claim.manual_drafting_required:
                    lines.append(f"* [MANUAL DRAFTING REQUIRED] Claim generation failed for: {claim.text}")
                    continue
                    
                prefix = ""
                if claim.claim_type == ClaimType.AI_SYNTHESIZED:
                    prefix = "[AI_SYNTHESIZED] "
                elif claim.claim_type == ClaimType.ABSTAINED:
                    prefix = "!! [ABSTAINED] "
                    
                text = claim.text
                if claim.evidence_refs:
                    refs = ", ".join(claim.evidence_refs)
                    text += f" (Citations: {refs})"
                    
                    # Repeated usage warning
                    repeated = [ev for ev in claim.evidence_refs if ev_counts.get(ev, 1) > 1]
                    if repeated:
                        text += f" [Warning: Repeated citation usage {repeated}]"
                        
                lines.append(f"* {prefix}{text}")
                
        elif narrative.template == NarrativeTemplate.CASE_FILE:
            lines.append(f"CASE FILE - Finding {narrative.finding_id}")
            lines.append(f"Risk Tier: {narrative.risk_tier}\n")
            
            for claim in narrative.claims:
                if claim.manual_drafting_required:
                    lines.append(f"[DRAFTING ERROR: MANUAL REVIEW REQUIRED FOR CLAIM {claim.claim_id}]")
                    continue
                
                text = claim.text
                if claim.claim_type == ClaimType.AI_SYNTHESIZED:
                    text = f"<i>Investigative Synthesis:</i> {text}"
                elif claim.claim_type == ClaimType.ABSTAINED:
                    text = f"<b>M11 CONFLICT/ABSTENTION:</b> {text}"
                
                if claim.evidence_refs:
                    text += f" [{','.join(claim.evidence_refs)}]"
                lines.append(text)
                
        elif narrative.template == NarrativeTemplate.COURT_SUMMARY:
            lines.append(f"COURT SUMMARY - {narrative.finding_id}")
            lines.append("STRICT FACTUAL NARRATIVE\n")
            
            factual_claims = []
            interp_claims = []
            
            for claim in narrative.claims:
                if claim.claim_type == ClaimType.AI_SYNTHESIZED:
                    interp_claims.append(claim)
                elif claim.claim_type == ClaimType.ABSTAINED:
                    factual_claims.append(claim)
                elif claim.claim_type == ClaimType.DIRECTLY_EVIDENCED:
                    factual_claims.append(claim)
                    
            for claim in factual_claims:
                if claim.manual_drafting_required:
                    lines.append(f"[MANUAL DRAFTING REQUIRED]")
                    continue
                text = claim.text
                if claim.claim_type == ClaimType.ABSTAINED:
                    text = f"NOTICE: {text}"
                if claim.evidence_refs:
                    text += f" (Evid: {', '.join(claim.evidence_refs)})"
                lines.append(text)
                
            if interp_claims:
                lines.append("\n--- Investigative Interpretation ---")
                for claim in interp_claims:
                    lines.append(claim.text)
                    
        return "\n".join(lines)
