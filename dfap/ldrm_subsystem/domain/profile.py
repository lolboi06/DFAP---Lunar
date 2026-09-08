"""
Domain Entities for Provider Integration Profiles, Certificate Metadata,
Certification Records, and Endpoint Allowlists (DFAP Stage 3).
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Any, Optional
import uuid

from dfap.ldrm_subsystem.domain.enums import (
    IntegrationEnvironment,
    ProviderIntegrationStatus,
    TransmissionMethod,
    DatasetType,
    CertificationResult,
    CertificateType,
)
from dfap.ldrm_subsystem.domain.utils import utc_now


@dataclass
class CertificateMetadata:
    certificate_reference: str
    certificate_type: CertificateType
    issuer: str
    fingerprint: str
    valid_from: datetime
    valid_until: datetime
    status: str = "ACTIVE"
    environment: IntegrationEnvironment = IntegrationEnvironment.SANDBOX
    created_at: datetime = field(default_factory=utc_now)

    @property
    def is_valid(self) -> bool:
        now = utc_now()
        return (
            self.status == "ACTIVE"
            and self.valid_from <= now <= self.valid_until
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "certificate_reference": self.certificate_reference,
            "certificate_type": getattr(self.certificate_type, "value", str(self.certificate_type)),
            "issuer": self.issuer,
            "fingerprint": self.fingerprint,
            "valid_from": self.valid_from.isoformat(),
            "valid_until": self.valid_until.isoformat(),
            "status": self.status,
            "environment": getattr(self.environment, "value", str(self.environment)),
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class IntegrationCertificationRecord:
    certification_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    integration_profile_id: str = ""
    test_suite_version: str = "v1.0"
    tested_at: datetime = field(default_factory=utc_now)
    tested_by: str = ""
    tests_passed: int = 0
    tests_failed: int = 0
    result: CertificationResult = CertificationResult.FAIL
    report_reference: str = ""
    security_review_reference: Optional[str] = None
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "certification_id": self.certification_id,
            "integration_profile_id": self.integration_profile_id,
            "test_suite_version": self.test_suite_version,
            "tested_at": self.tested_at.isoformat(),
            "tested_by": self.tested_by,
            "tests_passed": self.tests_passed,
            "tests_failed": self.tests_failed,
            "result": getattr(self.result, "value", str(self.result)),
            "report_reference": self.report_reference,
            "security_review_reference": self.security_review_reference,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
        }


@dataclass
class EndpointAllowlistEntry:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    provider_id: str = ""
    environment: IntegrationEnvironment = IntegrationEnvironment.SANDBOX
    url: str = ""
    verified_by: str = ""
    verified_at: datetime = field(default_factory=utc_now)
    is_active: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "provider_id": self.provider_id,
            "environment": getattr(self.environment, "value", str(self.environment)),
            "url": self.url,
            "verified_by": self.verified_by,
            "verified_at": self.verified_at.isoformat(),
            "is_active": self.is_active,
        }


@dataclass
class ProviderIntegrationProfile:
    """
    Production-grade ProviderIntegrationProfile establishing formal environment,
    transmission methods, secret/certificate references, and lifecycle verification.
    """
    integration_profile_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    provider_id: str = ""
    environment: IntegrationEnvironment = IntegrationEnvironment.MOCK
    submission_method: TransmissionMethod = TransmissionMethod.MOCK_DISPATCH
    response_method: str = "MOCK"
    supported_dataset_types: List[DatasetType] = field(default_factory=list)
    supported_request_categories: List[str] = field(default_factory=list)
    endpoint_reference: str = ""
    endpoint_verification_status: str = "UNVERIFIED"
    authentication_type: str = "HMAC_SECRET"
    credential_reference: str = ""
    client_certificate_reference: Optional[str] = None
    signing_certificate_reference: Optional[str] = None
    required_documents: List[str] = field(default_factory=list)
    required_fields: List[str] = field(default_factory=list)
    accepted_request_formats: List[str] = field(default_factory=lambda: ["application/json"])
    accepted_response_formats: List[str] = field(default_factory=lambda: ["application/json"])
    webhook_enabled: bool = False
    webhook_reference: Optional[str] = None
    integration_status: ProviderIntegrationStatus = ProviderIntegrationStatus.DRAFT
    verified_by: Optional[str] = None
    verified_at: Optional[datetime] = None
    last_reviewed_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    @property
    def is_production(self) -> bool:
        return self.environment == IntegrationEnvironment.PRODUCTION

    @property
    def is_active(self) -> bool:
        return self.integration_status in {
            ProviderIntegrationStatus.PRODUCTION_ACTIVE,
            ProviderIntegrationStatus.SANDBOX_CONFIGURED,
            ProviderIntegrationStatus.CONTRACT_TESTED,
            ProviderIntegrationStatus.SECURITY_REVIEWED,
            ProviderIntegrationStatus.AGENCY_APPROVED,
            ProviderIntegrationStatus.PROVIDER_APPROVED,
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "integration_profile_id": self.integration_profile_id,
            "provider_id": self.provider_id,
            "environment": getattr(self.environment, "value", str(self.environment)),
            "submission_method": getattr(self.submission_method, "value", str(self.submission_method)),
            "response_method": self.response_method,
            "supported_dataset_types": [getattr(d, "value", str(d)) for d in self.supported_dataset_types],
            "supported_request_categories": self.supported_request_categories,
            "endpoint_reference": self.endpoint_reference,
            "endpoint_verification_status": self.endpoint_verification_status,
            "authentication_type": self.authentication_type,
            "credential_reference": self.credential_reference,
            "client_certificate_reference": self.client_certificate_reference,
            "signing_certificate_reference": self.signing_certificate_reference,
            "required_documents": self.required_documents,
            "required_fields": self.required_fields,
            "accepted_request_formats": self.accepted_request_formats,
            "accepted_response_formats": self.accepted_response_formats,
            "webhook_enabled": self.webhook_enabled,
            "webhook_reference": self.webhook_reference,
            "integration_status": getattr(self.integration_status, "value", str(self.integration_status)),
            "verified_by": self.verified_by,
            "verified_at": self.verified_at.isoformat() if self.verified_at else None,
            "last_reviewed_at": self.last_reviewed_at.isoformat() if self.last_reviewed_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }
