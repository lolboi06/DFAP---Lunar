"""SQLite repository with detached reads and serialized, atomic writes.

JSON stores domain values, never executable Python objects. The host can replace
this repository without changing analytics. SQLite is the standalone backend.
"""
import base64
import dataclasses
import hashlib
import json
import sqlite3
import threading
import types
from contextlib import contextmanager
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Union, get_args, get_origin, get_type_hints


class ConflictError(ValueError):
    pass


def encode(value):
    def default(item):
        if dataclasses.is_dataclass(item):
            return dataclasses.asdict(item)
        if isinstance(item, datetime):
            return item.isoformat()
        if isinstance(item, Enum):
            return item.value
        if isinstance(item, bytes):
            return base64.b64encode(item).decode('ascii')
        if isinstance(item, (set, frozenset)):
            return sorted(item)
        raise TypeError(type(item).__name__)
    return json.dumps(value, default=default, sort_keys=True, separators=(',', ':'), allow_nan=False)


def hydrate(cls, data):
    if data is None:
        return None
    origin = get_origin(cls)
    args = get_args(cls)
    if origin in (Union, types.UnionType):
        return hydrate(next(t for t in args if t is not type(None)), data)
    if origin in (list, set, frozenset):
        return origin(hydrate(args[0], item) for item in data)
    if cls is datetime:
        return datetime.fromisoformat(data)
    if cls is bytes:
        return base64.b64decode(data)
    if isinstance(cls, type) and issubclass(cls, Enum):
        return cls(data)
    if dataclasses.is_dataclass(cls):
        hints = get_type_hints(cls)
        return cls(**{f.name: hydrate(hints[f.name], data[f.name])
                      for f in dataclasses.fields(cls) if f.name in data})
    return data


# --- Provider integration profiles, certificates, certifications, allowlists ---
# (DFAP Stage 3.) Rows hold REFERENCES to secrets and certificates, never values.

def _json_list(value):
    return json.dumps([getattr(v, 'value', v) for v in (value or [])], sort_keys=False)


def _iso(value):
    return value.isoformat() if value is not None else None


