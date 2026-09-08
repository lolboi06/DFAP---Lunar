"""The authorization record that gates every sandbox exchange (Stage 4).

A `SandboxAuthorization` is not configuration. It is the agency's record that a
**named provider** has, in writing, authorized this agency to use a **named
non-production sandbox** — with the documentation reference, the human who
recorded it, and an expiry. Without an ACTIVE record no transport is
constructible, so a misconfiguration cannot produce an external connection.

Credential values never appear here. The record carries references that resolve
through a `SecretProvider` at the moment of use.
"""
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from dfap.ldrm_subsystem.domain.enums import IntegrationEnvironment, SandboxAuthorizationStatus as St
from dfap.ldrm_subsystem.domain.utils import utc_now
from dfap.ldrm_subsystem.persistence.unit_of_work import atomic
from dfap.ldrm_subsystem.policy.ssrf import SSRFProtection, SSRFProtectionError


class SandboxAuthorizationError(ValueError):
    pass


class SandboxNotAuthorized(PermissionError):
    """Raised whenever a sandbox exchange is attempted without a live authorization."""


def _v(value):
    return getattr(value, 'value', str(value))


#: Ceiling on how long one recorded sandbox authorization may run before it must
#: be re-confirmed with the provider. Deliberately short.
MAX_AUTHORIZATION_DAYS = 365

#: Hard ceiling on a sandbox response, independent of what a record asks for.
ABSOLUTE_MAX_RESPONSE_BYTES = 64 * 1024 * 1024

#: Hard ceiling on a single sandbox request, so a hung provider cannot pin a worker.
ABSOLUTE_MAX_TIMEOUT_SECONDS = 120.0


@dataclass
class SandboxAuthorization:
    """One provider's authorized non-production sandbox."""
    sandbox_authorization_id: str = field(default_factory=lambda: f'SBXA-{uuid.uuid4().hex[:12].upper()}')
    provider_id: str = ''
    environment: IntegrationEnvironment = IntegrationEnvironment.SANDBOX

    # The paperwork this rests on.
    documentation_reference: str = ''
    documentation_source: str = ''
    provider_contact: str = ''

    # Transport identity.
    base_url: str = ''
    allowed_paths: List[str] = field(default_factory=list)
    authentication_method: str = ''
    credential_reference: str = ''
    client_certificate_reference: Optional[str] = None
    tls_pin_sha256: Optional[str] = None

    # Agreed behaviour.
    mapper_reference: str = ''
    rate_limit_per_minute: Optional[int] = None
    max_response_bytes: int = 10 * 1024 * 1024
    request_timeout_seconds: float = 30.0

    status: SandboxAuthorizationStatus = St.PENDING
    authorized_by: str = ''
    authorized_at: datetime = field(default_factory=utc_now)
    expires_at: Optional[datetime] = None
    revoked_by: Optional[str] = None
    revoked_at: Optional[datetime] = None
    revocation_reason: Optional[str] = None
    notes: str = ''
    created_at: datetime = field(default_factory=utc_now)

    @property
    def is_live(self) -> bool:
        """Usable right now. Anything other than ACTIVE-and-unexpired is not."""
        return (self.status == St.ACTIVE
                and self.expires_at is not None
                and self.expires_at > utc_now()
                and self.environment == IntegrationEnvironment.SANDBOX)

    def why_not_live(self) -> str:
        if self.environment != IntegrationEnvironment.SANDBOX:
            return f'authorization is for {_v(self.environment)}, not SANDBOX'
        if self.status != St.ACTIVE:
            return f'authorization status is {_v(self.status)}'
        if self.expires_at is None:
            return 'authorization has no recorded expiry'
        if self.expires_at <= utc_now():
            return f'authorization expired at {self.expires_at.isoformat()}'
        return ''

    def to_dict(self) -> Dict[str, Any]:
        """Safe representation. Carries references, never credential values."""
        return {
            'sandbox_authorization_id': self.sandbox_authorization_id,
            'provider_id': self.provider_id,
            'environment': _v(self.environment),
            'documentation_reference': self.documentation_reference,
            'documentation_source': self.documentation_source,
            'provider_contact': self.provider_contact,
            'base_url': self.base_url,
            'allowed_paths': list(self.allowed_paths),
            'authentication_method': self.authentication_method,
            'credential_reference': self.credential_reference,
            'client_certificate_reference': self.client_certificate_reference,
            'tls_pin_sha256': self.tls_pin_sha256,
            'mapper_reference': self.mapper_reference,
            'rate_limit_per_minute': self.rate_limit_per_minute,
            'max_response_bytes': self.max_response_bytes,
            'request_timeout_seconds': self.request_timeout_seconds,
            'status': _v(self.status),
            'authorized_by': self.authorized_by,
            'authorized_at': self.authorized_at.isoformat(),
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'revoked_by': self.revoked_by,
            'revoked_at': self.revoked_at.isoformat() if self.revoked_at else None,
            'revocation_reason': self.revocation_reason,
            'notes': self.notes,
            'created_at': self.created_at.isoformat(),
            'is_live': self.is_live,
        }


