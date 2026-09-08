"""
Mock Provider Adapter for Lawful Data Request Module.
Simulates provider responses in development and testing environments without connecting to real infrastructure.
"""
import hashlib
import json
from datetime import datetime, timezone
from typing import Dict, Any, Optional
import uuid

from dfap.ldrm_subsystem.providers.base import ProviderAdapter, ProviderDispatchError
from dfap.ldrm_subsystem.domain.transmission import RequestTransmission
from dfap.ldrm_subsystem.domain.response import ProviderResponse
from dfap.ldrm_subsystem.domain.enums import (
    TransmissionStatus,
    ProviderResponseStatus,
    DatasetType,
)

class MockProviderAdapter(ProviderAdapter):
    """
    Mock adapter that simulates transmission, acknowledgment, status checks,
    and synthetic dataset payloads for CDR, IPDR, BANK, and SOCIAL requests.
    """

    def __init__(self, repository):
        self.repository = repository

    @property
    def adapter_name(self):
        return "MockProviderAdapter"

    def dispatch(self, transmission, canonical_payload):
        # Transmission ID is the durable idempotency key; retries reuse it.
        tracking_ref = "MOCK-" + transmission.id
        try:
            state = self.repository.get("mock_provider", tracking_ref)
            if state["request_id"] != transmission.request_id or state["package_hash"] != transmission.package_payload_hash:
                raise ProviderDispatchError("Transmission retry changed its package")
        except KeyError:
            state = {"tracking_ref": tracking_ref, "request_id": transmission.request_id,
                     "transmission_id": transmission.id, "provider_id": transmission.provider_id,
                     "case_id": canonical_payload["case_id"], "dataset_type": canonical_payload["dataset_type"],
                     "targets": canonical_payload["targets"], "package_hash": transmission.package_payload_hash,
                     "status": ProviderResponseStatus.COMPLETED.value, "responses": {}}
            self.repository.put("mock_provider", tracking_ref, state, transmission.request_id)
        transmission.acknowledge(tracking_ref)
        transmission.metadata["simulated_by"] = self.adapter_name
        return transmission

    def configure_simulated_status(self, tracking_ref, status):
        with self.repository.transaction():
            state = self.repository.get("mock_provider", tracking_ref)
            state["status"] = ProviderResponseStatus(status).value
            self.repository.put("mock_provider", tracking_ref, state, state["request_id"])

    def configure_simulated_query(self, tracking_ref, query_text):
        with self.repository.transaction():
            state = self.repository.get("mock_provider", tracking_ref)
            state["status"] = ProviderResponseStatus.PROVIDER_QUERY.value
            state["query_text"] = query_text
            self.repository.put("mock_provider", tracking_ref, state, state["request_id"])

    def get_status(self, provider_tracking_ref):
        state = self.repository.get("mock_provider", provider_tracking_ref)
        return {"tracking_ref": provider_tracking_ref, "status": state["status"], "query_text": state.get("query_text")}

    def retrieve_response(self, provider_tracking_ref):
        from dfap.ldrm_subsystem.persistence.repositories import encode, hydrate
        with self.repository.transaction():
            state = self.repository.get("mock_provider", provider_tracking_ref)
            status = ProviderResponseStatus(state["status"])
            if status in (ProviderResponseStatus.ACCEPTED, ProviderResponseStatus.PROCESSING, ProviderResponseStatus.REJECTED):
                return None
            if status.value in state["responses"]:
                return hydrate(ProviderResponse, state["responses"][status.value])
            payload = self._generate_synthetic_payload(state["dataset_type"], state["targets"])
            if status == ProviderResponseStatus.PARTIAL_RESPONSE:
                payload["records"] = payload["records"][:1]
            raw = json.dumps(payload, sort_keys=True, indent=2).encode("utf-8")
            response = ProviderResponse(
                request_id=state["request_id"], provider_id=state["provider_id"], case_id=state["case_id"],
                transmission_id=state["transmission_id"], provider_status=status, raw_payload=raw,
                raw_payload_hash=hashlib.sha256(raw).hexdigest(),
                metadata={"tracking_ref": provider_tracking_ref, "dataset_type": state["dataset_type"], "simulated_provider": True})
            state["responses"][status.value] = json.loads(encode(response))
            self.repository.put("mock_provider", provider_tracking_ref, state, state["request_id"])
            return response

    def _generate_synthetic_payload(self, dataset_type: str, targets: list) -> Dict[str, Any]:
        """Generates realistic synthetic sample records for testing and verification."""
        target_val = targets[0].get("target_value", "UNKNOWN") if targets else "SAMPLE_TARGET"
        
        if dataset_type == DatasetType.CDR.value:
            return {
                "dataset_type": "CDR",
                "target": target_val,
                "records": [
                    {
                        "call_id": f"call-{uuid.uuid4().hex[:8]}",
                        "calling_number": target_val,
                        "called_number": "+919876543210",
                        "timestamp": "2026-09-01T10:30:00Z",
                        "duration_seconds": 124,
                        "call_type": "OUTGOING_VOICE",
                        "cell_tower_id": "TOWER-DEL-4021",
                    },
                    {
                        "call_id": f"call-{uuid.uuid4().hex[:8]}",
                        "calling_number": "+919123456780",
                        "called_number": target_val,
                        "timestamp": "2026-09-01T14:15:22Z",
                        "duration_seconds": 45,
                        "call_type": "INCOMING_VOICE",
                        "cell_tower_id": "TOWER-DEL-4021",
                    }
                ]
            }
        elif dataset_type == DatasetType.IPDR.value:
            return {
                "dataset_type": "IPDR",
                "target": target_val,
                "records": [
                    {
                        "session_id": f"sess-{uuid.uuid4().hex[:8]}",
                        "source_ip": target_val if "." in target_val else "192.168.1.100",
                        "destination_ip": "104.244.42.1",
                        "protocol": "TCP",
                        "source_port": 54321,
                        "destination_port": 443,
                        "bytes_up": 1420,
                        "bytes_down": 8940,
                        "start_time": "2026-09-01T08:00:00Z",
                        "end_time": "2026-09-01T08:12:00Z",
                    }
                ]
            }
        elif dataset_type == DatasetType.BANK.value:
            return {
                "dataset_type": "BANK",
                "target": target_val,
                "records": [
                    {
                        "txn_id": f"txn-{uuid.uuid4().hex[:8]}",
                        "account_number": target_val,
                        "counterparty_account": "ACC-9988776655",
                        "amount": 25000.00,
                        "currency": "INR",
                        "txn_type": "NEFT_CREDIT",
                        "timestamp": "2026-09-01T11:45:00Z",
                        "narration": "CONSULTING FEE REF 492",
                    }
                ]
            }
        elif dataset_type == DatasetType.SOCIAL.value:
            return {
                "dataset_type": "SOCIAL",
                "target": target_val,
                "records": [
                    {
                        "post_id": f"post-{uuid.uuid4().hex[:8]}",
                        "handle": target_val,
                        "action": "POST_STATUS",
                        "timestamp": "2026-09-01T15:20:00Z",
                        "content_summary": "Meeting scheduled for tonight.",
                    }
                ]
            }
        else:
            return {"dataset_type": dataset_type, "target": target_val, "records": []}
