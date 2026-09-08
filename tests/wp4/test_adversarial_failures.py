# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: Test suite for WP4 Adversarial Fail-Closed Error Classifications (RC4 Hardening)

import pytest
import os
import shutil
import tempfile
import json
import pandas as pd
from dfap.wp4.service import WP4Service
from dfap.wp4.timeline import TimelineService
from dfap.wp4.contracts import (
    EvidenceChainError,
    WorkspaceError,
    UpstreamContractError,
    UpstreamIntegrityError,
    ErrorCode,
)


@pytest.fixture
def wp4_service():
    return WP4Service(data_dir="output")


def test_missing_finding_fails_closed(wp4_service):
    with pytest.raises(EvidenceChainError) as exc_info:
        wp4_service.get_finding("NON_EXISTENT_FINDING")
    assert exc_info.value.error_code == ErrorCode.UNKNOWN_FINDING


def test_invalid_hop_count_fails_closed(wp4_service):
    with pytest.raises(WorkspaceError) as exc_info:
        wp4_service.get_entity_subgraph("ENT_0F0FC38C24C0539E", hops=4)
    assert exc_info.value.error_code == ErrorCode.INVALID_HOP_COUNT

    with pytest.raises(WorkspaceError) as exc_info:
        wp4_service.get_entity_subgraph("ENT_0F0FC38C24C0539E", hops=-2)
    assert exc_info.value.error_code == ErrorCode.INVALID_HOP_COUNT


def test_invalid_timeline_dates_fails_closed(wp4_service):
    with pytest.raises(WorkspaceError) as exc_info:
        wp4_service.get_entity_timeline("ENT_0F0FC38C24C0539E", start="NOT_A_DATE")
    assert exc_info.value.error_code == ErrorCode.INVALID_TIME_RANGE

    with pytest.raises(WorkspaceError) as exc_info:
        wp4_service.get_entity_timeline("ENT_0F0FC38C24C0539E", start="2026-10-01", end="2026-09-01")
    assert exc_info.value.error_code == ErrorCode.INVALID_TIME_RANGE


def test_missing_upstream_directory_fails_closed():
    with pytest.raises(UpstreamContractError):
        WP4Service(data_dir="/tmp/non_existent_dfap_dir_xyz", verify_frozen_manifest=False)


def test_tampered_upstream_artifact_fails_startup():
    """Adversarial test: tampered artifact hash triggers UpstreamIntegrityError at startup."""
    with tempfile.TemporaryDirectory() as tmpdir:
        for f in ["canonical_events.parquet", "provenance_ledger.parquet", "resolved_entities.parquet", "graph_features.parquet", "telecom_features.parquet", "financial_features.parquet", "social_features.parquet"]:
            src = os.path.join("output", f)
            if os.path.exists(src):
                shutil.copy(src, os.path.join(tmpdir, f))
        
        os.makedirs(os.path.join(tmpdir, "m3/findings"), exist_ok=True)
        shutil.copy("output/m3/findings/findings.parquet", os.path.join(tmpdir, "m3/findings/findings.parquet"))

        # Mutate one byte in canonical_events.parquet
        p = os.path.join(tmpdir, "canonical_events.parquet")
        with open(p, "ab") as f:
            f.write(b"CORRUPTION_BYTES")

        with pytest.raises(UpstreamIntegrityError) as exc_info:
            WP4Service(data_dir=tmpdir, verify_frozen_manifest=True)
        assert exc_info.value.error_code == ErrorCode.UPSTREAM_INTEGRITY_ERROR


def test_tampered_telecom_features_fails_startup():
    """Adversarial test: tampered telecom_features.parquet triggers UpstreamIntegrityError."""
    with tempfile.TemporaryDirectory() as tmpdir:
        for f in ["canonical_events.parquet", "provenance_ledger.parquet", "resolved_entities.parquet", "graph_features.parquet", "telecom_features.parquet", "financial_features.parquet", "social_features.parquet"]:
            shutil.copy(os.path.join("output", f), os.path.join(tmpdir, f))
        os.makedirs(os.path.join(tmpdir, "m3/findings"), exist_ok=True)
        shutil.copy("output/m3/findings/findings.parquet", os.path.join(tmpdir, "m3/findings/findings.parquet"))

        with open(os.path.join(tmpdir, "telecom_features.parquet"), "ab") as f:
            f.write(b"CORRUPTION_BYTES")

        with pytest.raises(UpstreamIntegrityError) as exc_info:
            WP4Service(data_dir=tmpdir, verify_frozen_manifest=True)
        assert exc_info.value.error_code == ErrorCode.UPSTREAM_INTEGRITY_ERROR


