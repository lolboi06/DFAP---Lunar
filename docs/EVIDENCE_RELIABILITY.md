# DFAP Evidence Quality & Reliability Engine Specification
**Author:** Sam Roger X  
**Component:** DFAP WP1 / Investigation Platform  
**Version:** v1.0.0_PRODUCTION_RESEARCH (`cfg_v1.0`)  
**Status:** Certified / Research-Grade  

---

## 1. Executive Summary & Purpose

The DFAP **Evidence Quality & Reliability Engine** evaluates the quality, completeness, independence, and credibility of evidence supporting investigative findings and claims. 

### Fundamental Principle: Anomaly Score $\neq$ Evidence Reliability
An extraordinarily high anomaly score (e.g., `0.99` from an unsupervised detector or supervised classifier) reflects anomalous statistical deviation in telemetry. It does **not** indicate that the evidence was authoritatively bound to the suspect, that the cryptographic chain of custody is unbroken, or that contradictory baseline signals do not exist. The Evidence Quality & Reliability Engine provides an orthogonal, auditable, and deterministic quality index distinguishing statistical signal strength from investigative evidential credibility.

---

## 2. Architectural Placement

The engine sits between Cross-Domain Fusion (M11), Provenance Integrity (M12), Workspace Management (M13), and the Grounded Copilot (M14):

```
M1 (Raw Ingestion) / M2 (Identity Graph) / M3 (Temporal Sequences)
                       ↓
            M9 / M10 Findings Ledger
                       ↓
     M11 Cross-Domain Fusion & Conflict Engine
                       ↓
   [ NEW: Evidence Quality & Reliability Engine ]
                       ↓
     M12 Cryptographic Lineage & DAG Provenance
                       ↓
       M13 Investigation Workspace Backend
                       ↓
            M14 Grounded Copilot
```

---

## 3. Mathematical Formulation & Component Definitions

The continuous numerical reliability metric $\text{overall\_score} \in [0.0, 1.0]$ is computed deterministically from six orthogonal component indices minus a dynamic contradiction penalty.

### Scoring Formula:
$$\text{Base Reliability} = w_{\text{id}} C_{\text{id}} + w_{\text{temp}} T_{\text{rel}} + w_{\text{qual}} Q_{\text{ev}} + w_{\text{corrob}} S_{\text{corrob}} + w_{\text{data}} D_{\text{qual}} + w_{\text{prov}} P_{\text{comp}}$$

$$\text{overall\_score} = \text{round}\left(\text{clip}\left(\text{Base Reliability} - P_{\text{contra}}, 0.0, 1.0\right), 4\right)$$

### Default Weights ($W$, sum = 1.0):
* $w_{\text{id}} (\text{identity}) = 0.25$
* $w_{\text{temp}} (\text{temporal}) = 0.15$
* $w_{\text{qual}} (\text{evidence quality}) = 0.15$
* $w_{\text{corrob}} (\text{corroboration}) = 0.20$
* $w_{\text{data}} (\text{data quality}) = 0.10$
* $w_{\text{prov}} (\text{provenance}) = 0.15$

---

## 4. Component Definitions

### 1. Identity Confidence ($C_{\text{id}} \in [0.0, 1.0]$)
Measures the authoritative controlled bridge confidence linking the evidence item's raw identifier to the investigated canonical entity.
* Never trusts `finding.canonical_entity_id` alone.
* Queries the immutable read-only identity bridge (`data/cases/identity_bridge.parquet`) or backend authoritative alias table.
* Spoofed or unmapped identifiers fail closed to $0.0$.

### 2. Temporal Reliability ($T_{\text{rel}} \in [0.0, 1.0]$)
Enforces causal temporal alignment and zero future leakage.
* Records with timestamps strictly after the finding trigger timestamp ($t_{\text{obs}} > T_{\text{trigger}}$) are classified as future events, receive $0.0$ temporal score, and are excluded from causal corroboration.
* Valid pre-trigger timestamps receive $1.0$. Missing or unsequenced timestamps receive $0.50$.

