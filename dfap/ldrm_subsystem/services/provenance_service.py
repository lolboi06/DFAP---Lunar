"""Complete evidence provenance (DFAP Stage 3 §21).

Resolves the full chain in both directions:

    Entity/Dataset -> Normalized Record -> Original Record -> Evidence
      -> Provider Response -> Provider Reference -> LDRM Request
      -> Request Version -> Authorization -> Case

Case-level access is checked before any content is returned, so an actor without
access to the owning case learns nothing about the evidence, not even that it
exists beyond a not-found response.
"""
from typing import Any, Dict, List, Optional

from dfap.ldrm_subsystem.domain.models import LawfulDataRequest, RequestAuthorization
from dfap.ldrm_subsystem.domain.response import ProviderResponse
from dfap.ldrm_subsystem.domain.transmission import RequestTransmission


class ProvenanceServiceError(ValueError):
    pass


class ProvenanceService:
    def __init__(self, access, repository):
        self.access = access
        self.repository = repository

    # ------------------------------------------------------------ resolution

    def _locate(self, evidence_id: str) -> Dict[str, Any]:
        """Find the evidence anchor without revealing anything to the caller yet."""
        with self.repository.lock:
            row = self.repository.connection.execute(
                'SELECT * FROM evidence_store_metadata WHERE evidence_id=?', (evidence_id,)
            ).fetchone()
        if row is not None:
            return {'case_id': row['case_id'], 'request_id': row['request_id'],
                    'provider_id': row['provider_id'], 'response_id': row['response_id'],
                    'received_at': row['received_at'], 'sha256': row['sha256'],
                    'size_bytes': row['size_bytes'], 'media_type': row['media_type'],
                    'chain_of_custody_reference': row['chain_of_custody_reference'],
                    'source': 'immutable_evidence_store'}

        # Fall back to the host evidence register, then to the response that
        # produced it, so an evidence ID from either side resolves.
        try:
            from dfap.ldrm_subsystem.integration.evidence_adapter import EvidenceRecord
            record = self.repository.get('evidence', evidence_id, EvidenceRecord)
        except KeyError:
            record = None
        if record is not None:
            metadata = record.metadata or {}
            return {'case_id': record.case_id, 'request_id': metadata.get('request_id'),
                    'provider_id': metadata.get('provider_id'),
                    'response_id': metadata.get('response_id'),
                    'received_at': record.registered_at.isoformat(),
                    'sha256': record.payload_hash, 'size_bytes': record.byte_length,
                    'media_type': record.mime_type,
                    'chain_of_custody_reference': record.w3c_prov_urn,
                    'source': 'host_evidence_register'}
        raise ProvenanceServiceError(f"Evidence '{evidence_id}' not found")

    def get_evidence_provenance(self, evidence_id: str, actor_id: str) -> Dict[str, Any]:
        anchor = self._locate(evidence_id)
        case_id, request_id = anchor['case_id'], anchor['request_id']

        # Authorize against the owning case before returning any content.
        self.access.require(actor_id, 'VIEW_REQUEST', case_id=case_id, active=False)

        if not request_id:
            raise ProvenanceServiceError(
                f"Evidence '{evidence_id}' has no recorded originating request")
        request = self.repository.get_request(request_id)
        if request.case_id != case_id:
            # A mismatch means the chain has been tampered with; refuse rather
            # than return a lineage that crosses a case boundary.
            raise ProvenanceServiceError(
                'Evidence case does not match the originating request; provenance is inconsistent')

        transmissions = self.repository.list('transmission', RequestTransmission, request_id)
        responses = self.repository.list('response', ProviderResponse, request_id)
        response = next((r for r in responses if r.id == anchor['response_id']), None)
        authorizations = self.repository.list('authorization', RequestAuthorization, request_id)
        versions = self.repository.list_request_versions(request_id)
        datasets = self.repository.list('ingestion', request_id=request_id)
        case = self.access.cases.get_case(case_id)

        return {
            'provenance_summary': (
                f'Evidence {evidence_id} <- response {anchor["response_id"]} '
                f'<- request {request.request_number} v{request.request_version} '
                f'<- authorization {request.authorization.authority_reference if request.authorization else "none"} '
                f'<- case {case_id}'),
            'chain': ['case', 'authorization', 'request_version', 'request', 'provider_reference',
                      'provider_response', 'evidence', 'dataset'],
            'evidence': {
                'evidence_id': evidence_id, 'response_id': anchor['response_id'],
                'sha256': anchor['sha256'], 'size_bytes': anchor.get('size_bytes'),
                'media_type': anchor.get('media_type'), 'received_at': anchor['received_at'],
                'chain_of_custody_reference': anchor.get('chain_of_custody_reference'),
                'source': anchor['source'], 'immutable': True,
            },
            'provider_response': response.to_dict() if response else {
                'response_id': anchor['response_id'], 'raw_payload_hash': anchor['sha256'],
                'note': 'response row not retained; original bytes remain in evidence storage'},
            'provider_references': [
                {'transmission_id': t.id, 'provider_reference': t.provider_tracking_ref,
                 'method': t.transmission_method.value,
                 'status': t.transmission_status.value,
                 'dispatched_by': t.dispatched_by,
                 'dispatch_timestamp': t.dispatch_timestamp.isoformat(),
                 'package_payload_hash': t.package_payload_hash,
                 'request_version': t.request_version,
                 'authorization_id': t.authorization_id} for t in transmissions],
            'request': {
                'id': request.id, 'request_number': request.request_number,
                'version': request.request_version, 'canonical_hash': request.canonical_hash,
                'dataset_type': getattr(request.dataset_type, 'value', str(request.dataset_type)),
                'status': getattr(request.status, 'value', str(request.status)),
                'provider_id': request.provider_id, 'created_by': request.created_by,
                'created_at': request.created_at.isoformat(),
            },
            'request_versions': versions,
            'authorization': request.authorization.to_dict() if request.authorization else None,
            'authorization_history': [a.to_dict() for a in authorizations],
            'datasets': datasets,
            'case': {
                'case_id': case.case_id if case else case_id,
                'case_number': case.case_number if case else case_id,
                'title': case.title if case else 'Unknown case',
                'lead_investigator_id': case.lead_investigator_id if case else None,
            },
        }

    # -------------------------------------------------------- reverse lookup

    def get_request_provenance(self, request_id: str, actor_id: str) -> Dict[str, Any]:
        """Every evidence item produced by one request, with its lineage."""
        request = self.repository.get_request(request_id)
        self.access.require(actor_id, 'VIEW_REQUEST', case_id=request.case_id, active=False)
        with self.repository.lock:
            rows = self.repository.connection.execute(
                'SELECT evidence_id FROM evidence_store_metadata WHERE request_id=?',
                (request_id,)).fetchall()
        return {'request_id': request_id, 'case_id': request.case_id,
                'request_versions': self.repository.list_request_versions(request_id),
                'evidence': [self.get_evidence_provenance(r['evidence_id'], actor_id)
                             for r in rows]}
