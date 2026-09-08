# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: Real Public Dataset Registry, Provenance Manifest & Ingestion Engine

import datetime
import hashlib
import json
import logging
import os
from typing import Dict, Any, List, Optional
import pandas as pd

from dfap.adapters.elliptic import EllipticAdapter
from dfap.adapters.unsw_nb15 import UNSWAdapter
from dfap.adapters.stackoverflow import StackOverflowAdapter

logger = logging.getLogger(__name__)


class DataProvenanceTier:
    REAL_PUBLIC_DATA = "REAL_PUBLIC_DATA"
    SYNTHETIC_TEST_DATA = "SYNTHETIC_TEST_DATA"
    CONTROLLED_CASE_MAPPING = "CONTROLLED_CASE_MAPPING"
    SIMULATED_RUNTIME = "SIMULATED_RUNTIME"


class DatasetRegistryError(Exception):
    """Raised when dataset registry fails validation or integrity checks."""
    pass


class MissingRealDatasetError(DatasetRegistryError):
    """Raised when authentic public dataset files are absent in REAL_PUBLIC_DATA mode."""
    pass


class SourceHashMismatchError(DatasetRegistryError):
    """Raised when computed source file SHA-256 does not match authoritative manifest hash."""
    pass


class SyntheticDataRejectedError(DatasetRegistryError):
    """Raised when synthetic test data is supplied but REAL_PUBLIC_DATA is strictly required."""
    pass


