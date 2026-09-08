"""Authenticated FastAPI routes. All business decisions remain in module services."""
from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.routing import APIRoute
from dfap.ldrm_subsystem.api.dependencies import get_actor, get_module, get_request_service
from dfap.ldrm_subsystem.api.schemas import (RequestCreate, RequestUpdate, LegalReviewRequest, AuthorizeRequestDTO,
    SignRequestDTO, DispatchRequestDTO, ProviderCreateDTO, ProviderVerifyDTO, ProviderUpdateDTO,
    ActionDTO, VerifyResponseDTO, MockStatusDTO)
from dfap.ldrm_subsystem.domain.models import RequestTarget
from dfap.ldrm_subsystem.domain.provider import Provider, ProviderDestination
from dfap.ldrm_subsystem.domain.enums import RequestStatus, DatasetType, ProviderCategory
from dfap.ldrm_subsystem.integration.ingestion_adapter import IntegrationUnavailable
from dfap.ldrm_subsystem.persistence.repositories import ConflictError
from dfap.ldrm_subsystem.policy.state_machine import InvalidStateTransitionError
from dfap.ldrm_subsystem.policy.access_policy import AccessDenied


class LDRMRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()
        async def handler(request):
            try:
                return await original(request)
            except PermissionError as error:
                if isinstance(error, AccessDenied) and not getattr(error, 'audit_recorded', False):
                    request.app.state.ldrm.audit_adapter.log_security_violation(str(error), error.actor_id, error.context)
                raise HTTPException(403, 'Permission denied') from error
            except KeyError as error:
                raise HTTPException(404, 'Resource not found') from error
            except (ConflictError, InvalidStateTransitionError) as error:
                raise HTTPException(409, str(error)) from error
            except IntegrationUnavailable as error:
                raise HTTPException(503, str(error)) from error
            except ValueError as error:
                raise HTTPException(400, str(error)) from error
        return handler


router = APIRouter(route_class=LDRMRoute)


@router.post('/requests')
def create_request(dto: RequestCreate, actor=Depends(get_actor), service=Depends(get_request_service)):
    values = dto.model_dump()
    values['targets'] = [RequestTarget(**target.model_dump()) for target in dto.targets]
    return service.create_request(**values, created_by=actor).to_dict()


@router.get('/requests')
def list_requests(case_id: str | None = None, status: RequestStatus | None = None,
                  dataset_type: DatasetType | None = None, actor=Depends(get_actor), service=Depends(get_request_service)):
    return [r.to_dict() for r in service.list_requests(actor, case_id, status, dataset_type)]


@router.get('/requests/{request_id}')
def get_request(request_id: str, actor=Depends(get_actor), service=Depends(get_request_service)):
    return service.get_request(request_id, actor).to_dict()


@router.put('/requests/{request_id}')
def update_request(request_id: str, dto: RequestUpdate, actor=Depends(get_actor), service=Depends(get_request_service)):
    values = dto.model_dump(exclude_none=True)
    if dto.targets is not None:
        values['targets'] = [RequestTarget(**target.model_dump()) for target in dto.targets]
    return service.update_request(request_id, actor, **values).to_dict()


@router.post('/requests/{request_id}/submit')
def submit(request_id: str, actor=Depends(get_actor), service=Depends(get_request_service)):
    return service.submit_for_validation(request_id, actor).to_dict()


@router.post('/requests/{request_id}/legal-review')
def review(request_id: str, dto: LegalReviewRequest, actor=Depends(get_actor), service=Depends(get_request_service)):
    return service.complete_legal_review(request_id, actor, **dto.model_dump()).to_dict()


@router.post('/requests/{request_id}/authorize')
def authorize(request_id: str, dto: AuthorizeRequestDTO, actor=Depends(get_actor), service=Depends(get_request_service)):
    return service.authorize_request(request_id, actor, **dto.model_dump()).to_dict()