### 3. Evidence Quality ($Q_{\text{ev}} \in [0.0, 1.0]$)
Average of stored `evidence_quality` attributes in `CanonicalEvidenceRecord`.

### 4. Corroboration Strength ($S_{\text{corrob}} \in [0.0, 1.0]$)
Measures the count of **independent evidence clusters** supporting the finding:
$$S_{\text{corrob}} = \min\left(1.0, \frac{|E_{\text{independent\_clusters}}|}{N_{\text{target\_events}}}\right) \quad (N_{\text{target\_events}} = 3)$$

#### Independence & Deduplication Rules:
Evidence records $e_1, e_2$ are grouped into the same dependent cluster if:
1. Shared event ID: $e_1.\text{event\_ids} \cap e_2.\text{event\_ids} \neq \emptyset$
2. Identical cryptographic hash: $e_1.\text{evidence\_hash} == e_2.\text{evidence\_hash}$
3. Identical source row: same `source_file` and same `source_row_index`
*Three duplicate copies of a single event yield 1 cluster ($S_{\text{corrob}} = 0.33$), whereas three distinct events yield 3 clusters ($S_{\text{corrob}} = 1.00$).*

### 5. Data Quality ($D_{\text{qual}} \in [0.0, 1.0]$)
Penalizes incomplete schemas, missing source filenames, negative row indices, or invalid hash lengths.

### 6. Provenance Completeness ($P_{\text{comp}} \in [0.0, 1.0]$)
Directly verifies M12 cryptographic integrity (`verify_integrity()`) and confirms backwards DAG reachability to an authoritative root entity node.

---

## 5. Support Strength, Contradiction Strength & Penalty

### Support Strength ($S_{\text{supp}} \in [0.0, 1.0]$)
$$S_{\text{supp}} = \min\left(1.0, \frac{\sum_{e \in E_{\text{indep\_supp}}} C_{\text{id}}(e) \cdot Q_{\text{ev}}(e) \cdot T_{\text{rel}}(e)}{2.0}\right)$$

### Contradiction Strength ($S_{\text{contra}} \in [0.0, 1.0]$)
$$S_{\text{contra}} = \min\left(1.0, \frac{\sum_{e \in E_{\text{indep\_contra}}} C_{\text{id}}(e) \cdot Q_{\text{ev}}(e) \cdot T_{\text{rel}}(e)}{1.0}\right)$$

### Conflict Severity & Dynamic Penalty Table:
| Severity | Condition | Multiplier | Contradiction Penalty ($P_{\text{contra}}$) |
| :--- | :--- | :--- | :--- |
| `NO_CONFLICT` | $S_{\text{contra}} == 0.0$ | $0.00$ | $0.0$ |
| `WEAK_CONFLICT` | $0.0 < S_{\text{contra}} \le 0.25$ | $0.10$ | $S_{\text{contra}} \times 0.10$ |
| `MODERATE_CONFLICT` | $0.25 < S_{\text{contra}} \le 0.60$ | $0.25$ | $S_{\text{contra}} \times 0.25$ |
| `STRONG_CONFLICT` | $S_{\text{contra}} > 0.60$ | $0.35$ | $S_{\text{contra}} \times 0.35$ |

---

## 6. Evidence Sufficiency, Overall Status, and Provenance Architecture

Reliability score and decision status are strictly separated:

### Evidence Sufficiency:
* **`NO_VALID_EVIDENCE`**: Zero valid items bound to the canonical entity.
* **`CONFLICTED_EVIDENCE`**: Material support ($S_{\text{supp}} \ge 0.25$) and material contradiction ($S_{\text{contra}} \ge 0.25$) present concurrently.
* **`WEAK_EVIDENCE`**: Identity confidence $< 0.70$, fewer than 2 independent supporting clusters ($\text{clusters} < 2$), temporal failure, or incomplete provenance lineage.
* **`SUFFICIENT_EVIDENCE`**: At least 2 independent supporting clusters, verified identity ($\ge 0.70$), complete provenance ($\ge 0.80$), valid temporal order, and no material conflict.

