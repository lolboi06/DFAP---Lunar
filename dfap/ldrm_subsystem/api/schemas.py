from dfap.ldrm_subsystem.domain.enums import ProviderResponseStatus, ProviderActiveStatus
"""
Pydantic Schemas for Lawful Data Request Module API.
"""
from typing import List, Optional, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict

class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


from dfap.ldrm_subsystem.domain.enums import (
    RequestStatus,
    AuthorityType,
    ProviderCategory,
    DatasetType,
    TargetType,
    Priority,
    TransmissionMethod,
)

class RequestTargetCreate(StrictModel):
    target_type: TargetType
    target_value: str
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    requested_categories: List[str] = Field(default_factory=list)
    justification: str = ""


class RequestTargetResponse(StrictModel):
    id: str
    target_type: str
    target_value: str
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    requested_categories: List[str] = Field(default_factory=list)
    justification: str = ""


class RequestCreate(StrictModel):
    scope: Dict[str, Any] = Field(default_factory=dict)
    case_id: str
    provider_id: str
    dataset_type: DatasetType
    targets: List[RequestTargetCreate]
    priority: Priority = Priority.ROUTINE
    assigned_to: Optional[str] = None


class RequestUpdate(StrictModel):
    expected_revision: int = Field(ge=1)
    scope: Optional[Dict[str, Any]] = None
    provider_id: Optional[str] = None
    dataset_type: Optional[DatasetType] = None
    targets: Optional[List[RequestTargetCreate]] = None
    priority: Optional[Priority] = None


class LegalReviewRequest(StrictModel):
    approved: bool
    notes: str


class AuthorizeRequestDTO(StrictModel):
    expected_version: int = Field(ge=1)
    expected_hash: str = Field(pattern="^[a-f0-9]{64}$")
    authority_type: AuthorityType
    authority_reference: str
    issuing_authority: str
    approved_scope_summary: str
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None


class SignRequestDTO(StrictModel):
    expected_hash: str = Field(pattern="^[a-f0-9]{64}$")


class DispatchRequestDTO(StrictModel):
    transmission_method: Optional[TransmissionMethod] = None


class ProviderDestinationDTO(StrictModel):
    id: str = Field(min_length=1)
    method: TransmissionMethod
    address: str = Field(min_length=1)


class ProviderCreateDTO(StrictModel):
    submission_methods: List[TransmissionMethod] = Field(default_factory=lambda: [TransmissionMethod.MOCK_DISPATCH])
    response_methods: List[str] = Field(default_factory=lambda: ['MOCK'])
    destinations: List[ProviderDestinationDTO] = Field(default_factory=list)
    endpoint_references: Dict[str, str] = Field(default_factory=dict)
    required_documents: List[str] = Field(default_factory=list)
    configuration_metadata: Dict[str, Any] = Field(default_factory=dict)
    name: str
    category: ProviderCategory
    supported_datasets: List[DatasetType]
    contact_details: Dict[str, Any] = Field(default_factory=dict)


class ProviderVerifyDTO(StrictModel):
    notes: Optional[str] = None


class LawfulDataRequestResponse(StrictModel):
    id: str
    case_id: str
    request_number: str
    provider_id: str
    dataset_type: str
    status: str
    priority: str
    targets: List[Dict[str, Any]]
    authorization: Optional[Dict[str, Any]] = None
    created_by: str
    assigned_to: Optional[str] = None
    canonical_hash: Optional[str] = None
    revision: int
    scope: Dict[str, Any]
    request_version: int
    created_at: str
    updated_at: str


class ActionDTO(StrictModel):
    notes: str = Field(min_length=1)


class VerifyResponseDTO(StrictModel):
    accept_partial: bool = False


class MockStatusDTO(StrictModel):
    status: ProviderResponseStatus


class ProviderQueryCreateDTO(StrictModel):
    query_text: str = Field(min_length=1)
    provider_id: str = Field(min_length=1)


class ProviderQueryResponseDTO(StrictModel):
    response_text: str = Field(min_length=1)
    scope_modified: bool = False


class DuplicateCheckDTO(StrictModel):
    provider_id: Optional[str] = None
    dataset_type: Optional[DatasetType] = None
    targets: List[Dict[str, Any]] = Field(default_factory=list)
    start_date: Optional[str] = None
    end_date: Optional[str] = None


class ScopeMinimizationDTO(StrictModel):
    requested_start: str
    requested_end: str
    investigative_start: Optional[str] = None
    investigative_end: Optional[str] = None


class ManualSubmissionDTO(StrictModel):
    tracking_ref: str = Field(min_length=1)
    submission_notes: Optional[str] = None
    date_submitted: Optional[str] = None


class ProviderUpdateDTO(StrictModel):
    submission_methods: Optional[List[TransmissionMethod]] = None
    response_methods: Optional[List[str]] = None
    destinations: Optional[List[ProviderDestinationDTO]] = None
    endpoint_references: Optional[Dict[str, str]] = None
    required_documents: Optional[List[str]] = None
    configuration_metadata: Optional[Dict[str, Any]] = None
    name: Optional[str] = None
    category: Optional[ProviderCategory] = None
    supported_datasets: Optional[List[DatasetType]] = None
    contact_details: Optional[Dict[str, Any]] = None
    active_status: Optional[ProviderActiveStatus] = None


