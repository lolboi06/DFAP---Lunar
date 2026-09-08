# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: 4-Domain Controlled Forensic Case Fixture (CDR + IPDR + FINANCIAL + SOCIAL)

from typing import Dict, Any, List
import pandas as pd

from dfap.investigation.workspace import InvestigationWorkspaceBackend, InvestigationCase, CaseStatus
from dfap.investigation.evidence_provenance import CanonicalEvidenceRecord


FOUR_DOMAIN_CASE_ID = "CASE-DFAP-4DOMAIN-001"
FOUR_DOMAIN_ENTITY_ID = "ENT_DFAP_4DOM_001"

FND_4DOM_FUSED = "FND_4DOM_FUSED_001"
FND_4DOM_CONTEXT = "FND_4DOM_CONTEXT_002"
EVD_4DOM_FIN = "EVD-4DOM-FIN-001"
EVD_4DOM_CDR = "EVD-4DOM-CDR-001"
EVD_4DOM_SOC = "EVD-4DOM-SOC-001"
EVD_4DOM_IPDR = "EVD-4DOM-IPDR-001"

RAW_ID_CDR = "PHONE_+15550199"
RAW_ID_IPDR = "IP_198_51_100_45"
RAW_ID_FIN = "ACCT_FIN_99420"
RAW_ID_SOC = "HANDLE_SOC_X7"


