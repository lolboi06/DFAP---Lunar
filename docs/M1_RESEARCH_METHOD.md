# DFAP Member 1 — Research Methodology & Theoretical Foundation (RC2)

**Author**: Sam Roger X  
**Component**: DFAP WP1 — Trusted Data Foundation & Entity Resolution (M1–M3)  
**Date**: September 2026 (Release Candidate 2)  

---

## 1. Architectural Overview & Research Scope

Work Package 1 (WP1) forms the foundational trust layer of the Digital Footprint Analytics Platform (DFAP). It encompasses three integrated modules:
1. **M1 Trusted Data Foundation**: High-throughput ingestion, fail-safe row validation, structured rejection accounting, and row-level cryptographic provenance.
2. **M2 Entity Resolution**: Fellegi-Sunter probabilistic record linkage, multi-attribute candidate generation, decision status classification, and confirmed-only graph clustering.
3. **M3 Canonical Event & Temporal Layer**: Schema-strict canonicalization, ISO-8601 UTC temporal normalization, deterministic tie-breaking, and immutable upstream Parquet contract serialization.

```
+--------------------------------------------------------------------------------+
|                             RAW DIGITAL DATA SOURCES                           |
|       (CDR Telephony, IPDR Network, Core Banking, Social Media Telemetry)      |
+--------------------------------------------------------------------------------+
                                       |
                                       v
+--------------------------------------------------------------------------------+
|                        M1: VALIDATION & ACCOUNTABILITY                         |
|   Strict Domain Checks  |  Rejection Taxonomy  |  Row Accountability Invariant |
|               received_rows = accepted_rows + rejected_rows                    |
+--------------------------------------------------------------------------------+
                                       |
                                       v
+--------------------------------------------------------------------------------+
|                       ROW-LEVEL CRYPTOGRAPHIC PROVENANCE                       |
|        SHA-256( CanonicalJSON( schema_v, source_file, row_idx, row_payload ) ) |
+--------------------------------------------------------------------------------+
                                       |
                                       v
+--------------------------------------------------------------------------------+
|                      M2: FELLEGI-SUNTER ENTITY RESOLUTION                      |
|  Stage 1: Deterministic Evidence Extraction (EXACT)                            |
|  Stage 2: Multi-Attribute Candidate Blocking (ip_subnet, actor_id, device_id)  |
|  Stage 3: Splink 4.x Probabilistic Expectation-Maximisation Scoring           |
|  Stage 4: Tri-State Classification (CONFIRMED >= 0.85, POSSIBLE, REJECTED)    |
|  Stage 5: Confirmed-Only Transitive Graph Clustering                           |
+--------------------------------------------------------------------------------+
                                       |
                                       v
+--------------------------------------------------------------------------------+
|                     M3: CANONICAL EVENT & CONTRACT EXPORT                      |
|       canonical_events.parquet | resolved_entities.parquet | provenance_ledger |
+--------------------------------------------------------------------------------+
```

---

## 2. Mathematical & Cryptographic Formulations

### 2.1 Row Accountability Invariant
For any input batch $B$ across supported domains $D \in \{\text{CDR}, \text{IPDR}, \text{BANK}, \text{SOCIAL}\}$:
$$N_{\text{received}}(B) = N_{\text{accepted}}(B) + N_{\text{rejected}}(B)$$
Where every rejected row $r \in R_{\text{rejected}}$ is assigned an immutable reason code from the frozen controlled taxonomy:
$$\text{Taxonomy} = \{\text{MISSING\_REQUIRED\_FIELD}, \text{INVALID\_TIMESTAMP}, \text{INVALID\_IP}, \text{INVALID\_NUMERIC}, \text{INVALID\_DURATION}, \text{DUPLICATE\_SOURCE\_ROW}, \text{INVALID\_EVENT\_TYPE}\}$$

