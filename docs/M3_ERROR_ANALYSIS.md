# DFAP Member 3 — Error Analysis & Diagnostic Taxonomy (Release Candidate 2)

**Author**: Sam Roger X  
**Component**: DFAP WP3 — Intelligence & Research Layer (M8–M11)  
**Date**: September 2026 (RC2 Enterprise & Research Hardening)  

---

## 1. Diagnostic Taxonomy Overview

In multi-source digital footprint platforms, false discoveries (False Positives, FP) and missed signals (False Negatives, FN) arise from structural data dynamics rather than purely stochastic errors. This document catalogs the diagnostic failure pathways, empirical manifestations, and mitigation controls validated across M8–M11.

---

## 2. False Positive (FP) Diagnostic Pathways

| Error Archetype | Mechanism | Manifestation in DFAP | Mitigation Implemented |
|---|---|---|---|
| **FP-1: Cold-Start Instability** | Entities with $<3$ historical records exhibit unrepresentative empirical variance ($\text{MAD} \to 0$), producing artificially inflated Robust-Z scores. | Single normal event on new account flagged as severe deviation. | **`COLD_START` regime**: Strict threshold gate ($|X|<3$) suppresses deviation scoring and returns $RZ=0.0$ with explicit status tag. |
| **FP-2: Baseline Contamination** | In-flight or anomalous observations entering the historical baseline window inflate scale parameters ($\text{MAD}$), masking future anomalies or skewing historical percentiles. | Baseline center drifts upwards, causing subsequent normal events to be flagged as under-activity. | **Strict Temporal Precedence**: Leave-one-out baseline fitting strictly utilizes $X = \{x_1, \dots, x_{t-1}\}$; observation $x_t$ is never included in its own historical reference window. Verified via `test_temporal_leakage_attack`. |
| **FP-3: Shared Infrastructure Ambiguity** | Multiple distinct entities sharing physical hardware (NAT IP, household router, multi-user workstation) appear to have high counterparty diversity or activity bursts. | Normal household members flagged with high `graph_novelty_score`. | **Decoupled Linkage & Topology**: WP1 Splink resolution prevents merging based on IP subnet alone; M9 graph novelty discounts passive shared infrastructure. |
| **FP-4: Evidential Domain Conflict** | High legitimate activity in one domain (e.g. business call burst during operational hours) contradicted by quiescent banking records. | Naïve additive scoring aggregates domain signals into an elevated composite anomaly score. | **Dempster-Shafer Conflict Tracking ($K$) & Abstention**: Tracks conflict mass explicitly ($K \ge 0.50 \implies \text{status}=\text{"CONFLICTED\_EVIDENCE"}$). |
| **FP-5: Missing Domain Misinterpretation** | Entities active only in a subset of domains (e.g. unbanked prepaid phone or pure banking account without social media) penalized for absent records. | Imputing $0$ activity as abnormal or negative evidence. | **Epistemic Mass Assignment ($m(\Theta)=1$)**: Absent domains assigned full ignorance mass, preventing unobserved channels from suppressing or inflating belief. |
| **FP-6: Sequence Time Ambiguity** | Out-of-order logs or loosely spaced legitimate events coincidentally matching sequential event-type patterns. | Routine login followed hours later by routine purchase flagged as coordinated motif. | **Monotonic Temporal Constraints**: Strict $t_1 \le t_2 \le \dots \le t_n$ order enforcement and tight duration bounds ($\Delta t \le \Delta t_{\max}$, gap windows $[g_{\min}, g_{\max}]$). |

---

## 3. False Negative (FN) Diagnostic Pathways

| Error Archetype | Mechanism | Manifestation in DFAP | Mitigation Implemented |
|---|---|---|---|
| **FN-1: Sub-Threshold Low-and-Slow Activity** | Coordinated actions distributed across days below individual point-in-time statistical thresholds ($RZ < 3.0$). | Micro-structuring or low-volume probing unflagged by single-event detectors. | **M10 PrefixSpan Pattern Mining & DTW**: Aggregates subtle multi-step sequential trajectories across long horizons even when individual event volumes remain nominal. |
| **FN-2: Single-Domain Blindness** | Anomaly visible solely in cross-domain coordination (e.g. phone call coordinating an immediate third-party transfer), where each single-domain signal is within normal parameters. | Single-domain financial and telecom detectors both report normal status. | **M11 Evidential & Logistic Fusion**: Cross-domain interaction features and composite belief combination amplify correlated orthogonal signals. |
| **FN-3: Temporal Window Mismatch** | Evaluation window boundary splits a multi-event sequence across two non-overlapping aggregation bins. | Multi-domain kill chain (E6) partially truncated across window boundary. | **Rolling Event-Level Sequence Scanners**: Motif matching operates directly over contiguous event streams rather than fixed discrete window bins. |
| **FN-4: Insufficient Baseline History** | Entity is in `LOW_HISTORY` regime where true anomalous deviation is dampened by conservative scaling. | Early anomaly during onboarding period missed. | **M9 Rule & Isolation Forest Complementarity**: When behavioral baselines have low confidence, decoupled rule triggers and Isolation Forest provide fallback coverage. |

---

## 4. Operational Abstention & Analyst Feedback State Governance

To prevent premature escalation and alert fatigue, findings are governed by two decoupled states:
1. **System Analytical State (`status`)**:
   - `AI_GENERATED_LEAD`: Valid anomalous lead with consensus evidential support.
   - `CONFLICTED_EVIDENCE`: High evidential discordance ($K \ge 0.50$); flagged for triaged review.
   - `INSUFFICIENT_EVIDENCE`: High uncertainty ($m(\Theta) \ge 0.80$) with low composite signal.
2. **Analyst Review State (`review_state`)**:
   - `UNREVIEWED` (Default)
   - `REVIEWED`
   - `TRUE_LEAD`
   - `FALSE_POSITIVE`
   - `DISMISSED`
   - `CONFIRMED_BY_ANALYST`

User/analyst updates to `review_state` do not mutate or overwrite the underlying cryptographic provenance hashes or mathematical scoring vectors.
