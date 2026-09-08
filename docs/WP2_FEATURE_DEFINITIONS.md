# DFAP Member 2 Feature Definitions

This document mathematically and formally defines every feature extracted by Member 2 (M5, M6, M7). 

## 1. M5 Telecom Analytics (CDR/IPDR)

### 1.1 CDR Features
- **call_count(e, w)**
  - *Definition*: Number of `CALL` events for entity $e$ where $start \le t \le end$.
  - *Missing Data*: 0 if no events.
- **unique_contacts(e, w)**
  - *Definition*: Number of distinct target entities interacted with via `CALL`.
  - *Missing Data*: 0 if no events.
- **mean_duration(e, w)**
  - *Definition*: $\frac{\sum duration}{call\_count(e, w)}$.
  - *Zero Denominator*: `0.0`.
- **max_duration(e, w)**
  - *Definition*: $\max(duration)$.
  - *Missing Data*: `0.0`.
- **night_call_ratio(e, w)**
  - *Definition*: $\frac{\text{calls between 22:00 and 06:00 UTC}}{call\_count(e, w)}$.
  - *Zero Denominator*: `0.0`.
- **reciprocity(e, w)**
  - *Definition*: $\frac{\text{mutual\_pairs(e, w)}}{\text{directed\_unique\_pairs(e, w)}}$. A mutual pair is an entity $x$ where $e$ called $x$ AND $x$ called $e$.
  - *Zero Denominator*: `0.0`.
- **burstiness(e, w)**
  - *Definition*: Using the coefficient of variation (CV) of inter-event times ($\Delta t$): $\frac{\sigma(\Delta t)}{\mu(\Delta t)}$.
  - *Missing Data*: `0.0` if $<2$ events.
- **new_contact_rate(e, w)**
  - *Definition*: $\frac{\text{contacts in } w \text{ not seen before } w}{\text{unique\_contacts(e, w)}}$.
  - *Zero Denominator*: `0.0`.

### 1.2 IPDR Features
- **session_count(e, w)**: Number of `IP_SESSION` events.
- **bytes_in(e, w)**: Sum of `bytes_in`.
- **bytes_out(e, w)**: Sum of `bytes_out`.
- **destination_diversity(e, w)**: Number of distinct target IPs.
- **protocol_diversity(e, w)**: Number of distinct protocols used.
- **port_diversity(e, w)**: Number of distinct destination ports used.
- **session_duration(e, w)**: Total duration of IP sessions.
- **new_destination_rate(e, w)**: Ratio of newly observed target IPs to total distinct target IPs in window.

## 2. M6 Financial Analytics (BANK)

- **transaction_count(e, w)**: Number of `TRANSACTION` events.
- **mean_amount(e, w)**: $\frac{\sum amount}{transaction\_count(e, w)}$.
- **median_amount(e, w)**: Median of transaction amounts.
- **amount_deviation(e, w)**: Median Absolute Deviation (MAD) of transaction amounts.
- **transaction_velocity(e, w)**: Total amount of money moved (sum of amounts).
- **unique_counterparties(e, w)**: Distinct entities involved as sender or receiver.
- **new_counterparty_ratio(e, w)**: Ratio of counterparties newly seen in $w$.
- **inflow_outflow_ratio(e, w)**: $\frac{\sum amount\_received}{\sum amount\_sent}$. If sent is 0, returns `999999.0` (cap).
- **merchant_diversity(e, w)**: Number of distinct MERCHANT entities interacted with.
- **time_of_day_pattern(e, w)**: Most frequent hour of day [0-23] of transactions.


## 3. M7 Social Analytics (SOCIAL)

- **activity_frequency(e, w)**: Number of `SOCIAL` events.
- **interaction_count(e, w)**: Number of direct interactions (e.g., replies, mentions) with other users.
- **new_connections(e, w)**: Count of social interactions with entities never interacted with prior to $w$.
- **activity_burst(e, w)**: Burstiness (CV of inter-event times) for social posts.
- **community_membership(e)**: Static (Unavailable unless explicit community tags exist in data. Default `UNAVAILABLE`).
- **topic_shift(e, w)**: (Unavailable without NLP topic modelling engine. Default `UNAVAILABLE`).

## 4. Feature Output Contract
Every exported feature row contains:
- `entity_id`: `canonical_entity_id`.
- `feature_name`: exact string name.
- `feature_value`: float/string.
- `window`: string (e.g. `24h`, `ALL`).
- `source`: Domain (`CDR`, `BANK`, etc., or `GRAPH`).
- `evidence_refs`: Array of `event_id`s used to compute the metric.

## 5. Graph Features (M4)

These features are calculated topologically and exported to `graph_features.parquet`.

- **degree(e, w)**
  - *Definition*: Number of distinct neighboring canonical entities directly connected to $e$. Multiple events between the same pair count as 1 neighbor. Undirected.
  - *Missing Data*: 0 if no neighbors.
  - *Evidence Rule*: Contains all `event_id`s incident to the entity.
- **weighted_degree(e, w)**
  - *Definition*: Sum of all transaction amounts (inflow + outflow) across all `TRANSACTION` events associated with entity $e$. Directed edges (SENDS/RECEIVES) are all summed as total volume.
  - *Missing Data*: `0.0`.
  - *Evidence Rule*: Contains `event_id`s of all incident `TRANSACTION` events.
- **shared_counterparties(e, w)**
  - *Definition*: $\max_{u \neq e} |Neighbors(e) \cap Neighbors(u)|$. The maximum number of neighbors $e$ shares with any single other entity in the graph.
  - *Missing Data*: 0.
  - *Evidence Rule*: Contains all `event_id`s incident to $e$.
- **transaction_path_features(e, w)**
  - *Definition*: Evaluated as `reachable_counterparties_2hop`: the total number of distinct entities reachable from entity $e$ via exactly $\le 2$ consecutive `TRANSACTION` edges (ignoring directionality).
  - *Missing Data*: 0.
  - *Evidence Rule*: Contains `event_id`s of all incident `TRANSACTION` events.

- `feature_value`: float/string.
- `window`: string (e.g. `24h`, `ALL`).
- `source`: Domain (`CDR`, `BANK`, etc.).
- `evidence_refs`: Array of `event_id`s used to compute the metric.
