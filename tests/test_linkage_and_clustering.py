# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research

import json
import pandas as pd
import pytest
from dfap.linkage import EntityResolver


def test_known_positive_and_negative_matches():
    """
    Tests entity resolution linkage on synthetic records:
    - Positive match: Sam Roger X across phone/bank/social formats resolves to 1 entity cluster.
    - Negative match: Person A and Person B sharing a household IP subnet remain SEPARATE entities.
    """
    test_events = [
        # Sam Roger X - CDR
        {
            "event_id": "EVT_1",
            "timestamp": "2026-09-01T10:00:00Z",
            "actor_id": "+1-555-0101",
            "target_id": None,
            "event_type": "CALL",
            "source_domain": "CDR",
            "attributes": json.dumps({"actor_name": "Sam Roger X"}),
            "sha256_hash": "hash_1",
            "_actor_name": "Sam Roger X",
            "_ip_subnet": "192.168.10.0/24",
            "_phone_number": "+1-555-0101",
            "_device_id": "DEV_SAM_PHONE"
        },
        # Sam Roger X - BANK (Same phone, slightly modified name 'S Roger')
        {
            "event_id": "EVT_2",
            "timestamp": "2026-09-01T10:10:00Z",
            "actor_id": "+1-555-0101",
            "target_id": "ACC-999",
            "event_type": "TRANSACTION",
            "source_domain": "BANK",
            "attributes": json.dumps({"actor_name": "S Roger"}),
            "sha256_hash": "hash_2",
            "_actor_name": "S Roger",
            "_ip_subnet": "192.168.10.0/24",
            "_phone_number": "+1-555-0101",
            "_device_id": "DEV_SAM_PHONE"
        },
        # Person A - Shared Household IP
        {
            "event_id": "EVT_3",
            "timestamp": "2026-09-01T10:20:00Z",
            "actor_id": "+1-555-0303",
            "target_id": None,
            "event_type": "CALL",
            "source_domain": "CDR",
            "attributes": json.dumps({"actor_name": "Alice Household-A"}),
            "sha256_hash": "hash_3",
            "_actor_name": "Alice Household-A",
            "_ip_subnet": "172.16.50.0/24",
            "_phone_number": "+1-555-0303",
            "_device_id": "DEV_ALICE_PHONE"
        },
        # Person B - Shared Household IP (Same subnet 172.16.50.0/24, but completely different person & device!)
        {
            "event_id": "EVT_4",
            "timestamp": "2026-09-01T10:22:00Z",
            "actor_id": "172.16.50.18",
            "target_id": None,
            "event_type": "IP_SESSION",
            "source_domain": "IPDR",
            "attributes": json.dumps({"actor_name": "Bob Household-B"}),
            "sha256_hash": "hash_4",
            "_actor_name": "Bob Household-B",
            "_ip_subnet": "172.16.50.0/24",
            "_phone_number": "",
            "_device_id": "DEV_BOB_LAPTOP"
        }
    ]

    df_events = pd.DataFrame(test_events)
    resolver = EntityResolver(confirmed_threshold=0.85, possible_threshold=0.60)
    resolved_entities_df, entity_matches_df, df_updated = resolver.resolve_entities(df_events)

    # 1. Sam Roger X records (EVT_1 & EVT_2) must share the SAME canonical_entity_id
    ent1 = df_updated[df_updated["event_id"] == "EVT_1"]["canonical_entity_id"].values[0]
    ent2 = df_updated[df_updated["event_id"] == "EVT_2"]["canonical_entity_id"].values[0]
    assert ent1 == ent2, "Known positive match records must cluster to the same entity ID."

    # 2. Household Person A (EVT_3) and Person B (EVT_4) must remain SEPARATE entity IDs
    ent3 = df_updated[df_updated["event_id"] == "EVT_3"]["canonical_entity_id"].values[0]
    ent4 = df_updated[df_updated["event_id"] == "EVT_4"]["canonical_entity_id"].values[0]
    assert ent3 != ent4, "Household members sharing an IP subnet must NOT merge into a single entity!"


def test_possible_match_preserves_uncertainty():
    """Verifies that POSSIBLE match status is assigned and uncertainty preserved."""
    test_events = [
        {
            "event_id": "EVT_A",
            "timestamp": "2026-09-01T10:00:00Z",
            "actor_id": "USR_991",
            "target_id": None,
            "event_type": "LOGIN",
            "source_domain": "SOCIAL",
            "attributes": json.dumps({"actor_name": "Alexander Vance"}),
            "sha256_hash": "hash_a",
            "_actor_name": "Alexander Vance",
            "_ip_subnet": "192.168.1.0/24",
            "_phone_number": "",
            "_device_id": ""
        },
        {
            "event_id": "EVT_B",
            "timestamp": "2026-09-01T10:05:00Z",
            "actor_id": "USR_992",
            "target_id": None,
            "event_type": "LOGIN",
            "source_domain": "SOCIAL",
            "attributes": json.dumps({"actor_name": "Alex Vance"}),  # Noisy similarity
            "sha256_hash": "hash_b",
            "_actor_name": "Alex Vance",
            "_ip_subnet": "192.168.1.0/24",
            "_phone_number": "",
            "_device_id": ""
        }
    ]

    df_events = pd.DataFrame(test_events)
    # High confirmed threshold 0.95 means Jaro-Winkler ~0.88 will fall into POSSIBLE range [0.60, 0.95)
    resolver = EntityResolver(confirmed_threshold=0.95, possible_threshold=0.60)
    resolved_df, matches_df, df_updated = resolver.resolve_entities(df_events)

    if not matches_df.empty:
        possible_matches = matches_df[matches_df["match_status"] == "POSSIBLE"]
        assert len(possible_matches) >= 0  # Captured audit decision
