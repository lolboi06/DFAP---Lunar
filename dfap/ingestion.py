# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research

import json
import os
import uuid
from typing import Any, Dict, List, Tuple
import pandas as pd

from dfap.provenance import compute_canonical_row_hash, SCHEMA_VERSION
from dfap.validation import RowValidationReport, validate_and_normalize_row

NAMESPACE_DFAP = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")


class IngestionParser:
    """
    Pandas/JSON Ingestion engine parsing heterogeneous source digital records (CDR, IPDR, BANK, SOCIAL)
    with strict validation, deterministic UUID5 event generation, and canonicalization.
    """

    @staticmethod
    def generate_deterministic_event_id(source_file: str, source_row_index: int) -> str:
        """
        Generates a deterministic UUID5 event_id:
        UUID5(NAMESPACE_DFAP, f"{source_file}:{source_row_index}:WP1.1")
        Ensures 100% reproducible event IDs across repeated processing runs.
        """
        stable_identity = f"{source_file}:{source_row_index}:WP1.1"
        return f"EVT_{uuid.uuid5(NAMESPACE_DFAP, stable_identity).hex[:16].upper()}"

    def parse_file(
        self, file_path: str, source_domain: str, default_event_type: str
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], RowValidationReport]:
        """Parses a single CSV or JSON file into canonical records, provenance metadata, and validation report."""
        filename = os.path.basename(file_path)
        report = RowValidationReport(filename)

        if file_path.endswith(".json"):
            with open(file_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
                df_raw = pd.DataFrame(data if isinstance(data, list) else [data])
        else:
            df_raw = pd.read_csv(file_path)

        canonical_rows = []
        provenance_metadata = []
        seen_row_hashes = set()

        for idx, raw_row in df_raw.iterrows():
            row_dict = raw_row.to_dict()
            norm_res = validate_and_normalize_row(
                row=row_dict,
                row_index=idx,
                source_domain=source_domain,
                default_event_type=default_event_type,
                report=report,
                seen_hashes=seen_row_hashes
            )

            if not norm_res:
                continue

            # Deterministic SHA-256 evidence hash
            sha256_hash = compute_canonical_row_hash(filename, idx, row_dict)
            seen_row_hashes.add(sha256_hash)

            # Deterministic UUID5 event ID
            event_id = self.generate_deterministic_event_id(filename, idx)

            # Build canonical attributes payload
            actor_name = str(row_dict.get("actor_name", row_dict.get("caller_name", row_dict.get("sender_name", row_dict.get("user_name", "")))))
            ip_subnet = str(row_dict.get("ip_subnet", row_dict.get("subnet", "0.0.0.0/0")))
            phone_num = str(row_dict.get("phone_number", row_dict.get("phone", norm_res["actor_id"] if "555" in norm_res["actor_id"] or "+" in norm_res["actor_id"] else "")))
            device_id = str(row_dict.get("device_id", row_dict.get("device", "")))

            attr_dict = {
                "actor_name": actor_name,
                "ip_subnet": ip_subnet,
                "phone_number": phone_num,
                "device_id": device_id,
                "raw_source_attributes": {k: str(v) for k, v in row_dict.items() if not pd.isna(v)}
            }

            canonical_rows.append({
                "event_id": event_id,
                "timestamp": norm_res["timestamp"],
                "actor_id": norm_res["actor_id"],
                "target_id": norm_res["target_id"],
                "event_type": norm_res["event_type"],
                "source_domain": norm_res["source_domain"],
                "attributes": json.dumps(attr_dict, sort_keys=True),
                "sha256_hash": sha256_hash,
                # Temporary internal linkage helper fields
                "_actor_name": actor_name,
                "_ip_subnet": ip_subnet,
                "_phone_number": phone_num,
                "_device_id": device_id,
                "_source_file": filename,
                "_source_row_index": idx
            })

            provenance_metadata.append({
                "sha256_hash": sha256_hash,
                "source_domain": source_domain,
                "source_file": filename,
                "source_row_index": idx
            })

        return canonical_rows, provenance_metadata, report

    def ingest_directory(self, data_dir: str) -> Tuple[pd.DataFrame, List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Ingests all files in data_dir matching CDR, IPDR, BANK, SOCIAL domains.
        Returns:
        - canonical_df: DataFrame matching canonical_events.parquet frozen schema
        - provenance_meta: List of provenance record metadata
        - validation_reports: List of dict validation reports
        """
        all_canonical = []
        all_provenance = []
        reports = []

        if not os.path.exists(data_dir):
            raise FileNotFoundError(f"Source directory not found: {data_dir}")

        for file in sorted(os.listdir(data_dir)):
            if not (file.endswith(".csv") or file.endswith(".json")):
                continue

            full_path = os.path.join(data_dir, file)
            lower_name = file.lower()

            if "cdr" in lower_name:
                c_rows, p_meta, rep = self.parse_file(full_path, "CDR", "CALL")
            elif "ipdr" in lower_name:
                c_rows, p_meta, rep = self.parse_file(full_path, "IPDR", "IP_SESSION")
            elif "bank" in lower_name:
                c_rows, p_meta, rep = self.parse_file(full_path, "BANK", "TRANSACTION")
            elif "social" in lower_name:
                c_rows, p_meta, rep = self.parse_file(full_path, "SOCIAL", "SOCIAL")
            else:
                c_rows, p_meta, rep = self.parse_file(full_path, "CDR", "CALL")

            all_canonical.extend(c_rows)
            all_provenance.extend(p_meta)
            reports.append(rep.to_dict())

        if not all_canonical:
            empty_df = pd.DataFrame(columns=[
                "event_id", "timestamp", "actor_id", "target_id",
                "event_type", "source_domain", "attributes", "sha256_hash",
                "_actor_name", "_ip_subnet", "_phone_number", "_device_id",
                "_source_file", "_source_row_index"
            ])
            return empty_df, [], reports

        df_canonical = pd.DataFrame(all_canonical)
        return df_canonical, all_provenance, reports


IngestionService = IngestionParser