def register_four_domain_fixture(backend: InvestigationWorkspaceBackend) -> str:
    """
    Registers the definitive 4-domain end-to-end controlled investigation:
      CDR + IPDR + FINANCIAL + SOCIAL
             ↓
      Authoritative Identity Bridge (4 explicit links, zero blind equating)
             ↓
      16-event strictly causal chronological timeline with 3 repetitions of an uncatalogued motif
             ↓
      Domain anomalies: FINANCIAL (0.92, structuring), CDR (0.85, burst), SOCIAL (0.08, baseline normal), IPDR (0.45, network access)
             ↓
      M11 Cross-Domain Fusion with evidential conflict (FINANCIAL vs SOCIAL -> CONFLICTED / HUMAN_REVIEW)
             ↓
      M10 Unsupervised Motif Discovery (discovering recurring sequence)
             ↓
      M12 Forensic Case Packet with deterministic SHA-256 digest & traceability matrix
             ↓
      M13 Workspace CLI & M14 Grounded Copilot integration
    """
    case_id = FOUR_DOMAIN_CASE_ID
    entity_id = FOUR_DOMAIN_ENTITY_ID

    # 1. Authoritative Identity Bridge & Entity Registration
    backend.valid_entities.add(entity_id)
    backend._entity_alias_to_canonical[entity_id] = entity_id

    bridge_rows = [
        {
            "case_id": case_id,
            "canonical_entity_id": entity_id,
            "domain": "CDR",
            "raw_identifier": RAW_ID_CDR,
            "mapping_method": "RESOLVED_PHONE_LINK",
            "confidence": 0.95,
            "evidence_ref": "ref:bridge_cdr_001",
        },
        {
            "case_id": case_id,
            "canonical_entity_id": entity_id,
            "domain": "IPDR",
            "raw_identifier": RAW_ID_IPDR,
            "mapping_method": "AUTH_DEVICE_LINK",
            "confidence": 0.90,
            "evidence_ref": "ref:bridge_ipdr_001",
        },
        {
            "case_id": case_id,
            "canonical_entity_id": entity_id,
            "domain": "FINANCIAL",
            "raw_identifier": RAW_ID_FIN,
            "mapping_method": "EXACT_KYC_ACCOUNT",
            "confidence": 0.98,
            "evidence_ref": "ref:bridge_fin_001",
        },
        {
            "case_id": case_id,
            "canonical_entity_id": entity_id,
            "domain": "SOCIAL",
            "raw_identifier": RAW_ID_SOC,
            "mapping_method": "VERIFIED_OAUTH_HANDLE",
            "confidence": 0.88,
            "evidence_ref": "ref:bridge_soc_001",
        },
    ]

    for br in bridge_rows:
        backend._entity_alias_to_canonical[br["raw_identifier"]] = entity_id

    df_bridge = pd.DataFrame(bridge_rows)
    if hasattr(backend, "bridge_df") and not backend.bridge_df.empty:
        backend.bridge_df = pd.concat([backend.bridge_df, df_bridge], ignore_index=True).drop_duplicates(subset=["raw_identifier", "canonical_entity_id"])
    else:
        backend.bridge_df = df_bridge

    if hasattr(backend, "fusion_engine") and hasattr(backend.fusion_engine, "bridge_df"):
        if not backend.fusion_engine.bridge_df.empty:
            backend.fusion_engine.bridge_df = pd.concat([backend.fusion_engine.bridge_df, df_bridge], ignore_index=True).drop_duplicates(subset=["raw_identifier", "canonical_entity_id"])
        else:
            backend.fusion_engine.bridge_df = df_bridge

    # 2. Chronological Timeline Events
    # 3 repetitions of an uncatalogued cross-domain motif:
    # CALL (CDR) -> LOGIN (IPDR) -> TRANSFER (FINANCIAL) -> MESSAGE (SOCIAL)
    pattern = [
        ("CALL", "CDR", RAW_ID_CDR, "PHONE_+15550888", 0.0),
        ("LOGIN", "IPDR", RAW_ID_IPDR, "SERVER_AUTH_GW", 60.0),
        ("TRANSFER", "FINANCIAL", RAW_ID_FIN, "ACCT_EXT_77123", 120.0),
        ("MESSAGE", "SOCIAL", RAW_ID_SOC, "USER_SOC_COMMUNITY", 180.0),
    ]

    base_times = [1700000000.0, 1700010000.0, 1700020000.0]
    demo_events = []
    ev_counter = 1

    for t_start in base_times:
        for etype, dom, act, tgt, dt in pattern:
            t_curr = t_start + dt
            ev_id = f"EVT_4DOM_{ev_counter:03d}"
            ev_ref = f"ref:evd:{ev_id}"
            demo_events.append({
                "event_id": ev_id,
                "actor_id": act,
                "target_id": tgt,
                "event_type": etype,
                "source_domain": dom,
                "domain": dom,
                "dataset": f"{dom}_TELEMETRY",
                "timestamp": pd.to_datetime(t_curr, unit="s", utc=True).isoformat(),
                "epoch_time": t_curr,
                "evidence_ref": ev_ref,
                "provenance_ref": f"ref:prov:{ev_id}",
                "sha256_hash": f"hash_{ev_id.lower()}_{int(t_curr)}",
                "amount": 4950.0 if etype == "TRANSFER" else 0.0,
                "case_id": case_id,
                "canonical_entity_id": entity_id,
                "temporal_semantics": "OBSERVED_TIMESTAMP",
            })
            ev_counter += 1

    # 4 Contextual events at t = 1700030000.0
    context_events = [
        ("SESSION_LOGOUT", "IPDR", RAW_ID_IPDR, "SERVER_AUTH_GW", 1700030000.0),
        ("BALANCE_INQUIRY", "FINANCIAL", RAW_ID_FIN, "BANK_CORE_API", 1700030100.0),
        ("COMMUNITY_POST", "SOCIAL", RAW_ID_SOC, "FORUM_PUBLIC", 1700030200.0),
        ("CALL_DISCONNECT", "CDR", RAW_ID_CDR, "TELCO_TOWER_04", 1700030300.0),
    ]
    for etype, dom, act, tgt, t_val in context_events:
        ev_id = f"EVT_4DOM_{ev_counter:03d}"
        ev_ref = f"ref:evd:{ev_id}"
        demo_events.append({
            "event_id": ev_id,
            "actor_id": act,
            "target_id": tgt,
            "event_type": etype,
            "source_domain": dom,
            "domain": dom,
            "dataset": f"{dom}_TELEMETRY",
            "timestamp": pd.to_datetime(t_val, unit="s", utc=True).isoformat(),
            "epoch_time": t_val,
            "evidence_ref": ev_ref,
            "provenance_ref": f"ref:prov:{ev_id}",
            "sha256_hash": f"hash_{ev_id.lower()}_{int(t_val)}",
            "amount": 0.0,
            "case_id": case_id,
            "canonical_entity_id": entity_id,
            "temporal_semantics": "OBSERVED_TIMESTAMP",
        })
        ev_counter += 1

    demo_events.sort(key=lambda x: x["epoch_time"])

    df_events = pd.DataFrame(demo_events)
    if hasattr(backend, "events_df") and not backend.events_df.empty:
        backend.events_df = pd.concat([backend.events_df, df_events], ignore_index=True).drop_duplicates(subset=["event_id"])
    else:
        backend.events_df = df_events

    # Register evidence records for each raw event
    for e in demo_events:
        rec = CanonicalEvidenceRecord(
            evidence_type="TELEMETRY_LOG",
            source_domain=e["source_domain"],
            source_id=e["actor_id"],
            source_file=f"{e['source_domain'].lower()}_telemetry.parquet",
            source_row_index=0,
            canonical_entity_ids=[entity_id],
            event_ids=[e["event_id"]],
            observation_timestamp=e["epoch_time"],
            ingestion_timestamp="2026-09-08T00:00:00Z",
            derivation_method="TELEMETRY_INGEST_PIPELINE",
            confidence=0.95,
            evidence_category="SUPPORTING" if e["event_type"] in ("TRANSFER", "CALL") else "CONTEXTUAL",
            evidence_id=f"EVD-ITEM-{e['event_id']}",
            metadata={"anomaly_score": 0.50}
        )
        rec.provenance_ref = f"ref:evd:{rec.evidence_id}"
        backend.evidence_engine.register_evidence(rec)

    # 3. Domain Anomaly Evidence Records
    # A. FINANCIAL (Score: 0.92) [SUPPORTING]
    ev_fin = CanonicalEvidenceRecord(
        evidence_type="ANOMALY_DETECTION",
        source_domain="FINANCIAL",
        source_id="RECORD_FIN_4DOM_001",
        source_file="financial_telemetry.parquet",
        source_row_index=101,
        canonical_entity_ids=[entity_id],
        event_ids=["EVT_4DOM_003"],
        observation_timestamp=1700000120.0,
        ingestion_timestamp="2026-09-08T00:00:00Z",
        derivation_method="STRUCTURING_ANOMALY_DETECTOR",
        confidence=0.92,
        evidence_category="SUPPORTING",
        evidence_id=EVD_4DOM_FIN,
        metadata={
            "anomaly_score": 0.92,
            "hypothesis": "Rapid repeated structuring transfers",
            "signal": "Structured multi-layer fund dispersal"
        }
    )
    ev_fin.provenance_ref = f"ref:evd:{EVD_4DOM_FIN}"
    backend.evidence_engine.register_evidence(ev_fin)

    # B. CDR (Score: 0.85) [SUPPORTING]
    ev_cdr = CanonicalEvidenceRecord(
        evidence_type="ANOMALY_DETECTION",
        source_domain="CDR",
        source_id="RECORD_CDR_4DOM_001",
        source_file="cdr_telemetry.parquet",
        source_row_index=42,
        canonical_entity_ids=[entity_id],
        event_ids=["EVT_4DOM_001"],
        observation_timestamp=1700000000.0,
        ingestion_timestamp="2026-09-08T00:00:00Z",
        derivation_method="TELECOM_BURST_DETECTOR",
        confidence=0.85,
        evidence_category="SUPPORTING",
        evidence_id=EVD_4DOM_CDR,
        metadata={
            "anomaly_score": 0.85,
            "hypothesis": "Burst telecommunication redirection",
            "signal": "High frequency call handover"
        }
    )
    ev_cdr.provenance_ref = f"ref:evd:{EVD_4DOM_CDR}"
    backend.evidence_engine.register_evidence(ev_cdr)

    # C. SOCIAL (Score: 0.08 anomaly / 0.92 normal) [CONTRADICTING]
    ev_soc = CanonicalEvidenceRecord(
        evidence_type="BEHAVIORAL_BASELINE",
        source_domain="SOCIAL",
        source_id="RECORD_SOC_4DOM_001",
        source_file="social_telemetry.parquet",
        source_row_index=204,
        canonical_entity_ids=[entity_id],
        event_ids=["EVT_4DOM_004"],
        observation_timestamp=1700000180.0,
        ingestion_timestamp="2026-09-08T00:00:00Z",
        derivation_method="COMMUNITY_BASELINE_PROFILER",
        confidence=0.90,
        evidence_category="CONTRADICTING",
        evidence_id=EVD_4DOM_SOC,
        metadata={
            "anomaly_score": 0.08,
            "hypothesis": "Longstanding organic community engagement inconsistent with illicit activity",
            "signal": "Authentic personal social history"
        }
    )
    ev_soc.provenance_ref = f"ref:evd:{EVD_4DOM_SOC}"
    backend.evidence_engine.register_evidence(ev_soc)

    # D. IPDR (Score: 0.45) [CONTEXTUAL]
    ev_ipdr = CanonicalEvidenceRecord(
        evidence_type="TELEMETRY_LOG",
        source_domain="IPDR",
        source_id="RECORD_IPDR_4DOM_001",
        source_file="network_telemetry.parquet",
        source_row_index=305,
        canonical_entity_ids=[entity_id],
        event_ids=["EVT_4DOM_002"],
        observation_timestamp=1700000060.0,
        ingestion_timestamp="2026-09-08T00:00:00Z",
        derivation_method="TELEMETRY_INGEST_PIPELINE",
        confidence=0.88,
        evidence_category="CONTEXTUAL",
        evidence_id=EVD_4DOM_IPDR,
        metadata={
            "anomaly_score": 0.45,
            "signal": "Standard mobile network session access"
        }
    )
    ev_ipdr.provenance_ref = f"ref:evd:{EVD_4DOM_IPDR}"
    backend.evidence_engine.register_evidence(ev_ipdr)

    # 4. Cross-Domain Fusion Execution
    fusion_items = [
        {
            "finding_id": "FND-4DOM-FIN-001",
            "source_domain": "FINANCIAL",
            "raw_identifier": RAW_ID_FIN,
            "anomaly_score": 0.92,
            "epoch_time": 1700000120.0,
            "event_id": "EVT_4DOM_003",
            "evidence_ref": f"ref:evd:{EVD_4DOM_FIN}",
        },
        {
            "finding_id": "FND-4DOM-CDR-001",
            "source_domain": "CDR",
            "raw_identifier": RAW_ID_CDR,
            "anomaly_score": 0.85,
            "epoch_time": 1700000000.0,
            "event_id": "EVT_4DOM_001",
            "evidence_ref": f"ref:evd:{EVD_4DOM_CDR}",
        },
        {
            "finding_id": "FND-4DOM-SOC-001",
            "source_domain": "SOCIAL",
            "raw_identifier": RAW_ID_SOC,
            "anomaly_score": 0.08,
            "epoch_time": 1700000180.0,
            "event_id": "EVT_4DOM_004",
            "evidence_ref": f"ref:evd:{EVD_4DOM_SOC}",
        },
        {
            "finding_id": "FND-4DOM-IPDR-001",
            "source_domain": "IPDR",
            "raw_identifier": RAW_ID_IPDR,
            "anomaly_score": 0.45,
            "epoch_time": 1700000060.0,
            "event_id": "EVT_4DOM_002",
            "evidence_ref": f"ref:evd:{EVD_4DOM_IPDR}",
        },
    ]

    fusion_res = backend.fusion_engine.fuse_for_entity(entity_id, domain_evidence_items=fusion_items)

    # 5. Register Primary Fused Finding
    fnd = {
        "finding_id": FND_4DOM_FUSED,
        "canonical_entity_id": entity_id,
        "entity_id": entity_id,
        "source_domain": "CROSS_DOMAIN",
        "dataset": "FOUR_DOMAIN_FUSED",
        "detector": "M11_CROSS_DOMAIN_FUSION_DETECTOR",
        "anomaly_type": "M11_CROSS_DOMAIN_FUSION_DETECTOR",
        "composite_score": fusion_res.get("corroboration_score", 0.76),
        "anomaly_score": fusion_res.get("corroboration_score", 0.76),
        "confidence": 0.92,
        "status": "CONFLICTED",
        "timestamp": "2026-09-08T00:00:00Z",
        "temporal_semantics": "OBSERVED_TIMESTAMP",
        "supporting_evidence": [EVD_4DOM_FIN, EVD_4DOM_CDR],
        "contradicting_evidence": [EVD_4DOM_SOC],
        "contextual_evidence": [EVD_4DOM_IPDR],
        "evidence_ref": f"ref:fnd:{FND_4DOM_FUSED}",
        "evidence_id": f"ref:fnd:{FND_4DOM_FUSED}",
        "m11_fusion_info": fusion_res,
    }
    backend.findings_by_id[FND_4DOM_FUSED] = fnd

    # Lineage Graph Wiring
    backend.evidence_engine.graph.add_node(
        node_id=FND_4DOM_FUSED,
        node_type="FUSED_FINDING",
        domain="CROSS_DOMAIN",
        metadata={"finding_id": FND_4DOM_FUSED, "score": fusion_res.get("corroboration_score", 0.76)}
    )
    backend.evidence_engine.graph.add_edge(EVD_4DOM_FIN, FND_4DOM_FUSED, relation="SUPPORTS", method="M11_FUSION")
    backend.evidence_engine.graph.add_edge(EVD_4DOM_CDR, FND_4DOM_FUSED, relation="SUPPORTS", method="M11_FUSION")
    backend.evidence_engine.graph.add_edge(EVD_4DOM_SOC, FND_4DOM_FUSED, relation="CONTRADICTS", method="M11_FUSION")
    backend.evidence_engine.graph.add_edge(EVD_4DOM_IPDR, FND_4DOM_FUSED, relation="CONTEXTUALIZES", method="M11_FUSION")
    backend.evidence_engine.finding_evidence_map[FND_4DOM_FUSED] = [EVD_4DOM_FIN, EVD_4DOM_CDR, EVD_4DOM_SOC, EVD_4DOM_IPDR]

    # 5b. Register Secondary Contextual Finding (Single-Domain IPDR Network Anomaly)
    fnd_context = {
        "finding_id": FND_4DOM_CONTEXT,
        "canonical_entity_id": entity_id,
        "entity_id": entity_id,
        "source_domain": "IPDR",
        "dataset": "IPDR_TELEMETRY",
        "detector": "NETWORK_SESSION_DETECTOR",
        "anomaly_type": "NETWORK_SESSION_DETECTOR",
        "composite_score": 0.45,
        "anomaly_score": 0.45,
        "confidence": 0.88,
        "status": "ACTIVE",
        "timestamp": "2026-09-08T00:00:00Z",
        "temporal_semantics": "OBSERVED_TIMESTAMP",
        "supporting_evidence": [EVD_4DOM_IPDR],
        "contradicting_evidence": [],
        "contextual_evidence": [],
        "evidence_ref": f"ref:fnd:{FND_4DOM_CONTEXT}",
        "evidence_id": f"ref:fnd:{FND_4DOM_CONTEXT}",
        "m11_fusion_info": {},  # Single domain finding, no cross-domain fusion
    }
    backend.findings_by_id[FND_4DOM_CONTEXT] = fnd_context

    backend.evidence_engine.graph.add_node(
        node_id=FND_4DOM_CONTEXT,
        node_type="FINDING",
        domain="IPDR",
        metadata={"finding_id": FND_4DOM_CONTEXT, "score": 0.45}
    )
    backend.evidence_engine.graph.add_edge(EVD_4DOM_IPDR, FND_4DOM_CONTEXT, relation="SUPPORTS", method="RULE_EVALUATION")
    backend.evidence_engine.finding_evidence_map[FND_4DOM_CONTEXT] = [EVD_4DOM_IPDR]

    # 6. Investigation Case Registration
    case = InvestigationCase(
        case_id=case_id,
        canonical_entity_id=entity_id,
        status=CaseStatus.OPEN,
        created_at="2026-09-08T00:00:00Z",
        finding_ids=[FND_4DOM_FUSED, FND_4DOM_CONTEXT],
        evidence_ids=[EVD_4DOM_FIN, EVD_4DOM_CDR, EVD_4DOM_SOC, EVD_4DOM_IPDR],
        provenance_refs=[
            f"ref:fnd:{FND_4DOM_FUSED}",
            ev_fin.provenance_ref,
            ev_cdr.provenance_ref,
            ev_soc.provenance_ref,
            ev_ipdr.provenance_ref,
        ],
        search_context={"scope": "CONTROLLED_4DOMAIN_FORENSIC_CASE"}
    )
    backend.cases[case_id] = case

    return case_id
