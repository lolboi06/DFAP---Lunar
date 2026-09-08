"""Secret management abstraction for DFAP LDRM (Stage 3 §8, §9).

The provider database stores REFERENCES only. Values are resolved at the moment
of use through a SecretProvider and are never returned to API callers, written
to audit metadata, or logged. Credential references are bound to exactly one
integration environment, so a MOCK credential can never be resolved for a
SANDBOX or PRODUCTION integration.
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from dfap.ldrm_subsystem.domain.enums import IntegrationEnvironment


class SecretProviderError(ValueError):
    pass


class SecretNotFound(SecretProviderError):
    pass


class CredentialEnvironmentMismatch(SecretProviderError):
    """A credential reference was used outside the environment it belongs to."""


#: Marker returned wherever a secret value would otherwise be serialised.
REDACTED = '***REDACTED***'


def redact(value: Any) -> str:
    """Never render a secret. Used by API schemas and audit metadata builders."""
    return REDACTED if value else ''


def _env(environment) -> str:
    return getattr(environment, 'value', str(environment))


class SecretProvider(ABC):
    """Interface for secret backends (env vars, OS keyring, vault, cloud KMS, HSM)."""

    #: Human-readable backend name surfaced in health output.
    backend_name = 'abstract'

    @abstractmethod
    def get_secret(self, reference: str, environment: IntegrationEnvironment) -> str:
        """Resolve a secret value. Raises rather than returning a placeholder."""

    @abstractmethod
    def get_certificate(self, reference: str, environment: IntegrationEnvironment) -> Dict[str, Any]:
        """Resolve certificate material or an opaque handle to it."""

    @abstractmethod
    def secret_exists(self, reference: str, environment: IntegrationEnvironment) -> bool:
        """Report whether a reference resolves for this environment, without reading it."""

    def health(self) -> Dict[str, Any]:
        return {'backend': self.backend_name, 'status': 'AVAILABLE'}


class _MappingSecretProvider(SecretProvider):
    """Shared enforcement: one reference belongs to exactly one environment."""

    def __init__(self):
        self._secrets: Dict[tuple, str] = {}

    def register_secret(self, reference: str, environment: IntegrationEnvironment, secret_value: str) -> None:
        env = _env(environment)
        if not reference or not isinstance(reference, str):
            raise SecretProviderError('A non-empty credential reference is required')
        for (existing_ref, existing_env) in self._secrets:
            if existing_ref == reference and existing_env != env:
                raise CredentialEnvironmentMismatch(
                    f"Credential reference '{reference}' is already bound to environment "
                    f"'{existing_env}' and cannot also be registered for '{env}'")
        self._secrets[(reference, env)] = secret_value

    def environment_of(self, reference: str) -> Optional[str]:
        for (ref, env) in self._secrets:
            if ref == reference:
                return env
        return None

    def secret_exists(self, reference: str, environment: IntegrationEnvironment) -> bool:
        return (reference, _env(environment)) in self._secrets

    def get_secret(self, reference: str, environment: IntegrationEnvironment) -> str:
        env = _env(environment)
        if not reference:
            raise SecretNotFound('No credential reference is configured for this integration')
        key = (reference, env)
        if key not in self._secrets:
            owner = self.environment_of(reference)
            if owner is not None:
                raise CredentialEnvironmentMismatch(
                    f"Credential reference '{reference}' belongs to environment '{owner}' "
                    f"and cannot be used in '{env}'")
            raise SecretNotFound(f"Secret reference '{reference}' not found for environment '{env}'")
        return self._secrets[key]

    def get_certificate(self, reference: str, environment: IntegrationEnvironment) -> Dict[str, Any]:
        value = self.get_secret(reference, environment)
        return {'reference': reference, 'environment': _env(environment),
                'certificate_data': value, 'status': 'RESOLVED'}


class DevelopmentSecretProvider(_MappingSecretProvider):
    """Local development and test backend. Holds synthetic values only.

    The seeded entries are deliberately non-production. Nothing here is read
    from disk, the environment, or a network service.
    """

    backend_name = 'development'

    _SEED = {
        (IntegrationEnvironment.MOCK, 'cred-mock-telecom'): 'mock-secret-telecom-12345',
        (IntegrationEnvironment.MOCK, 'cred-mock-bank'): 'mock-secret-bank-12345',
        (IntegrationEnvironment.MOCK, 'cred-mock-isp'): 'mock-secret-isp-12345',
        (IntegrationEnvironment.MOCK, 'cred-mock-social'): 'mock-secret-social-12345',
        (IntegrationEnvironment.MOCK, 'webhook-mock-key'): 'test-callback-secret-01234567890123456789',
        (IntegrationEnvironment.SANDBOX, 'cred-sandbox-bank'): 'sandbox-secret-bank-889900',
        (IntegrationEnvironment.SANDBOX, 'cred-sandbox-isp'): 'sandbox-secret-isp-889900',
        (IntegrationEnvironment.SANDBOX, 'cert-sandbox-client'): 'sandbox-cert-data-mtls',
    }

    def __init__(self, seed=True):
        super().__init__()
        if seed:
            for (environment, reference), value in self._SEED.items():
                self.register_secret(reference, environment, value)

    def get_secret(self, reference: str, environment: IntegrationEnvironment) -> str:
        # Report an environment crossover first: naming the environment the
        # reference actually belongs to is the more precise refusal.
        owner = self.environment_of(reference)
        if owner is not None and owner != _env(environment):
            raise CredentialEnvironmentMismatch(
                f"Credential reference '{reference}' belongs to environment '{owner}' "
                f"and cannot be used in '{_env(environment)}'")
        if _env(environment) == IntegrationEnvironment.PRODUCTION.value:
            raise CredentialEnvironmentMismatch(
                'The development secret backend never serves PRODUCTION credentials; '
                'configure an enterprise secret backend before production activation')
        return super().get_secret(reference, environment)
