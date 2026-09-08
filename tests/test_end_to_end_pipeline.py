# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research

import json
import os
import shutil
import pandas as pd
import pytest

from generate_sample_data import generate_sample_datasets
from dfap.pipeline import DFAPPipeline


@pytest.fixture
def sample_environment(tmp_path):
    data_dir = str(tmp_path / "raw")
    out_dir1 = str(tmp_path / "output1")
    out_dir2 = str(tmp_path / "output2")

    generate_sample_datasets(output_dir=data_dir)
    return data_dir, out_dir1, out_dir2


def test_end_to_end_pipeline_and_contracts(sample_environment):
    """Executes full WP1 pipeline and asserts existence & column schema of all frozen contract outputs."""
    data_dir, out_dir, _ = sample_environment
    pipeline = DFAPPipeline(confirmed_threshold=0.85, possible_threshold=0.60)
    summary = pipeline.run(raw_data_dir=data_dir, output_dir=out_dir)

    assert summary["status"] == "SUCCESS"
    assert summary["accepted_rows"] > 0
    assert summary["rejected_rows"] > 0  # Our adversarial dataset includes malformed rows

    # 1. canonical_events.parquet
    c_events_path = summary["canonical_events_path"]
    assert os.path.exists(c_events_path)
    df_c = pd.read_parquet(c_events_path)
    assert list(df_c.columns) == [
        "event_id", "timestamp", "actor_id", "target_id",
        "event_type", "source_domain", "attributes", "sha256_hash"
    ]
    assert df_c["event_id"].is_unique, "event_id must be 100% unique"

    # 2. provenance_ledger.parquet
    prov_path = summary["provenance_ledger_path"]
    assert os.path.exists(prov_path)
    df_p = pd.read_parquet(prov_path)
    assert list(df_p.columns) == [
        "sha256_hash", "source_id", "source_file", "source_row_index",
        "ingestion_timestamp", "schema_version"
    ]
    assert len(df_p) == len(df_c), "100% of accepted canonical events must have provenance records."
    assert set(df_c["sha256_hash"]).issubset(set(df_p["sha256_hash"]))

    # 3. resolved_entities.parquet
    ent_path = summary["resolved_entities_path"]
    assert os.path.exists(ent_path)
    df_e = pd.read_parquet(ent_path)
    assert list(df_e.columns) == [
        "canonical_entity_id", "raw_identifier", "identifier_type",
        "match_confidence", "match_method", "match_status", "evidence"
    ]

    # 4. entity_matches.parquet
    mch_path = summary["entity_matches_path"]
    assert os.path.exists(mch_path)
    df_m = pd.read_parquet(mch_path)
    assert list(df_m.columns) == [
        "match_id", "left_record_id", "right_record_id", "match_probability",
        "match_weight", "blocking_rule", "comparison_summary", "match_method",
        "match_status", "decision_reason", "model_version"
    ]

    # 5. wp1_manifest.json
    man_path = summary["manifest_path"]
    assert os.path.exists(man_path)
    with open(man_path, "r", encoding="utf-8") as fh:
        manifest = json.load(fh)
    assert manifest["schema_version"] == "WP1.1"
    assert manifest["accepted_counts"] == summary["accepted_rows"]


def test_reproducibility(sample_environment):
    """Proves 100% deterministic reproducibility across repeated pipeline runs on identical inputs."""
    data_dir, out_dir1, out_dir2 = sample_environment
    pipeline = DFAPPipeline(confirmed_threshold=0.85, possible_threshold=0.60)

    summary1 = pipeline.run(raw_data_dir=data_dir, output_dir=out_dir1)
    summary2 = pipeline.run(raw_data_dir=data_dir, output_dir=out_dir2)

    df_c1 = pd.read_parquet(summary1["canonical_events_path"])
    df_c2 = pd.read_parquet(summary2["canonical_events_path"])

    assert df_c1["event_id"].tolist() == df_c2["event_id"].tolist()
    assert df_c1["sha256_hash"].tolist() == df_c2["sha256_hash"].tolist()

    df_p1 = pd.read_parquet(summary1["provenance_ledger_path"])
    df_p2 = pd.read_parquet(summary2["provenance_ledger_path"])

    assert df_p1["sha256_hash"].tolist() == df_p2["sha256_hash"].tolist()

    df_e1 = pd.read_parquet(summary1["resolved_entities_path"])
    df_e2 = pd.read_parquet(summary2["resolved_entities_path"])

    assert df_e1["canonical_entity_id"].tolist() == df_e2["canonical_entity_id"].tolist()
