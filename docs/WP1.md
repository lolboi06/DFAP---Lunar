# DFAP WP1 — Trusted Data Foundation + Entity Resolution Architecture

**Author**: Sam Roger X  
**Component**: DFAP WP1 - Data & Entity Research  

---

## 1. Overview & Architecture

Work Package 1 (WP1) of the **Digital Footprint Fusion & Analysis Platform (DFAP)** creates an auditable, deterministic, reproducible, and research-grade trusted data foundation. WP1 ingests heterogeneous digital footprints (CDR, IPDR, Banking, Social), validates row accountability, generates cryptographic evidence hashes, resolves entity identity via Splink Fellegi-Sunter probabilistic linkage, and serializes frozen Parquet contract outputs for downstream consumption.

```
+------------------+     +------------------------+     +--------------------------+
|  Heterogeneous   | --> |  Row Accountability    | --> |  Cryptographic Evidence  |
|  CSV/JSON Files  |     |  & Rejection Engine    |     |  SHA-256 Hash Engine     |
+------------------+     +------------------------+     +--------------------------+
                                                                     |
                                                                     v
+------------------+     +------------------------+     +--------------------------+
| Frozen Parquet   | <-- | 5-Stage Splink DuckDB  | <-- |  Canonical Event Stream  |
| Output Contracts |     |  Fellegi-Sunter Engine |     |  (UUID5 Deterministic)   |
+------------------+     +------------------------+     +--------------------------+
```

---

## 2. Frozen Downstream Output Contracts

WP1 guarantees strict, unalterable schema contracts for downstream members:

### 2.1 `canonical_events.parquet`
* **`event_id`**: Deterministic UUID5 string (`EVT_...`) computed from `UUID5(namespace, source_file:source_row_index:schema_version)`
* **`timestamp`**: UTC ISO-8601 normalized string
* **`actor_id`**: Primary actor identifier string
* **`target_id`**: Primary target identifier string (or `null` if event has no target)
* **`event_type`**: Frozen vocabulary (`CALL`, `IP_SESSION`, `TRANSACTION`, `LOGIN`, `SOCIAL`, `DEVICE_EVENT`, `LOCATION_EVENT`)
* **`source_domain`**: Frozen domain (`CDR`, `IPDR`, `BANK`, `SOCIAL`)
* **`attributes`**: Serialized JSON string preserving domain-specific metadata
* **`sha256_hash`**: SHA-256 evidence hash linking to `provenance_ledger.parquet`

### 2.2 `provenance_ledger.parquet`
* **`sha256_hash`**: Deterministic SHA-256 evidence hash of canonical source row
* **`source_id`**: Source domain identifier (`CDR`, `IPDR`, `BANK`, `SOCIAL`)
* **`source_file`**: Raw input filename
* **`source_row_index`**: 0-based row index in raw source file
* **`ingestion_timestamp`**: UTC timestamp of pipeline execution
* **`schema_version`**: Frozen schema version string (`WP1.1`)

### 2.3 `resolved_entities.parquet`
* **`canonical_entity_id`**: Reproducible entity cluster ID string (`ENT_...`)
* **`raw_identifier`**: Primary raw identifier associated with the entity
* **`identifier_type`**: `PHONE`, `IP`, `ACCOUNT`, `HANDLE`, `USER_ID`
* **`match_confidence`**: Confidence probability threshold
* **`match_method`**: Linkage method (`EXACT`, `PROBABILISTIC`)
* **`match_status`**: Match decision status (`CONFIRMED`)
* **`evidence`**: JSON string summarizing source domain event counts and sample evidence hashes

---

## 3. WP1 Audit & Reproducibility Artifacts

### 3.1 `entity_matches.parquet` (Audit Artifact)
Tracks all pairwise candidate evaluation decisions:
`match_id`, `left_record_id`, `right_record_id`, `match_probability`, `match_weight`, `blocking_rule`, `comparison_summary`, `match_method`, `match_status`, `decision_reason`, `model_version`.

