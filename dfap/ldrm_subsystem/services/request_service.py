"""Public LDRM application service. Host systems are accessed only through adapters."""
from copy import deepcopy
from datetime import timedelta
import uuid
from dfap.ldrm_subsystem.domain.models import LawfulDataRequest, RequestAuthorization
from dfap.ldrm_subsystem.domain.enums import RequestStatus, Priority, TransmissionMethod
from dfap.ldrm_subsystem.domain.response import ProviderResponse
from dfap.ldrm_subsystem.domain.transmission import RequestTransmission
from dfap.ldrm_subsystem.domain.utils import utc_now
from dfap.ldrm_subsystem.persistence.repositories import ConflictError
from dfap.ldrm_subsystem.persistence.unit_of_work import atomic
from dfap.ldrm_subsystem.policy.access_policy import AccessPolicy, AccessDenied
from dfap.ldrm_subsystem.policy.state_machine import transition, RequestStateMachine
from dfap.ldrm_subsystem.services.package_service import PackageService
from dfap.ldrm_subsystem.services.validation_service import ValidationService, ValidationServiceError
from dfap.ldrm_subsystem.services.authorization_service import AuthorizationService
from dfap.ldrm_subsystem.services.dispatch_service import DispatchService
from dfap.ldrm_subsystem.services.response_service import ResponseService
from dfap.ldrm_subsystem.providers.registry import ProviderRegistry
from dfap.ldrm_subsystem.providers.mock_adapter import MockProviderAdapter