# Re-exported name used in the annotation above.
SandboxAuthorizationStatus = St


class SandboxAuthorizationService:
    """Administrator management of sandbox authorizations."""

    def __init__(self, repository, access, audit, secret_provider):
        self.repository, self.access, self.audit = repository, access, audit
        self.audit_adapter = audit
        self.secrets = secret_provider

    # ------------------------------------------------------------- recording

    @atomic
    def record_authorization(self, actor_id, *, provider_id, documentation_reference,
                             documentation_source, provider_contact, base_url, allowed_paths,
                             authentication_method, credential_reference, mapper_reference,
                             expires_at, notes, client_certificate_reference=None,
                             tls_pin_sha256=None, rate_limit_per_minute=None,
                             max_response_bytes=10 * 1024 * 1024, request_timeout_seconds=30.0):
        """Record that a provider has authorized this agency to use its sandbox.

        Starts PENDING. It becomes usable only after a separate `activate` call,
        which re-checks that the destination is allowlisted and the credential
        resolves — so recording paperwork and enabling traffic stay two acts.
        """
        user = self.access.administrator(actor_id)
        if not user.is_human:
            raise SandboxAuthorizationError(
                'A sandbox authorization must be recorded by an authenticated human')

        for label, value in (('documentation reference', documentation_reference),
                             ('documentation source', documentation_source),
                             ('provider contact', provider_contact),
                             ('authentication method', authentication_method),
                             ('credential reference', credential_reference),
                             ('mapper reference', mapper_reference),
                             ('notes', notes)):
            if not str(value or '').strip():
                raise SandboxAuthorizationError(
                    f'A sandbox authorization requires the {label}; this record stands in for '
                    "the provider's written authorization and cannot be partially filled")

        # The provider must already be a verified registry entry.
        self._provider(provider_id)

        # Transport rules apply to the base URL before it is stored. The
        # allowlist is checked separately at activation, so a recording error
        # reports the actual problem rather than a missing allowlist entry.
        if not base_url.lower().startswith('https://'):
            raise SandboxAuthorizationError('A sandbox base URL must use https')
        try:
            SSRFProtection.validate_transport_rules(base_url, IntegrationEnvironment.SANDBOX)
        except SSRFProtectionError as error:
            raise SandboxAuthorizationError(f'Sandbox base URL rejected: {error}') from error

        if not allowed_paths or any(not p.startswith('/') for p in allowed_paths):
            raise SandboxAuthorizationError(
                'At least one allowed path is required, and each must start with "/"')

        if expires_at is None or expires_at.tzinfo is None:
            raise SandboxAuthorizationError('A timezone-aware expiry is required')
        if expires_at <= utc_now():
            raise SandboxAuthorizationError('The recorded expiry is already in the past')
        if (expires_at - utc_now()).days > MAX_AUTHORIZATION_DAYS:
            raise SandboxAuthorizationError(
                f'A sandbox authorization may run for at most {MAX_AUTHORIZATION_DAYS} days '
                'before it is re-confirmed with the provider')

        if not 0 < max_response_bytes <= ABSOLUTE_MAX_RESPONSE_BYTES:
            raise SandboxAuthorizationError(
                f'max_response_bytes must be between 1 and {ABSOLUTE_MAX_RESPONSE_BYTES}')
        if not 0 < request_timeout_seconds <= ABSOLUTE_MAX_TIMEOUT_SECONDS:
            raise SandboxAuthorizationError(
                f'request_timeout_seconds must be between 0 and {ABSOLUTE_MAX_TIMEOUT_SECONDS}')

        from dfap.ldrm_subsystem.providers.sandbox.mapper import MAPPER_REGISTRY
        if mapper_reference not in MAPPER_REGISTRY:
            raise SandboxAuthorizationError(
                f"Unknown mapper reference '{mapper_reference}'. Registered mappers: "
                + ', '.join(sorted(MAPPER_REGISTRY)))

        if self.find_live(provider_id) is not None:
            raise SandboxAuthorizationError(
                f"Provider '{provider_id}' already has a live sandbox authorization; "
                'revoke it before recording another')

        record = SandboxAuthorization(
            provider_id=provider_id, environment=IntegrationEnvironment.SANDBOX,
            documentation_reference=documentation_reference.strip(),
            documentation_source=documentation_source.strip(),
            provider_contact=provider_contact.strip(), base_url=base_url.rstrip('/'),
            allowed_paths=list(allowed_paths), authentication_method=authentication_method.strip(),
            credential_reference=credential_reference.strip(),
            client_certificate_reference=client_certificate_reference,
            tls_pin_sha256=tls_pin_sha256, mapper_reference=mapper_reference,
            rate_limit_per_minute=rate_limit_per_minute, max_response_bytes=max_response_bytes,
            request_timeout_seconds=request_timeout_seconds, status=St.PENDING,
            authorized_by=user.user_id, expires_at=expires_at, notes=notes.strip())
        self.repository.save_sandbox_authorization(record)
        self.audit.log_event('SANDBOX_AUTHORIZATION_RECORDED', 'SandboxAuthorization',
                             record.sandbox_authorization_id, actor_id,
                             {'provider_id': provider_id, 'base_url': record.base_url,
                              'documentation_reference': record.documentation_reference,
                              'expires_at': expires_at.isoformat(), 'status': 'PENDING'})
        return record

    @atomic
    def activate(self, sandbox_authorization_id, actor_id, reason):
        """Enable traffic. Re-checks the destination and the credential first."""
        user = self.access.administrator(actor_id)
        if not str(reason or '').strip():
            raise SandboxAuthorizationError('Activation requires a recorded reason')
        record = self.repository.get_sandbox_authorization(sandbox_authorization_id)
        if record.status not in {St.PENDING, St.SUSPENDED}:
            raise SandboxAuthorizationError(
                f'Only a PENDING or SUSPENDED authorization can be activated (currently {_v(record.status)})')

        blockers = self.activation_blockers(record)
        if blockers:
            self.audit.log_event('SANDBOX_AUTHORIZATION_ACTIVATION_BLOCKED', 'SandboxAuthorization',
                                 sandbox_authorization_id, actor_id, {'blockers': blockers})
            raise SandboxAuthorizationError(
                'Sandbox activation refused: ' + '; '.join(blockers))

        record.status = St.ACTIVE
        self.repository.save_sandbox_authorization(record)
        self.audit.log_event('SANDBOX_AUTHORIZATION_ACTIVATED', 'SandboxAuthorization',
                             sandbox_authorization_id, actor_id,
                             {'provider_id': record.provider_id, 'reason': reason,
                              'authorized_by': user.user_id})
        return record

    def activation_blockers(self, record) -> List[str]:
        """Everything that must hold before a sandbox may be contacted."""
        blockers = []
        if record.environment != IntegrationEnvironment.SANDBOX:
            blockers.append(f'authorization environment is {_v(record.environment)}, not SANDBOX')
        if record.expires_at is None or record.expires_at <= utc_now():
            blockers.append('authorization has expired or has no recorded expiry')

        try:
            provider = self._provider(record.provider_id)
            if not provider.is_eligible_for_dispatch:
                blockers.append('provider is not VERIFIED and ACTIVE in the registry')
        except Exception as error:
            blockers.append(f'provider record unavailable: {error}')

        # The base URL must be an administrator-verified allowlist entry, not
        # merely a plausible-looking string on this record.
        allowlist = self.repository.list_endpoint_allowlist(
            record.provider_id, IntegrationEnvironment.SANDBOX)
        try:
            SSRFProtection.validate_endpoint(record.base_url, IntegrationEnvironment.SANDBOX,
                                             allowlist=allowlist, provider_id=record.provider_id)
        except SSRFProtectionError as error:
            blockers.append(f'sandbox base URL rejected: {error}')

        if not record.credential_reference:
            blockers.append('no credential reference recorded')
        else:
            try:
                if not self.secrets.secret_exists(record.credential_reference,
                                                  IntegrationEnvironment.SANDBOX):
                    blockers.append(
                        f"credential reference '{record.credential_reference}' does not resolve "
                        'in the SANDBOX environment')
            except Exception as error:
                blockers.append(f'credential reference unusable: {error}')

        if record.client_certificate_reference:
            from dfap.ldrm_subsystem.security.certificates import (
                CertificateValidator, CertificateValidationError)
            try:
                CertificateValidator.validate_certificate(
                    self.repository.get_certificate(record.client_certificate_reference),
                    IntegrationEnvironment.SANDBOX, 'sandbox client certificate')
            except (KeyError, CertificateValidationError) as error:
                blockers.append(f'sandbox client certificate invalid: {error}')
        return blockers

    @atomic
    def suspend(self, sandbox_authorization_id, actor_id, reason):
        return self._change(sandbox_authorization_id, actor_id, St.SUSPENDED, reason,
                            'SANDBOX_AUTHORIZATION_SUSPENDED')

    @atomic
    def revoke(self, sandbox_authorization_id, actor_id, reason):
        record = self._change(sandbox_authorization_id, actor_id, St.REVOKED, reason,
                              'SANDBOX_AUTHORIZATION_REVOKED')
        record.revoked_by, record.revoked_at = actor_id, utc_now()
        record.revocation_reason = reason
        self.repository.save_sandbox_authorization(record)
        return record

    def _change(self, sandbox_authorization_id, actor_id, status, reason, event):
        self.access.administrator(actor_id)
        if not str(reason or '').strip():
            raise SandboxAuthorizationError('A reason is required')
        record = self.repository.get_sandbox_authorization(sandbox_authorization_id)
        if record.status == St.REVOKED:
            raise SandboxAuthorizationError('A REVOKED sandbox authorization is terminal')
        record.status = status
        self.repository.save_sandbox_authorization(record)
        self.audit.log_event(event, 'SandboxAuthorization', sandbox_authorization_id, actor_id,
                             {'provider_id': record.provider_id, 'reason': reason})
        return record

    # -------------------------------------------------------------- querying

    def find_live(self, provider_id) -> Optional[SandboxAuthorization]:
        """The single live authorization for a provider, or None."""
        for record in self.repository.list_sandbox_authorizations(provider_id):
            if record.is_live:
                return record
        return None

    def require_live(self, provider_id) -> SandboxAuthorization:
        """Resolve or refuse. This is the only way a transport is reached."""
        records = self.repository.list_sandbox_authorizations(provider_id)
        for record in records:
            if record.is_live:
                return record
        if records:
            reasons = '; '.join(sorted({r.why_not_live() for r in records if r.why_not_live()}))
            raise SandboxNotAuthorized(
                f"No live sandbox authorization for provider '{provider_id}': {reasons}")
        raise SandboxNotAuthorized(
            f"No sandbox authorization has been recorded for provider '{provider_id}'. "
            "An administrator must record the provider's written sandbox authorization "
            'before any sandbox exchange is possible.')

    def list_authorizations(self, actor_id, provider_id=None):
        self.access.require(actor_id, 'VIEW_REQUEST', active=False)
        return self.repository.list_sandbox_authorizations(provider_id)

    # ------------------------------------------------------------- internals

    def _provider(self, provider_id):
        from dfap.ldrm_subsystem.domain.provider import Provider
        return self.repository.get('provider', provider_id, Provider)

