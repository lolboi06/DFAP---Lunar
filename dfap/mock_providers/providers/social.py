"""
Mock Provider D — Example Social (SOCIAL).
Supports both MOCK REST API and compliance portal submissions for SOCIAL dataset.
"""
import uuid
from typing import Dict, Any, Optional

from dfap.mock_providers.domain.models import MockProviderRequest, ProviderRequestStatus, utc_now
from dfap.mock_providers.synthetic.generator import SyntheticDataGenerator
from dfap.mock_providers.transports.webhook_dispatcher import WebhookDispatcher


class MockSocialProvider:
    PROVIDER_ID = "prov-social-001"
    NAME = "Example Social"
    TYPE = "SOCIAL_PLATFORM"
    PRIMARY_SUBMISSION = "OFFICIAL_API"
    SECONDARY_SUBMISSION = "PROVIDER_PORTAL"
    DATASET = "SOCIAL"

    def __init__(self, repository, webhook_dispatcher: Optional[WebhookDispatcher] = None):
        self.repository = repository
        self.webhook_dispatcher = webhook_dispatcher or WebhookDispatcher(repository)

    def receive_request(
        self,
        agency_request_ref: str,
        agency_case_ref: str,
        requested_categories: list,
        date_range: dict,
        request_package_hash: str,
    ) -> MockProviderRequest:
        prov_ref = f"SOC-{uuid.uuid4().hex[:8].upper()}"
        req = MockProviderRequest(
            provider_request_id=prov_ref,
            agency_request_reference=agency_request_ref,
            agency_case_reference=agency_case_ref,
            provider_id=self.PROVIDER_ID,
            dataset_type=self.DATASET,
            requested_record_categories=requested_categories,
            date_range=date_range,
            status=ProviderRequestStatus.RECEIVED,
            request_package_hash=request_package_hash,
            provider_notes="Received via Example Social law-enforcement portal",
        )
        self.repository.save_request(req)
        return req

    def start_processing(self, provider_request_id: str) -> MockProviderRequest:
        req = self._must_get(provider_request_id)
        req.status = ProviderRequestStatus.PROCESSING
        req.updated_at = utc_now()
        self.repository.save_request(req)
        self.webhook_dispatcher.dispatch_event(req.provider_request_id, req.agency_request_reference, "PROCESSING")
        return req

    def complete_request(self, provider_request_id: str, scenario: str = "VALID") -> Dict[str, Any]:
        req = self._must_get(provider_request_id)
        req.status = ProviderRequestStatus.COMPLETED
        req.updated_at = utc_now()
        self.repository.save_request(req)
        
        target_handle = req.date_range.get("target_handle", SyntheticDataGenerator.DEMO_SOCIAL_HANDLE)
        payload_bytes = SyntheticDataGenerator.generate_social_response(target_handle, scenario=scenario)
        
        evt = self.webhook_dispatcher.dispatch_event(
            req.provider_request_id,
            req.agency_request_reference,
            "COMPLETED",
            payload={"scenario": scenario},
        )
        return {
            "provider_request": req,
            "raw_payload": payload_bytes,
            "webhook": evt,
        }

    def _must_get(self, provider_request_id: str) -> MockProviderRequest:
        req = self.repository.get_request(provider_request_id)
        if not req:
            raise KeyError(f"Social provider request {provider_request_id} not found")
        return req
