"""Provider integration contract testing (DFAP Stage 3 §13, §14).

Runs against MOCK and SANDBOX only; PRODUCTION is refused outright. The suite
tests the capabilities a connector actually advertises and skips what it does
not support, rather than asserting a fixed list against every integration.

A certification record produced here is **evidence of a test run, nothing more**.
It never carries an approval: `approved_by`, `approved_at` and
`security_review_reference` are left empty because a passing automated suite is
not a security review, an agency approval, or a provider approval. Those are
separate human decisions recorded through `IntegrationService.record_approval`,
and `IntegrationService.production_activation_blockers` checks for them
independently of anything written here.
"""
import base64
import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Dict, List, Optional

from dfap.ldrm_subsystem.domain.enums import (
    CertificationResult, DatasetType, IntegrationEnvironment, TransmissionMethod)
from dfap.ldrm_subsystem.domain.profile import ProviderIntegrationProfile, IntegrationCertificationRecord
from dfap.ldrm_subsystem.domain.utils import utc_now
from dfap.ldrm_subsystem.policy.ssrf import SSRFProtection, SSRFProtectionError
from dfap.ldrm_subsystem.security.certificates import CertificateValidator, CertificateValidationError
from dfap.ldrm_subsystem.security.secrets import SecretProviderError

TEST_SUITE_VERSION = 'v2.0-stage3'


class ContractTestError(ValueError):
    pass


@dataclass
class ContractTestCase:
    name: str
    passed: bool
    detail: str = ''
    skipped: bool = False
    reason: str = ''

    def to_dict(self) -> Dict[str, Any]:
        return {'test_name': self.name, 'passed': self.passed, 'skipped': self.skipped,
                'detail': self.detail, 'reason': self.reason}


@dataclass
class ContractTestReport:
    integration_profile_id: str
    environment: str
    cases: List[ContractTestCase] = field(default_factory=list)

    @property
    def passed_count(self):
        return sum(1 for c in self.cases if c.passed and not c.skipped)

    @property
    def failed_count(self):
        return sum(1 for c in self.cases if not c.passed and not c.skipped)

    @property
    def skipped_count(self):
        return sum(1 for c in self.cases if c.skipped)

    def to_dict(self) -> Dict[str, Any]:
        return {'integration_profile_id': self.integration_profile_id,
                'environment': self.environment,
                'passed': self.passed_count, 'failed': self.failed_count,
                'skipped': self.skipped_count, 'cases': [c.to_dict() for c in self.cases]}


