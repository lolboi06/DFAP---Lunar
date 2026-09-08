"""
FastAPI Router for Mock Provider Subsystem.
Exposes independent compliance endpoints for Bank, ISP, Telecom, and Social platforms.
Enforces provider-side role isolation (PROVIDER_REVIEWER / PROVIDER_SUPERVISOR).
"""
from fastapi import APIRouter, Depends, HTTPException, Header, Response
from typing import Optional, List, Dict, Any

from dfap.mock_providers.domain.models import ProviderUserRole
from dfap.mock_providers.persistence.repository import MockProviderRepository
from dfap.mock_providers.providers.bank import MockBankProvider
from dfap.mock_providers.providers.isp import MockISPProvider
from dfap.mock_providers.providers.telecom import MockTelecomProvider
from dfap.mock_providers.providers.social import MockSocialProvider
from dfap.mock_providers.api.schemas import ISPRequestCreateDTO, ClarificationQueryDTO, RejectionDTO, CompleteRequestDTO


router = APIRouter(prefix="/provider-api/v1", tags=["Mock Provider Ecosystem"])


def assert_demonstration_mode() -> None:
    """The synthetic provider ecosystem must never run outside demonstration mode.

    `create_app` only mounts this router in demonstration mode; this is the
    second, independent check so importing and calling the subsystem directly
    cannot bring synthetic providers into a production deployment.
    """
    from dfap.ldrm_subsystem.config import LDRMConfig
    if not LDRMConfig().demonstration_mode:
        raise RuntimeError(
            "The mock provider ecosystem is available only in demonstration mode "
            "(set DFAP_DEMO_MODE=true or LDRM_DEMO_MODE=true)")


# Provider-side state. Isolated from the agency database by construction: a
# separate repository, a separate schema and a separate connection.
mock_repo = MockProviderRepository()
bank_provider = MockBankProvider(mock_repo)
isp_provider = MockISPProvider(mock_repo)
telecom_provider = MockTelecomProvider(mock_repo)
social_provider = MockSocialProvider(mock_repo)


def get_provider_role(x_provider_role: Optional[str] = Header(None)) -> str:
    """Verifies that the request comes from an authorized provider user."""
    if not x_provider_role or x_provider_role not in (ProviderUserRole.PROVIDER_REVIEWER.value, ProviderUserRole.PROVIDER_SUPERVISOR.value):
        raise HTTPException(status_code=403, detail="Provider-side authentication required: Invalid or missing X-Provider-Role header")
    return x_provider_role


@router.get("/requests")
def list_provider_requests(provider_id: Optional[str] = None, role: str = Depends(get_provider_role)):
    return [r.to_dict() for r in mock_repo.list_requests(provider_id)]


@router.get("/requests/{provider_request_id}")
def get_provider_request(provider_request_id: str, role: str = Depends(get_provider_role)):
    req = mock_repo.get_request(provider_request_id)
    if not req:
        raise HTTPException(status_code=404, detail="Provider request not found")
    return req.to_dict()


@router.post("/requests/isp/submit")
def submit_isp_request(dto: ISPRequestCreateDTO):
    """Local REST API endpoint for ExampleNet ISP."""
    return isp_provider.receive_api_request(
        agency_request_ref=dto.agency_request_reference,
        agency_case_ref=dto.agency_case_reference,
        requested_categories=dto.requested_categories,
        date_range=dto.date_range,
        request_package_hash=dto.request_package_hash,
    )


@router.get("/requests/isp/{provider_request_id}/status")
def get_isp_request_status(provider_request_id: str):
    """Local GET status polling endpoint for ExampleNet ISP."""
    try:
        return isp_provider.get_api_status(provider_request_id)
    except KeyError as err:
        raise HTTPException(status_code=404, detail=str(err))