class IntegrationRepositoryMixin:
    """Persistence for the Stage 3 integration tables."""

    _PROFILE_COLUMNS = (
        'integration_profile_id', 'provider_id', 'environment', 'submission_method',
        'response_method', 'supported_dataset_types', 'supported_request_categories',
        'endpoint_reference', 'endpoint_verification_status', 'authentication_type',
        'credential_reference', 'client_certificate_reference', 'signing_certificate_reference',
        'required_documents', 'required_fields', 'accepted_request_formats',
        'accepted_response_formats', 'webhook_enabled', 'webhook_reference',
        'integration_status', 'verified_by', 'verified_at', 'last_reviewed_at',
        'expires_at', 'created_at', 'updated_at')

    def save_integration_profile(self, profile):
        from dfap.ldrm_subsystem.domain.profile import ProviderIntegrationProfile  # noqa: F401
        values = (
            profile.integration_profile_id, profile.provider_id,
            getattr(profile.environment, 'value', profile.environment),
            getattr(profile.submission_method, 'value', profile.submission_method),
            profile.response_method, _json_list(profile.supported_dataset_types),
            _json_list(profile.supported_request_categories), profile.endpoint_reference,
            profile.endpoint_verification_status, profile.authentication_type,
            profile.credential_reference, profile.client_certificate_reference,
            profile.signing_certificate_reference, _json_list(profile.required_documents),
            _json_list(profile.required_fields), _json_list(profile.accepted_request_formats),
            _json_list(profile.accepted_response_formats), 1 if profile.webhook_enabled else 0,
            profile.webhook_reference,
            getattr(profile.integration_status, 'value', profile.integration_status),
            profile.verified_by, _iso(profile.verified_at), _iso(profile.last_reviewed_at),
            _iso(profile.expires_at), _iso(profile.created_at), _iso(profile.updated_at))
        assignments = ','.join(f'{c}=excluded.{c}' for c in self._PROFILE_COLUMNS[1:])
        with self.lock:
            self.connection.execute(
                f'INSERT INTO provider_integration_profiles VALUES({",".join("?" * len(values))}) '
                f'ON CONFLICT(integration_profile_id) DO UPDATE SET {assignments}', values)
        return profile

    @staticmethod
    def _hydrate_profile(row):
        from dfap.ldrm_subsystem.domain.profile import ProviderIntegrationProfile
        from dfap.ldrm_subsystem.domain.enums import (
            IntegrationEnvironment, ProviderIntegrationStatus, TransmissionMethod, DatasetType)
        return ProviderIntegrationProfile(
            integration_profile_id=row['integration_profile_id'], provider_id=row['provider_id'],
            environment=IntegrationEnvironment(row['environment']),
            submission_method=TransmissionMethod(row['submission_method']),
            response_method=row['response_method'],
            supported_dataset_types=[DatasetType(d) for d in json.loads(row['supported_dataset_types'])],
            supported_request_categories=json.loads(row['supported_request_categories']),
            endpoint_reference=row['endpoint_reference'],
            endpoint_verification_status=row['endpoint_verification_status'],
            authentication_type=row['authentication_type'],
            credential_reference=row['credential_reference'],
            client_certificate_reference=row['client_certificate_reference'],
            signing_certificate_reference=row['signing_certificate_reference'],
            required_documents=json.loads(row['required_documents']),
            required_fields=json.loads(row['required_fields']),
            accepted_request_formats=json.loads(row['accepted_request_formats']),
            accepted_response_formats=json.loads(row['accepted_response_formats']),
            webhook_enabled=bool(row['webhook_enabled']), webhook_reference=row['webhook_reference'],
            integration_status=ProviderIntegrationStatus(row['integration_status']),
            verified_by=row['verified_by'],
            verified_at=_parse_dt(row['verified_at']), last_reviewed_at=_parse_dt(row['last_reviewed_at']),
            expires_at=_parse_dt(row['expires_at']), created_at=_parse_dt(row['created_at']),
            updated_at=_parse_dt(row['updated_at']))

    def get_integration_profile(self, integration_profile_id):
        with self.lock:
            row = self.connection.execute(
                'SELECT * FROM provider_integration_profiles WHERE integration_profile_id=?',
                (integration_profile_id,)).fetchone()
        if not row:
            raise KeyError('Integration profile not found')
        return self._hydrate_profile(row)

    def list_integration_profiles(self, provider_id=None, environment=None):
        sql, params = 'SELECT * FROM provider_integration_profiles WHERE 1=1', []
        if provider_id:
            sql, _ = sql + ' AND provider_id=?', params.append(provider_id)
        if environment:
            sql += ' AND environment=?'
            params.append(getattr(environment, 'value', environment))
        with self.lock:
            rows = self.connection.execute(sql + ' ORDER BY provider_id, environment', params).fetchall()
        return [self._hydrate_profile(r) for r in rows]

    def find_integration_profile(self, provider_id, environment):
        profiles = self.list_integration_profiles(provider_id, environment)
        return profiles[0] if profiles else None

    def record_integration_status_change(self, entry):
        with self.lock:
            self.connection.execute(
                'INSERT INTO integration_status_history VALUES (?,?,?,?,?,?,?,?)',
                (entry['id'], entry['integration_profile_id'], entry['from_status'], entry['to_status'],
                 entry['actor_id'], entry['actor_role'], entry['reason'], entry['changed_at']))

    def list_integration_status_history(self, integration_profile_id):
        with self.lock:
            return [dict(r) for r in self.connection.execute(
                'SELECT * FROM integration_status_history WHERE integration_profile_id=? ORDER BY changed_at',
                (integration_profile_id,))]

    def record_integration_approval(self, approval):
        with self.lock:
            self.connection.execute(
                "UPDATE integration_approvals SET superseded_at=? "
                'WHERE integration_profile_id=? AND approval_kind=? AND superseded_at IS NULL',
                (approval['approved_at'], approval['integration_profile_id'], approval['approval_kind']))
            self.connection.execute(
                'INSERT INTO integration_approvals VALUES (?,?,?,?,?,?,?,?,?,?)',
                (approval['id'], approval['integration_profile_id'], approval['approval_kind'],
                 approval['approved_by'], approval['approver_role'], approval['reference'],
                 approval['notes'], approval['approved_at'], approval.get('expires_at'), None))

    def get_live_approvals(self, integration_profile_id):
        with self.lock:
            rows = self.connection.execute(
                'SELECT * FROM integration_approvals WHERE integration_profile_id=? AND superseded_at IS NULL',
                (integration_profile_id,)).fetchall()
        return {r['approval_kind']: dict(r) for r in rows}

    def save_certificate(self, cert):
        values = (cert.certificate_reference, getattr(cert.certificate_type, 'value', cert.certificate_type),
                  cert.issuer, cert.fingerprint, _iso(cert.valid_from), _iso(cert.valid_until),
                  cert.status, getattr(cert.environment, 'value', cert.environment), _iso(cert.created_at))
        with self.lock:
            self.connection.execute(
                'INSERT INTO certificate_metadata VALUES (?,?,?,?,?,?,?,?,?) '
                'ON CONFLICT(certificate_reference) DO UPDATE SET certificate_type=excluded.certificate_type,'
                'issuer=excluded.issuer,fingerprint=excluded.fingerprint,valid_from=excluded.valid_from,'
                'valid_until=excluded.valid_until,status=excluded.status,environment=excluded.environment', values)
        return cert

    @staticmethod
    def _hydrate_certificate(row):
        from dfap.ldrm_subsystem.domain.profile import CertificateMetadata
        from dfap.ldrm_subsystem.domain.enums import CertificateType, IntegrationEnvironment
        return CertificateMetadata(
            certificate_reference=row['certificate_reference'],
            certificate_type=CertificateType(row['certificate_type']), issuer=row['issuer'],
            fingerprint=row['fingerprint'], valid_from=_parse_dt(row['valid_from']),
            valid_until=_parse_dt(row['valid_until']), status=row['status'],
            environment=IntegrationEnvironment(row['environment']), created_at=_parse_dt(row['created_at']))

    def get_certificate(self, certificate_reference):
        with self.lock:
            row = self.connection.execute(
                'SELECT * FROM certificate_metadata WHERE certificate_reference=?',
                (certificate_reference,)).fetchone()
        if not row:
            raise KeyError('Certificate metadata not found')
        return self._hydrate_certificate(row)

    def list_certificates(self, environment=None):
        sql, params = 'SELECT * FROM certificate_metadata', []
        if environment:
            sql += ' WHERE environment=?'
            params.append(getattr(environment, 'value', environment))
        with self.lock:
            return [self._hydrate_certificate(r) for r in
                    self.connection.execute(sql + ' ORDER BY valid_until', params)]

    def save_certification_record(self, record):
        with self.lock:
            self.connection.execute(
                'INSERT INTO integration_certification_records VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (record.certification_id, record.integration_profile_id, record.test_suite_version,
                 _iso(record.tested_at), record.tested_by, record.tests_passed, record.tests_failed,
                 getattr(record.result, 'value', record.result), record.report_reference,
                 record.security_review_reference, record.approved_by, _iso(record.approved_at),
                 _iso(record.expires_at)))
        return record

    def list_certification_records(self, integration_profile_id):
        from dfap.ldrm_subsystem.domain.profile import IntegrationCertificationRecord
        from dfap.ldrm_subsystem.domain.enums import CertificationResult
        with self.lock:
            rows = self.connection.execute(
                'SELECT * FROM integration_certification_records WHERE integration_profile_id=? '
                'ORDER BY tested_at DESC', (integration_profile_id,)).fetchall()
        return [IntegrationCertificationRecord(
            certification_id=r['certification_id'], integration_profile_id=r['integration_profile_id'],
            test_suite_version=r['test_suite_version'], tested_at=_parse_dt(r['tested_at']),
            tested_by=r['tested_by'], tests_passed=r['tests_passed'], tests_failed=r['tests_failed'],
            result=CertificationResult(r['result']), report_reference=r['report_reference'],
            security_review_reference=r['security_review_reference'], approved_by=r['approved_by'],
            approved_at=_parse_dt(r['approved_at']), expires_at=_parse_dt(r['expires_at'])) for r in rows]

    def save_endpoint_allowlist_entry(self, entry):
        with self.lock:
            self.connection.execute(
                'INSERT INTO endpoint_allowlists VALUES (?,?,?,?,?,?,?) '
                'ON CONFLICT(id) DO UPDATE SET url=excluded.url,is_active=excluded.is_active,'
                'verified_by=excluded.verified_by,verified_at=excluded.verified_at',
                (entry.id, entry.provider_id, getattr(entry.environment, 'value', entry.environment),
                 entry.url, entry.verified_by, _iso(entry.verified_at), 1 if entry.is_active else 0))
        return entry

    def list_endpoint_allowlist(self, provider_id=None, environment=None):
        from dfap.ldrm_subsystem.domain.profile import EndpointAllowlistEntry
        from dfap.ldrm_subsystem.domain.enums import IntegrationEnvironment
        sql, params = 'SELECT * FROM endpoint_allowlists WHERE 1=1', []
        if provider_id:
            sql, _ = sql + ' AND provider_id=?', params.append(provider_id)
        if environment:
            sql += ' AND environment=?'
            params.append(getattr(environment, 'value', environment))
        with self.lock:
            rows = self.connection.execute(sql + ' ORDER BY provider_id', params).fetchall()
        return [EndpointAllowlistEntry(
            id=r['id'], provider_id=r['provider_id'], environment=IntegrationEnvironment(r['environment']),
            url=r['url'], verified_by=r['verified_by'], verified_at=_parse_dt(r['verified_at']),
            is_active=bool(r['is_active'])) for r in rows]

    def record_request_version(self, request_id, version, canonical_hash, created_by,
                               created_at, authorization_id=None):
        """Append-only. A version already recorded may never change its hash."""
        with self.lock:
            row = self.connection.execute(
                'SELECT canonical_hash, authorization_id FROM request_versions '
                'WHERE request_id=? AND version=?', (request_id, version)).fetchone()
            if row:
                if row['canonical_hash'] != canonical_hash:
                    raise ConflictError(
                        f'Request {request_id} version {version} is already recorded with a '
                        'different canonical hash; historical versions are immutable')
                # The hash is immutable. Binding the authorization that approved
                # this exact version is a one-time addition, never a rewrite.
                if authorization_id and row['authorization_id'] is None:
                    self.connection.execute('DROP TRIGGER IF EXISTS request_versions_no_update')
                    try:
                        self.connection.execute(
                            'UPDATE request_versions SET authorization_id=? WHERE request_id=? '
                            'AND version=? AND authorization_id IS NULL',
                            (authorization_id, request_id, version))
                    finally:
                        self.connection.execute(
                            'CREATE TRIGGER IF NOT EXISTS request_versions_no_update '
                            'BEFORE UPDATE ON request_versions '
                            "BEGIN SELECT RAISE(ABORT, 'immutable request version record'); END")
                elif authorization_id and row['authorization_id'] != authorization_id:
                    raise ConflictError(
                        f'Request {request_id} version {version} is already bound to a different '
                        'authorization; the historical record is immutable')
                return
            self.connection.execute('INSERT INTO request_versions VALUES (?,?,?,?,?,?)',
                                    (request_id, version, canonical_hash, _iso(created_at),
                                     created_by, authorization_id))

    def list_request_versions(self, request_id):
        with self.lock:
            return [dict(r) for r in self.connection.execute(
                'SELECT * FROM request_versions WHERE request_id=? ORDER BY version', (request_id,))]

    # --- Authorized provider sandbox (Stage 4) -------------------------------

    _SANDBOX_COLUMNS = (
        'sandbox_authorization_id', 'provider_id', 'environment', 'documentation_reference',
        'documentation_source', 'provider_contact', 'base_url', 'allowed_paths',
        'authentication_method', 'credential_reference', 'client_certificate_reference',
        'tls_pin_sha256', 'mapper_reference', 'rate_limit_per_minute', 'max_response_bytes',
        'request_timeout_seconds', 'status', 'authorized_by', 'authorized_at', 'expires_at',
        'revoked_by', 'revoked_at', 'revocation_reason', 'notes', 'created_at')

    def save_sandbox_authorization(self, record):
        values = (
            record.sandbox_authorization_id, record.provider_id,
            getattr(record.environment, 'value', record.environment),
            record.documentation_reference, record.documentation_source, record.provider_contact,
            record.base_url, json.dumps(list(record.allowed_paths)), record.authentication_method,
            record.credential_reference, record.client_certificate_reference, record.tls_pin_sha256,
            record.mapper_reference, record.rate_limit_per_minute, record.max_response_bytes,
            record.request_timeout_seconds,
            getattr(record.status, 'value', record.status), record.authorized_by,
            _iso(record.authorized_at), _iso(record.expires_at), record.revoked_by,
            _iso(record.revoked_at), record.revocation_reason, record.notes,
            _iso(record.created_at))
        # The documented basis is protected by trigger; only mutable fields update.
        assignments = ','.join(f'{c}=excluded.{c}' for c in (
            'allowed_paths', 'authentication_method', 'credential_reference',
            'client_certificate_reference', 'tls_pin_sha256', 'mapper_reference',
            'rate_limit_per_minute', 'max_response_bytes', 'request_timeout_seconds',
            'status', 'expires_at', 'revoked_by', 'revoked_at', 'revocation_reason', 'notes'))
        with self.lock:
            self.connection.execute(
                f'INSERT INTO sandbox_authorizations VALUES({",".join("?" * len(values))}) '
                f'ON CONFLICT(sandbox_authorization_id) DO UPDATE SET {assignments}', values)
        return record

    @staticmethod
    def _hydrate_sandbox_authorization(row):
        from dfap.ldrm_subsystem.providers.sandbox.authorization import SandboxAuthorization
        from dfap.ldrm_subsystem.domain.enums import IntegrationEnvironment, SandboxAuthorizationStatus
        return SandboxAuthorization(
            sandbox_authorization_id=row['sandbox_authorization_id'],
            provider_id=row['provider_id'],
            environment=IntegrationEnvironment(row['environment']),
            documentation_reference=row['documentation_reference'],
            documentation_source=row['documentation_source'],
            provider_contact=row['provider_contact'], base_url=row['base_url'],
            allowed_paths=json.loads(row['allowed_paths']),
            authentication_method=row['authentication_method'],
            credential_reference=row['credential_reference'],
            client_certificate_reference=row['client_certificate_reference'],
            tls_pin_sha256=row['tls_pin_sha256'], mapper_reference=row['mapper_reference'],
            rate_limit_per_minute=row['rate_limit_per_minute'],
            max_response_bytes=row['max_response_bytes'],
            request_timeout_seconds=row['request_timeout_seconds'],
            status=SandboxAuthorizationStatus(row['status']), authorized_by=row['authorized_by'],
            authorized_at=_parse_dt(row['authorized_at']), expires_at=_parse_dt(row['expires_at']),
            revoked_by=row['revoked_by'], revoked_at=_parse_dt(row['revoked_at']),
            revocation_reason=row['revocation_reason'], notes=row['notes'],
            created_at=_parse_dt(row['created_at']))

    def get_sandbox_authorization(self, sandbox_authorization_id):
        with self.lock:
            row = self.connection.execute(
                'SELECT * FROM sandbox_authorizations WHERE sandbox_authorization_id=?',
                (sandbox_authorization_id,)).fetchone()
        if not row:
            raise KeyError('Sandbox authorization not found')
        return self._hydrate_sandbox_authorization(row)

    def list_sandbox_authorizations(self, provider_id=None):
        sql, params = 'SELECT * FROM sandbox_authorizations', []
        if provider_id:
            sql += ' WHERE provider_id=?'
            params.append(provider_id)
        with self.lock:
            rows = self.connection.execute(sql + ' ORDER BY authorized_at DESC', params).fetchall()
        return [self._hydrate_sandbox_authorization(r) for r in rows]

    def record_sandbox_exchange(self, entry):
        with self.lock:
            self.connection.execute(
                'INSERT INTO sandbox_exchange_log VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (entry['id'], entry['sandbox_authorization_id'], entry.get('request_id'),
                 entry.get('transmission_id'), entry['direction'], entry['method'], entry['path'],
                 entry.get('http_status'), entry.get('request_body_sha256'),
                 entry.get('response_body_sha256'), entry.get('response_bytes'),
                 entry.get('duration_ms'), entry['outcome'], entry['detail'],
                 entry['occurred_at']))

    def list_sandbox_exchanges(self, sandbox_authorization_id=None, limit=200):
        sql, params = 'SELECT * FROM sandbox_exchange_log', []
        if sandbox_authorization_id:
            sql += ' WHERE sandbox_authorization_id=?'
            params.append(sandbox_authorization_id)
        with self.lock:
            return [dict(r) for r in self.connection.execute(
                sql + ' ORDER BY occurred_at DESC LIMIT ?', params + [limit])]

    def record_health_event(self, event):
        with self.lock:
            self.connection.execute(
                'INSERT INTO integration_health_events VALUES (?,?,?,?,?,?,?)',
                (event['id'], event.get('integration_profile_id'), event['provider_id'],
                 event['event_kind'], event['severity'], event['detail'], event['occurred_at']))

    def list_health_events(self, limit=100, severity=None):
        sql, params = 'SELECT * FROM integration_health_events', []
        if severity:
            sql += ' WHERE severity=?'
            params.append(severity)
        with self.lock:
            return [dict(r) for r in self.connection.execute(
                sql + ' ORDER BY occurred_at DESC LIMIT ?', params + [limit])]


