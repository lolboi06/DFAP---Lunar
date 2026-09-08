"""Official-request API architecture, using an in-process local ASGI server only."""
from abc import ABC, abstractmethod
import asyncio
import hashlib
import hmac
import json
import secrets
from fastapi import FastAPI, Request, HTTPException
import httpx
from dfap.ldrm_subsystem.domain.enums import TransmissionMethod, TransmissionStatus, ProviderResponseStatus
from dfap.ldrm_subsystem.domain.response import ProviderResponse
from dfap.ldrm_subsystem.persistence.repositories import encode, hydrate
from dfap.ldrm_subsystem.providers.connectors.base import (
    ProviderConnector, ConnectorCapabilities, SubmissionMode)


class APIAuthentication(ABC):
    @abstractmethod
    def headers(self): ...


class LocalTokenAuthentication(APIAuthentication):
    def __init__(self, token):
        self.token = token

    def headers(self):
        return {'Authorization': 'Bearer ' + self.token}


class APITransport(ABC):
    @abstractmethod
    def request(self, method, path, *, payload=None, headers=None): ...


class LocalMockProviderServer:
    """Accepts authorized request packages; contains no customer query endpoint."""
    def __init__(self, repository, token):
        self.repository, self.token = repository, token
        self.app = FastAPI(title='Local Mock Provider Request API')

        def authenticate(request):
            if not hmac.compare_digest(request.headers.get('authorization', ''), 'Bearer ' + token):
                raise HTTPException(401, 'Invalid local provider credential')

        @self.app.post('/requests')
        async def submit(request: Request):
            authenticate(request)
            payload = await request.json()
            package = payload['package']
            if (hashlib.sha256(package.encode()).hexdigest() != payload['package_hash']
                    or not payload.get('signature') or payload.get('authorization_hash') != payload['package_hash']):
                raise HTTPException(400, 'An approved signed request package is required')
            reference = 'LOCAL-API-' + payload['transmission_id']
            try:
                stored = repository.get('local_provider_api', reference)
            except KeyError:
                stored = None
            if stored and stored['submission'] != payload:
                raise HTTPException(409, 'Idempotency conflict')
            if not stored:
                repository.put('local_provider_api', reference, {'submission': payload, 'status': 'ACCEPTED'}, payload['request_id'])
            return {'provider_reference': reference, 'status': stored['status'] if stored else 'ACCEPTED'}

        @self.app.get('/requests/{reference}')
        async def status(reference: str, request: Request):
            authenticate(request)
            state = repository.get('local_provider_api', reference)
            return {'tracking_ref': reference, 'status': state['status']}

        @self.app.get('/requests/{reference}/response')
        async def response(reference: str, request: Request):
            authenticate(request)
            state = repository.get('local_provider_api', reference)
            if state['status'] not in {'COMPLETED', 'PARTIAL_RESPONSE'}:
                return None
            if 'response' not in state:
                submission = state['submission']
                scope = json.loads(submission['package'])
                raw = encode({'dataset_type': scope['dataset_type'], 'records': [], 'test_only': True}).encode()
                result = ProviderResponse(id='api-response-' + submission['transmission_id'] + '-' + state['status'],
                    request_id=submission['request_id'], provider_id=submission['provider_id'], case_id=scope['case_id'],
                    transmission_id=submission['transmission_id'], raw_payload=raw, raw_payload_hash=hashlib.sha256(raw).hexdigest(),
                    provider_status=ProviderResponseStatus(state['status']), metadata={'tracking_ref': reference, 'test_only': True})
                state['response'] = json.loads(encode(result))
                repository.put('local_provider_api', reference, state, submission['request_id'])
            return state['response']

    def configure_status(self, reference, status):
        with self.repository.transaction():
            state = self.repository.get('local_provider_api', reference)
            state['status'] = ProviderResponseStatus(status).value
            state.pop('response', None)
            self.repository.put('local_provider_api', reference, state, state['submission']['request_id'])


class InProcessAPITransport(APITransport):
    """ASGI transport has no socket/DNS/internet path, redirects or arbitrary URL input."""
    def __init__(self, server):
        if type(server) is not LocalMockProviderServer:
            raise ValueError('Only the local mock provider server is enabled')
        self.server = server

    def request(self, method, path, *, payload=None, headers=None):
        if not path.startswith('/requests') or '://' in path:
            raise ValueError('Only local request API paths are allowed')
        async def call():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.server.app), base_url='http://local-provider.test') as client:
                result = await client.request(method, path, json=payload, headers=headers)
                if result.status_code >= 400:
                    raise ValueError(f'Local provider API rejected request: {result.status_code}')
                return result.json()
        return asyncio.run(call())


class OfficialAPIConnector(ProviderConnector):
    method = TransmissionMethod.OFFICIAL_API
    # The full automated contract: submit, poll, receive callbacks, download.
    CAPABILITIES = ConnectorCapabilities(
        submission_mode=SubmissionMode.AUTOMATIC, supports_status_polling=True,
        supports_webhooks=True, supports_response_download=True, supports_clarification=True)

    def __init__(self, *args, transport, authentication, **kwargs):
        super().__init__(*args, **kwargs)
        if type(transport) is not InProcessAPITransport:
            raise ValueError('Only an in-process mock API transport is enabled')
        self.transport, self.authentication = transport, authentication

    def _submit(self, package, transmission, provider, request):
        destination = self.destination(provider)
        if (provider.endpoint_references.get(self.method.value) != 'local-mock-api'
                or destination.address != 'local-mock-api'):
            raise ValueError('OFFICIAL_API must reference the configured local-mock-api')
        result = self.transport.request('POST', '/requests', headers=self.authentication.headers(), payload={
            'transmission_id': transmission.id, 'request_id': request.id, 'provider_id': provider.id,
            'package': package.canonical_json, 'package_hash': package.sha256_hash,
            'authorization_hash': request.authorization.bound_canonical_hash, 'signature': request.authorization.digital_signature})
        transmission.provider_tracking_ref = result['provider_reference']
        transmission.transmission_status = TransmissionStatus.DELIVERED
        transmission.metadata.update({'test_only': True, 'local_api_status': result['status'], 'destination_id': destination.id})
        self.open_channel(transmission)
        return transmission

    def get_status(self, provider_tracking_ref):
        channel = self.repository.get('communication_channel', provider_tracking_ref)
        if channel.get('callback_received'):
            return super().get_status(provider_tracking_ref)
        return self.transport.request('GET', '/requests/' + provider_tracking_ref, headers=self.authentication.headers())

    def retrieve_response(self, provider_tracking_ref):
        channel = self.repository.get('communication_channel', provider_tracking_ref)
        if channel.get('callback_received'):
            return super().retrieve_response(provider_tracking_ref)
        data = self.transport.request('GET', '/requests/' + provider_tracking_ref + '/response', headers=self.authentication.headers())
        return hydrate(ProviderResponse, data) if data else None
