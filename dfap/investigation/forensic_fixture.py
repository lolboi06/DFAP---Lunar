# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: Forensic Case Packet Verification Fixture (Cross-linking M10 Motif + M11 Conflict + M12 Provenance + M13 Case)

from typing import Dict, Any, List
import pandas as pd

from dfap.investigation.workspace import InvestigationWorkspaceBackend, InvestigationCase, CaseStatus
from dfap.investigation.evidence_provenance import CanonicalEvidenceRecord


FORENSIC_DEMO_CASE_ID = "CASE-FORENSIC-001"
FORENSIC_DEMO_ENTITY_ID = "ENT_FORENSIC_DEMO_001"

FND_FORENSIC_001 = "FND_FORENSIC_001"
EVD_FIN_SUPPORT = "EVD-FIN-SUPPORT-001"
EVD_SOC_CONTRA = "EVD-SOC-CONTRA-001"
EVD_IPDR_CONTEXT = "EVD-IPDR-CONTEXT-001"


def register_forensic_demo_fixture(backend: InvestigationWorkspaceBackend) -> str:
    """
    Registers a comprehensive controlled case with:
    - 3 domains (FINANCIAL, SOCIAL, IPDR)
    - 14 chronological sequence events containing 3 repetitions of an uncatalogued motif (M10)
    - One primary finding attached (FND_FORENSIC_001)
    - Supporting & Contradicting evidence causing material M11 conflict (FINANCIAL vs SOCIAL)
    - End-to-end M12 provenance lineage
    """
    case_id = FORENSIC_DEMO_CASE_ID
    entity_id = FORENSIC_DEMO_ENTITY_ID

    # 1. Entity registration
    backend.valid_entities.add(entity_id)
    backend._entity_alias_to_canonical[entity_id] = entity_id

    # 2. Sequence Events with 3 repetitions of novel motif: LOGIN -> QUERY -> TRANSFER -> MESSAGE
    # Pattern: LOGIN (IPDR) -> QUERY (IPDR) -> TRANSFER (BANK) -> MESSAGE (SOCIAL)
    pattern = [
        ("LOGIN", "IPDR"),
        ("QUERY", "IPDR"),
        ("TRANSFER", "BANK"),
        ("MESSAGE", "SOCIAL"),
    ]

    base_times = [1700000000.0, 1700005000.0, 1700010000.0]
    demo_events = []
    ev_counter = 1

    for t_start in base_times:
        t_curr = t_start
        for etype, dom in pattern:
            ev_id = f"EVT_FORENSIC_{ev_counter:03d}"
            ev_ref = f"ref:evd:{ev_id}"
            demo_events.append({
                "event_id": ev_id,
                "actor_id": entity_id,
                "target_id": f"TARGET_{ev_counter:03d}",
                "event_type": etype,
                "source_domain": dom,
                "timestamp": pd.to_datetime(t_curr, unit="s", utc=True).isoformat(),
                "epoch_time": t_curr,
                "evidence_ref": ev_ref,
                "sha256_hash": f"hash_{ev_id.lower()}",
                "amount": 5000.0 if etype == "TRANSFER" else 0.0,
                "case_id": case_id,
                "temporal_semantics": "OBSERVED_TIMESTAMP",
            })
            t_curr += 120.0
            ev_counter += 1

    # Add 2 additional events for context
    t_extra = 1700020000.0
    for etype, dom in [("ACCOUNT_CHECK", "BANK"), ("PROFILE_UPDATE", "SOCIAL")]:
        ev_id = f"EVT_FORENSIC_{ev_counter:03d}"
        ev_ref = f"ref:evd:{ev_id}"
        demo_events.append({
            "event_id": ev_id,
            "actor_id": entity_id,
            "target_id": f"TARGET_{ev_counter:03d}",
            "event_type": etype,
            "source_domain": dom,
            "timestamp": pd.to_datetime(t_extra, unit="s", utc=True).isoformat(),
            "epoch_time": t_extra,
            "evidence_ref": ev_ref,
            "sha256_hash": f"hash_{ev_id.lower()}",
            "amount": 0.0,
            "case_id": case_id,
            "temporal_semantics": "OBSERVED_TIMESTAMP",
        })
        t_extra += 180.0
        ev_counter += 1

    demo_events.sort(key=lambda x: x["epoch_time"])

    # Append to backend events_df
    df_events = pd.DataFrame(demo_events)
    if hasattr(backend, "events_df") and not backend.events_df.empty:
        backend.events_df = pd.concat([backend.events_df, df_events], ignore_index=True)
    else:
        backend.events_df = df_events

    # Register evidence records in evidence engine for all events
    for e in demo_events:
        rec = CanonicalEvidenceRecord(
            evidence_type="TELEMETRY_LOG",
            source_domain=e["source_domain"],
            source_id=e["actor_id"],
            source_file="synthetic_forensic_telemetry.parquet",
            source_row_index=0,
            canonical_entity_ids=[entity_id],
            event_ids=[e["event_id"]],
            observation_timestamp=e["epoch_time"],
            ingestion_timestamp="2026-09-08T00:00:00Z",
            derivation_method="TELEMETRY_PIPELINE",
            confidence=0.95,
            evidence_category="SUPPORTING" if e["event_type"] == "TRANSFER" else "CONTEXTUAL",
            evidence_id=f"EVD-ITEM-{e['event_id']}",
            metadata={"anomaly_score": 0.50}
        )
        rec.provenance_ref = f"ref:evd:{rec.evidence_id}"
        backend.evidence_engine.register_evidence(rec)

    # 3. Register Specific Finding Evidence Items
    # Evidence 1: Financial Anomaly (High Structuring Score = 0.92) [SUPPORTING]
    ev_fin = CanonicalEvidenceRecord(
        evidence_type="ANOMALY_DETECTION",
        source_domain="FINANCIAL",
        source_id="RECORD_FIN_SRC_001",
        source_file="financial_telemetry.parquet",
        source_row_index=101,
        canonical_entity_ids=[entity_id],
        event_ids=["EVT_FORENSIC_003"],
        observation_timestamp=1700000240.0,
        ingestion_timestamp="2026-09-08T00:00:00Z",
        derivation_method="BEHAVIORAL_ANOMALY_DETECTOR",
        confidence=0.92,
        evidence_category="SUPPORTING",
        evidence_id=EVD_FIN_SUPPORT,
        metadata={
            "anomaly_score": 0.92,
            "hypothesis": "Rapid repeated structuring transfers",
            "signal": "Structured multi-layer fund dispersal"
        }
    )
    ev_fin.provenance_ref = f"ref:evd:{EVD_FIN_SUPPORT}"
    backend.evidence_engine.register_evidence(ev_fin)

    # Evidence 2: Social Baseline (Normal Personal Profile = 0.08 anomaly / 0.92 normal) [CONTRADICTING]
    ev_soc = CanonicalEvidenceRecord(
        evidence_type="BEHAVIORAL_BASELINE",
        source_domain="SOCIAL",
        source_id="RECORD_SOC_SRC_001",
        source_file="social_telemetry.parquet",
        source_row_index=204,
        canonical_entity_ids=[entity_id],
        event_ids=["EVT_FORENSIC_004"],
        observation_timestamp=1700000360.0,
        ingestion_timestamp="2026-09-08T00:00:00Z",
        derivation_method="COMMUNITY_BASELINE_PROFILER",
        confidence=0.90,
        evidence_category="CONTRADICTING",
        evidence_id=EVD_SOC_CONTRA,
        metadata={
            "anomaly_score": 0.08,
            "hypothesis": "Longstanding organic community engagement inconsistent with illicit activity",
            "signal": "Authentic personal social history"
        }
    )
    ev_soc.provenance_ref = f"ref:evd:{EVD_SOC_CONTRA}"
    backend.evidence_engine.register_evidence(ev_soc)

    # Evidence 3: IPDR Telemetry (Neutral contextual log) [CONTEXTUAL]
    ev_ipdr = CanonicalEvidenceRecord(
        evidence_type="TELEMETRY_LOG",
        source_domain="IPDR",
        source_id="RECORD_IPDR_SRC_001",
        source_file="network_telemetry.parquet",
        source_row_index=305,
        canonical_entity_ids=[entity_id],
        event_ids=["EVT_FORENSIC_001"],
        observation_timestamp=1700000000.0,
        ingestion_timestamp="2026-09-08T00:00:00Z",
        derivation_method="TELEMETRY_INGEST_PIPELINE",
        confidence=0.88,
        evidence_category="CONTEXTUAL",
        evidence_id=EVD_IPDR_CONTEXT,
        metadata={
            "anomaly_score": 0.45,
            "signal": "Standard mobile network session access"
        }
    )
    ev_ipdr.provenance_ref = f"ref:evd:{EVD_IPDR_CONTEXT}"
    backend.evidence_engine.register_evidence(ev_ipdr)

    # 4. Register Finding
    fnd = {
        "finding_id": FND_FORENSIC_001,
        "canonical_entity_id": entity_id,
        "entity_id": entity_id,
        "source_domain": "CROSS_DOMAIN",
        "dataset": "FINANCIAL_SOCIAL_FUSED",
        "detector": "M11_CROSS_DOMAIN_FUSION_DETECTOR",
        "anomaly_type": "M11_CROSS_DOMAIN_FUSION_DETECTOR",
        "composite_score": 0.74,
        "anomaly_score": 0.74,
        "confidence": 0.92,
        "status": "ACTIVE",
        "timestamp": "2026-09-08T00:00:00Z",
        "temporal_semantics": "OBSERVED_TIMESTAMP",
        "supporting_evidence": [EVD_FIN_SUPPORT],
        "contradicting_evidence": [EVD_SOC_CONTRA],
        "contextual_evidence": [EVD_IPDR_CONTEXT],
        "evidence_ref": f"ref:fnd:{FND_FORENSIC_001}",
        "evidence_id": f"ref:fnd:{FND_FORENSIC_001}",
    }
    backend.findings_by_id[FND_FORENSIC_001] = fnd

    # Register in lineage graph
    backend.evidence_engine.graph.add_node(
        node_id=FND_FORENSIC_001,
        node_type="FUSED_FINDING",
        domain="CROSS_DOMAIN",
        metadata={"finding_id": FND_FORENSIC_001, "score": 0.74}
    )
    backend.evidence_engine.graph.add_edge(EVD_FIN_SUPPORT, FND_FORENSIC_001, relation="SUPPORTS", method="M11_FUSION")
    backend.evidence_engine.graph.add_edge(EVD_SOC_CONTRA, FND_FORENSIC_001, relation="CONTRADICTS", method="M11_FUSION")
    backend.evidence_engine.graph.add_edge(EVD_IPDR_CONTEXT, FND_FORENSIC_001, relation="CONTEXTUALIZES", method="M11_FUSION")
    backend.evidence_engine.finding_evidence_map[FND_FORENSIC_001] = [EVD_FIN_SUPPORT, EVD_SOC_CONTRA, EVD_IPDR_CONTEXT]

    # 5. Create Investigation Case
    case = InvestigationCase(
        case_id=case_id,
        canonical_entity_id=entity_id,
        status=CaseStatus.OPEN,
        created_at="2026-09-08T00:00:00Z",
        finding_ids=[FND_FORENSIC_001],
        evidence_ids=[EVD_FIN_SUPPORT, EVD_SOC_CONTRA, EVD_IPDR_CONTEXT],
        provenance_refs=[f"ref:fnd:{FND_FORENSIC_001}", ev_fin.provenance_ref, ev_soc.provenance_ref, ev_ipdr.provenance_ref],
        search_context={"scope": "CONTROLLED_CROSS_DOMAIN_FORENSIC_CASE"}
    )
    backend.cases[case_id] = case

    return case_id
