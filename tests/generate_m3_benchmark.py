# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
"""
M3 Synthetic Benchmark Generator.

Generates a rich, multi-entity, multi-day dataset for M8–M11 scientific evaluation.

Design:
  - 30 NORMAL entities, 5 domains (CDR/IPDR/BANK/SOCIAL/multi), 60 days
  - Each normal entity has stable behavioral profile (low variance)
  - 8 ANOMALY entities injected in test period (last 15% of data)
  - Ground truth stored INDEPENDENTLY from detector output

Temporal split:
  - Training:   day  1–42  (70%)
  - Validation: day 43–51  (15%)
  - Test:       day 52–60  (15%)

Anomaly archetypes:
  E1 — Event anomaly:          Single abnormally large transaction (10× normal)
  E2 — Behavioral anomaly:     Sustained elevated call frequency (5× baseline)
  E3 — Relationship anomaly:   New counterparty never seen before (relationship novelty)
  E4 — Graph anomaly:          Sudden spike in degree and weighted_degree
  E5 — Temporal anomaly:       CALL → TRANSACTION motif in under 60s
  E6 — Multi-domain sequence:  CALL → IP_SESSION → LOGIN → TRANSACTION in 30 minutes
  E7 — Conflicting evidence:   High telecom anomaly + normal financial = conflict
  E8 — Missing domain:         Entity only present in BANK, no CDR/IPDR/SOCIAL

Random seeds: all fixed for reproducibility.
"""
import json
import os
import random
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

RANDOM_SEED = 42
N_NORMAL = 30
N_DAYS_TRAIN = 42
N_DAYS_VAL = 9
N_DAYS_TEST = 9
N_DAYS_TOTAL = N_DAYS_TRAIN + N_DAYS_VAL + N_DAYS_TEST

BASE_DATE = datetime(2026, 1, 1, tzinfo=timezone.utc)
NAMESPACE_BM = uuid.UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890")


def _eid(name: str) -> str:
    return f"ENT_{uuid.uuid5(NAMESPACE_BM, name).hex[:12].upper()}"


def _evt(source: str, idx: int) -> str:
    return f"EVT_{uuid.uuid5(NAMESPACE_BM, f'{source}:{idx}').hex[:12].upper()}"


def _ts(day: int, hour: int, minute: int = 0) -> str:
    dt = BASE_DATE + timedelta(days=day, hours=hour, minutes=minute)
    return dt.isoformat()


def _epoch(day: int, hour: int = 12) -> float:
    dt = BASE_DATE + timedelta(days=day, hours=hour)
    return dt.timestamp()


# ── Normal entity profile generators ─────────────────────────────────────────

def generate_normal_entity_events(
    entity_name: str,
    domain: str,
    rng: np.random.Generator,
    days: int = N_DAYS_TOTAL,
) -> List[Dict]:
    """Generate stable daily events for one normal entity."""
    eid = _eid(entity_name)
    events = []
    idx = 0

    for day in range(days):
        # Each normal entity generates 1–3 events/day with stable distribution
        n_events = int(rng.integers(1, 4))
        for _ in range(n_events):
            hour = int(rng.integers(9, 18))  # business hours
            minute = int(rng.integers(0, 60))
            ts = _ts(day, hour, minute)
            evt_id = _evt(f"{entity_name}:{idx}", idx)
            idx += 1

            if domain == "CDR":
                events.append({
                    "event_id": evt_id,
                    "timestamp": ts,
                    "actor_id": eid,
                    "target_id": _eid(f"contact_{rng.integers(0,5)}"),
                    "event_type": "CALL",
                    "source_domain": "CDR",
                    "attributes": json.dumps({"duration_sec": str(int(rng.normal(120, 20))), "amount": "0"}),
                    "sha256_hash": f"BM_HASH_{evt_id}",
                })
            elif domain == "BANK":
                events.append({
                    "event_id": evt_id,
                    "timestamp": ts,
                    "actor_id": eid,
                    "target_id": _eid(f"merchant_{rng.integers(0,3)}"),
                    "event_type": "TRANSACTION",
                    "source_domain": "BANK",
                    "attributes": json.dumps({"amount": str(round(float(rng.normal(500, 50)), 2)), "duration_sec": "0"}),
                    "sha256_hash": f"BM_HASH_{evt_id}",
                })
            elif domain == "IPDR":
                events.append({
                    "event_id": evt_id,
                    "timestamp": ts,
                    "actor_id": eid,
                    "target_id": f"10.0.{rng.integers(0,10)}.{rng.integers(1,254)}",
                    "event_type": "IP_SESSION",
                    "source_domain": "IPDR",
                    "attributes": json.dumps({"bytes_in": str(int(rng.normal(1000, 100))), "bytes_out": str(int(rng.normal(500, 50))), "amount": "0"}),
                    "sha256_hash": f"BM_HASH_{evt_id}",
                })
            elif domain == "SOCIAL":
                events.append({
                    "event_id": evt_id,
                    "timestamp": ts,
                    "actor_id": eid,
                    "target_id": None,
                    "event_type": "SOCIAL",
                    "source_domain": "SOCIAL",
                    "attributes": json.dumps({"activity": "post", "amount": "0"}),
                    "sha256_hash": f"BM_HASH_{evt_id}",
                })
    return events


