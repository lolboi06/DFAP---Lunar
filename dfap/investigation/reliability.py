# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: Evidence Quality & Reliability Engine

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, Any, List, Optional, Set, Tuple

import numpy as np
import pandas as pd

from dfap.investigation.evidence_provenance import (
    CanonicalEvidenceRecord,
    EvidenceStatus,
    ProvenanceIntegrityStatus,
)
from dfap.investigation.temporal_engine import load_identity_bridge_readonly
from dfap.investigation.workspace import InvestigationWorkspaceBackend, InvestigationCase


class EvidenceSufficiency(str, Enum):
    NO_VALID_EVIDENCE = "NO_VALID_EVIDENCE"
    WEAK_EVIDENCE = "WEAK_EVIDENCE"
    SUFFICIENT_EVIDENCE = "SUFFICIENT_EVIDENCE"
    CONFLICTED_EVIDENCE = "CONFLICTED_EVIDENCE"


class ConflictSeverity(str, Enum):
    NO_CONFLICT = "NO_CONFLICT"
    WEAK_CONFLICT = "WEAK_CONFLICT"
    MODERATE_CONFLICT = "MODERATE_CONFLICT"
    STRONG_CONFLICT = "STRONG_CONFLICT"


class ReliabilityStatus(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    CONFLICTED = "CONFLICTED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


@dataclass(frozen=True)
class ReliabilityConfig:
    """
    Immutable, strictly validated configuration for the Evidence Quality & Reliability Engine.
    Zero hidden constants.
    """
    algorithm_version: str = "v1.0.0_PRODUCTION_RESEARCH"
    configuration_version: str = "cfg_v1.0"
    weights: Dict[str, float] = field(default_factory=lambda: {
        "identity": 0.25,
        "temporal": 0.15,
        "evidence_quality": 0.15,
        "corroboration": 0.20,
        "data_quality": 0.10,
        "provenance": 0.15,
    })
    target_independent_events: int = 3
    target_independent_domains: int = 2
    min_independent_clusters: int = 2
    min_identity_confidence: float = 0.70
    strong_identity_confidence: float = 0.85
    target_support_items: float = 2.0
    target_contradiction_items: float = 1.0
    conflict_penalty_multiplier: Dict[str, float] = field(default_factory=lambda: {
        "NO_CONFLICT": 0.0,
        "WEAK_CONFLICT": 0.10,
        "MODERATE_CONFLICT": 0.25,
        "STRONG_CONFLICT": 0.35,
    })

    def __post_init__(self):
        # Validate versions
        if not self.algorithm_version or not str(self.algorithm_version).strip():
            raise ValueError("algorithm_version must be a non-empty string.")
        if not self.configuration_version or not str(self.configuration_version).strip():
            raise ValueError("configuration_version must be a non-empty string.")

        # Validate weights
        required_weight_keys = {"identity", "temporal", "evidence_quality", "corroboration", "data_quality", "provenance"}
        if set(self.weights.keys()) != required_weight_keys:
            raise ValueError(f"weights keys must exactly match {required_weight_keys}, got {set(self.weights.keys())}")

        total_weight = 0.0
        for k, v in self.weights.items():
            if not isinstance(v, (int, float)) or math.isnan(v):
                raise ValueError(f"Weight '{k}' must be a numeric float, got {v}")
            if v < 0.0:
                raise ValueError(f"Weight '{k}' must be non-negative, got {v}")
            total_weight += float(v)

        if abs(total_weight - 1.0) > 1e-4:
            raise ValueError(f"Component weights must sum exactly to 1.0 (got {total_weight:.6f}). Do not silently normalize.")

        # Validate thresholds
        if self.target_independent_events <= 0:
            raise ValueError("target_independent_events must be positive integer.")
        if self.target_independent_domains <= 0:
            raise ValueError("target_independent_domains must be positive integer.")
        if self.min_independent_clusters <= 0:
            raise ValueError("min_independent_clusters must be positive integer.")
        if not (0.0 <= self.min_identity_confidence <= 1.0):
            raise ValueError("min_identity_confidence must be in [0.0, 1.0].")
        if not (0.0 <= self.strong_identity_confidence <= 1.0):
            raise ValueError("strong_identity_confidence must be in [0.0, 1.0].")
        if self.strong_identity_confidence < self.min_identity_confidence:
            raise ValueError("strong_identity_confidence cannot be less than min_identity_confidence.")

        # Validate multipliers
        required_severities = {"NO_CONFLICT", "WEAK_CONFLICT", "MODERATE_CONFLICT", "STRONG_CONFLICT"}
        if set(self.conflict_penalty_multiplier.keys()) != required_severities:
            raise ValueError(f"conflict_penalty_multiplier keys must match {required_severities}")
        for k, m in self.conflict_penalty_multiplier.items():
            if not isinstance(m, (int, float)) or m < 0.0:
                raise ValueError(f"Multiplier for '{k}' must be non-negative float.")


@dataclass
class EvidenceItemAssessment:
    """Detailed deterministic assessment for an individual evidence record."""
    evidence_ref: str
    source_domain: str
    event_id: str
    evidence_category: str  # SUPPORTING, CONTRADICTING, CONTEXTUAL
    identity_contribution: float
    temporal_contribution: float
    quality_contribution: float
    provenance_status: str
    is_duplicate: bool
    is_future_event: bool
    root_ancestor_id: Optional[str]
    reliability_contribution: float
    reason: str
    cryptographic_integrity: str = "INTEGRITY_VERIFIED"
    lineage_status: str = "ROOT_ANCESTOR_VERIFIED"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "evidence_ref": self.evidence_ref,
            "source_domain": self.source_domain,
            "event_id": self.event_id,
            "evidence_category": self.evidence_category,
            "identity_contribution": round(self.identity_contribution, 4),
            "temporal_contribution": round(self.temporal_contribution, 4),
            "quality_contribution": round(self.quality_contribution, 4),
            "provenance_status": self.provenance_status,
            "cryptographic_integrity": self.cryptographic_integrity,
            "lineage_status": self.lineage_status,
            "is_duplicate": self.is_duplicate,
            "is_future_event": self.is_future_event,
            "root_ancestor_id": self.root_ancestor_id,
            "reliability_contribution": round(self.reliability_contribution, 4),
            "reason": self.reason,
        }


