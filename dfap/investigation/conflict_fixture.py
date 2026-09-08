# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: Synthetic Contradiction & Conflict Resolution Fixture (Test 8)

import hashlib
import pandas as pd
from typing import Dict, Any, List, Optional

from dfap.investigation.workspace import InvestigationWorkspaceBackend, CaseStatus
from dfap.investigation.evidence_provenance import CanonicalEvidenceRecord, EvidenceStatus
from dfap.investigation.cross_domain_fusion import CrossDomainFusionEngine, ConflictStatus


CASE_CONFLICT_ID = "CASE-CONFLICT-001"
CONFLICT_ENTITY_ID = "ENT_SYNTHETIC_CONFLICT_001"
SUPPORT_EVID_ID = "EVID-CONFLICT-SUPPORT-001"
CONTRA_EVID_ID = "EVID-CONFLICT-CONTRA-001"
NEUTRAL_EVID_ID = "EVID-CONFLICT-NEUTRAL-001"
CONFLICT_FINDING_ID = "FND_CONFLICT_001"

SUPPORT_PROV_REF = "prov:conflict_support_001"
CONTRA_PROV_REF = "prov:conflict_contra_001"
NEUTRAL_PROV_REF = "prov:conflict_neutral_001"


def create_contradiction_evidence_records() -> List[CanonicalEvidenceRecord]:
    """Creates the certified M12 evidence records for Test 8."""
    r1 = CanonicalEvidenceRecord(
        evidence_type="ANOMALY_DETECTION",
        source_domain="FINANCIAL",
        source_id="WALLET_CONFLICT_SUPPORT_001",
        source_file="synthetic_conflict_financial.parquet",
        source_row_index=0,
        canonical_entity_ids=[CONFLICT_ENTITY_ID],
        event_ids=["EVT_CONFLICT_SUPPORT_001"],
        observation_timestamp=1700050000.0,
        ingestion_timestamp="2026-09-05T00:00:00Z",
        derivation_method="BEHAVIORAL_ANOMALY_DETECTOR",
        confidence=0.95,
        evidence_category="SUPPORTING",
        evidence_id=SUPPORT_EVID_ID,
        metadata={
            "provenance_ref": SUPPORT_PROV_REF,
            "anomaly_score": 0.92,
            "hypothesis": "High velocity structuring across accounts",
            "signal": "Rapid layer transfers indicating structuring activity"
        }
    )
    r1.provenance_ref = SUPPORT_PROV_REF

    r2 = CanonicalEvidenceRecord(
        evidence_type="BEHAVIORAL_BASELINE",
        source_domain="SOCIAL",
        source_id="SO_CONFLICT_CONTRA_001",
        source_file="synthetic_conflict_social.parquet",
        source_row_index=0,
        canonical_entity_ids=[CONFLICT_ENTITY_ID],
        event_ids=["EVT_CONFLICT_CONTRA_001"],
        observation_timestamp=1700050010.0,
        ingestion_timestamp="2026-09-05T00:00:00Z",
        derivation_method="SOCIAL_BASELINE_PROFILER",
        confidence=0.90,
        evidence_category="CONTRADICTING",
        evidence_id=CONTRA_EVID_ID,
        metadata={
            "provenance_ref": CONTRA_PROV_REF,
            "anomaly_score": 0.08,
            "hypothesis": "Authentic organic personal engagement inconsistent with illicit activity",
            "signal": "Longstanding normal community interaction profile"
        }
    )
    r2.provenance_ref = CONTRA_PROV_REF

    r3 = CanonicalEvidenceRecord(
        evidence_type="TELEMETRY_LOG",
        source_domain="IPDR",
        source_id="IP_CONFLICT_NEUTRAL_001",
        source_file="synthetic_conflict_ipdr.parquet",
        source_row_index=0,
        canonical_entity_ids=[CONFLICT_ENTITY_ID],
        event_ids=["EVT_CONFLICT_NEUTRAL_001"],
        observation_timestamp=1700050020.0,
        ingestion_timestamp="2026-09-05T00:00:00Z",
        derivation_method="IPDR_TELEMETRY_MONITOR",
        confidence=0.85,
        evidence_category="CONTEXTUAL",
        evidence_id=NEUTRAL_EVID_ID,
        metadata={
            "provenance_ref": NEUTRAL_PROV_REF,
            "anomaly_score": 0.40,
            "signal": "Neutral IP telemetry records without anomaly signature"
        }
    )
    r3.provenance_ref = NEUTRAL_PROV_REF

    return [r1, r2, r3]


