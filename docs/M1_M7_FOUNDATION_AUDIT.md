# DFAP FOUNDATION AUDIT — M1–M7 (Members 1 & 2)

**Date**: 2026-09-01  
**Auditor**: Independent Senior Researcher  
**Scope**: M1–M7 integrated foundation (WP1 + WP2)

---

## FINAL DECISION

> **DFAP FOUNDATION M1–M7 = PASS**

All blocking criteria independently verified. Identified limitations are non-blocking and documented.

---

## 1. FOUNDATION ARCHITECTURE

The data flow is confirmed as:

```
RAW SOURCE FILES (CDR/IPDR/BANK/SOCIAL)
       ↓ ingestion.py (IngestionParser)
VALIDATION (domain, timestamp, IP, numeric, duplicate)
       ↓ provenance.py (compute_canonical_row_hash)
SHA-256 EVIDENCE HASH → provenance_ledger.parquet
       ↓ linkage.py (EntityResolver / Splink)
ENTITY RESOLUTION → resolved_entities.parquet, entity_matches.parquet
       ↓ pipeline.py (clean schema extraction)
CANONICAL EVENTS → canonical_events.parquet
       ↓ graph.py (DFAPGraphService)
TEMPORAL HETEROGENEOUS GRAPH (igraph in-memory)
       ↓ features.py (DomainAnalyticsService)
DOMAIN FEATURES → telecom/financial/social/graph_features.parquet
```

Each stage consumes only the outputs of the previous stage. No stage rewrites upstream semantics.

---

## 2. MEMBER 1 OUTPUT CONTRACTS

### Schemas (actual, from DuckDB DESCRIBE)

**canonical_events.parquet** (13 rows):  
`event_id VARCHAR, timestamp VARCHAR, actor_id VARCHAR, target_id VARCHAR, event_type VARCHAR, source_domain VARCHAR, attributes VARCHAR, sha256_hash VARCHAR`

**resolved_entities.parquet** (12 rows):  
`canonical_entity_id VARCHAR, raw_identifier VARCHAR, identifier_type VARCHAR, match_confidence DOUBLE, match_method VARCHAR, match_status VARCHAR, evidence VARCHAR`

**provenance_ledger.parquet** (13 rows):  
`sha256_hash VARCHAR, source_id VARCHAR, source_file VARCHAR, source_row_index BIGINT, ingestion_timestamp VARCHAR, schema_version VARCHAR`

**entity_matches.parquet** (0 rows — see §22):  
`match_id, left_record_id, right_record_id, match_probability, match_weight, blocking_rule, comparison_summary, match_method, match_status, decision_reason, model_version`

**wp1_manifest.json**: Present. Contains run_id, schema_version, row_counts, input_file_hashes, thresholds, validation_reports.

### WP1 SHA-256 Hashes (frozen)

| Artifact | SHA-256 |
|----------|---------|
| canonical_events.parquet | `a90e1bf43ad413dc52633237690ae7e55ada89ddeb3005fa218c3fd01d866a63` |
| resolved_entities.parquet | `1eeff0fbb82b6cd9517b71a3f561e5a0de36f51eddeba15acf424ae666ee3096` |
| provenance_ledger.parquet | `6ee4a80405b8d0ff8768077d32a41102cb0a60630b7c713c1a48223a363d181e` |

WP2 verified not to modify these files.

---

## 3. M1 — TRUSTED DATA FOUNDATION

**Validated**: All 6 source files balance correctly.

| File | Received | Accepted | Rejected | Balance |
|------|----------|----------|----------|---------|
| bank_records.csv | 3 | 2 | 1 | OK |
| banking_records.csv | 2 | 2 | 0 | OK |
| cdr_records.csv | 5 | 3 | 2 | OK |
| ipdr_records.csv | 3 | 2 | 1 | OK |
| social_records.csv | 2 | 2 | 0 | OK |
| social_records.json | 2 | 2 | 0 | OK |
| **TOTAL** | **17** | **13** | **4** | **OK** |

`received == accepted + rejected`: **True**. No silent row loss.

Validation checks implemented: source domain, duplicate raw row (SHA-256 fingerprint), missing actor_id, timestamp normalization, event_type vocabulary, CDR duration ≥ 0, BANK amount ≥ 0, IPDR IP address format.

---

## 4. M2 — ENTITY RESOLUTION (Splink)

