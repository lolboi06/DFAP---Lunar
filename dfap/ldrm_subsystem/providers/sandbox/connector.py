"""The authorized sandbox connector (Stage 4).

Slots into the existing `ProviderConnector` contract, so every Stage 3 control
still applies unchanged: the package is re-verified, the authorization must be
current and signed, and the ProductionDispatchGuard has already run.

On top of that it refuses to exist for a PRODUCTION profile, refuses to act
without a live `SandboxAuthorization`, and treats an unrecognised provider
status as something a human must look at rather than a success.
"""
from typing import Any, Dict, Optional

from dfap.ldrm_subsystem.domain.enums import (
    IntegrationEnvironment, ProviderResponseStatus, TransmissionMethod, TransmissionStatus)
from dfap.ldrm_subsystem.domain.response import ProviderResponse
from dfap.ldrm_subsystem.providers.connectors.base import (
    ProviderConnector, ConnectorCapabilities, SubmissionMode, ConnectorConfigurationError)
from dfap.ldrm_subsystem.providers.sandbox.authorization import SandboxNotAuthorized
from dfap.ldrm_subsystem.providers.sandbox.mapper import (
    UnknownProviderStatus, ProviderMappingError, resolve_mapper)
from dfap.ldrm_subsystem.providers.sandbox.transport import (
    SandboxHTTPTransport, NonRetryableTransportError, RetryableTransportError)


class SandboxConnectorError(ValueError):
    pass


class ProviderStatusRequiresReview(SandboxConnectorError):
    """An unrecognised provider status. Never treated as success."""


