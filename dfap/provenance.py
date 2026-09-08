# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research

import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List
import pandas as pd

SCHEMA_VERSION = "WP1.1"


def compute_canonical_row_hash(source_file: str, source_row_index: int, raw_row: Dict[str, Any]) -> str:
    """
    Computes a deterministic SHA-256 evidence hash committing to the entire canonical source row payload.

    Canonical Hash Payload Construction:
    - Sorted JSON keys
    - Compact separators (',', ':')
    - UTF-8 encoding
    - Explicit schema version, source file, row index, and row fields.

    Note: These SHA-256 hashes represent row-level cryptographic evidence hashes.
    A full Merkle tree/root construction is a downstream responsibility.
    """
    # Clean dictionary to ensure stable string representation of types
    clean_row = {}
    for k in sorted(raw_row.keys()):
        val = raw_row[k]
        if pd.isna(val):
            clean_row[k] = None
        else:
            clean_row[k] = str(val)

    canonical_payload = {
        "schema_version": SCHEMA_VERSION,
        "source_file": str(source_file),
        "source_row_index": int(source_row_index),
        "row": clean_row
    }

    serialized_bytes = json.dumps(
        canonical_payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True
    ).encode("utf-8")

    return hashlib.sha256(serialized_bytes).hexdigest()


compute_canonical_event_hash = compute_canonical_row_hash


def generate_provenance_ledger(accepted_records_meta: List[Dict[str, Any]], ingestion_ts: str) -> pd.DataFrame:
    """
    Generates the official provenance_ledger DataFrame.

    Required schema:
    sha256_hash, source_id, source_file, source_row_index, ingestion_timestamp, schema_version
    """
    ledger_rows = []
    for rec in accepted_records_meta:
        ledger_rows.append({
            "sha256_hash": rec["sha256_hash"],
            "source_id": str(rec.get("source_domain", rec.get("source_id", "UNKNOWN"))),
            "source_file": str(rec["source_file"]),
            "source_row_index": int(rec["source_row_index"]),
            "ingestion_timestamp": ingestion_ts,
            "schema_version": SCHEMA_VERSION
        })

    return pd.DataFrame(ledger_rows, columns=[
        "sha256_hash", "source_id", "source_file", "source_row_index", "ingestion_timestamp", "schema_version"
    ])


def export_provenance_ledger(ledger_df: pd.DataFrame, output_path: str) -> str:
    """Exports provenance ledger DataFrame to parquet output contract."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    ledger_df.to_parquet(output_path, index=False)
    return output_path
