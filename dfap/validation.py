# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research

import hashlib
import json
import ipaddress
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
import pandas as pd

from dfap.schemas import ALLOWED_SOURCE_DOMAINS, ALLOWED_EVENT_TYPES


class RowValidationReport:
    """Tracks source row accountability and rejection metrics."""

    def __init__(self, source_file: str):
        self.source_file = source_file
        self.received_rows: int = 0
        self.accepted_rows: int = 0
        self.rejected_rows: int = 0
        self.rejections: List[Dict[str, Any]] = []

    def record_rejection(self, row_index: int, reason_code: str, details: str, raw_row: Dict[str, Any]):
        self.rejected_rows += 1
        self.rejections.append({
            "source_file": self.source_file,
            "source_row_index": row_index,
            "reason_code": reason_code,
            "details": details,
            "raw_row_sample": {k: str(v) for k, v in list(raw_row.items())[:5]}
        })

    def record_acceptance(self):
        self.accepted_rows += 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_file": self.source_file,
            "received": self.received_rows,
            "accepted": self.accepted_rows,
            "rejected": self.rejected_rows,
            "rejections": self.rejections
        }


def normalize_timestamp(ts_val: Any) -> Optional[str]:
    """Normalizes raw timestamp string/datetime to UTC ISO-8601 string."""
    if pd.isna(ts_val) or ts_val is None or str(ts_val).strip() == "":
        return None
    try:
        dt = pd.to_datetime(ts_val, utc=True)
        if pd.isna(dt):
            return None
        return dt.isoformat()
    except Exception:
        return None


def validate_ip_address_or_subnet(ip_str: Optional[str]) -> bool:
    """Validates IPv4/IPv6 address or CIDR subnet notation."""
    if not ip_str or pd.isna(ip_str) or str(ip_str).strip() in ("", "0.0.0.0/0", "UNKNOWN"):
        return True
    clean_ip = str(ip_str).strip()
    try:
        if "/" in clean_ip:
            ipaddress.ip_network(clean_ip, strict=False)
        else:
            ipaddress.ip_address(clean_ip)
        return True
    except ValueError:
        return False


import math

def clean_string_identifier(val: Any) -> str:
    """Strips leading/trailing whitespace and zero-width Unicode characters."""
    if val is None or pd.isna(val):
        return ""
    s = str(val).strip()
    s = re.sub(r"[\u200b\u200c\u200d\ufeff\u00a0]", "", s).strip()
    return s


