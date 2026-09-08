"""
Signed Local Webhook Dispatcher with HMAC-SHA256 and Replay Protection.
Simulates provider status callbacks back to LDRM webhook receivers.
"""
import hmac
import hashlib
import json
import uuid
from typing import Dict, Any, Optional

from dfap.mock_providers.domain.models import utc_now


class WebhookDispatcher:
    def __init__(self, repository, webhook_secret: str = "test-webhook-secret-key-32bytes!"):
        self.repository = repository
        self.webhook_secret = webhook_secret.encode("utf-8")

    def dispatch_event(
        self,
        provider_ref: str,
        agency_ref: str,
        event_type: str,
        payload: Optional[Dict[str, Any]] = None,
        event_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Dispatches a signed local webhook event.
        Logs event in mock repository with HMAC-SHA256 signature for replay protection verification.
        """
        evt_id = event_id or f"EVT-{uuid.uuid4().hex[:12]}"
        now = utc_now()
        data = {
            "event_id": evt_id,
            "provider_reference": provider_ref,
            "agency_request_reference": agency_ref,
            "event_type": event_type,
            "timestamp": now,
            "payload": payload or {},
        }
        
        raw_bytes = json.dumps(data, sort_keys=True).encode("utf-8")
        signature = hmac.new(self.webhook_secret, raw_bytes, hashlib.sha256).hexdigest()

        # Log event in mock provider repository
        self.repository.record_webhook(
            event_id=evt_id,
            provider_ref=provider_ref,
            agency_ref=agency_ref,
            event_type=event_type,
            timestamp=now,
            signature=signature,
            payload=data,
        )

        return {
            "event": data,
            "signature": signature,
            "raw_bytes": raw_bytes,
        }

    def verify_signature(self, raw_bytes: bytes, signature_hex: str) -> bool:
        """Verifies HMAC-SHA256 webhook signature against test secret."""
        expected = hmac.new(self.webhook_secret, raw_bytes, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature_hex)
