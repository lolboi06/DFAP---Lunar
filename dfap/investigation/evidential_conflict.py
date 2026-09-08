# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: M11 Evidential Conflict Intelligence (BetP, Hellinger Distance, Belief Vector Cosine & Compound Conflict)

import math
from typing import Any, Dict, List, Optional, Tuple, Union
import numpy as np


class EvidentialConflictStatus:
    NO_MATERIAL_CONFLICT = "NO_MATERIAL_CONFLICT"
    MATERIAL_CONFLICT = "MATERIAL_CONFLICT"
    ABSTENTION_REQUIRED = "ABSTENTION_REQUIRED"


class EvidentialRequiredAction:
    PROCEED = "PROCEED"
    REVIEW_DISCREPANCY = "REVIEW_DISCREPANCY"
    HUMAN_REVIEW = "HUMAN_REVIEW"


DEFAULT_EVIDENTIAL_CONFLICT_THRESHOLDS = {
    "material_conflict_threshold": 0.25,
    "abstention_conflict_threshold": 0.38,
}

# Deterministic hypothesis frame singletons and focal elements
FRAME_SINGLETONS = ("ANOMALOUS", "NORMAL")
FOCAL_ELEMENTS = ("ANOMALOUS", "NORMAL", "THETA")


def normalize_mass_vector(
    mass: Union[Tuple[float, float, float], List[float], Dict[str, float], float, int],
    sensitivity: float = 0.8
) -> Tuple[float, float, float]:
    """
    Normalizes input mass into an authoritative 3-element tuple (m_A, m_N, m_Theta).
    Deterministic focal ordering: [ANOMALOUS, NORMAL, THETA].
    Handles raw floats (anomaly scores), dicts, and tuples safely.
    Zero-vector / degenerate cases return (0.0, 0.0, 0.0).
    """
    if mass is None:
        return (0.0, 0.0, 1.0)

    # If raw float or int score in [0, 1]
    if isinstance(mass, (int, float)):
        s = float(np.clip(mass, 0.0, 1.0))
        m_a = s * sensitivity
        m_n = (1.0 - s) * sensitivity
        m_theta = 1.0 - sensitivity
        return (round(m_a, 6), round(m_n, 6), round(m_theta, 6))

    # If dict
    if isinstance(mass, dict):
        # Check if direct mass keys exist
        m_a = mass.get("ANOMALOUS", mass.get("A", mass.get("anomalous", None)))
        m_n = mass.get("NORMAL", mass.get("N", mass.get("normal", None)))
        m_t = mass.get("THETA", mass.get("T", mass.get("theta", mass.get("omega", None))))

        if m_a is not None or m_n is not None or m_t is not None:
            ma_val = float(max(0.0, m_a or 0.0))
            mn_val = float(max(0.0, m_n or 0.0))
            mt_val = float(max(0.0, m_t or 0.0))
            s = ma_val + mn_val + mt_val
            if s < 1e-12:
                return (0.0, 0.0, 0.0)
            return (round(ma_val / s, 6), round(mn_val / s, 6), round(mt_val / s, 6))

        # Check if anomaly score exists in dict
        score = mass.get("anomaly_score", mass.get("score", None))
        if score is not None:
            return normalize_mass_vector(float(score), sensitivity=sensitivity)

        # Fallback empty
        return (0.0, 0.0, 1.0)

    # If tuple / list
    if isinstance(mass, (list, tuple)):
        if len(mass) == 3:
            ma_val = float(max(0.0, mass[0]))
            mn_val = float(max(0.0, mass[1]))
            mt_val = float(max(0.0, mass[2]))
            s = ma_val + mn_val + mt_val
            if s < 1e-12:
                return (0.0, 0.0, 0.0)
            return (round(ma_val / s, 6), round(mn_val / s, 6), round(mt_val / s, 6))
        elif len(mass) == 2:
            ma_val = float(max(0.0, mass[0]))
            mn_val = float(max(0.0, mass[1]))
            mt_val = 0.0
            s = ma_val + mn_val
            if s < 1e-12:
                return (0.0, 0.0, 0.0)
            return (round(ma_val / s, 6), round(mn_val / s, 6), 0.0)

    return (0.0, 0.0, 1.0)


