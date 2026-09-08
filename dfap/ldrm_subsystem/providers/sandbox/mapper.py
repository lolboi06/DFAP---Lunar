"""Provider-specific translation, kept outside the LDRM core (Stage 4).

    LDRM Canonical Request  ->  ProviderMapper  ->  Sandbox API
    Sandbox API response    ->  ProviderMapper  ->  LDRM ProviderResponse

The LDRM core knows nothing about any provider's field names, envelope shape or
status vocabulary. Adding a provider means writing a mapper and registering it;
it never means editing the request, dispatch or response services.

The status vocabulary is the load-bearing part. A status the mapper does not
recognise is **not** success and **not** a silent failure: it raises
`UnknownProviderStatus`, which the connector turns into a reviewable state.
"""
import hashlib
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from dfap.ldrm_subsystem.domain.enums import ProviderResponseStatus
from dfap.ldrm_subsystem.domain.response import ProviderResponse


class ProviderMappingError(ValueError):
    """The provider's payload could not be understood."""


class UnknownProviderStatus(ProviderMappingError):
    """A status outside the agreed vocabulary. Requires human review, never success."""

    def __init__(self, raw_status, known):
        self.raw_status = raw_status
        self.known = sorted(known)
        super().__init__(
            f"Provider returned status '{raw_status}', which is not in the agreed vocabulary "
            f"({', '.join(self.known)}). This requires review; it is not treated as success.")


@dataclass
class MappedResponse:
    """What a mapper extracts from a provider payload."""
    status: ProviderResponseStatus
    provider_reference: str
    #: Raw bytes exactly as received. Never re-serialised before hashing.
    raw_payload: bytes = b''
    #: Provider's own message, e.g. a clarification question or rejection reason.
    provider_message: str = ''
    #: True when the provider's message changes what is being asked for.
    scope_affecting: bool = False
    safe_metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def payload_sha256(self) -> str:
        return hashlib.sha256(self.raw_payload).hexdigest()


class ProviderMapper(ABC):
    """One provider's request and response translation."""

    #: Registered name, referenced by a SandboxAuthorization.
    reference: str = ''

    #: The provider's status vocabulary, mapped to LDRM's. Every value the
    #: provider may return must appear here or the exchange requires review.
    STATUS_VOCABULARY: Dict[str, ProviderResponseStatus] = {}

    #: Statuses that carry a dataset payload.
    DATA_BEARING = {ProviderResponseStatus.COMPLETED, ProviderResponseStatus.PARTIAL_RESPONSE}

    @abstractmethod
    def submission_path(self) -> str:
        """Path, relative to the authorized base URL, that accepts a request."""

    @abstractmethod
    def status_path(self, provider_reference: str) -> str:
        """Path that reports the status of a previously submitted request."""

    @abstractmethod
    def response_path(self, provider_reference: str) -> str:
        """Path that returns the provider's response payload."""

    @abstractmethod
    def map_request(self, package, request, transmission) -> Dict[str, Any]:
        """Canonical authorized package -> the provider's submission body.

        Must carry the package hash so the provider can verify integrity, and
        must not invent, widen or restate scope beyond the approved package.
        """

    @abstractmethod
    def map_response(self, payload: Dict[str, Any], raw_body: bytes) -> MappedResponse:
        """Provider payload -> a MappedResponse. Raises on anything unrecognised."""

    # ------------------------------------------------------------- shared

    def map_status(self, raw_status: Any) -> ProviderResponseStatus:
        """Translate one provider status. Unknown is a refusal, not a default."""
        if raw_status is None:
            raise UnknownProviderStatus('<missing>', self.STATUS_VOCABULARY)
        key = str(raw_status).strip().upper()
        if key not in self.STATUS_VOCABULARY:
            raise UnknownProviderStatus(raw_status, self.STATUS_VOCABULARY)
        return self.STATUS_VOCABULARY[key]

    def build_provider_response(self, mapped: MappedResponse, *, request, transmission) -> ProviderResponse:
        """Assemble the LDRM domain object. Provenance is taken from our own
        records, never from the provider's payload."""
        return ProviderResponse(
            id=f'sandbox-{transmission.id}-{mapped.payload_sha256[:12]}',
            request_id=request.id, provider_id=request.provider_id, case_id=request.case_id,
            transmission_id=transmission.id, provider_status=mapped.status,
            raw_payload=mapped.raw_payload, raw_payload_hash=mapped.payload_sha256,
            metadata={'tracking_ref': transmission.provider_tracking_ref,
                      'provider_reference': mapped.provider_reference,
                      'sandbox': True, 'environment': 'SANDBOX',
                      **mapped.safe_metadata})


