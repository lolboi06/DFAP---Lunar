"""
Secure File Transfer Connector for Lawful Data Request Module.
Simulates encrypted SFTP/MFT-style batch exchanges and controlled quarantine ingestion.
"""
import hashlib
import json
from typing import Dict, Any, Optional

from dfap.ldrm_subsystem.domain.enums import TransmissionMethod, TransmissionStatus, ProviderResponseStatus
from dfap.ldrm_subsystem.domain.response import ProviderResponse
from dfap.ldrm_subsystem.domain.utils import utc_now
from dfap.ldrm_subsystem.providers.connectors.base import (
    ProviderConnector, ConnectorCapabilities, SubmissionMode)

from dfap.ldrm_subsystem.integration.ingestion_adapter import IntegrationUnavailable

class SecureFileTransferConnector(ProviderConnector):
    """
    SFTP/MFT batch transfer connector.
    Packages canonical request payloads into encrypted test archives and manages
    quarantine intake for received provider response packages.
    """
    method = TransmissionMethod.SECURE_FILE_TRANSFER
    # Batch file exchange: no interactive status, responses arrive as files.
    CAPABILITIES = ConnectorCapabilities(
        submission_mode=SubmissionMode.AUTOMATIC, supports_status_polling=True,
        supports_webhooks=False, supports_response_download=True)

    def _submit(self, package, transmission, provider, request):
        destination = self.destination(provider)
        if not destination.address.startswith("sftp://sandbox") and not transmission.metadata.get("enable_test_transport"):
            raise IntegrationUnavailable('Secure file transfer is not connected; a reviewed test transport is required')
        
        tracking_ref = f"MFT-{hashlib.sha256(transmission.id.encode()).hexdigest()[:12].upper()}"
        transmission.provider_tracking_ref = tracking_ref
        transmission.transmission_status = TransmissionStatus.DELIVERED
        transmission.metadata.update({
            "test_only": True,
            "mft_reference": tracking_ref,
            "destination_id": destination.id,
            "destination": destination.address,
            "package_encrypted": True,
        })
        self.open_channel(transmission, status=ProviderResponseStatus.ACCEPTED)
        return transmission