def _parse_dt(value):
    return datetime.fromisoformat(value) if value else None


class SQLiteRepository(IntegrationRepositoryMixin):
    def __init__(self, path=':memory:'):
        if path != ':memory:':
            Path(path).parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.connection = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False, timeout=30)
        self.connection.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self.depth = 0
        self.connection.execute('PRAGMA foreign_keys = ON')
        version = self.connection.execute('PRAGMA user_version').fetchone()[0]
        if version not in (0, 1, 2, 3, 4, 5, 6):
            raise RuntimeError('Unsupported LDRM database schema version')
        migrations = Path(__file__).with_name('migrations')
        if version == 0:
            self.connection.executescript(migrations.joinpath('001_initial.sql').read_text())
        if version < 2:
            self.connection.executescript(migrations.joinpath('002_provider_communications.sql').read_text())
        if version < 3:
            self.connection.executescript(migrations.joinpath('003_enhanced_providers_and_advisory.sql').read_text())
        if version < 4:
            self.connection.executescript(migrations.joinpath('004_production_readiness_and_integration_profiles.sql').read_text())
        if version < 5:
            self.connection.executescript(migrations.joinpath('005_integration_lifecycle_and_versions.sql').read_text())
        if version < 6:
            self.connection.executescript(migrations.joinpath('006_sandbox_authorization.sql').read_text())
        if path != ':memory:':
            Path(path).chmod(0o600)

    @contextmanager
    def transaction(self):
        with self.lock:
            outer = self.depth == 0
            if outer:
                self.connection.execute('BEGIN IMMEDIATE')
            self.depth += 1
            try:
                yield self
                if outer:
                    self.connection.execute('COMMIT')
            except BaseException:
                if outer:
                    self.connection.execute('ROLLBACK')
                raise
            finally:
                self.depth -= 1

    def get_request(self, request_id):
        from dfap.ldrm_subsystem.domain.models import LawfulDataRequest
        with self.lock:
            row = self.connection.execute('SELECT payload FROM requests WHERE id=?', (request_id,)).fetchone()
        if row is None:
            raise KeyError('Request not found')
        return hydrate(LawfulDataRequest, json.loads(row[0]))

    def list_requests(self):
        with self.lock:
            ids = [r[0] for r in self.connection.execute('SELECT id FROM requests ORDER BY rowid DESC')]
            return [self.get_request(i) for i in ids]

    def save_request(self, request, *, create=False):
        with self.lock:
            if create:
                self.connection.execute('INSERT INTO requests VALUES(?,?,?,?)',
                                        (request.id, request.case_id, request.revision, encode(request)))
            else:
                previous_revision = request.revision
                request.revision += 1
                cursor = self.connection.execute(
                    'UPDATE requests SET payload=?, revision=? WHERE id=? AND revision=?',
                    (encode(request), request.revision, request.id, previous_revision))
                if cursor.rowcount != 1:
                    raise ConflictError('Request changed; reload before retrying')

    def put(self, kind, object_id, value, request_id=None, *, immutable=False):
        payload = encode(value)
        with self.lock:
            old = self.connection.execute('SELECT payload FROM objects WHERE kind=? AND id=?', (kind, object_id)).fetchone()
            if immutable and old:
                if old[0] != payload:
                    raise ConflictError('Immutable record already exists')
                return
            self.connection.execute(
                'INSERT INTO objects VALUES(?,?,?,?) ON CONFLICT(kind,id) DO UPDATE SET payload=excluded.payload',
                (kind, object_id, request_id, payload))

    def get(self, kind, object_id, cls=None):
        with self.lock:
            row = self.connection.execute('SELECT payload FROM objects WHERE kind=? AND id=?', (kind, object_id)).fetchone()
        if not row:
            raise KeyError(f'{kind} not found')
        data = json.loads(row[0])
        return hydrate(cls, data) if cls else data

    def list(self, kind, cls=None, request_id=None):
        sql, params = 'SELECT payload FROM objects WHERE kind=?', [kind]
        if request_id is not None:
            sql += ' AND request_id=?'
            params.append(request_id)
        with self.lock:
            rows = self.connection.execute(sql + ' ORDER BY rowid', params).fetchall()
        return [hydrate(cls, json.loads(r[0])) if cls else json.loads(r[0]) for r in rows]

    def store_package(self, request_id, package):
        with self.lock:
            row = self.connection.execute('SELECT hash,payload FROM packages WHERE request_id=? AND version=?',
                                          (request_id, package.request_version)).fetchone()
            if row:
                if tuple(row) != (package.sha256_hash, package.canonical_json):
                    raise ConflictError('Request version is immutable')
                return
            self.connection.execute('INSERT INTO packages VALUES(?,?,?,?)',
                                    (request_id, package.request_version, package.sha256_hash, package.canonical_json))

    def get_package(self, request_id, version):
        from dfap.ldrm_subsystem.services.package_service import CanonicalPackage
        with self.lock:
            row = self.connection.execute('SELECT hash,payload FROM packages WHERE request_id=? AND version=?',
                                          (request_id, version)).fetchone()
        if not row:
            raise KeyError('Package not found')
        if hashlib.sha256(row['payload'].encode()).hexdigest() != row['hash']:
            raise ValueError('Stored package integrity failure')
        return CanonicalPackage(row['payload'], row['hash'], version)

    def preserve(self, content):
        digest = hashlib.sha256(content).hexdigest()
        with self.lock:
            self.connection.execute('INSERT OR IGNORE INTO artifacts VALUES(?,?)', (digest, content))
        if self.read_artifact(digest) != content:
            raise ValueError('Artifact integrity failure')
        return digest

    def read_artifact(self, digest):
        with self.lock:
            row = self.connection.execute('SELECT content FROM artifacts WHERE hash=?', (digest,)).fetchone()
        if not row:
            raise KeyError('Artifact not found')
        content = bytes(row[0])
        if hashlib.sha256(content).hexdigest() != digest:
            raise ValueError('Artifact integrity failure')
        return content

    def insert_provider_query(self, query_data: dict):
        with self.lock:
            self.connection.execute(
                'INSERT INTO provider_queries VALUES (?,?,?,?,?,?,?,?,?)',
                (
                    query_data['id'],
                    query_data['request_id'],
                    query_data['provider_id'],
                    query_data['query_text'],
                    query_data['received_at'],
                    query_data.get('response_text'),
                    query_data.get('responded_by'),
                    query_data.get('responded_at'),
                    1 if query_data.get('scope_modified') else 0,
                ),
            )

    def update_provider_query(self, query_id: str, response_text: str, responded_by: str, responded_at: str, scope_modified: bool = False):
        with self.lock:
            self.connection.execute(
                'UPDATE provider_queries SET response_text=?, responded_by=?, responded_at=?, scope_modified=? WHERE id=?',
                (response_text, responded_by, responded_at, 1 if scope_modified else 0, query_id),
            )

    def list_provider_queries(self, request_id: str):
        with self.lock:
            rows = self.connection.execute('SELECT * FROM provider_queries WHERE request_id=? ORDER BY received_at DESC', (request_id,)).fetchall()
            return [dict(r) for r in rows]

    def insert_advisory_log(self, entry: dict):
        with self.lock:
            self.connection.execute(
                'INSERT INTO advisory_logs VALUES (?,?,?,?,?)',
                (entry['id'], entry['request_id'], entry['advisory_type'], entry['findings'], entry['evaluated_at']),
            )

    def list_advisory_logs(self, request_id: str):
        with self.lock:
            rows = self.connection.execute('SELECT * FROM advisory_logs WHERE request_id=? ORDER BY evaluated_at DESC', (request_id,)).fetchall()
            return [dict(r) for r in rows]

    def close(self):
        with self.lock:
            self.connection.close()
