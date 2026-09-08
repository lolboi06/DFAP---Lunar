# DFAP Member 4 (WP4) — Error Analysis & Fail-Closed Taxonomy (RC1)

**Author**: Sam Roger X  
**Component**: DFAP WP4 — Evidence & Provenance Engine (M12) & Investigation Workspace (M13)  
**Date**: September 2026 (Release Candidate 1)  

---

## 1. Controlled Error Taxonomy & Fail-Closed Defenses

Member 4 strictly defines and enforces typed error codes across all operations. In the presence of corrupted or missing links, the system fails closed rather than producing unverified or speculative intelligence:

| Error Code | Trigger Condition | System Defense Mechanism |
|---|---|---|
| `UNKNOWN_FINDING` | Requesting evidence for an unindexed or nonexistent finding ID. | Raises `EvidenceChainError(UNKNOWN_FINDING)` immediately; zero fabricated evidence. |
| `MISSING_FEATURE` | A finding references an analytical feature not present in feature stores. | Recorded in `issues` list; status downgraded to `PARTIALLY_EVIDENCED`. |
| `MISSING_EVIDENCE_REF` | A finding contains empty or unresolvable evidence reference pointers. | Status classified as `UNREFERENCED_OR_BROKEN`. |
| `MISSING_EVENT` | An `event_id` in evidence references is absent from `canonical_events.parquet`. | Recorded in `issues`; status downgraded. |
| `MISSING_PROVENANCE` | A canonical event's SHA-256 hash is absent from `provenance_ledger.parquet`. | Recorded in `issues`; source metadata labeled as unresolvable. |
| `INVALID_SHA256` | Recomputed canonical event hash diverges from recorded hash. | Cryptographic verification fails closed with `INVALID_SHA256`. |
| `DUPLICATE_EVIDENCE_REF` | Redundant evidence references present in finding metadata. | Flagged in `issues`; duplicates removed during canonical sorting. |
| `DUPLICATE_EVENT_REF` | Duplicate event IDs referenced in finding. | Deduplicated deterministically with issue recorded. |
| `INVALID_HOP_COUNT` | Querying subgraph with $\text{hops} < 0$ or $\text{hops} > 2$. | Raises `WorkspaceError(INVALID_HOP_COUNT)` with zero graph traversal. |
| `INVALID_TIME_RANGE` | Querying timeline with $\text{start} > \text{end}$ or malformed ISO timestamp. | Raises `WorkspaceError(INVALID_TIME_RANGE)`. |
| `UPSTREAM_INTEGRITY_ERROR` | Upstream parquet artifact missing or SHA-256 altered. | Service initialization fails closed with `UpstreamIntegrityError`. |
| `UNKNOWN_RELATIONSHIP_STATUS` | Graph edge contains status other than `OBSERVED` or `INFERRED`. | Raises `WorkspaceError(UNKNOWN_RELATIONSHIP_STATUS)`. |

---

## 2. Security Boundaries for Future Member 5 (Copilot)

1. **Strict Read-Only Enforcement**: Member 5 interacts strictly via structured getters (`get_evidence_chain`, `get_events`, `get_entity_timeline`, `get_entity_subgraph`, `get_finding`).
2. **No Free-Form Database Queries**: Member 5 is not granted arbitrary SQL or DuckDB execution capabilities.
3. **No Direct Model Mutations**: Member 5 cannot alter feature definitions, weights, or finding statuses directly.
4. **Evidence-Bounded Context**: All context fed to future LLMs or investigators must be grounded strictly within the returned `EvidenceChain` structure.
