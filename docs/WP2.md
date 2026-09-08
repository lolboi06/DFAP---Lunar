# DFAP Member 2: Temporal Graph & Domain Analytics (M4-M7)

## Overview
This document specifies the ontology, graph model, and domain features implemented in Member 2 (WP2) of the Digital Footprint Fusion & Analysis Platform (DFAP).

**Upstream Authority**: Member 2 strictly consumes the frozen data products of WP1.

---

## 1. M4 - Temporal Heterogeneous Graph Ontology

### 1.1 Node Types
Derived directly from WP1 identifier types where supported.
- `Person`
- `Phone`
- `Device`
- `IP`
- `Account`
- `Merchant`
- `SocialAccount`
- `Location`
- `Event`

### 1.2 Edge Types & Evidence Boundaries
Edges represent relationships. An edge is `OBSERVED` if directly supported by source data. It is `INFERRED` if derived.

- **`OBSERVED` Relationships (Entity <-> Event)**:
  - When an entity's raw identifier appears directly in an event (e.g. `CALLS`, `CONNECTS_TO`, `LOGGED_IN_FROM`, `SENDS`, `RECEIVES`, `POSTED`).
  - Evidence: The event itself (`event_id`, `sha256_hash`).

- **`INFERRED` Relationships (Entity <-> Entity)**:
  - When two entities share infrastructure (e.g. `USES` same device, `ASSOCIATED_WITH` same IP).
  - Evidence: The events that form the associative bridge.

### 1.3 Formal Temporal Semantics
- **Event Time**: The specific timestamp `t` at which an event occurred.
- **Relationship Validity**: Defined by `first_seen` and `last_seen` timestamps.
- **Paths**: A valid temporal path must satisfy `t1 <= t2 <= ... <= tn`.
- **Boundaries**: Temporal queries use inclusive bounds: `start_time <= timestamp <= end_time`.
