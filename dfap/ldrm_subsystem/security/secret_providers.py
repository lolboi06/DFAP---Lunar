"""Adapters for future secret backends (Stage 3 §8).

None of these require an external service to be present for this stage. Each one
declares how it would resolve a reference and refuses to guess when its backend
is absent, so a missing secret blocks dispatch instead of silently succeeding.
"""
import os
from typing import Any, Dict
from dfap.ldrm_subsystem.domain.enums import IntegrationEnvironment
from dfap.ldrm_subsystem.security.secrets import (
    SecretProvider, SecretNotFound, CredentialEnvironmentMismatch, SecretProviderError, _env)


class EnvironmentSecretProvider(SecretProvider):
    """Resolves `LDRM_SECRET_<ENVIRONMENT>_<REFERENCE>` process environment variables.

    The environment name is part of the variable name, so one reference cannot
    resolve across two environments unless an operator deliberately exports both.
    """

    backend_name = 'environment'

    @staticmethod
    def _variable(reference: str, environment) -> str:
        safe = ''.join(c if c.isalnum() else '_' for c in reference).upper()
        return f'LDRM_SECRET_{_env(environment).upper()}_{safe}'

    def secret_exists(self, reference, environment):
        return bool(reference) and self._variable(reference, environment) in os.environ

    def get_secret(self, reference, environment):
        if not reference:
            raise SecretNotFound('No credential reference is configured for this integration')
        name = self._variable(reference, environment)
        try:
            return os.environ[name]
        except KeyError as error:
            for other in IntegrationEnvironment:
                if other != environment and self._variable(reference, other) in os.environ:
                    raise CredentialEnvironmentMismatch(
                        f"Credential reference '{reference}' is present for environment "
                        f"'{_env(other)}' but not for '{_env(environment)}'") from error
            raise SecretNotFound(f"Environment variable '{name}' is not set") from error

    def get_certificate(self, reference, environment):
        return {'reference': reference, 'environment': _env(environment),
                'certificate_data': self.get_secret(reference, environment), 'status': 'RESOLVED'}


class _UnconfiguredBackend(SecretProvider):
    """Declares an interface whose backend is not connected in this stage."""

    backend_name = 'unconfigured'
    requirement = 'a configured backend'

    def secret_exists(self, reference, environment):
        return False

    def get_secret(self, reference, environment):
        raise SecretProviderError(
            f'{type(self).__name__} is an interface placeholder; {self.requirement} '
            'must be connected and security reviewed before it can resolve secrets')

    def get_certificate(self, reference, environment):
        return self.get_secret(reference, environment)

    def health(self):
        return {'backend': self.backend_name, 'status': 'NOT_CONFIGURED', 'requires': self.requirement}


class KeyringSecretProvider(_UnconfiguredBackend):
    """OS keyring / credential-manager backed secrets."""
    backend_name = 'os-keyring'
    requirement = 'an OS keyring service and the keyring client library'


class VaultSecretProvider(_UnconfiguredBackend):
    """Enterprise secret vault (HashiCorp Vault, CyberArk,等) backed secrets."""
    backend_name = 'enterprise-vault'
    requirement = 'an enterprise vault endpoint, authentication role and network policy'


class CloudSecretManagerProvider(_UnconfiguredBackend):
    """Cloud provider secret manager backed secrets."""
    backend_name = 'cloud-secret-manager'
    requirement = 'cloud secret manager credentials and an approved egress policy'


class HSMCertificateProvider(_UnconfiguredBackend):
    """HSM-backed certificate and private key references.

    Private keys never leave the HSM; only handles are returned. The provider
    database stores the handle reference, never key material.
    """
    backend_name = 'hsm'
    requirement = 'an HSM/PKCS#11 module, slot configuration and key custody approval'


AVAILABLE_BACKENDS: Dict[str, Any] = {
    'environment': EnvironmentSecretProvider,
    'keyring': KeyringSecretProvider,
    'vault': VaultSecretProvider,
    'cloud': CloudSecretManagerProvider,
    'hsm': HSMCertificateProvider,
}
