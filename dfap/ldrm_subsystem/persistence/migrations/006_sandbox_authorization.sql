-- Migration 006: Authorized provider sandbox records (DFAP Stage 4).
--
-- A row here is the agency's record that a NAMED PROVIDER has, in writing,
-- authorized this agency to use a NAMED NON-PRODUCTION SANDBOX. No sandbox
-- transport can be constructed without one. The row stores the documentation
-- reference and the human who recorded it; it stores credential REFERENCES
-- only, never credential values.
BEGIN IMMEDIATE;

CREATE TABLE IF NOT EXISTS sandbox_authorizations (
    sandbox_authorization_id TEXT PRIMARY KEY,
    provider_id TEXT NOT NULL,
    environment TEXT NOT NULL,
    -- Institutional paperwork this authorization rests on.
    documentation_reference TEXT NOT NULL,
    documentation_source TEXT NOT NULL,
    provider_contact TEXT NOT NULL,
    -- Transport identity. base_url must be https and separately allowlisted.
    base_url TEXT NOT NULL,
    allowed_paths TEXT NOT NULL,
    authentication_method TEXT NOT NULL,
    credential_reference TEXT NOT NULL,
    client_certificate_reference TEXT,
    tls_pin_sha256 TEXT,
    -- Behaviour agreed with the provider.
    mapper_reference TEXT NOT NULL,
    rate_limit_per_minute INTEGER,
    max_response_bytes INTEGER NOT NULL,
    request_timeout_seconds REAL NOT NULL,
    -- Who recorded it, and how long it is good for.
    status TEXT NOT NULL,
    authorized_by TEXT NOT NULL,
    authorized_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    revoked_by TEXT,
    revoked_at TEXT,
    revocation_reason TEXT,
    notes TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS sandbox_authorizations_provider
    ON sandbox_authorizations(provider_id, environment);

-- Append-only record of every sandbox exchange, for contract evidence and
-- incident review. Bodies are NOT stored here; only hashes and safe metadata.
CREATE TABLE IF NOT EXISTS sandbox_exchange_log (
    id TEXT PRIMARY KEY,
    sandbox_authorization_id TEXT NOT NULL,
    request_id TEXT,
    transmission_id TEXT,
    direction TEXT NOT NULL,
    method TEXT NOT NULL,
    path TEXT NOT NULL,
    http_status INTEGER,
    request_body_sha256 TEXT,
    response_body_sha256 TEXT,
    response_bytes INTEGER,
    duration_ms INTEGER,
    outcome TEXT NOT NULL,
    detail TEXT NOT NULL,
    occurred_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS sandbox_exchange_log_auth
    ON sandbox_exchange_log(sandbox_authorization_id, occurred_at);

-- The authorization itself may only be superseded by status change; the
-- documentation it rests on is never rewritten.
CREATE TRIGGER IF NOT EXISTS sandbox_authorizations_immutable_basis
BEFORE UPDATE ON sandbox_authorizations
WHEN NEW.documentation_reference <> OLD.documentation_reference
  OR NEW.provider_id <> OLD.provider_id
  OR NEW.base_url <> OLD.base_url
  OR NEW.authorized_by <> OLD.authorized_by
  OR NEW.authorized_at <> OLD.authorized_at
BEGIN SELECT RAISE(ABORT, 'the documented basis of a sandbox authorization is immutable'); END;

CREATE TRIGGER IF NOT EXISTS sandbox_authorizations_no_delete
BEFORE DELETE ON sandbox_authorizations
BEGIN SELECT RAISE(ABORT, 'sandbox authorization records are retained; revoke instead'); END;

CREATE TRIGGER IF NOT EXISTS sandbox_exchange_log_no_update
BEFORE UPDATE ON sandbox_exchange_log
BEGIN SELECT RAISE(ABORT, 'append-only sandbox exchange log'); END;

CREATE TRIGGER IF NOT EXISTS sandbox_exchange_log_no_delete
BEFORE DELETE ON sandbox_exchange_log
BEGIN SELECT RAISE(ABORT, 'append-only sandbox exchange log'); END;

PRAGMA user_version = 6;
COMMIT;
