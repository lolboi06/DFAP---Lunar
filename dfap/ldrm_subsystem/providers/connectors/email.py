"""Institutional-style email, captured locally. No SMTP/network transport exists."""
from abc import ABC, abstractmethod
import re
from dfap.ldrm_subsystem.domain.enums import TransmissionMethod, TransmissionStatus
from dfap.ldrm_subsystem.domain.utils import utc_now
from dfap.ldrm_subsystem.persistence.repositories import encode
from dfap.ldrm_subsystem.providers.connectors.base import (
    ProviderConnector, ConnectorCapabilities, SubmissionMode)


def validate_test_address(address):
    if not isinstance(address, str) or not re.fullmatch(r'[A-Za-z0-9.!#$%&\'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.(test|example|invalid)', address):
        raise ValueError('Only explicit reserved-domain test email addresses are permitted')


class EmailTransport(ABC):
    @abstractmethod
    def send(self, message):
        """Return normalized message_id, sent_at and delivery_status."""
        ...


class TestEmailTransport(EmailTransport):
    __test__ = False
    def __init__(self, repository):
        self.repository = repository

    def send(self, message):
        validate_test_address(message['sender'])
        validate_test_address(message['recipient'])
        message_id = f"<ldrm-{message['transmission_id']}@local.test>"
        try:
            existing = self.repository.get('test_email', message_id)
        except KeyError:
            existing = None
        if existing:
            if existing['message'] != message:
                raise ValueError('Email retry changed immutable message content')
            return existing['receipt']
        receipt = {'message_id': message_id, 'sent_at': utc_now().isoformat(), 'delivery_status': 'CAPTURED_TEST_ONLY'}
        self.repository.put('test_email', message_id, {'message': message, 'receipt': receipt}, message['request_id'], immutable=True)
        return receipt


class InstitutionalEmailConnector(ProviderConnector):
    method = TransmissionMethod.OFFICIAL_EMAIL
    # Institutional email submits, but cannot poll status or download a
    # response: the provider replies on its own schedule, into the inbox.
    CAPABILITIES = ConnectorCapabilities(
        submission_mode=SubmissionMode.AUTOMATIC, supports_status_polling=False,
        supports_webhooks=False, supports_response_download=False, supports_clarification=True)

    def __init__(self, *args, transport, **kwargs):
        super().__init__(*args, **kwargs)
        if type(transport) is not TestEmailTransport:
            raise ValueError('Only TestEmailTransport is enabled')
        self.transport = transport

    def _submit(self, package, transmission, provider, request):
        recipient = self.destination(provider)
        validate_test_address(recipient.address)
        try:
            sender = self.repository.get('email_sender', 'institution')
        except KeyError as error:
            raise ValueError('An authorized institutional test sender must be configured') from error
        if not sender.get('authorized_by') or not sender.get('identity', '').strip():
            raise ValueError('Institutional sender is not authorized')
        validate_test_address(sender['address'])
        subject = f'Authorized Data Request – {request.request_number}'
        body = (f'Dear Compliance/Nodal Officer,\n\n'
                f'Please find attached the authorized request associated with the referenced investigation.\n\n'
                f'Request Reference: {request.request_number}\nCase Reference: {request.case_id}\n'
                f'Request Category: {request.dataset_type.value}\nAuthority Reference: {request.authorization.authority_reference}\n\n'
                'The exact identifiers, requested records, and scope are contained in the signed request package.\n'
                "Please process the request according to the institution's applicable procedures and use the approved response channel.\n\n"
                f"Regards,\n{sender['identity']}\n")
        message = {'sender': sender['address'], 'recipient': recipient.address, 'subject': subject, 'body': body,
                   'request_id': request.id, 'transmission_id': transmission.id,
                   'attachments': [{'filename': 'request.json', 'content': package.canonical_json,
                                    'sha256': package.sha256_hash, 'content_type': 'application/json'},
                                   {'filename': 'authorization.json', 'content': encode(request.authorization),
                                    'content_type': 'application/json'}]}
        receipt = self.transport.send(message)
        transmission.provider_tracking_ref = receipt['message_id']
        transmission.transmission_status = TransmissionStatus.DELIVERED
        transmission.metadata.update({'test_only': True, 'destination_id': recipient.id, 'recipient': recipient.address,
                                       'sender': sender['address'], 'email_receipt': receipt})
        self.open_channel(transmission)
        return transmission
