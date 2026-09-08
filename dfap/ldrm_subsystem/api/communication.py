"""Additional provider communication endpoints, all test/mock only."""
from datetime import datetime
from typing import Literal
from fastapi import APIRouter, Depends, Request, HTTPException
from pydantic import Field, ValidationError
from dfap.ldrm_subsystem.api.router import LDRMRoute
from dfap.ldrm_subsystem.api.dependencies import get_actor, get_module, get_request_service
from dfap.ldrm_subsystem.api.schemas import StrictModel
from dfap.ldrm_subsystem.domain.enums import TransmissionMethod, ProviderResponseStatus

communication_router = APIRouter(route_class=LDRMRoute)


class SenderDTO(StrictModel):
    address: str
    identity: str


class CallbackKeyDTO(StrictModel):
    secret: str = Field(min_length=32)


class SubmissionDTO(StrictModel):
    method: TransmissionMethod
    submitted_at: datetime
    provider_reference: str = Field(min_length=1)
    receipt_reference: str = Field(min_length=1)
    notes: str = Field(min_length=1)
    physical_method: Literal['REGISTERED_POST', 'COURIER', 'IN_PERSON', 'OFFLINE_MEDIA'] | None = None
    provider_acknowledgement: bool = False


class AttachmentDTO(StrictModel):
    filename: str
    content_type: str
    content_base64: str = Field(max_length=2_000_000)
    sha256: str | None = None


class ReplyDTO(StrictModel):
    event_id: str = Field(min_length=1, max_length=200)
    request_id: str
    request_reference: str
    provider_reference: str
    thread_reference: str
    timestamp: datetime
    status: Literal['ACCEPTED', 'ACKNOWLEDGED', 'PROCESSING', 'PROVIDER_QUERY', 'REJECTED', 'PARTIAL_RESPONSE', 'COMPLETED', 'RESPONSE_RECEIVED']
    sender: str | None = None
    institution_reference: str | None = None
    attachments: list[AttachmentDTO] = Field(default_factory=list, max_length=10)


class APIStatusDTO(StrictModel):
    status: ProviderResponseStatus


@communication_router.put('/communication/sender')
def configure_sender(dto: SenderDTO, actor=Depends(get_actor), module=Depends(get_module)):
    return module.communication.configure_sender(actor, **dto.model_dump())


@communication_router.put('/providers/{provider_id}/destinations/{destination_id}/verify')
def verify_destination(provider_id: str, destination_id: str, actor=Depends(get_actor), service=Depends(get_request_service)):
    return service.provider_registry.verify_destination(provider_id, destination_id, actor).to_dict()


@communication_router.put('/providers/{provider_id}/test-callback-key')
def callback_key(provider_id: str, dto: CallbackKeyDTO, actor=Depends(get_actor), module=Depends(get_module)):
    return module.communication.configure_callback_key(provider_id, actor, dto.secret)


@communication_router.get('/requests/{request_id}/submission-preparations')
def preparations(request_id: str, actor=Depends(get_actor), module=Depends(get_module)):
    return module.communication.preparations(request_id, actor)


@communication_router.post('/requests/{request_id}/record-submission')
def record_submission(request_id: str, dto: SubmissionDTO, actor=Depends(get_actor), module=Depends(get_module)):
    return module.communication.record_submission(request_id, actor, **dto.model_dump()).to_dict()


@communication_router.get('/requests/{request_id}/test-messages')
def test_messages(request_id: str, actor=Depends(get_actor), module=Depends(get_module)):
    return module.communication.captured_messages(request_id, actor)


@communication_router.get('/requests/{request_id}/quarantine')
def quarantine(request_id: str, actor=Depends(get_actor), module=Depends(get_module)):
    return module.communication.quarantine_records(request_id, actor)


@communication_router.post('/providers/{provider_id}/test-replies')
def test_reply(provider_id: str, dto: ReplyDTO, actor=Depends(get_actor), module=Depends(get_module)):
    return module.communication.accept_test_reply(provider_id, dto.model_dump(mode='json'), actor)


@communication_router.post('/requests/{request_id}/test-api-status')
def api_status(request_id: str, dto: APIStatusDTO, actor=Depends(get_actor), module=Depends(get_module)):
    module.communication.configure_api_status(request_id, actor, dto.status)
    return {'status': dto.status.value}


@communication_router.post('/provider-callbacks/{provider_id}')
async def provider_callback(provider_id: str, request: Request, module=Depends(get_module)):
    module.communication.require_demo()
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 5_000_000:
            raise HTTPException(413, 'Callback exceeds the five-megabyte limit')
    raw = bytes(body)
    signature = request.headers.get('x-provider-signature', '')
    if not module.communication.receiver.authenticator.verify(provider_id, raw, signature):
        module.audit_adapter.log_security_violation('Invalid callback authentication', 'provider:' + provider_id)
        raise HTTPException(401, 'Invalid provider authentication')
    try:
        event = ReplyDTO.model_validate_json(raw)
    except ValidationError as error:
        raise HTTPException(422, 'Invalid provider event envelope') from error
    return module.communication.accept_callback(provider_id, event.model_dump(mode='json'), raw, signature)
