"""Dataset routing contract. No parsers or simulated pipeline successes."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional
from dfap.ldrm_subsystem.domain.enums import DatasetType
from dfap.ldrm_subsystem.domain.utils import utc_now


class IntegrationUnavailable(RuntimeError):
    pass


@dataclass
class IngestionResult:
    dataset_type: DatasetType
    evidence_id: str
    case_id: str
    records_ingested: int
    pipeline_status: str
    dataset_id: Optional[str] = None
    job_id: Optional[str] = None
    ingested_at: datetime = field(default_factory=utc_now)
    details: Dict[str, Any] = field(default_factory=dict)
    error_message: Optional[str] = None


class IngestionAdapter(ABC):
    @abstractmethod
    def route(self, evidence, dataset_type, raw_payload=None, context=None):
        """Host must deduplicate by context['idempotency_key'] and retain evidence lineage."""
        ...


class RouterIngestionAdapter(IngestionAdapter):
    def __init__(self, routes=None):
        self.routes = routes or {}

    def route(self, evidence, dataset_type, raw_payload=None, context=None):
        handler = self.routes.get(dataset_type)
        if handler is None:
            raise IntegrationUnavailable(f'DFAP {dataset_type.value} ingestion pipeline is not configured')
        result = handler(evidence=evidence, raw_payload=raw_payload, context=context or {})
        if not isinstance(result, IngestionResult):
            raise ValueError('Ingestion router returned an invalid result')
        if (result.dataset_type, result.evidence_id, result.case_id) != (dataset_type, evidence.evidence_id, evidence.case_id):
            raise ValueError('Ingestion result has mismatched provenance')
        if result.pipeline_status == 'SUCCESS' and not result.dataset_id:
            raise ValueError('Completed ingestion must return a dataset identifier')
        return result


DefaultIngestionAdapter = RouterIngestionAdapter
