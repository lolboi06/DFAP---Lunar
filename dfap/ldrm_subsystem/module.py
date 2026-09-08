"""Composition root for the independent LawfulDataRequestModule."""
import json
import logging
import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict
from dfap.ldrm_subsystem.config import LDRMConfig
from dfap.ldrm_subsystem.persistence.repositories import SQLiteRepository
from dfap.ldrm_subsystem.integration.auth_adapter import MockAuthAdapter
from dfap.ldrm_subsystem.integration.case_adapter import MockCaseAdapter
from dfap.ldrm_subsystem.integration.audit_adapter import JournalAuditAdapter
from dfap.ldrm_subsystem.integration.evidence_adapter import LocalEvidenceAdapter
from dfap.ldrm_subsystem.integration.ingestion_adapter import RouterIngestionAdapter
from dfap.ldrm_subsystem.security.secrets import DevelopmentSecretProvider
from dfap.ldrm_subsystem.services.request_service import RequestService

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LDRMHostAdapters:
    """Host services required to compose LDRM into DFAP."""

    auth: Any
    case: Any
    audit: Any
    evidence: Any
    ingestion: Any

    def as_module_kwargs(self) -> Dict[str, Any]:
        return {
            'auth_adapter': self.auth,
            'case_adapter': self.case,
            'audit_adapter': self.audit,
            'evidence_adapter': self.evidence,
            'ingestion_adapter': self.ingestion,
        }


class LawfulDataRequestModule:
    def __init__(self, config=None, *, repository=None, auth_adapter=None, case_adapter=None,
                 audit_adapter=None, evidence_adapter=None, ingestion_adapter=None, tokens=None,
                 audit_key=None, signing_key=None, secret_provider=None):
        self.config = config or LDRMConfig()
        if not self.config.USE_MOCK_PROVIDERS_ONLY:
            raise ValueError('Only mock provider transport is implemented')
        # Either demo flag places the deployment in demonstration operation, so
        # both gate synthetic identities and cases the same way.
        demonstration = self.config.demonstration_mode
        if not demonstration:
            if any(adapter is None for adapter in (auth_adapter, case_adapter, audit_adapter, evidence_adapter, ingestion_adapter)):
                raise RuntimeError('LDRM requires host Auth, Case, Audit, Evidence and Ingestion adapters; use explicit demo mode for standalone development')
            if isinstance(auth_adapter, MockAuthAdapter) or isinstance(case_adapter, MockCaseAdapter):
                raise ValueError('Mock identity and cases are restricted to demo mode')
        if demonstration and auth_adapter is None:
            tokens = tokens if tokens is not None else json.loads(os.getenv('LDRM_DEMO_TOKENS', '{}'))
            if not isinstance(tokens, dict) or not tokens or any(not isinstance(k, str) or len(k) < 24 or not isinstance(v, str) for k, v in tokens.items()):
                raise ValueError('Demo mode requires an explicit token-to-user map with tokens at least 24 characters long')
        if repository is None:
            root = Path(self.config.STORAGE_DIR)
            root.mkdir(parents=True, exist_ok=True, mode=0o700)
            audit_key = audit_key or self._key(root / 'audit.key')
            if demonstration:
                signing_key = signing_key or self._key(root / 'mock-signing.key')
            repository = SQLiteRepository(root / 'ldrm.sqlite3')
        self.repository = repository
        self.auth_adapter = auth_adapter or MockAuthAdapter(tokens=tokens, signing_key=signing_key)
        self.case_adapter = case_adapter or MockCaseAdapter()
        self.audit_adapter = JournalAuditAdapter(repository, audit_key, host=audit_adapter)
        self.evidence_adapter = evidence_adapter or LocalEvidenceAdapter(repository)
        self.ingestion_adapter = ingestion_adapter or RouterIngestionAdapter()
        # References only; the backend resolves values at the moment of use and
        # they never reach an API response, an audit record, or a log line.
        self.secret_provider = secret_provider or DevelopmentSecretProvider()
        # Stage 4: the sandbox authorization service is composed first so the
        # connector registry can decide whether a sandbox connector may exist.
        from dfap.ldrm_subsystem.providers.sandbox.authorization import SandboxAuthorizationService
        from dfap.ldrm_subsystem.policy.access_policy import AccessPolicy
        self.sandbox_authorizations = SandboxAuthorizationService(
            repository, AccessPolicy(self.auth_adapter, self.case_adapter),
            self.audit_adapter, self.secret_provider)
        self.service = RequestService(repository=repository, auth_adapter=self.auth_adapter, case_adapter=self.case_adapter,
                        audit_adapter=self.audit_adapter, evidence_adapter=self.evidence_adapter, ingestion_adapter=self.ingestion_adapter,
                        max_response_size=self.config.MAX_ATTACHMENT_SIZE_BYTES, timeout_days=self.config.DEFAULT_REQUEST_TIMEOUT_DAYS,
                        config=self.config, secret_provider=self.secret_provider,
                        sandbox_authorizations=self.sandbox_authorizations)
        from dfap.ldrm_subsystem.services.communication_service import CommunicationService
        from dfap.ldrm_subsystem.services.advisory_service import AdvisoryService
        from dfap.ldrm_subsystem.services.clarification_service import ClarificationService
        self.communication = CommunicationService(self.service, self.config.demonstration_mode)
        self.advisory_service = AdvisoryService(repository)
        self.clarification_service = ClarificationService(repository, self.service)
        from dfap.ldrm_subsystem.services.integration_service import IntegrationService
        from dfap.ldrm_subsystem.services.readiness_service import ReadinessService
        from dfap.ldrm_subsystem.services.provenance_service import ProvenanceService
        self.integration_service = IntegrationService(
            repository, self.service.access, self.audit_adapter, self.config, self.secret_provider)
        self.provenance_service = ProvenanceService(self.service.access, repository)
        self.readiness_service = ReadinessService(
            repository, self.service.access, self.config, self.secret_provider,
            connectors=self.service.dispatch_service.connectors, audit=self.audit_adapter)

    @staticmethod
    def _key(path):
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            key = path.read_bytes()
        else:
            key = secrets.token_bytes(32)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(key)
                stream.flush()
                os.fsync(stream.fileno())

        if len(key) < 32:
            raise ValueError('LDRM key must contain at least 32 bytes')
        return key

    def flush_integrations(self):
        # Persisted outboxes are retried on startup and periodically. Individual
        # host failures do not discard committed requests or audit events.
        for action in (self.service.flush_case_links, self.audit_adapter.flush):
            try:
                action()
            except Exception:
                logger.exception('LDRM integration delivery pending; will retry')

    def close(self):
        self.flush_integrations()
        self.repository.close()
