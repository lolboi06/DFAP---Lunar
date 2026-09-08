# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: Causal Multi-Domain Entity Behavioral Profiler

import json
import math
from typing import Dict, Any, List, Optional
import numpy as np
import pandas as pd


class BehavioralProfiler:
    """
    Computes per-entity causal behavioral baselines across Financial, Network, and Social domains.
    Strictly causal: All statistics are computed using events strictly before or at epoch t.
    Zero future information leakage.
    """

    @staticmethod
    def compute_financial_profile(events: List[Dict[str, Any]], current_epoch: float) -> Dict[str, Any]:
        """
        Extracts Financial profile:
        - transaction count, amount statistics (mean, max, std, sum)
        - velocity, counterparty turnover rate, in/out ratio, temporal cadence
        """
        valid_evts = [e for e in events if e.get("epoch_time", 0.0) <= current_epoch and e.get("source_domain") == "BANK"]
        if not valid_evts:
            return {"status": "NO_FINANCIAL_HISTORY", "event_count": 0}

        amounts = [float(e.get("amount", 0.0)) for e in valid_evts if float(e.get("amount", 0.0)) > 0]
        epochs = sorted([e.get("epoch_time", 0.0) for e in valid_evts])
        counterparties = set([e.get("target_id") for e in valid_evts if e.get("target_id")])

        total_vol = sum(amounts)
        mean_amt = float(np.mean(amounts)) if amounts else 0.0
        max_amt = float(np.max(amounts)) if amounts else 0.0
        std_amt = float(np.std(amounts)) if len(amounts) > 1 else 0.0

        # Velocity in last 3600s
        t_1h = current_epoch - 3600.0
        recent_1h = [e for e in valid_evts if e.get("epoch_time", 0.0) >= t_1h]
        vel_1h = sum([float(e.get("amount", 0.0)) for e in recent_1h]) / 3600.0

        # In/out behavior
        in_count = sum(1 for e in valid_evts if "IN" in str(e.get("event_type", "")).upper())
        out_count = len(valid_evts) - in_count

        return {
            "domain": "FINANCIAL",
            "observation_epoch": current_epoch,
            "total_transactions": len(valid_evts),
            "total_volume_usd": round(total_vol, 2),
            "mean_amount_usd": round(mean_amt, 2),
            "max_amount_usd": round(max_amt, 2),
            "std_amount_usd": round(std_amt, 2),
            "hourly_velocity_usd": round(vel_1h, 4),
            "unique_counterparties": len(counterparties),
            "counterparty_turnover_rate": round(len(counterparties) / max(1, len(valid_evts)), 3),
            "in_out_ratio": round(in_count / max(1, out_count), 2)
        }

    @staticmethod
    def compute_network_profile(events: List[Dict[str, Any]], current_epoch: float) -> Dict[str, Any]:
        """
        Extracts Network profile:
        - flow rate, usual destinations, ports, protocols, bytes, durations, burstiness
        """
        valid_evts = [e for e in events if e.get("epoch_time", 0.0) <= current_epoch and e.get("source_domain") in ("IPDR", "NETWORK")]
        if not valid_evts:
            return {"status": "NO_NETWORK_HISTORY", "event_count": 0}

        destinations = set()
        ports = set()
        protocols = set()
        bytes_list = []
        durations = []

        for e in valid_evts:
            attrs = json.loads(e["attributes"]) if isinstance(e.get("attributes"), str) else e.get("attributes", {})
            destinations.add(e.get("target_id"))
            ports.add(attrs.get("dst_port", 0))
            protocols.add(attrs.get("protocol", "unknown"))
            bytes_list.append(attrs.get("sent_bytes", 0) + attrs.get("recv_bytes", 0))
            durations.append(float(e.get("duration", attrs.get("flow_duration_sec", 0.0))))

        # Burstiness: variance in inter-arrival times
        epochs = sorted([e.get("epoch_time", 0.0) for e in valid_evts])
        if len(epochs) >= 3:
            deltas = np.diff(epochs)
            mean_d = float(np.mean(deltas))
            std_d = float(np.std(deltas))
            burstiness = float((std_d - mean_d) / (std_d + mean_d)) if (std_d + mean_d) > 0 else 0.0
        else:
            burstiness = 0.0

        return {
            "domain": "NETWORK",
            "observation_epoch": current_epoch,
            "total_flows": len(valid_evts),
            "unique_destinations": len(destinations),
            "unique_ports": len(ports),
            "protocols": list(protocols),
            "mean_flow_bytes": round(float(np.mean(bytes_list)), 1) if bytes_list else 0.0,
            "max_flow_bytes": int(np.max(bytes_list)) if bytes_list else 0,
            "mean_flow_duration_sec": round(float(np.mean(durations)), 3) if durations else 0.0,
            "burstiness_index": round(burstiness, 3)
        }

    @staticmethod
    def compute_social_profile(events: List[Dict[str, Any]], current_epoch: float) -> Dict[str, Any]:
        """
        Extracts Social profile:
        - interaction frequency, usual contacts, new contacts, activity timing, interaction types
        """
        valid_evts = [e for e in events if e.get("epoch_time", 0.0) <= current_epoch and e.get("source_domain") == "SOCIAL"]
        if not valid_evts:
            return {"status": "NO_SOCIAL_HISTORY", "event_count": 0}

        contacts = set()
        interaction_types = {}

        for e in valid_evts:
            attrs = json.loads(e["attributes"]) if isinstance(e.get("attributes"), str) else e.get("attributes", {})
            contacts.add(e.get("target_id"))
            itype = attrs.get("interaction_type", "interaction")
            interaction_types[itype] = interaction_types.get(itype, 0) + 1

        epochs = sorted([e.get("epoch_time", 0.0) for e in valid_evts])
        time_span = max(1.0, epochs[-1] - epochs[0])
        freq_per_hour = round(len(valid_evts) / (time_span / 3600.0), 3)

        return {
            "domain": "SOCIAL",
            "observation_epoch": current_epoch,
            "total_interactions": len(valid_evts),
            "unique_contacts": len(contacts),
            "interaction_frequency_per_hour": freq_per_hour,
            "interaction_distribution": interaction_types,
            "new_contact_rate": round(len(contacts) / max(1, len(valid_evts)), 3)
        }

    @classmethod
    def compute_composite_profile(cls, events: List[Dict[str, Any]], current_epoch: float) -> Dict[str, Any]:
        """Builds unified multi-domain profile."""
        return {
            "financial": cls.compute_financial_profile(events, current_epoch),
            "network": cls.compute_network_profile(events, current_epoch),
            "social": cls.compute_social_profile(events, current_epoch),
            "causality": "STRICT_HISTORICAL_WINDOW_BEFORE_T"
        }