@dataclass
class ReliabilityAssessment:
    """
    Structured, auditable assessment produced by EvidenceQualityReliabilityEngine.
    Separates continuous reliability score from categorical decision status.
    """
    case_id: str
    finding_id: str
    canonical_entity_id: str
    overall_score: float
    overall_status: ReliabilityStatus
    evidence_sufficiency: EvidenceSufficiency
    conflict_status: str
    conflict_severity: ConflictSeverity
    support_strength: float
    contradiction_strength: float
    contradiction_penalty: float
    components: Dict[str, float]
    supporting_evidence: List[str]
    contradicting_evidence: List[str]
    unresolved_evidence: List[str]
    duplicate_evidence: List[str]
    evidence_breakdown: List[EvidenceItemAssessment]
    reasons: List[str]
    limitations: List[str]
    algorithm_version: str
    configuration_version: str
    evaluated_at: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "case_id": self.case_id,
            "finding_id": self.finding_id,
            "canonical_entity_id": self.canonical_entity_id,
            "overall_score": self.overall_score,
            "overall_status": self.overall_status.value if hasattr(self.overall_status, "value") else str(self.overall_status),
            "evidence_sufficiency": self.evidence_sufficiency.value if hasattr(self.evidence_sufficiency, "value") else str(self.evidence_sufficiency),
            "conflict_status": self.conflict_status,
            "conflict_severity": self.conflict_severity.value if hasattr(self.conflict_severity, "value") else str(self.conflict_severity),
            "support_strength": self.support_strength,
            "contradiction_strength": self.contradiction_strength,
            "contradiction_penalty": self.contradiction_penalty,
            "components": {k: round(v, 4) for k, v in self.components.items()},
            "supporting_evidence": self.supporting_evidence,
            "contradicting_evidence": self.contradicting_evidence,
            "unresolved_evidence": self.unresolved_evidence,
            "duplicate_evidence": self.duplicate_evidence,
            "evidence_breakdown": [eb.to_dict() for eb in self.evidence_breakdown],
            "reasons": self.reasons,
            "limitations": self.limitations,
            "algorithm_version": self.algorithm_version,
            "configuration_version": self.configuration_version,
            "evaluated_at": self.evaluated_at,
        }


