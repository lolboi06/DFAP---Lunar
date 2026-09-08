"""Provider integration profile administration (DFAP Stage 3 §5, §6, §7, §14, §15).

Every lifecycle advance is an administrator action recorded against a named human
actor. Nothing in this service can be satisfied by generated output: security
review, agency approval and provider approval are separate recorded decisions by
authorized human users, and production activation re-checks all of them.
"""
import uuid
from copy import deepcopy
from datetime import timedelta

from dfap.ldrm_subsystem.domain.enums import (
    IntegrationEnvironment, ProviderIntegrationStatus as S, CertificationResult,
    TransmissionMethod, DatasetType, CertificateType)
from dfap.ldrm_subsystem.domain.profile import (
    ProviderIntegrationProfile, CertificateMetadata, EndpointAllowlistEntry)
from dfap.ldrm_subsystem.domain.utils import utc_now
from dfap.ldrm_subsystem.persistence.unit_of_work import atomic
from dfap.ldrm_subsystem.policy.integration_lifecycle import (
    IntegrationStateMachine, InvalidIntegrationTransitionError, IntegrationActivationError)
from dfap.ldrm_subsystem.policy.ssrf import SSRFProtection, SSRFProtectionError
from dfap.ldrm_subsystem.security.certificates import CertificateValidator, CertificateValidationError
from dfap.ldrm_subsystem.security.secrets import SecretProviderError


class IntegrationServiceError(ValueError):
    pass


#: Recorded human decisions required before production activation.
SECURITY_REVIEW = 'SECURITY_REVIEW'
AGENCY_APPROVAL = 'AGENCY_APPROVAL'
PROVIDER_APPROVAL = 'PROVIDER_APPROVAL'
DOCUMENTATION = 'DOCUMENTATION_VERIFICATION'

#: Which recorded approval each forward transition depends on.
_TRANSITION_REQUIRES = {
    S.DOCUMENTATION_VERIFIED: DOCUMENTATION,
    S.SECURITY_REVIEWED: SECURITY_REVIEW,
    S.AGENCY_APPROVED: AGENCY_APPROVAL,
    S.PROVIDER_APPROVED: PROVIDER_APPROVAL,
}


def _v(value):
    return getattr(value, 'value', str(value))


