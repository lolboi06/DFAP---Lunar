# DFAP Member 3 — Research Methodology (Release Candidate 2)

**Author**: Sam Roger X  
**Component**: DFAP WP3 — Intelligence & Research Layer (M8–M11)  
**Date**: September 2026 (RC2 Enterprise & Research Hardening)  

---

## 1. Executive Summary & Epistemic Scope

Member 3 (WP3) delivers the primary intelligence, behavioral baseline modeling, anomaly scoring, temporal sequence modeling, and cross-domain evidence fusion layer for the Digital Footprint Fusion & Analysis Platform (DFAP).

Consuming frozen, immutable upstream contracts from Member 1 (WP1) and Member 2 (WP2), Member 3 implements:
- **M8**: Entity-Specific Behavioral Baseline Engine
- **M9**: Multi-Level Anomaly Engine (6 levels, 5 decoupled component signals)
- **M10**: Temporal Sequence Engine (Motif matching, PrefixSpan sequential pattern mining, Local DTW)
- **M11**: Cross-Domain Evidence Fusion (Weighted, Calibrated Logistic Regression, and Dempster-Shafer Evidential Reasoning)

### Epistemic Discipline & Research Claims
> [!IMPORTANT]
> **Research Claim Discipline**: All experimental findings reported herein are **SUPPORTED ON CURRENT BENCHMARK** datasets. No claim of universal optimality or unconditional theoretical superiority is made. Dempster-Shafer belief masses represent degree of evidential support under frame $\Theta$, not Bayesian posterior probabilities. All analytical findings are designated as **`AI_GENERATED_LEAD`**, **`CONFLICTED_EVIDENCE`**, or **`INSUFFICIENT_EVIDENCE`**, serving as investigative leads rather than judicial conclusions.

---

## 2. Formal Research Hypotheses

* **H1 (Entity-Specific Baselines)**: Entity-specific statistical baselines (Robust-Z via MAD and EWMA) reduce false discoveries compared to fixed global thresholds across heterogeneous digital behavior. *(Status: Supported on current benchmark)*.
* **H2 (Temporal Sequences)**: Enforcing strict chronological monotonicity ($t_1 \le t_2 \le \dots \le t_n$) and bounded window constraints improves detection of multi-step coordinated actions over static point-in-time scoring. *(Status: Supported on current benchmark)*.
* **H3 (Graph-Behavioral Synergy)**: Structural graph topology metrics (degree, weighted transaction volume, shared counterparties) provide orthogonal confirmation when combined with longitudinal behavioral deviations. *(Status: Supported on current benchmark)*.
* **H4 (Cross-Domain Evidential Fusion)**: Fusing observations across multiple independent digital domains (CDR, IPDR, Banking, Social) improves detection ranking and average precision over isolated single-domain detectors. *(Status: Supported on current benchmark)*.
* **H5 (Evidence-Aware Uncertainty & Conflict Handling)**: Assigning unobserved domains to epistemic uncertainty ($m(\Theta)=1$) and explicitly tracking evidential conflict ($K$) handles missing and contradictory data more robustly than naïve score averaging. *(Status: Supported on current benchmark)*.

---

## 3. Mathematical Formulations & Algorithms

### 3.1 M8 — Behavioral Baseline Engine
For each entity $e$ and feature $f$, the historical sequence of observations $X = \{x_1, x_2, \dots, x_{t-1}\}$ strictly prior to evaluation time $t$ defines the baseline:

1. **Baseline Center**:
   $$\text{median}(X) = \text{Q}_{50}(X)$$
2. **Median Absolute Deviation (MAD)**:
   $$\text{MAD}(X) = \text{median}(\{|x_i - \text{median}(X)|\})$$
3. **Robust Z-Score ($RZ$)**:
   $$RZ(x_t) = \frac{x_t - \text{median}(X)}{1.4826 \cdot \text{MAD}(X) + \epsilon}$$
   *(where $1.4826$ is the normal consistency scale factor and $\epsilon = 10^{-9}$)*
