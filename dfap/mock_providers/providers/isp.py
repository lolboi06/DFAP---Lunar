"""
Mock Provider B — ExampleNet ISP (IPDR).
Exposes a LOCAL MOCK REST API. Not accessible as a real-world provider integration.
"""
import uuid
from typing import Dict, Any, Optional

from dfap.mock_providers.domain.models import MockProviderRequest, ProviderRequestStatus, utc_now
from dfap.mock_providers.synthetic.generator import SyntheticDataGenerator
from dfap.mock_providers.transports.webhook_dispatcher import WebhookDispatcher


class MockISPProvider:
    PROVIDER_ID = "prov-isp-001"
    NAME = "ExampleNet ISP"
    TYPE = "ISP"
    PRIMARY_SUBMISSION = "OFFICIAL_API"
    DATASET = "IPDR"

    def __init__(self, repository, webhook_dispatcher: Optional[WebhookDispatcher] = None):
        self.repository = repository
        self.webhook_dispatcher = webhook_dispatcher or WebhookDispatcher(repository)

    def receive_api_request(
        self,
        agency_request_ref: str,
        agency_case_ref: str,
        requested_categories: list,
        date_range: dict,
        request_package_hash: str,
    ) -> Dict[str, Any]:
        prov_ref = f"ISP-{uuid.uuid4().hex[:8].upper()}"
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
            provider_notes="Received via local REST API endpoint /provider-api/v1/requests",
        )
        self.repository.save_request(req)
        return {
            "provider_reference": prov_ref,
            "status": ProviderRequestStatus.RECEIVED.value,
            "received_at": req.received_at,
        }

    def get_api_status(self, provider_request_id: str) -> Dict[str, Any]:
        req = self._must_get(provider_request_id)
        return {
            "provider_reference": req.provider_request_id,
            "status": req.status.value,
            "updated_at": req.updated_at,
        }

    def accept_for_review(self, provider_request_id: str) -> MockProviderRequest:
        req = self._must_get(provider_request_id)
        req.status = ProviderRequestStatus.UNDER_REVIEW
        req.updated_at = utc_now()
        self.repository.save_request(req)
        self.webhook_dispatcher.dispatch_event(req.provider_request_id, req.agency_request_reference, "ACKNOWLEDGED")
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
        
        target_ip = req.date_range.get("target_ip", SyntheticDataGenerator.DEMO_IP)
        payload_bytes = SyntheticDataGenerator.generate_ipdr_response(target_ip, scenario=scenario)
        
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
            raise KeyError(f"ISP provider request {provider_request_id} not found")
        return req
