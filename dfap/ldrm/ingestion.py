from typing import Any, Dict
from dfap.ldrm_subsystem.integration.ingestion_adapter import IngestionAdapter, IngestionResult
from dfap.ldrm_subsystem.domain.enums import DatasetType
from dfap.ldrm_subsystem.integration.evidence_adapter import EvidenceRecord
from dfap.schemas import CanonicalEvent, ProvenanceRecord
from dfap.ingestion import IngestionParser
from dfap.provenance import compute_canonical_row_hash
import pandas as pd
import os
import hashlib
import uuid
import json

class DFAPIngestionAdapter(IngestionAdapter):
    def __init__(self, canonical_dir: str = "data/canonical"):
        self.canonical_dir = canonical_dir
        os.makedirs(self.canonical_dir, exist_ok=True)

    def route(self, evidence: EvidenceRecord, dataset_type: DatasetType, raw_payload=None, context=None):
        context = context or {}
        
        payload_data = json.loads(raw_payload) if isinstance(raw_payload, (bytes, bytearray, str)) else raw_payload
        records = payload_data.get("records", []) if isinstance(payload_data, dict) else payload_data

        canonical_events = []
        provenance_records = []

        request_id = evidence.metadata.get("request_id")
        provider_id = evidence.metadata.get("provider_id")
        response_id = evidence.metadata.get("response_id")

        for idx, rec in enumerate(records):
            event_id = IngestionParser.generate_deterministic_event_id(evidence.evidence_id, idx)
            actor_id = rec.get("actor_id", rec.get("source_id", "UNKNOWN"))
            target_id = rec.get("target_id", rec.get("destination_id"))
            ts = rec.get("timestamp", rec.get("date", "UNKNOWN_TIMESTAMP"))
            ev_type = rec.get("event_type", rec.get("type", "LDRM_EVENT"))
            domain = dataset_type.value

            # Recompute DFAP specific canonical hash for the row
            row_hash = compute_canonical_row_hash(
                source_file=evidence.evidence_id,
                source_row_index=idx,
                raw_row=rec
            )

            attributes = rec.get("attributes", {})
            attributes.update({
                "ldrm_request_id": request_id,
                "ldrm_case_id": evidence.case_id,
                "ldrm_provider_id": provider_id,
                "ldrm_response_id": response_id,
                "ldrm_evidence_id": evidence.evidence_id,
                "ldrm_payload_hash": evidence.payload_hash,
                "raw_source_attributes": rec
            })

            canonical_events.append({
                "event_id": event_id,
                "timestamp": ts,
                "actor_id": actor_id,
                "target_id": target_id,
                "event_type": ev_type,
                "source_domain": domain,
                "attributes": json.dumps(attributes),
                "sha256_hash": row_hash
            })

            provenance_records.append({
                "sha256_hash": row_hash,
                "source_id": f"LDRM_{provider_id}",
                "source_file": evidence.evidence_id,
                "source_row_index": idx,
                "ingestion_timestamp": evidence.registered_at.isoformat(),
                "schema_version": "WP1.1"
            })

        if canonical_events:
            df_ev = pd.DataFrame(canonical_events)
            df_prov = pd.DataFrame(provenance_records)

            dataset_id = f"LDRM_{evidence.evidence_id}"
            ev_path = os.path.join(self.canonical_dir, f"canonical_events_{dataset_id}.parquet")
            prov_path = os.path.join(self.canonical_dir, f"provenance_ledger_{dataset_id}.parquet")

            df_ev.to_parquet(ev_path, index=False)
            df_prov.to_parquet(prov_path, index=False)

        return IngestionResult(
            dataset_type=dataset_type,
            evidence_id=evidence.evidence_id,
            case_id=evidence.case_id,
            records_ingested=len(canonical_events),
            pipeline_status='SUCCESS',
            dataset_id=f"LDRM_{evidence.evidence_id}" if canonical_events else "LDRM_EMPTY"
        )
