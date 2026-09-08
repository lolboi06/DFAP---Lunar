"""
Mock Provider C — Example Telecom (CDR & IPDR).
Supports PROVIDER_PORTAL & REGISTERED_POST physical submission workflows.
"""
import uuid
from typing import Dict, Any, Optional

from dfap.mock_providers.domain.models import MockProviderRequest, ProviderRequestStatus, utc_now
from dfap.mock_providers.synthetic.generator import SyntheticDataGenerator
from dfap.mock_providers.transports.webhook_dispatcher import WebhookDispatcher


class MockTelecomProvider:
    PROVIDER_ID = "prov-telecom-001"
    NAME = "Example Telecom"
    TYPE = "TELECOM"
    PRIMARY_SUBMISSION = "PROVIDER_PORTAL"
    SECONDARY_SUBMISSION = "REGISTERED_POST"
    DATASETS = ["CDR", "IPDR"]

    def __init__(self, repository, webhook_dispatcher: Optional[WebhookDispatcher] = None):
        self.repository = repository
        self.webhook_dispatcher = webhook_dispatcher or WebhookDispatcher(repository)

    def receive_portal_submission(
        self,
        agency_request_ref: str,
        agency_case_ref: str,
        requested_categories: list,
        date_range: dict,
        request_package_hash: str,
        dataset_type: str = "CDR",
    ) -> MockProviderRequest:
        prov_ref = f"TEL-{uuid.uuid4().hex[:8].upper()}"
        req = MockProviderRequest(
            provider_request_id=prov_ref,
            agency_request_reference=agency_request_ref,
            agency_case_reference=agency_case_ref,
            provider_id=self.PROVIDER_ID,
            dataset_type=dataset_type,
            requested_record_categories=requested_categories,
            date_range=date_range,
            status=ProviderRequestStatus.RECEIVED,
            request_package_hash=request_package_hash,
            provider_notes="Submitted via Example Telecom compliance portal",
        )
        self.repository.save_request(req)
        return req

    def receive_physical_post(
        self,
        agency_request_ref: str,
        agency_case_ref: str,
        tracking_number: str,
        receipt_reference: str,
        request_package_hash: str,
        dataset_type: str = "CDR",
    ) -> MockProviderRequest:
        prov_ref = f"TEL-POST-{uuid.uuid4().hex[:8].upper()}"
        req = MockProviderRequest(
            provider_request_id=prov_ref,
            agency_request_reference=agency_request_ref,
            agency_case_reference=agency_case_ref,
            provider_id=self.PROVIDER_ID,
            dataset_type=dataset_type,
            status=ProviderRequestStatus.RECEIVED,
            request_package_hash=request_package_hash,
            provider_notes=f"Physical post received. Tracking: {tracking_number}, Receipt: {receipt_reference}",
        )
        self.repository.save_request(req)
        # Dispatch physical post acknowledgement
        self.webhook_dispatcher.dispatch_event(
            prov_ref,
            agency_request_ref,
            "ACKNOWLEDGED",
            payload={"tracking_number": tracking_number, "physical_method": "REGISTERED_POST"},
        )
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
        
        target_phone = req.date_range.get("target_phone", SyntheticDataGenerator.DEMO_PHONE)
        payload_bytes = SyntheticDataGenerator.generate_cdr_response(target_phone, scenario=scenario)
        
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
            raise KeyError(f"Telecom provider request {provider_request_id} not found")
        return req