def test_tampered_financial_features_fails_startup():
    """Adversarial test: tampered financial_features.parquet triggers UpstreamIntegrityError."""
    with tempfile.TemporaryDirectory() as tmpdir:
        for f in ["canonical_events.parquet", "provenance_ledger.parquet", "resolved_entities.parquet", "graph_features.parquet", "telecom_features.parquet", "financial_features.parquet", "social_features.parquet"]:
            shutil.copy(os.path.join("output", f), os.path.join(tmpdir, f))
        os.makedirs(os.path.join(tmpdir, "m3/findings"), exist_ok=True)
        shutil.copy("output/m3/findings/findings.parquet", os.path.join(tmpdir, "m3/findings/findings.parquet"))

        with open(os.path.join(tmpdir, "financial_features.parquet"), "ab") as f:
            f.write(b"CORRUPTION_BYTES")

        with pytest.raises(UpstreamIntegrityError) as exc_info:
            WP4Service(data_dir=tmpdir, verify_frozen_manifest=True)
        assert exc_info.value.error_code == ErrorCode.UPSTREAM_INTEGRITY_ERROR


def test_tampered_social_features_fails_startup():
    """Adversarial test: tampered social_features.parquet triggers UpstreamIntegrityError."""
    with tempfile.TemporaryDirectory() as tmpdir:
        for f in ["canonical_events.parquet", "provenance_ledger.parquet", "resolved_entities.parquet", "graph_features.parquet", "telecom_features.parquet", "financial_features.parquet", "social_features.parquet"]:
            shutil.copy(os.path.join("output", f), os.path.join(tmpdir, f))
        os.makedirs(os.path.join(tmpdir, "m3/findings"), exist_ok=True)
        shutil.copy("output/m3/findings/findings.parquet", os.path.join(tmpdir, "m3/findings/findings.parquet"))

        with open(os.path.join(tmpdir, "social_features.parquet"), "ab") as f:
            f.write(b"CORRUPTION_BYTES")

        with pytest.raises(UpstreamIntegrityError) as exc_info:
            WP4Service(data_dir=tmpdir, verify_frozen_manifest=True)
        assert exc_info.value.error_code == ErrorCode.UPSTREAM_INTEGRITY_ERROR


def test_corrupted_canonical_hash_fails_closed():
    """Adversarial test: tamper with canonical_event.sha256_hash."""
    with tempfile.TemporaryDirectory() as tmpdir:
        for f in ["canonical_events.parquet", "provenance_ledger.parquet", "resolved_entities.parquet", "graph_features.parquet", "telecom_features.parquet", "financial_features.parquet", "social_features.parquet"]:
            shutil.copy(os.path.join("output", f), os.path.join(tmpdir, f))
        
        os.makedirs(os.path.join(tmpdir, "m3/findings"), exist_ok=True)
        shutil.copy("output/m3/findings/findings.parquet", os.path.join(tmpdir, "m3/findings/findings.parquet"))

        df_events = pd.read_parquet(os.path.join(tmpdir, "canonical_events.parquet"))
        df_events.loc[0, "sha256_hash"] = "0" * 64
        df_events.to_parquet(os.path.join(tmpdir, "canonical_events.parquet"), index=False)

        service = WP4Service(data_dir=tmpdir, verify_frozen_manifest=False)
        findings = service.list_findings()

        with pytest.raises(EvidenceChainError) as exc_info:
            for f in findings:
                service.get_evidence_chain(f["finding_id"])
        assert exc_info.value.error_code == ErrorCode.INVALID_SHA256


def test_corrupted_provenance_hash_fails_closed():
    """Adversarial test: tamper with provenance_ledger.sha256_hash."""
    with tempfile.TemporaryDirectory() as tmpdir:
        for f in ["canonical_events.parquet", "provenance_ledger.parquet", "resolved_entities.parquet", "graph_features.parquet", "telecom_features.parquet", "financial_features.parquet", "social_features.parquet"]:
            shutil.copy(os.path.join("output", f), os.path.join(tmpdir, f))
        
        os.makedirs(os.path.join(tmpdir, "m3/findings"), exist_ok=True)
        shutil.copy("output/m3/findings/findings.parquet", os.path.join(tmpdir, "m3/findings/findings.parquet"))

        df_prov = pd.read_parquet(os.path.join(tmpdir, "provenance_ledger.parquet"))
        df_prov.loc[0, "sha256_hash"] = "f" * 64
        df_prov.to_parquet(os.path.join(tmpdir, "provenance_ledger.parquet"), index=False)

        service = WP4Service(data_dir=tmpdir, verify_frozen_manifest=False)
        findings = service.list_findings()

        with pytest.raises(EvidenceChainError) as exc_info:
            for f in findings:
                service.get_evidence_chain(f["finding_id"])
        assert exc_info.value.error_code == ErrorCode.INVALID_SHA256


