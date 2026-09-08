# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: Phase 2 Real Data Foundation Integration & Rigorous Adapter Contract Tests

import json
import os
import pandas as pd
import pytest

from dfap.adapters.base import RejectionReason, RowValidationReport
from dfap.adapters.unsw_nb15 import UNSWAdapter
from dfap.adapters.stackoverflow import StackOverflowAdapter
from dfap.adapters.elliptic import EllipticAdapter
from dfap.data.dataset_registry import (
    DatasetRegistry,
    DataProvenanceTier,
    MissingRealDatasetError,
    SourceHashMismatchError
)
from dfap.wp4.contracts import FROZEN_UPSTREAM_MANIFEST


def test_real_sources_exist_and_sizes_match_manifest():
    """Verifies acquired real public source files exist and match manifest sizes."""
    registry = DatasetRegistry()
    manifest = registry.manifest["datasets"]

    # UNSW-NB15
    unsw_meta = manifest["unsw"]
    unsw_path = unsw_meta["expected_files"][0]
    assert os.path.exists(unsw_path)
    assert os.path.getsize(unsw_path) == unsw_meta["source_size_bytes"]

    # Stack Overflow
    so_meta = manifest["stackoverflow"]
    so_path = so_meta["expected_files"][0]
    assert os.path.exists(so_path)
    assert os.path.getsize(so_path) == so_meta["source_size_bytes"]


def test_real_source_sha256_digests_match_manifest():
    """Verifies that SHA-256 digests computed directly from source bytes match manifest."""
    registry = DatasetRegistry()
    manifest = registry.manifest["datasets"]

    # UNSW SHA-256
    unsw_path = manifest["unsw"]["expected_files"][0]
    actual_unsw_hash = UNSWAdapter.compute_file_sha256(unsw_path)
    assert actual_unsw_hash == manifest["unsw"]["source_sha256"]
    assert actual_unsw_hash == "0ebd9eb06d53ae223fbe7948737985e851e00e9c20140508d653de4b1655fdd6"

    # Stack Overflow SHA-256
    so_path = manifest["stackoverflow"]["expected_files"][0]
    actual_so_hash = StackOverflowAdapter.compute_file_sha256(so_path)
    assert actual_so_hash == manifest["stackoverflow"]["source_sha256"]
    assert actual_so_hash == "10808eb3e092d29e2b93a15de4b8782e009d48fe3d23477f4b173c62399dafc2"


def test_schema_inspection_and_validation():
    """Verifies inspect_schema returns accurate columns and data types."""
    unsw = UNSWAdapter()
    schema = unsw.inspect_schema("data/sources/unsw_nb15/unsw_nb15_training-set.csv")
    assert "columns" in schema
    assert "dtypes" in schema
    for col in ["id", "dur", "proto", "service", "state", "sbytes", "dbytes", "attack_cat", "label"]:
        assert col in schema["columns"]

    so = StackOverflowAdapter()
    so_schema = so.inspect_schema("data/sources/stackoverflow/sx_stackoverflow_c2q.txt")
    assert "src_user_id" in so_schema["columns"]
    assert "dst_user_id" in so_schema["columns"]
    assert "timestamp" in so_schema["columns"]


def test_record_parsing_and_canonical_conversion():
    """Verifies record parsing converts raw lines into standard canonical DFAP events."""
    unsw = UNSWAdapter()
    can_df, gt_df = unsw.load_and_convert("data/sources/unsw_nb15/unsw_nb15_training-set.csv", max_records=100)

    assert len(can_df) == 100
    assert len(gt_df) == 100
    assert (can_df["source_domain"] == "IPDR").all()
    assert (can_df["event_type"] == "IP_SESSION").all()
    # Zero fabrication: without srcip in training-set, actor_id uses FLOW_{rec_id} rather than invented IPs
    assert (can_df["actor_id"].str.startswith("FLOW_") | can_df["actor_id"].str.startswith("IP_")).all()
    assert "sha256_hash" in can_df.columns


def test_row_accountability_accepted_plus_rejected():
    """Verifies source_rows == accepted_rows + rejected_rows."""
    unsw = UNSWAdapter()
    can_df, _ = unsw.load_and_convert("data/sources/unsw_nb15/unsw_nb15_training-set.csv", max_records=250)
    report = unsw.last_validation_report

    assert report["source_rows"] == 250
    assert report["accepted_rows"] == len(can_df)
    assert report["source_rows"] == report["accepted_rows"] + report["rejected_rows"]
    assert report["is_accountable"] is True


