# DFAP Member 1 — Error Analysis & Failure-Mode Defenses (RC2)

**Author**: Sam Roger X  
**Component**: DFAP WP1 — Trusted Data Foundation & Entity Resolution (M1–M3)  
**Date**: September 2026 (Release Candidate 2)  

---

## 1. Dominant False-Match & False-Non-Match Error Mechanisms

### 1.1 Dominant False-Non-Match Mechanism (Under-Merging)
On the expanded 300-pair benchmark, the dominant source of False Negatives (85 pairs at threshold $0.85$) arises from:
1. **Noisy Name Typos & Name Abbreviations**: In the absence of an exact `actor_id` match, single-token typos or single-letter initials produce match probabilities in the range $0.33 \dots 0.49$. Under the strict confirmed operating threshold ($\tau = 0.85$), these pairs are classified as `POSSIBLE` or `REJECTED` to prevent premature graph mutation.
2. **Missing Infrastructure Evidence**: When two records share similar names but lack corroborating device or telecom identifiers, the Fellegi-Sunter log-likelihood score does not reach the confirmation threshold.

*Architectural Policy*: This is an intentional design choice for intelligence-grade analytics. In DFAP, false positive merges (contaminating identity graphs) are considered catastrophic, whereas false non-matches remain available in `entity_matches.parquet` for human analyst review.

### 1.2 Dominant False-Match Prevention (Over-Merging Defense)
The system achieves a **0.0000 False Match Rate (0 false positive merges)** across all 145 negative pairs on the benchmark:
- **Household IP Subnets**: Distinct spouses sharing `192.168.100.0/24` are separated ($P < 0.01$).
- **Shared Public Kiosks**: Multiple patrons using `DEV_SHARED_KIOSK` are kept distinct ($P = 0.0184 < 0.85$).
- **Common Surnames**: Distinct customers sharing common surnames shopping at the same merchant are isolated.

---

## 2. Failure-Mode Defenses & Safe Fallbacks

| Injected Failure Mode | Unmitigated Danger | DFAP Safe Behavior | Audit & Recovery Mechanism |
|---|---|---|---|
| **Corrupted / Truncated Source File** | Pipeline crashes mid-batch, corrupting partial database. | **Fail-Safe Row Isolation**: Row-level validation catches corrupt row, records `MISSING_REQUIRED_FIELD` / `INVALID_NUMERIC`, and accepts valid rows. | Rejection log generated in validation report. |
| **Impossible / Future Timestamps** | Chronological anomaly, time-travel causal leaks. | Rejection with `INVALID_TIMESTAMP`. | Row rejected; provenance ledger records non-inclusion. |
| **Single-Byte Bit Rot / Tamper** | Fraudulent modification of canonical attributes post-ingestion. | Cryptographic verification failure on SHA-256 hash check. | Audit ledger flags mismatch; artifact rejected. |
| **Splink EM Numerical Divergence** | Expectation-Maximisation fails to converge or DuckDB backend issues warning. | **Deterministic Fallback**: Pipeline catches divergence, defaults to exact-evidence matching, logs explicit warning, and prevents unhandled exception. | `model_version` and `match_method="EXACT"` recorded in `entity_matches.parquet`. |
| **Zero-Row Input File** | Downstream graph construction crashes on empty Parquet schema. | **Zero-Row Schema Export**: Generates empty Parquet files preserving exact column types and headers. | Handled gracefully with zero errors. |

---

## 3. Empirical Limitations & Operating Guidelines

1. **Benchmark Scope**: All reported performance metrics are **SUPPORTED ON CURRENT BENCHMARK** ($N=300$ pairs across 4 difficulty regimes).
2. **Operating Threshold Policy**: The production confirmed threshold of $0.85$ is an **empirical operating point** chosen to strictly eliminate false positive merges ($\text{Precision}=100\%$). For recall-oriented discovery pipelines, the threshold can be lowered to $0.40$ ($\text{Recall}=68.39\%$, $\text{Precision}=97.25\%$).
3. **Cryptographic Provenance**: DFAP provides **row-level cryptographic provenance** via per-row SHA-256 hashing. It does not implement or claim Merkle tree data structures.
