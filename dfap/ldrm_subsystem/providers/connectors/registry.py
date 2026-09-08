"""Select communication connectors without leaking them into RequestService."""
import secrets
from dfap.ldrm_subsystem.domain.enums import TransmissionMethod
from dfap.ldrm_subsystem.providers.connectors.email import InstitutionalEmailConnector, TestEmailTransport
from dfap.ldrm_subsystem.providers.connectors.manual import ManualPortalConnector, PhysicalSubmissionConnector
from dfap.ldrm_subsystem.providers.connectors.gateway import GovernmentGatewayConnector
from dfap.ldrm_subsystem.providers.connectors.sftp import SecureFileTransferConnector
from dfap.ldrm_subsystem.providers.connectors.api import (OfficialAPIConnector, LocalMockProviderServer,
    InProcessAPITransport, LocalTokenAuthentication)


class ConnectorRegistry:
    def __init__(self, repository, access, registry, authorization,
                 sandbox_authorizations=None, secret_provider=None, audit=None):
        args = (repository, access, registry, authorization)
        self.email_transport = TestEmailTransport(repository)
        token = secrets.token_urlsafe(32)
        self.local_api = LocalMockProviderServer(repository, token)
        
        # Base connectors
        manual_portal = ManualPortalConnector(*args)
        physical = PhysicalSubmissionConnector(*args)
        
        self.connectors = {
            TransmissionMethod.OFFICIAL_EMAIL: InstitutionalEmailConnector(*args, transport=self.email_transport),
            TransmissionMethod.PROVIDER_PORTAL: manual_portal,
            TransmissionMethod.MANUAL_PORTAL: manual_portal,
            TransmissionMethod.PHYSICAL_SUBMISSION: physical,
            TransmissionMethod.REGISTERED_POST: physical,
            TransmissionMethod.COURIER: physical,
            TransmissionMethod.IN_PERSON: physical,
            TransmissionMethod.OFFLINE_MEDIA: physical,
            TransmissionMethod.MANUAL_OTHER: manual_portal,
            TransmissionMethod.SECURE_FILE_TRANSFER: SecureFileTransferConnector(*args),
            TransmissionMethod.GOVERNMENT_GATEWAY: GovernmentGatewayConnector(*args),
            TransmissionMethod.OFFICIAL_API: OfficialAPIConnector(*args, transport=InProcessAPITransport(self.local_api),
                                                                 authentication=LocalTokenAuthentication(token)),
        }

        # Stage 4: the authorized sandbox connector exists only when the module
        # was composed with a sandbox authorization service and a secret backend.
        # Without them SANDBOX_API resolves to nothing and dispatch fails closed,
        # rather than silently falling back to a manual preparation connector.
        self.sandbox = None
        if sandbox_authorizations is not None and secret_provider is not None:
            from dfap.ldrm_subsystem.providers.sandbox.connector import AuthorizedSandboxConnector
            self.sandbox = AuthorizedSandboxConnector(
                *args, sandbox_authorizations=sandbox_authorizations,
                secret_provider=secret_provider, audit=audit)
            self.connectors[TransmissionMethod.SANDBOX_API] = self.sandbox

    def get(self, method):
        if method == TransmissionMethod.SANDBOX_API and method not in self.connectors:
            # Never fall back for the sandbox: an unconfigured sandbox must be a
            # refusal, not a quiet downgrade to manual preparation.
            raise ValueError(
                'The authorized sandbox connector is not configured. A sandbox authorization '
                'service and a secret backend are required before SANDBOX_API can be used.')
        if method not in self.connectors:
            # Fallback to manual portal preparation connector for non-automated methods
            return self.connectors[TransmissionMethod.MANUAL_PORTAL]
        return self.connectors[method]