4. **Exponentially Weighted Moving Average (EWMA)**:
   $$\text{EWMA}_t = \alpha \cdot x_t + (1 - \alpha) \cdot \text{EWMA}_{t-1}, \quad \alpha = 0.3$$
5. **Empirical Percentile**:
   $$P(x_t) = \frac{1}{|X|} \sum_{x_i \in X} \mathbb{I}(x_i \le x_t) \times 100\% \quad (\text{for } |X| \ge 3)$$

**Baseline Regimes**:
- `COLD_START`: $|X| < 3$ (insufficient historical support; $RZ=0.0$, percentile=`NaN`)
- `LOW_HISTORY`: $3 \le |X| < 10$ (moderate confidence)
- `STABLE_BASELINE`: $|X| \ge 10$ (full confidence)

---

### 3.2 M9 — Multi-Level Anomaly Engine
Anomalies are detected across six distinct analytical levels:
1. **EVENT**: Individual transaction or communication exceeding domain parameters.
2. **ENTITY**: Longitudinal deviation from entity-specific baseline.
3. **RELATIONSHIP**: Interaction with unprecedented or unexpected counterparty.
4. **COMMUNITY**: Deviation from peer community behavioral norms.
5. **SUBGRAPH**: Structural shift in local 2-hop topological ego-network.
6. **SEQUENCE**: Uncharacteristic temporal sequence or motif trigger.

**Component Signals (Decoupled & Uncollapsed)**:
- `rule_score` $\in [0, 1]$: Deterministic domain policy rules.
- `baseline_deviation_score` $\in [0, \infty)$: Maximum absolute robust Z-score.
- `isolation_forest_score` $\in (-\infty, \infty)$: Scikit-learn Isolation Forest decision function ($s < 0 \implies$ anomalous; native scale, NOT probability).
- `graph_novelty_score` $\in [0, 1]$: Bounded structural metric combining degree, shared counterparties, and path features.
- `relationship_score` $\in [0, 1]$: Rate of novel or unverified counterparties.

---

### 3.3 M10 — Temporal Sequence Engine

#### 1. Deterministic Motif Matching
Evaluates strict monotonic sequences $E = (e_1, e_2, \dots, e_n)$ such that:
$$t(e_1) \le t(e_2) \le \dots \le t(e_n)$$
$$t(e_n) - t(e_1) \le \Delta t_{\max}$$
$$g_k = t(e_{k+1}) - t(e_k) \in [g_{k,\min}, g_{k,\max}]$$

#### 2. PrefixSpan Sequential Pattern Mining
Extracts frequent sequential sub-patterns $\alpha = \langle a_1, a_2, \dots, a_k \rangle$ across entity chronologies without external black-box dependencies.
- **Support**: $|\{e \in \mathcal{E} : \alpha \sqsubseteq S_e\}|$
- **Frequency**: Total occurrences of $\alpha$ in corpus
- **Recurrence**: True if Frequency $>$ Support
- **Novelty**: True if $\alpha \notin \text{Patterns}(\text{Train})$

#### 3. Local Dynamic Time Warping (DTW)
Converts event sequences into numerical trajectory matrices $\mathbf{M} \in \mathbb{R}^{n \times 5}$:
$$\mathbf{v}(e) = \begin{bmatrix} 
\text{type\_enc}(e)/6 \\ 
\text{domain\_enc}(e)/3 \\ 
(t(e) - t_{\min})/(t_{\max} - t_{\min} + \epsilon) \\ 
\min(\text{amount}/10^5, 1.0) \\ 
\min(\text{duration}/3600, 1.0) 
\end{bmatrix}$$

Local distance metric: Squared Euclidean ($L_2^2$).  
Dynamic Programming Recurrence:
$$D(i, j) = \|\mathbf{u}_i - \mathbf{v}_j\|_2^2 + \min\begin{cases} D(i-1, j) \\ D(i, j-1) \\ D(i-1, j-1) \end{cases}$$
$$\text{DTW}(\mathbf{U}, \mathbf{V}) = D(m, n), \quad \text{NormDTW} = \frac{\text{DTW}(\mathbf{U}, \mathbf{V})}{|\text{WarpingPath}|}$$
$$\text{SequenceScore} = \exp(-\text{NormDTW}) \in (0, 1] \quad (\text{Similarity proxy, NOT probability})$$

