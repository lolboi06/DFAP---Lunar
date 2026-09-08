-- Migration 004: Production Readiness, Provider Integration Profiles, Certificate Metadata, and Endpoint Allowlisting
CREATE TABLE IF NOT EXISTS provider_integration_profiles (
    integration_profile_id TEXT PRIMARY KEY,
    provider_id TEXT NOT NULL,
    environment TEXT NOT NULL,
    submission_method TEXT NOT NULL,
    response_method TEXT NOT NULL,
    supported_dataset_types TEXT NOT NULL,
    supported_request_categories TEXT NOT NULL,
    endpoint_reference TEXT NOT NULL,
    endpoint_verification_status TEXT NOT NULL,
    authentication_type TEXT NOT NULL,
    credential_reference TEXT NOT NULL,
    client_certificate_reference TEXT,
    signing_certificate_reference TEXT,
    required_documents TEXT NOT NULL,
    required_fields TEXT NOT NULL,
    accepted_request_formats TEXT NOT NULL,
    accepted_response_formats TEXT NOT NULL,
    webhook_enabled INTEGER NOT NULL DEFAULT 0,
    webhook_reference TEXT,
    integration_status TEXT NOT NULL,
    verified_by TEXT,
    verified_at TEXT,
    last_reviewed_at TEXT,
    expires_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS certificate_metadata (
    certificate_reference TEXT PRIMARY KEY,
    certificate_type TEXT NOT NULL,
    issuer TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    valid_from TEXT NOT NULL,
    valid_until TEXT NOT NULL,
    status TEXT NOT NULL,
    environment TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS integration_certification_records (
    certification_id TEXT PRIMARY KEY,
    integration_profile_id TEXT NOT NULL,
    test_suite_version TEXT NOT NULL,
    tested_at TEXT NOT NULL,
    tested_by TEXT NOT NULL,
    tests_passed INTEGER NOT NULL,
    tests_failed INTEGER NOT NULL,
    result TEXT NOT NULL,
    report_reference TEXT NOT NULL,
    security_review_reference TEXT,
    approved_by TEXT,
    approved_at TEXT,
    expires_at TEXT
);

CREATE TABLE IF NOT EXISTS endpoint_allowlists (
    id TEXT PRIMARY KEY,
    provider_id TEXT NOT NULL,
    environment TEXT NOT NULL,
    url TEXT NOT NULL,
    verified_by TEXT NOT NULL,
    verified_at TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS evidence_store_metadata (
    evidence_id TEXT PRIMARY KEY,
    response_id TEXT NOT NULL,
    request_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    provider_id TEXT NOT NULL,
    received_at TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    media_type TEXT NOT NULL,
    storage_reference TEXT NOT NULL,
    chain_of_custody_reference TEXT NOT NULL
);

PRAGMA user_version = 4;