def test_missing_raw_source_attributes_fails_closed():
    """Adversarial test: canonical event missing raw_source_attributes fails closed."""
    with tempfile.TemporaryDirectory() as tmpdir:
        for f in ["canonical_events.parquet", "provenance_ledger.parquet", "resolved_entities.parquet", "graph_features.parquet", "telecom_features.parquet", "financial_features.parquet", "social_features.parquet"]:
            shutil.copy(os.path.join("output", f), os.path.join(tmpdir, f))
        
        os.makedirs(os.path.join(tmpdir, "m3/findings"), exist_ok=True)
        shutil.copy("output/m3/findings/findings.parquet", os.path.join(tmpdir, "m3/findings/findings.parquet"))

        df_events = pd.read_parquet(os.path.join(tmpdir, "canonical_events.parquet"))
        df_events.loc[0, "attributes"] = json.dumps({"actor_name": "Tampered", "raw_source_attributes": None})
        df_events.to_parquet(os.path.join(tmpdir, "canonical_events.parquet"), index=False)

        service = WP4Service(data_dir=tmpdir, verify_frozen_manifest=False)
        findings = service.list_findings()

        with pytest.raises(EvidenceChainError) as exc_info:
            for f in findings:
                service.get_evidence_chain(f["finding_id"])
        assert exc_info.value.error_code == ErrorCode.INVALID_SHA256


def test_missing_source_provenance_metadata_fails_closed():
    """Adversarial test: provenance ledger missing source_file or source_row_index fails closed."""
    with tempfile.TemporaryDirectory() as tmpdir:
        for f in ["canonical_events.parquet", "provenance_ledger.parquet", "resolved_entities.parquet", "graph_features.parquet", "telecom_features.parquet", "financial_features.parquet", "social_features.parquet"]:
            shutil.copy(os.path.join("output", f), os.path.join(tmpdir, f))
        
        os.makedirs(os.path.join(tmpdir, "m3/findings"), exist_ok=True)
        shutil.copy("output/m3/findings/findings.parquet", os.path.join(tmpdir, "m3/findings/findings.parquet"))

        df_prov = pd.read_parquet(os.path.join(tmpdir, "provenance_ledger.parquet"))
        df_prov.loc[0, "source_file"] = None
        df_prov.to_parquet(os.path.join(tmpdir, "provenance_ledger.parquet"), index=False)

        service = WP4Service(data_dir=tmpdir, verify_frozen_manifest=False)
        findings = service.list_findings()

        with pytest.raises(EvidenceChainError) as exc_info:
            for f in findings:
                service.get_evidence_chain(f["finding_id"])
        assert exc_info.value.error_code == ErrorCode.MISSING_PROVENANCE


def test_invalid_workspace_entity_and_finding_id_fail_closed(wp4_service):
    """Verifies that selecting an invalid entity_id or finding_id raises a typed WorkspaceError."""
    with pytest.raises(WorkspaceError) as exc_info:
        wp4_service.update_workspace_state(selected_entity_id="ENT_NON_EXISTENT_ID_999")
    assert exc_info.value.error_code == ErrorCode.SCHEMA_CONTRACT_ERROR

    with pytest.raises(WorkspaceError) as exc_info:
        wp4_service.update_workspace_state(selected_finding_id="FND_NON_EXISTENT_ID_999")
    assert exc_info.value.error_code == ErrorCode.UNKNOWN_FINDING


def test_malformed_upstream_timestamp_fails_closed():
    """Adversarial test: corrupted event timestamp in timeline fails closed."""
    df_events = pd.read_parquet("output/canonical_events.parquet").copy()
    df_entities = pd.read_parquet("output/resolved_entities.parquet").copy()
    
    df_events.loc[0, "timestamp"] = "CORRUPTED_TIMESTAMP_NOT_ISO"
    
    tl_service = TimelineService(df_events, df_entities)
    target_ent = df_events.loc[0, "actor_id"]
    
    with pytest.raises(WorkspaceError) as exc_info:
        tl_service.get_entity_timeline(target_ent)
    assert exc_info.value.error_code == ErrorCode.INVALID_TIME_RANGE


def test_get_events_with_missing_id_fails_closed(wp4_service):
    """Verifies that requesting a batch containing any missing event ID raises MISSING_EVENT."""
    with pytest.raises(EvidenceChainError) as exc_info:
        wp4_service.get_events(["EVT_80E854E8D3B557DC", "EVT_NON_EXISTENT_999"])
    assert exc_info.value.error_code == ErrorCode.MISSING_EVENT


# ── EXPLICIT STARTUP SCHEMA VALIDATION ADVERSARIAL TESTS ──────────────────────

