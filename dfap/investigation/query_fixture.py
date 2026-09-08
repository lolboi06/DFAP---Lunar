# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: Feature 1 - Dedicated Controlled Test Fixture for Grammar-Constrained Query Parsing

import pandas as pd
from typing import Dict, Any, Tuple, List
from dfap.investigation.workspace import InvestigationWorkspaceBackend, InvestigationCase, CaseStatus

FIXTURE_CASE_ID = "CASE-QUERY-FEATURE1-001"
FIXTURE_CONTEXT_ENTITY = "ENT_CASE_TARGET_001"

# Same-name entities for disambiguation testing (Rahul Sharma)
ENT_RAHUL_A = "ENT_RAHUL_SHARMA_A"
ENT_RAHUL_B = "ENT_RAHUL_SHARMA_B"
ENT_RAHUL_C = "ENT_RAHUL_SHARMA_C"

# Intermediate hops for M4 graph topology (Test F)
# Topology:
# TARGET <-> RAHUL_A (1 hop)
# TARGET <-> HOP_B1 <-> RAHUL_B (2 hops)
# TARGET <-> HOP_C1 <-> HOP_C2 <-> HOP_C3 <-> RAHUL_C (4 hops)
NODE_HOP_B1 = "ENT_HOP_B1"
NODE_HOP_C1 = "ENT_HOP_C1"
NODE_HOP_C2 = "ENT_HOP_C2"
NODE_HOP_C3 = "ENT_HOP_C3"

# Another confirmed entity for PATH_BETWEEN
ENT_AMIT = "ENT_AMIT_KUMAR_01"

# POSSIBLE-only entity
ENT_POSSIBLE_ONLY = "ENT_POSSIBLE_UNCONFIRMED_99"
RAW_POSSIBLE_ID = "SUSPECT_PHONE_POSSIBLE_99"

