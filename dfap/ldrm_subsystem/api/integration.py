"""Administrator API for provider integrations (DFAP Stage 3 §23, §29, §30).

Every route delegates to a service; no security decision is made here. Responses
carry references, never resolved secrets or key material. There is no route that
skips a lifecycle requirement: activation goes through the same
`production_activation_blockers` check as everything else.
"""
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import Field

from dfap.ldrm_subsystem.api.dependencies import get_actor, get_module
from dfap.ldrm_subsystem.api.router import LDRMRoute
from dfap.ldrm_subsystem.api.schemas import StrictModel
from dfap.ldrm_subsystem.domain.enums import (
    CertificateType, DatasetType, IntegrationEnvironment, ProviderIntegrationStatus,
    TransmissionMethod)

integration_router = APIRouter(route_class=LDRMRoute)


def get_integration_service(module=Depends(get_module)):
    return module.integration_service


def get_readiness_service(module=Depends(get_module)):
    return module.readiness_service


# --------------------------------------------------------------------- DTOs

class IntegrationProfileCreateDTO(StrictModel):
    provider_id: str = Field(min_length=1)
    environment: IntegrationEnvironment
    submission_method: TransmissionMethod
    response_method: str = 'MOCK'
    supported_dataset_types: list[DatasetType] = Field(default_factory=list)
    supported_request_categories: list[str] = Field(default_factory=list, max_length=64)
    # An endpoint may be proposed here by an administrator, but it is UNVERIFIED
    # until separately verified and allowlisted. Request creators never reach this.
    endpoint_reference: str = ''
    authentication_type: str = 'HMAC_SECRET'
    credential_reference: str = ''
    client_certificate_reference: str | None = None
    signing_certificate_reference: str | None = None
    required_documents: list[str] = Field(default_factory=list, max_length=32)
    required_fields: list[str] = Field(default_factory=list, max_length=64)
    accepted_request_formats: list[str] = Field(default_factory=lambda: ['application/json'])
    accepted_response_formats: list[str] = Field(default_factory=lambda: ['application/json'])
    webhook_enabled: bool = False
    webhook_reference: str | None = None
    expires_at: datetime | None = None


class IntegrationProfileUpdateDTO(StrictModel):
    submission_method: TransmissionMethod | None = None
    response_method: str | None = None
    supported_dataset_types: list[DatasetType] | None = None
    supported_request_categories: list[str] | None = None
    endpoint_reference: str | None = None
    authentication_type: str | None = None
    credential_reference: str | None = None
    client_certificate_reference: str | None = None
    signing_certificate_reference: str | None = None
    webhook_enabled: bool | None = None
    webhook_reference: str | None = None
    expires_at: datetime | None = None


class LifecycleActionDTO(StrictModel):
    target_status: ProviderIntegrationStatus
    reason: str = Field(min_length=1, max_length=2000)


class ReasonDTO(StrictModel):
    reason: str = Field(min_length=1, max_length=2000)


class ApprovalDTO(StrictModel):
    reference: str = Field(min_length=1, max_length=200)
    notes: str = Field(min_length=1, max_length=4000)
    expires_at: datetime | None = None


class EndpointVerifyDTO(StrictModel):
    notes: str = Field(min_length=1, max_length=2000)


class AllowlistEntryDTO(StrictModel):
    provider_id: str = Field(min_length=1)
    environment: IntegrationEnvironment
    url: str = Field(min_length=1, max_length=2048)
    notes: str = Field(min_length=1, max_length=2000)


class CertificateRegisterDTO(StrictModel):
    certificate_reference: str = Field(min_length=1, max_length=200)
    certificate_type: CertificateType
    issuer: str = Field(min_length=1, max_length=500)
    fingerprint: str = Field(min_length=1, max_length=200)
    valid_from: datetime
    valid_until: datetime
    environment: IntegrationEnvironment
    status: Literal['ACTIVE', 'REVOKED', 'SUSPENDED', 'UNTRUSTED', 'PENDING'] = 'ACTIVE'


# ------------------------------------------------------------------- routes

@integration_router.get('/integrations')
def list_integrations(provider_id: str | None = None,
                      environment: IntegrationEnvironment | None = None,
                      actor=Depends(get_actor), service=Depends(get_integration_service)):
    return [p.to_dict() for p in service.list_profiles(actor, provider_id, environment)]


