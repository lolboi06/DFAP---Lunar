"""Dispatch only immutable, currently authorized packages through the mock adapter."""
from dfap.ldrm_subsystem.domain.enums import RequestStatus, TransmissionMethod, TransmissionStatus
from dfap.ldrm_subsystem.domain.utils import utc_now
from dfap.ldrm_subsystem.persistence.repositories import encode
import hashlib
from dfap.ldrm_subsystem.domain.transmission import RequestTransmission
from dfap.ldrm_subsystem.policy.state_machine import RequestStateMachine, transition
from dfap.ldrm_subsystem.providers.mock_adapter import MockProviderAdapter


class DispatchServiceError(ValueError):
    pass


class DispatchService:
    def __init__(self, access, repository, registry, provider, authorization, audit,
                 config=None, secret_provider=None, sandbox_authorizations=None):
        self.access, self.repository, self.registry = access, repository, registry
        self.provider, self.authorization, self.audit = provider, authorization, audit
        from dfap.ldrm_subsystem.config import LDRMConfig
        from dfap.ldrm_subsystem.security.secrets import DevelopmentSecretProvider
        self.config = config or LDRMConfig()
        self.secret_provider = secret_provider or DevelopmentSecretProvider()
        from dfap.ldrm_subsystem.providers.connectors.registry import ConnectorRegistry
        self.sandbox_authorizations = sandbox_authorizations
        self.connectors = ConnectorRegistry(repository, access, registry, authorization,
                                            sandbox_authorizations=sandbox_authorizations,
                                            secret_provider=self.secret_provider, audit=audit)
        if type(provider) is not MockProviderAdapter:
            raise ValueError('Only MockProviderAdapter is supported')

    def capabilities_for(self, transmission_method):
        """Connector capabilities drive business logic; class names never do."""
        if transmission_method in {TransmissionMethod.MOCK_DISPATCH, TransmissionMethod.MOCK}:
            from dfap.ldrm_subsystem.providers.connectors.base import ConnectorCapabilities
            return ConnectorCapabilities(supports_status_polling=True, supports_response_download=True)
        return self.connectors.get(transmission_method).capabilities

    def integration_profile_for(self, provider, transmission_method):
        """Resolve the persisted profile, or synthesise the MOCK default.

        Only the MOCK environment has an implied profile, and it is pinned to
        MOCK with a mock submission method, so it can never satisfy any
        production check. Every other environment must be configured explicitly.
        """
        from dfap.ldrm_subsystem.domain.profile import ProviderIntegrationProfile
        from dfap.ldrm_subsystem.domain.enums import IntegrationEnvironment, ProviderIntegrationStatus
        environment = self.environment_for(provider)
        profile = self.repository.find_integration_profile(provider.id, environment)
        if profile is not None:
            return profile
        if environment != IntegrationEnvironment.MOCK:
            raise DispatchServiceError(
                f"No {environment.value} integration profile is configured for provider "
                f"'{provider.id}'; dispatch fails closed")
        return ProviderIntegrationProfile(
            integration_profile_id=f'IPROF-IMPLICIT-MOCK-{provider.id}',
            provider_id=provider.id, environment=IntegrationEnvironment.MOCK,
            submission_method=transmission_method,
            supported_dataset_types=list(provider.supported_datasets),
            supported_request_categories=['ALL_MOCK'],
            integration_status=ProviderIntegrationStatus.SANDBOX_CONFIGURED,
            endpoint_reference='', credential_reference='')

    def environment_for(self, provider):
        """The environment a provider operates in. Never inferred from a hostname.

        Resolved only from persisted profiles. Demonstration mode does NOT
        silently downgrade a PRODUCTION provider to MOCK: a request authorized
        against a production integration must be refused by the guard, not
        quietly redirected to a synthetic provider.
        """
        from dfap.ldrm_subsystem.domain.enums import IntegrationEnvironment
        profiles = self.repository.list_integration_profiles(provider.id)
        for environment in (IntegrationEnvironment.PRODUCTION, IntegrationEnvironment.SANDBOX):
            if any(p.environment == environment for p in profiles):
                return environment
        return IntegrationEnvironment.MOCK

    def _certificates_for(self, profile):
        certificates = {}
        for reference in (profile.client_certificate_reference, profile.signing_certificate_reference):
            if not reference:
                continue
            try:
                certificates[reference] = self.repository.get_certificate(reference)
            except KeyError:
                continue
        return certificates

    def prepare_for_dispatch(self, request, actor_id):
        self.access.require(actor_id, 'DISPATCH_REQUEST', request)
        self.authorization.validate_current(request, signed=True)
        self.registry.validate_provider_for_dispatch(request.provider_id, request.dataset_type)
        transition(request, RequestStatus.READY_TO_SEND, actor_id, self.audit)
        return request

    def dispatch(self, request, dispatched_by, transmission_method=None):
        self.access.require(dispatched_by, 'DISPATCH_REQUEST', request)
        package = self.authorization.validate_current(request, signed=True)
        provider = self.registry.validate_provider_for_dispatch(request.provider_id, request.dataset_type)
        transmission_method = transmission_method or provider.submission_methods[0]

        # An already-recorded transmission is an idempotent replay, not a second
        # dispatch: it returns the stored record and transmits nothing. The
        # authorization and package hash were revalidated above.
        existing = self.repository.list('transmission', RequestTransmission, request.id)
        if existing:
            if request.status in {RequestStatus.REJECTED, RequestStatus.CANCELLED,
                                  RequestStatus.EXPIRED, RequestStatus.CLOSED}:
                # A provider's refusal is a decision, not a transport failure.
                # Re-sending would be a second attempt at compelled disclosure.
                raise DispatchServiceError(
                    f'Request is {request.status.value}; a provider decision is never retried. '
                    'Raise a new request if the scope still needs to be sought.')
            if (existing[-1].package_payload_hash != package.sha256_hash
                    or existing[-1].transmission_method != transmission_method):
                raise DispatchServiceError('Transmission package mismatch')
            return existing[-1]

        # Stage 3: one centralized, fail-closed guard. It resolves the persisted
        # integration profile for this provider and environment; a missing
        # profile is a refusal, never an implied permission.
        from dfap.ldrm_subsystem.policy.dispatch_guard import (
            ProductionDispatchGuard, DispatchGuardContext, DispatchGuardValidationError)

        profile = self.integration_profile_for(provider, transmission_method)
        context = DispatchGuardContext(
            config=self.config, actor_id=dispatched_by, access=self.access, provider=provider,
            secret_provider=self.secret_provider,
            certificates=self._certificates_for(profile),
            allowlist=self.repository.list_endpoint_allowlist(provider.id, profile.environment),
            connector_capabilities=self.capabilities_for(transmission_method),
            audit=self.audit, expected_canonical_hash=package.sha256_hash,
            transmission_method=transmission_method)
        try:
            ProductionDispatchGuard.validate(request, profile, context)
        except DispatchGuardValidationError as err:
            event = ('DISPATCH_BLOCKED', 'LawfulDataRequest', request.id, dispatched_by,
                     {'reason': str(err), 'failed_checks': err.failures, 'provider_id': provider.id,
                      'environment': getattr(profile.environment, 'value', profile.environment),
                      'integration_profile_id': profile.integration_profile_id,
                      'integration_status': getattr(profile.integration_status, 'value',
                                                    profile.integration_status)})
            error = DispatchServiceError(f'Dispatch blocked by security guard: {err}')
            # Recording it here would be undone by the surrounding rollback. The
            # unit of work writes it after the transaction unwinds; if this call
            # is not inside one, write it now.
            if self.repository.depth == 0:
                self.audit.log_event(*event)
                error.audit_recorded = True
            error.audit_event = event
            raise error from err
        self.audit.log_event('DISPATCH_ATTEMPTED', 'LawfulDataRequest', request.id, dispatched_by,
                             {'provider_id': provider.id, 'method': transmission_method.value,
                              'integration_profile_id': profile.integration_profile_id,
                              'environment': getattr(profile.environment, 'value', profile.environment)})

        if transmission_method not in provider.submission_methods:
            raise DispatchServiceError('Submission method is not configured for this provider')
        if request.status == RequestStatus.SIGNED:
            self.prepare_for_dispatch(request, dispatched_by)
        RequestStateMachine.validate_transition(request.status, RequestStatus.SENT)
        transmission = RequestTransmission(request_id=request.id, provider_id=request.provider_id,
            case_id=request.case_id, authorization_id=request.authorization.id, request_version=request.request_version,
            dispatched_by=dispatched_by, package_payload_hash=package.sha256_hash, transmission_method=transmission_method)
        if transmission_method in {TransmissionMethod.MOCK_DISPATCH, TransmissionMethod.MOCK}:
            transmission = self.provider.dispatch(transmission, package.canonical_dict)
        else:
            connector = self.connectors.get(transmission_method)
            preparation_id = f'{request.id}:{request.request_version}:{transmission_method.value}'
            if connector.capabilities.is_manual:
                try:
                    prepared = self.repository.get('submission_preparation', preparation_id, RequestTransmission)
                except KeyError:
                    prepared = None
                if prepared:
                    if prepared.metadata['provider_configuration_hash'] != self.configuration_hash(provider):
                        raise DispatchServiceError('Provider configuration changed; reauthorize a new request version')
                    return prepared
            transmission = connector.submit_request(package, transmission, provider, request)
            if transmission.transmission_status in {TransmissionStatus.READY_FOR_MANUAL_SUBMISSION, TransmissionStatus.READY_FOR_PHYSICAL_SUBMISSION}:
                transmission.metadata['provider_configuration_hash'] = self.configuration_hash(provider)
                self.repository.put('submission_preparation', preparation_id, transmission, request.id, immutable=True)
                self.audit.log_event('SUBMISSION_PREPARED', 'LawfulDataRequest', request.id, dispatched_by,
                                     {'method': transmission_method.value, 'preparation_id': preparation_id, 'automatic_submission': False})
                return transmission
        self.repository.put('transmission', transmission.id, transmission, request.id, immutable=True)
        transition(request, RequestStatus.SENT, dispatched_by, self.audit)
        if transmission.acknowledgment_timestamp:
            transition(request, RequestStatus.ACKNOWLEDGED, dispatched_by, self.audit)
        self.audit.log_event('REQUEST_DISPATCHED', 'LawfulDataRequest', request.id, dispatched_by,
                             {'transmission_id': transmission.id, 'authorization_id': transmission.authorization_id,
                              'hash': package.sha256_hash, 'version': package.request_version,
                              'method': transmission_method.value, 'test_only': True})
        return transmission


    @staticmethod
    def configuration_hash(provider):
        return hashlib.sha256(encode(provider).encode()).hexdigest()

    def provider_for(self, transmission):
        if transmission.transmission_method in {TransmissionMethod.MOCK_DISPATCH, TransmissionMethod.MOCK}:
            return self.provider
        return self.connectors.get(transmission.transmission_method)

    def record_submission(self, request, actor_id, *, method, submitted_at, provider_reference,
                          receipt_reference, notes, physical_method=None, provider_acknowledgement=False):
        user = self.access.require(actor_id, 'DISPATCH_REQUEST', request)
        if not user.is_human:
            raise PermissionError('Submission must be recorded by an authenticated human')
        package = self.authorization.validate_current(request, signed=True)
        provider = self.registry.validate_provider_for_dispatch(request.provider_id, request.dataset_type)
        capabilities = self.capabilities_for(method)
        if not capabilities.requires_recorded_human_submission or method not in provider.submission_methods:
            raise ValueError('A configured manual submission method is required')
        preparation = self.repository.get('submission_preparation', f'{request.id}:{request.request_version}:{method.value}', RequestTransmission)
        if preparation.metadata['provider_configuration_hash'] != self.configuration_hash(provider) or preparation.package_payload_hash != package.sha256_hash:
            raise ValueError('Prepared package or provider configuration changed')
        if (not submitted_at.tzinfo or submitted_at > utc_now() or submitted_at < request.authorization.authorized_at
                or not provider_reference.strip() or not receipt_reference.strip() or not notes.strip()):
            raise ValueError('A valid submitted_at, provider reference, receipt and notes are required')
        if method == TransmissionMethod.PHYSICAL_SUBMISSION and physical_method not in {'REGISTERED_POST', 'COURIER', 'IN_PERSON', 'OFFLINE_MEDIA'}:
            raise ValueError('A supported physical submission method is required')
        record = {'submitted_at': submitted_at.isoformat(), 'submitted_by': actor_id, 'provider_reference': provider_reference,
                  'receipt_reference': receipt_reference, 'notes': notes, 'physical_method': physical_method,
                  'provider_acknowledgement': provider_acknowledgement}
        existing = self.repository.list('transmission', RequestTransmission, request.id)
        if existing:
            if existing[-1].metadata.get('human_submission') != record:
                raise ValueError('Recorded submission cannot be overwritten')
            return existing[-1]
        RequestStateMachine.validate_transition(request.status, RequestStatus.SENT)
        preparation.dispatched_by, preparation.dispatch_timestamp = actor_id, submitted_at
        preparation.provider_tracking_ref = f'{method.value}:{provider.id}:{provider_reference}'
        preparation.transmission_status = TransmissionStatus.DELIVERED
        preparation.metadata['human_submission'] = record
        if provider_acknowledgement:
            preparation.acknowledge(preparation.provider_tracking_ref)
        # References must uniquely identify a transmission, not just a provider.
        try:
            self.repository.get('communication_channel', preparation.provider_tracking_ref)
        except KeyError:
            pass
        else:
            raise ValueError('Provider reference is already associated with another transmission')
        self.provider_for(preparation).open_channel(preparation)
        self.repository.put('transmission', preparation.id, preparation, request.id, immutable=True)
        transition(request, RequestStatus.SENT, actor_id, self.audit)
        if provider_acknowledgement:
            transition(request, RequestStatus.ACKNOWLEDGED, actor_id, self.audit)
        self.audit.log_event('HUMAN_SUBMISSION_RECORDED', 'LawfulDataRequest', request.id, actor_id,
                             {'transmission_id': preparation.id, **record, 'test_only': True})
        return preparation