def run_m11_contradiction_fusion() -> Dict[str, Any]:
    """Runs genuine M11 cross-domain fusion on the contradictory evidence items."""
    fusion_engine = CrossDomainFusionEngine(identity_bridge_path="data/cases/identity_bridge.parquet")

    bridge_rows = [
        {
            "case_id": CASE_CONFLICT_ID,
            "canonical_entity_id": CONFLICT_ENTITY_ID,
            "domain": "FINANCIAL",
            "raw_identifier": "WALLET_CONFLICT_SUPPORT_001",
            "mapping_method": "CONTROLLED_CASE_MAPPING",
            "confidence": 0.95,
            "evidence_ref": "ref:bridge_conflict_fin"
        },
        {
            "case_id": CASE_CONFLICT_ID,
            "canonical_entity_id": CONFLICT_ENTITY_ID,
            "domain": "SOCIAL",
            "raw_identifier": "SO_CONFLICT_CONTRA_001",
            "mapping_method": "CONTROLLED_CASE_MAPPING",
            "confidence": 0.90,
            "evidence_ref": "ref:bridge_conflict_soc"
        },
        {
            "case_id": CASE_CONFLICT_ID,
            "canonical_entity_id": CONFLICT_ENTITY_ID,
            "domain": "IPDR",
            "raw_identifier": "IP_CONFLICT_NEUTRAL_001",
            "mapping_method": "CONTROLLED_CASE_MAPPING",
            "confidence": 0.85,
            "evidence_ref": "ref:bridge_conflict_ipdr"
        }
    ]
    df_bridge = pd.DataFrame(bridge_rows)
    fusion_engine.bridge_df = pd.concat([fusion_engine.bridge_df, df_bridge], ignore_index=True)

    domain_items = [
        {
            "finding_id": "FND_CONFLICT_FIN",
            "source_domain": "FINANCIAL",
            "raw_identifier": "WALLET_CONFLICT_SUPPORT_001",
            "anomaly_score": 0.92,
            "epoch_time": 1700050000.0,
            "event_id": "EVT_CONFLICT_SUPPORT_001",
            "evidence_ref": SUPPORT_EVID_ID
        },
        {
            "finding_id": "FND_CONFLICT_SOC",
            "source_domain": "SOCIAL",
            "raw_identifier": "SO_CONFLICT_CONTRA_001",
            "anomaly_score": 0.08,
            "epoch_time": 1700050010.0,
            "event_id": "EVT_CONFLICT_CONTRA_001",
            "evidence_ref": CONTRA_EVID_ID
        },
        {
            "finding_id": "FND_CONFLICT_IPDR",
            "source_domain": "IPDR",
            "raw_identifier": "IP_CONFLICT_NEUTRAL_001",
            "anomaly_score": 0.40,
            "epoch_time": 1700050020.0,
            "event_id": "EVT_CONFLICT_NEUTRAL_001",
            "evidence_ref": NEUTRAL_EVID_ID
        }
    ]

    fusion_result = fusion_engine.fuse_for_entity(
        canonical_entity_id=CONFLICT_ENTITY_ID,
        domain_evidence_items=domain_items,
        temporal_window_name="MODERATE"
    )
    return fusion_result