def compute_betp(
    mass: Union[Tuple[float, float, float], List[float], Dict[str, float], float, int],
    sensitivity: float = 0.8
) -> Dict[str, float]:
    """
    Computes pignistic probability distribution (BetP) over frame Theta = {ANOMALOUS, NORMAL}.
    BetP(k) = sum_{F contains k} m(F) / (|F| * (1 - m(empty)))
    For binary frame:
      BetP(ANOMALOUS) = m(ANOMALOUS) + 0.5 * m(THETA)
      BetP(NORMAL)    = m(NORMAL) + 0.5 * m(THETA)
    Degenerate / zero vectors return uniform BetP [0.5, 0.5].
    Guarantees sum(BetP) == 1.0, non-negative, bounded in [0.0, 1.0].
    """
    m_a, m_n, m_t = normalize_mass_vector(mass, sensitivity=sensitivity)
    s = m_a + m_n + m_t

    if s < 1e-12:
        return {"ANOMALOUS": 0.5, "NORMAL": 0.5}

    betp_a = m_a + 0.5 * m_t
    betp_n = m_n + 0.5 * m_t

    tot = betp_a + betp_n
    if tot < 1e-12:
        return {"ANOMALOUS": 0.5, "NORMAL": 0.5}

    betp_a = float(np.clip(betp_a / tot, 0.0, 1.0))
    betp_n = float(np.clip(1.0 - betp_a, 0.0, 1.0))

    return {
        "ANOMALOUS": round(betp_a, 4),
        "NORMAL": round(betp_n, 4)
    }


def compute_hellinger_distance(
    betp_a: Dict[str, float],
    betp_b: Dict[str, float]
) -> float:
    """
    Computes Hellinger distance between two discrete pignistic probability distributions:
      d_H(P, Q) = (1 / sqrt(2)) * sqrt( sum_k (sqrt(P(k)) - sqrt(Q(k)))^2 )
    Properties:
      - 0.0 <= d_H <= 1.0
      - d_H = 0.0 for identical distributions
      - d_H = 1.0 for disjoint / orthogonal distributions
    Guarantees zero NaN / Inf leakage.
    """
    diff_sq_sum = 0.0
    for k in FRAME_SINGLETONS:
        pa = max(0.0, float(betp_a.get(k, 0.5)))
        pb = max(0.0, float(betp_b.get(k, 0.5)))
        diff_sq_sum += (math.sqrt(pa) - math.sqrt(pb)) ** 2

    raw_dist = (1.0 / math.sqrt(2.0)) * math.sqrt(diff_sq_sum)
    clamped = float(np.clip(raw_dist, 0.0, 1.0))
    return round(clamped, 4)


def compute_belief_vector_cosine(
    mass_a: Union[Tuple[float, float, float], List[float], Dict[str, float], float, int],
    mass_b: Union[Tuple[float, float, float], List[float], Dict[str, float], float, int],
    sensitivity: float = 0.8
) -> float:
    """
    Computes cosine similarity between two belief mass vectors over ordered frame:
      cos(theta_ij) = (m_i . m_j) / (||m_i|| * ||m_j||)
    Safe handling:
      - Both zero-vectors: returns 1.0 (no angular divergence)
      - One zero-vector: returns 0.0
      - Bounded strictly in [-1.0, 1.0] (and >= 0.0 for non-negative mass vectors)
    """
    va = list(normalize_mass_vector(mass_a, sensitivity=sensitivity))
    vb = list(normalize_mass_vector(mass_b, sensitivity=sensitivity))

    norm_a = math.sqrt(sum(x * x for x in va))
    norm_b = math.sqrt(sum(x * x for x in vb))

    if norm_a < 1e-12 and norm_b < 1e-12:
        return 1.0
    if norm_a < 1e-12 or norm_b < 1e-12:
        return 0.0

    dot = sum(a * b for a, b in zip(va, vb))
    raw_cos = dot / (norm_a * norm_b)
    clamped = float(np.clip(raw_cos, -1.0, 1.0))
    return round(clamped, 4)


def compute_compound_conflict(
    hellinger_dist: float,
    belief_cosine: float
) -> float:
    """
    Computes compound conflict metric combining distributional Hellinger separation
    with geometric belief vector angular divergence:
      Conf_ij = d_H * (1.0 - cos(theta_ij))
    Bounded strictly in [0.0, 1.0].
    """
    dist = float(np.clip(hellinger_dist, 0.0, 1.0))
    cos_val = float(np.clip(belief_cosine, -1.0, 1.0))
    raw_conf = dist * (1.0 - cos_val)
    clamped = float(np.clip(raw_conf, 0.0, 1.0))
    return round(clamped, 4)


