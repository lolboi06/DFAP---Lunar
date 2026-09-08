# Author: Sam Roger X
# Component: DFAP Paper 1 Evaluation Harness
# Scope: Controlled Synthetic Case Bank for Paper 1 (Forced Abstention Disclosure Evaluation)

from typing import Dict, Any, List
from dfap.experiments.paper1_models import GroundTruthLabel


def get_paper1_case_bank() -> List[Dict[str, Any]]:
    """
    Returns the standardized 7-case synthetic benchmark bank.
    All data is strictly synthetic; zero citizen records, zero PII.
    
    Covers the required matrix:
    1. WELL_SUPPORTED non-abstained finding
    2. WEAKLY_SUPPORTED non-abstained finding
    3. CONFLICTED finding where M11 abstains (Ground truth = WEAKLY_SUPPORTED)
    4. CONFLICTED finding with strong evidence in one domain (Ground truth = WELL_SUPPORTED)
    5. CONFLICTED finding with strong contradictory evidence across domains (Ground truth = WEAKLY_SUPPORTED)
    6. Non-abstained finding that is genuinely well-supported
    7. Non-abstained finding that is weakly-supported
    """
    cases: List[Dict[str, Any]] = [
        {
            "case_id": "CASE_P1_01",
            "finding_id": "FND_P1_001",
            "title": "Corroborated Telemetry and Transaction Structuring",
            "entity_id": "ENT_SYNTHETIC_ALPHA_01",
            "ground_truth": GroundTruthLabel.WELL_SUPPORTED,
            "ground_truth_rationale": "High-confidence multi-domain corroboration across CDR telephony and financial accounting logs.",
            "score": 0.88,
            "status_summary": "Cross-domain activity corroborated across financial and telecom domains.",
            "m11_state": {
                "overall_status": "FUSION_PERMITTED",
                "corroboration_score": 0.88,
                "conflict_status": "NORMAL",
                "hellinger_distance": 0.12,
            },
            "evidence_items": [
                {
                    "evidence_id": "EVD_P1_FIN_001",
                    "domain": "FINANCIAL",
                    "description": "Four sub-threshold wire transfers structured under $10,000 within 48 hours.",
                    "confidence": 0.92,
                },
                {
                    "evidence_id": "EVD_P1_CDR_001",
                    "domain": "CDR",
                    "description": "Burst of 14 encrypted voice calls immediately preceding each financial disbursement.",
                    "confidence": 0.86,
                }
            ],
            "claims": [
                {
                    "claim_id": "CLM_P1_001_1",
                    "text": "Structured cash disbursements detected across commercial bank accounts.",
                    "claim_type": "DIRECTLY_EVIDENCED",
                    "evidence_refs": ["EVD_P1_FIN_001"],
                },
                {
                    "claim_id": "CLM_P1_001_2",
                    "text": "Telephony activity temporally coincides with transaction dispatches.",
                    "claim_type": "AI_SYNTHESIZED",
                    "evidence_refs": ["EVD_P1_CDR_001"],
                }
            ]
        },
        {
            "case_id": "CASE_P1_02",
            "finding_id": "FND_P1_002",
            "title": "Isolated Ephemeral Telemetry Ping",
            "entity_id": "ENT_SYNTHETIC_BETA_02",
            "ground_truth": GroundTruthLabel.WEAKLY_SUPPORTED,
            "ground_truth_rationale": "Single transient network event with zero persistence or financial connection.",
            "score": 0.25,
            "status_summary": "Weak transient signal with low persistence.",
            "m11_state": {
                "overall_status": "FUSION_PERMITTED",
                "corroboration_score": 0.25,
                "conflict_status": "WEAK_SIGNAL",
                "hellinger_distance": 0.08,
            },
            "evidence_items": [
                {
                    "evidence_id": "EVD_P1_IPDR_002",
                    "domain": "IPDR",
                    "description": "Single outbound TCP SYN packet to unverified external server.",
                    "confidence": 0.30,
                }
            ],
            "claims": [
                {
                    "claim_id": "CLM_P1_002_1",
                    "text": "Isolated network connection detected without secondary telemetry confirmation.",
                    "claim_type": "DIRECTLY_EVIDENCED",
                    "evidence_refs": ["EVD_P1_IPDR_002"],
                }
            ]
        },
        {
            "case_id": "CASE_P1_03",
            "finding_id": "FND_P1_003",
            "title": "Contradictory Evidential Signals (Alibi vs Transaction)",
            "entity_id": "ENT_SYNTHETIC_GAMMA_03",
            "ground_truth": GroundTruthLabel.WEAKLY_SUPPORTED,
            "ground_truth_rationale": "Suspect account was compromised; authoritative cell-tower alibi proves entity was not involved.",
            "score": 0.40,
            "status_summary": "Irreconcilable contradiction between financial records and cellular alibi.",
            "m11_state": {
                "overall_status": "ABSTENTION_REQUIRED",
                "corroboration_score": 0.40,
                "conflict_status": "CONFLICTED",
                "hellinger_distance": 0.82,
            },
            "evidence_items": [
                {
                    "evidence_id": "EVD_P1_FIN_003",
                    "domain": "FINANCIAL",
                    "description": "Automated debit activity recorded in region X.",
                    "confidence": 0.90,
                },
                {
                    "evidence_id": "EVD_P1_CDR_003",
                    "domain": "CDR",
                    "description": "Continuous cell tower connectivity establishes presence 800 miles away in region Y.",
                    "confidence": 0.94,
                }
            ],
            "claims": [
                {
                    "claim_id": "CLM_P1_003_1",
                    "text": "Debit withdrawal initiated from terminal in region X.",
                    "claim_type": "DIRECTLY_EVIDENCED",
                    "evidence_refs": ["EVD_P1_FIN_003"],
                }
            ]
        },
        {
            "case_id": "CASE_P1_04",
            "finding_id": "FND_P1_004",
            "title": "Strong Forensic Financial Accounting vs Silent Telecom Domain",
            "entity_id": "ENT_SYNTHETIC_DELTA_04",
            "ground_truth": GroundTruthLabel.WELL_SUPPORTED,
            "ground_truth_rationale": "Forensic ledger documentation conclusively proves systematic fraud; perpetrator used air-gapped terminal with no telecom trace.",
            "score": 0.50,
            "status_summary": "Domain divergence: Strong financial anomaly with absent cellular corroboration.",
            "m11_state": {
                "overall_status": "ABSTENTION_REQUIRED",
                "corroboration_score": 0.50,
                "conflict_status": "CONFLICTED",
                "hellinger_distance": 0.74,
            },
            "evidence_items": [
                {
                    "evidence_id": "EVD_P1_FIN_004",
                    "domain": "FINANCIAL",
                    "description": "Certified bank ledgers establish $450,000 diversion across 9 dummy vendor accounts.",
                    "confidence": 0.98,
                },
                {
                    "evidence_id": "EVD_P1_CDR_004",
                    "domain": "CDR",
                    "description": "No telecommunication logs matching counterparties during period.",
                    "confidence": 0.85,
                }
            ],
            "claims": [
                {
                    "claim_id": "CLM_P1_004_1",
                    "text": "Direct diversion of vendor disbursements confirmed by certified audit ledgers.",
                    "claim_type": "DIRECTLY_EVIDENCED",
                    "evidence_refs": ["EVD_P1_FIN_004"],
                }
            ]
        },
        {
            "case_id": "CASE_P1_05",
            "finding_id": "FND_P1_005",
            "title": "Equally Conflicting Evidential Vectors",
            "entity_id": "ENT_SYNTHETIC_EPSILON_05",
            "ground_truth": GroundTruthLabel.WEAKLY_SUPPORTED,
            "ground_truth_rationale": "High conflict between synthetic social accusation and verified corporate registry verification.",
            "score": 0.45,
            "status_summary": "High cross-domain discordance between social claims and verified public records.",
            "m11_state": {
                "overall_status": "ABSTENTION_REQUIRED",
                "corroboration_score": 0.45,
                "conflict_status": "CONFLICTED",
                "hellinger_distance": 0.79,
            },
            "evidence_items": [
                {
                    "evidence_id": "EVD_P1_SOC_005",
                    "domain": "SOCIAL",
                    "description": "Public allegations claiming unauthorized entity ownership.",
                    "confidence": 0.65,
                },
                {
                    "evidence_id": "EVD_P1_REG_005",
                    "domain": "CORPORATE",
                    "description": "Verified Ministry corporate filing records third-party sole proprietorship.",
                    "confidence": 0.95,
                }
            ],
            "claims": [
                {
                    "claim_id": "CLM_P1_005_1",
                    "text": "Unverified social media attribution links entity to offshore holding.",
                    "claim_type": "DIRECTLY_EVIDENCED",
                    "evidence_refs": ["EVD_P1_SOC_005"],
                }
            ]
        },
        {
            "case_id": "CASE_P1_06",
            "finding_id": "FND_P1_006",
            "title": "Monotonic Causal Sequence Triangulation",
            "entity_id": "ENT_SYNTHETIC_ZETA_06",
            "ground_truth": GroundTruthLabel.WELL_SUPPORTED,
            "ground_truth_rationale": "Triangulated causal progression: Authentication -> API transfer -> Disbursement.",
            "score": 0.94,
            "status_summary": "Strong monotonic causal sequence across three authoritative systems.",
            "m11_state": {
                "overall_status": "FUSION_PERMITTED",
                "corroboration_score": 0.94,
                "conflict_status": "NORMAL",
                "hellinger_distance": 0.05,
            },
            "evidence_items": [
                {
                    "evidence_id": "EVD_P1_IPDR_006",
                    "domain": "IPDR",
                    "description": "Multi-factor authentication session from corporate static IP.",
                    "confidence": 0.95,
                },
                {
                    "evidence_id": "EVD_P1_FIN_006",
                    "domain": "FINANCIAL",
                    "description": "Authorized ledger entry matching MFA session ID exactly.",
                    "confidence": 0.98,
                }
            ],
            "claims": [
                {
                    "claim_id": "CLM_P1_006_1",
                    "text": "Static IP authentication directly initiated financial settlement.",
                    "claim_type": "DIRECTLY_EVIDENCED",
                    "evidence_refs": ["EVD_P1_IPDR_006", "EVD_P1_FIN_006"],
                }
            ]
        },
        {
            "case_id": "CASE_P1_07",
            "finding_id": "FND_P1_007",
            "title": "Distant Graph Association with No Behavioral Correlation",
            "entity_id": "ENT_SYNTHETIC_ETA_07",
            "ground_truth": GroundTruthLabel.WEAKLY_SUPPORTED,
            "ground_truth_rationale": "Graph proximity without any observed direct interactions or financial ties.",
            "score": 0.30,
            "status_summary": "Distant graph community proximity with zero direct corroboration.",
            "m11_state": {
                "overall_status": "FUSION_PERMITTED",
                "corroboration_score": 0.30,
                "conflict_status": "WEAK_SIGNAL",
                "hellinger_distance": 0.15,
            },
            "evidence_items": [
                {
                    "evidence_id": "EVD_P1_NET_007",
                    "domain": "GRAPH",
                    "description": "Entity appears 3 hops away in historical telecom contact tree.",
                    "confidence": 0.35,
                }
            ],
            "claims": [
                {
                    "claim_id": "CLM_P1_007_1",
                    "text": "Peripheral graph co-occurrence without direct interaction.",
                    "claim_type": "DIRECTLY_EVIDENCED",
                    "evidence_refs": ["EVD_P1_NET_007"],
                }
            ]
        }
    ]
    return cases
