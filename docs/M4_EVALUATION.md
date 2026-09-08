# DFAP Member 4 (WP4) — Scientific Evaluation & Traceability Report (RC1)

**Author**: Sam Roger X  
**Component**: DFAP WP4 — Evidence & Provenance Engine (M12) & Investigation Workspace (M13)  
**Date**: September 2026 (Release Candidate 1)  

---

## 1. Upstream Contract & Integrity Audit

Prior to and following all Member 4 operations, cryptographic SHA-256 hashes of all frozen upstream artifacts were verified for 100% byte-for-byte immutability:

| Upstream Artifact File | Frozen SHA-256 Digest | Status | Mutation Count |
|---|---|---|---|
| `canonical_events.parquet` | `a90e1bf43ad413dc52633237690ae7e55ada89ddeb3005fa218c3fd01d866a63` | **MATCH / FROZEN** | 0 |
| `resolved_entities.parquet` | `1eeff0fbb82b6cd9517b71a3f561e5a0de36f51eddeba15acf424ae666ee3096` | **MATCH / FROZEN** | 0 |
| `provenance_ledger.parquet` | `6ee4a80405b8d0ff8768077d32a41102cb0a60630b7c713c1a48223a363d181e` | **MATCH / FROZEN** | 0 |
| `m3/findings/findings.parquet` | `e25aeb8844f2955bbc0a1336a2e3e115b469d097a28759836ce6d63359723d86` | **MATCH / FROZEN** | 0 |
| `graph_features.parquet` | `8c47f9f220ecda1d798c414995f3661eb1bb32fb77c5950a416b9cb8732c3f87` | **MATCH / FROZEN** | 0 |

---

## 2. Evidence Chain Traceability Evaluation

Evidence resolution was evaluated across all 12 production findings in `output/m3/findings/findings.parquet`:

| Finding ID | Entity Target | Anomaly Type | Evidence Events Resolved | SHA-256 Validated | Source Row Resolved | Status |
|---|---|---|---|---|---|---|
| `FND_F7F1AEA41A06` | `ENT_0F0FC38C24C0539E` | `BEHAVIORAL_DEVIATION` | 1 (`EVT_80E854E8D3B557DC`) | Yes (`e248c66d...`) | `banking_records.csv:1` | **FULLY_EVIDENCED** |
| `FND_94968EA872E3` | `ENT_10235790E9A254DE` | `BEHAVIORAL_DEVIATION` | 1 (`EVT_3ECE757380845FF1`) | Yes (`041fb8d8...`) | `cdr_telephony.csv:4` | **FULLY_EVIDENCED** |
| `FND_149CD13D3B51` | `ENT_2270FD1F3B6651E0` | `BEHAVIORAL_DEVIATION` | 1 (`EVT_DF7BCFCE2C145FE0`) | Yes (`e885c392...`) | `ipdr_traffic.csv:2` | **FULLY_EVIDENCED** |
| `FND_B2CA1BD09689` | `ENT_3C15D5F0F5D65A0D` | `BEHAVIORAL_DEVIATION` | 1 (`EVT_23EC48873E425F81`) | Yes (`b19c4342...`) | `cdr_telephony.csv:3` | **FULLY_EVIDENCED** |
| `FND_A93C80CE4D14` | `ENT_50D4D6B5EE7D5A46` | `BEHAVIORAL_DEVIATION` | 1 (`EVT_9553EDBA30315C2F`) | Yes (`e77373f7...`) | `ipdr_traffic.csv:1` | **FULLY_EVIDENCED** |
| `FND_74BCFBBD0D62` | `ENT_67D77F1778135AC3` | `BEHAVIORAL_DEVIATION` | 1 (`EVT_04F34A81CD115DAA`) | Yes (`544ca939...`) | `banking_records.csv:2` | **FULLY_EVIDENCED** |
| `FND_31481177659F` | `ENT_7B0BD795B5B35C15` | `BEHAVIORAL_DEVIATION` | 1 (`EVT_F20FA7702FF05F9A`) | Yes (`3e0bf037...`) | `cdr_telephony.csv:5` | **FULLY_EVIDENCED** |
| `FND_698AE218CA14` | `ENT_7F9EBE32C8C6544D` | `BEHAVIORAL_DEVIATION` | 1 (`EVT_D5954B52825B5B53`) | Yes (`409323df...`) | `banking_records.csv:3` | **FULLY_EVIDENCED** |
| `FND_37F9DCD6ECB6` | `ENT_95EF612083D6560A` | `BEHAVIORAL_DEVIATION` | 1 (`EVT_6EE6134D09D558FE`) | Yes (`ff994645...`) | `cdr_telephony.csv:2` | **FULLY_EVIDENCED** |
| `FND_7CF8427F2A28` | `ENT_A688DFEFBF665EAA` | `BEHAVIORAL_DEVIATION` | 1 (`EVT_44BDCC65BF2C5E03`) | Yes (`b4b60098...`) | `social_network.csv:1` | **FULLY_EVIDENCED** |
| `FND_477F5C7C33D8` | `ENT_B5CBA5E19A62580E` | `BEHAVIORAL_DEVIATION` | 1 (`EVT_4818EC1A81165A92`) | Yes (`0a0e98c9...`) | `cdr_telephony.csv:1` | **FULLY_EVIDENCED** |
| `FND_913BCE0238C9` | `ENT_C0FF0673327653F7` | `BEHAVIORAL_DEVIATION` | 1 (`EVT_4B3E03598A82597A`) | Yes (`7e1da5e8...`) | `social_network.csv:2` | **FULLY_EVIDENCED** |

