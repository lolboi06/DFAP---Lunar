# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: Base Real Dataset Adapter Interface & Rigorous Row Accountability Contract

import abc
from enum import Enum
import hashlib
import json
import logging
from typing import Dict, Any, Tuple, Optional, Iterator, List
import pandas as pd

logger = logging.getLogger(__name__)


class RejectionReason(str, Enum):
    """Explicit WP1 Rejection Reason Taxonomy."""
    MISSING_REQUIRED_FIELD = "MISSING_REQUIRED_FIELD"
    INVALID_TIMESTAMP = "INVALID_TIMESTAMP"
    INVALID_IP = "INVALID_IP"
    INVALID_NUMERIC = "INVALID_NUMERIC"
    INVALID_EVENT_TYPE = "INVALID_EVENT_TYPE"
    DUPLICATE_SOURCE_ROW = "DUPLICATE_SOURCE_ROW"
    MALFORMED_RECORD = "MALFORMED_RECORD"
    SCHEMA_MISMATCH = "SCHEMA_MISMATCH"
    HASH_FAILURE = "HASH_FAILURE"


class RowValidationReport:
    """
    Tracks source row accountability and detailed rejection breakdown.
    Strictly distinguishes between complete source rows and processed rows under bounded ingestion.
    """

    def __init__(self, source_file: str, source_total_records: int, ingestion_mode: str = "FULL", requested_max_records: Optional[int] = None):
        self.source_file = source_file
        self.source_total_records: int = source_total_records
        self.ingestion_mode: str = ingestion_mode
        self.requested_max_records: Optional[int] = requested_max_records
        self.source_rows: int = 0  # Processed source rows
        self.accepted_rows: int = 0
        self.rejected_rows: int = 0
        self.rejection_breakdown: Dict[str, int] = {r.value: 0 for r in RejectionReason}
        self.rejections: List[Dict[str, Any]] = []

    def record_acceptance(self):
        self.source_rows += 1
        self.accepted_rows += 1

    def record_rejection(self, row_index: int, reason: RejectionReason, details: str, raw_sample: Optional[Dict[str, Any]] = None):
        self.source_rows += 1
        self.rejected_rows += 1
        self.rejection_breakdown[reason.value] = self.rejection_breakdown.get(reason.value, 0) + 1
        if len(self.rejections) < 100:
            self.rejections.append({
                "source_file": self.source_file,
                "source_row_index": row_index,
                "reason_code": reason.value,
                "details": details,
                "sample": {k: str(v) for k, v in list((raw_sample or {}).items())[:4]}
            })

    def verify_accountability(self) -> bool:
        """Verifies processed source rows == accepted_rows + rejected_rows."""
        return self.source_rows == (self.accepted_rows + self.rejected_rows)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_file": self.source_file,
            "ingestion_mode": self.ingestion_mode,
            "source_total_records": self.source_total_records,
            "requested_max_records": self.requested_max_records,
            "processed_source_records": self.source_rows,
            "source_rows": self.source_rows,
            "accepted_rows": self.accepted_rows,
            "rejected_rows": self.rejected_rows,
            "is_accountable": self.verify_accountability(),
            "rejection_breakdown": {k: v for k, v in self.rejection_breakdown.items() if v > 0},
            "sample_rejections": self.rejections[:10]
        }


class BaseDatasetAdapter(abc.ABC):
    """
    Abstract Base Class for Real Public Dataset Ingestion Adapters.
    Enforces the complete real-data ingestion contract:
    - Source inspection, record counting, streaming iteration
    - Record-level validation & normalization without synthetic field fabrication
    - Deterministic canonical event creation
    - Complete provenance recording
    - Strict ground-truth isolation
    """

    def __init__(self, dataset_name: str, domain: str):
        self.dataset_name = dataset_name
        self.domain = domain

    @abc.abstractmethod
    def load_source(self, source_path: str) -> Any:
        """Loads or opens the raw source file."""
        pass

    @abc.abstractmethod
    def inspect_schema(self, source_path: str) -> Dict[str, Any]:
        """Returns column names and inferred data types from raw source."""
        pass

    @abc.abstractmethod
    def count_records(self, source_path: str) -> int:
        """Counts total raw records in the source file without full in-memory buffering."""
        pass

    @abc.abstractmethod
    def iter_records(self, source_path: str, limit: Optional[int] = None) -> Iterator[Tuple[int, Dict[str, Any]]]:
        """Yields (row_index, raw_record_dict) from the source file."""
        pass

    @abc.abstractmethod
    def validate_record(self, raw_record: Dict[str, Any], row_index: int) -> Tuple[bool, Optional[RejectionReason], Optional[str]]:
        """Validates record against strict domain requirements. Fails on missing required fields."""
        pass

    @abc.abstractmethod
    def normalize_record(self, raw_record: Dict[str, Any], row_index: int) -> Dict[str, Any]:
        """Normalizes source fields. NEVER synthesizes missing timestamps, IPs, or ports."""
        pass

    @abc.abstractmethod
    def to_canonical_event(
        self,
        normalized_record: Dict[str, Any],
        row_index: int,
        source_sha256: str
    ) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
        """Converts normalized record into (canonical_event_dict, ground_truth_dict)."""
        pass

    @abc.abstractmethod
    def build_provenance(
        self,
        canonical_event: Dict[str, Any],
        source_path: str,
        source_sha256: str,
        row_index: int,
        ingestion_timestamp: str
    ) -> Dict[str, Any]:
        """Constructs full provenance ledger record."""
        pass

    @abc.abstractmethod
    def load_and_convert(
        self,
        source_path: str,
        aux_path: Optional[str] = None,
        max_records: Optional[int] = None
    ) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        Entry point:
        max_records=None -> Full source streaming ingestion
        max_records=N    -> Ingest at most N records
        """
        pass

    @staticmethod
    def compute_sha256(content: str) -> str:
        """Computes deterministic SHA-256 hash."""
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    @staticmethod
    def compute_file_sha256(file_path: str) -> str:
        """Computes SHA-256 directly from source bytes."""
        hasher = hashlib.sha256()
        with open(file_path, "rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        return hasher.hexdigest()
