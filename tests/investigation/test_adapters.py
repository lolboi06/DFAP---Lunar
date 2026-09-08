# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: Research Test Suite for Real Dataset Adapters and Ground-Truth Isolation

import json
import os
import pandas as pd
import pytest

from dfap.adapters.elliptic import EllipticAdapter
from dfap.adapters.unsw_nb15 import UNSWAdapter
from dfap.adapters.stackoverflow import StackOverflowAdapter
from dfap.data.dataset_registry import DatasetRegistry


def test_elliptic_adapter_and_ground_truth_isolation():
    """Verifies Elliptic++ adapter converts records while strictly isolating ground truth."""
    adapter = EllipticAdapter()
    can_df, gt_df = adapter.load_and_convert(
        "data/test_fixtures/elliptic/elliptic_txs.csv",
        "data/test_fixtures/elliptic/elliptic_classes.csv"
    )

    assert len(can_df) == 3000
    assert len(gt_df) == 3000

    # Required canonical columns
    for col in ["event_id", "timestamp", "epoch_time", "source_domain", "event_type", "actor_id", "target_id", "amount", "attributes", "sha256_hash"]:
        assert col in can_df.columns

    # Verify domain and event type
    assert (can_df["source_domain"] == "BANK").all()
    assert (can_df["event_type"] == "TRANSACTION").all()

    # Verify GROUND TRUTH IS ISOLATED: not in canonical events or attributes
    assert "class" not in can_df.columns
    assert "is_illicit_ground_truth" not in can_df.columns
    for _, r in can_df.head(50).iterrows():
        attrs = json.loads(r["attributes"])
        assert "class" not in attrs
        assert "is_illicit" not in attrs

    # Verify ground truth dataframe has labels
    assert "is_illicit_ground_truth" in gt_df.columns
    assert gt_df["is_illicit_ground_truth"].sum() > 0


def test_unsw_adapter_and_ground_truth_isolation():
    """Verifies UNSW-NB15 adapter converts records while strictly isolating ground truth."""
    adapter = UNSWAdapter()
    can_df, gt_df = adapter.load_and_convert(
        "data/test_fixtures/unsw_nb15/unsw_nb15_flows.csv"
    )

    assert len(can_df) == 4000
    assert len(gt_df) == 4000

    assert (can_df["source_domain"] == "IPDR").all()
    assert (can_df["event_type"] == "IP_SESSION").all()

    # Ground truth isolated
    assert "label" not in can_df.columns
    assert "attack_cat" not in can_df.columns
    for _, r in can_df.head(50).iterrows():
        attrs = json.loads(r["attributes"])
        assert "label" not in attrs
        assert "attack_cat" not in attrs

    assert "is_attack_ground_truth" in gt_df.columns
    assert gt_df["is_attack_ground_truth"].sum() > 0


def test_stackoverflow_adapter_and_ground_truth_isolation():
    """Verifies Stack Overflow adapter converts records while strictly isolating ground truth."""
    adapter = StackOverflowAdapter()
    can_df, gt_df = adapter.load_and_convert(
        "data/test_fixtures/stackoverflow/stackoverflow_temporal.csv"
    )

    assert len(can_df) == 3500
    assert len(gt_df) == 3500

    assert (can_df["source_domain"] == "SOCIAL").all()
    assert (can_df["event_type"] == "SOCIAL").all()

    # Ground truth isolated
    assert "is_sockpuppet_ring" not in can_df.columns
    for _, r in can_df.head(50).iterrows():
        attrs = json.loads(r["attributes"])
        assert "is_sockpuppet_ring" not in attrs

    assert "is_sockpuppet_ring_ground_truth" in gt_df.columns
    assert gt_df["is_sockpuppet_ring_ground_truth"].sum() > 0


def test_dataset_registry_fail_closed_validation():
    """Verifies dataset registry validates schema and fails closed on unknown or corrupt dataset."""
    registry = DatasetRegistry()
    ds_list = registry.list_datasets()
    assert len(ds_list) == 3

    info = registry.get_dataset_info("elliptic")
    assert info["key"] == "elliptic"
    assert info["is_ingested"] is True
    assert info["ingested_record_count"] == 3000

    with pytest.raises(Exception):
        registry.get_dataset_info("unknown_fabricated_dataset")
