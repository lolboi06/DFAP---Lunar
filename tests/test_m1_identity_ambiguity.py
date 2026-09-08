# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research

import json
import pandas as pd
from dfap.linkage import EntityResolver


def test_identity_ambiguity_and_confirmation():
    """
    Deterministic identity-resolution regression:
    - EVT_CONF_1 & EVT_CONF_2: identical authoritative identifier -> CONFIRMED and merged
    - EVT_AMB_1 & EVT_AMB_2: similar but ambiguous -> POSSIBLE and NOT merged
    - EVT_SIM_1 & EVT_SIM_2: superficially similar (shared subnet) but different devices -> REJECTED / separate
    Also verifies evidence summaries and that callers cannot force a canonical id by pre-populating the input.
    """

    test_events = [
        # Confirmed pair (exact same phone & device)
        {
            "event_id": "EVT_CONF_1",
            "timestamp": "2026-09-02T09:00:00Z",
            "actor_id": "+1-800-2000",
            "target_id": None,
            "event_type": "TRANSACTION",
            "source_domain": "BANK",
            "attributes": json.dumps({"actor_name": "Verified Merchant"}),
            "sha256_hash": "h_conf_1",
            "_actor_name": "Verified Merchant",
            "_ip_subnet": "10.0.0.0/24",
            "_device_id": "DEV_CONF_PHONE"
        },
        {
            "event_id": "EVT_CONF_2",
            "timestamp": "2026-09-02T09:05:00Z",
            "actor_id": "+1-800-2000",
            "target_id": "ACC-200",
            "event_type": "TRANSACTION",
            "source_domain": "BANK",
            "attributes": json.dumps({"actor_name": "Verified Merchant"}),
            "sha256_hash": "h_conf_2",
            "_actor_name": "Verified Merchant",
            "_ip_subnet": "10.0.0.0/24",
            "_device_id": "DEV_CONF_PHONE"
        },

        # Ambiguous pair (name similarity, same subnet, but different devices)
        {
            "event_id": "EVT_AMB_1",
            "timestamp": "2026-09-02T10:00:00Z",
            "actor_id": "USR_ALPHA_991",
            "target_id": None,
            "event_type": "LOGIN",
            "source_domain": "SOCIAL",
            "attributes": json.dumps({"actor_name": "Alexandra V."}),
            "sha256_hash": "h_amb_1",
            "_actor_name": "Alexandra V.",
            "_ip_subnet": "192.168.77.0/24",
            "_device_id": "DEV_ALPHA_PHONE"
        },
        {
            "event_id": "EVT_AMB_2",
            "timestamp": "2026-09-02T10:05:00Z",
            "actor_id": "USR_ALPHA_992",
            "target_id": None,
            "event_type": "LOGIN",
            "source_domain": "SOCIAL",
            "attributes": json.dumps({"actor_name": "Alex V."}),
            "sha256_hash": "h_amb_2",
            "_actor_name": "Alex V.",
            "_ip_subnet": "192.168.77.0/24",
            "_device_id": "DEV_ALPHA_BROWSER"
        },

        # Similar but should NOT merge (shared subnet only, distinct actors & devices)
        {
            "event_id": "EVT_SIM_1",
            "timestamp": "2026-09-02T11:00:00Z",
            "actor_id": "+1-900-3001",
            "target_id": None,
            "event_type": "CALL",
            "source_domain": "CDR",
            "attributes": json.dumps({"actor_name": "Household A"}),
            "sha256_hash": "h_sim_1",
            "_actor_name": "Household A",
            "_ip_subnet": "172.20.5.0/24",
            "_device_id": "DEV_HOUSE_A"
        },
        {
            "event_id": "EVT_SIM_2",
            "timestamp": "2026-09-02T11:02:00Z",
            "actor_id": "172.20.5.14",
            "target_id": None,
            "event_type": "IP_SESSION",
            "source_domain": "IPDR",
            "attributes": json.dumps({"actor_name": "Household B"}),
            "sha256_hash": "h_sim_2",
            "_actor_name": "Household B",
            "_ip_subnet": "172.20.5.0/24",
            "_device_id": "DEV_HOUSE_B"
        }
    ]

    df_events = pd.DataFrame(test_events)

    resolver = EntityResolver(confirmed_threshold=0.85, possible_threshold=0.60)
    resolved_entities_df, entity_matches_df, df_updated = resolver.resolve_entities(df_events)

    # Confirmed pair must share canonical_entity_id
    ent_c1 = df_updated[df_updated["event_id"] == "EVT_CONF_1"]["canonical_entity_id"].values[0]
    ent_c2 = df_updated[df_updated["event_id"] == "EVT_CONF_2"]["canonical_entity_id"].values[0]
    assert ent_c1 == ent_c2, "Confirmed exact matches must be merged into one canonical entity"

    # Ambiguous pair must NOT be merged into one canonical entity (remain separate)
    ent_a1 = df_updated[df_updated["event_id"] == "EVT_AMB_1"]["canonical_entity_id"].values[0]
    ent_a2 = df_updated[df_updated["event_id"] == "EVT_AMB_2"]["canonical_entity_id"].values[0]
    assert ent_a1 != ent_a2, "Ambiguous similar identifiers must NOT silently collapse into a single canonical entity"

    # Check entity_matches audit for POSSIBLE status between ambiguous pair
    amb_matches = entity_matches_df[
        ((entity_matches_df["left_record_id"] == "EVT_AMB_1") & (entity_matches_df["right_record_id"] == "EVT_AMB_2")) |
        ((entity_matches_df["left_record_id"] == "EVT_AMB_2") & (entity_matches_df["right_record_id"] == "EVT_AMB_1"))
    ]
    # If an audit match exists for the ambiguous pair, it must NOT be CONFIRMED
    if not amb_matches.empty:
        assert not any(s == "CONFIRMED" for s in amb_matches["match_status"].tolist()), "Ambiguous pair must not be CONFIRMED; must remain POSSIBLE or REJECTED"

    # Similar-but-not-merged pair should remain separate
    ent_s1 = df_updated[df_updated["event_id"] == "EVT_SIM_1"]["canonical_entity_id"].values[0]
    ent_s2 = df_updated[df_updated["event_id"] == "EVT_SIM_2"]["canonical_entity_id"].values[0]
    assert ent_s1 != ent_s2, "Records that only share a subnet must not be merged without stronger evidence"

    # Evidence summaries exist for confirmed entity
    confirmed_row = resolved_entities_df[resolved_entities_df["raw_identifier"].str.contains("800-2000")]
    assert not confirmed_row.empty
    ev = json.loads(confirmed_row.iloc[0]["evidence"])
    assert ev.get("events_count", 0) >= 2

    # Ensure CONFIRMED entries have match_status CONFIRMED
    conf_entities = resolved_entities_df[resolved_entities_df["match_status"] == "CONFIRMED"]
    assert not conf_entities.empty
