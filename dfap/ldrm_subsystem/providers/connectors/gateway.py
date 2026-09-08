"""
Government Gateway Connector Abstraction for Lawful Data Request Module.
Simulates sandbox exchange with authorized government gateways.
"""
import hashlib
from typing import Dict, Any, Optional

from dfap.ldrm_subsystem.domain.enums import TransmissionMethod, TransmissionStatus, ProviderResponseStatus
from dfap.ldrm_subsystem.domain.response import ProviderResponse
from dfap.ldrm_subsystem.domain.utils import utc_now
from dfap.ldrm_subsystem.providers.connectors.base import (
    ProviderConnector, ConnectorCapabilities, SubmissionMode)

class GovernmentGatewayConnector(ProviderConnector):
    """
    Integration connector for state/national government exchange gateways.
    Operates in sandbox mode in test/dev environments.
    """
    method = TransmissionMethod.GOVERNMENT_GATEWAY
    # A gateway acknowledges and can be polled, but delivers responses through
    # its own channel rather than a direct download.
    CAPABILITIES = ConnectorCapabilities(
        submission_mode=SubmissionMode.AUTOMATIC, supports_status_polling=True,
        supports_webhooks=False, supports_response_download=False)

    def _submit(self, package, transmission, provider, request):
        destination = self.destination(provider)
        
        tracking_ref = f"GW-{hashlib.sha256(transmission.id.encode()).hexdigest()[:12].upper()}"
        transmission.provider_tracking_ref = tracking_ref
        transmission.transmission_status = TransmissionStatus.DELIVERED
        transmission.metadata.update({
            "test_only": True,
            "gateway_reference": tracking_ref,
            "destination_id": destination.id,
            "destination": destination.address,
        })
        self.open_channel(transmission, status=ProviderResponseStatus.ACCEPTED)
        return transmission
