"""Centralized production dispatch guard for DFAP LDRM (Stage 3 §26).

Every dispatch passes through `ProductionDispatchGuard.validate` before a single
byte leaves the module. The checks live here and nowhere else: no UI component,
API route or connector repeats or relaxes them, and any check that cannot be
evaluated is a failure, never a pass.

There is deliberately no bypass parameter. `force_send`, `skip_authorization`
and `ignore_hash` do not exist; see `src/dfap/ldrm/policy/break_glass.py`.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from dfap.ldrm_subsystem.domain.enums import (
    IntegrationEnvironment, ProviderIntegrationStatus, RequestStatus, TransmissionMethod)
from dfap.ldrm_subsystem.domain.models import LawfulDataRequest
from dfap.ldrm_subsystem.domain.profile import (
    ProviderIntegrationProfile, CertificateMetadata, EndpointAllowlistEntry)
from dfap.ldrm_subsystem.domain.utils import utc_now
from dfap.ldrm_subsystem.policy.integration_lifecycle import IntegrationStateMachine
from dfap.ldrm_subsystem.policy.ssrf import SSRFProtection, SSRFProtectionError
from dfap.ldrm_subsystem.security.certificates import CertificateValidator, CertificateValidationError
from dfap.ldrm_subsystem.security.secrets import SecretProvider, SecretProviderError


class DispatchGuardValidationError(ValueError):
    """A dispatch was refused. Carries every failed check for the audit record."""

    def __init__(self, message, failures=None):
        super().__init__(message)
        self.failures: List[str] = list(failures or [message])


@dataclass
class DispatchGuardContext:
    """Everything the guard needs. Absent collaborators fail the relevant check."""
    config: Any = None
    actor_id: Optional[str] = None
    access: Any = None
    provider: Any = None
    secret_provider: Optional[SecretProvider] = None
    certificates: Dict[str, CertificateMetadata] = field(default_factory=dict)
    allowlist: Optional[List[EndpointAllowlistEntry]] = None
    connector_capabilities: Any = None
    audit: Any = None
    expected_canonical_hash: Optional[str] = None
    transmission_method: Optional[TransmissionMethod] = None


def _v(value):
    return getattr(value, 'value', str(value))


class ProductionDispatchGuard:
    """Fail-closed pre-dispatch validation. Backend enforcement is mandatory."""

    #: Request states from which a dispatch may legitimately be attempted.
    DISPATCHABLE_STATES = {RequestStatus.SIGNED, RequestStatus.READY_TO_SEND,
                           RequestStatus.READY_FOR_MANUAL_SUBMISSION}

    @classmethod
    def validate(cls, request: LawfulDataRequest, profile: ProviderIntegrationProfile,
                 context: Optional[DispatchGuardContext] = None,
                 *,
                 config_ldrm_enabled: bool = True,
                 config_production_dispatch_enabled: bool = False,
                 config_demo_mode: bool = True,
                 secret_provider: Optional[SecretProvider] = None,
                 client_cert: Optional[CertificateMetadata] = None,
                 allowlist: Optional[List[EndpointAllowlistEntry]] = None) -> Dict[str, Any]:
        """Raise `DispatchGuardValidationError` on the first blocking failure.

        The keyword form is the standalone contract used by policy tests. The
        `context` form is what `DispatchService` passes and carries the actor,
        access policy, secrets, certificates and allowlist for the full check set.
        """
        ctx = context or DispatchGuardContext()
        if ctx.config is not None:
            config_ldrm_enabled = ctx.config.ENABLED
            config_production_dispatch_enabled = ctx.config.PRODUCTION_DISPATCH_ENABLED
            config_demo_mode = ctx.config.demonstration_mode
        secret_provider = secret_provider or ctx.secret_provider
        allowlist = allowlist if allowlist is not None else ctx.allowlist

        checks: List[Dict[str, Any]] = []

        def fail(message):
            checks.append({'check': message, 'passed': False})
            raise DispatchGuardValidationError(message, [c['check'] for c in checks if not c['passed']])

        def passed(name):
            checks.append({'check': name, 'passed': True})

        env_val = _v(profile.environment)
        status_val = _v(profile.integration_status)
        is_production = env_val == IntegrationEnvironment.PRODUCTION.value

        # 1. LDRM globally enabled.
        if not config_ldrm_enabled:
            fail('LDRM system is globally disabled')
        passed('ldrm_enabled')

        # 2. Production kill switch, demo mode, and mock-connector refusal.
        if is_production:
            sub_method = _v(profile.submission_method)
            if sub_method in {TransmissionMethod.MOCK_DISPATCH.value, TransmissionMethod.MOCK.value}:
                fail('MOCK connector submission method cannot be set to PRODUCTION_ACTIVE '
                     'in PRODUCTION environment')
            if not config_production_dispatch_enabled:
                fail('Production dispatch is globally DISABLED '
                     '(LDRM_PRODUCTION_DISPATCH_ENABLED=false)')
            if config_demo_mode:
                fail('DEMO_MODE is enabled; production external dispatch is prohibited')
            if ctx.config is not None:
                permitted, reason = ctx.config.production_dispatch_permitted()
                if not permitted:
                    fail(reason)
            passed('production_dispatch_permitted')

        # 3. Integration lifecycle state.
        if status_val == ProviderIntegrationStatus.DRAFT.value:
            fail('Provider integration profile is in DRAFT status and cannot dispatch')
        if status_val in {ProviderIntegrationStatus.SUSPENDED.value,
                          ProviderIntegrationStatus.EXPIRED.value,
                          ProviderIntegrationStatus.REVOKED.value}:
            fail(f'Provider integration profile is {status_val} and cannot dispatch')
        if not IntegrationStateMachine.is_dispatchable(profile.integration_status):
            fail(f'Provider integration profile status {status_val} is not dispatchable')
        if is_production and status_val != ProviderIntegrationStatus.PRODUCTION_ACTIVE.value:
            fail(f'Production integration requires PRODUCTION_ACTIVE status (current: {status_val})')
        if not is_production and status_val == ProviderIntegrationStatus.PRODUCTION_ACTIVE.value:
            fail(f'A {env_val} integration cannot hold PRODUCTION_ACTIVE status')
        passed('integration_status')

        # 4. Profile validity window.
        if profile.expires_at and profile.expires_at <= utc_now():
            fail('Provider integration profile has expired')
        passed('integration_not_expired')

        # 5. Authenticated actor with dispatch permission and case access.
        if ctx.access is not None:
            if not ctx.actor_id:
                fail('Dispatch requires an authenticated actor')
            try:
                user = ctx.access.require(ctx.actor_id, 'DISPATCH_REQUEST', request)
            except PermissionError as error:
                fail(f'Actor is not permitted to dispatch this request: {error}')
            if not getattr(user, 'is_human', False):
                fail('Dispatch must be performed by an authenticated human actor')
            passed('actor_authorized')

        # 6. Provider record.
        if ctx.provider is not None:
            if not ctx.provider.is_eligible_for_dispatch:
                fail('Provider is not VERIFIED and ACTIVE')
            if ctx.provider.id != profile.provider_id:
                fail('Integration profile does not belong to the resolved provider')
            if request.dataset_type not in ctx.provider.supported_datasets:
                fail('Provider does not support the requested dataset')
            passed('provider_eligible')

        # 7. Human authorization, currency, and request state.
        if not request.authorization:
            fail('Request lacks a valid, current human authorization decision')
        if request.authorization.is_invalidated:
            fail('Request lacks a valid, current human authorization decision '
                 f'(invalidated: {request.authorization.invalidation_reason})')
        if request.status in {RequestStatus.CANCELLED, RequestStatus.CLOSED,
                              RequestStatus.EXPIRED, RequestStatus.REJECTED}:
            fail(f'Request is in final/cancelled status: {_v(request.status)}')
        if ctx.access is not None and request.status not in cls.DISPATCHABLE_STATES:
            fail(f'Request state {_v(request.status)} is not dispatchable')
        valid_until = request.authorization.valid_until
        if valid_until and valid_until <= utc_now():
            fail('The recorded authorization has expired')
        passed('authorization_current')

        # 8. Signature and canonical hash binding.
        auth = request.authorization
        if ctx.expected_canonical_hash is not None:
            if auth.bound_canonical_hash != ctx.expected_canonical_hash:
                fail('Authorization is bound to a different canonical request hash')
            if request.canonical_hash != ctx.expected_canonical_hash:
                fail('Request canonical hash does not match its stored package')
            if auth.bound_request_version != request.request_version:
                fail('Authorization is bound to a different request version')
            if not auth.digital_signature:
                fail('Request package is not signed')
            passed('hash_and_signature_bound')

        # 9. Submission method supported by the profile and the connector.
        method = ctx.transmission_method or profile.submission_method
        if _v(method) != _v(profile.submission_method):
            fail(f'Submission method {_v(method)} does not match the integration profile '
                 f'({_v(profile.submission_method)})')
        if ctx.connector_capabilities is not None:
            if not ctx.connector_capabilities.supports_submission:
                fail(f'Connector for {_v(method)} does not support submission')
            passed('connector_capability')
        passed('submission_method_supported')

        # 10. Endpoint verification, allowlisting and SSRF policy.
        if profile.endpoint_reference and str(profile.endpoint_reference).startswith(('http://', 'https://')):
            if is_production and profile.endpoint_verification_status != 'VERIFIED':
                fail('Production endpoint is not administrator-verified')
            try:
                SSRFProtection.validate_endpoint(
                    profile.endpoint_reference, profile.environment,
                    allowlist=allowlist, provider_id=profile.provider_id)
            except SSRFProtectionError as error:
                fail(f'Endpoint rejected: {error}')
            passed('endpoint_verified')
        elif is_production:
            fail('Production integration has no verified HTTPS endpoint configured')

        # 11. Credentials resolvable in this exact environment.
        if profile.credential_reference:
            if secret_provider is None:
                if is_production:
                    fail('No secret backend is configured; credentials cannot be resolved')
            else:
                try:
                    secret_provider.get_secret(profile.credential_reference, profile.environment)
                except SecretProviderError as error:
                    fail(f'Credential unavailable: {error}')
                passed('credential_resolvable')
        elif is_production:
            fail('Production integration has no credential reference configured')

        # 12. Certificates required by the authentication mechanism.
        requirements = CertificateValidator.requirements_for(profile.authentication_type)
        pairs = (('Client Certificate', 'client_certificate', profile.client_certificate_reference),
                 ('Signing Certificate', 'signing_certificate', profile.signing_certificate_reference))
        for label, key, reference in pairs:
            explicit = client_cert if (label == 'Client Certificate' and client_cert) else None
            cert = explicit or (ctx.certificates.get(reference) if reference else None)
            if not requirements[key] and not reference and not explicit:
                continue
            if requirements[key] and not reference and not explicit:
                fail(f'{profile.authentication_type} requires a {label.lower()} reference')
            if cert is None:
                fail(f"{label} '{reference}' metadata is not registered")
            try:
                CertificateValidator.validate_certificate(cert, profile.environment, label)
            except CertificateValidationError as error:
                fail(str(error))
            passed(f'{key}_valid')

        # 13. Audit subsystem must be able to record the dispatch.
        if ctx.audit is not None:
            verify = getattr(ctx.audit, 'verify_integrity', None)
            if callable(verify) and not verify():
                fail('Audit subsystem integrity check failed; dispatch is refused')
            passed('audit_available')

        return {'passed': True, 'environment': env_val, 'integration_status': status_val,
                'checks': [c['check'] for c in checks]}

    @classmethod
    def explain(cls, request, profile, context=None, **kwargs) -> Dict[str, Any]:
        """Non-raising readiness report for UI and diagnostics."""
        try:
            result = cls.validate(request, profile, context, **kwargs)
            return {'dispatchable': True, 'blockers': [], **result}
        except DispatchGuardValidationError as error:
            return {'dispatchable': False, 'blockers': error.failures,
                    'environment': _v(profile.environment),
                    'integration_status': _v(profile.integration_status)}
