# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: Elliptic++ Bitcoin Transaction Network Adapter (Full Adapter Contract & Ground Truth Isolation)

import csv
import json
import logging
import os
from typing import Dict, Any, Tuple, Optional, Iterator, List
import pandas as pd

from dfap.adapters.base import BaseDatasetAdapter, RejectionReason, RowValidationReport

logger = logging.getLogger(__name__)


class EllipticAdapter(BaseDatasetAdapter):
    """
    Adapter for Elliptic++ Bitcoin Transaction Graph Dataset.
    Converts raw Bitcoin transaction flows into DFAP BANK/CRYPTO_TRANSFER events.
    ZERO FABRICATION: Does not invent USD conversion rates or fallback timestamps.
    Isolates illicit/licit ground-truth labels into a separate verification ledger.
    """

    def __init__(self):
        super().__init__(dataset_name="Elliptic++", domain="BANK")
        self.last_validation_report: Optional[Dict[str, Any]] = None

    def load_source(self, source_path: str) -> pd.DataFrame:
        """Loads raw source CSV."""
        if not os.path.exists(source_path):
            raise FileNotFoundError(f"Source file '{source_path}' does not exist.")
        return pd.read_csv(source_path)

    def inspect_schema(self, source_path: str) -> Dict[str, Any]:
        """Inspects columns and inferred types."""
        df_head = pd.read_csv(source_path, nrows=5)
        return {
            "columns": list(df_head.columns),
            "dtypes": {c: str(df_head[c].dtype) for c in df_head.columns}
        }

    def count_records(self, source_path: str) -> int:
        """Counts records in source file."""
        with open(source_path, "r", encoding="utf-8-sig", errors="replace") as f:
            reader = csv.reader(f)
            next(reader, None)
            return sum(1 for _ in reader)

    def iter_records(self, source_path: str, limit: Optional[int] = None) -> Iterator[Tuple[int, Dict[str, Any]]]:
        """Yields (row_index, record_dict) from stream."""
        with open(source_path, "r", encoding="utf-8-sig", errors="replace") as f:
            reader = csv.DictReader(f)
            for idx, row in enumerate(reader):
                if limit is not None and idx >= limit:
                    break
                yield idx, dict(row)

    def validate_record(self, raw_record: Dict[str, Any], row_index: int) -> Tuple[bool, Optional[RejectionReason], Optional[str]]:
        """Validates transaction ID, wallets, timestamp, and amounts."""
        if "txId" not in raw_record:
            return False, RejectionReason.MISSING_REQUIRED_FIELD, "Missing 'txId'."
        if "input_wallet" not in raw_record or "output_wallet" not in raw_record:
            return False, RejectionReason.MISSING_REQUIRED_FIELD, "Missing wallet endpoints."

        # Strict timestamp check - no synthetic fallback
        raw_ts = raw_record.get("timestamp")
        if raw_ts is None or str(raw_ts).strip() == "":
            return False, RejectionReason.MISSING_REQUIRED_FIELD, "Missing mandatory timestamp; synthetic timestamp generation is prohibited."

        try:
            amt = float(raw_record.get("amount_btc", 0.0))
            if amt < 0.0:
                return False, RejectionReason.INVALID_NUMERIC, "Negative Bitcoin amount."
        except (ValueError, TypeError):
            return False, RejectionReason.INVALID_NUMERIC, "Non-numeric amount."

        return True, None, None

    def normalize_record(self, raw_record: Dict[str, Any], row_index: int) -> Dict[str, Any]:
        """Normalizes transaction identifiers and amounts without inventing FX values."""
        raw_tx = str(raw_record["txId"]).strip()
        ts_str = str(raw_record["timestamp"]).strip()
        epoch = float(raw_record.get("epoch_time", pd.to_datetime(ts_str, utc=True).timestamp()))
        src_wallet = str(raw_record["input_wallet"]).strip()
        dst_wallet = str(raw_record["output_wallet"]).strip()
        amt_btc = float(raw_record.get("amount_btc", 0.0))

        # NO HARDCODED USD ESTIMATION
        amt_usd = float(raw_record["amount_usd"]) if "amount_usd" in raw_record and pd.notna(raw_record["amount_usd"]) else None
        fee = float(raw_record.get("fee_btc", 0.0)) if "fee_btc" in raw_record and pd.notna(raw_record["fee_btc"]) else 0.0
        timestep = int(raw_record.get("timestep", 1)) if str(raw_record.get("timestep", "")).isdigit() else 1

        return {
            "source_record_id": raw_tx,
            "source_row_index": row_index,
            "timestamp": ts_str,
            "epoch_time": epoch,
            "src_wallet": src_wallet,
            "dst_wallet": dst_wallet,
            "amount_btc": amt_btc,
            "amount_usd": amt_usd,
            "fee_btc": fee,
            "timestep": timestep
        }

    def to_canonical_event(
        self,
        normalized_record: Dict[str, Any],
        row_index: int,
        source_sha256: str
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """Converts normalized record into (canonical_event, ground_truth)."""
        raw_tx = normalized_record["source_record_id"]
        evt_id = f"EVT_EL_{raw_tx[:16]}"
        actor_id = f"WALLET_{normalized_record['src_wallet']}"
        target_id = f"WALLET_{normalized_record['dst_wallet']}"
        ts_str = normalized_record["timestamp"]
        epoch = normalized_record["epoch_time"]
        amt_value = normalized_record["amount_usd"] if normalized_record["amount_usd"] is not None else normalized_record["amount_btc"]

        attrs = {
            "source_dataset": self.dataset_name,
            "source_record_id": raw_tx,
            "source_row_index": row_index,
            "source_sha256": source_sha256,
            "amount_btc": normalized_record["amount_btc"],
            "amount_usd": normalized_record["amount_usd"],
            "fee_btc": normalized_record["fee_btc"],
            "timestep": normalized_record["timestep"]
        }

        attrs_json = json.dumps(attrs, sort_keys=True)
        event_hash = self.compute_sha256(f"{evt_id}|{ts_str}|{actor_id}|{target_id}|{amt_value}|{attrs_json}")

        canonical_event = {
            "event_id": evt_id,
            "timestamp": ts_str,
            "epoch_time": epoch,
            "source_domain": "BANK",
            "event_type": "TRANSACTION",
            "actor_id": actor_id,
            "target_id": target_id,
            "amount": amt_value,
            "duration": 0.0,
            "attributes": attrs_json,
            "sha256_hash": event_hash
        }

        ground_truth = {
            "dataset": self.dataset_name,
            "source_record_id": raw_tx,
            "event_id": evt_id,
            "actor_id": actor_id,
            "target_id": target_id,
            "is_illicit_ground_truth": 0,
            "class_label": "unknown",
            "label_type": "FINANCIAL_ILLICIT"
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
        source_path: str = "data/sources/elliptic/elliptic_txs.csv",
        aux_path: Optional[str] = "data/sources/elliptic/elliptic_classes.csv",
        max_records: Optional[int] = None
    ) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """Loads and converts Elliptic records with row accountability."""
        if not os.path.exists(source_path):
            raise FileNotFoundError(f"Source file '{source_path}' does not exist.")

        classes_df = pd.read_csv(aux_path) if aux_path and os.path.exists(aux_path) else pd.DataFrame()
        class_map = {}
        if not classes_df.empty:
            for _, r in classes_df.iterrows():
                class_map[str(r["txId"])] = {
                    "class": str(r.get("class", "unknown")),
                    "label_name": str(r.get("label_name", "unknown"))
                }

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

            # Enrich ground truth from auxiliary classes if available
            tx_id = normalized["source_record_id"]
            if tx_id in class_map:
                c_info = class_map[tx_id]
                gt["class_label"] = c_info["class"]
                gt["is_illicit_ground_truth"] = 1 if c_info["class"] in ("1", "illicit") else 0

            canonical_records.append(can_evt)
            ground_truth_records.append(gt)
            report.record_acceptance()

        self.last_validation_report = report.to_dict()
        can_df = pd.DataFrame(canonical_records).sort_values("epoch_time").reset_index(drop=True)
        gt_df = pd.DataFrame(ground_truth_records)
        return can_df, gt_df