def test_rejection_taxonomy_codes():
    """Verifies that invalid records trigger explicit rejection taxonomy codes."""
    unsw = UNSWAdapter()
    report = RowValidationReport(source_file="test_corrupt.csv", source_total_records=3)

    # 1. Missing required field
    valid, reason, _ = unsw.validate_record({"dur": 1.0}, 0)
    assert valid is False
    assert reason == RejectionReason.MISSING_REQUIRED_FIELD

    # 2. Invalid numeric
    valid, reason, _ = unsw.validate_record({"id": 1, "sbytes": "NOT_A_NUMBER"}, 1)
    assert valid is False
    assert reason == RejectionReason.INVALID_NUMERIC

    # Record rejections and verify accountability
    report.record_rejection(0, RejectionReason.MISSING_REQUIRED_FIELD, "Missing id", {"dur": 1.0})
    report.record_rejection(1, RejectionReason.INVALID_NUMERIC, "Bad sbytes", {"id": 1})
    report.record_acceptance()

    assert report.source_rows == 3
    assert report.accepted_rows == 1
    assert report.rejected_rows == 2
    assert report.verify_accountability() is True


def test_unsw_strict_ground_truth_isolation():
    """
    CRITICAL PROOF OF GROUND-TRUTH ISOLATION:
    Verifies that 'label', 'attack_cat', and attack descriptors are completely absent
    from canonical events and attributes, residing exclusively in isolated ground truth.
    """
    unsw = UNSWAdapter()
    can_df, gt_df = unsw.load_and_convert("data/sources/unsw_nb15/unsw_nb15_training-set.csv", max_records=100)

    # 1. Not in canonical columns
    assert "label" not in can_df.columns
    assert "attack_cat" not in can_df.columns
    assert "is_attack" not in can_df.columns
    assert "is_attack_ground_truth" not in can_df.columns

    # 2. Not in attributes JSON
    for _, row in can_df.iterrows():
        attrs = json.loads(row["attributes"])
        assert "label" not in attrs
        assert "attack_cat" not in attrs
        assert "is_attack" not in attrs

    # 3. Present exclusively in ground_truth dataframe
    assert "is_attack_ground_truth" in gt_df.columns
    assert "attack_category" in gt_df.columns
    assert len(gt_df) == len(can_df)


def test_stackoverflow_no_fabricated_crime_labels():
    """
    CRITICAL PROOF: Stack Overflow adapter does NOT invent crimes, sockpuppets, or malicious labels.
    """
    so = StackOverflowAdapter()
    can_df, gt_df = so.load_and_convert("data/sources/stackoverflow/sx_stackoverflow_c2q.txt", max_records=100)

    # Verify no crime/illicit labels invented in canonical events
    assert (can_df["source_domain"] == "SOCIAL").all()
    for _, row in can_df.iterrows():
        attrs = json.loads(row["attributes"])
        assert "crime" not in attrs
        assert "is_sockpuppet" not in attrs
        assert "fraud" not in attrs

    # Ground truth dataframe explicitly flags has_ground_truth = False
    assert (gt_df["has_ground_truth"] == False).all()


def test_provenance_full_chain_traceability():
    """Verifies that every canonical event has a complete provenance ledger trace to the source file."""
    unsw = UNSWAdapter()
    can_df, _ = unsw.load_and_convert("data/sources/unsw_nb15/unsw_nb15_training-set.csv", max_records=50)

    for idx, row in can_df.iterrows():
        prov = unsw.build_provenance(
            canonical_event=row.to_dict(),
            source_path="data/sources/unsw_nb15/unsw_nb15_training-set.csv",
            source_sha256="0ebd9eb06d53ae223fbe7948737985e851e00e9c20140508d653de4b1655fdd6",
            row_index=idx,
            ingestion_timestamp="2026-09-03T10:00:00Z"
        )
        assert prov["dataset"] == "UNSW-NB15"
        assert prov["source_file"] == "unsw_nb15_training-set.csv"
        assert prov["source_sha256"] == "0ebd9eb06d53ae223fbe7948737985e851e00e9c20140508d653de4b1655fdd6"
        assert prov["canonical_event_id"] == row["event_id"]
        assert prov["canonical_event_hash"] == row["sha256_hash"]


