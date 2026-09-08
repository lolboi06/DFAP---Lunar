# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research

import pytest
from dfap.provenance import compute_canonical_row_hash
from dfap.ingestion import IngestionParser


def test_hash_determinism():
    """Proves that identical row data produces identical SHA-256 evidence hashes."""
    row1 = {"call_id": "CDR_1001", "caller_num": "+1-555-0101", "duration_sec": 180}
    row2 = {"call_id": "CDR_1001", "caller_num": "+1-555-0101", "duration_sec": 180}

    hash1 = compute_canonical_row_hash("cdr.csv", 0, row1)
    hash2 = compute_canonical_row_hash("cdr.csv", 0, row2)

    assert hash1 == hash2, "Identical inputs must produce identical SHA-256 hashes."


def test_hash_changes_when_source_changes():
    """Proves that modifying any row attribute alters the SHA-256 evidence hash."""
    row1 = {"call_id": "CDR_1001", "caller_num": "+1-555-0101", "duration_sec": 180}
    row2 = {"call_id": "CDR_1001", "caller_num": "+1-555-0101", "duration_sec": 181}  # Changed value

    hash1 = compute_canonical_row_hash("cdr.csv", 0, row1)
    hash2 = compute_canonical_row_hash("cdr.csv", 0, row2)

    assert hash1 != hash2, "Altering a row value must change the computed SHA-256 hash."


def test_hash_changes_when_row_index_changes():
    """Proves that changing source row index produces a distinct hash."""
    row = {"call_id": "CDR_1001", "caller_num": "+1-555-0101", "duration_sec": 180}

    hash1 = compute_canonical_row_hash("cdr.csv", 0, row)
    hash2 = compute_canonical_row_hash("cdr.csv", 1, row)

    assert hash1 != hash2, "Different row indices must produce distinct SHA-256 hashes."


def test_deterministic_event_id_uniqueness():
    """Proves deterministic UUID5 event ID generation is unique and reproducible."""
    parser = IngestionParser()
    evt1 = parser.generate_deterministic_event_id("cdr.csv", 0)
    evt2 = parser.generate_deterministic_event_id("cdr.csv", 0)
    evt3 = parser.generate_deterministic_event_id("cdr.csv", 1)

    assert evt1 == evt2, "Identical source file and row index must produce identical event_id."
    assert evt1 != evt3, "Different row indices must produce distinct event_ids."
    assert evt1.startswith("EVT_")
