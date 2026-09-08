# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research

import pytest
from dfap.validation import (
    RowValidationReport,
    normalize_timestamp,
    validate_and_normalize_row
)


def test_timestamp_normalization():
    """Verifies timestamp normalization to UTC ISO-8601 format."""
    ts1 = normalize_timestamp("2026-09-01 10:00:00")
    ts2 = normalize_timestamp("2026-09-01T10:00:00Z")
    assert ts1 is not None and "2026-09-01" in ts1
    assert ts2 is not None and "2026-09-01" in ts2
    assert normalize_timestamp("invalid_date") is None


def test_invalid_record_rejection():
    """Tests rejection of invalid source records with explicit reason codes."""
    report = RowValidationReport("test.csv")
    seen_hashes = set()

    # 1. Missing actor_id
    bad_row1 = {"caller_num": "", "timestamp": "2026-09-01T10:00:00Z"}
    res1 = validate_and_normalize_row(bad_row1, 0, "CDR", "CALL", report, seen_hashes)
    assert res1 is None
    assert report.rejections[-1]["reason_code"] == "MISSING_REQUIRED_FIELD"

    # 2. Negative Call Duration
    bad_row2 = {"caller_num": "+1-555-0101", "timestamp": "2026-09-01T10:00:00Z", "duration_sec": -50}
    res2 = validate_and_normalize_row(bad_row2, 1, "CDR", "CALL", report, seen_hashes)
    assert res2 is None
    assert report.rejections[-1]["reason_code"] == "INVALID_DURATION"

    # 3. Negative Bank Amount
    bad_row3 = {"sender_acc": "ACC-100", "timestamp": "2026-09-01T10:00:00Z", "amount": -1000.0}
    res3 = validate_and_normalize_row(bad_row3, 2, "BANK", "TRANSACTION", report, seen_hashes)
    assert res3 is None
    assert report.rejections[-1]["reason_code"] == "INVALID_NUMERIC"

    # 4. Invalid IP format
    bad_row4 = {"src_ip": "999.888.777.666", "timestamp": "2026-09-01T10:00:00Z"}
    res4 = validate_and_normalize_row(bad_row4, 3, "IPDR", "IP_SESSION", report, seen_hashes)
    assert res4 is None
    assert report.rejections[-1]["reason_code"] == "INVALID_IP"


def test_duplicate_source_row_rejection():
    """Verifies that exact duplicate raw source rows are detected and rejected with DUPLICATE_SOURCE_ROW code."""
    report = RowValidationReport("test_dup.csv")
    seen_hashes = set()

    row_a = {"caller_num": "+1-555-0101", "timestamp": "2026-09-01T10:00:00Z", "duration_sec": 60}
    row_dup = {"caller_num": "+1-555-0101", "timestamp": "2026-09-01T10:00:00Z", "duration_sec": 60}

    res_a = validate_and_normalize_row(row_a, 0, "CDR", "CALL", report, seen_hashes)
    assert res_a is not None

    res_dup = validate_and_normalize_row(row_dup, 1, "CDR", "CALL", report, seen_hashes)
    assert res_dup is None
    assert report.rejections[-1]["reason_code"] == "DUPLICATE_SOURCE_ROW"


def test_row_accountability_metrics():
    """Verifies that received_rows == accepted_rows + rejected_rows."""
    report = RowValidationReport("sample.csv")
    seen_hashes = set()

    valid_row = {"caller_num": "+1-555-0101", "timestamp": "2026-09-01T10:00:00Z", "duration_sec": 60}
    invalid_row = {"caller_num": "", "timestamp": "2026-09-01T10:00:00Z"}

    validate_and_normalize_row(valid_row, 0, "CDR", "CALL", report, seen_hashes)
    validate_and_normalize_row(invalid_row, 1, "CDR", "CALL", report, seen_hashes)

    assert report.received_rows == 2
    assert report.accepted_rows == 1
    assert report.rejected_rows == 1
    assert report.received_rows == report.accepted_rows + report.rejected_rows
