"""Preserve provider originals, register evidence, and route verified artifacts."""
import hashlib
from dfap.ldrm_subsystem.domain.enums import RequestStatus, ProviderResponseStatus, IngestionStatus
from dfap.ldrm_subsystem.domain.response import ProviderResponse
from dfap.ldrm_subsystem.domain.transmission import RequestTransmission
from dfap.ldrm_subsystem.domain.utils import utc_now
from dfap.ldrm_subsystem.policy.state_machine import transition, RequestStateMachine
from dfap.ldrm_subsystem.integration.ingestion_adapter import IngestionResult


class ResponseServiceError(ValueError):
    pass


class ResponseService:
    def __init__(self, access, repository, provider, evidence, ingestion, audit, max_size,
                 evidence_storage=None):
        self.access, self.repository, self.provider = access, repository, provider
        self.evidence, self.ingestion, self.audit, self.max_size = evidence, ingestion, audit, max_size
        #: Write-once original store (Stage 3 §20). Optional so an embedding host
        #: may supply its own; when present every received original is recorded.
        self.evidence_storage = evidence_storage

    def transmission(self, request):
        transmissions = self.repository.list('transmission', RequestTransmission, request.id)
        if not transmissions:
            raise ResponseServiceError('Request has not been transmitted')
        return transmissions[-1]

    def receive(self, request, actor_id):
        self.access.require(actor_id, 'RECEIVE_RESPONSE', request)
        if request.status not in {RequestStatus.SENT, RequestStatus.ACKNOWLEDGED, RequestStatus.RESPONSE_PENDING,
                                  RequestStatus.PROVIDER_PROCESSING, RequestStatus.PARTIAL_RESPONSE, RequestStatus.RESPONSE_RECEIVED, RequestStatus.PROVIDER_QUERY}:
            raise ResponseServiceError('Request is not awaiting a provider response')
        transmission = self.transmission(request)
        tracking = transmission.provider_tracking_ref
        provider = self.connector_resolver(transmission) if hasattr(self, "connector_resolver") else self.provider
        status_result = provider.get_status(tracking)
        if status_result['tracking_ref'] != tracking:
            raise ResponseServiceError('Provider tracking reference mismatch')
        status = ProviderResponseStatus(status_result['status'])
        if request.status == RequestStatus.PROVIDER_QUERY and status != ProviderResponseStatus.PROVIDER_QUERY:
            transition(request, RequestStatus.RESPONSE_PENDING, actor_id, self.audit)
        if request.status == RequestStatus.SENT:
            transition(request, RequestStatus.ACKNOWLEDGED, actor_id, self.audit)
        if request.status == RequestStatus.ACKNOWLEDGED:
            transition(request, RequestStatus.RESPONSE_PENDING, actor_id, self.audit)
        if status in {ProviderResponseStatus.ACCEPTED, ProviderResponseStatus.PROCESSING}:
            self.audit.log_event('PROVIDER_STATUS', 'LawfulDataRequest', request.id, actor_id, {'status': status.value})
            return None
        if status == ProviderResponseStatus.PROVIDER_QUERY:
            if request.status != RequestStatus.PROVIDER_QUERY:
                transition(request, RequestStatus.PROVIDER_QUERY, actor_id, self.audit)
            return None
        if status == ProviderResponseStatus.REJECTED:
            transition(request, RequestStatus.REJECTED, actor_id, self.audit)
            return None
        response = provider.retrieve_response(tracking)
        if response is None:
            return None
        if (response.request_id, response.case_id, response.provider_id, response.transmission_id,
            response.metadata.get('tracking_ref'), response.provider_status) != (
                request.id, request.case_id, request.provider_id, transmission.id, tracking, status):
            raise ResponseServiceError('Response provenance does not match the transmission')
        if len(response.raw_payload) > self.max_size or not response.raw_payload:
            raise ResponseServiceError('Response is empty or exceeds the size limit')
        if not response.raw_payload_hash or hashlib.sha256(response.raw_payload).hexdigest() != response.raw_payload_hash:
            raise ResponseServiceError('Response hash mismatch')
        if not provider.verify_response(response):
            raise ResponseServiceError('Provider connector rejected response integrity')
        try:
            existing = self.repository.get('response', response.id, ProviderResponse)
        except KeyError:
            existing = None
        if existing:
            if (existing.raw_payload_hash, existing.transmission_id) != (response.raw_payload_hash, transmission.id):
                raise ResponseServiceError('Provider reused a response ID with different content')
            return existing
        target = RequestStatus.PARTIAL_RESPONSE if status == ProviderResponseStatus.PARTIAL_RESPONSE else RequestStatus.RESPONSE_RECEIVED
        # A subsequent complete response is a distinct artifact; retain partial originals.
        if request.status != target:
            RequestStateMachine.validate_transition(request.status, target)
        response.receipt_timestamp = utc_now()
        raw_bytes = response.raw_payload
        digest = self.repository.preserve(raw_bytes)
        if self.evidence_storage is not None:
            # Write-once: a second payload under the same identity is refused,
            # and an identical one is recognised as a duplicate rather than
            # rewritten. Recorded before the response row so the original
            # survives even if later steps fail.
            duplicates = self.evidence_storage.find_by_hash(digest)
            record = self.evidence_storage.store_original(
                evidence_id='ORIG-' + response.id.replace('/', '-'), response_id=response.id,
                request_id=request.id, case_id=request.case_id, provider_id=request.provider_id,
                raw_payload=raw_bytes,
                media_type=response.metadata.get('content_type', 'application/json'),
                actor_id=actor_id)
            response.metadata['original_storage_reference'] = record.chain_of_custody_reference
            if duplicates:
                response.metadata['duplicate_of'] = duplicates
                self.audit.log_event('PROVIDER_RESPONSE_DUPLICATE_PAYLOAD', 'LawfulDataRequest',
                                     request.id, actor_id,
                                     {'response_id': response.id, 'sha256': digest,
                                      'existing_evidence_ids': duplicates})
        response.raw_payload_path = 'ldrm:sha256:' + digest
        response.raw_payload = b''  # Bytes live in immutable artifact storage, never text metadata.
        self.repository.put('response_original', response.id, response, request.id, immutable=True)
        self.repository.put('response', response.id, response, request.id)
        if request.status != target:
            transition(request, target, actor_id, self.audit)
        self.audit.log_event('PROVIDER_RESPONSE_RECEIVED', 'LawfulDataRequest', request.id, actor_id,
                             {'response_id': response.id, 'transmission_id': transmission.id, 'hash': digest})
        return response

    def response(self, request, response_id):
        response = self.repository.get('response', response_id, ProviderResponse)
        transmission = self.transmission(request)
        if (response.request_id, response.case_id, response.provider_id, response.transmission_id) != (
                request.id, request.case_id, request.provider_id, transmission.id):
            raise ResponseServiceError('Response belongs to another request, case, or transmission')
        original = self.repository.get('response_original', response_id, ProviderResponse)
        if (response.raw_payload_hash, response.raw_payload_path, response.receipt_timestamp) != (
                original.raw_payload_hash, original.raw_payload_path, original.receipt_timestamp):
            raise ResponseServiceError('Response original metadata was altered')
        return response

    def evidence_metadata(self, request, response):
        transmission = self.transmission(request)
        return {'request_id': request.id, 'request_number': request.request_number, 'request_version': transmission.request_version,
                'authorization_id': transmission.authorization_id, 'transmission_id': transmission.id,
                'response_id': response.id, 'case_id': request.case_id, 'provider_id': request.provider_id,
                'dataset_type': request.dataset_type.value, 'package_hash': transmission.package_payload_hash,
                'authority_reference': request.authorization.authority_reference,
                'partial': response.provider_status == ProviderResponseStatus.PARTIAL_RESPONSE}

    def validate_evidence(self, request, response, evidence, raw):
        if not evidence or (evidence.case_id, evidence.payload_hash, evidence.byte_length) != (request.case_id, response.raw_payload_hash, len(raw)):
            raise ResponseServiceError('Evidence adapter returned mismatched evidence')
        if any(evidence.metadata.get(key) != value for key, value in self.evidence_metadata(request, response).items()):
            raise ResponseServiceError('Evidence adapter did not preserve provenance')
        if not self.evidence.verify_evidence_integrity(evidence.evidence_id, raw):
            raise ResponseServiceError('Evidence integrity verification failed')

    def register(self, request, response_id, actor_id):
        self.access.require(actor_id, 'RECEIVE_RESPONSE', request)
        response = self.response(request, response_id)
        raw = self.repository.read_artifact(response.raw_payload_hash)
        if response.evidence_id:
            self.validate_evidence(request, response, self.evidence.get_evidence(response.evidence_id), raw)
            return response
        evidence = self.evidence.register_evidence(request.case_id, f'LDRM-{response.id}', raw,
                                                   response.raw_payload_hash, self.evidence_metadata(request, response))
        # Registration establishes provenance; independent verification gates ingestion.
        if not evidence or evidence.case_id != request.case_id or evidence.payload_hash != response.raw_payload_hash:
            raise ResponseServiceError('Evidence registration returned mismatched evidence')
        if any(evidence.metadata.get(key) != value for key, value in self.evidence_metadata(request, response).items()):
            raise ResponseServiceError('Evidence registration did not retain provenance')
        response.bind_evidence(evidence.evidence_id)
        self.repository.put('response', response.id, response, request.id)
        self.audit.log_event('EVIDENCE_REGISTERED', 'LawfulDataRequest', request.id, actor_id,
                             {'response_id': response.id, 'evidence_id': evidence.evidence_id})
        return response

    def verify(self, request, response_id, actor_id, accept_partial=False):
        self.access.require(actor_id, 'VERIFY_EVIDENCE', request)
        response = self.response(request, response_id)
        if response.provider_status == ProviderResponseStatus.PARTIAL_RESPONSE and not accept_partial:
            raise ResponseServiceError('Partial evidence requires an explicit acceptance decision')
        if response.verified_at:
            return response
        if response.provider_status == ProviderResponseStatus.PARTIAL_RESPONSE and request.status != RequestStatus.PARTIAL_RESPONSE:
            raise ResponseServiceError('Partial response has been superseded')
        RequestStateMachine.validate_transition(request.status, RequestStatus.EVIDENCE_VERIFIED)
        if not response.evidence_id:
            raise ResponseServiceError('Register the preserved response with evidence before verification')
        raw = self.repository.read_artifact(response.raw_payload_hash)
        evidence = self.evidence.get_evidence(response.evidence_id)
        self.validate_evidence(request, response, evidence, raw)
        response.verified_at, response.verified_by = utc_now(), actor_id
        self.repository.put('response', response.id, response, request.id)
        if all(r.verified_at for r in self.fulfillment_responses(request)):
            transition(request, RequestStatus.EVIDENCE_VERIFIED, actor_id, self.audit)
        self.audit.log_event('EVIDENCE_VERIFIED_AND_REGISTERED', 'LawfulDataRequest', request.id, actor_id,
                             {'response_id': response.id, 'evidence_id': evidence.evidence_id, 'payload_hash': response.raw_payload_hash})
        return response

    def ingest(self, request, response_id, actor_id):
        self.access.require(actor_id, 'INGEST_DATASET', request)
        response = self.response(request, response_id)
        if not response.verified_at or not response.evidence_id:
            raise ResponseServiceError('Evidence must be verified before ingestion')
        if response.ingestion_status == IngestionStatus.INGESTED:
            return self.repository.get('ingestion', response.id, IngestionResult)
        RequestStateMachine.validate_transition(request.status, RequestStatus.INGESTED)
        raw = self.repository.read_artifact(response.raw_payload_hash)
        evidence = self.evidence.get_evidence(response.evidence_id)
        if (not evidence or evidence.case_id != request.case_id or evidence.payload_hash != response.raw_payload_hash
                or evidence.metadata.get('response_id') != response.id
                or not self.evidence.verify_evidence_integrity(response.evidence_id, raw)):
            raise ResponseServiceError('Evidence integrity or provenance verification failed')
        context = {**evidence.metadata, 'idempotency_key': f'ldrm:{response.id}:{response.raw_payload_hash}'}
        result = self.ingestion.route(evidence, request.dataset_type, raw, context)
        if not isinstance(result, IngestionResult) or (result.case_id, result.evidence_id, result.dataset_type) != (
                request.case_id, evidence.evidence_id, request.dataset_type):
            raise ResponseServiceError('Dataset provenance mismatch')
        if result.pipeline_status == 'SUCCESS':
            if not result.dataset_id or result.records_ingested < 0:
                raise ResponseServiceError('Ingestion completion needs a valid dataset ID and record count')
            response.mark_ingested({'dataset_id': result.dataset_id, 'job_id': result.job_id, **result.details})
            # Include this result when deciding whether the request is complete.
            self.repository.put('response', response.id, response, request.id)
            if all(r.ingestion_status == IngestionStatus.INGESTED for r in self.fulfillment_responses(request)):
                transition(request, RequestStatus.INGESTED, actor_id, self.audit)
            self.audit.log_event('DATASET_INGESTED', 'LawfulDataRequest', request.id, actor_id,
                                 {'response_id': response.id, 'evidence_id': evidence.evidence_id, 'dataset_id': result.dataset_id})
        elif result.pipeline_status == 'FAILED':
            response.mark_ingestion_failed(result.error_message or 'Host ingestion failed')
        elif result.pipeline_status not in {'PENDING', 'PROCESSING'} or not result.job_id:
            raise ResponseServiceError('Invalid ingestion status or missing job identifier')
        self.repository.put('ingestion', response.id, result, request.id)
        self.repository.put('response', response.id, response, request.id)
        return result

    def close_request(self, request, actor_id, notes=''):
        self.access.require(actor_id, 'CLOSE_REQUEST', request)
        transition(request, RequestStatus.CLOSED, actor_id, self.audit, notes)
        self.audit.log_event('REQUEST_CLOSED', 'LawfulDataRequest', request.id, actor_id, {'notes': notes})
        return request


    def fulfillment_responses(self, request):
        responses = self.repository.list('response', ProviderResponse, request.id)
        complete = [r for r in responses if r.provider_status == ProviderResponseStatus.COMPLETED]
        return complete or responses