### 2.2 Row-Level Cryptographic Provenance
To ensure tamper-evidence without introducing unverified Merkle-tree abstractions, each accepted record commits to a cryptographic hash:
$$h_i = \text{SHA-256}\Big(\text{CanonicalJSON}\big(\text{schema\_version}, \text{source\_file}, i, \text{clean\_row}(r_i)\big)\Big)$$
Where:
- $\text{CanonicalJSON}$ enforces ASCII encoding, alphanumeric key sorting, and minimal whitespace separators (`','`, `':'`).
- $\text{clean\_row}$ maps nulls/NaNs to `null` and converts primitive scalar types to deterministic UTF-8 strings.
- This construction is strictly documented and tested as **row-level cryptographic provenance**.

### 2.3 Fellegi-Sunter Probabilistic Linkage Model
For record pair $(a, b)$ with comparison vector $\gamma = (\gamma_{\text{name}}, \gamma_{\text{actor}}, \gamma_{\text{ip}}, \gamma_{\text{device}})$:
$$\text{Match Weight } w = \sum_{k} \log_2 \left( \frac{m_k}{u_k} \right)$$
$$\text{Match Probability } P(M|\gamma) = \frac{P(M) \prod_k m_k}{P(M) \prod_k m_k + P(U) \prod_k u_k}$$
Where:
- $m_k = P(\gamma_k | (a, b) \in M)$ (probability comparison state is observed given true match).
- $u_k = P(\gamma_k | (a, b) \in U)$ (probability comparison state is observed given non-match).
- $P(M)$ is estimated via Expectation-Maximisation (EM) across blocked candidate partitions.

---

## 3. Normalization Invariants & Transformations

| Field | Ingestion Transformation | Preservation Guarantee | Classification |
|---|---|---|---|
| `timestamp` | ISO-8601 UTC canonicalization via `pd.to_datetime(ts, utc=True).isoformat()` | Microsecond precision, explicit `+00:00` offset | Semantics-preserving normalization under DFAP policy |
| `actor_id` | Stripped leading/trailing whitespace, zero-width Unicode stripping, uppercase canonicalization | Deterministic identifier equality | Semantics-preserving normalization under DFAP policy |
| `ip_subnet` | CIDR validation via Python `ipaddress` network parser | IPv4/IPv6 subnet routing boundary | Semantics-preserving normalization under DFAP policy |
| `amount` / `duration` | Non-finite / negative rejection, scalar float casting | Strict numeric validation | Semantics-preserving normalization under DFAP policy |
| `attributes` | JSON serialization with `sort_keys=True` | Deterministic byte-for-byte Parquet storage | Semantics-preserving normalization under DFAP policy |

---

## 4. Frozen Output Contracts

1. **`canonical_events.parquet`**:
   - `event_id` (VARCHAR / UUID5 deterministic)
   - `timestamp` (VARCHAR / ISO-8601 UTC)
   - `actor_id` (VARCHAR / Normalized identifier)
   - `target_id` (VARCHAR / Optional normalized target)
   - `event_type` (VARCHAR / Frozen vocabulary)
   - `source_domain` (VARCHAR / CDR, IPDR, BANK, SOCIAL)
   - `attributes` (VARCHAR / Serialized JSON)
   - `sha256_hash` (VARCHAR / Row-level provenance hash)

2. **`provenance_ledger.parquet`**:
   - `sha256_hash`, `source_id`, `source_file`, `source_row_index`, `ingestion_timestamp`, `schema_version`

3. **`resolved_entities.parquet`**:
   - `canonical_entity_id`, `raw_identifier`, `identifier_type`, `match_confidence`, `match_method`, `match_status`, `evidence`

4. **`entity_matches.parquet`** (Audit Trail):
   - `match_id`, `left_record_id`, `right_record_id`, `match_probability`, `match_weight`, `blocking_rule`, `comparison_summary`, `match_method`, `match_status`, `decision_reason`, `model_version`
