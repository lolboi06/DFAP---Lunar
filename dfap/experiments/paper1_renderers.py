# Author: Sam Roger X
# Component: DFAP Paper 1 Evaluation Harness
# Scope: Experimental Renderers for Presentation Conditions (SILENT_DROP, LOW_SCORE, FORCED_DISCLOSURE)

from typing import Dict, Any, List, Optional
from dfap.experiments.paper1_models import (
    AbstentionPresentationCondition,
    GroundTruthLabel,
)


def render_presentation(
    case_def: Dict[str, Any],
    condition: AbstentionPresentationCondition,
) -> Dict[str, Any]:
    """
    Renders the participant-facing presentation for a case under the assigned condition.

    CRITICAL INVARIANTS:
    1. Underlying evidence, finding ID, entity ID, ground truth, and M11 state remain identical.
    2. Blinding: The internal condition name ('SILENT_DROP', 'LOW_SCORE', 'FORCED_DISCLOSURE')
       is STRICTLY OMITTED from participant-facing output.
    3. Equivalence: Typography, field keys, and prompt formatting are controlled across conditions.
    """
    finding_id = case_def["finding_id"]
    entity_id = case_def.get("entity_id", "ENT_SYNTHETIC_TARGET")
    evidence_items = case_def.get("evidence_items", [])
    m11_state = case_def.get("m11_state", {})
    is_abstained = m11_state.get("overall_status") == "ABSTENTION_REQUIRED"
    
    # Base factual claims derived from evidence (unrelated to abstention)
    base_claims = list(case_def.get("claims", []))

    if not is_abstained:
        # ── NON-ABSTAINED FINDING: ALL CONDITIONS PRESENT IDENTICALLY ────────
        return {
            "entity_id": entity_id,
            "finding_id": finding_id,
            "finding_visible": True,
            "corroboration_score": case_def.get("score", 0.85),
            "status_summary": case_def.get("status_summary", "Cross-domain activity corroborated across domains."),
            "claims": base_claims,
            "evidence_references": [e.get("evidence_id") for e in evidence_items],
            "abstention_disclosed": False,
        }

    # ── ABSTAINED FINDING (M11 says ABSTENTION_REQUIRED) ──────────────────────
    if condition == AbstentionPresentationCondition.SILENT_DROP:
        # A. SILENT_DROP: Finding is completely omitted from the human-facing view.
        return {
            "entity_id": entity_id,
            "finding_id": None,
            "finding_visible": False,
            "corroboration_score": None,
            "status_summary": "No conclusive cross-domain findings identified for this entity during the monitored window.",
            "claims": [],
            "evidence_references": [],
            "abstention_disclosed": False,
        }

    elif condition == AbstentionPresentationCondition.LOW_SCORE:
        # B. LOW_SCORE: Finding is shown as a low/uncertain score.
        # No explicit explanation that the underlying fusion process abstained because of conflicting evidence.
        return {
            "entity_id": entity_id,
            "finding_id": finding_id,
            "finding_visible": True,
            "corroboration_score": 0.20,  # Low/uncertain numerical presentation score
            "status_summary": "Finding evaluated with low corroboration score.",
            "claims": [c for c in base_claims if c.get("claim_type") != "ABSTAINED"],
            "evidence_references": [e.get("evidence_id") for e in evidence_items],
            "abstention_disclosed": False,
        }

    elif condition == AbstentionPresentationCondition.FORCED_DISCLOSURE:
        # C. FORCED_DISCLOSURE: Real Feature 2 structural ABSTAINED claim explicitly disclosing conflict.
        disclosure_claim = {
            "claim_id": f"CLM_ABST_{finding_id}",
            "text": "ABSTENTION REQUIRED: Relevant domains/evidence disagreed. Fusion was withheld. Result requires human review.",
            "claim_type": "ABSTAINED",
            "evidence_refs": [],
            "confidence": 1.0,
            "source_module": "M11"
        }
        claims_with_abstention = [c for c in base_claims if c.get("claim_type") != "ABSTAINED"] + [disclosure_claim]

        return {
            "entity_id": entity_id,
            "finding_id": finding_id,
            "finding_visible": True,
            "corroboration_score": None,
            "status_summary": "ABSTENTION REQUIRED: Cross-domain evidential conflict detected. Automated fusion withheld.",
            "claims": claims_with_abstention,
            "evidence_references": [e.get("evidence_id") for e in evidence_items],
            "abstention_disclosed": True,
        }

    else:
        raise ValueError(f"Unknown presentation condition '{condition}'")