def test_schema_missing_event_id_fails_startup():
    """Adversarial test: canonical_events missing event_id fails with SCHEMA_CONTRACT_ERROR."""
    with tempfile.TemporaryDirectory() as tmpdir:
        for f in ["canonical_events.parquet", "provenance_ledger.parquet", "resolved_entities.parquet", "graph_features.parquet", "telecom_features.parquet", "financial_features.parquet", "social_features.parquet"]:
            shutil.copy(os.path.join("output", f), os.path.join(tmpdir, f))
        os.makedirs(os.path.join(tmpdir, "m3/findings"), exist_ok=True)
        shutil.copy("output/m3/findings/findings.parquet", os.path.join(tmpdir, "m3/findings/findings.parquet"))

        df = pd.read_parquet(os.path.join(tmpdir, "canonical_events.parquet"))
        df.drop(columns=["event_id"]).to_parquet(os.path.join(tmpdir, "canonical_events.parquet"), index=False)

        with pytest.raises(UpstreamContractError) as exc_info:
            WP4Service(data_dir=tmpdir, verify_frozen_manifest=False)
        assert exc_info.value.error_code == ErrorCode.SCHEMA_CONTRACT_ERROR


def test_schema_missing_sha256_hash_fails_startup():
    """Adversarial test: provenance_ledger missing sha256_hash fails with SCHEMA_CONTRACT_ERROR."""
    with tempfile.TemporaryDirectory() as tmpdir:
        for f in ["canonical_events.parquet", "provenance_ledger.parquet", "resolved_entities.parquet", "graph_features.parquet", "telecom_features.parquet", "financial_features.parquet", "social_features.parquet"]:
            shutil.copy(os.path.join("output", f), os.path.join(tmpdir, f))
        os.makedirs(os.path.join(tmpdir, "m3/findings"), exist_ok=True)
        shutil.copy("output/m3/findings/findings.parquet", os.path.join(tmpdir, "m3/findings/findings.parquet"))

        df = pd.read_parquet(os.path.join(tmpdir, "provenance_ledger.parquet"))
        df.drop(columns=["sha256_hash"]).to_parquet(os.path.join(tmpdir, "provenance_ledger.parquet"), index=False)

        with pytest.raises(UpstreamContractError) as exc_info:
            WP4Service(data_dir=tmpdir, verify_frozen_manifest=False)
        assert exc_info.value.error_code == ErrorCode.SCHEMA_CONTRACT_ERROR


def test_schema_missing_feature_name_fails_startup():
    """Adversarial test: graph_features missing feature_name fails with SCHEMA_CONTRACT_ERROR."""
    with tempfile.TemporaryDirectory() as tmpdir:
        for f in ["canonical_events.parquet", "provenance_ledger.parquet", "resolved_entities.parquet", "graph_features.parquet", "telecom_features.parquet", "financial_features.parquet", "social_features.parquet"]:
            shutil.copy(os.path.join("output", f), os.path.join(tmpdir, f))
        os.makedirs(os.path.join(tmpdir, "m3/findings"), exist_ok=True)
        shutil.copy("output/m3/findings/findings.parquet", os.path.join(tmpdir, "m3/findings/findings.parquet"))

        df = pd.read_parquet(os.path.join(tmpdir, "graph_features.parquet"))
        df.drop(columns=["feature_name"]).to_parquet(os.path.join(tmpdir, "graph_features.parquet"), index=False)

        with pytest.raises(UpstreamContractError) as exc_info:
            WP4Service(data_dir=tmpdir, verify_frozen_manifest=False)
        assert exc_info.value.error_code == ErrorCode.SCHEMA_CONTRACT_ERROR


def test_schema_missing_finding_id_fails_startup():
    """Adversarial test: findings missing finding_id fails with SCHEMA_CONTRACT_ERROR."""
    with tempfile.TemporaryDirectory() as tmpdir:
        for f in ["canonical_events.parquet", "provenance_ledger.parquet", "resolved_entities.parquet", "graph_features.parquet", "telecom_features.parquet", "financial_features.parquet", "social_features.parquet"]:
            shutil.copy(os.path.join("output", f), os.path.join(tmpdir, f))
        os.makedirs(os.path.join(tmpdir, "m3/findings"), exist_ok=True)
        shutil.copy("output/m3/findings/findings.parquet", os.path.join(tmpdir, "m3/findings/findings.parquet"))

        df = pd.read_parquet(os.path.join(tmpdir, "m3/findings/findings.parquet"))
        df.drop(columns=["finding_id"]).to_parquet(os.path.join(tmpdir, "m3/findings/findings.parquet"), index=False)

        with pytest.raises(UpstreamContractError) as exc_info:
            WP4Service(data_dir=tmpdir, verify_frozen_manifest=False)
        assert exc_info.value.error_code == ErrorCode.SCHEMA_CONTRACT_ERROR
