"""Certificate metadata validation for DFAP LDRM (Stage 3 §10).

The provider database holds certificate METADATA and REFERENCES only. Private
keys are never stored here; a reference resolves through a SecretProvider or an
HSM handle. Expired, revoked, untrusted and wrong-environment certificates are
refused before any dispatch.
"""
from typing import List, Optional
from dfap.ldrm_subsystem.domain.profile import CertificateMetadata
from dfap.ldrm_subsystem.domain.enums import IntegrationEnvironment, CertificateType
from dfap.ldrm_subsystem.domain.utils import utc_now


class CertificateValidationError(ValueError):
    pass


#: Statuses that permit use. Everything else blocks.
USABLE_STATUS = 'ACTIVE'
BLOCKING_STATUSES = {'REVOKED', 'UNTRUSTED', 'SUSPENDED', 'EXPIRED', 'PENDING'}

#: Authentication types that require a client certificate to be configured.
MTLS_AUTH_TYPES = {'MTLS', 'MUTUAL_TLS', 'CLIENT_CERTIFICATE', 'MTLS_CLIENT'}
#: Authentication types that require a request signing certificate.
SIGNING_AUTH_TYPES = {'SIGNED_REQUEST', 'REQUEST_SIGNING', 'XMLDSIG', 'JWS'}


def _env(value):
    return getattr(value, 'value', str(value))


class CertificateValidator:
    """Validates certificate metadata for dispatch readiness."""

    @staticmethod
    def validate_certificate(cert: Optional[CertificateMetadata],
                             expected_environment: IntegrationEnvironment,
                             purpose_label: str = 'Certificate',
                             expected_type: Optional[CertificateType] = None) -> CertificateMetadata:
        if not cert:
            raise CertificateValidationError(f'{purpose_label} reference is missing')
        if not cert.fingerprint or not cert.issuer:
            raise CertificateValidationError(
                f"{purpose_label} '{cert.certificate_reference}' is missing issuer or fingerprint metadata")
        now = utc_now()
        for value, name in ((cert.valid_from, 'valid_from'), (cert.valid_until, 'valid_until')):
            if value.tzinfo is None or value.utcoffset() is None:
                raise CertificateValidationError(
                    f"{purpose_label} '{cert.certificate_reference}' {name} must include a timezone")
        if cert.valid_until <= now:
            raise CertificateValidationError(f"{purpose_label} '{cert.certificate_reference}' has expired")
        if cert.valid_from > now:
            raise CertificateValidationError(f"{purpose_label} '{cert.certificate_reference}' is not yet valid")
        if cert.status != USABLE_STATUS:
            raise CertificateValidationError(
                f"{purpose_label} '{cert.certificate_reference}' is in status {cert.status}")
        cert_env, exp_env = _env(cert.environment), _env(expected_environment)
        if cert_env != exp_env:
            raise CertificateValidationError(
                f"{purpose_label} '{cert.certificate_reference}' is for environment '{cert_env}' "
                f"but current environment is '{exp_env}'")
        if expected_type is not None and _env(cert.certificate_type) != _env(expected_type):
            raise CertificateValidationError(
                f"{purpose_label} '{cert.certificate_reference}' is a "
                f"{_env(cert.certificate_type)} certificate, not {_env(expected_type)}")
        return cert

    @staticmethod
    def requirements_for(authentication_type: str) -> dict:
        """Which certificate references an authentication mechanism obliges."""
        auth = (authentication_type or '').upper()
        return {'client_certificate': auth in MTLS_AUTH_TYPES,
                'signing_certificate': auth in SIGNING_AUTH_TYPES}

    @staticmethod
    def get_expiring_certificates(certificates: List[CertificateMetadata], days: int = 30) -> List[CertificateMetadata]:
        """Certificates that are still active but expire within `days`."""
        now = utc_now()
        expiring = []
        for cert in certificates:
            remaining_days = (cert.valid_until - now).total_seconds() / 86400
            if 0 <= remaining_days <= days and cert.status == USABLE_STATUS:
                expiring.append(cert)
        return sorted(expiring, key=lambda c: c.valid_until)

    @staticmethod
    def get_expired_certificates(certificates: List[CertificateMetadata]) -> List[CertificateMetadata]:
        now = utc_now()
        return [c for c in certificates if c.valid_until <= now or c.status in BLOCKING_STATUSES]
