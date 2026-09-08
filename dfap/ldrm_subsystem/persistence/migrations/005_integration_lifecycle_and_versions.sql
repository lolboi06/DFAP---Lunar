-- Migration 005: Integration lifecycle history, human approvals, request version
-- ledger, and integration health events. Additive only; 001-004 are untouched.
BEGIN IMMEDIATE;

-- Append-only record of every integration status change, with the human actor.
CREATE TABLE IF NOT EXISTS integration_status_history (
    id TEXT PRIMARY KEY,
    integration_profile_id TEXT NOT NULL,
    from_status TEXT NOT NULL,
    to_status TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    actor_role TEXT NOT NULL,
    reason TEXT NOT NULL,
    changed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS integration_status_history_profile
    ON integration_status_history(integration_profile_id);

-- Recorded human approvals. approval_kind is SECURITY_REVIEW, AGENCY_APPROVAL,
-- PROVIDER_APPROVAL or DOCUMENTATION_VERIFICATION. One live record per kind per
-- profile; superseded records are retained with superseded_at set.
CREATE TABLE IF NOT EXISTS integration_approvals (
    id TEXT PRIMARY KEY,
    integration_profile_id TEXT NOT NULL,
    approval_kind TEXT NOT NULL,
    approved_by TEXT NOT NULL,
    approver_role TEXT NOT NULL,
    reference TEXT NOT NULL,
    notes TEXT NOT NULL,
    approved_at TEXT NOT NULL,
    expires_at TEXT,
    superseded_at TEXT
);
CREATE INDEX IF NOT EXISTS integration_approvals_profile
    ON integration_approvals(integration_profile_id, approval_kind);

-- Immutable ledger of every canonical request version ever produced.
CREATE TABLE IF NOT EXISTS request_versions (
    request_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    canonical_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    created_by TEXT NOT NULL,
    authorization_id TEXT,
    PRIMARY KEY(request_id, version)
);

-- Operational health/observability events for administrators.
CREATE TABLE IF NOT EXISTS integration_health_events (
    id TEXT PRIMARY KEY,
    integration_profile_id TEXT,
    provider_id TEXT NOT NULL,
    event_kind TEXT NOT NULL,
    severity TEXT NOT NULL,
    detail TEXT NOT NULL,
    occurred_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS integration_health_events_provider
    ON integration_health_events(provider_id, occurred_at);

CREATE INDEX IF NOT EXISTS provider_integration_profiles_provider
    ON provider_integration_profiles(provider_id, environment);
CREATE INDEX IF NOT EXISTS integration_certification_records_profile
    ON integration_certification_records(integration_profile_id);
CREATE INDEX IF NOT EXISTS endpoint_allowlists_provider
    ON endpoint_allowlists(provider_id, environment);

-- History, approvals and version records are evidence of a human decision and
-- are never rewritten. Approvals may only be superseded, never edited or removed.
CREATE TRIGGER IF NOT EXISTS integration_status_history_no_update
BEFORE UPDATE ON integration_status_history
BEGIN SELECT RAISE(ABORT, 'append-only integration status history'); END;
CREATE TRIGGER IF NOT EXISTS integration_status_history_no_delete
BEFORE DELETE ON integration_status_history
BEGIN SELECT RAISE(ABORT, 'append-only integration status history'); END;

CREATE TRIGGER IF NOT EXISTS integration_approvals_supersede_only
BEFORE UPDATE ON integration_approvals
WHEN OLD.superseded_at IS NOT NULL
  OR NEW.approved_by <> OLD.approved_by
  OR NEW.approved_at <> OLD.approved_at
  OR NEW.reference <> OLD.reference
  OR NEW.approval_kind <> OLD.approval_kind
BEGIN SELECT RAISE(ABORT, 'recorded approval is immutable; it may only be superseded'); END;
CREATE TRIGGER IF NOT EXISTS integration_approvals_no_delete
BEFORE DELETE ON integration_approvals
BEGIN SELECT RAISE(ABORT, 'recorded approval cannot be deleted'); END;

CREATE TRIGGER IF NOT EXISTS request_versions_no_update
BEFORE UPDATE ON request_versions
BEGIN SELECT RAISE(ABORT, 'immutable request version record'); END;
CREATE TRIGGER IF NOT EXISTS request_versions_no_delete
BEFORE DELETE ON request_versions
BEGIN SELECT RAISE(ABORT, 'immutable request version record'); END;

CREATE TRIGGER IF NOT EXISTS certification_records_no_update
BEFORE UPDATE ON integration_certification_records
BEGIN SELECT RAISE(ABORT, 'immutable certification record'); END;
CREATE TRIGGER IF NOT EXISTS certification_records_no_delete
BEFORE DELETE ON integration_certification_records
BEGIN SELECT RAISE(ABORT, 'immutable certification record'); END;

CREATE TRIGGER IF NOT EXISTS evidence_store_metadata_no_update
BEFORE UPDATE ON evidence_store_metadata
BEGIN SELECT RAISE(ABORT, 'immutable original evidence metadata'); END;
CREATE TRIGGER IF NOT EXISTS evidence_store_metadata_no_delete
BEFORE DELETE ON evidence_store_metadata
BEGIN SELECT RAISE(ABORT, 'immutable original evidence metadata'); END;

PRAGMA user_version = 5;
COMMIT;
