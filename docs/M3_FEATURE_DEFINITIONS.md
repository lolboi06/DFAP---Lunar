# DFAP Member 3 — Feature & Score Definitions

**Author**: Sam Roger X  
**Component**: DFAP WP3 — Intelligence & Research Layer (M8–M11)  
**Date**: September 2026  

---

## 1. Overview & Semantic Classifications

DFAP Member 3 extracts, computes, and fuses features and anomaly signals across M8 (Behavioral Baselines), M9 (Multi-Level Anomalies), M10 (Temporal Sequences), and M11 (Cross-Domain Fusion).

### Strict Output Semantics
* **`score`**: Bounded or unbounded numerical indicator (higher indicates greater abnormality).
* **`distance` / `deviation`**: Non-probabilistic metric distance or scale-normalized deviation (e.g. Robust-Z, DTW distance).
* **`belief`**: Evidential mass assignment under Dempster-Shafer theory ($\text{Bel}(A) \in [0, 1]$), reflecting degree of direct evidential support. **Not a Bayesian probability**.
* **`probability`**: Strictly reserved for calibrated logistic regression outputs calibrated via Platt scaling (`CalibratedClassifierCV(method='sigmoid')`).
* **`status`**: Fixed to **`AI_GENERATED_LEAD`** across all anomaly and finding contracts.

---

## 2. M8 — Behavioral Baseline Features (`baselines.parquet`)

| Feature Column | Type | Mathematical Definition | Missing / Edge-Case Handling |
|---|---|---|---|
| `baseline_center` | `float64` | $\text{median}(X) = \text{Q}_{50}(X)$ over historical observations $X$ strictly prior to $t$. | If $|X|=0$, equals observed value $x_t$. |
| `baseline_scale` | `float64` | $1.4826 \cdot \text{MAD}(X) + \epsilon$, where $\text{MAD} = \text{median}(\|X - \text{median}(X)\|), \epsilon = 10^{-9}$. | If $|X| < 1$, equals $\epsilon$. |
| `robust_z` | `float64` | $\frac{x_t - \text{baseline\_center}}{\text{baseline\_scale}}$ | If $|X|=0$, returns $0.0$. |
| `ewma` | `float64` | $\text{EWMA}_t = \alpha x_t + (1 - \alpha) \text{EWMA}_{t-1}, \quad \alpha = 0.3$ | Initialized to $x_0$ at $t=0$. |
| `percentile` | `float64` | $\frac{1}{\|X\|} \sum_{x_i \in X} \mathbb{I}(x_i \le x_t) \times 100\%$ | Returns `NaN` if $\|X\| < 3$. |
| `q25` | `float64` | 25th percentile ($\text{Q}_{25}(X)$) | Equals `baseline_center` if $\|X\| < 3$. |
| `q75` | `float64` | 75th percentile ($\text{Q}_{75}(X)$) | Equals `baseline_center` if $\|X\| < 3$. |
| `rolling_mean` | `float64` | Arithmetic mean of up to 10 most recent historical observations. | Equals `baseline_center` if $\|X\| < 3$. |
| `history_count` | `int64` | Number of historical observations $\|X\|$. | Starts at $0$. |
| `baseline_status` | `string` | Categorical regime: `COLD_START` ($\|X\|<3$), `LOW_HISTORY` ($3 \le \|X\| < 10$), `STABLE_BASELINE` ($\|X\| \ge 10$). | Deterministic thresholding. |

---

## 3. M9 — Anomaly Engine Output (`anomalies/anomalies.parquet`)

