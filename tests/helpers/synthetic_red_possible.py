import os
import pandas as pd

from dfap.investigation.workspace import InvestigationWorkspaceBackend, InvestigationCase, CaseStatus
from dfap.investigation.event_sourcing import EventStore
from dfap.investigation.four_domain_fixture import (
    register_four_domain_fixture,
    FOUR_DOMAIN_CASE_ID,
    FOUR_DOMAIN_ENTITY_ID,
)

# Constants for the synthetic test case (clearly labelled as synthetic test data)
CASE_ID = "CASE-RED-POSSIBLE-001"
FINDING_ID = "FND_SYN_RED_01"
ENTITY_ID = FOUR_DOMAIN_ENTITY_ID  # Reuse the known entity so bridge/entity data exists


def setup_synthetic_red_possible(tmp_dir: str):
    """
    Create a minimal synthetic RED+POSSIBLE case for Feature 6 manual safety test.

    THIS IS SYNTHETIC TEST DATA. No production investigative records are created.

    Conditions satisfied:
      - risk tier HIGH (anomaly_score=0.95 → PriorityLevel.HIGH ≥ 0.65 threshold)
        generate_candidates checks: p_level in ("RED", "CRITICAL", "HIGH") → satisfied
      - POSSIBLE identity match row in backend.entities_df
      - Candidate type: RESOLVE_POSSIBLE_MATCH with is_safety_critical=True

    Args:
        tmp_dir: Path to a temporary directory for backend output, canonical, and case data.
    Returns:
        tuple: (backend, event_store)
    """
    # Initialise backend with temporary directories
    backend = InvestigationWorkspaceBackend(
        output_dir=os.path.join(tmp_dir, "output"),
        canonical_dir=os.path.join(tmp_dir, "data", "canonical"),
        cases_dir=os.path.join(tmp_dir, "data", "cases"),
    )
    # Load baseline four-domain fixture (provides entities_df, evidence engine, risk engine etc.)
    register_four_domain_fixture(backend)

    # Register the synthetic case as a proper InvestigationCase object (not a plain dict)
    # because generate_candidates accesses case.canonical_entity_id and case.finding_ids
    backend.cases[CASE_ID] = InvestigationCase(
        case_id=CASE_ID,
        canonical_entity_id=ENTITY_ID,
        status=CaseStatus.OPEN,
        created_at="2026-09-08T00:00:00Z",
        finding_ids=[FINDING_ID],
        evidence_ids=[],
    )

    # Register the entity as valid so risk engine can resolve it
    backend.valid_entities.add(ENTITY_ID)
    backend._entity_alias_to_canonical[ENTITY_ID] = ENTITY_ID

    # Insert a HIGH/RED finding – anomaly_score=0.95 exceeds the HIGH threshold (0.65)
    # Risk engine will assign PriorityLevel.HIGH → matches ("RED","CRITICAL","HIGH") check
    # NOTE: This is SYNTHETIC TEST DATA, not a real investigation finding.
    backend.findings_by_id[FINDING_ID] = {
        "finding_id": FINDING_ID,
        "case_id": CASE_ID,
        "entity_id": ENTITY_ID,
        "anomaly_score": 0.95,
        "supporting_evidence": [],
        "label": "SYNTHETIC_TEST_DATA",
    }

    # Inject a POSSIBLE identity-match row into entities_df
    # This is SYNTHETIC TEST DATA to simulate an unresolved identity match.
    possible_row = {
        "canonical_entity_id": ENTITY_ID,
        "raw_identifier": "synthetic_possible_match_TESTONLY",
        "match_status": "POSSIBLE",
        "label": "SYNTHETIC_TEST_DATA",
    }
    backend.entities_df = pd.concat(
        [backend.entities_df, pd.DataFrame([possible_row])],
        ignore_index=True,
    )

    # Create a fresh EventStore (temporary path; isolated from production events)
    event_store_path = os.path.join(tmp_dir, "data", "features5_6_events.jsonl")
    os.makedirs(os.path.dirname(event_store_path), exist_ok=True)
    event_store = EventStore(event_store_path)

    return backend, event_store