class IntegrationService:
    def __init__(self, repository, access, audit, config, secret_provider):
        self.repository, self.access, self.audit = repository, access, audit
        # `atomic` records failures through `audit_adapter`; keep the same journal.
        self.audit_adapter = audit
        self.config, self.secrets = config, secret_provider

    # ---------------------------------------------------------------- profiles

    def get_profile(self, integration_profile_id, actor_id):
        self.access.require(actor_id, 'VIEW_REQUEST', active=False)
        return self.repository.get_integration_profile(integration_profile_id)

    def list_profiles(self, actor_id, provider_id=None, environment=None):
        self.access.require(actor_id, 'VIEW_REQUEST', active=False)
        return self.repository.list_integration_profiles(provider_id, environment)

    def resolve_for_dispatch(self, provider_id, environment):
        """The profile a dispatch will use. Absence is a refusal, never a default."""
        profile = self.repository.find_integration_profile(provider_id, environment)
        if profile is None:
            raise IntegrationServiceError(
                f"No provider integration profile is configured for provider '{provider_id}' "
                f'in environment {_v(environment)}; dispatch fails closed')
        return profile

    @atomic
    def create_profile(self, actor_id, *, provider_id, environment, submission_method,
                       response_method='MOCK', supported_dataset_types=None,
                       supported_request_categories=None, endpoint_reference='',
                       authentication_type='HMAC_SECRET', credential_reference='',
                       client_certificate_reference=None, signing_certificate_reference=None,
                       required_documents=None, required_fields=None,
                       accepted_request_formats=None, accepted_response_formats=None,
                       webhook_enabled=False, webhook_reference=None, expires_at=None):
        self.access.administrator(actor_id)
        environment = IntegrationEnvironment(_v(environment))
        provider = self._provider(provider_id)
        if self.repository.find_integration_profile(provider_id, environment) is not None:
            raise IntegrationServiceError(
                f"Provider '{provider_id}' already has a {_v(environment)} integration profile")
        submission_method = TransmissionMethod(_v(submission_method))
        self._assert_environment_method(environment, submission_method)
        profile = ProviderIntegrationProfile(
            integration_profile_id=f'IPROF-{uuid.uuid4().hex[:12].upper()}',
            provider_id=provider_id, environment=environment, submission_method=submission_method,
            response_method=response_method,
            supported_dataset_types=[DatasetType(_v(d)) for d in (supported_dataset_types or provider.supported_datasets)],
            supported_request_categories=list(supported_request_categories or []),
            endpoint_reference=endpoint_reference or '',
            endpoint_verification_status='UNVERIFIED',
            authentication_type=authentication_type, credential_reference=credential_reference or '',
            client_certificate_reference=client_certificate_reference,
            signing_certificate_reference=signing_certificate_reference,
            required_documents=list(required_documents or []), required_fields=list(required_fields or []),
            accepted_request_formats=list(accepted_request_formats or ['application/json']),
            accepted_response_formats=list(accepted_response_formats or ['application/json']),
            webhook_enabled=bool(webhook_enabled), webhook_reference=webhook_reference,
            integration_status=S.DRAFT, expires_at=expires_at)
        self.repository.save_integration_profile(profile)
        self.audit.log_event('PROVIDER_INTEGRATION_CREATED', 'ProviderIntegrationProfile',
                             profile.integration_profile_id, actor_id, self._safe(profile))
        return profile

    @atomic
    def update_profile(self, integration_profile_id, actor_id, **changes):
        """Any change to endpoint, credentials or certificates resets verification."""
        self.access.administrator(actor_id)
        profile = self.repository.get_integration_profile(integration_profile_id)
        if profile.integration_status == S.REVOKED:
            raise IntegrationServiceError('A REVOKED integration cannot be modified')
        sensitive = {'endpoint_reference', 'credential_reference', 'client_certificate_reference',
                     'signing_certificate_reference', 'authentication_type', 'submission_method',
                     'webhook_reference', 'webhook_enabled'}
        touched = []
        for key, value in changes.items():
            if value is None or not hasattr(profile, key):
                continue
            if key == 'submission_method':
                value = TransmissionMethod(_v(value))
                self._assert_environment_method(profile.environment, value)
            if key == 'supported_dataset_types':
                value = [DatasetType(_v(d)) for d in value]
            if value != getattr(profile, key):
                setattr(profile, key, deepcopy(value))
                touched.append(key)
        if not touched:
            return profile
        reset = bool(sensitive.intersection(touched))
        if reset:
            # Changing what the integration talks to, or as whom, invalidates
            # every verification and approval that was made about the old value.
            profile.endpoint_verification_status = 'UNVERIFIED'
            profile.verified_by = profile.verified_at = None
            if profile.integration_status != S.DRAFT:
                self._change_status(profile, S.DRAFT, actor_id,
                                    f'Security-relevant configuration changed: {", ".join(sorted(touched))}',
                                    force=True)
        profile.updated_at = utc_now()
        self.repository.save_integration_profile(profile)
        for key in ('endpoint_reference', 'credential_reference',
                    'client_certificate_reference', 'signing_certificate_reference'):
            if key in touched:
                self.audit.log_event(
                    {'endpoint_reference': 'PROVIDER_ENDPOINT_CHANGED',
                     'credential_reference': 'PROVIDER_CREDENTIAL_REFERENCE_CHANGED',
                     'client_certificate_reference': 'PROVIDER_CERTIFICATE_CHANGED',
                     'signing_certificate_reference': 'PROVIDER_CERTIFICATE_CHANGED'}[key],
                    'ProviderIntegrationProfile', profile.integration_profile_id, actor_id,
                    {'field': key, 'verification_reset': reset})
        self.audit.log_event('PROVIDER_INTEGRATION_UPDATED', 'ProviderIntegrationProfile',
                             profile.integration_profile_id, actor_id,
                             {'changed': sorted(touched), 'verification_reset': reset})
        return profile

    # ------------------------------------------------------- configuration check

    def validate_configuration(self, integration_profile_id, actor_id):
        """Non-mutating readiness report. Never advances the lifecycle by itself."""
        self.access.require(actor_id, 'VIEW_REQUEST', active=False)
        profile = self.repository.get_integration_profile(integration_profile_id)
        checks, env = [], profile.environment

        def check(name, ok, detail=''):
            checks.append({'check': name, 'passed': bool(ok), 'detail': detail})

        try:
            provider = self._provider(profile.provider_id)
            check('provider_verified', provider.is_eligible_for_dispatch,
                  f'verification={provider.verification_status.value}, active={provider.active_status.value}')
        except Exception as error:
            check('provider_verified', False, str(error))

        check('supported_datasets_declared', bool(profile.supported_dataset_types),
              ','.join(_v(d) for d in profile.supported_dataset_types))
        check('request_categories_declared', bool(profile.supported_request_categories),
              ','.join(profile.supported_request_categories))
        check('authentication_configured', bool(profile.authentication_type), profile.authentication_type)

        if profile.endpoint_reference:
            try:
                SSRFProtection.validate_endpoint(
                    profile.endpoint_reference, env,
                    allowlist=self.repository.list_endpoint_allowlist(profile.provider_id, env),
                    provider_id=profile.provider_id)
                check('endpoint_allowlisted', True, profile.endpoint_reference)
            except SSRFProtectionError as error:
                check('endpoint_allowlisted', False, str(error))
        else:
            check('endpoint_allowlisted', env == IntegrationEnvironment.MOCK,
                  'no endpoint configured')
        check('endpoint_verified', profile.endpoint_verification_status == 'VERIFIED',
              profile.endpoint_verification_status)

        if profile.credential_reference:
            try:
                check('credential_resolvable',
                      self.secrets.secret_exists(profile.credential_reference, env),
                      f'reference={profile.credential_reference}')
            except SecretProviderError as error:
                check('credential_resolvable', False, str(error))
        else:
            check('credential_resolvable', env == IntegrationEnvironment.MOCK,
                  'no credential reference configured')

        requirements = CertificateValidator.requirements_for(profile.authentication_type)
        for label, reference in (('client_certificate', profile.client_certificate_reference),
                                 ('signing_certificate', profile.signing_certificate_reference)):
            if not requirements[label] and not reference:
                check(f'{label}_valid', True, 'not required by this authentication type')
                continue
            if not reference:
                check(f'{label}_valid', False,
                      f'{profile.authentication_type} requires a {label} reference')
                continue
            try:
                cert = self.repository.get_certificate(reference)
                CertificateValidator.validate_certificate(cert, env, label)
                check(f'{label}_valid', True, f'expires {cert.valid_until.isoformat()}')
            except (KeyError, CertificateValidationError) as error:
                check(f'{label}_valid', False, str(error))

        check('not_expired', not (profile.expires_at and profile.expires_at <= utc_now()),
              profile.expires_at.isoformat() if profile.expires_at else 'no expiry set')

        records = self.repository.list_certification_records(integration_profile_id)
        passing = [r for r in records if r.result == CertificationResult.PASS]
        check('contract_tests_passed', bool(passing),
              f'{len(records)} record(s), {len(passing)} passing')

        approvals = self.repository.get_live_approvals(integration_profile_id)
        for kind in (DOCUMENTATION, SECURITY_REVIEW, AGENCY_APPROVAL, PROVIDER_APPROVAL):
            recorded = approvals.get(kind)
            check(kind.lower(), bool(recorded),
                  f"recorded by {recorded['approved_by']}" if recorded else 'not recorded')

        permitted, reason = self.config.production_dispatch_permitted()
        check('production_dispatch_enabled', permitted, reason or 'enabled')

        self.audit.log_event('PROVIDER_INTEGRATION_CONFIGURATION_VALIDATED',
                             'ProviderIntegrationProfile', integration_profile_id, actor_id,
                             {'failed': [c['check'] for c in checks if not c['passed']]})
        return {'integration_profile_id': integration_profile_id,
                'environment': _v(env), 'integration_status': _v(profile.integration_status),
                'checks': checks,
                'passed': all(c['passed'] for c in checks),
                'failed_checks': [c['check'] for c in checks if not c['passed']]}

    # ------------------------------------------------------------- endpoint verify

    @atomic
    def verify_endpoint(self, integration_profile_id, actor_id, notes=''):
        """An administrator confirms the destination against institutional documentation."""
        user = self.access.administrator(actor_id)
        profile = self.repository.get_integration_profile(integration_profile_id)
        if not profile.endpoint_reference:
            raise IntegrationServiceError('No endpoint is configured on this integration profile')
        if not notes.strip():
            raise IntegrationServiceError('Endpoint verification requires the source of the destination')
        SSRFProtection.validate_endpoint(
            profile.endpoint_reference, profile.environment,
            allowlist=self.repository.list_endpoint_allowlist(profile.provider_id, profile.environment),
            provider_id=profile.provider_id)
        profile.endpoint_verification_status = 'VERIFIED'
        profile.verified_by, profile.verified_at = user.user_id, utc_now()
        profile.last_reviewed_at = profile.verified_at
        profile.updated_at = profile.verified_at
        self.repository.save_integration_profile(profile)
        self.audit.log_event('PROVIDER_ENDPOINT_VERIFIED', 'ProviderIntegrationProfile',
                             integration_profile_id, actor_id,
                             {'endpoint': profile.endpoint_reference, 'notes': notes})
        return profile

    @atomic
    def add_allowlist_entry(self, actor_id, provider_id, environment, url, notes=''):
        user = self.access.administrator(actor_id)
        environment = IntegrationEnvironment(_v(environment))
        if not notes.strip():
            raise IntegrationServiceError('An allowlist entry requires the documented source of the URL')
        # The URL itself must survive every transport rule before it is trusted.
        SSRFProtection.validate_endpoint(url, environment)
        entry = EndpointAllowlistEntry(id=f'EPA-{uuid.uuid4().hex[:12].upper()}', provider_id=provider_id,
                                       environment=environment, url=url, verified_by=user.user_id)
        self.repository.save_endpoint_allowlist_entry(entry)
        self.audit.log_event('PROVIDER_ENDPOINT_ALLOWLISTED', 'ProviderIntegrationProfile',
                             provider_id, actor_id, {'url': url, 'environment': _v(environment), 'notes': notes})
        return entry

    def list_allowlist(self, actor_id, provider_id=None, environment=None):
        self.access.require(actor_id, 'VIEW_REQUEST', active=False)
        return self.repository.list_endpoint_allowlist(provider_id, environment)

    # ------------------------------------------------------------ human approvals

    @atomic
    def record_approval(self, integration_profile_id, actor_id, kind, reference, notes, expires_at=None):
        """Record a human decision. The actor must be an authenticated administrator."""
        user = self.access.administrator(actor_id)
        if kind not in {SECURITY_REVIEW, AGENCY_APPROVAL, PROVIDER_APPROVAL, DOCUMENTATION}:
            raise IntegrationServiceError(f"Unknown approval kind '{kind}'")
        profile = self.repository.get_integration_profile(integration_profile_id)
        if not reference.strip() or not notes.strip():
            raise IntegrationServiceError(
                f'{kind} requires an external reference and the reviewer\'s decision notes')
        if not user.is_human:
            raise IntegrationServiceError(
                f'{kind} must be recorded by an authenticated human actor')
        approval = {'id': f'APPR-{uuid.uuid4().hex[:12].upper()}',
                    'integration_profile_id': integration_profile_id, 'approval_kind': kind,
                    'approved_by': user.user_id, 'approver_role': user.role,
                    'reference': reference.strip(), 'notes': notes.strip(),
                    'approved_at': utc_now().isoformat(),
                    'expires_at': expires_at.isoformat() if expires_at else None}
        self.repository.record_integration_approval(approval)
        self.audit.log_event(f'INTEGRATION_{kind}_RECORDED', 'ProviderIntegrationProfile',
                             integration_profile_id, actor_id,
                             {'reference': approval['reference'], 'approver_role': user.role})
        profile.last_reviewed_at = utc_now()
        self.repository.save_integration_profile(profile)
        return approval

    def live_approvals(self, integration_profile_id):
        return self.repository.get_live_approvals(integration_profile_id)

    # -------------------------------------------------------- contract testing

    @atomic
    def run_contract_tests(self, integration_profile_id, actor_id, module=None):
        """Run the contract suite and persist an immutable certification record.

        The record proves a suite ran. It never grants an approval, and it never
        advances the lifecycle: `advance_status` to CONTRACT_TESTED is a separate
        administrator action that additionally requires a passing record.
        """
        from dfap.ldrm_subsystem.providers.contract_testing import ProviderContractTester, ContractTestError
        user = self.access.administrator(actor_id)
        profile = self.repository.get_integration_profile(integration_profile_id)
        if profile.environment == IntegrationEnvironment.PRODUCTION:
            raise ContractTestError(
                'Contract tests never run against a PRODUCTION integration')
        report = ProviderContractTester.execute(
            profile, module, repository=self.repository, secret_provider=self.secrets)
        record = ProviderContractTester.to_certification_record(report, user.user_id)
        self.repository.save_certification_record(record)
        assert record.approved_by is None, 'a contract run must never record an approval'
        self.audit.log_event('INTEGRATION_CONTRACT_TESTS_RUN', 'ProviderIntegrationProfile',
                             integration_profile_id, actor_id,
                             {'certification_id': record.certification_id,
                              'result': _v(record.result), 'passed': record.tests_passed,
                              'failed': record.tests_failed, 'skipped': report.skipped_count})
        return {'certification': record.to_dict(), 'report': report.to_dict()}

    def list_certifications(self, integration_profile_id, actor_id):
        self.access.require(actor_id, 'VIEW_REQUEST', active=False)
        return self.repository.list_certification_records(integration_profile_id)

    # ------------------------------------------------------------ certificates

    @atomic
    def register_certificate(self, actor_id, *, certificate_reference, certificate_type, issuer,
                             fingerprint, valid_from, valid_until, environment, status='ACTIVE'):
        """Record certificate METADATA. Private key material is never accepted here."""
        self.access.administrator(actor_id)
        if not fingerprint.strip() or not issuer.strip():
            raise IntegrationServiceError('Certificate issuer and fingerprint are required')
        for field_name, value in (('valid_from', valid_from), ('valid_until', valid_until)):
            if value.tzinfo is None:
                raise IntegrationServiceError(f'{field_name} must include a timezone')
        if valid_until <= valid_from:
            raise IntegrationServiceError('Certificate validity interval is invalid')
        cert = CertificateMetadata(
            certificate_reference=certificate_reference,
            certificate_type=CertificateType(_v(certificate_type)), issuer=issuer,
            fingerprint=fingerprint, valid_from=valid_from, valid_until=valid_until,
            status=status, environment=IntegrationEnvironment(_v(environment)))
        self.repository.save_certificate(cert)
        self.audit.log_event('PROVIDER_CERTIFICATE_REGISTERED', 'Certificate',
                             certificate_reference, actor_id,
                             {'type': _v(cert.certificate_type), 'environment': _v(cert.environment),
                              'issuer': issuer, 'valid_until': valid_until.isoformat()})
        return cert

    def list_certificates(self, actor_id, environment=None):
        self.access.require(actor_id, 'VIEW_REQUEST', active=False)
        return self.repository.list_certificates(environment)

    def expiring_certificates(self, days=None):
        days = self.config.EXPIRY_WARNING_DAYS if days is None else days
        return CertificateValidator.get_expiring_certificates(self.repository.list_certificates(), days)

    # -------------------------------------------------------------- lifecycle

    @atomic
    def advance_status(self, integration_profile_id, actor_id, target_status, reason=''):
        """One controlled step. Production activation goes through activate()."""
        user = self.access.administrator(actor_id)
        target = S(_v(target_status))
        profile = self.repository.get_integration_profile(integration_profile_id)
        if target == S.PRODUCTION_ACTIVE:
            raise IntegrationServiceError(
                'Production activation requires activate(), which re-checks every prerequisite')
        if not reason.strip():
            raise IntegrationServiceError('A lifecycle change requires a recorded reason')
        IntegrationStateMachine.validate_transition(profile.integration_status, target, profile.environment)
        required = _TRANSITION_REQUIRES.get(target)
        if required and required not in self.repository.get_live_approvals(integration_profile_id):
            raise IntegrationActivationError(
                f'{_v(target)} requires a recorded {required} by an authorized human actor')
        if target == S.CONTRACT_TESTED:
            passing = [r for r in self.repository.list_certification_records(integration_profile_id)
                       if r.result == CertificationResult.PASS]
            if not passing:
                raise IntegrationActivationError(
                    'CONTRACT_TESTED requires a passing integration certification record')
        self._change_status(profile, target, user.user_id, reason, actor_role=user.role)
        self.repository.save_integration_profile(profile)
        return profile

    @atomic
    def activate_production(self, integration_profile_id, actor_id, reason=''):
        """The only path to PRODUCTION_ACTIVE. Every §7 requirement is re-checked here."""
        user = self.access.administrator(actor_id)
        profile = self.repository.get_integration_profile(integration_profile_id)
        if not reason.strip():
            raise IntegrationServiceError('Production activation requires a recorded reason')

        blockers = self.production_activation_blockers(profile)
        if blockers:
            self.audit.log_event('INTEGRATION_PRODUCTION_ACTIVATION_BLOCKED',
                                 'ProviderIntegrationProfile', integration_profile_id, actor_id,
                                 {'blockers': blockers})
            raise IntegrationActivationError(
                'Production activation refused. Unsatisfied requirements: ' + '; '.join(blockers))

        IntegrationStateMachine.validate_transition(
            profile.integration_status, S.PRODUCTION_ACTIVE, profile.environment)
        self._change_status(profile, S.PRODUCTION_ACTIVE, user.user_id, reason, actor_role=user.role)
        self.repository.save_integration_profile(profile)
        self.audit.log_event('INTEGRATION_PRODUCTION_ACTIVATED', 'ProviderIntegrationProfile',
                             integration_profile_id, actor_id, {'reason': reason, 'approver_role': user.role})
        return profile

    def production_activation_blockers(self, profile):
        """Every §7 requirement, evaluated independently. Empty list means eligible."""
        blockers = []
        pid = profile.integration_profile_id

        if profile.environment != IntegrationEnvironment.PRODUCTION:
            blockers.append(f'integration environment is {_v(profile.environment)}, not PRODUCTION')
        if _v(profile.submission_method) in {TransmissionMethod.MOCK_DISPATCH.value, TransmissionMethod.MOCK.value}:
            blockers.append('a mock submission method can never be production-active')
        if profile.integration_status != S.PROVIDER_APPROVED:
            blockers.append(
                f'integration must be PROVIDER_APPROVED before activation (currently {_v(profile.integration_status)})')

        try:
            provider = self._provider(profile.provider_id)
            if not provider.is_eligible_for_dispatch:
                blockers.append('provider is not VERIFIED and ACTIVE')
        except Exception as error:
            blockers.append(f'provider record unavailable: {error}')

        approvals = self.repository.get_live_approvals(pid)
        for kind, label in ((DOCUMENTATION, 'official integration documentation'),
                            (SECURITY_REVIEW, 'security review'),
                            (AGENCY_APPROVAL, 'agency approval'),
                            (PROVIDER_APPROVAL, 'provider approval')):
            recorded = approvals.get(kind)
            if not recorded:
                blockers.append(f'no recorded {label}')
            elif recorded.get('expires_at') and recorded['expires_at'] <= utc_now().isoformat():
                blockers.append(f'recorded {label} has expired')

        if not profile.supported_request_categories:
            blockers.append('supported request categories are not defined')
        if not profile.authentication_type:
            blockers.append('no authentication mechanism is configured')
        if profile.endpoint_verification_status != 'VERIFIED':
            blockers.append('endpoint is not administrator-verified')

        if profile.endpoint_reference:
            try:
                SSRFProtection.validate_endpoint(
                    profile.endpoint_reference, profile.environment,
                    allowlist=self.repository.list_endpoint_allowlist(
                        profile.provider_id, profile.environment),
                    provider_id=profile.provider_id)
            except SSRFProtectionError as error:
                blockers.append(f'endpoint rejected: {error}')
        else:
            blockers.append('no endpoint is configured')

        if not profile.credential_reference:
            blockers.append('no credential reference is configured')
        else:
            try:
                if not self.secrets.secret_exists(profile.credential_reference, profile.environment):
                    blockers.append('credential reference does not resolve in this environment')
            except SecretProviderError as error:
                blockers.append(f'credential reference unusable: {error}')

        requirements = CertificateValidator.requirements_for(profile.authentication_type)
        for label, reference in (('client certificate', profile.client_certificate_reference),
                                 ('signing certificate', profile.signing_certificate_reference)):
            required = requirements['client_certificate' if 'client' in label else 'signing_certificate']
            if not required and not reference:
                continue
            if not reference:
                blockers.append(f'{profile.authentication_type} requires a {label}')
                continue
            try:
                CertificateValidator.validate_certificate(
                    self.repository.get_certificate(reference), profile.environment, label)
            except (KeyError, CertificateValidationError) as error:
                blockers.append(f'{label} invalid: {error}')

        passing = [r for r in self.repository.list_certification_records(pid)
                   if r.result == CertificationResult.PASS]
        if not passing:
            blockers.append('no passing sandbox/contract certification record')
        elif passing[0].expires_at and passing[0].expires_at <= utc_now():
            blockers.append('the most recent passing certification record has expired')

        if profile.expires_at and profile.expires_at <= utc_now():
            blockers.append('integration profile has expired')

        permitted, reason = self.config.production_dispatch_permitted()
        if not permitted:
            blockers.append(reason)
        return blockers

    @atomic
    def suspend(self, integration_profile_id, actor_id, reason):
        return self._interrupt(integration_profile_id, actor_id, S.SUSPENDED, reason,
                               'INTEGRATION_SUSPENDED')

    @atomic
    def revoke(self, integration_profile_id, actor_id, reason):
        return self._interrupt(integration_profile_id, actor_id, S.REVOKED, reason,
                               'INTEGRATION_REVOKED')

    @atomic
    def mark_expired(self, integration_profile_id, actor_id, reason='Integration validity elapsed'):
        return self._interrupt(integration_profile_id, actor_id, S.EXPIRED, reason,
                               'INTEGRATION_EXPIRED')

    def _interrupt(self, integration_profile_id, actor_id, target, reason, event):
        user = self.access.administrator(actor_id)
        if not reason.strip():
            raise IntegrationServiceError('A reason is required')
        profile = self.repository.get_integration_profile(integration_profile_id)
        IntegrationStateMachine.validate_transition(profile.integration_status, target)
        self._change_status(profile, target, user.user_id, reason, actor_role=user.role)
        self.repository.save_integration_profile(profile)
        self.audit.log_event(event, 'ProviderIntegrationProfile', integration_profile_id,
                             actor_id, {'reason': reason})
        return profile

    # ---------------------------------------------------------------- internals

    def _change_status(self, profile, target, actor_id, reason, actor_role='ADMIN', force=False):
        previous = profile.integration_status
        if not force:
            IntegrationStateMachine.validate_transition(previous, target, profile.environment)
        profile.integration_status = target
        profile.updated_at = utc_now()
        self.repository.record_integration_status_change({
            'id': f'ISH-{uuid.uuid4().hex[:12].upper()}',
            'integration_profile_id': profile.integration_profile_id,
            'from_status': _v(previous), 'to_status': _v(target), 'actor_id': actor_id,
            'actor_role': actor_role, 'reason': reason, 'changed_at': utc_now().isoformat()})
        self.audit.log_event('INTEGRATION_STATUS_CHANGED', 'ProviderIntegrationProfile',
                             profile.integration_profile_id, actor_id,
                             {'from': _v(previous), 'to': _v(target), 'reason': reason})

    def _provider(self, provider_id):
        from dfap.ldrm_subsystem.domain.provider import Provider
        return self.repository.get('provider', provider_id, Provider)

    @staticmethod
    def _assert_environment_method(environment, submission_method):
        env, method = _v(environment), _v(submission_method)
        mock_methods = {TransmissionMethod.MOCK_DISPATCH.value, TransmissionMethod.MOCK.value}
        if env == IntegrationEnvironment.MOCK.value and method not in mock_methods | {
                TransmissionMethod.OFFICIAL_EMAIL.value, TransmissionMethod.OFFICIAL_API.value,
                TransmissionMethod.MANUAL_PORTAL.value, TransmissionMethod.PHYSICAL_SUBMISSION.value,
                TransmissionMethod.PROVIDER_PORTAL.value, TransmissionMethod.GOVERNMENT_GATEWAY.value,
                TransmissionMethod.SECURE_FILE_TRANSFER.value}:
            raise IntegrationServiceError(f"'{method}' is not a MOCK-capable submission method")
        if env != IntegrationEnvironment.MOCK.value and method in mock_methods:
            raise IntegrationServiceError(
                f"A mock submission method cannot be used in the {env} environment")

    @staticmethod
    def _safe(profile):
        """Audit metadata: references only, never resolved secret or key material."""
        data = profile.to_dict()
        return {k: data[k] for k in ('provider_id', 'environment', 'submission_method',
                                     'integration_status', 'authentication_type',
                                     'endpoint_verification_status')}