*Result: 100% of production findings resolve down to original CSV source files and row indices without missing or broken links.*

---

## 3. Timeline Extraction & Boundary Verification

| Test Scenario | Window Specification | Expected Events | Observed Events | Ordering Verified |
|---|---|---|---|---|
| **Unbounded Window** | `start=None`, `end=None` | Complete entity event set ($N=1$) | $N=1$ | Deterministic `(timestamp, event_id)` |
| **Inclusive Start Boundary** | `start="2026-09-01T10:30:00+00:00"`, `end=None` | $N=1$ | $N=1$ | Verified |
| **Exclusive End Boundary** | `start="2026-09-01T10:30:00+00:00"`, `end="2026-09-01T10:30:00+00:00"` | $N=0$ (Strictly exclusive) | $N=0$ | Verified |
| **Reversed Window** | `start="2026-09-02"`, `end="2026-09-01"` | Fail Closed (`INVALID_TIME_RANGE`) | `WorkspaceError` raised | Verified |

---

## 4. Network 2-Hop Bounded BFS Verification

| Entity Root | Requested Hops | Independent BFS Max Distance | Extracted Nodes | Extracted Edges | Cytoscape Serialized |
|---|---|---|---|---|---|
| `ENT_0F0FC38C24C0539E` | `0` | $0$ | 1 | 0 | Validated |
| `ENT_0F0FC38C24C0539E` | `1` | $1$ | 2 | 1 | Validated |
| `ENT_0F0FC38C24C0539E` | `2` | $1 \le 2$ | 2 | 1 | Validated |
| `ENT_0F0FC38C24C0539E` | `3` | $> 2$ (Violation) | Rejected | Rejected | `INVALID_HOP_COUNT` |
| `ENT_0F0FC38C24C0539E` | `-1` | $< 0$ (Violation) | Rejected | Rejected | `INVALID_HOP_COUNT` |

---

## 5. Byte-for-Byte Serialization Determinism

Repeated executions across multiple processes and instances confirmed **100% byte equality**:
- `EvidenceChain.to_canonical_json()`: 0 byte variance across repeated invocations.
- `WorkspaceState.to_canonical_json()`: 0 byte variance across repeated invocations.
- `CytoscapeGraph.to_canonical_json()`: 0 byte variance across repeated invocations.
