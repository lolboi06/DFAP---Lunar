# DFAP Member 4 (WP4) — Research Methodology & Backend Architecture

**Author**: Sam Roger X  
**Component**: DFAP WP4 — Evidence & Provenance Engine (M12) & Investigation Workspace (M13)  
**Date**: September 2026 (Release Candidate 1)  

---

## 1. Architectural Overview & Boundary Definitions

Work Package 4 (Member 4) provides the deterministic analytical workspace, evidence resolution engine, and formal provenance layer for the Digital Footprint Analytics Platform (DFAP).

### 1.1 Architectural Scope & Core Invariants
- **Backend/Console Scope**: Implements pure backend state management, evidence chaining, timeline extraction, bounded graph extraction, and CLI/API interfaces. Zero UI code (Streamlit / Cytoscape.js frontend deferred to UI consumer layer).
- **Read-Only Invariant**: Treats all upstream artifacts from Member 1 (Trusted Data & ER), Member 2 (Temporal Graph & Domain Features), and Member 3 (Anomaly Engine & Fusion) as frozen, immutable inputs.
- **Fail-Closed Policy**: If any upstream artifact, schema, evidence reference, or cryptographic hash fails verification, all operations fail closed with explicit typed errors.
- **Member 5 Security Boundary**: Exposes strictly scoped, read-only structured retrieval APIs. No LLM integration or natural language conclusions are generated in WP4.

```
+-----------------------------------------------------------------------------------+
|                           FROZEN UPSTREAM CONTRACTS                               |
| canonical_events.parquet | provenance_ledger.parquet | m3/findings/findings.parquet|
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
|                       UPSTREAM INTEGRITY & SCHEMA VALIDATION                      |
|                  SHA-256 Hash Verification  |  Schema Conformance                 |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
|               M12: EVIDENCE ENGINE & W3C PROV-O COMPLIANCE LAYER                  |
|    Finding -> Feature -> Evidence Ref -> Canonical Event -> SHA256 -> Source Row   |
|         Deterministic URIs | Standard PROV-O Predicates | Complete Audit Chain    |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
|               M13: INVESTIGATION WORKSPACE & GRAPH BACKEND LAYER                  |
|   Unified Timeline [start, end) | Bounded 2-Hop BFS Subgraph | Cytoscape Payload  |
|            Centralized State Manager | Deterministic Canonical JSON                |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
|                        MEMBER 5 SECURE RETRIEVAL APIS & CLI                       |
|   get_evidence_chain() | get_events() | get_entity_timeline() | get_entity_subgraph|
+-----------------------------------------------------------------------------------+
```

---

## 2. Mathematical & Formal Proof of Evidence Traceability

For any finding $F_i \in \text{Findings}$, the evidence resolution operator $\mathcal{E}(F_i)$ deterministically yields an ordered sequence of verified tuples:
$$\mathcal{E}(F_i) = \Big\langle \big( \text{Feat}_j, \text{EvRef}_k, \text{Evt}_m, h_m, \text{Prov}_m, S_m, R_m \big) \Big\rangle$$
Where:
1. $\text{Feat}_j \in F_i.\text{graph\_refs} \cup F_i.\text{domain\_scores}$
2. $\text{Evt}_m \in \text{CanonicalEvents}$ such that $\text{Evt}_m.\text{event\_id} = \text{EvRef}_k$
3. $h_m = \text{SHA-256}(\text{CanonicalJSON}(\text{Evt}_m))$
4. $\text{Prov}_m \in \text{ProvenanceLedger}$ such that $\text{Prov}_m.\text{sha256\_hash} = h_m$
5. $S_m = \text{Prov}_m.\text{source\_file}$ (Raw ingested CSV/file)
6. $R_m = \text{Prov}_m.\text{source\_row\_index}$ (Exact integer row in $S_m$)

**Completeness Classification Rule**:
$$\text{Status}(F_i) = \begin{cases} 
\text{FULLY\_EVIDENCED} & \text{if } \forall k, \text{EvRef}_k \text{ resolves to valid } (h_m, \text{Prov}_m) \\
\text{PARTIALLY\_EVIDENCED} & \text{if } \exists k \text{ resolving and } \exists k' \text{ unresolvable} \\
\text{UNREFERENCED\_OR\_BROKEN} & \text{otherwise}
\end{cases}$$

---

## 3. Timeline Half-Open Window Semantics

The timeline extraction operator $\mathcal{T}(E, t_s, t_e)$ for entity $E$ over temporal bounds $[t_s, t_e)$ is defined as:
$$\mathcal{T}(E, t_s, t_e) = \{ e \in \text{CanonicalEvents} \mid e.\text{actor} = E \lor e.\text{target} = E \land t_s \le e.\text{timestamp} < t_e \}$$
- **Start Boundary**: $t_s \le e.\text{timestamp}$ (Inclusive)
- **End Boundary**: $e.\text{timestamp} < t_e$ (Strictly Exclusive)
- **Determinism**: Primary sort on $e.\text{timestamp}$ (ISO-8601 UTC), secondary sort on $e.\text{event\_id}$.

---

## 4. Bounded 2-Hop Network Subgraph Semantics

For an entity root vertex $v_0 \in V$, the subgraph operator $\mathcal{G}_{\le 2}(v_0)$ extracts the induced subgraph $G[V_{\le 2}]$ where:
$$V_{\le 2} = \{ v \in V \mid \text{dist}_G(v_0, v) \le 2 \}$$
- **Independent Distance Verification**: Distance is independently verified via breadth-first search on unweighted graph geodesics.
- **Status Preservation**: All edges explicitly retain `relationship_status` as either `OBSERVED` or `INFERRED`.
- **Serialization**: Converted into canonical sorted Cytoscape JSON payload format.
