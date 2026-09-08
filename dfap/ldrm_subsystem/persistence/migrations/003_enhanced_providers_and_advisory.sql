BEGIN IMMEDIATE;
CREATE TABLE IF NOT EXISTS provider_queries (
    id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL REFERENCES requests(id),
    provider_id TEXT NOT NULL,
    query_text TEXT NOT NULL,
    received_at TEXT NOT NULL,
    response_text TEXT,
    responded_by TEXT,
    responded_at TEXT,
    scope_modified INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS provider_queries_request ON provider_queries(request_id);

CREATE TABLE IF NOT EXISTS advisory_logs (
    id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL,
    advisory_type TEXT NOT NULL,
    findings TEXT NOT NULL,
    evaluated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS advisory_logs_request ON advisory_logs(request_id);

CREATE TRIGGER IF NOT EXISTS advisory_no_update BEFORE UPDATE ON advisory_logs
BEGIN SELECT RAISE(ABORT, 'immutable advisory evaluation'); END;

CREATE TRIGGER IF NOT EXISTS advisory_no_delete BEFORE DELETE ON advisory_logs
BEGIN SELECT RAISE(ABORT, 'immutable advisory evaluation'); END;

PRAGMA user_version = 3;
COMMIT;