class DatasetRegistry:
    """
    Catalog, verification, and provenance ledger for public research datasets.
    Strictly distinguishes:
      - REAL_PUBLIC_DATA: Genuine external research files (Stanford, Kaggle, ACCS)
      - SYNTHETIC_TEST_DATA: Local test fixtures for unit tests in data/test_fixtures/
      - CONTROLLED_CASE_MAPPING: Cross-domain evaluation bridge in data/cases/
      - SIMULATED_RUNTIME: Dynamic streaming event simulator
    Enforces fail-closed schema integrity, SHA-256 file digests, and provenance metadata.
    """

    MANIFEST_PATH = "data/sources/manifest.json"

    ADAPTER_MAPPING = {
        "elliptic": EllipticAdapter,
        "unsw": UNSWAdapter,
        "stackoverflow": StackOverflowAdapter
    }

    FIXTURE_PATHS = {
        "elliptic": [
            "data/test_fixtures/elliptic/elliptic_txs.csv",
            "data/test_fixtures/elliptic/elliptic_classes.csv"
        ],
        "unsw": [
            "data/test_fixtures/unsw_nb15/unsw_nb15_flows.csv"
        ],
        "stackoverflow": [
            "data/test_fixtures/stackoverflow/stackoverflow_temporal.csv"
        ]
    }

    def __init__(self, canonical_dir: str = "data/canonical"):
        self.canonical_dir = canonical_dir
        os.makedirs(self.canonical_dir, exist_ok=True)
        self.manifest = self._load_manifest()

    def _load_manifest(self) -> Dict[str, Any]:
        if not os.path.exists(self.MANIFEST_PATH):
            raise DatasetRegistryError(f"Official dataset manifest missing at {self.MANIFEST_PATH}")
        with open(self.MANIFEST_PATH, "r") as f:
            return json.load(f)

    def list_datasets(self) -> List[Dict[str, Any]]:
        """Lists all registered datasets with catalog summary."""
        result = []
        for key in self.manifest.get("datasets", {}).keys():
            info = self.get_dataset_info(key)
            result.append(info)
        return result

    def get_dataset_info(self, dataset_name: str) -> Dict[str, Any]:
        """Returns verified metadata, source file hashes, and ingestion status."""
        key = dataset_name.lower().strip()
        ds_specs = self.manifest.get("datasets", {})
        if key not in ds_specs:
            raise DatasetRegistryError(f"Unknown dataset '{dataset_name}'. Registered: {list(ds_specs.keys())}")

        meta = ds_specs[key]
        expected_files = meta["expected_files"]

        # Check for real public dataset files
        real_files_exist = all(os.path.exists(f) and os.path.getsize(f) > 0 for f in expected_files)
        fixture_files_exist = all(os.path.exists(f) and os.path.getsize(f) > 0 for f in self.FIXTURE_PATHS.get(key, []))

        # Check canonical output
        can_file = os.path.join(self.canonical_dir, f"{key}_canonical.parquet")
        prov_file = os.path.join(self.canonical_dir, f"{key}_provenance_manifest.json")

        is_ingested = os.path.exists(can_file)
        ingested_count = 0
        active_tier = None

        if is_ingested:
            try:
                idf = pd.read_parquet(can_file)
                ingested_count = len(idf)
                if os.path.exists(prov_file):
                    with open(prov_file, "r") as pf:
                        p_meta = json.load(pf)
                        active_tier = p_meta.get("provenance_tier")
            except Exception:
                is_ingested = False

        return {
            "key": key,
            "name": meta["name"],
            "version": meta["version"],
            "domain": meta["domain"],
            "source_url": meta["source_url"],
            "license": meta["license"],
            "citation": meta.get("citation", ""),
            "expected_files": expected_files,
            "real_source_files_present": real_files_exist,
            "fixture_files_present": fixture_files_exist,
            "is_ingested": is_ingested,
            "ingested_record_count": ingested_count,
            "active_provenance_tier": active_tier,
            "canonical_path": can_file if is_ingested else None
        }

    def ingest(
        self,
        dataset_name: str,
        tier: str = DataProvenanceTier.REAL_PUBLIC_DATA,
        max_records: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Ingests dataset into DFAP canonical storage (data/canonical/).
        DOES NOT TOUCH FROZEN output/*.parquet FILES.
        Fails closed when authentic files are missing or corrupted in REAL_PUBLIC_DATA mode.
        """
        key = dataset_name.lower().strip()
        ds_specs = self.manifest.get("datasets", {})
        if key not in ds_specs:
            raise DatasetRegistryError(f"Unknown dataset '{dataset_name}'. Registered: {list(ds_specs.keys())}")

        meta = ds_specs[key]
        adapter_cls = self.ADAPTER_MAPPING[key]
        adapter = adapter_cls()

        if tier == DataProvenanceTier.REAL_PUBLIC_DATA:
            src_files = meta["expected_files"]
            missing = [f for f in src_files if not os.path.exists(f) or os.path.getsize(f) == 0]
            if missing:
                raise MissingRealDatasetError(
                    f"Authentic public dataset '{key}' is absent at {missing}.\n"
                    f"DFAP refuses to fall back to synthetic data in REAL_PUBLIC_DATA mode.\n"
                    f"Please acquire the real files according to docs/DATASET_ACQUISITION.md."
                )

            # Strict Source Byte Hash Verification
            expected_sha256 = meta.get("source_sha256")
            if expected_sha256:
                actual_sha256 = adapter.compute_file_sha256(src_files[0])
                if actual_sha256 != expected_sha256:
                    raise SourceHashMismatchError(
                        f"Source file '{src_files[0]}' SHA-256 mismatch!\n"
                        f"Expected authoritative hash: {expected_sha256}\n"
                        f"Actual computed hash:       {actual_sha256}\n"
                        f"DFAP halts ingestion to prevent corrupted data propagation."
                    )

            p1 = src_files[0]
            p2 = src_files[1] if len(src_files) > 1 else None
        elif tier == DataProvenanceTier.SYNTHETIC_TEST_DATA:
            src_files = self.FIXTURE_PATHS.get(key, [])
            if not src_files or not all(os.path.exists(f) for f in src_files):
                raise DatasetRegistryError(f"Test fixture files for '{key}' are absent at {src_files}")
            p1 = src_files[0]
            p2 = src_files[1] if len(src_files) > 1 else None
        else:
            raise DatasetRegistryError(f"Invalid tier '{tier}' requested.")

        # Compute SHA-256 digests of input source files
        source_hashes = {}
        for sf in src_files:
            source_hashes[os.path.basename(sf)] = adapter.compute_file_sha256(sf)

        # Inspect schema before ingestion
        schema_fingerprint = adapter.inspect_schema(p1)

        # Schema Validation: verify required columns
        req_cols = set(meta.get("required_columns", []))
        if req_cols:
            found_cols = set(schema_fingerprint["columns"])
            missing_cols = req_cols - found_cols
            if missing_cols and tier == DataProvenanceTier.REAL_PUBLIC_DATA:
                raise DatasetRegistryError(
                    f"SCHEMA_MISMATCH: Dataset '{key}' missing required columns: {missing_cols}"
                )

        # Convert records using adapter with row accountability
        can_df, gt_df = adapter.load_and_convert(p1, p2, max_records=max_records)

        validation_report = getattr(adapter, "last_validation_report", {
            "source_file": p1,
            "source_rows": len(can_df),
            "accepted_rows": len(can_df),
            "rejected_rows": 0,
            "is_accountable": True,
            "rejection_breakdown": {}
        })

        # Explicitly tag each canonical record with its provenance tier
        can_df["provenance_tier"] = tier

        can_path = os.path.join(self.canonical_dir, f"{key}_canonical.parquet")
        gt_path = os.path.join(self.canonical_dir, f"{key}_ground_truth.parquet")
        prov_path = os.path.join(self.canonical_dir, f"{key}_provenance_manifest.json")

        can_df.to_parquet(can_path, index=False)
        gt_df.to_parquet(gt_path, index=False)

        with open(can_path, "rb") as f:
            can_hash = hashlib.sha256(f.read()).hexdigest()

        raw_total_records = validation_report.get("source_total_records", len(can_df))
        processed_records = validation_report.get("processed_source_records", len(can_df))
        ingestion_mode = validation_report.get("ingestion_mode", "FULL" if max_records is None else "BOUNDED")

        # Build full provenance manifest
        provenance_manifest = {
            "dataset_key": key,
            "name": meta["name"],
            "version": meta["version"],
            "domain": meta["domain"],
            "source_url": meta["source_url"],
            "license": meta["license"],
            "citation": meta.get("citation", ""),
            "provenance_tier": tier,
            "ingestion_mode": ingestion_mode,
            "requested_max_records": max_records,
            "raw_record_count": raw_total_records,
            "processed_record_count": processed_records,
            "canonical_record_count": len(can_df),
            "canonical_records_count": len(can_df),
            "acquisition_timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "source_files": src_files,
            "source_file_hashes": source_hashes,
            "canonical_sha256": can_hash,
            "time_range": f"{can_df['timestamp'].min()} -> {can_df['timestamp'].max()}" if len(can_df) > 0 else "EMPTY",
            "schema_fingerprint": schema_fingerprint,
            "row_accountability": validation_report,
            "provenance_manifest_path": prov_path
        }

        with open(prov_path, "w") as f:
            json.dump(provenance_manifest, f, indent=2)

        return provenance_manifest
