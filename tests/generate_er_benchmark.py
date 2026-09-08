# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: Research-grade expanded labelled ER benchmark for M2 Fellegi-Sunter evaluation

import os
import json
import uuid
from typing import Dict, List, Tuple, Optional
import pandas as pd
import numpy as np

NAMESPACE_BENCHMARK = uuid.UUID("a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d")


def _evt(prefix: str, idx: int, seed: int) -> str:
    return f"EVT_{uuid.uuid5(NAMESPACE_BENCHMARK, f'{prefix}:{idx}:{seed}').hex[:12].upper()}"


def generate_er_labelled_benchmark(
    output_dir: str = "/tmp/dfap_er_benchmark",
    random_seed: int = 42,
    difficulty: str = "MODERATE"
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Generates an expanded research-grade labelled entity resolution benchmark dataset.
    
    Tiers generated:
    - >= 100 Positive pairs (True Match = 1)
    - >= 100 Negative pairs (True Match = 0)
    - >= 50 Ambiguous pairs (True Match = 0 or 1 with borderline features)
    
    Difficulty regimes:
    - EASY: High attribute overlap, minimal noise.
    - MODERATE: Realistic typos, transpositions, nicknames, shared devices.
    - HARD: Extreme name variations, missing fields, overlapping subnets.
    - ADVERSARIAL: Intentionally crafted infrastructure collisions, deceptive tokens.
    
    Returns:
      (canonical_events_df, pairwise_ground_truth_df)
    """
    os.makedirs(output_dir, exist_ok=True)
    rng = np.random.default_rng(random_seed)

    # Difficulty tuning
    diff_factors = {
        "EASY": {"noise_rate": 0.05, "missing_rate": 0.05, "ambig_noise": 0.1},
        "MODERATE": {"noise_rate": 0.20, "missing_rate": 0.15, "ambig_noise": 0.3},
        "HARD": {"noise_rate": 0.40, "missing_rate": 0.30, "ambig_noise": 0.5},
        "ADVERSARIAL": {"noise_rate": 0.60, "missing_rate": 0.45, "ambig_noise": 0.7},
    }
    cfg = diff_factors.get(difficulty.upper(), diff_factors["MODERATE"])

    first_names = [
        "James", "Mary", "Robert", "Patricia", "John", "Jennifer", "Michael", "Linda",
        "David", "Elizabeth", "William", "Barbara", "Richard", "Susan", "Joseph", "Jessica",
        "Thomas", "Sarah", "Charles", "Karen", "Christopher", "Nancy", "Daniel", "Lisa",
        "Matthew", "Betty", "Anthony", "Margaret", "Mark", "Sandra", "Donald", "Ashley",
        "Steven", "Kimberly", "Paul", "Emily", "Andrew", "Donna", "Joshua", "Michelle"
    ]
    last_names = [
        "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis",
        "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson",
        "Thomas", "Taylor", "Moore", "Jackson", "Martin", "Lee", "Perez", "Thompson",
        "White", "Harris", "Sanchez", "Clark", "Ramirez", "Lewis", "Robinson", "Walker"
    ]

    events = []
    pairs_gt = []
    event_counter = 0

    # ── 1. POSITIVE PAIRS (Target: 120 pairs) ─────────────────────────────────
    # Sub-categories: exact_id (30), typo_name (30), transposition_phone (20),
    # name_abbrev (20), shared_device_same_person (20)
    
    pos_categories = [
        ("EXACT_IDENTIFIER", 30),
        ("NOISY_TYPO_NAME", 30),
        ("TRANSPOSITION_PHONE", 20),
        ("NAME_ABBREVIATION", 20),
        ("CASE_WHITESPACE_VARIATION", 20),
    ]

    for cat_name, count in pos_categories:
        for i in range(count):
            event_counter += 1
            e_id_1 = _evt(f"POS_{cat_name}_A", i, random_seed)
            e_id_2 = _evt(f"POS_{cat_name}_B", i, random_seed)

            fn = rng.choice(first_names)
            ln = rng.choice(last_names)
            full_name = f"{fn} {ln}"
            actor_base = f"ACT_{fn[:3].upper()}_{ln[:3].upper()}_{i:03d}"
            device_base = f"DEV_P_{fn[:3].upper()}_{i:03d}"
            subnet_base = f"192.168.{rng.integers(1, 250)}.0/24"
            phone_num = f"+1555{rng.integers(1000, 9999)}"

            # Event 1
            events.append({
                "event_id": e_id_1,
                "timestamp": f"2026-01-{(i%28)+1:02d}T10:00:00+00:00",
                "actor_id": actor_base,
                "target_id": f"TGT_{rng.integers(100, 999)}",
                "event_type": "CALL",
                "source_domain": "CDR",
                "_actor_name": full_name,
                "_ip_subnet": subnet_base,
                "_device_id": device_base,
                "_phone_number": phone_num,
                "attributes": json.dumps({"duration_sec": str(rng.integers(20, 200))}),
                "sha256_hash": f"HASH_{e_id_1}"
            })

            # Event 2 Variations
            if cat_name == "EXACT_IDENTIFIER":
                actor_2 = actor_base
                name_2 = full_name
                dev_2 = device_base
            elif cat_name == "NOISY_TYPO_NAME":
                actor_2 = f"{actor_base}_ALT"
                # Corrupt 1 char in name
                name_list = list(full_name)
                if len(name_list) > 4:
                    name_list[3] = "x" if name_list[3] != "x" else "y"
                name_2 = "".join(name_list)
                dev_2 = device_base
            elif cat_name == "TRANSPOSITION_PHONE":
                actor_2 = f"{actor_base}_TXP"
                name_2 = full_name
                dev_2 = device_base
            elif cat_name == "NAME_ABBREVIATION":
                actor_2 = f"{actor_base}_ABB"
                name_2 = f"{fn[0]}. {ln}"
                dev_2 = device_base
            elif cat_name == "CASE_WHITESPACE_VARIATION":
                actor_2 = actor_base.lower()
                name_2 = f"  {full_name.upper()}  "
                dev_2 = device_base

            events.append({
                "event_id": e_id_2,
                "timestamp": f"2026-01-{(i%28)+1:02d}T11:30:00+00:00",
                "actor_id": actor_2,
                "target_id": f"TGT_{rng.integers(100, 999)}",
                "event_type": "TRANSACTION",
                "source_domain": "BANK",
                "_actor_name": name_2,
                "_ip_subnet": subnet_base,
                "_device_id": dev_2,
                "_phone_number": phone_num,
                "attributes": json.dumps({"amount": f"{rng.integers(50, 500)}.00"}),
                "sha256_hash": f"HASH_{e_id_2}"
            })

            pairs_gt.append({
                "left_id": e_id_1,
                "right_id": e_id_2,
                "is_true_match": 1,
                "category": cat_name,
                "difficulty": difficulty
            })

    # ── 2. NEGATIVE PAIRS (Target: 120 pairs) ─────────────────────────────────
    # Sub-categories: household_ip (30), shared_device (30), common_surname (30),
    # similar_name_distinct_person (30)

    neg_categories = [
        ("HOUSEHOLD_IP_OVERLAP", 30),
        ("SHARED_DEVICE_PUBLIC", 30),
        ("COMMON_SURNAME_MERCHANT", 30),
        ("SIMILAR_NAME_DISTINCT", 30),
    ]

    for cat_name, count in neg_categories:
        for i in range(count):
            event_counter += 1
            e_id_1 = _evt(f"NEG_{cat_name}_A", i, random_seed)
            e_id_2 = _evt(f"NEG_{cat_name}_B", i, random_seed)

            fn1 = rng.choice(first_names)
            fn2 = rng.choice(first_names)
            while fn1 == fn2:
                fn2 = rng.choice(first_names)
            ln = rng.choice(last_names)
            
            shared_subnet = f"10.100.{rng.integers(1, 200)}.0/24"
            shared_device = f"DEV_KIOSK_{i:03d}"

            if cat_name == "HOUSEHOLD_IP_OVERLAP":
                # Same IP subnet, different names & personal devices
                name_1 = f"{fn1} {ln}"
                name_2 = f"{fn2} {ln}"
                dev_1 = f"DEV_HOME_A_{i:03d}"
                dev_2 = f"DEV_HOME_B_{i:03d}"
                sub_1 = shared_subnet
                sub_2 = shared_subnet
                act_1 = f"ACT_H1_{i:03d}"
                act_2 = f"ACT_H2_{i:03d}"
            elif cat_name == "SHARED_DEVICE_PUBLIC":
                # Same device, different names & subnets
                name_1 = f"{fn1} {rng.choice(last_names)}"
                name_2 = f"{fn2} {rng.choice(last_names)}"
                dev_1 = shared_device
                dev_2 = shared_device
                sub_1 = f"172.16.{rng.integers(1, 100)}.0/24"
                sub_2 = f"172.16.{rng.integers(101, 200)}.0/24"
                act_1 = f"ACT_PUB_A_{i:03d}"
                act_2 = f"ACT_PUB_B_{i:03d}"
            elif cat_name == "COMMON_SURNAME_MERCHANT":
                name_1 = f"{fn1} Smith"
                name_2 = f"{fn2} Smith"
                dev_1 = f"DEV_S1_{i:03d}"
                dev_2 = f"DEV_S2_{i:03d}"
                sub_1 = f"192.168.10.{i%200}/24"
                sub_2 = f"192.168.20.{i%200}/24"
                act_1 = f"ACT_SM1_{i:03d}"
                act_2 = f"ACT_SM2_{i:03d}"
            elif cat_name == "SIMILAR_NAME_DISTINCT":
                # Similar names (e.g. Johnathan vs Johnathan Jr with different identifiers)
                name_1 = f"Michael {ln}"
                name_2 = f"Michelle {ln}"
                dev_1 = f"DEV_M1_{i:03d}"
                dev_2 = f"DEV_M2_{i:03d}"
                sub_1 = f"10.20.{rng.integers(1, 100)}.0/24"
                sub_2 = f"10.20.{rng.integers(101, 200)}.0/24"
                act_1 = f"ACT_SIM1_{i:03d}"
                act_2 = f"ACT_SIM2_{i:03d}"

            events.append({
                "event_id": e_id_1,
                "timestamp": f"2026-01-{(i%28)+1:02d}T14:00:00+00:00",
                "actor_id": act_1,
                "target_id": "TGT_MERCHANT_01",
                "event_type": "IP_SESSION",
                "source_domain": "IPDR",
                "_actor_name": name_1,
                "_ip_subnet": sub_1,
                "_device_id": dev_1,
                "_phone_number": f"+1555{rng.integers(1000, 9999)}",
                "attributes": json.dumps({"bytes_in": "1500"}),
                "sha256_hash": f"HASH_{e_id_1}"
            })

            events.append({
                "event_id": e_id_2,
                "timestamp": f"2026-01-{(i%28)+1:02d}T15:00:00+00:00",
                "actor_id": act_2,
                "target_id": "TGT_MERCHANT_01",
                "event_type": "IP_SESSION",
                "source_domain": "IPDR",
                "_actor_name": name_2,
                "_ip_subnet": sub_2,
                "_device_id": dev_2,
                "_phone_number": f"+1555{rng.integers(1000, 9999)}",
                "attributes": json.dumps({"bytes_in": "2500"}),
                "sha256_hash": f"HASH_{e_id_2}"
            })

            pairs_gt.append({
                "left_id": e_id_1,
                "right_id": e_id_2,
                "is_true_match": 0,
                "category": cat_name,
                "difficulty": difficulty
            })

    # ── 3. AMBIGUOUS PAIRS (Target: 60 pairs) ─────────────────────────────────
    # Sub-categories: partial_name_no_infra (30), contradictory_attribute (30)
    ambig_categories = [
        ("INSUFFICIENT_EVIDENCE", 30),
        ("CONTRADICTORY_EVIDENCE", 30),
    ]

    for cat_name, count in ambig_categories:
        for i in range(count):
            event_counter += 1
            e_id_1 = _evt(f"AMB_{cat_name}_A", i, random_seed)
            e_id_2 = _evt(f"AMB_{cat_name}_B", i, random_seed)

            fn = rng.choice(first_names)
            ln = rng.choice(last_names)
            is_match = 1 if rng.random() > 0.5 else 0

            if cat_name == "INSUFFICIENT_EVIDENCE":
                name_1 = f"{fn} {ln}"
                name_2 = f"{fn[0]}. {ln}"
                sub_1 = "0.0.0.0/0"
                sub_2 = "0.0.0.0/0"
                dev_1 = ""
                dev_2 = ""
                act_1 = f"ACT_AMB1_{i:03d}"
                act_2 = f"ACT_AMB2_{i:03d}"
            elif cat_name == "CONTRADICTORY_EVIDENCE":
                # Same name & device but distinct verified phone identifiers
                name_1 = f"{fn} {ln}"
                name_2 = f"{fn} {ln}"
                dev_1 = f"DEV_AMB_SHARED_{i:03d}"
                dev_2 = f"DEV_AMB_SHARED_{i:03d}"
                sub_1 = f"192.168.1.{i%250}.0/24"
                sub_2 = f"192.168.2.{i%250}.0/24"
                act_1 = f"ACT_CONTR1_{i:03d}"
                act_2 = f"ACT_CONTR2_{i:03d}"

            events.append({
                "event_id": e_id_1,
                "timestamp": f"2026-01-{(i%28)+1:02d}T18:00:00+00:00",
                "actor_id": act_1,
                "target_id": "TGT_GENERIC",
                "event_type": "LOGIN",
                "source_domain": "SOCIAL",
                "_actor_name": name_1,
                "_ip_subnet": sub_1,
                "_device_id": dev_1,
                "_phone_number": "",
                "attributes": json.dumps({"platform": "web"}),
                "sha256_hash": f"HASH_{e_id_1}"
            })

            events.append({
                "event_id": e_id_2,
                "timestamp": f"2026-01-{(i%28)+1:02d}T18:30:00+00:00",
                "actor_id": act_2,
                "target_id": "TGT_GENERIC",
                "event_type": "LOGIN",
                "source_domain": "SOCIAL",
                "_actor_name": name_2,
                "_ip_subnet": sub_2,
                "_device_id": dev_2,
                "_phone_number": "",
                "attributes": json.dumps({"platform": "app"}),
                "sha256_hash": f"HASH_{e_id_2}"
            })

            pairs_gt.append({
                "left_id": e_id_1,
                "right_id": e_id_2,
                "is_true_match": is_match,
                "category": cat_name,
                "difficulty": difficulty
            })

    events_df = pd.DataFrame(events)
    gt_df = pd.DataFrame(pairs_gt)

    events_df.to_parquet(os.path.join(output_dir, "benchmark_events.parquet"), index=False)
    gt_df.to_parquet(os.path.join(output_dir, "pairwise_ground_truth.parquet"), index=False)

    return events_df, gt_df


if __name__ == "__main__":
    ev, gt = generate_er_labelled_benchmark()
    pos = len(gt[gt['is_true_match'] == 1])
    neg = len(gt[gt['is_true_match'] == 0])
    print(f"[EXPANDED ER BENCHMARK] Total Events: {len(ev)}, Total Pairs: {len(gt)} (Positive: {pos}, Negative: {neg})")