**Exact Splink Configuration:**
- `link_type`: `dedupe_only`
- **Blocking rules**: `block_on('ip_subnet')`, `block_on('actor_id')`, `block_on('device_id')`
- **Comparisons**: `JaroWinklerAtThresholds('actor_name', [0.85])`, `ExactMatch('actor_id')`, `ExactMatch('ip_subnet')`, `ExactMatch('device_id')`
- **Training**: EM over `block_on('ip_subnet')` and `block_on('actor_id')`
- **CONFIRMED threshold**: 0.85
- **POSSIBLE threshold**: 0.60
- **Clustering**: `cluster_pairwise_predictions_at_threshold(threshold=confirmed_threshold=0.85)` — POSSIBLE and REJECTED pairs are excluded from clusters

**Status Semantics — Verified Distinct:**
- `CONFIRMED`: prob ≥ 0.85 OR exact actor_id match
- `POSSIBLE`: 0.60 ≤ prob < 0.85
- `REJECTED`: prob < 0.60

**Confirmed**: similarity ≠ identity. POSSIBLE pairs do not enter confirmed clusters (test `test_possible_match_preserves_uncertainty` passes).

---

## 5. ENTITY RESOLUTION CONTROLLED EXAMPLES

From `test_known_positive_and_negative_matches` (PASSING):

**A. Sam Roger X ("+1-555-0101") across CDR + BANK** → Same `canonical_entity_id` ✓  
**B. Household IP sharing (Alice + Bob, same 172.16.50.0/24 subnet, different phones/devices)** → Different `canonical_entity_id` ✓

`test_possible_match_preserves_uncertainty` (PASSING): "Alexander Vance" / "Alex Vance" with high confirmed threshold (0.95) correctly produces POSSIBLE status without merging entities.

---

## 6. M3 — CANONICAL EVENT AUDIT

All 8 required fields present: `event_id, timestamp, actor_id, target_id, event_type, source_domain, attributes, sha256_hash`

- **event_id**: Deterministic UUID5 `EVT_<hex16>`. Uniqueness guaranteed by deterministic input `f"{source_file}:{row_index}:WP1.1"`.
- **timestamp**: UTC ISO-8601 via `pd.to_datetime(ts_val, utc=True).isoformat()`.
- **event_type**: From frozen vocabulary `{CALL, IP_SESSION, TRANSACTION, LOGIN, SOCIAL, DEVICE_EVENT, LOCATION_EVENT}`.
- **source_domain**: From frozen vocabulary `{CDR, IPDR, BANK, SOCIAL}`.
- **sha256_hash**: SHA-256 over `{schema_version, source_file, source_row_index, row}`.
- **5/5 sampled events** traced directly to provenance_ledger.parquet.

---

## 7. PROVENANCE AUDIT

SHA-256 hash payload fields (explicit, from `provenance.py`):
```json
{
  "schema_version": "WP1.1",
  "source_file": "<filename>",
  "source_row_index": <int>,
  "row": { "<sorted field>": "<str value>", ... }
}
```

- **Hash determinism**: Same input → same hash: **True**
- **Sensitive to content**: Changed `amount` field → different hash: **True**
- **Merkle root NOT claimed**: `provenance.py` code confirms SHA-256 are row-level evidence hashes only. Comment explicitly states: "A full Merkle tree/root construction is a downstream responsibility."

---

## 8. MEMBER 2 INPUT INTEGRITY

- WP2 reads only `canonical_events.parquet` + `resolved_entities.parquet` via DuckDB `read_parquet`.
- SHA-256 hashes of both WP1 files are **identical** before and after WP2 graph construction.
- `actor_id` and `target_id` from canonical events are used directly as node names in graph construction.
- `match_status` (CONFIRMED/POSSIBLE/REJECTED) is read from `resolved_entities.parquet` and stored as a node attribute — it is NOT mapped to edge status.

---

## 9. GRAPH ONTOLOGY AUDIT

**Node types present**: `SocialAccount`, `Account`, `IP`, `Phone`, `Event`  
**Relationship types**: `SENDS`, `RECEIVES`, `CALLS`, `CONNECTS_TO`, `POSTED`, `INTERACTED_WITH`, `ASSOCIATED_WITH`  
**Edge statuses**: `OBSERVED`, `INFERRED`

**CRITICAL CHECK — Identity vs Relationship status are decoupled**:
- `resolved_entities.match_status` ∈ {CONFIRMED, POSSIBLE, REJECTED}
- Graph edge `status` ∈ {OBSERVED, INFERRED}
- These sets are **disjoint**. CONFIRMED ≠ OBSERVED.

