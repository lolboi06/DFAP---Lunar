"""Deployment readiness and observability (DFAP Stage 3 §29, §30).

Answers one question for an administrator: is this system safe to operate right
now, and what is blocking it. Every figure is counted from persisted state; none
is asserted. No endpoint here returns a secret value, a certificate fingerprint's
private counterpart, an internal hostname, or case content.
"""
from collections import Counter

from dfap.ldrm_subsystem.domain.enums import (
    IntegrationEnvironment, ProviderIntegrationStatus as S, CertificationResult)
from dfap.ldrm_subsystem.domain.provider import Provider
from dfap.ldrm_subsystem.domain.utils import utc_now
from dfap.ldrm_subsystem.security.certificates import CertificateValidator


def _v(value):
    return getattr(value, 'value', str(value))


class ReadinessService:
    def __init__(self, repository, access, config, secret_provider, connectors=None, audit=None):
        self.repository, self.access, self.config = repository, access, config
        self.secrets, self.connectors, self.audit = secret_provider, connectors, audit

    # ------------------------------------------------------------- dashboard

    def dashboard(self, actor_id):
        """The Stage 3 §30 administrator readiness view."""
        self.access.administrator(actor_id)
        profiles = self.repository.list_integration_profiles()
        providers = self.repository.list('provider', Provider)
        status_counts = Counter(_v(p.integration_status) for p in profiles)
        env_counts = Counter(_v(p.environment) for p in profiles)

        certificates = self.repository.list_certificates()
        expiring = CertificateValidator.get_expiring_certificates(
            certificates, self.config.EXPIRY_WARNING_DAYS)
        expired = CertificateValidator.get_expired_certificates(certificates)

        failed_certifications = 0
        for profile in profiles:
            records = self.repository.list_certification_records(profile.integration_profile_id)
            if records and records[0].result != CertificationResult.PASS:
                failed_certifications += 1

        permitted, reason = self.config.production_dispatch_permitted()
        quarantined = self._quarantine_backlog()

        return {
            'generated_at': utc_now().isoformat(),
            'demonstration_mode': self.config.demonstration_mode,
            'production_dispatch': {
                'enabled': permitted,
                'state': 'ENABLED' if permitted else 'DISABLED',
                'reason': reason,
                'kill_switch': self.config.PRODUCTION_DISPATCH_ENABLED,
                'ldrm_enabled': self.config.ENABLED,
                'mock_transport_only': self.config.USE_MOCK_PROVIDERS_ONLY,
            },
            'counts': {
                'providers': len(providers),
                'providers_verified': sum(1 for p in providers if p.is_eligible_for_dispatch),
                'integration_profiles': len(profiles),
                'mock_active': env_counts.get(IntegrationEnvironment.MOCK.value, 0),
                'sandbox_configured': status_counts.get(S.SANDBOX_CONFIGURED.value, 0),
                'contract_tested': status_counts.get(S.CONTRACT_TESTED.value, 0),
                'security_reviewed': status_counts.get(S.SECURITY_REVIEWED.value, 0),
                'agency_approved': status_counts.get(S.AGENCY_APPROVED.value, 0),
                'provider_approved': status_counts.get(S.PROVIDER_APPROVED.value, 0),
                'production_active': status_counts.get(S.PRODUCTION_ACTIVE.value, 0),
                'suspended': status_counts.get(S.SUSPENDED.value, 0),
                'revoked': status_counts.get(S.REVOKED.value, 0),
                'draft': status_counts.get(S.DRAFT.value, 0),
                'certificates_expiring': len(expiring),
                'certificates_expired': len(expired),
                'failed_contract_tests': failed_certifications,
                'quarantined_responses': quarantined,
            },
            'by_environment': dict(env_counts),
            'by_status': dict(status_counts),
            'certificates_expiring_soon': [
                {'reference': c.certificate_reference, 'type': _v(c.certificate_type),
                 'environment': _v(c.environment), 'valid_until': c.valid_until.isoformat()}
                for c in expiring],
            'safe_to_operate': self._safety_summary(profiles, expired, permitted),
        }

    def _safety_summary(self, profiles, expired_certificates, production_permitted):
        concerns = []
        if production_permitted:
            concerns.append('Production dispatch is ENABLED; every production integration is live')
        if expired_certificates:
            concerns.append(f'{len(expired_certificates)} certificate(s) are expired or revoked')
        stale = [p for p in profiles if p.expires_at and p.expires_at <= utc_now()
                 and p.integration_status not in {S.EXPIRED, S.REVOKED}]
        if stale:
            concerns.append(f'{len(stale)} integration profile(s) are past their expiry '
                            'but not marked EXPIRED')
        if self.config.demonstration_mode:
            concerns.append('DEMONSTRATION MODE: synthetic providers, cases and identities only')
        return {'production_dispatch_disabled': not production_permitted,
                'concerns': concerns,
                'verdict': 'SAFE — production dispatch disabled' if not production_permitted
                           else 'REVIEW REQUIRED — production dispatch enabled'}

    # ---------------------------------------------------------------- health

    def health(self, actor_id):
        """Administrator health view. Contains no endpoint, credential or case data."""
        self.access.administrator(actor_id)
        profiles = self.repository.list_integration_profiles()
        return {
            'ldrm': {'enabled': self.config.ENABLED,
                     'demonstration_mode': self.config.demonstration_mode,
                     'audit_integrity': bool(self.audit and self.audit.verify_integrity())
                     if self.audit else None},
            'secret_backend': self.secrets.health() if self.secrets else {'status': 'NOT_CONFIGURED'},
            'connectors': self._connector_health(),
            'integrations': [
                {'integration_profile_id': p.integration_profile_id, 'provider_id': p.provider_id,
                 'environment': _v(p.environment), 'status': _v(p.integration_status),
                 'endpoint_verified': p.endpoint_verification_status == 'VERIFIED',
                 'expires_at': p.expires_at.isoformat() if p.expires_at else None}
                for p in profiles],
            'certificate_expiry': [
                {'reference': c.certificate_reference, 'environment': _v(c.environment),
                 'valid_until': c.valid_until.isoformat(), 'status': c.status}
                for c in CertificateValidator.get_expiring_certificates(
                    self.repository.list_certificates(), self.config.EXPIRY_WARNING_DAYS)],
            'failures': self.recent_failures(),
            'quarantine_backlog': self._quarantine_backlog(),
        }

    def public_health(self):
        """Unauthenticated liveness only. Deliberately reveals nothing operational."""
        return {'status': 'healthy', 'ldrm_enabled': self.config.ENABLED,
                'production_dispatch_enabled': self.config.production_dispatch_permitted()[0]}

    def _connector_health(self):
        if not self.connectors:
            return []
        seen, health = set(), []
        for connector in self.connectors.connectors.values():
            if id(connector) in seen:
                continue
            seen.add(id(connector))
            try:
                health.append(connector.health_check())
            except Exception as error:
                health.append({'status': 'UNHEALTHY', 'connector': type(connector).__name__,
                               'detail': type(error).__name__})
        return health

    def recent_failures(self, limit=50):
        """Counts of blocked dispatches, rejected responses and webhook failures."""
        events = self.audit.all_events if self.audit else []
        interesting = {'DISPATCH_BLOCKED', 'PROVIDER_REPLY_QUARANTINED', 'OPERATION_FAILED',
                       'SECURITY_VIOLATION', 'PROVIDER_RESPONSE_REJECTED'}
        counts = Counter(e.action for e in events if e.action in interesting)
        return {'counts': dict(counts),
                'recent': [{'action': e.action, 'entity_id': e.entity_id,
                            'timestamp': e.timestamp.isoformat(),
                            'reason': e.metadata.get('reason') or e.metadata.get('error_type')}
                           for e in events if e.action in interesting][-limit:]}

    def _quarantine_backlog(self):
        with self.repository.lock:
            row = self.repository.connection.execute(
                "SELECT COUNT(*) FROM quarantine WHERE json_extract(metadata,'$.status')='QUARANTINED'"
            ).fetchone()
        return row[0] if row else 0