class RequestService:
    def __init__(self, *, repository, case_adapter, auth_adapter, audit_adapter,
                 evidence_adapter, ingestion_adapter, max_response_size=100*1024*1024, timeout_days=30,
                 config=None, secret_provider=None, sandbox_authorizations=None):
        self.repository = repository
        self.case_adapter, self.auth_adapter, self.audit_adapter = case_adapter, auth_adapter, audit_adapter
        self.evidence_adapter, self.ingestion_adapter = evidence_adapter, ingestion_adapter
        self.access = AccessPolicy(auth_adapter, case_adapter)
        self.provider_registry = ProviderRegistry(repository, self.access, audit_adapter)
        self.provider_adapter = MockProviderAdapter(repository)
        self.validation_service = ValidationService(case_adapter, self.provider_registry, audit_adapter)
        self.authorization_service = AuthorizationService(self.access, repository, audit_adapter)
        from dfap.ldrm_subsystem.config import LDRMConfig
        from dfap.ldrm_subsystem.security.secrets import DevelopmentSecretProvider
        self.config = config or LDRMConfig()
        self.secret_provider = secret_provider or DevelopmentSecretProvider()
        self.dispatch_service = DispatchService(self.access, repository, self.provider_registry,
                                                self.provider_adapter, self.authorization_service, audit_adapter,
                                                config=self.config, secret_provider=self.secret_provider,
                                                sandbox_authorizations=sandbox_authorizations)
        from dfap.ldrm_subsystem.services.evidence_storage import ImmutableEvidenceStorage
        self.evidence_storage = ImmutableEvidenceStorage(self.config.STORAGE_DIR, repository)
        self.response_service = ResponseService(self.access, repository, self.provider_adapter,
                                                evidence_adapter, ingestion_adapter, audit_adapter,
                                                max_response_size, evidence_storage=self.evidence_storage)
        self.response_service.connector_resolver = self.dispatch_service.provider_for
        self.timeout_days = timeout_days

    def _get(self, request_id, actor_id, permission, *, active=True):
        # Authenticate/authorize globally before resolving object identifiers.
        self.access.require(actor_id, permission, active=False)
        request = self.repository.get_request(request_id)
        self.access.require(actor_id, permission, request, active=active)
        return request

    def get_request(self, request_id, actor_id):
        try:
            return self._get(request_id, actor_id, 'VIEW_REQUEST', active=False)
        except AccessDenied as error:
            self.audit_adapter.log_security_violation(str(error), actor_id, error.context)
            error.audit_recorded = True
            raise

    def list_requests(self, actor_id, case_id=None, status=None, dataset_type=None):
        try:
            self.access.require(actor_id, 'VIEW_REQUEST', case_id=case_id, active=False)
            return [r for r in self.repository.list_requests()
                    if self.case_adapter.user_has_case_access(actor_id, r.case_id, 'VIEW_REQUEST')
                    and (not case_id or r.case_id == case_id) and (not status or r.status == status)
                    and (not dataset_type or r.dataset_type == dataset_type)]
        except AccessDenied as error:
            self.audit_adapter.log_security_violation(str(error), actor_id, error.context)
            error.audit_recorded = True
            raise

    @atomic
    def create_request(self, case_id, provider_id, dataset_type, targets, created_by,
                       priority=Priority.ROUTINE, assigned_to=None, scope=None):
        self.access.require(created_by, 'CREATE_REQUEST', case_id=case_id)
        if assigned_to:
            self.access.require(assigned_to, 'VIEW_REQUEST', case_id=case_id)
        self.provider_registry._get(provider_id)
        request = LawfulDataRequest(case_id=case_id, provider_id=provider_id, dataset_type=dataset_type,
                    targets=deepcopy(targets), created_by=created_by, assigned_to=assigned_to or created_by,
                    priority=priority, scope=deepcopy(scope or {}),
                    request_number=f'LDR-{utc_now().year}-{uuid.uuid4().hex[:12].upper()}')
        package = PackageService.generate_package(request)
        request.canonical_hash = package.sha256_hash
        self.repository.save_request(request, create=True)
        self.repository.store_package(request.id, package)
        # Immutable version ledger: the historical authorized representation of
        # a request version is never rewritten (Stage 3 §22).
        self.repository.record_request_version(request.id, request.request_version,
                                               package.sha256_hash, created_by, request.created_at)
        # Host association must be idempotent by request_id. Persist an outbox
        # entry so a host outage cannot leave an untracked case association.
        self.repository.put('case_link', request.id, {'case_id': case_id, 'request_id': request.id, 'delivered': False}, request.id)
        self.audit_adapter.log_event('REQUEST_CREATED', 'LawfulDataRequest', request.id, created_by,
                                    {'case_id': case_id, 'version': request.request_version, 'hash': package.sha256_hash})
        return request

    @atomic
    def update_request(self, request_id, actor_id, *, expected_revision, provider_id=None,
                       dataset_type=None, targets=None, priority=None, scope=None):
        request = self._get(request_id, actor_id, 'EDIT_DRAFT')
        if request.revision != expected_revision:
            raise ConflictError('Request changed; reload before editing')
        if request.status not in {RequestStatus.DRAFT, RequestStatus.NEEDS_CORRECTION, RequestStatus.LEGAL_REVIEW,
                                  RequestStatus.AUTHORIZATION_PENDING, RequestStatus.AUTHORIZED, RequestStatus.SIGNED, RequestStatus.READY_TO_SEND}:
            raise ValueError('Request cannot be edited in this state; transmitted versions are immutable')
        old = request.canonical_dict()
        for key, value in {'provider_id': provider_id, 'dataset_type': dataset_type, 'targets': targets, 'scope': scope}.items():
            if value is not None:
                setattr(request, key, deepcopy(value))
        self.provider_registry._get(request.provider_id)
        if priority is not None:
            request.priority = priority
        if request.canonical_dict() != old:
            self.authorization_service.invalidate(request, actor_id, 'Scope altered after review')
            request.canonical_hash = None
            if request.status not in {RequestStatus.DRAFT, RequestStatus.NEEDS_CORRECTION}:
                transition(request, RequestStatus.NEEDS_CORRECTION, actor_id, self.audit_adapter)
            request.legal_reviewer_id = request.legal_review_notes = None
            request.request_version += 1
            package = PackageService.generate_package(request)
            request.canonical_hash = package.sha256_hash
            self.repository.store_package(request.id, package)
            self.repository.record_request_version(request.id, request.request_version,
                                                   package.sha256_hash, actor_id, utc_now())
        request.updated_at = utc_now()
        self.repository.save_request(request)
        self.audit_adapter.log_event('REQUEST_UPDATED', 'LawfulDataRequest', request.id, actor_id,
                                    {'version': request.request_version, 'hash': request.canonical_hash})
        return request

    @atomic
    def submit_for_validation(self, request_id, actor_id):
        request = self._get(request_id, actor_id, 'SUBMIT_REQUEST')
        transition(request, RequestStatus.VALIDATION_PENDING, actor_id, self.audit_adapter)
        try:
            self.validation_service.validate_for_submission(request, actor_id)
        except ValidationServiceError as error:
            transition(request, RequestStatus.NEEDS_CORRECTION, actor_id, self.audit_adapter, str(error))
        else:
            transition(request, RequestStatus.LEGAL_REVIEW, actor_id, self.audit_adapter)
            self.audit_adapter.log_event('REQUEST_SUBMITTED_FOR_LEGAL_REVIEW', 'LawfulDataRequest', request.id, actor_id)
        self.repository.save_request(request)
        return request

    @atomic
    def complete_legal_review(self, request_id, reviewer_id, approved, notes):
        request = self._get(request_id, reviewer_id, 'REVIEW_LEGAL')
        if request.status != RequestStatus.LEGAL_REVIEW or not notes.strip():
            raise ValueError('A pending legal review and decision notes are required')
        transition(request, RequestStatus.AUTHORIZATION_PENDING if approved else RequestStatus.NEEDS_CORRECTION,
                   reviewer_id, self.audit_adapter, notes)
        request.legal_reviewer_id, request.legal_review_notes = reviewer_id, notes
        self.repository.save_request(request)
        self.audit_adapter.log_event('LEGAL_REVIEW_COMPLETED', 'LawfulDataRequest', request.id, reviewer_id, {'approved': approved})
        return request

    @atomic
    def authorize_request(self, request_id, approver_id, authority_type, authority_reference,
                          issuing_authority, approved_scope_summary, *, expected_version, expected_hash,
                          valid_from=None, valid_until=None):
        request = self._get(request_id, approver_id, 'AUTHORIZE_REQUEST')
        auth = self.authorization_service.authorize_request(request, approver_id, authority_type,
                 authority_reference, issuing_authority, approved_scope_summary, expected_version=expected_version,
                 expected_hash=expected_hash, valid_from=valid_from, valid_until=valid_until)
        self.repository.save_request(request)
        return auth

    @atomic
    def sign_request(self, request_id, signer_id, *, expected_hash):
        request = self._get(request_id, signer_id, 'SIGN_REQUEST')
        self.authorization_service.sign_request(request, signer_id, expected_hash=expected_hash)
        self.repository.save_request(request)
        return request

    @atomic
    def prepare_dispatch(self, request_id, actor_id):
        request = self._get(request_id, actor_id, 'DISPATCH_REQUEST')
        self.dispatch_service.prepare_for_dispatch(request, actor_id)
        self.repository.save_request(request)
        return request

    @atomic
    def dispatch_request(self, request_id, dispatched_by, transmission_method=None):
        request = self._get(request_id, dispatched_by, 'DISPATCH_REQUEST')
        self.dispatch_service.dispatch(request, dispatched_by, transmission_method)
        self.repository.save_request(request)
        return request

    def receive_response(self, request_id, actor_id):
        # Commit received bytes first. If the host evidence service is offline,
        # the preserved original survives and registration can be retried.
        response = self._receive_response(request_id, actor_id)
        if response:
            return self.register_response(request_id, response.id, actor_id)
        return None

    @atomic
    def _receive_response(self, request_id, actor_id):
        request = self._get(request_id, actor_id, 'RECEIVE_RESPONSE')
        response = self.response_service.receive(request, actor_id)
        self.repository.save_request(request)
        return response

    @atomic
    def register_response(self, request_id, response_id, actor_id):
        request = self._get(request_id, actor_id, 'RECEIVE_RESPONSE')
        return self.response_service.register(request, response_id, actor_id)

    @atomic
    def verify_response(self, request_id, response_id, actor_id, accept_partial=False):
        request = self._get(request_id, actor_id, 'VERIFY_EVIDENCE')
        response = self.response_service.verify(request, response_id, actor_id, accept_partial)
        self.repository.save_request(request)
        return response

    @atomic
    def ingest_response(self, request_id, response_id, actor_id):
        request = self._get(request_id, actor_id, 'INGEST_DATASET')
        result = self.response_service.ingest(request, response_id, actor_id)
        self.repository.save_request(request)
        return result

    @atomic
    def close_request(self, request_id, actor_id, notes=''):
        request = self._get(request_id, actor_id, 'CLOSE_REQUEST')
        self.response_service.close_request(request, actor_id, notes)
        self.repository.save_request(request)
        return request

    @atomic
    def exception_action(self, request_id, actor_id, action, notes):
        actions = {'cancel': ('CANCEL_REQUEST', RequestStatus.CANCELLED),
                   'reject': ('REVIEW_LEGAL', RequestStatus.REJECTED),
                   'correction': ('EDIT_DRAFT', RequestStatus.NEEDS_CORRECTION),
                   'provider-query': ('PROVIDER_QUERY', RequestStatus.PROVIDER_QUERY),
                   'resume': ('PROVIDER_QUERY', RequestStatus.RESPONSE_PENDING),
                   'expire': ('EXPIRE_REQUEST', RequestStatus.EXPIRED)}
        if action not in actions or not notes.strip():
            raise ValueError('A supported action and reason are required')
        permission, target = actions[action]
        request = self._get(request_id, actor_id, permission, active=action not in {'expire', 'cancel'})
        if action == 'reject' and request.status not in {RequestStatus.LEGAL_REVIEW, RequestStatus.AUTHORIZATION_PENDING}:
            raise ValueError('Human rejection is only valid during review or authorization')
        if action == 'correction' and self.repository.list('transmission', request_id=request.id):
            raise ValueError('Transmitted scope is immutable; create a new request')
        if action == 'expire':
            auth = request.authorization
            deadline = auth.valid_until if auth and auth.valid_until else request.created_at + timedelta(days=self.timeout_days)
            if deadline > utc_now():
                raise ValueError('Request has not expired')
        transition(request, target, actor_id, self.audit_adapter, notes)
        if target in {RequestStatus.NEEDS_CORRECTION, RequestStatus.EXPIRED, RequestStatus.CANCELLED, RequestStatus.REJECTED}:
            self.authorization_service.invalidate(request, actor_id, notes)
        self.repository.save_request(request)
        return request

    def get_package(self, request_id, version, actor_id):
        self.get_request(request_id, actor_id)
        return self.repository.get_package(request_id, version)

    def get_history(self, request_id, actor_id):
        self.get_request(request_id, actor_id)
        return self.audit_adapter.get_events_for_entity(request_id)

    def get_responses(self, request_id, actor_id):
        self.get_request(request_id, actor_id)
        return self.repository.list('response', ProviderResponse, request_id)

    def get_transmissions(self, request_id, actor_id):
        self.get_request(request_id, actor_id)
        return self.repository.list('transmission', RequestTransmission, request_id)

    def get_provenance(self, request_id, actor_id):
        request = self.get_request(request_id, actor_id)
        return {'case_id': request.case_id, 'request_id': request.id,
                'authorizations': [a.to_dict() for a in self.repository.list('authorization', RequestAuthorization, request.id)],
                'transmissions': [t.to_dict() for t in self.get_transmissions(request_id, actor_id)],
                'responses': [r.to_dict() for r in self.get_responses(request_id, actor_id)],
                'datasets': self.repository.list('ingestion', request_id=request.id)}

    def flush_case_links(self):
        for link in self.repository.list('case_link'):
            if not link['delivered']:
                self.case_adapter.attach_request_to_case(link['case_id'], link['request_id'])
                link['delivered'] = True
                with self.repository.transaction():
                    self.repository.put('case_link', link['request_id'], link, link['request_id'])

    @atomic
    def configure_mock_status(self, request_id, actor_id, status):
        self.access.administrator(actor_id)
        request = self._get(request_id, actor_id, 'RECEIVE_RESPONSE')
        transmission = self.response_service.transmission(request)
        self.provider_adapter.configure_simulated_status(transmission.provider_tracking_ref, status)
        self.audit_adapter.log_event('MOCK_PROVIDER_STATUS_SET', 'LawfulDataRequest', request.id, actor_id, {'status': status.value})
