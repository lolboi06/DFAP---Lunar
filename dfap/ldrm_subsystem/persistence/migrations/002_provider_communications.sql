BEGIN IMMEDIATE;
CREATE TABLE IF NOT EXISTS communication_events (
    provider_id TEXT NOT NULL, event_id TEXT NOT NULL, request_id TEXT NOT NULL REFERENCES requests(id),
    payload_hash TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(provider_id, event_id)
);
CREATE TABLE IF NOT EXISTS quarantine (
    id TEXT PRIMARY KEY, request_id TEXT NOT NULL REFERENCES requests(id),
    content BLOB NOT NULL, metadata TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON communication_events
BEGIN SELECT RAISE(ABORT, 'immutable communication event'); END;
CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON communication_events
BEGIN SELECT RAISE(ABORT, 'immutable communication event'); END;
CREATE TRIGGER IF NOT EXISTS quarantine_no_update BEFORE UPDATE ON quarantine
BEGIN SELECT RAISE(ABORT, 'immutable quarantined original'); END;
CREATE TRIGGER IF NOT EXISTS quarantine_no_delete BEFORE DELETE ON quarantine
BEGIN SELECT RAISE(ABORT, 'immutable quarantined original'); END;
CREATE TRIGGER IF NOT EXISTS communications_no_update BEFORE UPDATE ON objects
WHEN OLD.kind IN ('test_email', 'submission_preparation')
BEGIN SELECT RAISE(ABORT, 'immutable communication record'); END;
CREATE TRIGGER IF NOT EXISTS communications_no_delete BEFORE DELETE ON objects
WHEN OLD.kind IN ('test_email', 'submission_preparation')
BEGIN SELECT RAISE(ABORT, 'immutable communication record'); END;
PRAGMA user_version = 2;
COMMIT;
