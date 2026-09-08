PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS requests (
    id TEXT PRIMARY KEY, case_id TEXT NOT NULL, revision INTEGER NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS requests_case ON requests(case_id);
CREATE TABLE IF NOT EXISTS objects (
    kind TEXT NOT NULL, id TEXT NOT NULL, request_id TEXT REFERENCES requests(id),
    payload TEXT NOT NULL, PRIMARY KEY(kind, id)
);
CREATE INDEX IF NOT EXISTS objects_request ON objects(kind, request_id);
CREATE TABLE IF NOT EXISTS packages (
    request_id TEXT NOT NULL REFERENCES requests(id), version INTEGER NOT NULL,
    hash TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(request_id, version)
);
CREATE TABLE IF NOT EXISTS artifacts (hash TEXT PRIMARY KEY, content BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS audit (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL UNIQUE,
    entity_id TEXT NOT NULL, payload TEXT NOT NULL, previous_hash TEXT NOT NULL,
    hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_delivery (event_id TEXT PRIMARY KEY REFERENCES audit(event_id));
CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS packages_no_update BEFORE UPDATE ON packages
BEGIN SELECT RAISE(ABORT, 'immutable package'); END;
CREATE TRIGGER IF NOT EXISTS packages_no_delete BEFORE DELETE ON packages
BEGIN SELECT RAISE(ABORT, 'immutable package'); END;
CREATE TRIGGER IF NOT EXISTS artifacts_no_update BEFORE UPDATE ON artifacts
BEGIN SELECT RAISE(ABORT, 'immutable artifact'); END;
CREATE TRIGGER IF NOT EXISTS artifacts_no_delete BEFORE DELETE ON artifacts
BEGIN SELECT RAISE(ABORT, 'immutable artifact'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit
BEGIN SELECT RAISE(ABORT, 'append-only audit'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit
BEGIN SELECT RAISE(ABORT, 'append-only audit'); END;
CREATE TRIGGER IF NOT EXISTS originals_no_update BEFORE UPDATE ON objects
WHEN OLD.kind IN ('authorization_decision', 'signature', 'transmission', 'response_original', 'evidence')
BEGIN SELECT RAISE(ABORT, 'immutable original record'); END;
CREATE TRIGGER IF NOT EXISTS originals_no_delete BEFORE DELETE ON objects
WHEN OLD.kind IN ('authorization_decision', 'signature', 'transmission', 'response_original', 'evidence')
BEGIN SELECT RAISE(ABORT, 'immutable original record'); END;
PRAGMA user_version = 1;
