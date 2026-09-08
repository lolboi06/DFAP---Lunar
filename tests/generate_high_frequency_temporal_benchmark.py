# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: High-Frequency Temporal Benchmark Generator for Sub-Hour Next-State Prediction Evaluation

"""
DFAP High-Frequency Temporal Research Benchmark Generator.

RESEARCH NOTICE:
This dataset is a strictly controlled synthetic research benchmark for evaluating
sub-hour temporal transition models (+15m, +30m, +60m). It does NOT contain real-world
persons, real accounts, or scraped data. All entities, identifiers, and timestamps
are deterministically generated under reproducible PRNG seeds.

Design:
- 50 entities total (40 stable baseline, 10 behavioral transition archetypes).
- 20-day timeline with high event frequency (active hours 08:00–22:00 UTC).
- Inter-event intervals: 10–30 min for normal periods; 1–4 min during escalation episodes.
- Domains: BANK, CDR, IPDR, SOCIAL.

Temporal Separation (Strict Chronological Partitioning):
- Historical Training Split:   Day 0.0 to Day 12.0 (60%)
- Validation / Calibration:    Day 12.0 to Day 16.0 (20%)
- Held-Out Unseen Test:        Day 16.0 to Day 20.0 (20%)

Ground truth transition states are recorded independently from model predictions.
"""

import datetime
import json
import os
import uuid
from typing import Dict, List, Tuple, Any

import numpy as np
import pandas as pd


NAMESPACE_TEMPORAL = uuid.UUID("c2d3e4f5-a6b7-8901-cdef-1234567890ab")


def _generate_deterministic_id(prefix: str, key: str) -> str:
    return f"{prefix}_{uuid.uuid5(NAMESPACE_TEMPORAL, key).hex[:12].upper()}"


def generate_high_frequency_temporal_benchmark(
    output_dir: str = "output/temporal_benchmark",
    random_seed: int = 42,
    n_entities: int = 50,
    n_transition_entities: int = 10,
    total_days: int = 20
) -> Dict[str, Any]:
    """
    Generates high-frequency streaming events with genuine sub-hour behavioral transitions.
    Outputs Parquet artifacts to output_dir.
    """
    os.makedirs(output_dir, exist_ok=True)
    rng = np.random.RandomState(random_seed)
    base_dt = datetime.datetime(2026, 8, 1, 0, 0, 0, tzinfo=datetime.timezone.utc)

    entities = [_generate_deterministic_id("ENT", f"entity_{i}") for i in range(n_entities)]
    transition_entities = set(entities[n_entities - n_transition_entities:])

    events = []
    ground_truth_episodes = []

    for day in range(total_days):
        for eid in entities:
            is_trans_ent = eid in transition_entities
            curr_sec = day * 86400 + 8 * 3600   # 08:00 UTC
            end_sec = day * 86400 + 22 * 3600    # 22:00 UTC

            # 35% probability of an escalation episode per day for transition entities
            has_episode_today = is_trans_ent and (rng.rand() < 0.35)
            episode_start_sec = rng.randint(curr_sec + 3600, end_sec - 3600) if has_episode_today else -1
            episode_duration_sec = rng.randint(1800, 3600) if has_episode_today else 0

            if has_episode_today:
                ep_start_dt = base_dt + datetime.timedelta(seconds=episode_start_sec)
                ep_end_dt = base_dt + datetime.timedelta(seconds=episode_start_sec + episode_duration_sec)
                ground_truth_episodes.append({
                    "entity_id": eid,
                    "day": day,
                    "start_time": ep_start_dt.isoformat(),
                    "end_time": ep_end_dt.isoformat(),
                    "start_epoch": ep_start_dt.timestamp(),
                    "end_epoch": ep_end_dt.timestamp(),
                    "archetype": "ELEVATED_VELOCITY_BURST"
                })

            while curr_sec < end_sec:
                in_episode = has_episode_today and (episode_start_sec <= curr_sec <= episode_start_sec + episode_duration_sec)

                if in_episode:
                    # High-frequency burst: 1 to 4 minutes between events
                    step = rng.randint(60, 240)
                    curr_sec += step
                    domain = rng.choice(["BANK", "CDR", "SOCIAL"])
                    etype = "TRANSACTION" if domain == "BANK" else ("CALL" if domain == "CDR" else "LOGIN")
                    amt = float(round(rng.uniform(3500.0, 15000.0), 2)) if domain == "BANK" else 0.0
                    dur = float(round(rng.uniform(300.0, 900.0), 1)) if domain == "CDR" else 0.0
                    is_elev = 1
                else:
                    # Normal steady cadence: 10 to 30 minutes between events
                    step = rng.randint(600, 1800)
                    curr_sec += step
                    domain = rng.choice(["BANK", "CDR", "IPDR"])
                    etype = "TRANSACTION" if domain == "BANK" else ("CALL" if domain == "CDR" else "IP_SESSION")
                    amt = float(round(rng.uniform(15.0, 250.0), 2)) if domain == "BANK" else 0.0
                    dur = float(round(rng.uniform(30.0, 180.0), 1)) if domain == "CDR" else 0.0
                    is_elev = 0

                if curr_sec >= end_sec:
                    break

                ts = base_dt + datetime.timedelta(seconds=curr_sec)
                evt_id = _generate_deterministic_id("EVT", f"{eid}_{day}_{curr_sec}")

                attrs = {
                    "amount": amt,
                    "duration_sec": dur,
                    "channel": "API" if domain == "BANK" else ("VOICE" if domain == "CDR" else "WEB")
                }

                events.append({
                    "event_id": evt_id,
                    "timestamp": ts.isoformat(),
                    "epoch_time": ts.timestamp(),
                    "day": curr_sec / 86400.0,
                    "actor_id": eid,
                    "target_id": _generate_deterministic_id("TGT", f"target_{rng.randint(0, 15)}"),
                    "source_domain": domain,
                    "event_type": etype,
                    "amount": amt,
                    "duration": dur,
                    "attributes": json.dumps(attrs),
                    "sha256_hash": f"SHA256_TEMPORAL_{evt_id}",
                    "is_elevated_state": is_elev
                })

    events_df = pd.DataFrame(events).sort_values("epoch_time").reset_index(drop=True)
    gt_df = pd.DataFrame(ground_truth_episodes)

    events_path = os.path.join(output_dir, "hf_canonical_events.parquet")
    gt_path = os.path.join(output_dir, "hf_ground_truth.parquet")

    events_df.to_parquet(events_path, index=False)
    gt_df.to_parquet(gt_path, index=False)

    return {
        "random_seed": random_seed,
        "total_events": len(events_df),
        "total_entities": n_entities,
        "transition_entities": n_transition_entities,
        "elevated_events_count": int(events_df["is_elevated_state"].sum()),
        "elevated_events_ratio": float(events_df["is_elevated_state"].mean()),
        "total_episodes": len(gt_df),
        "events_path": events_path,
        "ground_truth_path": gt_path,
        "split_cutoffs": {
            "train_cutoff_day": 12.0,
            "val_cutoff_day": 16.0,
            "test_cutoff_day": 20.0
        }
    }


if __name__ == "__main__":
    meta = generate_high_frequency_temporal_benchmark()
    print(f"Generated benchmark with {meta['total_events']} events, {meta['elevated_events_count']} elevated.")