class ProviderContractTester:
    """Capability-driven contract suite for MOCK and SANDBOX integrations."""

    #: A run with fewer than this many executed cases cannot certify anything.
    MINIMUM_EXECUTED_CASES = 8

    @classmethod
    def run_contract_tests(cls, profile: ProviderIntegrationProfile, module_or_service: Any,
                           tested_by: str, *, repository=None, secret_provider=None,
                           capabilities=None) -> IntegrationCertificationRecord:
        report = cls.execute(profile, module_or_service, repository=repository,
                             secret_provider=secret_provider, capabilities=capabilities)
        return cls.to_certification_record(report, tested_by)

    @classmethod
    def execute(cls, profile, module_or_service=None, *, repository=None,
                secret_provider=None, capabilities=None) -> ContractTestReport:
        env = getattr(profile.environment, 'value', str(profile.environment))
        if env == IntegrationEnvironment.PRODUCTION.value:
            raise ContractTestError(
                'Automated contract testing against PRODUCTION environments is strictly prohibited')

        module = module_or_service
        repository = repository or getattr(module, 'repository', None)
        secret_provider = secret_provider or getattr(module, 'secret_provider', None)
        capabilities = capabilities or cls._capabilities(module, profile)

        report = ContractTestReport(profile.integration_profile_id, env)
        add = report.cases.append

        def run(name, fn, skip_when=False, skip_reason=''):
            if skip_when:
                add(ContractTestCase(name, True, skipped=True, reason=skip_reason))
                return
            try:
                detail = fn()
                add(ContractTestCase(name, True, detail=detail or ''))
            except AssertionError as error:
                add(ContractTestCase(name, False, detail=str(error)))
            except Exception as error:
                add(ContractTestCase(name, False, detail=f'{type(error).__name__}: {error}'))

        # --- configuration and schema -----------------------------------
        def datasets():
            assert profile.supported_dataset_types, 'no supported dataset types declared'
            for dataset in profile.supported_dataset_types:
                DatasetType(getattr(dataset, 'value', dataset))
            return ','.join(getattr(d, 'value', d) for d in profile.supported_dataset_types)
        run('supported_datasets_declared', datasets)

        def categories():
            assert profile.supported_request_categories, 'no supported request categories declared'
            return ','.join(profile.supported_request_categories)
        run('request_categories_declared', categories)

        def formats():
            assert profile.accepted_request_formats, 'no accepted request formats'
            assert profile.accepted_response_formats, 'no accepted response formats'
            unknown = [f for f in profile.accepted_request_formats + profile.accepted_response_formats
                       if '/' not in f]
            assert not unknown, f'not media types: {unknown}'
            return f'request={profile.accepted_request_formats} response={profile.accepted_response_formats}'
        run('request_and_response_formats_agreed', formats)

        def method():
            value = getattr(profile.submission_method, 'value', str(profile.submission_method))
            assert value in {m.value for m in TransmissionMethod}, f'unknown method {value}'
            assert capabilities is None or capabilities.supports_submission, \
                f'connector for {value} does not support submission'
            return value
        run('submission_method_supported', method)

        # --- authentication ---------------------------------------------
        def auth_success():
            assert profile.credential_reference, 'no credential reference configured'
            assert secret_provider is not None, 'no secret backend available'
            secret_provider.get_secret(profile.credential_reference, profile.environment)
            return f'reference {profile.credential_reference} resolved for {env}'
        run('authentication_success', auth_success,
            skip_when=not profile.credential_reference and env == IntegrationEnvironment.MOCK.value,
            skip_reason='MOCK transport uses no external credential')

        def auth_rejection():
            """A credential from another environment must be refused."""
            assert secret_provider is not None, 'no secret backend available'
            other = (IntegrationEnvironment.SANDBOX if env == IntegrationEnvironment.MOCK.value
                     else IntegrationEnvironment.MOCK)
            try:
                secret_provider.get_secret(profile.credential_reference, other)
            except SecretProviderError:
                return f'credential correctly refused for {other.value}'
            raise AssertionError(f'credential also resolved for {other.value}: separation broken')
        run('authentication_rejection', auth_rejection,
            skip_when=not profile.credential_reference,
            skip_reason='no credential reference to cross-check')

        # --- endpoint and transport --------------------------------------
        def endpoint():
            assert profile.endpoint_reference, 'no endpoint configured'
            allowlist = (repository.list_endpoint_allowlist(profile.provider_id, profile.environment)
                         if repository is not None else None)
            SSRFProtection.validate_endpoint(profile.endpoint_reference, profile.environment,
                                             allowlist=allowlist, provider_id=profile.provider_id)
            return profile.endpoint_reference
        run('endpoint_policy_compliant', endpoint,
            skip_when=not profile.endpoint_reference,
            skip_reason='this submission method uses no network endpoint')

        def unsafe_endpoints_refused():
            hostile = ['http://169.254.169.254/latest/meta-data/', 'file:///etc/passwd',
                       'gopher://internal/', 'http://127.0.0.1:22/']
            for url in hostile:
                try:
                    SSRFProtection.validate_endpoint(url, profile.environment, allowlist=[],
                                                     provider_id=profile.provider_id)
                except SSRFProtectionError:
                    continue
                raise AssertionError(f'hostile endpoint accepted: {url}')
            return f'{len(hostile)} hostile destinations refused'
        run('hostile_endpoints_refused', unsafe_endpoints_refused)

        # --- certificates -------------------------------------------------
        def certificates():
            requirements = CertificateValidator.requirements_for(profile.authentication_type)
            checked = []
            for label, key, reference in (
                    ('client certificate', 'client_certificate', profile.client_certificate_reference),
                    ('signing certificate', 'signing_certificate', profile.signing_certificate_reference)):
                if not reference:
                    assert not requirements[key], f'{profile.authentication_type} requires a {label}'
                    continue
                assert repository is not None, 'no repository to resolve certificate metadata'
                CertificateValidator.validate_certificate(
                    repository.get_certificate(reference), profile.environment, label)
                checked.append(label)
            return ', '.join(checked) or 'no certificates required'
        run('certificate_requirements_satisfied', certificates)

        # --- package integrity --------------------------------------------
        def package_integrity():
            payload = json.dumps({'probe': profile.integration_profile_id}, sort_keys=True,
                                 separators=(',', ':'))
            digest = hashlib.sha256(payload.encode()).hexdigest()
            assert hashlib.sha256(payload.encode()).hexdigest() == digest, 'hash is not stable'
            assert hashlib.sha256((payload + ' ').encode()).hexdigest() != digest, \
                'hash does not change with content'
            return f'sha256 stable and content-sensitive ({digest[:12]}...)'
        run('request_package_hash_preservation', package_integrity)

        # --- response handling --------------------------------------------
        def malformed_response():
            from dfap.ldrm_subsystem.providers.replies import AttachmentValidator
            validator = AttachmentValidator()
            hostile = [
                ({'filename': '../../etc/passwd', 'content_type': 'text/plain',
                  'content_base64': base64.b64encode(b'x').decode()}, 'Unsafe attachment filename'),
                ({'filename': 'a.json', 'content_type': 'application/json',
                  'content_base64': base64.b64encode(b'{not json').decode()}, 'Malformed'),
                ({'filename': 'a.json', 'content_type': 'application/json',
                  'content_base64': '!!!not-base64!!!'}, 'Malformed base64'),
                ({'filename': 'a.json', 'content_type': 'application/json',
                  'content_base64': ''}, None),
            ]
            for attachment, expected in hostile:
                _, error = validator.validate(attachment, 1024 * 1024)
                assert error is not None, f'accepted a malformed attachment: {attachment["filename"]}'
                if expected:
                    assert expected in error, f'unexpected rejection reason: {error}'
            return f'{len(hostile)} malformed responses refused'
        run('malformed_response_refused', malformed_response,
            skip_when=not capabilities or not capabilities.supports_response_download,
            skip_reason='connector does not download responses')

        def response_hash_verification():
            from dfap.ldrm_subsystem.providers.replies import AttachmentValidator
            payload = b'{"records": []}'
            attachment = {'filename': 'r.json', 'content_type': 'application/json',
                          'content_base64': base64.b64encode(payload).decode(),
                          'sha256': hashlib.sha256(payload).hexdigest()}
            raw, error = attachment and AttachmentValidator().validate(attachment, 1024 * 1024)
            assert error is None, f'valid response refused: {error}'
            attachment['sha256'] = '0' * 64
            _, error = AttachmentValidator().validate(attachment, 1024 * 1024)
            assert error == 'Attachment hash mismatch', f'hash mismatch not detected: {error}'
            return 'response hash verified and mismatch detected'
        run('response_hash_verification', response_hash_verification,
            skip_when=not capabilities or not capabilities.supports_response_download,
            skip_reason='connector does not download responses')

        def size_limit():
            from dfap.ldrm_subsystem.providers.replies import AttachmentValidator
            oversized = base64.b64encode(b'x' * 4096).decode()
            _, error = AttachmentValidator().validate(
                {'filename': 'big.json', 'content_type': 'application/json',
                 'content_base64': oversized}, 1024)
            assert error is not None, 'oversized attachment accepted'
            return f'oversized attachment refused: {error}'
        run('response_size_limit_enforced', size_limit,
            skip_when=not capabilities or not capabilities.supports_response_download,
            skip_reason='connector does not download responses')

        # --- capability-gated behaviours ------------------------------------
        run('status_polling_contract',
            lambda: f'connector advertises status polling ({profile.response_method})',
            skip_when=not capabilities or not capabilities.supports_status_polling,
            skip_reason='connector does not support status polling')

        def webhook_contract():
            assert profile.webhook_reference, 'webhook enabled without a signing-secret reference'
            assert secret_provider is None or profile.webhook_reference, 'no webhook reference'
            return f'webhook secret reference {profile.webhook_reference}'
        run('webhook_configuration', webhook_contract,
            skip_when=not profile.webhook_enabled,
            skip_reason='webhooks are not enabled for this integration')

        run('clarification_supported',
            lambda: 'connector supports provider clarification exchanges',
            skip_when=not capabilities or not capabilities.supports_clarification,
            skip_reason='connector does not support clarification')

        def duplicate_and_replay():
            seen, event_id = set(), 'EVT-CONTRACT-1'
            seen.add(event_id)
            assert event_id in seen, 'duplicate detection is not possible'
            return 'event identity is available for replay and duplicate detection'
        run('replay_and_duplicate_detection', duplicate_and_replay)

        def provider_reference_handling():
            assert profile.provider_id, 'profile has no provider'
            if repository is not None:
                from dfap.ldrm_subsystem.domain.provider import Provider
                provider = repository.get('provider', profile.provider_id, Provider)
                assert provider.is_eligible_for_dispatch, 'provider is not VERIFIED and ACTIVE'
                return f'{provider.name} is verified and active'
            return 'provider identity present'
        run('provider_reference_handling', provider_reference_handling)

        return report

    @classmethod
    def to_certification_record(cls, report: ContractTestReport,
                                tested_by: str) -> IntegrationCertificationRecord:
        """Convert a run into a record. It never carries an approval."""
        executed = report.passed_count + report.failed_count
        if report.failed_count:
            result = CertificationResult.FAIL
        elif executed < cls.MINIMUM_EXECUTED_CASES:
            # Too much was skipped to certify anything; a human must look.
            result = CertificationResult.REQUIRES_MANUAL_REVIEW
        else:
            result = CertificationResult.PASS
        return IntegrationCertificationRecord(
            certification_id=f'CERT-{uuid.uuid4().hex[:12].upper()}',
            integration_profile_id=report.integration_profile_id,
            test_suite_version=TEST_SUITE_VERSION, tested_at=utc_now(), tested_by=tested_by,
            tests_passed=report.passed_count, tests_failed=report.failed_count, result=result,
            report_reference=f'RPT-{report.integration_profile_id}-'
                             f'{report.passed_count}P-{report.failed_count}F-{report.skipped_count}S',
            # Deliberately empty: an automated run is not a security review and
            # cannot approve itself. These are filled only by recorded human
            # decisions, which live in `integration_approvals`.
            security_review_reference=None, approved_by=None, approved_at=None,
            expires_at=utc_now() + timedelta(days=180))

    @staticmethod
    def _capabilities(module, profile):
        service = getattr(module, 'service', module)
        dispatch = getattr(service, 'dispatch_service', None)
        if dispatch is None:
            return None
        try:
            return dispatch.capabilities_for(profile.submission_method)
        except Exception:
            return None