class AuthorizedSandboxConnector(ProviderConnector):
    """Talks to one explicitly authorized, non-production provider sandbox."""

    method = TransmissionMethod.SANDBOX_API
    test_only = False

    CAPABILITIES = ConnectorCapabilities(
        submission_mode=SubmissionMode.AUTOMATIC, supports_status_polling=True,
        supports_webhooks=True, supports_response_download=True, supports_clarification=True)

    def __init__(self, repository, access, registry, authorization, *,
                 sandbox_authorizations, secret_provider, audit=None, transport_factory=None):
        super().__init__(repository, access, registry, authorization)
        self.sandbox_authorizations = sandbox_authorizations
        self.secret_provider = secret_provider
        self.audit = audit
        #: Tests substitute a transport whose httpx client is a MockTransport.
        #: It cannot relax any policy: the same authorization gate runs first.
        self._transport_factory = transport_factory

    # -------------------------------------------------------- environment

    def assert_sandbox_profile(self, profile) -> None:
        """Refuse a PRODUCTION profile outright (Stage 4 requirement)."""
        environment = getattr(profile, 'environment', None)
        env = getattr(environment, 'value', str(environment))
        if env != IntegrationEnvironment.SANDBOX.value:
            raise SandboxConnectorError(
                f'The authorized sandbox connector serves SANDBOX only and refuses a '
                f'{env} integration profile')

    def _sandbox_profile_for(self, provider_id):
        profile = self.repository.find_integration_profile(
            provider_id, IntegrationEnvironment.SANDBOX)
        if profile is None:
            raise SandboxConnectorError(
                f"No SANDBOX integration profile is configured for provider '{provider_id}'")
        self.assert_sandbox_profile(profile)
        return profile

    def transport(self, provider_id) -> SandboxHTTPTransport:
        """Build the transport, or refuse. The authorization gate is here."""
        record = self.sandbox_authorizations.require_live(provider_id)
        if self._transport_factory is not None:
            return self._transport_factory(record)
        return SandboxHTTPTransport(record, self.secret_provider, self.repository, self.audit)

    def mapper(self, provider_id):
        return resolve_mapper(self.sandbox_authorizations.require_live(provider_id).mapper_reference)

    # ------------------------------------------------------------ submission

    def _submit(self, package, transmission, provider, request):
        # Stage 3 checks already ran in ProviderConnector.submit_request.
        self._sandbox_profile_for(provider.id)
        transport, mapper = self.transport(provider.id), self.mapper(provider.id)

        body = mapper.map_request(package, request, transmission)
        # The approved package hash must survive mapping unchanged.
        if body.get('request_package_sha256') != package.sha256_hash:
            raise SandboxConnectorError(
                'Provider mapper altered the approved package hash; submission refused')

        result = transport.request('POST', mapper.submission_path(), json_body=body,
                                   request_id=request.id, transmission_id=transmission.id)
        payload = self._decode(result)

        if result.status_code >= 400:
            raise NonRetryableTransportError(
                f'Sandbox refused the submission with HTTP {result.status_code}; '
                'a provider decision is never retried automatically')

        mapped = self._map_response(mapper, payload, result, provider.id)
        transmission.provider_tracking_ref = mapped.provider_reference
        transmission.transmission_status = TransmissionStatus.DELIVERED
        transmission.metadata.update({
            'sandbox': True, 'environment': 'SANDBOX', 'test_only': False,
            'provider_reference': mapped.provider_reference,
            'sandbox_authorization_id':
                self.sandbox_authorizations.require_live(provider.id).sandbox_authorization_id,
            'submission_status': mapped.status.value,
            'response_sha256': result.body_sha256})
        self.open_channel(transmission, status=mapped.status)
        return transmission

    # ---------------------------------------------------------------- status

    def get_status(self, provider_tracking_ref):
        channel = self.repository.get('communication_channel', provider_tracking_ref)
        if channel.get('callback_received'):
            return super().get_status(provider_tracking_ref)
        provider_id = channel['provider_id']
        transport, mapper = self.transport(provider_id), self.mapper(provider_id)
        result = transport.request('GET', mapper.status_path(provider_tracking_ref),
                                   request_id=channel.get('request_id'))
        if result.status_code >= 400:
            raise NonRetryableTransportError(
                f'Sandbox status query returned HTTP {result.status_code}')
        mapped = self._map_response(mapper, self._decode(result), result, provider_id)
        return {'tracking_ref': provider_tracking_ref, 'status': mapped.status.value,
                'query_text': mapped.provider_message or None,
                'scope_affecting': mapped.scope_affecting}

    def retrieve_response(self, provider_tracking_ref):
        channel = self.repository.get('communication_channel', provider_tracking_ref)
        if channel.get('callback_received'):
            return super().retrieve_response(provider_tracking_ref)
        provider_id = channel['provider_id']
        transport, mapper = self.transport(provider_id), self.mapper(provider_id)
        result = transport.request('GET', mapper.response_path(provider_tracking_ref),
                                   request_id=channel.get('request_id'))
        if result.status_code == 404:
            return None
        if result.status_code >= 400:
            raise NonRetryableTransportError(
                f'Sandbox response retrieval returned HTTP {result.status_code}')

        mapped = self._map_response(mapper, self._decode(result), result, provider_id)
        if mapped.status not in mapper.DATA_BEARING:
            return None

        request = self.repository.get_request(channel['request_id'])
        from dfap.ldrm_subsystem.domain.transmission import RequestTransmission
        transmissions = self.repository.list('transmission', RequestTransmission,
                                             channel['request_id'])
        transmission = next((t for t in transmissions
                             if t.provider_tracking_ref == provider_tracking_ref), None)
        if transmission is None:
            raise SandboxConnectorError(
                'No transmission matches this provider reference; response refused')
        return mapper.build_provider_response(mapped, request=request, transmission=transmission)

    # ------------------------------------------------------------- internals

    def _decode(self, result) -> Dict[str, Any]:
        import json
        if not result.body:
            raise ProviderMappingError('Sandbox returned an empty body')
        try:
            payload = json.loads(result.body.decode('utf-8'))
        except (UnicodeDecodeError, ValueError) as error:
            raise ProviderMappingError(
                'Sandbox returned a body that is not valid UTF-8 JSON') from error
        if not isinstance(payload, dict):
            raise ProviderMappingError('Sandbox response envelope must be a JSON object')
        return payload

    def _map_response(self, mapper, payload, result, provider_id):
        """Map, turning an unknown status into a reviewable refusal."""
        try:
            return mapper.map_response(payload, result.body)
        except UnknownProviderStatus as error:
            if self.audit is not None:
                self.audit.log_event(
                    'SANDBOX_UNKNOWN_PROVIDER_STATUS', 'Provider', provider_id, 'system',
                    {'raw_status': str(error.raw_status), 'known': error.known,
                     'response_sha256': result.body_sha256,
                     'action': 'held for human review; not treated as success'})
            raise ProviderStatusRequiresReview(str(error)) from error

    def validate_configuration(self, provider) -> bool:
        super().validate_configuration(provider)
        self._sandbox_profile_for(provider.id)
        self.sandbox_authorizations.require_live(provider.id)
        return True

    def destination(self, provider):
        """The destination is the authorized base URL, not a registry address."""
        from dfap.ldrm_subsystem.domain.provider import ProviderDestination
        from dfap.ldrm_subsystem.domain.utils import utc_now
        record = self.sandbox_authorizations.require_live(provider.id)
        return ProviderDestination(id=record.sandbox_authorization_id, method=self.method,
                                   address=record.base_url, verified_by=record.authorized_by,
                                   verified_at=record.authorized_at)

    def health_check(self) -> Dict[str, Any]:
        base = super().health_check()
        base['environment'] = 'SANDBOX'
        base['refuses_production'] = True
        return base
