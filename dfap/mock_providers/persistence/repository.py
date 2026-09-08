"""
SQLite persistence for Mock Provider Subsystem.
Maintains isolated provider-side state completely independent of DFAP agency database.
"""
import json
import sqlite3
import threading
from pathlib import Path
from typing import Dict, Any, List, Optional

from dfap.mock_providers.domain.models import MockProviderRequest, ProviderRequestStatus


class MockProviderRepository:
    def __init__(self, db_path=":memory:"):
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.connection = sqlite3.connect(str(db_path), isolation_level=None, check_same_thread=False, timeout=30)
        self.connection.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self._init_db()

    def _init_db(self):
        with self.lock:
            self.connection.executescript("""
                CREATE TABLE IF NOT EXISTS provider_requests (
                    provider_request_id TEXT PRIMARY KEY,
                    agency_request_reference TEXT NOT NULL,
                    agency_case_reference TEXT NOT NULL,
                    provider_id TEXT NOT NULL,
                    dataset_type TEXT NOT NULL,
                    requested_record_categories TEXT NOT NULL,
                    date_range TEXT NOT NULL,
                    received_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    request_package_hash TEXT,
                    provider_notes TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_prov_req_agency ON provider_requests(agency_request_reference);
                
                CREATE TABLE IF NOT EXISTS webhook_logs (
                    event_id TEXT PRIMARY KEY,
                    provider_reference TEXT NOT NULL,
                    agency_request_reference TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    signature TEXT NOT NULL,
                    payload TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS provider_inbox (
                    message_id TEXT PRIMARY KEY,
                    sender TEXT NOT NULL,
                    destination TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    sent_at TEXT NOT NULL,
                    agency_request_reference TEXT NOT NULL,
                    package_hash TEXT NOT NULL,
                    attachments_json TEXT NOT NULL,
                    read_status INTEGER DEFAULT 0
                );
            """)

    def save_request(self, req: MockProviderRequest):
        with self.lock:
            status_val = req.status.value if isinstance(req.status, ProviderRequestStatus) else req.status
            self.connection.execute(
                """
                INSERT INTO provider_requests VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(provider_request_id) DO UPDATE SET
                    status=excluded.status,
                    provider_notes=excluded.provider_notes,
                    updated_at=excluded.updated_at
                """,
                (
                    req.provider_request_id,
                    req.agency_request_reference,
                    req.agency_case_reference,
                    req.provider_id,
                    req.dataset_type,
                    json.dumps(req.requested_record_categories),
                    json.dumps(req.date_range),
                    req.received_at,
                    status_val,
                    req.request_package_hash,
                    req.provider_notes,
                    req.created_at,
                    req.updated_at,
                ),
            )

    def get_request(self, provider_request_id: str) -> Optional[MockProviderRequest]:
        with self.lock:
            row = self.connection.execute("SELECT * FROM provider_requests WHERE provider_request_id=?", (provider_request_id,)).fetchone()
            if not row:
                return None
            return self._hydrate_request(row)

    def get_by_agency_reference(self, agency_request_ref: str) -> Optional[MockProviderRequest]:
        with self.lock:
            row = self.connection.execute("SELECT * FROM provider_requests WHERE agency_request_reference=?", (agency_request_ref,)).fetchone()
            if not row:
                return None
            return self._hydrate_request(row)

    def list_requests(self, provider_id: Optional[str] = None) -> List[MockProviderRequest]:
        with self.lock:
            if provider_id:
                rows = self.connection.execute("SELECT * FROM provider_requests WHERE provider_id=? ORDER BY created_at DESC", (provider_id,)).fetchall()
            else:
                rows = self.connection.execute("SELECT * FROM provider_requests ORDER BY created_at DESC").fetchall()
            return [self._hydrate_request(r) for r in rows]

    def record_webhook(self, event_id: str, provider_ref: str, agency_ref: str, event_type: str, timestamp: str, signature: str, payload: dict):
        with self.lock:
            self.connection.execute(
                "INSERT INTO webhook_logs VALUES (?,?,?,?,?,?,?)",
                (event_id, provider_ref, agency_ref, event_type, timestamp, signature, json.dumps(payload)),
            )

    def list_webhooks(self, agency_ref: Optional[str] = None) -> List[dict]:
        with self.lock:
            if agency_ref:
                rows = self.connection.execute("SELECT * FROM webhook_logs WHERE agency_request_reference=? ORDER BY timestamp DESC", (agency_ref,)).fetchall()
            else:
                rows = self.connection.execute("SELECT * FROM webhook_logs ORDER BY timestamp DESC").fetchall()
            return [dict(r) for r in rows]

    def save_inbox_message(self, message: dict):
        with self.lock:
            self.connection.execute(
                "INSERT INTO provider_inbox VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    message["message_id"],
                    message["sender"],
                    message["destination"],
                    message["subject"],
                    message["sent_at"],
                    message["agency_request_reference"],
                    message["package_hash"],
                    json.dumps(message.get("attachments", [])),
                    1 if message.get("read_status") else 0,
                ),
            )

    def list_inbox_messages(self, destination: Optional[str] = None) -> List[dict]:
        with self.lock:
            if destination:
                rows = self.connection.execute("SELECT * FROM provider_inbox WHERE destination=? ORDER BY sent_at DESC", (destination,)).fetchall()
            else:
                rows = self.connection.execute("SELECT * FROM provider_inbox ORDER BY sent_at DESC").fetchall()
            return [dict(r) for r in rows]

    def _hydrate_request(self, row) -> MockProviderRequest:
        return MockProviderRequest(
            provider_request_id=row["provider_request_id"],
            agency_request_reference=row["agency_request_reference"],
            agency_case_reference=row["agency_case_reference"],
            provider_id=row["provider_id"],
            dataset_type=row["dataset_type"],
            requested_record_categories=json.loads(row["requested_record_categories"]),
            date_range=json.loads(row["date_range"]),
            received_at=row["received_at"],
            status=ProviderRequestStatus(row["status"]),
            request_package_hash=row["request_package_hash"],
            provider_notes=row["provider_notes"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def close(self):
        with self.lock:
            self.connection.close()