@integration_router.get('/integrations/{integration_profile_id}')
def get_integration(integration_profile_id: str, actor=Depends(get_actor),
                    service=Depends(get_integration_service)):
    profile = service.get_profile(integration_profile_id, actor)
    return {**profile.to_dict(),
            'approvals': service.live_approvals(integration_profile_id),
            'status_history': service.repository.list_integration_status_history(integration_profile_id),
            'certifications': [c.to_dict() for c in
                               service.repository.list_certification_records(integration_profile_id)],
            'production_activation_blockers': service.production_activation_blockers(profile)}


@integration_router.post('/integrations')
def create_integration(dto: IntegrationProfileCreateDTO, actor=Depends(get_actor),
                       service=Depends(get_integration_service)):
    return service.create_profile(actor, **dto.model_dump()).to_dict()


@integration_router.put('/integrations/{integration_profile_id}')
def update_integration(integration_profile_id: str, dto: IntegrationProfileUpdateDTO,
                       actor=Depends(get_actor), service=Depends(get_integration_service)):
    return service.update_profile(integration_profile_id, actor,
                                  **dto.model_dump(exclude_none=True)).to_dict()


@integration_router.post('/integrations/{integration_profile_id}/validate-configuration')
def validate_configuration(integration_profile_id: str, actor=Depends(get_actor),
                           service=Depends(get_integration_service)):
    return service.validate_configuration(integration_profile_id, actor)


@integration_router.post('/integrations/{integration_profile_id}/contract-tests')
def run_contract_tests(integration_profile_id: str, actor=Depends(get_actor),
                       service=Depends(get_integration_service), module=Depends(get_module)):
    return service.run_contract_tests(integration_profile_id, actor, module)


@integration_router.post('/integrations/{integration_profile_id}/verify-endpoint')
def verify_endpoint(integration_profile_id: str, dto: EndpointVerifyDTO, actor=Depends(get_actor),
                    service=Depends(get_integration_service)):
    return service.verify_endpoint(integration_profile_id, actor, dto.notes).to_dict()


@integration_router.post('/integrations/{integration_profile_id}/approvals/{kind}')
def record_approval(integration_profile_id: str,
                    kind: Literal['SECURITY_REVIEW', 'AGENCY_APPROVAL', 'PROVIDER_APPROVAL',
                                  'DOCUMENTATION_VERIFICATION'],
                    dto: ApprovalDTO, actor=Depends(get_actor),
                    service=Depends(get_integration_service)):
    return service.record_approval(integration_profile_id, actor, kind, dto.reference,
                                   dto.notes, dto.expires_at)


@integration_router.post('/integrations/{integration_profile_id}/status')
def advance_status(integration_profile_id: str, dto: LifecycleActionDTO, actor=Depends(get_actor),
                   service=Depends(get_integration_service)):
    return service.advance_status(integration_profile_id, actor, dto.target_status,
                                  dto.reason).to_dict()


@integration_router.post('/integrations/{integration_profile_id}/activate')
def activate(integration_profile_id: str, dto: ReasonDTO, actor=Depends(get_actor),
             service=Depends(get_integration_service)):
    """Production activation. Re-checks every §7 requirement; there is no skip."""
    return service.activate_production(integration_profile_id, actor, dto.reason).to_dict()


@integration_router.post('/integrations/{integration_profile_id}/suspend')
def suspend(integration_profile_id: str, dto: ReasonDTO, actor=Depends(get_actor),
            service=Depends(get_integration_service)):
    return service.suspend(integration_profile_id, actor, dto.reason).to_dict()


@integration_router.post('/integrations/{integration_profile_id}/revoke')
def revoke(integration_profile_id: str, dto: ReasonDTO, actor=Depends(get_actor),
           service=Depends(get_integration_service)):
    return service.revoke(integration_profile_id, actor, dto.reason).to_dict()


@integration_router.get('/certificates')
def list_certificates(environment: IntegrationEnvironment | None = None, actor=Depends(get_actor),
                      service=Depends(get_integration_service)):
    return [c.to_dict() for c in service.list_certificates(actor, environment)]


@integration_router.post('/certificates')
def register_certificate(dto: CertificateRegisterDTO, actor=Depends(get_actor),
                         service=Depends(get_integration_service)):
    return service.register_certificate(actor, **dto.model_dump()).to_dict()


@integration_router.get('/endpoint-allowlist')
def list_allowlist(provider_id: str | None = None,
                   environment: IntegrationEnvironment | None = None,
                   actor=Depends(get_actor), service=Depends(get_integration_service)):
    return [e.to_dict() for e in service.list_allowlist(actor, provider_id, environment)]