@router.post('/requests/{request_id}/sign')
def sign(request_id: str, dto: SignRequestDTO, actor=Depends(get_actor), service=Depends(get_request_service)):
    return service.sign_request(request_id, actor, **dto.model_dump()).to_dict()


@router.post('/requests/{request_id}/prepare-dispatch')
def prepare(request_id: str, actor=Depends(get_actor), service=Depends(get_request_service)):
    return service.prepare_dispatch(request_id, actor).to_dict()


@router.post('/requests/{request_id}/dispatch')
def dispatch(request_id: str, dto: DispatchRequestDTO, actor=Depends(get_actor), service=Depends(get_request_service)):
    return service.dispatch_request(request_id, actor, **dto.model_dump()).to_dict()


@router.get('/requests/{request_id}/packages/{version}')
def package(request_id: str, version: int, actor=Depends(get_actor), service=Depends(get_request_service)):
    stored = service.get_package(request_id, version, actor)
    return Response(content=stored.canonical_json, media_type='application/json', headers={'ETag': f'"{stored.sha256_hash}"'})


@router.get('/requests/{request_id}/history')
def history(request_id: str, actor=Depends(get_actor), service=Depends(get_request_service)):
    return service.get_history(request_id, actor)


@router.get('/requests/{request_id}/provenance')
def provenance(request_id: str, actor=Depends(get_actor), service=Depends(get_request_service)):
    return service.get_provenance(request_id, actor)


@router.get('/requests/{request_id}/transmissions')
def transmissions(request_id: str, actor=Depends(get_actor), service=Depends(get_request_service)):
    return [t.to_dict() for t in service.get_transmissions(request_id, actor)]


@router.post('/requests/{request_id}/receive-response')
def receive(request_id: str, actor=Depends(get_actor), service=Depends(get_request_service)):
    result = service.receive_response(request_id, actor)
    return result.to_dict() if result else {'status': service.get_request(request_id, actor).status.value}


@router.get('/requests/{request_id}/responses')
def responses(request_id: str, actor=Depends(get_actor), service=Depends(get_request_service)):
    return [r.to_dict() for r in service.get_responses(request_id, actor)]


@router.post('/requests/{request_id}/responses/{response_id}/verify')
def verify(request_id: str, response_id: str, dto: VerifyResponseDTO, actor=Depends(get_actor), service=Depends(get_request_service)):
    return service.verify_response(request_id, response_id, actor, **dto.model_dump()).to_dict()


@router.post('/requests/{request_id}/responses/{response_id}/register')
def register_response(request_id: str, response_id: str, actor=Depends(get_actor), service=Depends(get_request_service)):
    return service.register_response(request_id, response_id, actor).to_dict()


@router.post('/requests/{request_id}/responses/{response_id}/ingest')
def ingest(request_id: str, response_id: str, actor=Depends(get_actor), service=Depends(get_request_service)):
    return service.ingest_response(request_id, response_id, actor)


@router.post('/requests/{request_id}/close')
def close(request_id: str, dto: ActionDTO, actor=Depends(get_actor), service=Depends(get_request_service)):
    return service.close_request(request_id, actor, dto.notes).to_dict()


@router.post('/requests/{request_id}/actions/{action}')
def exception(request_id: str, action: str, dto: ActionDTO, actor=Depends(get_actor), service=Depends(get_request_service)):
    return service.exception_action(request_id, actor, action, dto.notes).to_dict()


@router.post('/requests/{request_id}/mock-status')
def mock_status(request_id: str, dto: MockStatusDTO, actor=Depends(get_actor), module=Depends(get_module)):
    if not module.config.DEMO_MODE:
        raise HTTPException(404, 'Mock status controls are disabled')
    module.service.configure_mock_status(request_id, actor, dto.status)
    return {'status': dto.status.value}


@router.get('/providers')
def providers(category: ProviderCategory | None = None, only_eligible: bool = False,
              actor=Depends(get_actor), service=Depends(get_request_service)):
    return [p.to_dict() for p in service.provider_registry.list_providers(actor, category, only_eligible)]