def validate_and_normalize_row(
    row: Dict[str, Any],
    row_index: int,
    source_domain: str,
    default_event_type: str,
    report: RowValidationReport,
    seen_hashes: set
) -> Optional[Tuple[Dict[str, Any], str]]:
    """
    Validates a raw source row against strict WP1 domain constraints.
    Returns (normalized_dict, rejection_reason) or (normalized_dict, None) if accepted.
    """
    report.received_rows += 1

    # 1. Validate Source Domain
    if source_domain not in ALLOWED_SOURCE_DOMAINS:
        report.record_rejection(row_index, "INVALID_EVENT_TYPE", f"Invalid domain '{source_domain}'", row)
        return None

    # 2. Check for duplicate raw payload in same file
    try:
        clean_row_str = json.dumps({k: str(v) for k, v in sorted(row.items())}, sort_keys=True)
        raw_payload_hash = hashlib.sha256(clean_row_str.encode("utf-8")).hexdigest()
        if raw_payload_hash in seen_hashes:
            report.record_rejection(row_index, "DUPLICATE_SOURCE_ROW", "Exact duplicate raw source row payload", row)
            return None
        seen_hashes.add(raw_payload_hash)
    except Exception:
        pass

    # 3. Check for missing actor_id / primary identifier
    raw_actor = row.get("actor_id") or row.get("caller_num") or row.get("src_ip") or row.get("sender_acc") or row.get("user_handle") or row.get("caller") or row.get("calling_number") or row.get("source_phone") or row.get("source_ip") or row.get("sender") or row.get("from_account") or row.get("user") or row.get("username")
    
    actor_id = clean_string_identifier(raw_actor)
    if not actor_id:
        report.record_rejection(row_index, "MISSING_REQUIRED_FIELD", "Missing mandatory actor_id identifier", row)
        return None

    # 4. Validate & Normalize Timestamp
    raw_ts = row.get("timestamp") or row.get("call_time") or row.get("txn_time") or row.get("created_at")
    norm_ts = normalize_timestamp(raw_ts)
    if not norm_ts:
        report.record_rejection(row_index, "INVALID_TIMESTAMP", f"Malformed or unparseable timestamp '{raw_ts}'", row)
        return None

    # 5. Target ID (optional or required based on domain)
    raw_target = row.get("target_id") or row.get("receiver_num") or row.get("dst_ip") or row.get("beneficiary_acc") or row.get("target_handle") or row.get("callee") or row.get("called_number") or row.get("destination_phone") or row.get("destination_ip") or row.get("receiver") or row.get("to_account") or row.get("target") or row.get("mentioned_user")
    
    target_id = clean_string_identifier(raw_target) if raw_target and not pd.isna(raw_target) else None
    if target_id == "":
        target_id = None

    # 6. Validate Event Type
    event_type = str(row.get("event_type", default_event_type)).upper()
    if event_type not in ALLOWED_EVENT_TYPES:
        report.record_rejection(row_index, "INVALID_EVENT_TYPE", f"Event type '{event_type}' not in frozen vocabulary", row)
        return None

    # 7. Domain-specific validation (Numeric/IP/Duration)
    if source_domain == "CDR":
        duration = row.get("duration_sec", row.get("duration", 0))
        try:
            if duration is None or pd.isna(duration):
                report.record_rejection(row_index, "INVALID_NUMERIC", "Missing or NaN duration", row)
                return None
            dur_f = float(duration)
            if math.isnan(dur_f) or math.isinf(dur_f):
                report.record_rejection(row_index, "INVALID_NUMERIC", f"Non-finite duration value '{duration}'", row)
                return None
            if dur_f < 0:
                report.record_rejection(row_index, "INVALID_DURATION", f"Negative call duration '{duration}'", row)
                return None
        except (ValueError, TypeError):
            report.record_rejection(row_index, "INVALID_NUMERIC", f"Invalid duration numeric value '{duration}'", row)
            return None

    elif source_domain == "BANK":
        amount = row.get("amount", row.get("transaction_amount", 0.0))
        try:
            if amount is None or pd.isna(amount):
                report.record_rejection(row_index, "INVALID_NUMERIC", "Missing or NaN amount", row)
                return None
            amt_f = float(amount)
            if math.isnan(amt_f) or math.isinf(amt_f):
                report.record_rejection(row_index, "INVALID_NUMERIC", f"Non-finite banking amount '{amount}'", row)
                return None
            if amt_f < 0:
                report.record_rejection(row_index, "INVALID_NUMERIC", f"Negative banking transaction amount '{amount}'", row)
                return None
        except (ValueError, TypeError):
            report.record_rejection(row_index, "INVALID_NUMERIC", f"Invalid numeric amount '{amount}'", row)
            return None

    elif source_domain == "IPDR":
        src_ip = row.get("src_ip", row.get("source_ip", actor_id))
        dst_ip = row.get("dst_ip", row.get("destination_ip", target_id))
        if src_ip and not validate_ip_address_or_subnet(src_ip):
            report.record_rejection(row_index, "INVALID_IP", f"Invalid IP address format '{src_ip}'", row)
            return None
        if dst_ip and not validate_ip_address_or_subnet(dst_ip):
            report.record_rejection(row_index, "INVALID_IP", f"Invalid IP address format '{dst_ip}'", row)
            return None

    report.record_acceptance()
    
    normalized_record = {
        "source_domain": source_domain,
        "event_type": event_type,
        "timestamp": norm_ts,
        "actor_id": actor_id,
        "target_id": target_id,
        "raw_row": row
    }
    return normalized_record