| Column | Type | Description |
|---|---|---|
| `anomaly_id` | `string` | Unique deterministic identifier `ANO_<UUID12>`. |
| `entity_id` | `string` | Resolved entity identifier `ENT_<UUID12>`. |
| `timestamp_start` | `string` | ISO-8601 UTC timestamp of earliest contributing event. |
| `timestamp_end` | `string` | ISO-8601 UTC timestamp of latest contributing event. |
| `anomaly_level` | `string` | Hierarchy level: `EVENT`, `ENTITY`, `RELATIONSHIP`, `COMMUNITY`, `SUBGRAPH`, `SEQUENCE`. |
| `anomaly_type` | `string` | Non-criminal analytical typology: `UNUSUAL_EVENT`, `BEHAVIORAL_DEVIATION`, `RELATIONSHIP_NOVELTY`, `COMMUNITY_DEVIATION`, `SUBGRAPH_DEVIATION`, `SEQUENCE_DEVIATION`. |
| `score` | `float64` | Composite anomaly metric $\text{rule\_score} + 0.5 \cdot \text{baseline\_dev}$. |
| `score_type` | `string` | Fixed to `"COMPOSITE_ANOMALY_SCORE"`. |
| `component_scores` | `string` (JSON) | Serialized dict containing decoupled signals: `rule_score`, `baseline_deviation_score`, `isolation_forest_score`, `graph_novelty_score`, `relationship_score`. |
| `reasons` | `string` (JSON) | Array of human-readable deterministic explanations and triggering conditions. |
| `event_ids` | `string` (JSON) | List of constituent canonical `event_id`s. |
| `graph_refs` | `string` (JSON) | List of graph features contributing to structural assessment. |
| `evidence_refs` | `string` (JSON) | List of SHA-256 provenance hashes. |
| `model_version` | `string` | Model version string (`"M9_ANOMALY_v1.0"`). |
| `status` | `string` | Fixed to `"AI_GENERATED_LEAD"`. |

---

## 4. M10 — Temporal Sequence Outputs

### 4.1 Motif Catalog (`motif_catalog.json`)
* **`MOT_001` (CALL_THEN_TRANSFER)**: $\text{CALL} \to \text{TRANSACTION}$, $\Delta t \le 3600\text{s}$, gap $\in [0, 3600\text{s}]$.
* **`MOT_002` (LOGIN_THEN_TRANSACTION)**: $\text{LOGIN} \to \text{TRANSACTION}$, $\Delta t \le 1800\text{s}$, gap $\in [0, 1800\text{s}]$.
* **`MOT_003` (CALL_IP_LOGIN_TRANSFER)**: $\text{CALL} \to \text{IP\_SESSION} \to \text{LOGIN} \to \text{TRANSACTION}$, $\Delta t \le 7200\text{s}$.
* **`MOT_004` (RAPID_MULTI_TRANSACTION)**: $\text{TRANSACTION} \to \text{TRANSACTION}$, $\Delta t \le 300\text{s}$.

### 4.2 Sequence Matches & DTW (`sequences/*.parquet`)
* **`sequence_score`**: $\exp(-\text{NormDTW}) \in (0, 1]$, where $\text{NormDTW} = \frac{\text{DTW}(\mathbf{U}, \mathbf{V})}{|\text{WarpingPath}|}$.
* **`dtw_distance`**: Raw squared Euclidean DP alignment cost $D(m, n)$.
* **`gaps_seconds`**: Array of inter-event time deltas in seconds.

---

## 5. M11 — Cross-Domain Fusion Output (`findings/findings.parquet`)

| Column | Type | Semantic Definition |
|---|---|---|
| `finding_id` | `string` | Unique identifier `FND_<UUID12>`. |
| `entity_id` | `string` | Canonical entity identifier. |
| `anomaly_type` | `string` | Primary typology lead. |
| `domain_scores` | `string` (JSON) | Preserved per-domain activity scores (`telecom`, `financial`, `social`, `behavior`, `graph`, `temporal`). |
| `composite_score` | `float64` | Weighted fusion output $\in [0, 1]$ (**not a probability**). |
| `belief_anomalous` | `float64` | Dempster-Shafer belief mass $\text{Bel}(\text{ANOMALOUS}) \in [0, 1]$. |
| `belief_normal` | `float64` | Dempster-Shafer belief mass $\text{Bel}(\text{NORMAL}) \in [0, 1]$. |
| `uncertainty` | `float64` | Uncommitted evidential mass $m(\Theta) \in [0, 1]$. |
| `conflict` | `float64` | Dempster-Shafer conflict metric $K \in [0, 1]$. |
| `calibrated_probability` | `float64` / `null` | Sigmoid-calibrated posterior probability from logistic fusion. |
| `status` | `string` | `"AI_GENERATED_LEAD"`. |
