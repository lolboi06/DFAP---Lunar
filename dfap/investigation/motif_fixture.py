# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: Synthetic Sequence Fixture for M10 Unsupervised Motif Discovery

from typing import Any, Dict, List
import pandas as pd

from dfap.investigation.workspace import InvestigationWorkspaceBackend, CaseStatus
from dfap.investigation.evidence_provenance import CanonicalEvidenceRecord
from dfap.investigation.temporal_motif_discovery import DiscoveredMotif

DEMO_ENTITY_ID = "ENT_MOTIF_DEMO_001"
DEMO_CASE_ID = "CASE-MOTIF-DEMO-001"


def create_motif_demo_events() -> List[Dict[str, Any]]:
    """
    Creates a deterministic sequence containing:
      1. An uncatalogued novel pattern: LOGIN -> QUERY -> TRANSFER -> MESSAGE
         repeated 3 times across distinct timestamps.
      2. A predefined catalog pattern: ACCESS_CHANGE_TRANSFER
         (LOGIN -> KEY_ROTATION -> TRANSFER).
    """
    events = []
    
    # 1. Three repetitions of uncatalogued pattern:
    # LOGIN (IPDR) -> QUERY (IPDR) -> TRANSFER (BANK) -> MESSAGE (SOCIAL)
    novel_pattern = [
        ("LOGIN", "IPDR"),
        ("QUERY", "IPDR"),
        ("TRANSFER", "BANK"),
        ("MESSAGE", "SOCIAL")
    ]
    
    base_times = [1700000000.0, 1700005000.0, 1700010000.0]
    ev_counter = 1

    for rep_idx, t_start in enumerate(base_times):
        t_curr = t_start
        for etype, dom in novel_pattern:
            ev_id = f"EVT_NOVEL_{ev_counter:02d}"
            ev_ref = f"ref:novel_ev_{ev_counter:02d}"
            events.append({
                "event_id": ev_id,
                "actor_id": DEMO_ENTITY_ID,
                "target_id": f"TARGET_{ev_counter:02d}",
                "event_type": etype,
                "source_domain": dom,
                "timestamp": pd.to_datetime(t_curr, unit="s", utc=True).isoformat(),
                "epoch_time": t_curr,
                "evidence_ref": ev_ref,
                "sha256_hash": f"hash_{ev_id.lower()}",
                "amount": 5000.0 if etype == "TRANSFER" else 0.0,
                "case_id": DEMO_CASE_ID
            })
            t_curr += 120.0  # 2 minute gaps
            ev_counter += 1

    # 2. One instance of predefined catalog pattern: ACCESS_CHANGE_TRANSFER
    # LOGIN (IPDR) -> KEY_ROTATION (IAM) -> TRANSFER (BANK)
    t_act = 1700020000.0
    act_pattern = [
        ("LOGIN", "IPDR"),
        ("KEY_ROTATION", "IAM"),
        ("TRANSFER", "BANK")
    ]
    for etype, dom in act_pattern:
        ev_id = f"EVT_ACT_{ev_counter:02d}"
        ev_ref = f"ref:act_ev_{ev_counter:02d}"
        events.append({
            "event_id": ev_id,
            "actor_id": DEMO_ENTITY_ID,
            "target_id": f"TARGET_{ev_counter:02d}",
            "event_type": etype,
            "source_domain": dom,
            "timestamp": pd.to_datetime(t_act, unit="s", utc=True).isoformat(),
            "epoch_time": t_act,
            "evidence_ref": ev_ref,
            "sha256_hash": f"hash_{ev_id.lower()}",
            "amount": 25000.0 if etype == "TRANSFER" else 0.0,
            "case_id": DEMO_CASE_ID
        })
        t_act += 180.0
        ev_counter += 1

    # Sort strictly chronologically
    events.sort(key=lambda x: x["epoch_time"])
    return events


def register_motif_demo_fixture(backend: InvestigationWorkspaceBackend) -> Dict[str, Any]:
    """
    Registers the demo case, entity, events, and evidence into the backend.
    """
    # 1. Register canonical entity
    backend.valid_entities.add(DEMO_ENTITY_ID)
    backend._entity_alias_to_canonical[DEMO_ENTITY_ID] = DEMO_ENTITY_ID

    # 2. Register raw events in timeline cache
    demo_events = create_motif_demo_events()
    df_events = pd.DataFrame(demo_events)
    if hasattr(backend, "events_df") and not backend.events_df.empty:
        backend.events_df = pd.concat([backend.events_df, df_events], ignore_index=True)
    else:
        backend.events_df = df_events

    # Register evidence records in evidence engine
    for e in demo_events:
        rec = CanonicalEvidenceRecord(
            evidence_type="TELEMETRY_LOG",
            source_domain=e["source_domain"],
            source_id=e["actor_id"],
            source_file="synthetic_motif_demo.parquet",
            source_row_index=0,
            canonical_entity_ids=[DEMO_ENTITY_ID],
            event_ids=[e["event_id"]],
            observation_timestamp=e["epoch_time"],
            ingestion_timestamp="2026-09-08T00:00:00Z",
            derivation_method="SYNTHETIC_MOTIF_GENERATOR",
            confidence=0.95,
            evidence_category="SUPPORTING",
            evidence_id=e["evidence_ref"],
            metadata={"event_id": e["event_id"], "event_type": e["event_type"]}
        )
        rec.provenance_ref = f"prov:{e['evidence_ref']}"
        backend.evidence_engine.register_evidence(rec)

    # 3. Create active investigation case
    if DEMO_CASE_ID not in backend.cases:
        backend.create_case(
            DEMO_ENTITY_ID,
            case_id=DEMO_CASE_ID,
            search_context={"source": "SYNTHETIC_MOTIF_DEMO", "case_kind": "NATIVE_CASE"}
        )

    # 4. Execute motif discovery
    seq = backend.build_sequence(demo_events, canonical_entity_id=DEMO_ENTITY_ID, case_id=DEMO_CASE_ID)
    discovered = backend.discover_sequence_motifs(seq, min_length=3, max_length=4)
    predefined = backend.detect_sequence_motifs(seq)

    return {
        "case_id": DEMO_CASE_ID,
        "entity_id": DEMO_ENTITY_ID,
        "events_count": len(demo_events),
        "sequence": seq,
        "discovered_motifs": discovered,
        "predefined_motifs": predefined
    }
