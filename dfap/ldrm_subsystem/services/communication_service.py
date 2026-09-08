"""Administrative/test communication entry points reuse existing lifecycle services."""
from dfap.ldrm_subsystem.persistence.unit_of_work import atomic
from dfap.ldrm_subsystem.providers.replies import ProviderReplyReceiver
from dfap.ldrm_subsystem.providers.connectors.email import validate_test_address
from dfap.ldrm_subsystem.domain.utils import utc_now
from dfap.ldrm_subsystem.domain.enums import TransmissionMethod


class CommunicationService:
    def __init__(self, service, demo_mode=False):
        self.service, self.demo_mode = service, demo_mode
        self.repository, self.access, self.audit_adapter = service.repository, service.access, service.audit_adapter
        self.receiver = ProviderReplyReceiver(self.repository, service.provider_registry, self.audit_adapter, service.response_service.max_size)

    def require_demo(self):
        if not self.demo_mode:
            raise PermissionError('Provider communication controls are TEST/MOCK ONLY in this phase')

    @atomic
    def configure_sender(self, actor_id, address, identity):
        self.require_demo()
        self.access.administrator(actor_id)
        validate_test_address(address)
        if not identity.strip() or any(ord(c) < 32 for c in identity):
            raise ValueError('A valid institutional identity is required')
        sender = {'address': address, 'identity': identity, 'authorized_by': actor_id, 'authorized_at': utc_now().isoformat()}
        self.repository.put('email_sender', 'institution', sender)
        self.audit_adapter.log_event('TEST_SENDER_CONFIGURED', 'Communication', 'institution', actor_id, sender)
        return sender

    @atomic
    def configure_callback_key(self, provider_id, actor_id, secret):
        self.require_demo()
        self.access.administrator(actor_id)
        self.service.provider_registry._get(provider_id)
        if len(secret) < 32:
            raise ValueError('An explicit test callback key of at least 32 characters is required')
        self.repository.put('callback_key', provider_id, {'secret': secret})
        self.audit_adapter.log_event('TEST_CALLBACK_KEY_CONFIGURED', 'Provider', provider_id, actor_id)
        return {'provider_id': provider_id, 'configured': True}

    @atomic
    def record_submission(self, request_id, actor_id, **details):
        self.require_demo()
        request = self.service._get(request_id, actor_id, 'DISPATCH_REQUEST')
        result = self.service.dispatch_service.record_submission(request, actor_id, **details)
        self.repository.save_request(request)
        return result

    def preparations(self, request_id, actor_id):
        self.service.get_request(request_id, actor_id)
        return self.repository.list('submission_preparation', request_id=request_id)

    def captured_messages(self, request_id, actor_id):
        self.require_demo()
        self.service.get_request(request_id, actor_id)
        return self.repository.list('test_email', request_id=request_id)

    def quarantine_records(self, request_id, actor_id):
        self.service.get_request(request_id, actor_id)
        import json
        with self.repository.lock:
            return [{'id': row['id'], **json.loads(row['metadata'])} for row in self.repository.connection.execute(
                'SELECT id,metadata FROM quarantine WHERE request_id=?', (request_id,))]

    @atomic
    def accept_test_reply(self, provider_id, event, actor_id):
        self.require_demo()
        self.service._get(event['request_id'], actor_id, 'RECEIVE_RESPONSE')
        return self.receiver.accept(provider_id, event, actor_id)

    def accept_callback(self, provider_id, event, raw_body, signature):
        self.require_demo()
        try:
            return self.receiver.accept(provider_id, event, 'provider:' + provider_id, webhook=True, raw_body=raw_body, signature=signature)
        except (PermissionError, ValueError) as error:
            self.audit_adapter.log_security_violation('Provider callback rejected', 'provider:' + provider_id,
                                                     {'error_type': type(error).__name__})
            raise

    @atomic
    def configure_api_status(self, request_id, actor_id, status):
        self.require_demo()
        self.access.administrator(actor_id)
        request = self.service._get(request_id, actor_id, 'RECEIVE_RESPONSE')
        transmission = self.service.response_service.transmission(request)
        if transmission.transmission_method != TransmissionMethod.OFFICIAL_API:
            raise ValueError('Request was not sent to the local mock API')
        self.service.dispatch_service.connectors.local_api.configure_status(transmission.provider_tracking_ref, status)
        self.audit_adapter.log_event('LOCAL_API_STATUS_SET', 'LawfulDataRequest', request.id, actor_id, {'status': status.value})