def analyze_domain_pair(
    domain_a: str,
    mass_a: Any,
    domain_b: str,
    mass_b: Any,
    thresholds: Optional[Dict[str, float]] = None,
    sensitivity: float = 0.8
) -> Dict[str, Any]:
    """
    Performs deterministic evidential conflict analysis for a pair of domains.
    Returns structured conflict result containing BetP distributions, Hellinger distance,
    belief vector cosine, compound conflict, conflict status, and recommended action.
    """
    thresh = dict(DEFAULT_EVIDENTIAL_CONFLICT_THRESHOLDS)
    if thresholds:
        thresh.update(thresholds)

    mat_thresh = thresh.get("material_conflict_threshold", 0.25)
    abst_thresh = thresh.get("abstention_conflict_threshold", 0.38)

    # 1. Pignistic Probability
    betp_a = compute_betp(mass_a, sensitivity=sensitivity)
    betp_b = compute_betp(mass_b, sensitivity=sensitivity)

    # 2. Hellinger Distance
    d_h = compute_hellinger_distance(betp_a, betp_b)

    # 3. Belief Vector Cosine
    cos_sim = compute_belief_vector_cosine(mass_a, mass_b, sensitivity=sensitivity)

    # 4. Compound Conflict
    conf = compute_compound_conflict(d_h, cos_sim)

    # 5. Determine Status & Required Action
    if conf >= abst_thresh:
        status = EvidentialConflictStatus.ABSTENTION_REQUIRED
        action = EvidentialRequiredAction.HUMAN_REVIEW
    elif conf >= mat_thresh:
        status = EvidentialConflictStatus.MATERIAL_CONFLICT
        action = EvidentialRequiredAction.REVIEW_DISCREPANCY
    else:
        status = EvidentialConflictStatus.NO_MATERIAL_CONFLICT
        action = EvidentialRequiredAction.PROCEED

    # 6. Build Objective, Grounded Explanation (Strictly Free of Crime/Fraud/Guilt Claims)
    norm_va = list(normalize_mass_vector(mass_a, sensitivity=sensitivity))
    norm_vb = list(normalize_mass_vector(mass_b, sensitivity=sensitivity))

    explanation = (
        f"Evidential conflict analysis between domain '{domain_a}' and domain '{domain_b}': "
        f"Pignistic distribution BetP({domain_a})=[ANOMALOUS: {betp_a['ANOMALOUS']:.2f}, NORMAL: {betp_a['NORMAL']:.2f}] "
        f"vs BetP({domain_b})=[ANOMALOUS: {betp_b['ANOMALOUS']:.2f}, NORMAL: {betp_b['NORMAL']:.2f}]. "
        f"Hellinger distance is {d_h:.4f} and belief vector cosine similarity is {cos_sim:.4f}, "
        f"yielding a compound conflict score of {conf:.4f} (status: {status}). "
    )
    if status == EvidentialConflictStatus.ABSTENTION_REQUIRED:
        explanation += (
            f"Compound conflict exceeds the abstention threshold ({abst_thresh:.2f}). "
            f"Independent domain signals diverge substantially; evidential combination requires human review "
            f"rather than automated consensus."
        )
    elif status == EvidentialConflictStatus.MATERIAL_CONFLICT:
        explanation += (
            f"Compound conflict exceeds the material threshold ({mat_thresh:.2f}). "
            f"Domain divergence is notable and warrants discrepancy review."
        )
    else:
        explanation += (
            f"Compound conflict is within acceptable bounds (< {mat_thresh:.2f}). "
            f"Domain evidence exhibits acceptable directional concordance."
        )

    return {
        "domain_a": domain_a,
        "domain_b": domain_b,
        "hellinger_distance": d_h,
        "belief_vector_cosine": cos_sim,
        "compound_conflict": conf,
        "conflict_status": status,
        "explanation": explanation,
        "threshold_used": {
            "material_conflict_threshold": mat_thresh,
            "abstention_conflict_threshold": abst_thresh
        },
        "required_action": action,
        "betp_a": betp_a,
        "betp_b": betp_b,
        "mass_vector_a": norm_va,
        "mass_vector_b": norm_vb
    }


