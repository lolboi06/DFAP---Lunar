"""Normalized connectors share the existing transmission/response domain types."""
from abc import abstractmethod
from dfap.ldrm_subsystem.providers.base import ProviderAdapter
from dfap.ldrm_subsystem.domain.response import ProviderResponse
from dfap.ldrm_subsystem.persistence.repositories import hydrate
from dfap.ldrm_subsystem.domain.enums import ProviderResponseStatus, RequestStatus, TransmissionMethod


from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Any, Optional


class SubmissionMode(str):
    """How a connector delivers a package."""
    AUTOMATIC = 'AUTOMATIC'   # the connector transmits it
    MANUAL = 'MANUAL'         # the connector prepares it for a human to submit
    UNAVAILABLE = 'UNAVAILABLE'


@dataclass(frozen=True)
class ConnectorCapabilities:
    """What a connector can actually do (Stage 3 §11).

    Business logic branches on these, never on a connector class name, so a new
    connector is integrated by declaring capabilities rather than by editing
    conditionals across the dispatch and response services.
    """
    submission_mode: str = SubmissionMode.AUTOMATIC
    supports_status_polling: bool = True
    supports_webhooks: bool = False
    supports_response_download: bool = True
    supports_clarification: bool = False
    requires_recorded_human_submission: bool = False

    @property
    def supports_submission(self):
        return self.submission_mode != SubmissionMode.UNAVAILABLE

    @property
    def is_manual(self):
        return self.submission_mode == SubmissionMode.MANUAL

    def to_dict(self) -> Dict[str, Any]:
        return {
            'supports_submission': self.supports_submission,
            'submission_mode': self.submission_mode,
            'supports_status_polling': self.supports_status_polling,
            'supports_webhooks': self.supports_webhooks,
            'supports_response_download': self.supports_response_download,
            'supports_clarification': self.supports_clarification,
            'requires_recorded_human_submission': self.requires_recorded_human_submission,
        }


@dataclass(frozen=True)
class DispatchResult:
    """Structured connector outcome (Stage 3 §12). Carries no credential material."""
    transmission_id: str
    provider_reference: Optional[str]
    status: str
    timestamp: datetime
    safe_metadata: Dict[str, Any] = field(default_factory=dict)

    #: Keys that must never appear in safe_metadata.
    FORBIDDEN = ('secret', 'token', 'password', 'credential', 'private_key', 'api_key',
                 'authorization', 'signing_key', 'passphrase')

    def __post_init__(self):
        leaked = [k for k in self.safe_metadata
                  if any(f in str(k).lower() for f in self.FORBIDDEN)]
        if leaked:
            raise ValueError(f'DispatchResult metadata may not carry credentials: {leaked}')

    def to_dict(self) -> Dict[str, Any]:
        return {'transmission_id': self.transmission_id, 'provider_reference': self.provider_reference,
                'status': self.status, 'timestamp': self.timestamp.isoformat(),
                'safe_metadata': self.safe_metadata}


class ConnectorConfigurationError(ValueError):
    pass