@integration_router.post('/endpoint-allowlist')
def add_allowlist_entry(dto: AllowlistEntryDTO, actor=Depends(get_actor),
                        service=Depends(get_integration_service)):
    return service.add_allowlist_entry(actor, dto.provider_id, dto.environment, dto.url,
                                       dto.notes).to_dict()


@integration_router.get('/readiness')
def readiness(actor=Depends(get_actor), service=Depends(get_readiness_service)):
    """Stage 3 §30 deployment readiness dashboard."""
    return service.dashboard(actor)


@integration_router.get('/health/integrations')
def integration_health(actor=Depends(get_actor), service=Depends(get_readiness_service)):
    return service.health(actor)


# ------------------------------------------------- authorized sandbox (Stage 4)

class SandboxAuthorizationDTO(StrictModel):
    """The agency's record of a provider's written sandbox authorization.

    Every field is required because this record stands in for institutional
    paperwork. There is no partially-filled sandbox authorization.
    """
    provider_id: str = Field(min_length=1)
    documentation_reference: str = Field(min_length=1, max_length=400)
    documentation_source: str = Field(min_length=1, max_length=400)
    provider_contact: str = Field(min_length=1, max_length=400)
    base_url: str = Field(min_length=1, max_length=2048)
    allowed_paths: list[str] = Field(min_length=1, max_length=32)
    authentication_method: str = Field(min_length=1, max_length=80)
    credential_reference: str = Field(min_length=1, max_length=200)
    mapper_reference: str = Field(min_length=1, max_length=120)
    expires_at: datetime
    notes: str = Field(min_length=1, max_length=4000)
    client_certificate_reference: str | None = None
    tls_pin_sha256: str | None = None
    rate_limit_per_minute: int | None = Field(default=None, ge=1, le=10_000)
    max_response_bytes: int = Field(default=10 * 1024 * 1024, ge=1)
    request_timeout_seconds: float = Field(default=30.0, gt=0)


def get_sandbox_service(module=Depends(get_module)):
    return module.sandbox_authorizations


@integration_router.get('/sandbox-authorizations')
def list_sandbox_authorizations(provider_id: str | None = None, actor=Depends(get_actor),
                                service=Depends(get_sandbox_service)):
    return [r.to_dict() for r in service.list_authorizations(actor, provider_id)]


@integration_router.post('/sandbox-authorizations')
def record_sandbox_authorization(dto: SandboxAuthorizationDTO, actor=Depends(get_actor),
                                 service=Depends(get_sandbox_service)):
    """Record the paperwork. Starts PENDING; a separate activation enables traffic."""
    return service.record_authorization(actor, **dto.model_dump()).to_dict()


@integration_router.post('/sandbox-authorizations/{sandbox_authorization_id}/activate')
def activate_sandbox_authorization(sandbox_authorization_id: str, dto: ReasonDTO,
                                   actor=Depends(get_actor), service=Depends(get_sandbox_service)):
    return service.activate(sandbox_authorization_id, actor, dto.reason).to_dict()


@integration_router.post('/sandbox-authorizations/{sandbox_authorization_id}/suspend')
def suspend_sandbox_authorization(sandbox_authorization_id: str, dto: ReasonDTO,
                                  actor=Depends(get_actor), service=Depends(get_sandbox_service)):
    return service.suspend(sandbox_authorization_id, actor, dto.reason).to_dict()


@integration_router.post('/sandbox-authorizations/{sandbox_authorization_id}/revoke')
def revoke_sandbox_authorization(sandbox_authorization_id: str, dto: ReasonDTO,
                                 actor=Depends(get_actor), service=Depends(get_sandbox_service)):
    return service.revoke(sandbox_authorization_id, actor, dto.reason).to_dict()


@integration_router.get('/sandbox-authorizations/{sandbox_authorization_id}/exchanges')
def sandbox_exchanges(sandbox_authorization_id: str, actor=Depends(get_actor),
                      module=Depends(get_module)):
    """Hashes and safe metadata for every sandbox exchange. Never bodies."""
    module.service.access.administrator(actor)
    return module.repository.list_sandbox_exchanges(sandbox_authorization_id)


@integration_router.get('/evidence/{evidence_id}/provenance')
def evidence_provenance(evidence_id: str, actor=Depends(get_actor), module=Depends(get_module)):
    """Stage 3 §21: Evidence -> Response -> Transmission -> Request -> Authorization -> Case."""
    return module.provenance_service.get_evidence_provenance(evidence_id, actor)