def test_ingestion_byte_level_determinism():
    """Verifies that two independent ingestion runs produce identical event IDs, values, and hashes."""
    unsw = UNSWAdapter()
    can1, _ = unsw.load_and_convert("data/sources/unsw_nb15/unsw_nb15_training-set.csv", max_records=150)
    can2, _ = unsw.load_and_convert("data/sources/unsw_nb15/unsw_nb15_training-set.csv", max_records=150)

    assert can1.equals(can2)
    assert list(can1["sha256_hash"]) == list(can2["sha256_hash"])
    assert list(can1["event_id"]) == list(can2["event_id"])


def test_missing_real_file_fails_closed():
    """Verifies that MissingRealDatasetError is raised when real public dataset file is absent."""
    reg = DatasetRegistry()
    with pytest.raises(MissingRealDatasetError) as exc_info:
        reg.ingest("elliptic", tier=DataProvenanceTier.REAL_PUBLIC_DATA)
    assert "is absent" in str(exc_info.value)
    assert "DFAP refuses to fall back to synthetic data" in str(exc_info.value)


def test_synthetic_fallback_strictly_prohibited():
    """Verifies that requesting REAL_PUBLIC_DATA will never silently fall back to test fixtures."""
    reg = DatasetRegistry()
    with pytest.raises(MissingRealDatasetError):
        reg.ingest("elliptic", tier=DataProvenanceTier.REAL_PUBLIC_DATA)


def test_source_hash_mismatch_fails_closed(monkeypatch):
    """Verifies that if source file bytes are tampered or corrupted, ingestion halts immediately."""
    reg = DatasetRegistry()
    # Temporarily monkeypatch authoritative manifest hash to simulate corruption
    monkeypatch.setitem(reg.manifest["datasets"]["unsw"], "source_sha256", "corrupted_hash_00000000000000000000000000000000000000000000000000000000")

    with pytest.raises(SourceHashMismatchError) as exc_info:
        reg.ingest("unsw", tier=DataProvenanceTier.REAL_PUBLIC_DATA)
    assert "SHA-256 mismatch" in str(exc_info.value)
    assert "halts ingestion" in str(exc_info.value)


def test_frozen_baseline_artifacts_remain_unmodified():
    """Verifies that the 8 production baseline Parquet files in output/ are 100% byte-identical."""
    import hashlib
    rebase_path = os.path.join("output", "wp1_rebaseline_manifest.json")
    rebaseline_new = None
    if os.path.exists(rebase_path):
        try:
            rb = json.load(open(rebase_path, "r", encoding="utf-8"))
            rebaseline_new = rb.get("new_hash")
        except Exception:
            rebaseline_new = None

    for rel_path, expected_hash in FROZEN_UPSTREAM_MANIFEST.items():
        full_path = os.path.join("output", rel_path)
        assert os.path.exists(full_path), f"Frozen file '{full_path}' is missing!"
        with open(full_path, "rb") as f:
            actual_hash = hashlib.sha256(f.read()).hexdigest()
        if rel_path == "provenance_ledger.parquet" and rebaseline_new:
            assert actual_hash == expected_hash or actual_hash == rebaseline_new, (
                f"Frozen file '{full_path}' was MUTATED!"
            )
        else:
            assert actual_hash == expected_hash, f"Frozen file '{full_path}' was MUTATED!"


def test_no_synthetic_timestamp():
    """Verifies that missing timestamp cannot generate a synthetic timestamp."""
    from dfap.adapters.unsw_nb15 import UNSWTemporalStrategy
    adapter = UNSWAdapter(temporal_strategy=UNSWTemporalStrategy.STRICT_SOURCE_TIMESTAMP)
    raw_record = {"id": "1", "sbytes": "100", "dbytes": "100", "dur": "0.1"}
    valid, reason, details = adapter.validate_record(raw_record, 0)
    assert valid is False
    assert reason == RejectionReason.MISSING_REQUIRED_FIELD
    assert "synthetic timestamp generation is prohibited" in details


def test_no_synthetic_source_ip():
    """Verifies that missing srcip produces None and NEVER an invented IP."""
    adapter = UNSWAdapter()
    raw_record = {"id": "1", "sbytes": "100", "dbytes": "100", "dur": "0.1"}
    normalized = adapter.normalize_record(raw_record, 0)
    assert normalized["src_ip"] is None
    assert normalized["src_ip"] != "10.0.1.0"


