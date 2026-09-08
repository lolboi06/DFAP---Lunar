"""Authorized provider sandbox integration (DFAP Stage 4).

Nothing in this package can reach a network until an administrator has recorded a
`SandboxAuthorization`: the agency's record that a named provider has, in
writing, authorized this agency to use a named non-production sandbox. There is
no default sandbox, no discovered sandbox and no inferred sandbox.

The package refuses PRODUCTION outright. It exists to talk to one explicitly
authorized non-production environment and nothing else.
"""
from dfap.ldrm_subsystem.providers.sandbox.authorization import (
    SandboxAuthorization, SandboxAuthorizationError, SandboxNotAuthorized, SandboxAuthorizationService)
from dfap.ldrm_subsystem.providers.sandbox.mapper import (
    ProviderMapper, PassThroughSandboxMapper, MAPPER_REGISTRY, UnknownProviderStatus,
    ProviderMappingError, MappedResponse)
from dfap.ldrm_subsystem.providers.sandbox.transport import (
    SandboxHTTPTransport, TransportResult, SandboxTransportError,
    RetryableTransportError, NonRetryableTransportError, TLSVerificationError)
from dfap.ldrm_subsystem.providers.sandbox.connector import AuthorizedSandboxConnector

__all__ = [
    'SandboxAuthorization', 'SandboxAuthorizationError', 'SandboxNotAuthorized',
    'SandboxAuthorizationService', 'ProviderMapper', 'PassThroughSandboxMapper',
    'MAPPER_REGISTRY', 'UnknownProviderStatus', 'ProviderMappingError', 'MappedResponse',
    'SandboxHTTPTransport', 'TransportResult', 'SandboxTransportError',
    'RetryableTransportError', 'NonRetryableTransportError', 'TLSVerificationError',
    'AuthorizedSandboxConnector',
]
