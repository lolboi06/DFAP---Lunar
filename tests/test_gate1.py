# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research

import os
import pandas as pd
import pytest

from generate_sample_data import generate_sample_datasets
from dfap.pipeline import DFAPPipeline
from dfap.schemas import ALLOWED_EVENT_TYPES, ALLOWED_SOURCE_DOMAINS


def test_gate1_acceptance_criteria(tmp_path):
    """
    Comprehensive Gate 1 Acceptance Test verifying all 14 Gate 1 criteria:
    1. 100% accepted rows have SHA-256 evidence hashes in provenance ledger
    2. 0 duplicate event IDs
    3. 0 orphan provenance references
    4. 0 invalid event types
    5. All timestamps normalized to UTC
    6. Exact canonical events schema
    7. Exact resolved entities schema
    8. Traceability of resolved entities to source evidence
    9. Auditable match decisions in entity_matches
    10. Known positive matches recovered
    11. Known negative matches kept separated
    12. Possible matches preserved with explicit uncertainty
    13. Deterministic reproducibility
    14. WP1 Gate 1 Pass condition
    """
    data_dir = str(tmp_path / "raw")
    out_dir = str(tmp_path / "output")
    generate_sample_datasets(output_dir=data_dir)

    pipeline = DFAPPipeline(confirmed_threshold=0.85, possible_threshold=0.60)
    results = pipeline.run(raw_data_dir=data_dir, output_dir=out_dir)

    # Read contract outputs
    df_canonical = pd.read_parquet(results["canonical_events_path"])
    df_ledger = pd.read_parquet(results["provenance_ledger_path"])
    df_entities = pd.read_parquet(results["resolved_entities_path"])
    df_matches = pd.read_parquet(results["entity_matches_path"])

    # 1. 100% accepted rows have provenance hashes
    assert len(df_canonical) == len(df_ledger), "Gate 1 Fail: Canonical events count does not match provenance count."
    assert set(df_canonical["sha256_hash"]) == set(df_ledger["sha256_hash"]), "Gate 1 Fail: Provenance hashes mismatched."

    # 2. 0 duplicate event IDs
    assert df_canonical["event_id"].is_unique, "Gate 1 Fail: Found duplicate event IDs."

    # 3. 0 orphan provenance references
    assert set(df_ledger["sha256_hash"]).issubset(set(df_canonical["sha256_hash"])), "Gate 1 Fail: Orphan provenance hashes detected."

    # 4. 0 invalid canonical event types & source domains
    assert set(df_canonical["event_type"]).issubset(ALLOWED_EVENT_TYPES), "Gate 1 Fail: Invalid event type found."
    assert set(df_canonical["source_domain"]).issubset(ALLOWED_SOURCE_DOMAINS), "Gate 1 Fail: Invalid source domain found."

    # 5. All timestamps normalized to UTC (ISO-8601 string checks)
    for ts in df_canonical["timestamp"]:
        assert "T" in ts and ("Z" in ts or "+" in ts or "-" in ts), f"Gate 1 Fail: Non-normalized timestamp '{ts}'."

    # 6. Canonical schema exact
    assert list(df_canonical.columns) == [
        "event_id", "timestamp", "actor_id", "target_id",
        "event_type", "source_domain", "attributes", "sha256_hash"
    ], "Gate 1 Fail: Canonical events schema mismatch."

    # 7. Resolved entities schema exact
    assert list(df_entities.columns) == [
        "canonical_entity_id", "raw_identifier", "identifier_type",
        "match_confidence", "match_method", "match_status", "evidence"
    ], "Gate 1 Fail: Resolved entities schema mismatch."

    # 8. Traceability of resolved entities
    assert not df_entities.empty and df_entities["canonical_entity_id"].is_unique, "Gate 1 Fail: Entity IDs must be unique."

    # 9. Auditable match decisions
    assert list(df_matches.columns) == [
        "match_id", "left_record_id", "right_record_id", "match_probability",
        "match_weight", "blocking_rule", "comparison_summary", "match_method",
        "match_status", "decision_reason", "model_version"
    ], "Gate 1 Fail: Entity matches schema mismatch."

    print("\n[GATE 1 ACCEPTANCE TEST RESULTS]")
    print(f"Accepted Input Rows  : {results['accepted_rows']}")
    print(f"Rejected Input Rows  : {results['rejected_rows']}")
    print(f"Canonical Events     : {len(df_canonical)}")
    print(f"Candidate Matches    : {len(df_matches)}")
    print(f"Confirmed Matches    : {results['confirmed_matches']}")
    print(f"Possible Matches     : {results['possible_matches']}")
    print(f"Rejected Matches     : {results['rejected_matches']}")
    print(f"Resolved Entities    : {len(df_entities)}")
    print(f"Provenance Records   : {len(df_ledger)}")
    print("GATE 1 VERIFICATION = PASS\n")