---

### 3.4 M11 — Cross-Domain Evidence Fusion & Abstention

#### 1. Configurable Weighted Fusion
$$\text{CompositeScore} = \frac{\sum_{d \in \mathcal{D}_{\text{active}}} w_d \cdot s_d}{\sum_{d \in \mathcal{D}_{\text{active}}} w_d}$$

#### 2. Calibrated Logistic Regression Fusion
Features $\mathbf{z} = [s_{\text{fin}}, s_{\text{beh}}, s_{\text{graph}}, \dots]^T$ mapped to calibrated class probabilities using Platt scaling / Sigmoid calibration via `CalibratedClassifierCV(cv='prefit')`:
$$P(\text{Anomalous} \mid \mathbf{z}) = \frac{1}{1 + \exp(- (A \cdot \mathbf{w}^T \mathbf{z} + B))}$$
*(Only model producing mathematical probabilities).*

#### 3. Dempster-Shafer (D-S) Evidential Reasoning
Frame of Discernment: $\Theta = \{\text{ANOMALOUS}, \text{NORMAL}\}$.  
Mass assignment for domain $d$ with score $s_d \in [0, 1]$ and sensitivity $\gamma = 0.8$:
- If domain $d$ unobserved: $m_d(\Theta) = 1.0, \quad m_d(\text{ANOMALOUS}) = 0, \quad m_d(\text{NORMAL}) = 0$
- If $s_d \ge 0.5$: $m_d(\text{ANOMALOUS}) = \gamma |2s_d - 1|, \quad m_d(\Theta) = 1 - m_d(\text{ANOMALOUS})$
- If $s_d < 0.5$: $m_d(\text{NORMAL}) = \gamma |2s_d - 1|, \quad m_d(\Theta) = 1 - m_d(\text{NORMAL})$

Dempster's Rule of Combination:
$$m_{1,2}(A) = \frac{1}{1 - K} \sum_{X \cap Y = A} m_1(X) m_2(Y), \quad A \neq \emptyset$$
$$K = \sum_{X \cap Y = \emptyset} m_1(X) m_2(Y) = m_1(\text{ANOMALOUS}) m_2(\text{NORMAL}) + m_1(\text{NORMAL}) m_2(\text{ANOMALOUS})$$

**Conflict & Abstention Policy**:
- $K < 0.25 \implies \text{conflict\_flag} = \text{"NORMAL\_CONFLICT"}$
- $0.25 \le K < 0.50 \implies \text{conflict\_flag} = \text{"MODERATE\_CONFLICT"}$
- $K \ge 0.50 \implies \text{conflict\_flag} = \text{"HIGH\_CONFLICT"}$
- If $K \ge 0.50 \implies \text{status} = \text{"CONFLICTED\_EVIDENCE"}$ (abstains from asserting anomaly)
- If $m(\Theta) \ge 0.80 \land \text{CompositeScore} < 0.30 \implies \text{status} = \text{"INSUFFICIENT\_EVIDENCE"}$
- Otherwise $\text{status} = \text{"AI\_GENERATED\_LEAD"}$

---

## 4. Temporal Leakage Defense & Invariance Proof

Data partitioning strictly obeys longitudinal causality:
1. **Training ($t \in [1, t_{\text{train}}]$, 70%)**: Baseline estimation, Isolation Forest fitting, pattern mining.
2. **Validation / Calibration ($t \in (t_{\text{train}}, t_{\text{val}}]$, 15%)**: Platt scaling calibration, rule validation.
3. **Test Evaluation ($t \in (t_{\text{val}}, t_{\text{test}}]$, 15%)**: Future unseen evaluation.

**Formal Invariance Inoculation**:
In `test_temporal_leakage_attack`, future extreme poisoning ($t+1, t+2 \to 999,999$) has mathematically $0.0$ impact on baseline parameters evaluated at timestamp $t$.