class EvidenceQualityReliabilityEngine:
    """
    Deterministic Evidence Quality & Reliability Engine.
    Evaluates evidence independence, identity binding, temporal causality, provenance integrity,
    and cross-domain contradictions without averaging away evidential conflicts.
    """

    def __init__(
        self,
        backend: InvestigationWorkspaceBackend,
        config: Optional[ReliabilityConfig] = None
    ):
        self.backend = backend
        self.config = config or ReliabilityConfig()
        self._identity_bridge_cache = None

    def _get_identity_bridge(self) -> pd.DataFrame:
        if self._identity_bridge_cache is None:
            self._identity_bridge_cache = load_identity_bridge_readonly()
        return self._identity_bridge_cache

    def assess_finding(
        self,
        case_id: str,
        finding_id: str,
        config: Optional[ReliabilityConfig] = None
    ) -> ReliabilityAssessment:
        """
        Main public entry point to evaluate reliability of evidence supporting a finding in a case.
        Strictly scopes evaluation to case_id and finding_id.
        """
        active_config = config or self.config
        now_ts = datetime.now(timezone.utc).isoformat()

        # 1. Scope & Finding Validation
        if case_id not in self.backend.cases:
            raise KeyError(f"Case '{case_id}' does not exist in workspace backend.")
        case: InvestigationCase = self.backend.cases[case_id]

        if finding_id not in case.finding_ids:
            raise ValueError(f"Finding '{finding_id}' is not attached to case '{case_id}' (Case isolation violation).")

        if finding_id not in self.backend.findings_by_id:
            raise KeyError(f"Finding '{finding_id}' does not exist in backend findings registry.")
        finding = self.backend.findings_by_id[finding_id]

        canonical_entity_id = case.canonical_entity_id

        # Fail-closed entity check
        if canonical_entity_id not in self.backend.valid_entities:
            return self._build_empty_assessment(
                case_id=case_id,
                finding_id=finding_id,
                canonical_entity_id=canonical_entity_id,
                status=ReliabilityStatus.INSUFFICIENT_EVIDENCE,
                sufficiency=EvidenceSufficiency.NO_VALID_EVIDENCE,
                reasons=[f"Fail Closed: Canonical entity '{canonical_entity_id}' is not registered in authoritative registries."],
                config=active_config,
                evaluated_at=now_ts
            )

        # 2. Gather Evidence attached to finding & case
        attached_ev_ids = list(self.backend.evidence_engine.finding_evidence_map.get(finding_id, []))
        # Also inspect finding dictionary for explicit evidence lists
        for cat_key in ["supporting_evidence", "contradicting_evidence", "contextual_evidence"]:
            for eid in finding.get(cat_key, []):
                if not str(eid).startswith("ref:fnd:"):
                    attached_ev_ids.append(eid)

        # De-duplicate while preserving order, and enforce case scoping
        unique_ev_ids = []
        for eid in attached_ev_ids:
            if eid not in unique_ev_ids and (eid in case.evidence_ids or eid in self.backend.evidence_engine.finding_evidence_map.get(finding_id, [])):
                unique_ev_ids.append(eid)

        if not unique_ev_ids:
            return self._build_empty_assessment(
                case_id=case_id,
                finding_id=finding_id,
                canonical_entity_id=canonical_entity_id,
                status=ReliabilityStatus.INSUFFICIENT_EVIDENCE,
                sufficiency=EvidenceSufficiency.NO_VALID_EVIDENCE,
                reasons=[f"Zero valid evidence records attached to finding '{finding_id}' in case '{case_id}'."],
                config=active_config,
                evaluated_at=now_ts
            )

        # Retrieve evidence records from M12 engine
        evidence_records: List[CanonicalEvidenceRecord] = []
        for eid in unique_ev_ids:
            rec = self.backend.evidence_engine.get_evidence(eid)
            if rec is not None:
                evidence_records.append(rec)

        if not evidence_records:
            return self._build_empty_assessment(
                case_id=case_id,
                finding_id=finding_id,
                canonical_entity_id=canonical_entity_id,
                status=ReliabilityStatus.INSUFFICIENT_EVIDENCE,
                sufficiency=EvidenceSufficiency.NO_VALID_EVIDENCE,
                reasons=["Attached evidence IDs could not be resolved to valid M12 CanonicalEvidenceRecords."],
                config=active_config,
                evaluated_at=now_ts
            )

        # 3. Identity Gate
        # Validate that each record's raw identifier maps authoritatively to canonical_entity_id
        identity_scores: Dict[str, float] = {}
        bridge_df = self._get_identity_bridge()

        for rec in evidence_records:
            conf = self._verify_record_identity(rec, canonical_entity_id, bridge_df)
            identity_scores[rec.evidence_id] = conf

        # 4. Temporal Gate: Trigger timestamp and future-leakage check
        trigger_time = self._extract_trigger_timestamp(finding)
        is_future_map: Dict[str, bool] = {}
        temporal_scores: Dict[str, float] = {}

        for rec in evidence_records:
            obs_t = self._parse_observation_timestamp(rec.observation_timestamp)
            if obs_t is None:
                is_future_map[rec.evidence_id] = False
                temporal_scores[rec.evidence_id] = 0.50  # Missing timestamp penalty
            elif trigger_time is not None and obs_t > trigger_time:
                # Strictly subsequent to trigger: future leakage!
                is_future_map[rec.evidence_id] = True
                temporal_scores[rec.evidence_id] = 0.00
            else:
                is_future_map[rec.evidence_id] = False
                temporal_scores[rec.evidence_id] = 1.00

        # 5. Provenance Gate (M12 DAG audit & integrity verification)
        provenance_status_map: Dict[str, Tuple[str, Optional[str], str, str]] = {}
        provenance_scores: Dict[str, float] = {}

        for rec in evidence_records:
            audit_res = self.backend.evidence_engine.verify_integrity(rec.evidence_id)
            crypto_status = audit_res.get("status", "UNKNOWN")
            root_id = self._find_dag_root_ancestor(rec.evidence_id)

            if crypto_status == ProvenanceIntegrityStatus.INTEGRITY_VERIFIED:
                if root_id:
                    prov_status = "VERIFIED"
                    lineage_st = "ROOT_ANCESTOR_VERIFIED"
                    provenance_scores[rec.evidence_id] = 1.0
                else:
                    prov_status = "RECORD_INTEGRITY_ONLY_UNLINKED_LINEAGE"
                    lineage_st = "UNLINKED_LINEAGE"
                    provenance_scores[rec.evidence_id] = 0.50
            elif crypto_status == ProvenanceIntegrityStatus.TAMPERED_RECORD_DETECTED:
                prov_status = "TAMPERED_RECORD"
                lineage_st = "COMPROMISED"
                provenance_scores[rec.evidence_id] = 0.0
            else:
                prov_status = crypto_status
                lineage_st = "UNKNOWN"
                provenance_scores[rec.evidence_id] = 0.40

            provenance_status_map[rec.evidence_id] = (prov_status, root_id, crypto_status, lineage_st)

        # 6. Dependency & Duplicate Clustering
        clusters, duplicate_ids = self._cluster_evidence_dependencies(evidence_records)

        # 7. Partition into Supporting, Contradicting, and Unresolved items
        supporting_items: List[CanonicalEvidenceRecord] = []
        contradicting_items: List[CanonicalEvidenceRecord] = []
        unresolved_items: List[CanonicalEvidenceRecord] = []

        for rec in evidence_records:
            cat = str(getattr(rec, "evidence_category", "CONTEXTUAL")).upper()
            if cat == "SUPPORTING":
                supporting_items.append(rec)
            elif cat == "CONTRADICTING":
                contradicting_items.append(rec)
            else:
                unresolved_items.append(rec)

        # 8. Compute Support Strength (only non-duplicate, valid identity, non-future items)
        valid_indep_support = [
            r for r in supporting_items
            if r.evidence_id not in duplicate_ids
            and not is_future_map[r.evidence_id]
            and identity_scores[r.evidence_id] >= active_config.min_identity_confidence
        ]
        support_sum = sum(
            identity_scores[r.evidence_id] * float(getattr(r, "evidence_quality", 1.0)) * temporal_scores[r.evidence_id]
            for r in valid_indep_support
        )
        support_strength = round(float(np.clip(support_sum / active_config.target_support_items, 0.0, 1.0)), 4)

        # 9. Compute Contradiction Strength & Conflict Severity
        valid_indep_contra = [
            r for r in contradicting_items
            if r.evidence_id not in duplicate_ids
            and not is_future_map[r.evidence_id]
            and identity_scores[r.evidence_id] >= active_config.min_identity_confidence
        ]
        contra_sum = sum(
            identity_scores[r.evidence_id] * float(getattr(r, "evidence_quality", 1.0)) * temporal_scores[r.evidence_id]
            for r in valid_indep_contra
        )
        contradiction_strength = round(float(np.clip(contra_sum / active_config.target_contradiction_items, 0.0, 1.0)), 4)

        # Determine conflict severity
        # A conflict requires material disagreement: both supporting and contradicting evidence present
        has_material_disagreement = (support_strength >= 0.25 and contradiction_strength >= 0.25) or (finding.get("status") == "CONFLICTED" and contradiction_strength > 0.0)

        if not has_material_disagreement:
            if contradiction_strength == 0.0:
                conflict_severity = ConflictSeverity.NO_CONFLICT
                conflict_status = "NO_CONFLICT"
            else:
                conflict_severity = ConflictSeverity.WEAK_CONFLICT
                conflict_status = "WEAK_CONFLICT" if contradiction_strength <= 0.25 else "UNCONTESTED_CONTRADICTION"
        else:
            if contradiction_strength <= 0.25:
                conflict_severity = ConflictSeverity.WEAK_CONFLICT
                conflict_status = "WEAK_CONFLICT"
            elif contradiction_strength <= 0.60:
                conflict_severity = ConflictSeverity.MODERATE_CONFLICT
                conflict_status = "CONFLICTED"
            else:
                conflict_severity = ConflictSeverity.STRONG_CONFLICT
                conflict_status = "CONFLICTED"

        # Apply multiplier to get contradiction penalty
        contra_multiplier = active_config.conflict_penalty_multiplier[conflict_severity.value]
        contradiction_penalty = round(float(contradiction_strength * contra_multiplier), 4)

        # 10. Corroboration Strength (Independent Clusters)
        # Distinct non-future independent supporting clusters
        valid_supp_clusters = [
            c for c in clusters
            if any(
                r.evidence_id in c and str(getattr(r, "evidence_category", "")).upper() == "SUPPORTING"
                and not is_future_map[r.evidence_id]
                and identity_scores[r.evidence_id] >= active_config.min_identity_confidence
                for r in evidence_records
            )
        ]
        corroboration_strength = round(float(np.clip(len(valid_supp_clusters) / active_config.target_independent_events, 0.0, 1.0)), 4)

        # 11. Component Metrics
        # Filter to active non-future items for average component metrics
        active_items = [r for r in evidence_records if not is_future_map[r.evidence_id]]
        if active_items:
            mean_id_conf = float(np.mean([identity_scores[r.evidence_id] for r in active_items]))
            mean_temp = float(np.mean([temporal_scores[r.evidence_id] for r in active_items]))
            mean_qual = float(np.mean([float(getattr(r, "evidence_quality", 1.0)) for r in active_items]))
            mean_data_qual = float(np.mean([self._assess_record_data_quality(r) for r in active_items]))
            mean_prov = float(np.mean([provenance_scores[r.evidence_id] for r in active_items]))
        else:
            mean_id_conf = 0.0
            mean_temp = 0.0
            mean_qual = 0.0
            mean_data_qual = 0.0
            mean_prov = 0.0

        components = {
            "identity_confidence": round(mean_id_conf, 4),
            "temporal_reliability": round(mean_temp, 4),
            "evidence_quality": round(mean_qual, 4),
            "corroboration_strength": corroboration_strength,
            "data_quality": round(mean_data_qual, 4),
            "provenance_completeness": round(mean_prov, 4),
        }

        # 12. Base Reliability & Overall Score
        w = active_config.weights
        base_reliability = (
            w["identity"] * components["identity_confidence"] +
            w["temporal"] * components["temporal_reliability"] +
            w["evidence_quality"] * components["evidence_quality"] +
            w["corroboration"] * components["corroboration_strength"] +
            w["data_quality"] * components["data_quality"] +
            w["provenance"] * components["provenance_completeness"]
        )
        overall_score = round(float(np.clip(base_reliability - contradiction_penalty, 0.0, 1.0)), 4)

        # 13. Determine Evidence Sufficiency
        items_with_binding = [r for r in active_items if identity_scores[r.evidence_id] > 0.0]
        items_with_strong_binding = [r for r in active_items if identity_scores[r.evidence_id] >= active_config.min_identity_confidence]

        if len(items_with_binding) == 0:
            evidence_sufficiency = EvidenceSufficiency.NO_VALID_EVIDENCE
        elif support_strength >= 0.25 and contradiction_strength >= 0.25:
            evidence_sufficiency = EvidenceSufficiency.CONFLICTED_EVIDENCE
        elif (
            len(items_with_strong_binding) == 0
            or components["identity_confidence"] < active_config.min_identity_confidence
            or len(valid_supp_clusters) < active_config.min_independent_clusters
            or components["provenance_completeness"] < 0.80
            or components["temporal_reliability"] < 0.70
        ):
            evidence_sufficiency = EvidenceSufficiency.WEAK_EVIDENCE
        else:
            evidence_sufficiency = EvidenceSufficiency.SUFFICIENT_EVIDENCE

        # 14. Determine Overall Status (Deterministic ordering)
        if evidence_sufficiency == EvidenceSufficiency.NO_VALID_EVIDENCE:
            overall_status = ReliabilityStatus.INSUFFICIENT_EVIDENCE
            overall_score = 0.0
        elif support_strength < 0.25 and contradiction_strength > 0.0:
            # Contradiction only -> not supported
            overall_status = ReliabilityStatus.LOW
        elif evidence_sufficiency == EvidenceSufficiency.CONFLICTED_EVIDENCE or conflict_severity in (ConflictSeverity.MODERATE_CONFLICT, ConflictSeverity.STRONG_CONFLICT):
            overall_status = ReliabilityStatus.CONFLICTED
        elif evidence_sufficiency == EvidenceSufficiency.WEAK_EVIDENCE:
            # Weak evidence cannot achieve HIGH. Single-cluster uncorroborated evidence caps at MEDIUM if score is high and identity/provenance pass
            if (
                overall_score >= 0.50
                and components["identity_confidence"] >= active_config.min_identity_confidence
                and components["provenance_completeness"] >= 0.80
                and len(valid_supp_clusters) >= 1
            ):
                overall_status = ReliabilityStatus.MEDIUM
            else:
                overall_status = ReliabilityStatus.LOW
        else:
            # SUFFICIENT_EVIDENCE (at least 2 independent supporting clusters) with no material conflict
            if (
                overall_score >= 0.80
                and components["identity_confidence"] >= active_config.strong_identity_confidence
                and len(valid_supp_clusters) >= active_config.target_independent_events
            ):
                overall_status = ReliabilityStatus.HIGH
            elif overall_score >= 0.50:
                overall_status = ReliabilityStatus.MEDIUM
            else:
                overall_status = ReliabilityStatus.LOW

        # 15. Evidence-Level Breakdown
        evidence_breakdown: List[EvidenceItemAssessment] = []
        for rec in evidence_records:
            eid = rec.evidence_id
            is_dup = eid in duplicate_ids
            is_fut = is_future_map[eid]
            prov_status, root_anc, crypto_status, lineage_st = provenance_status_map[eid]

            # Compute item reliability contribution
            item_score = (
                0.35 * identity_scores[eid] +
                0.25 * temporal_scores[eid] +
                0.25 * float(getattr(rec, "evidence_quality", 1.0)) +
                0.15 * provenance_scores[eid]
            )
            if is_dup:
                item_score *= 0.5  # duplicate penalty on item level
            if is_fut:
                item_score = 0.0

            # Construct factual reason
            reason_parts = []
            if identity_scores[eid] >= active_config.strong_identity_confidence:
                reason_parts.append(f"Strong identity binding ({identity_scores[eid]:.2f}) to {canonical_entity_id}")
            elif identity_scores[eid] >= active_config.min_identity_confidence:
                reason_parts.append(f"Moderate identity binding ({identity_scores[eid]:.2f})")
            else:
                reason_parts.append(f"Unverified/ambiguous identity mapping ({identity_scores[eid]:.2f})")

            if is_fut:
                reason_parts.append(f"Post-trigger event (timestamp > trigger time {trigger_time})")
            elif temporal_scores[eid] >= 1.0:
                reason_parts.append("Valid causal temporal order")

            if crypto_status == ProvenanceIntegrityStatus.INTEGRITY_VERIFIED:
                if root_anc:
                    reason_parts.append(f"M12 cryptographic integrity verified; complete DAG lineage (root={root_anc})")
                else:
                    reason_parts.append("M12 cryptographic record integrity verified, but DAG lineage is unlinked (root=None)")
            elif crypto_status == ProvenanceIntegrityStatus.TAMPERED_RECORD_DETECTED:
                reason_parts.append("M12 cryptographic hash tampering detected")
            else:
                reason_parts.append(f"Provenance status: {prov_status}")

            if is_dup:
                reason_parts.append("Dependent copy of already-evaluated event; duplicate excluded from corroboration")

            item_reason = "; ".join(reason_parts)

            evidence_breakdown.append(EvidenceItemAssessment(
                evidence_ref=eid,
                source_domain=rec.source_domain,
                event_id=rec.event_ids[0] if rec.event_ids else "NO_EVENT",
                evidence_category=rec.evidence_category,
                identity_contribution=identity_scores[eid],
                temporal_contribution=temporal_scores[eid],
                quality_contribution=float(getattr(rec, "evidence_quality", 1.0)),
                provenance_status=prov_status,
                is_duplicate=is_dup,
                is_future_event=is_fut,
                root_ancestor_id=root_anc,
                reliability_contribution=round(item_score, 4),
                reason=item_reason,
                cryptographic_integrity=crypto_status,
                lineage_status=lineage_st
            ))

        # 16. Build Reasons and Limitations
        reasons = []
        if overall_status == ReliabilityStatus.HIGH:
            reasons.append(f"Finding is supported by {len(valid_supp_clusters)} independent cluster(s) with unbroken provenance and strong identity binding.")
        elif overall_status == ReliabilityStatus.CONFLICTED:
            reasons.append(f"Evidential conflict detected: support_strength={support_strength:.2f} vs contradiction_strength={contradiction_strength:.2f} ({conflict_severity.value}).")
            reasons.append("Contradiction is explicitly preserved under evidential rules; conflict penalty applied.")
        elif overall_status == ReliabilityStatus.INSUFFICIENT_EVIDENCE:
            reasons.append("Insufficient valid evidence bound to canonical entity to evaluate reliability.")
        else:
            # Generate reasons based strictly on actual triggered conditions
            degradations = []
            if len(valid_supp_clusters) < active_config.min_independent_clusters:
                degradations.append("insufficient independent corroboration (single event or duplicate evidence)")
            elif len(valid_supp_clusters) < active_config.target_independent_events:
                degradations.append(f"partial corroboration ({len(valid_supp_clusters)} independent cluster(s))")

            if components["identity_confidence"] < active_config.min_identity_confidence:
                degradations.append(f"ambiguous or unverified identity binding ({components['identity_confidence']:.2f})")

            if components["provenance_completeness"] < 0.80:
                degradations.append(f"incomplete/missing provenance lineage (completeness={components['provenance_completeness']:.2f})")

            if components["temporal_reliability"] < 0.70:
                degradations.append(f"temporal causality concerns or missing timestamps ({components['temporal_reliability']:.2f})")

            if contradiction_strength > 0.0:
                degradations.append(f"presence of contradictory evidence (contradiction_strength={contradiction_strength:.2f})")

            if overall_status == ReliabilityStatus.MEDIUM:
                if degradations:
                    reasons.append(f"Finding shows moderate evidential support ({overall_score:.2f}) with caveats: {'; '.join(degradations)}.")
                else:
                    reasons.append(f"Finding shows moderate evidential support ({overall_score:.2f}) with zero active contradictions.")
            else:
                # LOW
                if contradiction_strength > 0.0 and support_strength == 0.0:
                    reasons.append("Contradictory evidence exists without supporting corroboration.")
                elif degradations:
                    reasons.append(f"Reliability degraded due to: {'; '.join(degradations)}.")
                else:
                    reasons.append("Reliability degraded due to low overall evidential support.")

        limitations = [
            "Non-Calibration Disclaimer: The reliability score is a deterministic heuristic index reflecting evidential completeness, identity confidence, DAG provenance, and contradiction penalties. It is NOT a calibrated statistical probability.",
            "Case Scoping: Assessment is strictly isolated to the active case and attached finding.",
        ]
        if any(is_future_map.values()):
            limitations.append("One or more evidence items occurred after the finding trigger timestamp and were excluded from causal reliability evaluation.")
        if duplicate_ids:
            limitations.append(f"{len(duplicate_ids)} duplicate evidence item(s) detected and prevented from inflating independent corroboration.")

        return ReliabilityAssessment(
            case_id=case_id,
            finding_id=finding_id,
            canonical_entity_id=canonical_entity_id,
            overall_score=overall_score,
            overall_status=overall_status,
            evidence_sufficiency=evidence_sufficiency,
            conflict_status=conflict_status,
            conflict_severity=conflict_severity,
            support_strength=support_strength,
            contradiction_strength=contradiction_strength,
            contradiction_penalty=contradiction_penalty,
            components=components,
            supporting_evidence=[r.evidence_id for r in supporting_items],
            contradicting_evidence=[r.evidence_id for r in contradicting_items],
            unresolved_evidence=[r.evidence_id for r in unresolved_items],
            duplicate_evidence=duplicate_ids,
            evidence_breakdown=evidence_breakdown,
            reasons=reasons,
            limitations=limitations,
            algorithm_version=active_config.algorithm_version,
            configuration_version=active_config.configuration_version,
            evaluated_at=now_ts
        )

    # ── HELPER METHODS ────────────────────────────────────────────────────────

    def _build_empty_assessment(
        self,
        case_id: str,
        finding_id: str,
        canonical_entity_id: str,
        status: ReliabilityStatus,
        sufficiency: EvidenceSufficiency,
        reasons: List[str],
        config: ReliabilityConfig,
        evaluated_at: str
    ) -> ReliabilityAssessment:
        return ReliabilityAssessment(
            case_id=case_id,
            finding_id=finding_id,
            canonical_entity_id=canonical_entity_id,
            overall_score=0.0,
            overall_status=status,
            evidence_sufficiency=sufficiency,
            conflict_status="NO_CONFLICT",
            conflict_severity=ConflictSeverity.NO_CONFLICT,
            support_strength=0.0,
            contradiction_strength=0.0,
            contradiction_penalty=0.0,
            components={
                "identity_confidence": 0.0,
                "temporal_reliability": 0.0,
                "evidence_quality": 0.0,
                "corroboration_strength": 0.0,
                "data_quality": 0.0,
                "provenance_completeness": 0.0,
            },
            supporting_evidence=[],
            contradicting_evidence=[],
            unresolved_evidence=[],
            duplicate_evidence=[],
            evidence_breakdown=[],
            reasons=reasons,
            limitations=["Non-Calibration Disclaimer: Assessment reflects zero valid evidence items."],
            algorithm_version=config.algorithm_version,
            configuration_version=config.configuration_version,
            evaluated_at=evaluated_at
        )

    def _verify_record_identity(
        self,
        record: CanonicalEvidenceRecord,
        canonical_entity_id: str,
        bridge_df: pd.DataFrame
    ) -> float:
        """Verifies whether the evidence record's raw identifier authoritatively maps to canonical_entity_id."""
        # Check explicit bridge DataFrame
        if not bridge_df.empty:
            matches = bridge_df[
                (bridge_df["canonical_entity_id"] == canonical_entity_id) &
                (bridge_df["raw_identifier"] == record.source_id)
            ]
            if not matches.empty:
                return float(matches["confidence"].max())

        # Check backend in-memory alias dictionary
        if hasattr(self.backend, "_entity_alias_to_canonical"):
            mapped = self.backend._entity_alias_to_canonical.get(record.source_id)
            if mapped == canonical_entity_id:
                # If mapped in backend alias table, check record confidence or default 0.90
                return float(getattr(record, "confidence", 0.90))

        # Check record's canonical_entity_ids directly ONLY IF confirmed by backend valid entities
        if canonical_entity_id in record.canonical_entity_ids:
            if record.source_id == canonical_entity_id:
                return float(getattr(record, "confidence", 1.0))
            # If raw identifier is distinct from canonical_entity_id, fail closed to 0.0 without bridge proof!
            return 0.0

        return 0.0

    def _extract_trigger_timestamp(self, finding: Dict[str, Any]) -> Optional[float]:
        for k in ["observation_timestamp", "trigger_timestamp", "timestamp", "epoch_time"]:
            val = finding.get(k)
            if val is not None:
                parsed = self._parse_observation_timestamp(val)
                if parsed is not None:
                    return parsed
        return None

    def _parse_observation_timestamp(self, val: Any) -> Optional[float]:
        if val is None:
            return None
        if isinstance(val, (int, float)):
            return float(val)
        if isinstance(val, str):
            try:
                dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
                return dt.timestamp()
            except Exception:
                pass
            try:
                return float(val)
            except Exception:
                pass
        return None

    def _find_dag_root_ancestor(self, evidence_id: str) -> Optional[str]:
        graph = self.backend.evidence_engine.graph
        if evidence_id not in graph.nodes:
            return None

        # Traverse backwards using graph._adjacency_in
        visited = set()
        queue = [evidence_id]
        roots = []

        while queue:
            curr = queue.pop(0)
            if curr in visited:
                continue
            visited.add(curr)
            parents = graph._adjacency_in.get(curr, [])
            if not parents:
                if curr != evidence_id:
                    roots.append(curr)
            else:
                for p in parents:
                    if p not in visited:
                        queue.append(p)

        return roots[0] if roots else None

    def _cluster_evidence_dependencies(
        self,
        records: List[CanonicalEvidenceRecord]
    ) -> Tuple[List[List[str]], List[str]]:
        """
        Groups evidence into dependent clusters based on:
          1. Shared event_ids
          2. Identical evidence_hash
          3. Identical source_file and source_row_index
        Returns: (clusters, list_of_duplicate_ids)
        """
        clusters: List[List[str]] = []
        duplicate_ids: List[str] = []

        for rec in records:
            assigned = False
            rec_events = set(rec.event_ids) if rec.event_ids else set()

            for cl in clusters:
                # Compare against first item in cluster
                cl_records = [r for r in records if r.evidence_id in cl]
                for rep in cl_records:
                    rep_events = set(rep.event_ids) if rep.event_ids else set()
                    shares_event = bool(rec_events and rep_events and (rec_events & rep_events))
                    shares_hash = (rec.evidence_hash == rep.evidence_hash)
                    shares_location = (
                        rec.source_file == rep.source_file and
                        rec.source_row_index == rep.source_row_index and
                        rec.source_row_index >= 0
                    )
                    if shares_event or shares_hash or shares_location:
                        cl.append(rec.evidence_id)
                        duplicate_ids.append(rec.evidence_id)
                        assigned = True
                        break
                if assigned:
                    break

            if not assigned:
                clusters.append([rec.evidence_id])

        return clusters, duplicate_ids

    def _assess_record_data_quality(self, record: CanonicalEvidenceRecord) -> float:
        """Evaluates completeness of source fields and hash integrity."""
        score = 1.0
        if not record.source_file or record.source_file == "UNKNOWN":
            score -= 0.20
        if record.source_row_index < 0:
            score -= 0.10
        if not record.observation_timestamp:
            score -= 0.20
        if not record.evidence_hash or len(record.evidence_hash) != 64:
            score -= 0.50
        return float(np.clip(score, 0.0, 1.0))
