"""
Mock Provider A — Example National Bank (BANK).
Supports OFFICIAL_EMAIL & PROVIDER_PORTAL submission methods.
"""
import uuid
from typing import Dict, Any, Optional

from dfap.mock_providers.domain.models import MockProviderRequest, ProviderRequestStatus, utc_now
from dfap.mock_providers.synthetic.generator import SyntheticDataGenerator
from dfap.mock_providers.transports.webhook_dispatcher import WebhookDispatcher


class MockBankProvider:
    PROVIDER_ID = "prov-bank-001"
    NAME = "Example National Bank"
    TYPE = "BANK"
    PRIMARY_SUBMISSION = "OFFICIAL_EMAIL"
    DEMO_PORTAL = "PROVIDER_PORTAL"
    DATASET = "BANK"

    def __init__(self, repository, webhook_dispatcher: Optional[WebhookDispatcher] = None):
        self.repository = repository
        self.webhook_dispatcher = webhook_dispatcher or WebhookDispatcher(repository)

    def receive_request(
        self,
        agency_request_ref: str,
        agency_case_ref: str,
        requested_record_categories: list,
        date_range: dict,
        request_package_hash: str,
        sender: str = "requests@dfap.test",
    ) -> MockProviderRequest:
        prov_ref = f"BANK-{uuid.uuid4().hex[:8].upper()}"
        req = MockProviderRequest(
            provider_request_id=prov_ref,
            agency_request_reference=agency_request_ref,
            agency_case_reference=agency_case_ref,
            provider_id=self.PROVIDER_ID,
            dataset_type=self.DATASET,
            requested_record_categories=requested_record_categories,
            date_range=date_range,
            status=ProviderRequestStatus.RECEIVED,
            request_package_hash=request_package_hash,
            provider_notes="Incoming request received via institutional email",
        )
        self.repository.save_request(req)
        
        # Log email in simulated inbox
        self.repository.save_inbox_message({
            "message_id": f"MSG-BANK-{uuid.uuid4().hex[:8]}",
            "sender": sender,
            "destination": "compliance@example-bank.test",
            "subject": f"Authorized Data Request – {agency_request_ref} / {agency_case_ref}",
            "sent_at": utc_now(),
            "agency_request_reference": agency_request_ref,
            "package_hash": request_package_hash,
            "attachments": [{"filename": f"{agency_request_ref}-Signed.pdf", "hash": request_package_hash}],
        })
        return req

    def accept_for_review(self, provider_request_id: str, reviewer: str = "bank.compliance.officer") -> MockProviderRequest:
        req = self._must_get(provider_request_id)
        req.status = ProviderRequestStatus.UNDER_REVIEW
        req.provider_notes = f"Accepted for review by {reviewer}"
        req.updated_at = utc_now()
        self.repository.save_request(req)
        self.webhook_dispatcher.dispatch_event(req.provider_request_id, req.agency_request_reference, "ACKNOWLEDGED")
        return req

    def request_clarification(self, provider_request_id: str, query_text: str, reviewer: str = "bank.compliance.officer") -> MockProviderRequest:
        req = self._must_get(provider_request_id)
        req.status = ProviderRequestStatus.CLARIFICATION_REQUIRED
        req.provider_notes = f"Clarification requested by {reviewer}: {query_text}"
        req.updated_at = utc_now()
        self.repository.save_request(req)
        self.webhook_dispatcher.dispatch_event(
            req.provider_request_id,
            req.agency_request_reference,
            "PROVIDER_QUERY",
            payload={"query_text": query_text},
        )
        return req

    def reject(self, provider_request_id: str, reason: str, reviewer: str = "bank.compliance.officer") -> MockProviderRequest:
        req = self._must_get(provider_request_id)
        req.status = ProviderRequestStatus.REJECTED
        req.provider_notes = f"Request rejected by {reviewer}: {reason}"
        req.updated_at = utc_now()
        self.repository.save_request(req)
        self.webhook_dispatcher.dispatch_event(
            req.provider_request_id,
            req.agency_request_reference,
            "REJECTED",
            payload={"reason": reason},
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
        
        target_acc = req.date_range.get("target_account", SyntheticDataGenerator.DEMO_BANK_ACC)
        payload_bytes = SyntheticDataGenerator.generate_bank_response(target_acc, scenario=scenario)
        
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
            raise KeyError(f"Bank provider request {provider_request_id} not found")
        return req