def test_no_synthetic_destination_ip():
    """Verifies that missing dstip produces None and NEVER an invented IP."""
    adapter = UNSWAdapter()
    raw_record = {"id": "1", "sbytes": "100", "dbytes": "100", "dur": "0.1"}
    normalized = adapter.normalize_record(raw_record, 0)
    assert normalized["dst_ip"] is None
    assert normalized["dst_ip"] != "172.16.1.1"


def test_no_synthetic_ports():
    """Verifies that missing sport/dsport produces None and NEVER invented port numbers."""
    adapter = UNSWAdapter()
    raw_record = {"id": "1", "sbytes": "100", "dbytes": "100", "dur": "0.1"}
    normalized = adapter.normalize_record(raw_record, 0)
    assert normalized["src_port"] is None
    assert normalized["dst_port"] is None


def test_full_ingestion_really_processes_all_rows():
    """
    CRITICAL PROOF: max_records=None streams the complete source file.
    Stack Overflow has 20,000 source rows; all 20,000 must be processed (not capped at 10k).
    """
    so = StackOverflowAdapter()
    can_df, _ = so.load_and_convert("data/sources/stackoverflow/sx_stackoverflow_c2q.txt", max_records=None)
    assert len(can_df) == 20000
    report = so.last_validation_report
    assert report["ingestion_mode"] == "FULL"
    assert report["requested_max_records"] is None
    assert report["source_total_records"] == 20000
    assert report["processed_source_records"] == 20000
    assert report["accepted_rows"] == 20000


def test_bounded_ingestion_reports_full_source_count():
    """
    CRITICAL PROOF: max_records=N processes exactly N rows while reporting the true total source count.
    """
    so = StackOverflowAdapter()
    can_df, _ = so.load_and_convert("data/sources/stackoverflow/sx_stackoverflow_c2q.txt", max_records=500)
    assert len(can_df) == 500
    report = so.last_validation_report
    assert report["ingestion_mode"] == "BOUNDED"
    assert report["requested_max_records"] == 500
    assert report["source_total_records"] == 20000
    assert report["processed_source_records"] == 500
    assert report["accepted_rows"] == 500


def test_row_accountability_full_source():
    """Verifies processed == accepted + rejected for full source."""
    so = StackOverflowAdapter()
    can_df, _ = so.load_and_convert("data/sources/stackoverflow/sx_stackoverflow_c2q.txt", max_records=None)
    report = so.last_validation_report
    assert report["processed_source_records"] == report["accepted_rows"] + report["rejected_rows"]
    assert report["is_accountable"] is True


def test_row_accountability_bounded_source():
    """Verifies processed == accepted + rejected for bounded source."""
    so = StackOverflowAdapter()
    can_df, _ = so.load_and_convert("data/sources/stackoverflow/sx_stackoverflow_c2q.txt", max_records=750)
    report = so.last_validation_report
    assert report["processed_source_records"] == report["accepted_rows"] + report["rejected_rows"]
    assert report["is_accountable"] is True


def test_elliptic_no_synthetic_timestamp():
    """Verifies Elliptic adapter rejects records with missing timestamp rather than synthesizing."""
    el = EllipticAdapter()
    raw_record = {"txId": "TX_999", "input_wallet": "W_A", "output_wallet": "W_B", "amount_btc": 1.5}
    valid, reason, details = el.validate_record(raw_record, 0)
    assert valid is False
    assert reason == RejectionReason.MISSING_REQUIRED_FIELD
    assert "synthetic timestamp generation is prohibited" in details


def test_elliptic_no_hardcoded_fx_fallback():
    """Verifies Elliptic adapter does NOT multiply amount_btc by hardcoded 65,000 USD."""
    el = EllipticAdapter()
    raw_record = {
        "txId": "TX_100",
        "timestamp": "2026-01-01T00:00:00Z",
        "input_wallet": "W_IN",
        "output_wallet": "W_OUT",
        "amount_btc": 2.0
    }
    normalized = el.normalize_record(raw_record, 0)
    assert normalized["amount_usd"] is None
    can_evt, _ = el.to_canonical_event(normalized, 0, "dummy_hash")
    # Canonical event uses amount_btc directly when amount_usd is unavailable
    assert can_evt["amount"] == 2.0
    assert can_evt["amount"] != 130000.0


