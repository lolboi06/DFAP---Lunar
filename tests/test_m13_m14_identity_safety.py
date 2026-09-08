# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research

import json
import pandas as pd
from dfap.linkage import EntityResolver
from dfap.investigation.workspace import InvestigationWorkspaceBackend
from dfap.investigation.copilot import InvestigationCopilot
import os


def test_m13_m14_identity_safety_fixture(tmp_path):
    """Controlled synthetic M13/M14 identity-safety fixture using real resolver outputs."""
    # Recreate deterministic events (same as ambiguity test)
    test_events = [
        {"event_id": "EVT_CONF_1", "timestamp": "2026-09-02T09:00:00Z", "actor_id": "+1-800-2000", "target_id": None, "event_type": "TRANSACTION", "source_domain": "BANK", "attributes": json.dumps({"actor_name": "Verified Merchant"}), "sha256_hash": "h_conf_1", "_actor_name": "Verified Merchant", "_ip_subnet": "10.0.0.0/24", "_device_id": "DEV_CONF_PHONE"},
        {"event_id": "EVT_CONF_2", "timestamp": "2026-09-02T09:05:00Z", "actor_id": "+1-800-2000", "target_id": "ACC-200", "event_type": "TRANSACTION", "source_domain": "BANK", "attributes": json.dumps({"actor_name": "Verified Merchant"}), "sha256_hash": "h_conf_2", "_actor_name": "Verified Merchant", "_ip_subnet": "10.0.0.0/24", "_device_id": "DEV_CONF_PHONE"},
        {"event_id": "EVT_AMB_1", "timestamp": "2026-09-02T10:00:00Z", "actor_id": "USR_ALPHA_991", "target_id": None, "event_type": "LOGIN", "source_domain": "SOCIAL", "attributes": json.dumps({"actor_name": "Alexandra V."}), "sha256_hash": "h_amb_1", "_actor_name": "Alexandra V.", "_ip_subnet": "192.168.77.0/24", "_device_id": "DEV_ALPHA_PHONE"},
        {"event_id": "EVT_AMB_2", "timestamp": "2026-09-02T10:05:00Z", "actor_id": "USR_ALPHA_992", "target_id": None, "event_type": "LOGIN", "source_domain": "SOCIAL", "attributes": json.dumps({"actor_name": "Alex V."}), "sha256_hash": "h_amb_2", "_actor_name": "Alex V.", "_ip_subnet": "192.168.77.0/24", "_device_id": "DEV_ALPHA_BROWSER"},
        {"event_id": "EVT_SIM_1", "timestamp": "2026-09-02T11:00:00Z", "actor_id": "SIM_USER_1", "target_id": None, "event_type": "LOGIN", "source_domain": "SOCIAL", "attributes": json.dumps({"actor_name": "Sam Sim"}), "sha256_hash": "h_sim_1", "_actor_name": "Sam Sim", "_ip_subnet": "10.10.10.0/24", "_device_id": "DEV_SIM_1"},
        {"event_id": "EVT_SIM_2", "timestamp": "2026-09-02T11:05:00Z", "actor_id": "SIM_USER_2", "target_id": None, "event_type": "LOGIN", "source_domain": "SOCIAL", "attributes": json.dumps({"actor_name": "S. Sim"}), "sha256_hash": "h_sim_2", "_actor_name": "S. Sim", "_ip_subnet": "10.10.10.0/24", "_device_id": "DEV_SIM_2"},
    ]

    df_events = pd.DataFrame(test_events)
    resolver = EntityResolver(confirmed_threshold=0.85, possible_threshold=0.60)
    resolved_entities_df, entity_matches_df, canonical_df_updated = resolver.resolve_entities(df_events)

    # Write outputs into a temporary output directory so backend loads them as authoritative
    out_dir = str(tmp_path / "output")
    os.makedirs(out_dir, exist_ok=True)
    resolved_entities_df.to_parquet(os.path.join(out_dir, "resolved_entities.parquet"), index=False)
    entity_matches_df.to_parquet(os.path.join(out_dir, "entity_matches.parquet"), index=False)
    canonical_df_updated.to_parquet(os.path.join(out_dir, "canonical_events.parquet"), index=False)

    # Instantiate backend which will load the above authoritative artifacts from the tmp output
    backend = InvestigationWorkspaceBackend(output_dir=out_dir)

    # Create a controlled synthetic case using the confirmed canonical entity
    # Pick confirmed canonical entity from resolved_entities for the confirmed phone
    confirmed_row = resolved_entities_df[resolved_entities_df["raw_identifier"].str.contains("800-2000")].iloc[0]
    confirmed_canon = confirmed_row["canonical_entity_id"]
    case_data = {
        "case_id": "CASE-SYN-IDENT-001",
        "canonical_entity_id": confirmed_canon,
        "mapping_status": "CONTROLLED_CASE_MAPPING",
        "search_context": {"source": "SYNTHETIC_TEST_FIXTURE", "domain_evidence_breakdown": {"bank": {"anomaly_score": 0.9}}}
    }
    # Attach the resolver-produced candidate match ids into the case so Q3 is scoped to them only.
    # Identify the two pairs we expect: EVT_AMB_1<->EVT_AMB_2 and EVT_SIM_1<->EVT_SIM_2
    candidate_rows = entity_matches_df[
        (entity_matches_df["left_record_id"].isin(["EVT_AMB_1", "EVT_AMB_2", "EVT_SIM_1", "EVT_SIM_2"])) |
        (entity_matches_df["right_record_id"].isin(["EVT_AMB_1", "EVT_AMB_2", "EVT_SIM_1", "EVT_SIM_2"]))
    ]
    candidate_match_ids = candidate_rows["match_id"].dropna().astype(str).unique().tolist()
    if candidate_match_ids:
        case_data["identity_candidate_match_ids"] = candidate_match_ids
    case = backend.register_controlled_case(case_data)

    copilot = InvestigationCopilot(backend)

    # A. Is this the same entity across all domains? (should be NOT_CONFIRMED for ambiguous parts)
    a = copilot.ask("Is this the same entity across all domains?", case_id=case.case_id, entity_id=case.canonical_entity_id)
    assert a["status"] in {"GROUNDED", "NOT_CONFIRMED", "PARTIALLY_GROUNDED", "INSUFFICIENT_EVIDENCE"}
    # If the copilot asserts GROUNDED, it must supply non-empty evidence and provenance refs
    if a["status"] == "GROUNDED":
        assert isinstance(a.get("evidence_refs", []), list) and len(a.get("evidence_refs", [])) > 0
        assert isinstance(a.get("provenance_refs", []), list) and len(a.get("provenance_refs", [])) > 0

    # B. What evidence proves the identities match?
    b = copilot.ask("What evidence proves the identities match?", case_id=case.case_id, entity_id=case.canonical_entity_id)
    # If confirmed evidence exists, it must be authoritative (provenance refs present)
    assert isinstance(b.get("evidence_refs", []), list)
    if b.get("evidence_refs"):
        assert isinstance(b.get("provenance_refs", []), list) and len(b.get("provenance_refs", [])) > 0

    # C. What identifiers are uncertain?
    c = copilot.ask("What identifiers are uncertain?", case_id=case.case_id, entity_id=case.canonical_entity_id)
    # Regression: Q3 must enumerate ambiguous/rejected pairwise relationships for the case
    assert ("ambiguous_identifiers" in c and c.get("ambiguous_identifiers")) or ("pairwise_records" in c and c.get("pairwise_records")) or c["status"] in {"NOT_CONFIRMED", "PARTIALLY_GROUNDED", "INSUFFICIENT_EVIDENCE"}

    # Stronger regression checks: ensure pairwise_records and ambiguous_identifiers are returned and populated
    assert isinstance(c.get("pairwise_records", []), list) and len(c.get("pairwise_records", [])) > 0, "pairwise_records must be present and non-empty for Q3"
    assert isinstance(c.get("ambiguous_identifiers", []), list) and len(c.get("ambiguous_identifiers", [])) > 0, "ambiguous_identifiers must be present and non-empty for Q3"
    # Ensure evidence and provenance refs are present
    assert isinstance(c.get("evidence_refs", []), list) and len(c.get("evidence_refs", [])) > 0
    assert isinstance(c.get("provenance_refs", []), list) and len(c.get("provenance_refs", [])) > 0
    # Ensure expected rejected pair relationships are present and unrelated matches excluded
    expected_event_ids = {"EVT_AMB_1", "EVT_AMB_2", "EVT_SIM_1", "EVT_SIM_2"}
    for rec in c.get("pairwise_records", []):
        assert rec.get("left_record_id") in expected_event_ids or rec.get("right_record_id") in expected_event_ids

    # D. What should be verified before treating these records as one entity?
    d = copilot.ask("What should be verified before treating these records as one entity?", case_id=case.case_id, entity_id=case.canonical_entity_id)
    assert "verify" in d.get("suggested_next_actions", [""])[0].lower() or d["status"] in {"PARTIALLY_GROUNDED", "INSUFFICIENT_EVIDENCE"}

    # Caller-supplied canonical ID rejection: attempting to create a case with an unknown canonical entity must fail
    try:
        backend.create_case("ENT_FAKE_0000")
        raise AssertionError("create_case must reject unknown canonical entity supplied by caller")
    except ValueError:
        pass