### 3.2 `wp1_manifest.json` (Execution Report)
Contains complete pipeline execution provenance:
`run_id`, `schema_version`, `pipeline_version`, `model_version`, `config_hash`, `input_files`, `input_file_hashes`, `row_counts`, `accepted_counts`, `rejected_counts`, `entity_count`, `match_counts`, `thresholds`, `validation_reports`, `created_at`.

---

## 4. Cryptographic Row Hashing Design

WP1 computes **row-level cryptographic evidence hashes** for every accepted input row.

```json
{
  "schema_version": "WP1.1",
  "source_file": "cdr_records.csv",
  "source_row_index": 0,
  "row": {
    "call_id": "CDR_1001",
    "caller_num": "+1-555-0101",
    "duration_sec": "180"
  }
}
```

The payload is serialized using sorted keys, compact separators `(',', ':')`, and UTF-8 encoding, then hashed with SHA-256:
$$\text{sha256\_hash} = \text{SHA256}(\text{UTF8}(\text{CanonicalJSON}))$$

> [!NOTE]
> These SHA-256 hashes represent row-level evidence fingerprints. They commit to exact source row contents. A full Merkle tree/root construction is a downstream member responsibility.

---

## 5. Validation Rules & Row Accountability

Every input row is tracked throughout ingestion:
- **Received Rows**: Total raw rows read from file.
- **Accepted Rows**: Passed all schema, data type, numeric, IP format, and domain checks.
- **Rejected Rows**: Logged with explicit rejection reason codes (`MISSING_REQUIRED_FIELD`, `INVALID_TIMESTAMP`, `INVALID_IP`, `INVALID_NUMERIC`, `INVALID_DURATION`, `DUPLICATE_SOURCE_ROW`, `INVALID_EVENT_TYPE`).

No row is silently discarded.

---

## 6. Entity Resolution Methodology

WP1 follows a strict 5-stage conceptual entity resolution architecture based on Fellegi-Sunter theory executing over DuckDB via Splink 4.x:

1. **Stage 1: Deterministic Evidence**: Exact authorized identifier matches are tagged as `match_method = EXACT`, `match_status = CONFIRMED`.
2. **Stage 2: Candidate Generation**: Blocking rules (`ip_subnet`, `actor_id`, `device_id`) reduce pairwise search space.
3. **Stage 3: Probabilistic Scoring**: Splink expectation-maximization estimates $m$ and $u$ parameters over comparison features (Jaro-Winkler string distance on names, exact matches on IDs/subnets).
4. **Stage 4: Decision Status Classification**: Pairwise candidate matches are categorized as:
   - `CONFIRMED` ($\text{probability} \ge 0.85$ or `EXACT`)
   - `POSSIBLE` ($0.60 \le \text{probability} < 0.85$)
   - `REJECTED` ($\text{probability} < 0.60$)
5. **Stage 5: Auditable Clustering**: Clusters are formed **only** from `CONFIRMED` match pairs. `POSSIBLE` matches remain unmerged to preserve identity uncertainty.

> [!IMPORTANT]
> Similarity creates candidates; evidence creates confidence. A string similarity score like Jaro-Winkler $\ge 0.85$ is one feature, not an automatic identity decision.

---

## 7. Gate 1 Acceptance Criteria

WP1 passes Gate 1 when all the following criteria are satisfied:
1. 100% accepted rows have SHA-256 evidence hashes in `provenance_ledger.parquet`.
2. 0 duplicate event IDs across canonical events.
3. 0 orphan provenance references.
4. 0 invalid event types (strictly using frozen vocabulary).
5. All timestamps normalized to UTC ISO-8601 format.
6. Exact compliance with frozen Parquet output schemas.
7. Pairwise match audit trail preserved in `entity_matches.parquet`.
8. Known positive entity matches recovered.
9. Known negative entity matches (e.g. shared household IP/device) kept separate.
10. Identity uncertainty preserved for `POSSIBLE` matches.
11. 100% deterministic reproducibility across repeated executions.
12. Full pytest test suite passing.