def register_query_feature_fixture(backend: InvestigationWorkspaceBackend) -> Tuple[str, List[Tuple[str, str]]]:
    """
    Registers dedicated Feature 1 test entities, controlled topology, and active case context.
    Returns (case_id, custom_m4_edges).
    """
    # 1. Register entities in backend.entities_df
    entities_data = [
        # Target entity in case
        {
            "canonical_entity_id": FIXTURE_CONTEXT_ENTITY,
            "raw_identifier": "+1-555-TARGET-01",
            "identifier_type": "PHONE",
            "match_confidence": 1.0,
            "match_method": "EXACT",
            "match_status": "CONFIRMED",
            "evidence": "{}"
        },
        # Confirmed Rahul Sharma candidates
        {
            "canonical_entity_id": ENT_RAHUL_A,
            "raw_identifier": "Rahul Sharma",
            "identifier_type": "NAME",
            "match_confidence": 0.95,
            "match_method": "EXACT_NAME",
            "match_status": "CONFIRMED",
            "evidence": "{}"
        },
        {
            "canonical_entity_id": ENT_RAHUL_B,
            "raw_identifier": "Rahul Sharma",
            "identifier_type": "NAME",
            "match_confidence": 0.95,
            "match_method": "EXACT_NAME",
            "match_status": "CONFIRMED",
            "evidence": "{}"
        },
        {
            "canonical_entity_id": ENT_RAHUL_C,
            "raw_identifier": "Rahul Sharma",
            "identifier_type": "NAME",
            "match_confidence": 0.95,
            "match_method": "EXACT_NAME",
            "match_status": "CONFIRMED",
            "evidence": "{}"
        },
        # Amit Kumar (Confirmed)
        {
            "canonical_entity_id": ENT_AMIT,
            "raw_identifier": "Amit Kumar",
            "identifier_type": "NAME",
            "match_confidence": 0.95,
            "match_method": "EXACT_NAME",
            "match_status": "CONFIRMED",
            "evidence": "{}"
        },
        # POSSIBLE-only entity (Never confirmed)
        {
            "canonical_entity_id": ENT_POSSIBLE_ONLY,
            "raw_identifier": RAW_POSSIBLE_ID,
            "identifier_type": "PHONE",
            "match_confidence": 0.62,
            "match_method": "FUZZY",
            "match_status": "POSSIBLE",
            "evidence": "{}"
        },
    ]

    new_entities_df = pd.DataFrame(entities_data)
    if hasattr(backend, "entities_df") and not backend.entities_df.empty:
        backend.entities_df = pd.concat([backend.entities_df, new_entities_df], ignore_index=True)
    else:
        backend.entities_df = new_entities_df

    if hasattr(backend, "valid_entities"):
        backend.valid_entities.update([r["canonical_entity_id"] for r in entities_data])

    # 2. Setup known M4 topology edges:
    # A is 1 hop from TARGET
    # B is 2 hops from TARGET
    # C is 4 hops from TARGET
    custom_m4_edges = [
        (FIXTURE_CONTEXT_ENTITY, ENT_RAHUL_A),  # 1 hop
        (FIXTURE_CONTEXT_ENTITY, NODE_HOP_B1),
        (NODE_HOP_B1, ENT_RAHUL_B),             # 2 hops
        (FIXTURE_CONTEXT_ENTITY, NODE_HOP_C1),
        (NODE_HOP_C1, NODE_HOP_C2),
        (NODE_HOP_C2, NODE_HOP_C3),
        (NODE_HOP_C3, ENT_RAHUL_C),             # 4 hops
        (FIXTURE_CONTEXT_ENTITY, ENT_AMIT),     # 1 hop to Amit
    ]

    # 3. Register timeline events for activity timestamps (recency ordering)
    events_data = [
        {
            "event_id": "EVT_RAHUL_A_01",
            "timestamp": "2026-09-01T12:00:00Z",
            "epoch_time": 1788264000.0,
            "actor_id": ENT_RAHUL_A,
            "target_id": FIXTURE_CONTEXT_ENTITY,
            "event_type": "TRANSACTION",
            "source_domain": "FINANCIAL",
            "attributes": "{}",
            "sha256_hash": "a1b2c3d4e5f60001",
            "temporal_semantics": "OBSERVED_TIMESTAMP"
        },
        {
            "event_id": "EVT_RAHUL_B_01",
            "timestamp": "2026-08-15T10:00:00Z",
            "epoch_time": 1786788000.0,
            "actor_id": ENT_RAHUL_B,
            "target_id": NODE_HOP_B1,
            "event_type": "CALL",
            "source_domain": "CDR",
            "attributes": "{}",
            "sha256_hash": "a1b2c3d4e5f60002",
            "temporal_semantics": "OBSERVED_TIMESTAMP"
        },
        {
            "event_id": "EVT_RAHUL_C_01",
            "timestamp": "2026-07-01T08:00:00Z",
            "epoch_time": 1782892800.0,
            "actor_id": ENT_RAHUL_C,
            "target_id": NODE_HOP_C3,
            "event_type": "SOCIAL",
            "source_domain": "SOCIAL",
            "attributes": "{}",
            "sha256_hash": "a1b2c3d4e5f60003",
            "temporal_semantics": "OBSERVED_TIMESTAMP"
        },
        {
            "event_id": "EVT_AMIT_01",
            "timestamp": "2026-09-05T14:00:00Z",
            "epoch_time": 1788616800.0,
            "actor_id": ENT_AMIT,
            "target_id": FIXTURE_CONTEXT_ENTITY,
            "event_type": "CALL",
            "source_domain": "CDR",
            "attributes": "{}",
            "sha256_hash": "a1b2c3d4e5f60004",
            "temporal_semantics": "OBSERVED_TIMESTAMP"
        },
    ]

    new_events_df = pd.DataFrame(events_data)
    if hasattr(backend, "events_df") and not backend.events_df.empty:
        backend.events_df = pd.concat([backend.events_df, new_events_df], ignore_index=True)
    else:
        backend.events_df = new_events_df

    # 4. Register active investigation case
    case = InvestigationCase(
        case_id=FIXTURE_CASE_ID,
        canonical_entity_id=FIXTURE_CONTEXT_ENTITY,
        status=CaseStatus.OPEN,
        created_at="2026-09-08T00:00:00Z",
        finding_ids=[],
        evidence_ids=[],
        search_context={"scope": "FEATURE_1_CONTROLLED_TEST_CASE"}
    )
    backend.cases[FIXTURE_CASE_ID] = case

    return FIXTURE_CASE_ID, custom_m4_edges
