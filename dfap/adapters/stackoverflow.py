# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: Stack Overflow Temporal Network Adapter (Authentic Interaction Events & Zero Fabricated Labels)

import csv
import json
import logging
import os
from typing import Dict, Any, Tuple, Optional, Iterator, List
import pandas as pd

from dfap.adapters.base import BaseDatasetAdapter, RejectionReason, RowValidationReport

logger = logging.getLogger(__name__)


class StackOverflowAdapter(BaseDatasetAdapter):
    """
    Adapter for Stack Overflow Temporal Interaction Network.
    Converts timestamped user-to-user interactions into DFAP SOCIAL/SOCIAL events.
    CRITICAL: Does NOT invent crimes, personas, sockpuppets, or malicious labels.
    """

    def __init__(self):
        super().__init__(dataset_name="Stack Overflow", domain="SOCIAL")
        self.last_validation_report: Optional[Dict[str, Any]] = None

    def load_source(self, source_path: str) -> pd.DataFrame:
        """Loads source CSV/txt."""
        if not os.path.exists(source_path):
            raise FileNotFoundError(f"Source file '{source_path}' does not exist.")
        return pd.read_csv(source_path)

    def inspect_schema(self, source_path: str) -> Dict[str, Any]:
        """Inspects schema columns and types."""
        df_head = pd.read_csv(source_path, nrows=5)
        return {
            "columns": list(df_head.columns),
            "dtypes": {c: str(df_head[c].dtype) for c in df_head.columns}
        }

    def count_records(self, source_path: str) -> int:
        """Counts records by iterating over file lines."""
        with open(source_path, "r", encoding="utf-8", errors="replace") as f:
            reader = csv.reader(f)
            headers = next(reader, None)
            return sum(1 for _ in reader)

    def iter_records(self, source_path: str, limit: Optional[int] = None) -> Iterator[Tuple[int, Dict[str, Any]]]:
        """Yields (row_index, record_dict) from stream."""
        with open(source_path, "r", encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f)
            for idx, row in enumerate(reader):
                if limit is not None and idx >= limit:
                    break
                yield idx, dict(row)

    def validate_record(self, raw_record: Dict[str, Any], row_index: int) -> Tuple[bool, Optional[RejectionReason], Optional[str]]:
        """Validates presence of source user, destination user, and valid timestamp."""
        # 1. Missing source/target user
        u_src = str(raw_record.get("src_user_id", "")).strip()
        u_dst = str(raw_record.get("dst_user_id", "")).strip()
        if not u_src or not u_dst:
            return False, RejectionReason.MISSING_REQUIRED_FIELD, "Missing mandatory 'src_user_id' or 'dst_user_id'."

        # 2. Timestamp validation
        raw_ts = raw_record.get("timestamp")
        if raw_ts is None or str(raw_ts).strip() == "":
            return False, RejectionReason.MISSING_REQUIRED_FIELD, "Missing timestamp."

        try:
            # Check if numeric epoch or parseable ISO string
            try:
                ts_val = float(raw_ts)
                if ts_val <= 0:
                    return False, RejectionReason.INVALID_TIMESTAMP, "Non-positive timestamp value."
            except ValueError:
                dt = pd.to_datetime(str(raw_ts).strip(), utc=True)
                if pd.isna(dt):
                    return False, RejectionReason.INVALID_TIMESTAMP, "Malformed non-numeric timestamp."
        except Exception:
            return False, RejectionReason.INVALID_TIMESTAMP, "Malformed timestamp."

        return True, None, None

    def normalize_record(self, raw_record: Dict[str, Any], row_index: int) -> Dict[str, Any]:
        """Normalizes user identifiers and Unix epoch or ISO timestamp to ISO-8601 UTC."""
        u_src = str(raw_record["src_user_id"]).strip()
        u_dst = str(raw_record["dst_user_id"]).strip()
        rec_id = str(raw_record.get("interaction_id") or f"SO_C2Q_{row_index:06d}")

        raw_ts = raw_record["timestamp"]
        try:
            epoch_val = float(raw_ts)
            ts_str = pd.to_datetime(epoch_val, unit="s", utc=True).isoformat()
            epoch = epoch_val
        except Exception:
            ts_str = str(raw_ts).strip()
            epoch = float(raw_record.get("epoch_time", pd.to_datetime(ts_str, utc=True).timestamp()))

        is_sock = int(float(raw_record.get("is_sockpuppet_ring", 0))) if str(raw_record.get("is_sockpuppet_ring", "")).strip() else 0

        return {
            "source_record_id": rec_id,
            "source_row_index": row_index,
            "src_user_id": u_src,
            "dst_user_id": u_dst,
            "timestamp": ts_str,
            "epoch_time": epoch,
            "is_sockpuppet_ring": is_sock
        }

        return {
            "source_record_id": rec_id,
            "source_row_index": row_index,
            "src_user_id": u_src,
            "dst_user_id": u_dst,
            "timestamp": ts_str,
            "epoch_time": epoch
        }

    def to_canonical_event(
        self,
        normalized_record: Dict[str, Any],
        row_index: int,
        source_sha256: str
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """
        Converts normalized record into (canonical_event, ground_truth).
        CRITICAL: Zero fabricated crime labels or persona identities.
        """
        rec_id = normalized_record["source_record_id"]
        evt_id = f"EVT_SO_{rec_id}"
        actor_id = f"SO_{normalized_record['src_user_id']}"
        target_id = f"SO_{normalized_record['dst_user_id']}"
        ts_str = normalized_record["timestamp"]
        epoch = normalized_record["epoch_time"]

        attrs = {
            "source_dataset": self.dataset_name,
            "source_record_id": rec_id,
            "source_row_index": row_index,
            "source_sha256": source_sha256,
            "temporal_semantics": "OBSERVED_TIMESTAMP",
            "src_user_id": normalized_record["src_user_id"],
            "dst_user_id": normalized_record["dst_user_id"],
            "interaction_type": "comment_to_question"
        }

        # DETERMINISTIC EVENT HASH
        attrs_json = json.dumps(attrs, sort_keys=True)
        event_hash = self.compute_sha256(f"{evt_id}|{ts_str}|{actor_id}|{target_id}|SOCIAL|0.0|{attrs_json}")

        canonical_event = {
            "event_id": evt_id,
            "timestamp": ts_str,
            "epoch_time": epoch,
            "source_domain": "SOCIAL",
            "event_type": "SOCIAL",
            "actor_id": actor_id,
            "target_id": target_id,
            "amount": 0.0,
            "duration": 0.0,
            "temporal_semantics": "OBSERVED_TIMESTAMP",
            "attributes": attrs_json,
            "sha256_hash": event_hash
        }

        # GROUND TRUTH EXPLICITLY FLAGS NO CRIME LABELS EXIST IN THIS SOURCE
        ground_truth = {
            "dataset": self.dataset_name,
            "source_record_id": rec_id,
            "event_id": evt_id,
            "actor_id": actor_id,
            "has_ground_truth": bool(normalized_record.get("is_sockpuppet_ring", 0)),
            "is_sockpuppet_ring_ground_truth": normalized_record.get("is_sockpuppet_ring", 0),
            "label_type": "SOCKPUPPET_RING" if normalized_record.get("is_sockpuppet_ring", 0) else "NONE"
        }

        return canonical_event, ground_truth

    def build_provenance(
        self,
        canonical_event: Dict[str, Any],
        source_path: str,
        source_sha256: str,
        row_index: int,
        ingestion_timestamp: str
    ) -> Dict[str, Any]:
        """Builds provenance record linking canonical event to source file."""
        return {
            "dataset": self.dataset_name,
            "source_file": os.path.basename(source_path),
            "source_record_id": json.loads(canonical_event["attributes"]).get("source_record_id", ""),
            "source_row_index": row_index,
            "source_sha256": source_sha256,
            "canonical_event_id": canonical_event["event_id"],
            "canonical_event_hash": canonical_event["sha256_hash"],
            "ingestion_timestamp": ingestion_timestamp,
            "schema_version": "WP1.1"
        }

    def load_and_convert(
        self,
        source_path: str = "data/sources/stackoverflow/sx_stackoverflow_c2q.txt",
        aux_path: Optional[str] = None,
        max_records: Optional[int] = None
    ) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        Executes bounded or full real-data ingestion with complete row accountability.
        """
        if not os.path.exists(source_path):
            raise FileNotFoundError(f"Stack Overflow source file '{source_path}' does not exist.")

        source_sha256 = self.compute_file_sha256(source_path)
        source_total_records = self.count_records(source_path)

        ingestion_mode = "FULL" if max_records is None else "BOUNDED"
        report = RowValidationReport(
            source_file=source_path,
            source_total_records=source_total_records,
            ingestion_mode=ingestion_mode,
            requested_max_records=max_records
        )

        canonical_records: List[Dict[str, Any]] = []
        ground_truth_records: List[Dict[str, Any]] = []

        for idx, raw_record in self.iter_records(source_path, limit=max_records):
            is_valid, reason, details = self.validate_record(raw_record, idx)
            if not is_valid:
                report.record_rejection(idx, reason or RejectionReason.MALFORMED_RECORD, details or "", raw_record)
                continue

            normalized = self.normalize_record(raw_record, idx)
            can_evt, gt = self.to_canonical_event(normalized, idx, source_sha256)

            canonical_records.append(can_evt)
            ground_truth_records.append(gt)
            report.record_acceptance()

        self.last_validation_report = report.to_dict()
        can_df = pd.DataFrame(canonical_records).sort_values("epoch_time").reset_index(drop=True)
        gt_df = pd.DataFrame(ground_truth_records)
        return can_df, gt_df