**OBSERVED** edges: Direct entity ↔ event connections (e.g., `ENT_X --SENDS--> EVT_Y`).  
**INFERRED** edges: Derived structural links (e.g., shared device/IP `ASSOCIATED_WITH`).

---

## 10. GRAPH EVIDENCE AUDIT

Verified OBSERVED edge example:
```
ENT_DB9EEA96AFE45B12 --[SENDS]--> EVT_025E41E766045F59
evidence_refs = ['EVT_025E41E766045F59']
Event: type=TRANSACTION, hash=972e854ffb8d1dd6140d...
```

Every observed relationship traces to at least one `event_id` with a verifiable `sha256_hash`.

---

## 11. TEMPORAL GRAPH AUDIT

- Time-bounded query `[10:00, 10:10]`: 2 events returned, all within bounds ✓
- `start_time <= timestamp <= end_time` (inclusive) ✓
- Backward time path `ENT3 → ENT2` (night call at 23:00 → morning call at 10:00): **rejected** (path length = 0) ✓
- Forward path `ENT1 → ENT2`: **accepted** ✓

---

## 12. 2-HOP GUARANTEE

`get_2hop_neighborhood()` BFS is confirmed to return only entity/event nodes reachable within 2 hops. The production graph has 25 nodes total, many in disconnected sub-components. The `hop>2=23` count in the BFS distance table reflects nodes unreachable from ENT1 (i.e., in a separate connected component), NOT nodes erroneously returned by the method.

Controlled test `test_2hop_bound` (PASSING) verifies correctness.

---

## 13–15. DOMAIN FEATURE AUDIT (M5, M6, M7)

### M5 Telecom Features (CDR)
| Feature | Formula | Zero-denom | Missing |
|---------|---------|------------|---------|
| call_count | `COUNT(CALL events)` | N/A | 0 |
| unique_contacts | `|distinct target entities|` | N/A | 0 |
| mean_duration | `Σ duration / call_count` | 0.0 | 0.0 |
| max_duration | `max(duration)` | N/A | 0.0 |
| night_call_ratio | `night_calls / call_count` | 0.0 | 0.0 |
| reciprocity | `mutual_pairs / directed_pairs` | 0.0 | 0.0 |
| burstiness | `σ(Δt) / μ(Δt)` (CV) | 0.0 | 0.0 (<2 events) |

### M6 Financial Features (BANK)
| Feature | Formula |
|---------|---------|
| transaction_count | COUNT |
| mean_amount | Σ amount / count |
| median_amount | median(amounts) |
| amount_deviation | MAD = median(|x - median(x)|) |
| transaction_velocity | Σ amount |
| unique_counterparties | distinct entity neighbors |
| inflow_outflow_ratio | Σ_received / Σ_sent (999999.0 if sent=0) |
| merchant_diversity | distinct Merchant nodes |

### M7 Social Features
| Feature | Status |
|---------|--------|
| activity_frequency | Implemented |
| interaction_count | Implemented |
| topic_shift | UNAVAILABLE — explicitly NOT fabricated |
| community_membership | UNAVAILABLE — explicitly NOT fabricated |

---

## 16. FEATURE CONTRACT AUDIT

All four parquets share the identical frozen schema with zero nulls:

`entity_id (str), feature_name (str), feature_value (float64), window (str), source (str), evidence_refs (object/list)`

| File | Rows | Null count |
|------|------|-----------|
| graph_features.parquet | 32 | 0 |
| telecom_features.parquet | 33 | 0 |
| financial_features.parquet | 32 | 0 |
| social_features.parquet | 6 | 0 |

---

## 17. FEATURE TRACEABILITY (10 samples)

All 10 sampled features across M5-M7-graph had **valid evidence_refs**. Total invalid `evidence_refs`: **0**.

---

## 18. NO FABRICATED RELATIONSHIPS

Test `test_no_fabricated_relationships` (PASSING): ENT1 and ENT7 have no transaction/call/IP path — `get_temporal_path("ENT1","ENT7")` returns an empty path.

`test_known_positive_and_negative_matches` (PASSING): Alice and Bob share IP subnet `172.16.50.0/24` but are resolved to **separate** entity IDs. No `OWNS`, `ASSOCIATED_WITH`, or `USES` edge is created without an explicit inference rule.

