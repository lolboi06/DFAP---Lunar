# DFAP MEMBER 2 — FINAL RESEARCH GATE AUDIT

**Date**: 2026-09-01
**Auditor role**: Independent Senior Researcher
**Gate Version**: v2 (Post-Defect-Fix)

## FINAL DECISION

**MEMBER 2 GATE = PASS**

Every requirement was independently verified with concrete evidence.

---

## 1. graph_features.parquet EXISTS

output/graph_features.parquet — EXISTS ✓

---

## 2. REQUIRED GRAPH FEATURES IMPLEMENTED

| Feature | Implemented |
|---------|-------------|
| degree | ✓ |
| weighted_degree | ✓ |
| shared_counterparties | ✓ |
| transaction_path_features | ✓ |

---

## 3. EXACT GRAPH FEATURE DEFINITIONS

### degree(e)
Formula: number of distinct canonical entity neighbors. Undirected. Self-loops excluded. Multiple events between same pair count once.

### weighted_degree(e)
Formula: sum of transaction amounts for all TRANSACTION events incident to e. BANK domain only. CDR/IPDR units are never mixed.

### shared_counterparties(e)
Formula: max over all u≠e of |Neighbors(e) ∩ Neighbors(u)|. Aggregation: max-pairwise. Documented explicitly.

### transaction_path_features(e)
Formula: count of distinct entities reachable from e via ≤2 TRANSACTION edges (undirected). Strictly bounded. Disconnected = 0.

---

## 4. ACTUAL FEATURE OUTPUT SCHEMA

All four parquets: entity_id (str), feature_name (str), feature_value (float64), window (str), source (str), evidence_refs (object/list).

Null counts: 0 in every column.

---

## 5. FEATURE ROW COUNTS

| File | Rows |
|------|------|
| graph_features.parquet | 32 |
| telecom_features.parquet | 33 |
| financial_features.parquet | 32 |
| social_features.parquet | 6 |

---

## 6. INDEPENDENT EXPECTED-VS-ACTUAL VALIDATION

Controlled graph: A--(100)--B, A--(50)--C, B--(25)--C, C--(10)--D

| Entity | Feature | Expected | Actual | Pass? |
|--------|---------|---------|--------|-------|
| ENT_A | degree | 2.0 | 2.0 | PASS |
| ENT_B | degree | 2.0 | 2.0 | PASS |
| ENT_C | degree | 3.0 | 3.0 | PASS |
| ENT_D | degree | 1.0 | 1.0 | PASS |
| ENT_A | weighted_degree | 150.0 | 150.0 | PASS |
| ENT_B | weighted_degree | 125.0 | 125.0 | PASS |
| ENT_C | weighted_degree | 85.0 | 85.0 | PASS |
| ENT_D | weighted_degree | 10.0 | 10.0 | PASS |
| ENT_A | shared_counterparties | 1.0 | 1.0 | PASS |
| ENT_D | shared_counterparties | 1.0 | 1.0 | PASS |
| ENT_A | transaction_path_features | 3.0 | 3.0 | PASS |
| ENT_D | transaction_path_features | 3.0 | 3.0 | PASS |

Expected values computed manually, independently of the tested functions.

---

## 7. EVIDENCE REFS VALIDITY

Invalid evidence_refs: 0 (expected: 0). All refs exist in canonical_events.parquet.

---

## 8. DETERMINISM

df_run1.equals(df_run2) = True for all four output files. Sorted by [entity_id, feature_name] before export.

---

## 9. COMPLETE TEST RESULTS

Gate suite: 27 passed
Full suite: 41 passed, 0 failed, 0 skipped

---

## 10. WP1 IMMUTABILITY

canonical_events.parquet: a90e1bf43ad413dc52633237690ae7e55ada89ddeb3005fa218c3fd01d866a63
resolved_entities.parquet: 1eeff0fbb82b6cd9517b71a3f561e5a0de36f51eddeba15acf424ae666ee3096
provenance_ledger.parquet: 6ee4a80405b8d0ff8768077d32a41102cb0a60630b7c713c1a48223a363d181e

WP1 was NOT modified.

---

## 11. MEMBER 3 INPUT ARTIFACTS

output/graph_features.parquet     — 32 rows — schema: frozen
output/telecom_features.parquet   — 33 rows — schema: frozen
output/financial_features.parquet — 32 rows — schema: frozen
output/social_features.parquet    —  6 rows — schema: frozen

---

## 12. KNOWN LIMITATIONS

1. shared_counterparties is a max-pairwise scalar, not a full pairwise distribution.
2. transaction_path_features strictly bounded at 2 hops by design.
3. weighted_degree is BANK/TRANSACTION only — unit mixing is prohibited.
4. topic_shift / community_membership are formally documented as UNAVAILABLE (not fabricated).