@router.post("/requests/{provider_request_id}/accept")
def accept_for_review(provider_request_id: str, role: str = Depends(get_provider_role)):
    req = mock_repo.get_request(provider_request_id)
    if not req:
        raise HTTPException(status_code=404, detail="Provider request not found")
    if req.provider_id == MockBankProvider.PROVIDER_ID:
        return bank_provider.accept_for_review(provider_request_id, reviewer=f"role:{role}").to_dict()
    elif req.provider_id == MockISPProvider.PROVIDER_ID:
        return isp_provider.accept_for_review(provider_request_id).to_dict()
    else:
        req.status = "UNDER_REVIEW"
        mock_repo.save_request(req)
        return req.to_dict()


@router.post("/requests/{provider_request_id}/clarification")
def request_clarification(provider_request_id: str, dto: ClarificationQueryDTO, role: str = Depends(get_provider_role)):
    req = mock_repo.get_request(provider_request_id)
    if not req:
        raise HTTPException(status_code=404, detail="Provider request not found")
    if req.provider_id == MockBankProvider.PROVIDER_ID:
        return bank_provider.request_clarification(provider_request_id, query_text=dto.query_text, reviewer=f"role:{role}").to_dict()
    else:
        req.status = "CLARIFICATION_REQUIRED"
        req.provider_notes = dto.query_text
        mock_repo.save_request(req)
        return req.to_dict()


@router.post("/requests/{provider_request_id}/reject")
def reject_request(provider_request_id: str, dto: RejectionDTO, role: str = Depends(get_provider_role)):
    req = mock_repo.get_request(provider_request_id)
    if not req:
        raise HTTPException(status_code=404, detail="Provider request not found")
    if req.provider_id == MockBankProvider.PROVIDER_ID:
        return bank_provider.reject(provider_request_id, reason=dto.reason, reviewer=f"role:{role}").to_dict()
    else:
        req.status = "REJECTED"
        req.provider_notes = dto.reason
        mock_repo.save_request(req)
        return req.to_dict()


@router.post("/requests/{provider_request_id}/process")
def start_processing(provider_request_id: str, role: str = Depends(get_provider_role)):
    req = mock_repo.get_request(provider_request_id)
    if not req:
        raise HTTPException(status_code=404, detail="Provider request not found")
    if req.provider_id == MockBankProvider.PROVIDER_ID:
        return bank_provider.start_processing(provider_request_id).to_dict()
    elif req.provider_id == MockISPProvider.PROVIDER_ID:
        return isp_provider.start_processing(provider_request_id).to_dict()
    elif req.provider_id == MockTelecomProvider.PROVIDER_ID:
        return telecom_provider.start_processing(provider_request_id).to_dict()
    else:
        return social_provider.start_processing(provider_request_id).to_dict()


@router.post("/requests/{provider_request_id}/complete")
def complete_request(provider_request_id: str, dto: CompleteRequestDTO, role: str = Depends(get_provider_role)):
    req = mock_repo.get_request(provider_request_id)
    if not req:
        raise HTTPException(status_code=404, detail="Provider request not found")
    if req.provider_id == MockBankProvider.PROVIDER_ID:
        res = bank_provider.complete_request(provider_request_id, scenario=dto.scenario)
    elif req.provider_id == MockISPProvider.PROVIDER_ID:
        res = isp_provider.complete_request(provider_request_id, scenario=dto.scenario)
    elif req.provider_id == MockTelecomProvider.PROVIDER_ID:
        res = telecom_provider.complete_request(provider_request_id, scenario=dto.scenario)
    else:
        res = social_provider.complete_request(provider_request_id, scenario=dto.scenario)
    
    return {
        "provider_request": res["provider_request"].to_dict(),
        "webhook_signature": res["webhook"]["signature"],
        "raw_payload_size": len(res["raw_payload"]),
    }


@router.get("/inbox")
def list_provider_inbox(destination: Optional[str] = None, role: str = Depends(get_provider_role)):
    return mock_repo.list_inbox_messages(destination)


@router.get("/webhooks")
def list_webhooks(agency_ref: Optional[str] = None, role: str = Depends(get_provider_role)):
    return mock_repo.list_webhooks(agency_ref)