class PassThroughSandboxMapper(ProviderMapper):
    """Reference mapper for a JSON sandbox that speaks the canonical vocabulary.

    This exists so the architecture is complete and testable end to end without
    a real provider. It is **not** a guess at any particular institution's API:
    a real integration ships its own mapper written against that provider's
    published sandbox specification, registered under its own reference.
    """

    reference = 'passthrough-json-v1'

    STATUS_VOCABULARY = {
        'RECEIVED': ProviderResponseStatus.ACCEPTED,
        'ACKNOWLEDGED': ProviderResponseStatus.ACCEPTED,
        'ACCEPTED': ProviderResponseStatus.ACCEPTED,
        'PROCESSING': ProviderResponseStatus.PROCESSING,
        'IN_PROGRESS': ProviderResponseStatus.PROCESSING,
        'PROVIDER_QUERY': ProviderResponseStatus.PROVIDER_QUERY,
        'CLARIFICATION_REQUIRED': ProviderResponseStatus.PROVIDER_QUERY,
        'REJECTED': ProviderResponseStatus.REJECTED,
        'REFUSED': ProviderResponseStatus.REJECTED,
        'PARTIAL': ProviderResponseStatus.PARTIAL_RESPONSE,
        'PARTIAL_RESPONSE': ProviderResponseStatus.PARTIAL_RESPONSE,
        'COMPLETED': ProviderResponseStatus.COMPLETED,
        'COMPLETE': ProviderResponseStatus.COMPLETED,
    }

    def submission_path(self) -> str:
        return '/lawful-requests'

    def status_path(self, provider_reference: str) -> str:
        return f'/lawful-requests/{provider_reference}'

    def response_path(self, provider_reference: str) -> str:
        return f'/lawful-requests/{provider_reference}/response'

    def map_request(self, package, request, transmission) -> Dict[str, Any]:
        # The approved canonical package is sent verbatim alongside its hash and
        # the recorded authority. Nothing is added to scope here.
        authorization = request.authorization
        return {
            'agency_request_reference': request.request_number,
            'agency_case_reference': request.case_id,
            'transmission_id': transmission.id,
            'dataset_type': getattr(request.dataset_type, 'value', str(request.dataset_type)),
            'request_package': package.canonical_json,
            'request_package_sha256': package.sha256_hash,
            'request_version': package.request_version,
            'authority': {
                'type': getattr(authorization.authority_type, 'value', str(authorization.authority_type)),
                'reference': authorization.authority_reference,
                'issuing_authority': authorization.issuing_authority,
                'bound_package_sha256': authorization.bound_canonical_hash,
            },
            'signature': {
                'algorithm': authorization.signature_algorithm,
                'value': authorization.digital_signature,
                'signer_reference': authorization.signer_id,
            },
        }

    def map_response(self, payload: Dict[str, Any], raw_body: bytes) -> MappedResponse:
        if not isinstance(payload, dict):
            raise ProviderMappingError('Sandbox response envelope must be a JSON object')

        provider_reference = payload.get('provider_reference') or payload.get('reference')
        if not provider_reference or not isinstance(provider_reference, str):
            raise ProviderMappingError('Sandbox response is missing a provider reference')
        if len(provider_reference) > 200 or any(ord(c) < 32 for c in provider_reference):
            raise ProviderMappingError('Sandbox provider reference is malformed')

        status = self.map_status(payload.get('status'))

        message = payload.get('message') or payload.get('query_text') or payload.get('reason') or ''
        if not isinstance(message, str) or len(message) > 10_000:
            raise ProviderMappingError('Sandbox response message is malformed')

        # A clarification that alters what is being asked for must be flagged so
        # the caller can invalidate the authorization rather than proceed.
        scope_affecting = bool(payload.get('scope_change_requested')) or (
            status == ProviderResponseStatus.PROVIDER_QUERY
            and bool(payload.get('requires_scope_amendment')))

        # Only a data-bearing status may carry a dataset; the dataset is the
        # raw bytes as received, never a re-serialisation.
        data = b''
        if status in self.DATA_BEARING:
            if 'dataset' not in payload:
                raise ProviderMappingError(
                    f'Sandbox reported {status.value} but returned no dataset')
            data = raw_body
        elif 'dataset' in payload:
            raise ProviderMappingError(
                f'Sandbox returned a dataset alongside a non-data status ({status.value})')

        return MappedResponse(
            status=status, provider_reference=provider_reference, raw_payload=data,
            provider_message=message, scope_affecting=scope_affecting,
            safe_metadata={'provider_status_raw': str(payload.get('status')),
                           'record_count_declared': payload.get('record_count'),
                           'partial': status == ProviderResponseStatus.PARTIAL_RESPONSE})


#: Mappers a SandboxAuthorization may reference. A real integration registers its
#: own here; there is deliberately no dynamic import by name from a stored value.
MAPPER_REGISTRY: Dict[str, ProviderMapper] = {
    PassThroughSandboxMapper.reference: PassThroughSandboxMapper(),
}


def resolve_mapper(reference: str) -> ProviderMapper:
    try:
        return MAPPER_REGISTRY[reference]
    except KeyError as error:
        raise ProviderMappingError(
            f"No mapper is registered under '{reference}'. A provider integration must ship a "
            'reviewed mapper; mappers are never loaded dynamically from stored configuration.'
        ) from error