def register_contradiction_fixture(backend: InvestigationWorkspaceBackend) -> Dict[str, Any]:
    """
    Registers CASE-CONFLICT-001, its canonical entity, evidence records, findings,
    and provenance graph edges into the backend.
    """
    # 1. Register canonical entity
    backend.valid_entities.add(CONFLICT_ENTITY_ID)
    backend._entity_alias_to_canonical[CONFLICT_ENTITY_ID] = CONFLICT_ENTITY_ID
    backend._entity_alias_to_canonical["WALLET_CONFLICT_SUPPORT_001"] = CONFLICT_ENTITY_ID
    backend._entity_alias_to_canonical["SO_CONFLICT_CONTRA_001"] = CONFLICT_ENTITY_ID
    backend._entity_alias_to_canonical["IP_CONFLICT_NEUTRAL_001"] = CONFLICT_ENTITY_ID

    # 2. Register Evidence Records
    ev_records = create_contradiction_evidence_records()
    for rec in ev_records:
        backend.evidence_engine.register_evidence(rec)
        backend._evidence_by_hash[rec.evidence_hash] = rec.evidence_id

    # 3. Run M11 Fusion
    fusion_result = run_m11_contradiction_fusion()

    # 4. Register Finding FND_CONFLICT_001
    finding_record = {
        "finding_id": CONFLICT_FINDING_ID,
        "entity_id": CONFLICT_ENTITY_ID,
        "canonical_entity_id": CONFLICT_ENTITY_ID,
        "detector": "M11_CROSS_DOMAIN_FUSION",
        "anomaly_score": 0.92,
        "composite_score": fusion_result.get("corroboration_score", 0.38),
        "confidence": 0.40,
        "status": "CONFLICTED",
        "timestamp": 1700050020.0,
        "observation_timestamp": 1700050020.0,
        "temporal_semantics": "OBSERVED_TIMESTAMP",
        "anomaly_reasons": [
            "Financial domain indicates high velocity structuring (anomaly_score=0.92)",
            "Contradicted by Social domain normal personal activity (anomaly_score=0.08)",
            "Cross-domain conflict detected between Financial and Social signals"
        ],
        "supporting_evidence": [SUPPORT_EVID_ID],
        "contradicting_evidence": [CONTRA_EVID_ID],
        "contextual_evidence": [NEUTRAL_EVID_ID],
        "m11_fusion_info": fusion_result,
        "evidence_ref": f"ref:fnd:{CONFLICT_FINDING_ID}"
    }
    backend.findings_by_id[CONFLICT_FINDING_ID] = finding_record

    # 5. Wire Finding in Evidence Engine and Provenance Graph
    backend.evidence_engine.finding_evidence_map[CONFLICT_FINDING_ID] = [
        SUPPORT_EVID_ID, CONTRA_EVID_ID, NEUTRAL_EVID_ID
    ]
    backend.evidence_engine.graph.add_node(
        CONFLICT_FINDING_ID,
        node_type="FINDING",
        domain="CROSS_DOMAIN",
        metadata={"finding_id": CONFLICT_FINDING_ID, "status": "CONFLICTED"}
    )
    backend.evidence_engine.graph.add_edge(
        SUPPORT_EVID_ID, CONFLICT_FINDING_ID, relation="SUPPORTS", method="M11_FUSION"
    )
    backend.evidence_engine.graph.add_edge(
        CONTRA_EVID_ID, CONFLICT_FINDING_ID, relation="CONTRADICTS", method="M11_FUSION"
    )
    backend.evidence_engine.graph.add_edge(
        NEUTRAL_EVID_ID, CONFLICT_FINDING_ID, relation="CONTEXT", method="M11_FUSION"
    )

    # 6. Create Case CASE-CONFLICT-001
    if CASE_CONFLICT_ID not in backend.cases:
        case = backend.create_case(
            canonical_entity_id=CONFLICT_ENTITY_ID,
            case_id=CASE_CONFLICT_ID,
            search_context={
                "source": "SYNTHETIC_CONTRADICTION_FIXTURE",
                "case_kind": "CONTRADICTION_TEST",
                "conflict_status": "CONFLICTED",
                "supporting_domains": ["FINANCIAL"],
                "contradicting_domains": ["SOCIAL"],
                "neutral_domains": ["IPDR"],
                "supporting_evidence": [SUPPORT_EVID_ID],
                "contradicting_evidence": [CONTRA_EVID_ID],
                "neutral_evidence": [NEUTRAL_EVID_ID],
                "fused_composite_score": fusion_result.get("corroboration_score", 0.38),
            }
        )
    else:
        case = backend.cases[CASE_CONFLICT_ID]

    case.status = CaseStatus.UNDER_REVIEW
    if CONFLICT_FINDING_ID not in case.finding_ids:
        backend.attach_finding(CASE_CONFLICT_ID, CONFLICT_FINDING_ID)
    for eid in [SUPPORT_EVID_ID, CONTRA_EVID_ID, NEUTRAL_EVID_ID]:
        if eid not in case.evidence_ids:
            backend.attach_evidence(CASE_CONFLICT_ID, eid)

    return {
        "case": case,
        "finding": finding_record,
        "fusion_result": fusion_result,
        "evidence_records": {r.evidence_id: r for r in ev_records}
    }