@router.get('/providers/{provider_id}')
def provider(provider_id: str, actor=Depends(get_actor), service=Depends(get_request_service)):
    return service.provider_registry.get_provider(provider_id, actor).to_dict()


@router.post('/providers')
def register_provider(dto: ProviderCreateDTO, actor=Depends(get_actor), service=Depends(get_request_service)):
    values = dto.model_dump()
    values['destinations'] = [ProviderDestination(**d.model_dump()) for d in dto.destinations]
    return service.provider_registry.register_provider(Provider(**values), actor).to_dict()


@router.put('/providers/{provider_id}')
def update_provider(provider_id: str, dto: ProviderUpdateDTO, actor=Depends(get_actor), service=Depends(get_request_service)):
    values = dto.model_dump(exclude_none=True)
    if dto.destinations is not None:
        values['destinations'] = [ProviderDestination(**d.model_dump()) for d in dto.destinations]
    return service.provider_registry.update_provider(provider_id, actor, **values).to_dict()


@router.put('/providers/{provider_id}/verify')
def verify_provider(provider_id: str, dto: ProviderVerifyDTO, actor=Depends(get_actor), service=Depends(get_request_service)):
    return service.provider_registry.verify_provider(provider_id, actor, dto.notes).to_dict()


@router.post('/providers/{provider_id}/suspend')
def suspend_provider(provider_id: str, dto: ActionDTO, actor=Depends(get_actor), service=Depends(get_request_service)):
    return service.provider_registry.suspend_provider(provider_id, actor, dto.notes).to_dict()


from dfap.ldrm_subsystem.api.dependencies import get_advisory_service, get_clarification_service
from dfap.ldrm_subsystem.api.schemas import DuplicateCheckDTO, ScopeMinimizationDTO, ProviderQueryCreateDTO, ProviderQueryResponseDTO


@router.post('/advisory/check-duplicates')
def check_duplicates(dto: DuplicateCheckDTO, actor=Depends(get_actor), advisory=Depends(get_advisory_service)):
    return advisory.check_duplicates(dto.model_dump())


@router.post('/advisory/minimize-scope')
def minimize_scope(dto: ScopeMinimizationDTO, actor=Depends(get_actor), advisory=Depends(get_advisory_service)):
    return advisory.minimize_scope(**dto.model_dump())


@router.post('/requests/{request_id}/queries')
def create_provider_query(request_id: str, dto: ProviderQueryCreateDTO, actor=Depends(get_actor), clarification=Depends(get_clarification_service)):
    return clarification.receive_provider_query(request_id=request_id, provider_id=dto.provider_id, query_text=dto.query_text, actor=actor)


@router.post('/requests/{request_id}/queries/{query_id}/respond')
def respond_provider_query(request_id: str, query_id: str, dto: ProviderQueryResponseDTO, actor=Depends(get_actor), clarification=Depends(get_clarification_service)):
    return clarification.respond_to_query(query_id=query_id, request_id=request_id, response_text=dto.response_text, actor=actor, scope_modified=dto.scope_modified)


@router.get('/requests/{request_id}/queries')
def list_provider_queries(request_id: str, actor=Depends(get_actor), clarification=Depends(get_clarification_service)):
    return clarification.list_queries(request_id)


# `POST /requests/{id}/mark-manual-submitted` was removed in Stage 3. It moved a
# request to SENT with no access check, no authorization validation, no package
# hash check, no dispatch guard and no audit event, using a caller-supplied
# tracking reference. Recording a manual submission goes through
# `POST /requests/{id}/record-submission`, which requires a prepared package, an
# authenticated human with DISPATCH_REQUEST, an unchanged provider configuration,
# and a receipt; see `DispatchService.record_submission`.


from dfap.ldrm_subsystem.api.communication import communication_router
from dfap.ldrm_subsystem.api.integration import integration_router
router.include_router(communication_router)
router.include_router(integration_router)