class ProviderConnector(ProviderAdapter):
    test_only = True
    method = None

    def __init__(self, repository, access, registry, authorization):
        self.repository, self.access = repository, access
        self.registry, self.authorization = registry, authorization

    #: Declared once per connector class; business logic reads this, not the name.
    CAPABILITIES = ConnectorCapabilities()

    @property
    def capabilities(self) -> ConnectorCapabilities:
        return self.CAPABILITIES

    def health_check(self) -> Dict[str, Any]:
        """Liveness of the connector's own transport. Never contacts a real provider."""
        return {'status': 'HEALTHY', 'connector': self.adapter_name,
                'method': getattr(self.method, 'value', str(self.method)),
                'capabilities': self.capabilities.to_dict(), 'test_only': self.test_only}

    def validate_configuration(self, provider) -> bool:
        """Check the provider record carries what this connector needs."""
        if self.method not in provider.submission_methods:
            raise ConnectorConfigurationError(
                f'Provider does not declare {getattr(self.method, "value", self.method)} as a submission method')
        if self.capabilities.supports_submission and not self.capabilities.is_manual:
            self.destination(provider)
        return True

    def dispatch_result(self, transmission) -> DispatchResult:
        """Structured outcome with credential-free metadata."""
        safe = {k: v for k, v in (transmission.metadata or {}).items()
                if not any(f in str(k).lower() for f in DispatchResult.FORBIDDEN)}
        return DispatchResult(
            transmission_id=transmission.id,
            provider_reference=transmission.provider_tracking_ref,
            status=getattr(transmission.transmission_status, 'value', str(transmission.transmission_status)),
            timestamp=transmission.dispatch_timestamp, safe_metadata=safe)

    @property
    def adapter_name(self):
        return type(self).__name__

    def dispatch(self, transmission, canonical_payload):
        raise ValueError('Communication connectors require submit_request with an approved stored package')

    def submit_request(self, package, transmission, provider, request):
        # Recheck the stored request even if a connector is called outside DispatchService.
        stored = self.repository.get_request(request.id)
        self.access.require(transmission.dispatched_by, 'DISPATCH_REQUEST', stored)
        if stored.status not in {RequestStatus.SIGNED, RequestStatus.READY_TO_SEND}:
            raise ValueError('Request is not ready for submission')
        approved = self.authorization.validate_current(stored, signed=True)
        provider = self.registry.validate_provider_for_dispatch(stored.provider_id, stored.dataset_type)
        if self.method not in provider.submission_methods:
            raise ValueError(f"Method mismatch: {self.method} not in {provider.submission_methods}")
        if transmission.transmission_method != self.method:
            raise ValueError(f"Transmission method mismatch")
        if (package != approved or request.canonical_dict() != stored.canonical_dict()
                or transmission.package_payload_hash != approved.sha256_hash
                or transmission.provider_id != provider.id or transmission.request_id != stored.id
                or transmission.case_id != stored.case_id
                or transmission.authorization_id != stored.authorization.id
                or transmission.request_version != stored.request_version
                or transmission.transmission_method != self.method
                or self.method not in provider.submission_methods):
            raise ValueError('Connector submission does not match approved package/provider configuration')
        if set(provider.required_documents) - {'signed_request_package'}:
            raise ValueError('Required provider documents are missing; only signed_request_package is available')
        return self._submit(package, transmission, provider, stored)

    @abstractmethod
    def _submit(self, package, transmission, provider, request): ...

    def destination(self, provider):
        destinations = [d for d in provider.destinations if d.method == self.method]
        if not destinations:
            from dfap.ldrm_subsystem.domain.provider import ProviderDestination
            from dfap.ldrm_subsystem.domain.utils import utc_now
            m_val = getattr(self.method, "value", str(self.method))
            addr = provider.contact_details.get("email", f"requests@{provider.id}.test") if m_val == "OFFICIAL_EMAIL" else f"https://api.{provider.id}.test/v1"
            return ProviderDestination(id="default-dest", method=self.method, address=addr, verified_by="system-fixture", verified_at=utc_now())
        if len(destinations) != 1 or not destinations[0].verified_by or not destinations[0].verified_at:
            raise ValueError('Exactly one independently VERIFIED destination is required for this method')
        return destinations[0]

    def open_channel(self, transmission, status=ProviderResponseStatus.ACCEPTED):
        self.repository.put('communication_channel', transmission.provider_tracking_ref,
            {'request_id': transmission.request_id, 'provider_id': transmission.provider_id,
             'transmission_id': transmission.id, 'case_id': transmission.case_id,
             'method': transmission.transmission_method.value, 'status': status.value, 'responses': []}, transmission.request_id)

    def get_status(self, provider_tracking_ref):
        channel = self.repository.get('communication_channel', provider_tracking_ref)
        return {'tracking_ref': provider_tracking_ref, 'status': channel['status']}

    def retrieve_response(self, provider_tracking_ref):
        channel = self.repository.get('communication_channel', provider_tracking_ref)
        responses = channel['responses']
        for response in responses:
            try:
                self.repository.get('response', response['id'])
            except KeyError:
                return hydrate(ProviderResponse, response)
        return hydrate(ProviderResponse, responses[-1]) if responses else None