### Deterministic Status Logic:
1. `NO_VALID_EVIDENCE` $\implies$ `overall_status = INSUFFICIENT_EVIDENCE`, `overall_score = 0.0`
2. Contradiction-only ($S_{\text{supp}} < 0.25$ and $S_{\text{contra}} > 0.0$) $\implies$ `overall_status = LOW`
3. `CONFLICTED_EVIDENCE` or `conflict_severity in (MODERATE_CONFLICT, STRONG_CONFLICT)` $\implies$ `overall_status = CONFLICTED` *(Preserves conflict regardless of whether base score is high)*
4. `WEAK_EVIDENCE`:
   * If single verified cluster ($\ge 1$) with $\text{overall\_score} \ge 0.50$, identity $\ge 0.70$, and provenance $\ge 0.80$: `overall_status = MEDIUM` (capped; cannot reach `HIGH` without independent corroboration)
   * Else: `overall_status = LOW`
5. `SUFFICIENT_EVIDENCE` ($\ge 2$ independent clusters, no material conflict):
   * If $\text{overall\_score} \ge 0.80$, $C_{\text{id}} \ge 0.85$, and independent clusters $\ge 3$: `HIGH`
   * Else if $\text{overall\_score} \ge 0.50$: `MEDIUM`
   * Else: `LOW`

### Provenance: Cryptographic Evidence Integrity vs Lineage Verification
The engine strictly distinguishes two independent levels of provenance assurance:
1. **Cryptographic Record Integrity (`cryptographic_integrity`)**: Audits M12 SHA-256 payload self-hashes against record contents. Verifies that the individual record has not suffered data tampering.
2. **Provenance Lineage Verification (`lineage_status`)**: Traverses the provenance DAG backwards to ensure the evidence item connects via explicit derivation edges back to authoritative raw data or resolved entity root ancestors (`ROOT_ANCESTOR_VERIFIED` vs `UNLINKED_LINEAGE`).
* An evidence item with valid cryptographic integrity but missing DAG parent edges receives `provenance_status = RECORD_INTEGRITY_ONLY_UNLINKED_LINEAGE`, a penalized completeness score of $0.50$, and cannot promote a finding to `SUFFICIENT_EVIDENCE` or `HIGH` reliability.

---

## 7. Parameter Sensitivity Analysis (Engineering Stability)

> [!IMPORTANT]
> **Engineering Stability Disclaimer:** The sensitivity experiment described below is an engineering stability analysis evaluating the numerical robustness of a heuristic scoring function against small parameter perturbations. It is **not** a statistical validation or empirical calibration.

### Stability Methodology:
1. Benchmark cases across high-support, duplicate-evidence, conflicted, weak-identity, and future-leakage conditions are evaluated under baseline weights.
2. Component weights are perturbed by $\pm 10\%$ with re-normalization.
3. Contradiction multipliers are perturbed by $\pm 20\%$.
4. **Results:**
   * Categorical statuses (`HIGH`, `MEDIUM`, `LOW`, `CONFLICTED`, `INSUFFICIENT_EVIDENCE`) remain 100% stable across all non-borderline test cases.
   * Rank-order correlation across benchmark cases satisfies Spearman's $\rho = 1.00$ ($\rho \ge 0.95$).

---

## 8. Non-Calibration Disclaimer

> [!CAUTION]
> The reliability score produced by this engine is a deterministic heuristic index reflecting compliance with evidential, identity, temporal, and cryptographic integrity constraints. It is **NOT** a calibrated statistical probability or Bayesian posterior likelihood. It must not be cited in court or compliance reports as a mathematical probability of guilt or illicit activity.