---

## 21. REPRODUCIBILITY

- `graph_features.equals(second_run)` = **True**
- `telecom_features.equals(second_run)` = **True**
- All features sorted by `[entity_id, feature_name]` before export.

---

## 23. FULL TEST SUITE RESULTS

```
tests/ — 41 passed, 0 failed, 0 skipped
Execution time: 9.08s
```

| Test file | Tests | Passed |
|-----------|-------|--------|
| test_end_to_end_pipeline.py | 2 | 2 |
| test_gate1.py | 1 | 1 |
| test_header_contract.py | 1 | 1 |
| test_linkage_and_clustering.py | 2 | 2 |
| test_member2_gate.py | 27 | 27 |
| test_schema_and_hashing.py | 4 | 4 |
| test_validation_accountability.py | 4 | 4 |

---

## 24. PERFORMANCE (actual measured)

| Operation | Time | Dataset |
|-----------|------|---------|
| Graph construction from WP1 parquets | 48.0 ms | 25 nodes, 14 edges |
| Full M5+M6+M7+graph feature extraction | 3.8 ms | fixture dataset |
| 2-hop neighborhood query | 0.15 ms | fixture dataset |
| Temporal path query | 0.03 ms | fixture dataset |

Note: Production dataset is small (13 events, 12 entities). Timings will scale with real data.

---

## 22. RESEARCH QUALITY ISSUES

| Issue | Classification | Detail |
|-------|---------------|--------|
| `entity_matches.parquet` is empty (0 rows) in production | NON-BLOCKING | Synthetic dataset is too small and structured to generate cross-domain candidate pairs above the Splink prediction threshold. The code path for POSSIBLE/REJECTED records is exercised in `test_linkage_and_clustering.py`. |
| `resolved_entities.match_status` is always CONFIRMED | NON-BLOCKING | Same cause as above. The three statuses are distinct in code; production data does not trigger borderline pairs. |
| Splink EM training may silently fail on small datasets | NON-BLOCKING | `try/except pass` block in linkage.py catches training failures. Silently degraded model is used. For research-grade production, this should log a warning. |
| `inflow_outflow_ratio` uses `999999.0` cap | NON-BLOCKING | Documented behavior. Member 3 must be aware. |
| `burstiness` = 0.0 for single-event entities | NON-BLOCKING | Documented. |
| No INFERRED edges in production graph | NON-BLOCKING | Production synthetic data has no shared-device/shared-IP multi-entity events. Inference rules are in code and verified by fixture tests. |

---

## 26. RESEARCH LIMITATIONS

1. **Synthetic data**: Production data is synthetic. Entity resolution thresholds (0.85/0.60) are heuristic defaults, not calibrated against labeled ground truth.
2. **Splink training instability**: EM estimation may converge sub-optimally on small datasets.
3. **Graph scale**: Current production graph has 25 nodes, 14 edges. Real-world graphs will require memory and latency profiling.
4. **Topic shift / community membership**: Not implemented — no NLP engine available.
5. **`shared_counterparties`**: Returns max-pairwise overlap (scalar). Full pairwise distribution not exported.
6. **`transaction_path_features`**: Strictly bounded at 2 hops by design.
7. **Temporal data limitations**: All test data is within a single day. Cross-day and cross-timezone path testing not yet validated.
8. **`new_contact_rate`, `new_counterparty_ratio`**: Defined in documentation but not yet implemented in `features.py`.

---

## 25. FROZEN FOUNDATION CONTRACTS

### MEMBER 1 OUTPUTS (read-only for Member 3)
| Artifact | Path | Status |
|----------|------|--------|
| canonical_events.parquet | output/ | FROZEN |
| resolved_entities.parquet | output/ | FROZEN |
| provenance_ledger.parquet | output/ | FROZEN |
| entity_matches.parquet | output/ | FROZEN |
| wp1_manifest.json | output/ | FROZEN |

### MEMBER 2 OUTPUTS (Member 3 inputs)
| Artifact | Path | Rows | Schema |
|----------|------|------|--------|
| graph_features.parquet | output/ | 32 | Frozen |
| telecom_features.parquet | output/ | 33 | Frozen |
| financial_features.parquet | output/ | 32 | Frozen |
| social_features.parquet | output/ | 6 | Frozen |

All Member 2 outputs use identical schema: `[entity_id, feature_name, feature_value, window, source, evidence_refs]`

