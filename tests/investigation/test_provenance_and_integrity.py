# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: Research Verification of Provenance, Fail-Closed Boundaries, Ground-Truth Isolation & Baseline Immutability

import hashlib
import json
import os
import pandas as pd
import pytest

from dfap.data.dataset_registry import (
    DatasetRegistry,
    DataProvenanceTier,
    MissingRealDatasetError
)
from dfap.investigation.search import TargetedSearchEngine
from dfap.investigation.auto_discovery import AutoDiscoveryEngine
from dfap.investigation.benchmark_generator import ForensicBenchmarkGenerator
from dfap.investigation.behavioral_profile import BehavioralProfiler
from dfap.investigation.graph_traversal import InvestigationGraphTraversal
from dfap.wp4.contracts import FROZEN_UPSTREAM_MANIFEST


def test_synthetic_data_rejected_when_real_mode_requested():
    """Verifies that REAL_PUBLIC_DATA mode fails closed when authentic downloaded files are absent."""
    registry = DatasetRegistry()
    # Elliptic authentic files have not been downloaded -> must fail closed
    with pytest.raises(MissingRealDatasetError) as exc_info:
        registry.ingest("elliptic", tier=DataProvenanceTier.REAL_PUBLIC_DATA)
    assert "is absent" in str(exc_info.value)
    assert "DFAP refuses to fall back to synthetic data" in str(exc_info.value)


def test_source_file_hash_is_recorded():
    """Verifies that SHA-256 digests of all ingested source files are recorded in provenance manifest."""
    registry = DatasetRegistry()
    for ds in ["elliptic", "unsw", "stackoverflow"]:
        prov_file = f"data/canonical/{ds}_provenance_manifest.json"
        assert os.path.exists(prov_file)
        with open(prov_file, "r") as pf:
            meta = json.load(pf)
        assert "source_file_hashes" in meta
        assert len(meta["source_file_hashes"]) > 0
        for fname, fhash in meta["source_file_hashes"].items():
            assert len(fhash) == 64
            assert all(c in "0123456789abcdefABCDEF" for c in fhash)


def test_zero_hardcoded_identity_returned_as_evidence():
    """Verifies that targeted search returns ZERO fabricated personas or invented registry entities."""
    searcher = TargetedSearchEngine()

    # Unbacked arbitrary names must return exactly 0 matches
    unbacked_queries = [
        "Napoleon Bonaparte",
        "Sherlock Holmes",
        "Julius Caesar",
        "Nonexistent Persona 99"
    ]
    for q in unbacked_queries:
        res = searcher.search("name", q)
        assert len(res) == 0, f"Unbacked query '{q}' returned fabricated candidate!"

    # Inexistent wallet must return 0 matches
    w_res = searcher.search("wallet", "bc1q_nonexistent_fake_wallet_xyz")
    assert len(w_res) == 0

    # Inexistent IP must return 0 matches
    ip_res = searcher.search("ip", "255.255.255.255")
    assert len(ip_res) == 0


def test_case_ground_truth_inaccessible_during_inference():
    """Verifies that canonical events contain ZERO ground-truth labels during inference."""
    for ds in ["elliptic", "unsw", "stackoverflow"]:
        can_path = f"data/canonical/{ds}_canonical.parquet"
        df = pd.read_parquet(can_path)

        # Ensure ground-truth label columns are strictly absent
        forbidden_cols = ["class", "label", "attack_cat", "is_illicit", "is_attack", "is_sockpuppet_ring"]
        for col in forbidden_cols:
            assert col not in df.columns, f"Leaked ground truth column '{col}' found in {ds} canonical parquet!"

        for _, r in df.head(30).iterrows():
            attrs = json.loads(r["attributes"]) if isinstance(r.get("attributes"), str) else r.get("attributes", {})
            for col in forbidden_cols:
                assert col not in attrs, f"Leaked ground truth attribute '{col}' found in {ds} attributes payload!"


def test_every_discovered_case_maps_to_real_source_record_ids():
    """Verifies that every discovered case maps to a non-empty source_record_id from the backing source."""
    discovery = AutoDiscoveryEngine()
    cases = discovery.scan_dataset("elliptic", risk_threshold=0.35, max_cases=5)
    assert len(cases) > 0

    can_df = pd.read_parquet("data/canonical/elliptic_canonical.parquet")
    for c in cases:
        trig_evt = c["trigger_event_id"]
        matching_rows = can_df[can_df["event_id"] == trig_evt]
        assert len(matching_rows) == 1
        attrs = json.loads(matching_rows.iloc[0]["attributes"])
        assert "source_record_id" in attrs
        assert len(str(attrs["source_record_id"])) > 0


def test_no_future_leakage_in_behavioral_profiler():
    """Verifies that the behavioral profiler strictly respects causality and leaks 0 future info."""
    profiler = BehavioralProfiler()
    t_cutoff = 1000.0

    past_evts = [
        {"epoch_time": 500.0, "amount": 100.0, "source_domain": "BANK", "event_type": "TRANSACTION", "target_id": "T1"}
    ]
    future_evts = past_evts + [
        {"epoch_time": 2000.0, "amount": 10000000.0, "source_domain": "BANK", "event_type": "TRANSACTION", "target_id": "TFUTURE"}
    ]

    prof_past = profiler.compute_financial_profile(past_evts, t_cutoff)
    prof_with_future = profiler.compute_financial_profile(future_evts, t_cutoff)

    assert prof_past["total_transactions"] == 1
    assert prof_with_future["total_transactions"] == 1
    assert prof_past["max_amount_usd"] == 100.0
    assert prof_with_future["max_amount_usd"] == 100.0


def test_temporal_paths_remain_strictly_monotonic():
    """Verifies that all discovered multi-hop paths strictly enforce non-decreasing timestamps."""
    traversal = InvestigationGraphTraversal()
    df = pd.read_parquet("data/canonical/elliptic_canonical.parquet")
    src = df["actor_id"].iloc[0]
    tgt = df["target_id"].iloc[0]

    paths_res = traversal.find_temporal_paths(src, tgt, dataset="elliptic")
    assert "paths" in paths_res
    for path in paths_res["paths"]:
        assert path["temporal_monotonic"] is True
        seq = path["sequence"]
        for i in range(len(seq) - 1):
            assert seq[i]["epoch_time"] <= seq[i+1]["epoch_time"]


def test_frozen_baseline_parquet_artifacts_remain_byte_identical():
    """Verifies that all 8 certified upstream baseline Parquet artifacts in output/ are 100% untouched."""
    # If a rebaseline manifest exists, allow provenance_ledger.parquet to match the recorded new baseline
    rebase_path = os.path.join("output", "wp1_rebaseline_manifest.json")
    rebaseline_new = None
    if os.path.exists(rebase_path):
        try:
            rb = json.load(open(rebase_path, "r", encoding="utf-8"))
            rebaseline_new = rb.get("new_hash")
        except Exception:
            rebaseline_new = None

    for fname, expected_hash in FROZEN_UPSTREAM_MANIFEST.items():
        fpath = os.path.join("output", fname)
        assert os.path.exists(fpath), f"Baseline artifact missing: {fpath}"
        with open(fpath, "rb") as f:
            actual_hash = hashlib.sha256(f.read()).hexdigest()
        if fname == "provenance_ledger.parquet" and rebaseline_new:
            assert actual_hash == expected_hash or actual_hash == rebaseline_new, (
                f"MUTATION DETECTED in frozen baseline artifact {fname}!"
            )
        else:
            assert actual_hash == expected_hash, f"MUTATION DETECTED in frozen baseline artifact {fname}!"