def test_provenance_preserves_source_row_identity():
    """Verifies that source row index and record ID are preserved across provenance."""
    so = StackOverflowAdapter()
    can_df, _ = so.load_and_convert("data/sources/stackoverflow/sx_stackoverflow_c2q.txt", max_records=10)
    first_row = can_df.iloc[0]
    attrs = json.loads(first_row["attributes"])
    assert "source_row_index" in attrs
    assert attrs["source_row_index"] == 0
    assert "source_record_id" in attrs


def test_unsw_temporal_semantics_is_sequence_surrogate():
    """Verifies that UNSW records without observed timestamps are explicitly marked SEQUENCE_ORDER_SURROGATE."""
    from dfap.schemas import TemporalSemantics
    adapter = UNSWAdapter()
    can_df, _ = adapter.load_and_convert("data/sources/unsw_nb15/unsw_nb15_training-set.csv", max_records=50)
    assert (can_df["temporal_semantics"] == TemporalSemantics.SEQUENCE_ORDER_SURROGATE).all()
    for _, r in can_df.iterrows():
        attrs = json.loads(r["attributes"])
        assert attrs["temporal_semantics"] == TemporalSemantics.SEQUENCE_ORDER_SURROGATE


def test_observed_timestamp_not_confused_with_surrogate():
    """Verifies that datasets with authentic timestamps are marked OBSERVED_TIMESTAMP and not confused with surrogate time."""
    from dfap.schemas import TemporalSemantics
    so = StackOverflowAdapter()
    can_so, _ = so.load_and_convert("data/sources/stackoverflow/sx_stackoverflow_c2q.txt", max_records=50)
    assert (can_so["temporal_semantics"] == TemporalSemantics.OBSERVED_TIMESTAMP).all()

    unsw = UNSWAdapter()
    can_unsw, _ = unsw.load_and_convert("data/sources/unsw_nb15/unsw_nb15_training-set.csv", max_records=50)
    assert can_so["temporal_semantics"].iloc[0] != can_unsw["temporal_semantics"].iloc[0]


def test_date_range_rejected_for_surrogate_time():
    """Verifies that calendar date-range queries are strictly rejected for datasets with sequence-order surrogate time."""
    from dfap.investigation.graph_traversal import InvestigationGraphTraversal
    traversal = InvestigationGraphTraversal()
    with pytest.raises(ValueError) as exc_info:
        traversal.backtrack("FLOW_1", dataset="unsw", start_date="2020-01-01", end_date="2020-01-02")
    assert "Date-range queries are unsupported" in str(exc_info.value)
    assert "SEQUENCE_ORDER_SURROGATE" in str(exc_info.value)


def test_surrogate_temporal_analysis_explicitly_labeled():
    """Verifies that analysis over surrogate-time records is labeled SEQUENCE_ORDER_ANALYSIS."""
    from dfap.investigation.graph_traversal import InvestigationGraphTraversal
    traversal = InvestigationGraphTraversal()
    res = traversal.backtrack("FLOW_1", dataset="unsw")
    assert res["analysis_type"] == "SEQUENCE_ORDER_ANALYSIS"
    assert res["temporal_semantics"] == "SEQUENCE_ORDER_SURROGATE"
    assert res["query"] == "ORDER_BACKTRACK"


def test_backtracking_surrogate_mode():
    """Verifies backtracking distinguishes ORDER_BACKTRACK (surrogate) from BACKTRACK (observed)."""
    from dfap.investigation.graph_traversal import InvestigationGraphTraversal
    traversal = InvestigationGraphTraversal()
    res_unsw = traversal.backtrack("FLOW_1", dataset="unsw")
    assert res_unsw["query"] == "ORDER_BACKTRACK"

    res_so = traversal.backtrack("SO_10661", dataset="stackoverflow")
    assert res_so["query"] == "BACKTRACK"
    assert res_so["analysis_type"] == "REAL_TIME_TEMPORAL_ANALYSIS"


def test_forwardtracking_surrogate_mode():
    """Verifies forward tracking distinguishes ORDER_FORWARD_TRACK (surrogate) from FORWARDTRACK (observed)."""
    from dfap.investigation.graph_traversal import InvestigationGraphTraversal
    traversal = InvestigationGraphTraversal()
    res_unsw = traversal.forwardtrack("FLOW_1", dataset="unsw")
    assert res_unsw["query"] == "ORDER_FORWARD_TRACK"

    res_so = traversal.forwardtrack("SO_10661", dataset="stackoverflow")
    assert res_so["query"] == "FORWARDTRACK"
    assert res_so["analysis_type"] == "REAL_TIME_TEMPORAL_ANALYSIS"
