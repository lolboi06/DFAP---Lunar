"""
Pydantic Schemas for Mock Provider REST API and Compliance Portal.
"""
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, ConfigDict

from dfap.mock_providers.domain.models import ProviderRequestStatus, ProviderUserRole


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ISPRequestCreateDTO(StrictModel):
    agency_request_reference: str = Field(min_length=1)
    agency_case_reference: str = Field(min_length=1)
    requested_categories: List[str] = Field(default_factory=list)
    date_range: Dict[str, Any] = Field(default_factory=dict)
    request_package_hash: str = Field(min_length=1)


class ClarificationQueryDTO(StrictModel):
    query_text: str = Field(min_length=1)


class RejectionDTO(StrictModel):
    reason: str = Field(min_length=1)


class CompleteRequestDTO(StrictModel):
    scenario: str = "VALID"  # VALID, PARTIAL, EMPTY, MALFORMED, TAMPERED