class EvidentialConflictAnalyzer:
    """
    Dedicated Evidential Conflict Analysis Engine for M11 Cross-Domain Fusion.
    Evaluates multi-domain evidential disagreement using pignistic probability (BetP),
    Hellinger distance, and belief mass vector cosine similarity.
    """

    def __init__(self, thresholds: Optional[Dict[str, float]] = None, sensitivity: float = 0.8):
        self.thresholds = dict(DEFAULT_EVIDENTIAL_CONFLICT_THRESHOLDS)
        if thresholds:
            self.thresholds.update(thresholds)
        self.sensitivity = sensitivity

    def analyze_pair(
        self,
        domain_a: str,
        mass_a: Any,
        domain_b: str,
        mass_b: Any
    ) -> Dict[str, Any]:
        """Analyzes a single pair of domains."""
        return analyze_domain_pair(
            domain_a=domain_a,
            mass_a=mass_a,
            domain_b=domain_b,
            mass_b=mass_b,
            thresholds=self.thresholds,
            sensitivity=self.sensitivity
        )

    def analyze_domains(
        self,
        domain_masses: Dict[str, Any],
        thresholds: Optional[Dict[str, float]] = None,
        sensitivity: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Analyzes all pairwise combinations across multiple domains.
        Returns aggregate summary including worst-pair conflict, overall status,
        and human review flags.
        """
        active_thresh = dict(self.thresholds)
        if thresholds:
            active_thresh.update(thresholds)

        active_sens = sensitivity if sensitivity is not None else self.sensitivity

        domains = sorted(list(domain_masses.keys()))
        if len(domains) < 2:
            return {
                "overall_status": EvidentialConflictStatus.NO_MATERIAL_CONFLICT,
                "max_compound_conflict": 0.0,
                "worst_pair": None,
                "requires_human_review": False,
                "abstention_required": False,
                "required_action": EvidentialRequiredAction.PROCEED,
                "pairwise_conflicts": [],
                "thresholds_used": active_thresh,
                "explanation": "Insufficient distinct domains (< 2) for cross-domain evidential conflict analysis."
            }

        pairwise_results = []
        max_conflict = -1.0
        worst_pair = None
        has_abstention = False
        has_material = False

        for i in range(len(domains)):
            for j in range(i + 1, len(domains)):
                da = domains[i]
                db = domains[j]
                res = analyze_domain_pair(
                    domain_a=da,
                    mass_a=domain_masses[da],
                    domain_b=db,
                    mass_b=domain_masses[db],
                    thresholds=active_thresh,
                    sensitivity=active_sens
                )
                pairwise_results.append(res)
                if res["compound_conflict"] > max_conflict:
                    max_conflict = res["compound_conflict"]
                    worst_pair = (da, db)

                if res["conflict_status"] == EvidentialConflictStatus.ABSTENTION_REQUIRED:
                    has_abstention = True
                elif res["conflict_status"] == EvidentialConflictStatus.MATERIAL_CONFLICT:
                    has_material = True

        if has_abstention:
            overall_status = EvidentialConflictStatus.ABSTENTION_REQUIRED
            required_action = EvidentialRequiredAction.HUMAN_REVIEW
            requires_human_review = True
            abstention_required = True
        elif has_material:
            overall_status = EvidentialConflictStatus.MATERIAL_CONFLICT
            required_action = EvidentialRequiredAction.REVIEW_DISCREPANCY
            requires_human_review = False
            abstention_required = False
        else:
            overall_status = EvidentialConflictStatus.NO_MATERIAL_CONFLICT
            required_action = EvidentialRequiredAction.PROCEED
            requires_human_review = False
            abstention_required = False

        explanation = (
            f"Cross-domain evidential conflict evaluation across {len(domains)} domains "
            f"({', '.join(domains)}): Overall status is '{overall_status}'. "
            f"Maximum compound conflict observed is {max_conflict:.4f} between '{worst_pair[0]}' and '{worst_pair[1]}'. "
        )
        if requires_human_review:
            explanation += (
                f"Severe cross-domain divergence between '{worst_pair[0]}' and '{worst_pair[1]}' exceeds the "
                f"abstention threshold ({active_thresh.get('abstention_conflict_threshold', 0.38):.2f}). "
                f"Automated fusion is abstained; manual human review is required."
            )
        elif has_material:
            explanation += (
                f"Material cross-domain divergence is present between '{worst_pair[0]}' and '{worst_pair[1]}'. "
                f"Discrepancy review is advised."
            )
        else:
            explanation += "No material conflict detected across analyzed domains."

        return {
            "overall_status": overall_status,
            "max_compound_conflict": round(max_conflict, 4),
            "worst_pair": worst_pair,
            "requires_human_review": requires_human_review,
            "abstention_required": abstention_required,
            "required_action": required_action,
            "pairwise_conflicts": pairwise_results,
            "thresholds_used": active_thresh,
            "explanation": explanation
        }
