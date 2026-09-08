# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: Controlled Cross-Domain Forensic Investigation & Evidential Fusion Engine

import json
import logging
import os
from typing import Dict, Any, List, Optional
import pandas as pd

from dfap.m3.fusion import _score_to_mass, dempster_shafer_combine
from dfap.investigation.behavioral_profile import BehavioralProfiler

logger = logging.getLogger(__name__)


class CrossDomainInvestigator:
    """
    Controlled Cross-Domain Investigation Engine.
    Correlates identities across otherwise independent public datasets (Elliptic++, UNSW-NB15, Stack Overflow)
    via explicit CONTROLLED_CASE_MAPPING bridges.
    Fuses multi-domain behavioral evidence using production Dempster-Shafer evidential combination.
    """

    def __init__(
        self,
        bridge_path: str = "data/cases/identity_bridge.parquet",
        canonical_dir: str = "data/canonical"
    ):
        self.bridge_path = bridge_path
        self.canonical_dir = canonical_dir
        self.profiler = BehavioralProfiler()
        self._load_bridges()

    def _load_bridges(self):
        if not os.path.exists(self.bridge_path):
            self.bridges_df = pd.DataFrame()
            return
        self.bridges_df = pd.read_parquet(self.bridge_path)

    def list_cases(self) -> List[Dict[str, Any]]:
        """Returns all registered controlled investigation cases."""
        if self.bridges_df.empty:
            return []
        cases = []
        for case_id, grp in self.bridges_df.groupby("case_id"):
            can_id = grp["canonical_entity_id"].iloc[0]
            domains = list(grp["domain"].unique())
            identities = grp[["domain", "raw_identifier", "confidence"]].to_dict(orient="records")
            cases.append({
                "case_id": case_id,
                "canonical_entity_id": can_id,
                "mapping_status": "CONTROLLED_CASE_MAPPING",
                "linked_domains": domains,
                "bridged_identities": identities
            })
        return cases

    def investigate_case(self, case_id: str) -> Dict[str, Any]:
        """
        Executes unified cross-domain investigation:
        1. Resolves all domain identifiers linked to the case.
        2. Ingests events across Financial, Network, and Social datasets.
        3. Computes domain-specific behavioral profiles and anomaly scores.
        4. Fuses evidential belief masses via Dempster-Shafer.
        5. Explains which domain contributed what evidence.
        """
        sub_bridge = self.bridges_df[self.bridges_df["case_id"] == case_id]
        if sub_bridge.empty:
            raise ValueError(f"Case '{case_id}' not found in identity bridge ledger.")

        can_id = sub_bridge["canonical_entity_id"].iloc[0]

        domain_evidence = {}
        domain_scores = {}
        all_events = []

        for _, row in sub_bridge.iterrows():
            dom = row["domain"]
            raw_id = row["raw_identifier"]

            # Load matching canonical dataset
            if dom in ("FINANCIAL", "BANK"):
                ds_key = "elliptic"
            elif dom in ("IPDR", "NETWORK"):
                ds_key = "unsw"
            elif dom in ("SOCIAL",):
                ds_key = "stackoverflow"
            else:
                continue

            can_file = f"{self.canonical_dir}/{ds_key}_canonical.parquet"
            if not os.path.exists(can_file):
                continue

            df = pd.read_parquet(can_file)
            entity_events = df[(df["actor_id"] == raw_id) | (df["target_id"] == raw_id)].to_dict(orient="records")

            if entity_events:
                all_events.extend(entity_events)
                t_max = max(e["epoch_time"] for e in entity_events)
                prof = self.profiler.compute_composite_profile(entity_events, t_max)

                # Compute domain-specific anomaly score based on profile signals
                score = 0.05
                reasons = []

                if dom in ("FINANCIAL", "BANK"):
                    f_prof = prof["financial"]
                    if f_prof.get("max_amount_usd", 0) >= 40000.0:
                        score = max(score, 0.85)
                        reasons.append(f"High-Value Outflow: ${f_prof.get('max_amount_usd'):,.2f}")
                    if "Mixer" in raw_id or "Dark" in raw_id:
                        score = max(score, 0.90)
                        reasons.append("Association with Anonymizing/Mixer Wallet")

                elif dom in ("IPDR", "NETWORK"):
                    n_prof = prof["network"]
                    if n_prof.get("burstiness_index", 0) > 0.30:
                        score = max(score, 0.75)
                        reasons.append(f"Network Burstiness Index: {n_prof.get('burstiness_index')}")
                    if n_prof.get("max_flow_bytes", 0) > 50000:
                        score = max(score, 0.80)
                        reasons.append(f"High Exfiltration Volume: {n_prof.get('max_flow_bytes'):,} bytes")

                elif dom in ("SOCIAL",):
                    s_prof = prof["social"]
                    if s_prof.get("total_interactions", 0) > 50:
                        score = max(score, 0.70)
                        reasons.append(f"High-Volume Interaction Hub: {s_prof.get('total_interactions')} user interactions")
                    elif s_prof.get("interaction_frequency_per_hour", 0) > 3.0:
                        score = max(score, 0.70)
                        reasons.append(f"Social Interaction Surge: {s_prof.get('interaction_frequency_per_hour')} /hr")

                domain_scores[dom.lower()] = score
                domain_evidence[dom.lower()] = {
                    "dataset": ds_key,
                    "raw_identifier": raw_id,
                    "events_count": len(entity_events),
                    "anomaly_score": round(score, 3),
                    "evidence_reasons": reasons,
                    "profile_summary": prof
                }

        # Convert scores to Dempster-Shafer evidential masses (m_a, m_n, m_theta)
        mass_tuples = []
        for d_name, d_score in domain_scores.items():
            mass_tuples.append(_score_to_mass(d_score))

        if mass_tuples:
            ds_res = dempster_shafer_combine(mass_tuples)
            b_anom = ds_res.get("belief_anomalous", 0.0)
            b_unc = ds_res.get("uncertainty", 0.0)
            fused_composite_score = round(b_anom + 0.5 * b_unc, 4)
            conflict_k = ds_res.get("conflict", 0.0)
            fused_mass = {
                "A": b_anom,
                "N": ds_res.get("belief_normal", 0.0),
                "T": b_unc
            }
        else:
            fused_composite_score = 0.05
            conflict_k = 0.0
            fused_mass = {"N": 0.90, "A": 0.05, "T": 0.05}

        # Sort timeline chronologically
        sorted_timeline = sorted(all_events, key=lambda x: x["epoch_time"])
        timeline_summary = [
            {
                "timestamp": e["timestamp"],
                "domain": e["source_domain"],
                "event_id": e["event_id"],
                "actor": e["actor_id"],
                "target": e["target_id"],
                "amount": float(e.get("amount", 0.0)),
                "evidence_ref": f"sha256:{e['sha256_hash'][:16]}"
            }
            for e in sorted_timeline[:30]
        ]

        return {
            "case_id": case_id,
            "canonical_entity_id": can_id,
            "mapping_status": "CONTROLLED_CASE_MAPPING",
            "fused_composite_score": fused_composite_score,
            "threat_classification": "CRITICAL_CROSS_DOMAIN_ESCALATION" if fused_composite_score >= 0.70 else "ELEVATED_MULTI_DOMAIN_RISK",
            "dempster_shafer_masses": {k: round(v, 4) for k, v in fused_mass.items()},
            "evidential_conflict_metric_k": round(conflict_k, 4),
            "domains_analyzed": list(domain_evidence.keys()),
            "domain_evidence_breakdown": domain_evidence,
            "cross_domain_timeline": timeline_summary
        }
