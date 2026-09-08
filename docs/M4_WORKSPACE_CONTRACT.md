# DFAP Member 4 (WP4) — Investigation Workspace & API Contracts

**Author**: Sam Roger X  
**Component**: DFAP WP4 — Investigation Workspace (M13)  
**Date**: September 2026 (Release Candidate 3)  

---

## 1. Authoritative Frozen Input Contracts

Work Package 4 formally establishes and consumes the following frozen upstream Parquet artifacts:

| Layer | Contract File Path | Authoritative Status | SHA-256 Digest |
|---|---|---|---|
| **Member 1** | `output/canonical_events.parquet` | Immutable Read-Only | `a90e1bf43ad413dc52633237690ae7e55ada89ddeb3005fa218c3fd01d866a63` |
| **Member 1** | `output/resolved_entities.parquet` | Immutable Read-Only | `1eeff0fbb82b6cd9517b71a3f561e5a0de36f51eddeba15acf424ae666ee3096` |
| **Member 1** | `output/provenance_ledger.parquet` | Immutable Read-Only | `6ee4a80405b8d0ff8768077d32a41102cb0a60630b7c713c1a48223a363d181e` |
| **Member 2** | `output/graph_features.parquet` | Immutable Read-Only | `ba0acdd140e804df4c94dcc6c1120140b734c6eed89a48fe7bc960cb01b20940` |
| **Member 3** | `output/m3/findings/findings.parquet` | Authoritative Frozen Finding Contract | `e25aeb8844f2955bbc0a1336a2e3e115b469d097a28759836ce6d63359723d86` |

At service startup, `WP4Service` verifies all files against the immutable `FROZEN_UPSTREAM_MANIFEST` and immediately raises `UpstreamIntegrityError` upon any byte-level deviation.

---

## 2. Investigation Workspace State Contract

The investigation workspace maintains centralized, immutable state representing an analyst's focus:

```json
{
  "selected_entity_id": "ENT_0F0FC38C24C0539E",
  "selected_finding_id": "FND_F7F1AEA41A06",
  "timeline_start": "2026-09-01T10:00:00+00:00",
  "timeline_end": "2026-09-01T11:00:00+00:00",
  "selected_event_ids": [
    "EVT_80E854E8D3B557DC"
  ],
  "selected_relationship_ids": [
    "EDGE:ENT_0F0FC38C24C0539E:SENDS:EVT_80E854E8D3B557DC:OBSERVED"
  ]
}
```

---

## 3. Structured Member 5 Read-Only Backend Interfaces

### 3.1 `get_evidence_chain(finding_id: str) -> dict`
- **Input**: Finding identifier (e.g. `FND_F7F1AEA41A06`).
- **Output**: Full `EvidenceChain` dictionary containing:
  * `finding_id`, `entity_id`, `anomaly_type`, `composite_score`, `evidence_status`
  * `resolved_features`: List of indexed feature dictionaries (`feature_name`, `feature_store`, `feature_value`, `entity_id`, `evidence_refs`)
  * `evidence_events`: List of canonical events with raw source file and row index
  * `provenance_steps`: Step-by-step audit trail
  * `prov_o_document`: W3C PROV-O JSON-LD document
  * `upstream_manifest`: Cryptographic integrity hashes of upstream files

### 3.2 `get_entity_timeline(entity_id: str, start: Optional[str], end: Optional[str]) -> List[dict]`
- **Window Policy**: Half-open window `[start, end)`.
- **Ordering**: Deterministic sorting by `(timestamp, event_id)`.
- **Fields Preserved**: `event_id`, `timestamp`, `event_type`, `source_domain`, `actor_id`, `target_id`, `sha256_hash`, `attributes`.

### 3.3 `get_entity_subgraph(entity_id: str, hops: int = 2) -> dict`
- **Hop Constraint**: $0 \le \text{hops} \le 2$. Rejects $\text{hops} > 2$ and $\text{hops} < 0$.
- **Edge Status**: All edges strictly tagged as `OBSERVED` or `INFERRED`.

### 3.4 `get_cytoscape_payload(entity_id: str, hops: int = 2) -> dict`
- **Output**: Deterministic Cytoscape-compatible JSON with `nodes` and `edges` arrays.