# ── Anomaly injectors ─────────────────────────────────────────────────────────

def inject_e1_event_anomaly(test_day: int, rng: np.random.Generator, idx_start: int, mag: float = 10.0, noise: float = 0.05) -> Tuple[List[Dict], Dict]:
    """E1: Extreme value transaction anomaly (scaled by scenario magnitude)."""
    eid = _eid("ANOMALY_E1")
    evt_id = _evt(f"E1:{idx_start}", idx_start)
    amount = round(float(500.0 * mag + rng.normal(0, 100 * noise)), 2)
    return [{
        "event_id": evt_id,
        "timestamp": _ts(test_day, 14, 30),
        "actor_id": eid,
        "target_id": _eid("victim_merchant"),
        "event_type": "TRANSACTION",
        "source_domain": "BANK",
        "attributes": json.dumps({"amount": str(amount), "duration_sec": "0"}),
        "sha256_hash": f"BM_HASH_{evt_id}",
    }], {"entity_id": eid, "anomaly_type": "E1_EVENT_ANOMALY", "is_anomalous": 1}


def inject_e2_behavioral_anomaly(test_day: int, rng: np.random.Generator, idx_start: int, mag: float = 5.0, noise: float = 0.05) -> Tuple[List[Dict], Dict]:
    """E2: Sustained elevated call frequency (scaled by scenario magnitude)."""
    eid = _eid("ANOMALY_E2")
    events = []
    n_calls = max(4, int(3 * mag + rng.integers(-1, 2)))
    for i in range(n_calls):
        evt_id = _evt(f"E2:{idx_start+i}", idx_start + i)
        events.append({
            "event_id": evt_id,
            "timestamp": _ts(test_day, 9 + (i * 15) // 60, (i * 15) % 60),
            "actor_id": eid,
            "target_id": _eid(f"E2_contact_{i % 5}"),
            "event_type": "CALL",
            "source_domain": "CDR",
            "attributes": json.dumps({"duration_sec": str(int(rng.normal(90, 20 * noise))), "amount": "0"}),
            "sha256_hash": f"BM_HASH_{evt_id}",
        })
    return events, {"entity_id": eid, "anomaly_type": "E2_BEHAVIORAL_ANOMALY", "is_anomalous": 1}


def inject_e3_relationship_anomaly(test_day: int, rng: np.random.Generator, idx_start: int, mag: float = 1.0, noise: float = 0.05) -> Tuple[List[Dict], Dict]:
    """E3: Transaction to a brand-new counterparty never seen in training."""
    eid = _eid("ANOMALY_E3")
    new_cp = _eid(f"NOVEL_CP_{rng.integers(1000, 9999)}")
    evt_id = _evt(f"E3:{idx_start}", idx_start)
    return [{
        "event_id": evt_id,
        "timestamp": _ts(test_day, 11, int(rng.integers(0, 50))),
        "actor_id": eid,
        "target_id": new_cp,
        "event_type": "TRANSACTION",
        "source_domain": "BANK",
        "attributes": json.dumps({"amount": str(round(float(500.0 + rng.normal(0, 50)), 2)), "duration_sec": "0"}),
        "sha256_hash": f"BM_HASH_{evt_id}",
    }], {"entity_id": eid, "anomaly_type": "E3_RELATIONSHIP_ANOMALY", "is_anomalous": 1}


def inject_e4_graph_anomaly(test_day: int, rng: np.random.Generator, idx_start: int, mag: float = 2.0, noise: float = 0.05) -> Tuple[List[Dict], Dict]:
    """E4: Sudden spike — multiple transactions to distinct counterparties in 1 hour."""
    eid = _eid("ANOMALY_E4")
    events = []
    n_tx = max(4, int(2 * mag + rng.integers(0, 2)))
    for i in range(n_tx):
        evt_id = _evt(f"E4:{idx_start+i}", idx_start + i)
        events.append({
            "event_id": evt_id,
            "timestamp": _ts(test_day, 10, min(59, i * 4)),
            "actor_id": eid,
            "target_id": _eid(f"E4_cp_{i}"),
            "event_type": "TRANSACTION",
            "source_domain": "BANK",
            "attributes": json.dumps({"amount": "200.00", "duration_sec": "0"}),
            "sha256_hash": f"BM_HASH_{evt_id}",
        })
    return events, {"entity_id": eid, "anomaly_type": "E4_GRAPH_ANOMALY", "is_anomalous": 1}


def inject_e5_temporal_anomaly(test_day: int, rng: np.random.Generator, idx_start: int, mag: float = 1.0, noise: float = 0.05) -> Tuple[List[Dict], Dict]:
    """E5: CALL → TRANSACTION in under 60 seconds (matches MOT_001)."""
    eid = _eid("ANOMALY_E5")
    e1 = _evt(f"E5A:{idx_start}", idx_start)
    e2 = _evt(f"E5B:{idx_start+1}", idx_start + 1)
    return [
        {
            "event_id": e1,
            "timestamp": _ts(test_day, 15, 0),
            "actor_id": eid,
            "target_id": _eid("E5_contact"),
            "event_type": "CALL",
            "source_domain": "CDR",
            "attributes": json.dumps({"duration_sec": "30", "amount": "0"}),
            "sha256_hash": f"BM_HASH_{e1}",
        },
        {
            "event_id": e2,
            "timestamp": _ts(test_day, 15, max(0, int(rng.integers(0, 2)))),  # ~same minute
            "actor_id": eid,
            "target_id": _eid("E5_merchant"),
            "event_type": "TRANSACTION",
            "source_domain": "BANK",
            "attributes": json.dumps({"amount": str(round(float(500.0 * mag), 2)), "duration_sec": "0"}),
            "sha256_hash": f"BM_HASH_{e2}",
        },
    ], {"entity_id": eid, "anomaly_type": "E5_TEMPORAL_ANOMALY", "is_anomalous": 1}


def inject_e6_multidomain_sequence(test_day: int, rng: np.random.Generator, idx_start: int, mag: float = 1.0, noise: float = 0.05) -> Tuple[List[Dict], Dict]:
    """E6: CALL → IP_SESSION → LOGIN → TRANSACTION in 30 minutes (MOT_003)."""
    eid = _eid("ANOMALY_E6")
    events = []
    for i, (evt_type, domain, attrs) in enumerate([
        ("CALL",        "CDR",    {"duration_sec": "45", "amount": "0"}),
        ("IP_SESSION",  "IPDR",   {"bytes_in": "2000", "bytes_out": "500", "amount": "0"}),
        ("LOGIN",       "SOCIAL", {"platform": "webportal", "amount": "0"}),
        ("TRANSACTION", "BANK",   {"amount": str(round(float(250.0 * mag + rng.normal(0, 50)), 2)), "duration_sec": "0"}),
    ]):
        evt_id = _evt(f"E6_{i}:{idx_start+i}", idx_start + i)
        events.append({
            "event_id": evt_id,
            "timestamp": _ts(test_day, 13, i * 6),
            "actor_id": eid,
            "target_id": _eid(f"E6_target_{i}"),
            "event_type": evt_type,
            "source_domain": domain,
            "attributes": json.dumps(attrs),
            "sha256_hash": f"BM_HASH_{evt_id}",
        })
    return events, {"entity_id": eid, "anomaly_type": "E6_MULTIDOMAIN_SEQUENCE", "is_anomalous": 1}


def inject_e7_conflicting_evidence(test_day: int, rng: np.random.Generator, idx_start: int, mag: float = 5.0, noise: float = 0.05) -> Tuple[List[Dict], Dict]:
    """E7: High CDR activity (anomalous telecom) + normal BANK (conflicting)."""
    eid = _eid("ANOMALY_E7")
    events = []
    n_cdr = max(4, int(3 * mag + rng.integers(-1, 2)))
    for i in range(n_cdr):
        evt_id = _evt(f"E7_CDR:{idx_start+i}", idx_start + i)
        events.append({
            "event_id": evt_id,
            "timestamp": _ts(test_day, 2 + (i * 20) // 60, (i * 20) % 60),  # night calls
            "actor_id": eid,
            "target_id": _eid(f"E7_contact_{i % 5}"),
            "event_type": "CALL",
            "source_domain": "CDR",
            "attributes": json.dumps({"duration_sec": "240", "amount": "0"}),
            "sha256_hash": f"BM_HASH_{evt_id}",
        })
    # Normal BANK transaction
    evt_id = _evt(f"E7_BANK:{idx_start+n_cdr}", idx_start + n_cdr)
    events.append({
        "event_id": evt_id,
        "timestamp": _ts(test_day, 10, 0),
        "actor_id": eid,
        "target_id": _eid("E7_normal_merchant"),
        "event_type": "TRANSACTION",
        "source_domain": "BANK",
        "attributes": json.dumps({"amount": "490.00", "duration_sec": "0"}),
        "sha256_hash": f"BM_HASH_{evt_id}",
    })
    return events, {"entity_id": eid, "anomaly_type": "E7_CONFLICTING_EVIDENCE", "is_anomalous": 1}


def inject_e8_missing_domain(test_day: int, rng: np.random.Generator, idx_start: int, mag: float = 6.0, noise: float = 0.05) -> Tuple[List[Dict], Dict]:
    """E8: Entity exists ONLY in BANK — no CDR/IPDR/SOCIAL data."""
    eid = _eid("ANOMALY_E8")
    evt_id = _evt(f"E8:{idx_start}", idx_start)
    return [{
        "event_id": evt_id,
        "timestamp": _ts(test_day, 16, 0),
        "actor_id": eid,
        "target_id": _eid("E8_counterparty"),
        "event_type": "TRANSACTION",
        "source_domain": "BANK",
        "attributes": json.dumps({"amount": str(round(float(500.0 * mag), 2)), "duration_sec": "0"}),
        "sha256_hash": f"BM_HASH_{evt_id}",
    }], {"entity_id": eid, "anomaly_type": "E8_MISSING_DOMAIN", "is_anomalous": 1}


# ── Main generator ────────────────────────────────────────────────────────────

def generate_benchmark(
    output_dir: str,
    random_seed: int = RANDOM_SEED,
    scenario: str = "MODERATE",
    days: int = N_DAYS_TOTAL,
):
    """
    Generate the full M3 benchmark dataset and save to output_dir.
    Scenarios: 'EASY', 'MODERATE', 'HARD', 'ADVERSARIAL'.
    """
    os.makedirs(output_dir, exist_ok=True)

    rng = np.random.default_rng(random_seed)
    random.seed(random_seed)

    # Difficulty calibration
    scenario_cfg = {
        "EASY":        {"mag": 10.0, "noise": 0.05, "drift": 0.0},
        "MODERATE":    {"mag": 5.0,  "noise": 0.15, "drift": 0.05},
        "HARD":        {"mag": 2.2,  "noise": 0.30, "drift": 0.15},
        "ADVERSARIAL": {"mag": 1.4,  "noise": 0.45, "drift": 0.25},
    }.get(scenario.upper(), {"mag": 5.0, "noise": 0.15, "drift": 0.05})

    mag = float(scenario_cfg["mag"])
    noise = float(scenario_cfg["noise"])

    all_events = []
    ground_truth_rows = []
    idx = 0

    # Normal entities
    domains = ["CDR", "BANK", "IPDR", "SOCIAL"]
    for i in range(N_NORMAL):
        domain = domains[i % len(domains)]
        name = f"NORMAL_{i:03d}"
        evts = generate_normal_entity_events(name, domain, rng, days)
        all_events.extend(evts)
        ground_truth_rows.append({
            "entity_id": _eid(name),
            "is_anomalous": 0,
            "anomaly_type": "NONE",
        })
        idx += len(evts)

    # Anomaly entities — injected in test period
    test_day = max(1, days - 5)
    for inject_fn in [
        inject_e1_event_anomaly,
        inject_e2_behavioral_anomaly,
        inject_e3_relationship_anomaly,
        inject_e4_graph_anomaly,
        inject_e5_temporal_anomaly,
        inject_e6_multidomain_sequence,
        inject_e7_conflicting_evidence,
        inject_e8_missing_domain,
    ]:
        evts, gt_row = inject_fn(test_day, rng, idx, mag=mag, noise=noise)
        all_events.extend(evts)
        ground_truth_rows.append(gt_row)
        idx += len(evts)

    events_df = pd.DataFrame(all_events).sort_values("timestamp").reset_index(drop=True)
    gt_df = pd.DataFrame(ground_truth_rows)

    # Resolved entities: one entity per actor_id
    entity_ids = gt_df["entity_id"].unique()
    resolved_rows = [
        {
            "canonical_entity_id": eid,
            "raw_identifier": eid,
            "identifier_type": "USER_ID",
            "match_confidence": 1.0,
            "match_method": "EXACT",
            "match_status": "CONFIRMED",
            "evidence": json.dumps({"events_count": int((events_df["actor_id"] == eid).sum())}),
        }
        for eid in entity_ids
    ]
    resolved_df = pd.DataFrame(resolved_rows)

    # Provenance ledger
    prov_rows = [
        {
            "sha256_hash": ev["sha256_hash"],
            "source_id": ev["source_domain"],
            "source_file": f"benchmark_{ev['source_domain'].lower()}.csv",
            "source_row_index": int(i),
            "ingestion_timestamp": datetime.now(timezone.utc).isoformat(),
            "schema_version": "WP1.1",
        }
        for i, ev in events_df.iterrows()
    ]
    prov_df = pd.DataFrame(prov_rows)

    # Build standard WP2 feature parquets
    tel_rows, fin_rows, soc_rows, gf_rows, benchmark_feature_rows = [], [], [], [], []
    for eid in entity_ids:
        e_evts = events_df[events_df["actor_id"] == eid]
        if e_evts.empty:
            continue

        # Financial
        bank = e_evts[e_evts["source_domain"] == "BANK"]
        if not bank.empty:
            amts = [float(json.loads(r.get("attributes","{}")).get("amount","0")) for _, r in bank.iterrows()]
            refs = bank["event_id"].tolist()
            fin_rows.append({"entity_id": eid, "feature_name": "transaction_count", "feature_value": float(len(bank)), "window": "ALL", "source": "BANK", "evidence_refs": refs})
            fin_rows.append({"entity_id": eid, "feature_name": "total_amount", "feature_value": float(sum(amts)), "window": "ALL", "source": "BANK", "evidence_refs": refs})
            fin_rows.append({"entity_id": eid, "feature_name": "mean_amount", "feature_value": float(np.mean(amts)), "window": "ALL", "source": "BANK", "evidence_refs": refs})
            fin_rows.append({"entity_id": eid, "feature_name": "max_amount", "feature_value": float(np.max(amts)), "window": "ALL", "source": "BANK", "evidence_refs": refs})
            benchmark_feature_rows.append({"entity_id": eid, "feature_name": "transaction_count", "feature_value": float(len(bank)), "window": "ALL", "source": "BANK", "evidence_refs": refs})
            benchmark_feature_rows.append({"entity_id": eid, "feature_name": "mean_amount", "feature_value": float(np.mean(amts)), "window": "ALL", "source": "BANK", "evidence_refs": refs})

        # Telecom
        cdr = e_evts[e_evts["source_domain"] == "CDR"]
        if not cdr.empty:
            durs = [float(json.loads(r.get("attributes","{}")).get("duration_sec", json.loads(r.get("attributes","{}")).get("duration","0"))) for _, r in cdr.iterrows()]
            refs = cdr["event_id"].tolist()
            dates = pd.to_datetime(cdr["timestamp"], utc=True).dt.date
            max_daily = float(dates.value_counts().max()) if not dates.empty else 0.0
            tel_rows.append({"entity_id": eid, "feature_name": "call_count", "feature_value": float(len(cdr)), "window": "ALL", "source": "CDR", "evidence_refs": refs})
            tel_rows.append({"entity_id": eid, "feature_name": "total_duration", "feature_value": float(sum(durs)), "window": "ALL", "source": "CDR", "evidence_refs": refs})
            tel_rows.append({"entity_id": eid, "feature_name": "burstiness", "feature_value": max_daily, "window": "ALL", "source": "CDR", "evidence_refs": refs})
            benchmark_feature_rows.append({"entity_id": eid, "feature_name": "call_count", "feature_value": float(len(cdr)), "window": "ALL", "source": "CDR", "evidence_refs": refs})

        # Social / IPDR
        soc = e_evts[e_evts["source_domain"].isin(["SOCIAL", "IPDR"])]
        if not soc.empty:
            refs = soc["event_id"].tolist()
            soc_rows.append({"entity_id": eid, "feature_name": "session_count", "feature_value": float(len(soc)), "window": "ALL", "source": "IPDR", "evidence_refs": refs})
            benchmark_feature_rows.append({"entity_id": eid, "feature_name": "session_count", "feature_value": float(len(soc)), "window": "ALL", "source": "IPDR", "evidence_refs": refs})

        # Graph
        targets = e_evts["target_id"].dropna().unique()
        refs = e_evts["event_id"].tolist()
        gf_rows.append({"entity_id": eid, "feature_name": "degree", "feature_value": float(len(targets)), "window": "ALL", "source": "GRAPH", "evidence_refs": refs})
        gf_rows.append({"entity_id": eid, "feature_name": "weighted_degree", "feature_value": float(len(e_evts)), "window": "ALL", "source": "GRAPH", "evidence_refs": refs})
        gf_rows.append({"entity_id": eid, "feature_name": "shared_counterparties", "feature_value": float(min(len(targets), 2)), "window": "ALL", "source": "GRAPH", "evidence_refs": refs})
        gf_rows.append({"entity_id": eid, "feature_name": "transaction_path_features", "feature_value": float(len(bank)), "window": "ALL", "source": "GRAPH", "evidence_refs": refs})
        benchmark_feature_rows.append({"entity_id": eid, "feature_name": "degree", "feature_value": float(len(targets)), "window": "ALL", "source": "GRAPH", "evidence_refs": refs})

    # Save all Parquet artifacts
    events_df.to_parquet(os.path.join(output_dir, "canonical_events.parquet"), index=False)
    resolved_df.to_parquet(os.path.join(output_dir, "resolved_entities.parquet"), index=False)
    prov_df.to_parquet(os.path.join(output_dir, "provenance_ledger.parquet"), index=False)
    gt_df.to_parquet(os.path.join(output_dir, "ground_truth.parquet"), index=False)
    pd.DataFrame(tel_rows).to_parquet(os.path.join(output_dir, "telecom_features.parquet"), index=False)
    pd.DataFrame(fin_rows).to_parquet(os.path.join(output_dir, "financial_features.parquet"), index=False)
    pd.DataFrame(soc_rows).to_parquet(os.path.join(output_dir, "social_features.parquet"), index=False)
    pd.DataFrame(gf_rows).to_parquet(os.path.join(output_dir, "graph_features.parquet"), index=False)
    pd.DataFrame(benchmark_feature_rows).to_parquet(os.path.join(output_dir, "benchmark_features.parquet"), index=False)

    print(f"[BENCHMARK] Generated {len(events_df)} events, {len(resolved_df)} entities, 8 anomaly archetypes ({scenario} scenario)")
    print(f"[BENCHMARK] Ground truth: {len(gt_df)} entities, {gt_df['is_anomalous'].sum()} anomalous")
    return {
        "random_seed": random_seed,
        "n_normal_entities": N_NORMAL,
        "n_anomaly_entities": 8,
        "total_events": len(events_df),
        "scenario": scenario,
    }


if __name__ == "__main__":
    generate_benchmark("output/benchmark")
