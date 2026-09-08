# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: Targeted Record-Backed Forensic Search Engine (Zero Fabrication)

import json
import os
import re
from typing import Dict, Any, List, Optional
import pandas as pd

from dfap.linkage import _jaro_winkler_sim


class TargetedSearchEngine:
    """
    Forensic Targeted Search Engine backed strictly by genuine dataset records
    and registered identity bridge mappings.
    ZERO FABRICATION: Never returns hardcoded personas, synthetic registries,
    or fabricated verification strings. Every returned candidate links directly
    to an underlying Parquet record.
    """

    def __init__(
        self,
        canonical_dir: str = "data/canonical",
        baseline_dir: str = "output",
        bridge_path: str = "data/cases/identity_bridge.parquet"
    ):
        self.canonical_dir = canonical_dir
        self.baseline_dir = baseline_dir
        self.bridge_path = bridge_path

    def search(self, query_type: str, query_val: str, max_results: int = 15) -> List[Dict[str, Any]]:
        """
        Executes typed search across authentic canonical records and identity bridges.
        query_type in ('name', 'wallet', 'ip', 'account', 'device', 'entity', 'general')
        """
        q_type = query_type.lower().strip()
        q_val = query_val.strip()
        if not q_val:
            return []

        if q_type == "wallet":
            return self._search_wallets(q_val, max_results)
        elif q_type in ("ip", "ip_address"):
            return self._search_ips(q_val, max_results)
        elif q_type == "name":
            return self._search_names(q_val, max_results)
        elif q_type in ("account", "bank_account"):
            return self._search_accounts(q_val, max_results)
        elif q_type == "device":
            return self._search_devices(q_val, max_results)
        elif q_type == "entity":
            return self._search_entities(q_val, max_results)
        else:
            return self._search_general(q_val, max_results)

    def _search_wallets(self, wallet_query: str, max_results: int) -> List[Dict[str, Any]]:
        p = os.path.join(self.canonical_dir, "elliptic_canonical.parquet")
        if not os.path.exists(p):
            return []
        df = pd.read_parquet(p)
        clean_q = wallet_query.replace("WALLET_", "").strip().lower()

        # Find exact or substring wallet in actor_id or target_id
        mask = df["actor_id"].str.lower().str.contains(clean_q, na=False) | df["target_id"].str.lower().str.contains(clean_q, na=False)
        sub = df[mask]
        if sub.empty:
            return []

        matched_wallets = set()
        results = []
        for _, r in sub.iterrows():
            w_act = r["actor_id"]
            w_tgt = r["target_id"]
            for w in (w_act, w_tgt):
                if clean_q in w.lower() and w not in matched_wallets:
                    matched_wallets.add(w)
                    count = int(len(df[(df["actor_id"] == w) | (df["target_id"] == w)]))
                    is_exact = clean_q == w.replace("WALLET_", "").lower()
                    results.append({
                        "candidate": w,
                        "query_type": "WALLET",
                        "confidence": 1.0 if is_exact else 0.85,
                        "canonical_entity": f"ENT_CRYPTO_{w.replace('WALLET_', '')[:12]}",
                        "dataset": "Elliptic++",
                        "match_evidence": f"{count} backing transaction record(s) in canonical ledger",
                        "first_seen": str(r["timestamp"]),
                        "backing_record_id": str(r["event_id"])
                    })
                    if len(results) >= max_results:
                        break
        return results

    def _search_ips(self, ip_query: str, max_results: int) -> List[Dict[str, Any]]:
        p = os.path.join(self.canonical_dir, "unsw_canonical.parquet")
        if not os.path.exists(p):
            return []
        df = pd.read_parquet(p)
        clean_q = ip_query.replace("IP_", "").strip().lower()

        mask = df["actor_id"].str.lower().str.contains(clean_q, na=False) | df["target_id"].str.lower().str.contains(clean_q, na=False)
        sub = df[mask]
        matched_ips = set()
        results = []

        if not sub.empty:
            for _, r in sub.iterrows():
                ip_act = r["actor_id"]
                ip_tgt = r["target_id"]
                for ip_node in (ip_act, ip_tgt):
                    if clean_q in ip_node.lower() and ip_node not in matched_ips:
                        matched_ips.add(ip_node)
                        count = int(len(df[(df["actor_id"] == ip_node) | (df["target_id"] == ip_node)]))
                        is_exact = clean_q == ip_node.replace("IP_", "").lower()
                        results.append({
                            "candidate": ip_node,
                            "query_type": "IP_ADDRESS",
                            "confidence": 1.0 if is_exact else 0.90,
                            "canonical_entity": f"ENT_HOST_{ip_node.replace('IP_', '').replace('.', '_')}",
                            "dataset": "UNSW-NB15",
                            "match_evidence": f"{count} backing network session record(s) in canonical ledger",
                            "first_seen": str(r["timestamp"]),
                            "backing_record_id": str(r["event_id"])
                        })
                        if len(results) >= max_results:
                            break

        # Also check authorized identity bridge records
        bridge_p = "data/cases/identity_bridge.parquet"
        if os.path.exists(bridge_p) and len(results) < max_results:
            b_df = pd.read_parquet(bridge_p)
            b_sub = b_df[(b_df["domain"] == "IPDR") & (b_df["raw_identifier"].str.lower().str.contains(clean_q, na=False))]
            for _, r in b_sub.iterrows():
                ident = r["raw_identifier"]
                if ident not in matched_ips:
                    matched_ips.add(ident)
                    results.append({
                        "candidate": ident,
                        "query_type": "IP_ADDRESS",
                        "confidence": float(r.get("confidence", 0.92)),
                        "canonical_entity": r["canonical_entity_id"],
                        "dataset": "CONTROLLED_CASE_MAPPING",
                        "match_evidence": f"Mapped in identity bridge for {r['case_id']}",
                        "first_seen": "BRIDGE_MAPPING",
                        "backing_record_id": r.get("evidence_ref", "bridge")
                    })
                    if len(results) >= max_results:
                        break
        return results

    def _search_names(self, name_query: str, max_results: int) -> List[Dict[str, Any]]:
        """
        Searches names strictly against backing records:
        1. Attributes in production canonical events (actor_name)
        2. Authorized identity bridge mappings (marked CONTROLLED_CASE_MAPPING / LEAD_ONLY)
        3. Stack Overflow user identifiers
        ZERO HARDCODED PERSONAS.
        """
        clean_q = name_query.strip().lower()
        results = []
        seen_candidates = set()

        # 1. Search backing production canonical events
        p_canon = os.path.join(self.baseline_dir, "canonical_events.parquet")
        if os.path.exists(p_canon):
            df_c = pd.read_parquet(p_canon)
            for _, r in df_c.iterrows():
                attrs_raw = r.get("attributes", "{}")
                attrs = json.loads(attrs_raw) if isinstance(attrs_raw, str) else (attrs_raw or {})
                name_val = attrs.get("actor_name") or attrs.get("raw_source_attributes", {}).get("caller_name")
                if name_val and str(name_val).strip() not in seen_candidates:
                    s_name = str(name_val).strip()
                    sim = _jaro_winkler_sim(clean_q, s_name.lower())
                    if sim >= 0.70:
                        seen_candidates.add(s_name)
                        results.append({
                            "candidate": s_name,
                            "query_type": "AUTHORIZED_NAME_RECORD",
                            "confidence": round(sim, 3),
                            "canonical_entity": str(r["actor_id"]),
                            "dataset": "DFAP Production Baseline",
                            "match_evidence": f"Found in canonical event {r['event_id']} attributes",
                            "first_seen": str(r["timestamp"]),
                            "backing_record_id": str(r["event_id"])
                        })

        # 2. Search registered identity bridge
        if os.path.exists(self.bridge_path):
            df_b = pd.read_parquet(self.bridge_path)
            for _, r in df_b.iterrows():
                raw_id = str(r["raw_identifier"])
                if clean_q in raw_id.lower() and raw_id not in seen_candidates:
                    seen_candidates.add(raw_id)
                    results.append({
                        "candidate": raw_id,
                        "query_type": "CONTROLLED_CASE_MAPPING / LEAD_ONLY",
                        "confidence": float(r.get("confidence", 0.85)),
                        "canonical_entity": str(r["canonical_entity_id"]),
                        "dataset": str(r.get("domain", "BRIDGE")),
                        "match_evidence": f"Registered in identity bridge (Ref: {r.get('evidence_ref')})",
                        "first_seen": "Controlled Investigation Registry",
                        "backing_record_id": str(r.get("evidence_ref", ""))
                    })

        # 3. Search Stack Overflow community handles in canonical parquet
        p_so = os.path.join(self.canonical_dir, "stackoverflow_canonical.parquet")
        if os.path.exists(p_so):
            df_so = pd.read_parquet(p_so)
            for u in df_so["actor_id"].unique():
                u_str = str(u).replace("SO_", "")
                if u_str not in seen_candidates:
                    sim = _jaro_winkler_sim(clean_q, u_str.lower())
                    if sim >= 0.75:
                        seen_candidates.add(u_str)
                        ev_sample = df_so[df_so["actor_id"] == u].iloc[0]
                        results.append({
                            "candidate": u_str,
                            "query_type": "COMMUNITY_USER_HANDLE",
                            "confidence": round(sim, 3),
                            "canonical_entity": f"ENT_USER_{u_str}",
                            "dataset": "Stack Overflow",
                            "match_evidence": f"Found in Stack Overflow interaction ledger (Event: {ev_sample['event_id']})",
                            "first_seen": str(ev_sample["timestamp"]),
                            "backing_record_id": str(ev_sample["event_id"])
                        })

        results.sort(key=lambda x: x["confidence"], reverse=True)
        return results[:max_results]

    def _search_accounts(self, acc_query: str, max_results: int) -> List[Dict[str, Any]]:
        clean_q = acc_query.strip().lower()
        p_canon = os.path.join(self.baseline_dir, "canonical_events.parquet")
        if not os.path.exists(p_canon):
            return []
        df_c = pd.read_parquet(p_canon)
        bank_events = df_c[df_c["source_domain"] == "BANK"]

        matched = set()
        results = []
        for _, r in bank_events.iterrows():
            act = str(r["actor_id"])
            tgt = str(r.get("target_id", ""))
            for acc in (act, tgt):
                if clean_q in acc.lower() and acc not in matched:
                    matched.add(acc)
                    count = int(len(bank_events[(bank_events["actor_id"] == acc) | (bank_events["target_id"] == acc)]))
                    results.append({
                        "candidate": acc,
                        "query_type": "ACCOUNT",
                        "confidence": 1.0 if clean_q == acc.lower() else 0.85,
                        "canonical_entity": f"ENT_ACC_{acc.replace('ACC_', '')}",
                        "dataset": "Production Banking Ledger",
                        "match_evidence": f"{count} backing transaction record(s) in canonical ledger",
                        "first_seen": str(r["timestamp"]),
                        "backing_record_id": str(r["event_id"])
                    })
                    if len(results) >= max_results:
                        break
        return results

    def _search_devices(self, dev_query: str, max_results: int) -> List[Dict[str, Any]]:
        clean_q = dev_query.strip().lower()
        p_canon = os.path.join(self.baseline_dir, "canonical_events.parquet")
        if not os.path.exists(p_canon):
            return []
        df_c = pd.read_parquet(p_canon)

        matched = set()
        results = []
        for _, r in df_c.iterrows():
            attrs_raw = r.get("attributes", "{}")
            attrs = json.loads(attrs_raw) if isinstance(attrs_raw, str) else (attrs_raw or {})
            dev_id = attrs.get("device_id") or attrs.get("raw_source_attributes", {}).get("device_id") or attrs.get("imei")
            if dev_id and clean_q in str(dev_id).lower() and str(dev_id) not in matched:
                d_str = str(dev_id)
                matched.add(d_str)
                results.append({
                    "candidate": d_str,
                    "query_type": "DEVICE",
                    "confidence": 1.0,
                    "canonical_entity": f"ENT_DEV_{d_str[:8]}",
                    "dataset": "Production Telemetry",
                    "match_evidence": f"Found in canonical event {r['event_id']} attributes",
                    "first_seen": str(r["timestamp"]),
                    "backing_record_id": str(r["event_id"])
                })
                if len(results) >= max_results:
                    break
        return results

    def _search_entities(self, ent_query: str, max_results: int) -> List[Dict[str, Any]]:
        clean_q = ent_query.strip().lower()
        p_ent = os.path.join(self.baseline_dir, "resolved_entities.parquet")
        if not os.path.exists(p_ent):
            return []
        df_e = pd.read_parquet(p_ent)
        mask = df_e["canonical_entity_id"].str.lower().str.contains(clean_q, na=False) | df_e["raw_identifier"].str.lower().str.contains(clean_q, na=False)
        sub = df_e[mask]
        if sub.empty:
            return []

        matched = set()
        results = []
        for _, r in sub.iterrows():
            eid = str(r["canonical_entity_id"])
            if eid not in matched:
                matched.add(eid)
                results.append({
                    "candidate": eid,
                    "query_type": "CANONICAL_ENTITY",
                    "confidence": float(r.get("match_confidence", 1.0)),
                    "canonical_entity": eid,
                    "dataset": "Production Entity Registry",
                    "match_evidence": f"Resolved via {r.get('match_method', 'EXACT')} (Status: {r.get('match_status', 'CONFIRMED')})",
                    "first_seen": "Production Entity Ledger",
                    "backing_record_id": str(r.get("evidence", ""))
                })
                if len(results) >= max_results:
                    break
        return results

    def _search_general(self, q_val: str, max_results: int) -> List[Dict[str, Any]]:
        if q_val.startswith("bc1") or q_val.startswith("1") or q_val.startswith("3") or "WALLET" in q_val.upper():
            return self._search_wallets(q_val, max_results)
        elif re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", q_val) or "IP_" in q_val.upper():
            return self._search_ips(q_val, max_results)
        elif q_val.startswith("ENT_"):
            return self._search_entities(q_val, max_results)
        elif q_val.startswith("ACC_"):
            return self._search_accounts(q_val, max_results)
        else:
            return self._search_names(q_val, max_results)
