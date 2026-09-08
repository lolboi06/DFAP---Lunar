"""Preparation/tracking only; no browser, portal, courier or file-transfer automation."""
from dfap.ldrm_subsystem.domain.enums import TransmissionMethod, TransmissionStatus
from dfap.ldrm_subsystem.providers.connectors.base import (
    ProviderConnector, ConnectorCapabilities, SubmissionMode)
from dfap.ldrm_subsystem.integration.ingestion_adapter import IntegrationUnavailable


class ManualPortalConnector(ProviderConnector):
    method = TransmissionMethod.MANUAL_PORTAL
    preparation_status = TransmissionStatus.READY_FOR_MANUAL_SUBMISSION
    # Prepares a package for a human to submit; nothing is transmitted here.
    CAPABILITIES = ConnectorCapabilities(
        submission_mode=SubmissionMode.MANUAL, supports_status_polling=False,
        supports_webhooks=False, supports_response_download=False,
        requires_recorded_human_submission=True)

    def _submit(self, package, transmission, provider, request):
        destination = self.destination(provider)
        transmission.transmission_status = self.preparation_status
        transmission.metadata.update({'test_only': True, 'automatic_submission': False,
            'destination_id': destination.id, 'destination': destination.address, 'prepared_package_hash': package.sha256_hash})
        return transmission


class PhysicalSubmissionConnector(ManualPortalConnector):
    method = TransmissionMethod.PHYSICAL_SUBMISSION
    preparation_status = TransmissionStatus.READY_FOR_PHYSICAL_SUBMISSION
    physical_methods = {'REGISTERED_POST', 'COURIER', 'IN_PERSON', 'OFFLINE_MEDIA'}


class SecureFileTransferConnector(ProviderConnector):
    method = TransmissionMethod.SECURE_FILE_TRANSFER
    CAPABILITIES = ConnectorCapabilities(submission_mode=SubmissionMode.UNAVAILABLE,
                                         supports_status_polling=False, supports_response_download=False)

    def _submit(self, package, transmission, provider, request):
        raise IntegrationUnavailable('Secure file transfer is not connected; a reviewed test transport is required')
