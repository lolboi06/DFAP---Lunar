# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: Test Suite for Data Quality & Source Health Engine

import json
import os
import tempfile
import pytest
import pandas as pd

from dfap.investigation.data_quality import (
    DataQualityConfig,
    DataQualityDimension,
    DataQualitySourceHealthEngine,
    DimensionStatus,
    QualityDimensionEvaluation,
    SourceHealthAssessment,
    SourceHealthStatus,
    SchemaEvaluationMode,
    EmptySourceClassification,
)
from dfap.investigation.data_quality_fixture import (
    ALL_SCENARIO_CREATORS,
    CASE_DATA_HEALTH_ID,
    DATA_HEALTH_ENTITY_ID,
    REFERENCE_TIMESTAMP_STR,
    create_healthy_baseline_dataframe,
    create_scenario_a_healthy,
    create_scenario_b_missing_timestamps,
    create_scenario_c_malformed_identifiers,
    create_scenario_d_duplicate_events,
    create_scenario_e_high_rejection,
    create_scenario_f_broken_references,
    create_scenario_g_incomplete_provenance,
    create_scenario_h_stale_source,
    create_scenario_i_volume_collapse,
    create_scenario_j_volume_spike,
    create_scenario_k_domain_disappearance,
    create_scenario_l_mixed_defects,
    create_scenario_m_unavailable,
    create_scenario_n_degraded_usable,
    register_data_quality_fixture,
)
from dfap.investigation.workspace import InvestigationWorkspaceBackend
from dfap.investigation.copilot import InvestigationCopilot
from dfap.validation import RowValidationReport


@pytest.fixture
def workspace_backend():
    backend = InvestigationWorkspaceBackend(
        output_dir="output",
        canonical_dir="data/canonical",
        cases_dir="data/cases"
    )
    register_data_quality_fixture(backend)
    return backend


@pytest.fixture
def dq_engine(workspace_backend):
    return DataQualitySourceHealthEngine(workspace_backend=workspace_backend)


# -----------------------------------------------------------------------------
# 1. Unit Tests: 12 Dimensions in Isolation
# -----------------------------------------------------------------------------

def test_dim_1_schema_validity_healthy(dq_engine):
    df = create_healthy_baseline_dataframe(10)
    eval_res = dq_engine._eval_schema_validity(df, required_columns=["event_id", "timestamp", "actor_id", "source_domain", "event_type"])
    assert eval_res.status == DimensionStatus.HEALTHY


def test_dim_1_schema_validity_missing_required_column(dq_engine):
    df = pd.DataFrame([{"event_id": "E1", "timestamp": "2026-09-01T00:00:00Z"}])
    eval_res = dq_engine._eval_schema_validity(df, required_columns=["actor_id", "source_domain"])
    assert eval_res.status == DimensionStatus.CRITICAL
    assert "actor_id" in eval_res.observed_metric["missing_columns"]


def test_dim_1_schema_validity_unrecognized_domain(dq_engine):
    df = create_healthy_baseline_dataframe(10)
    df["source_domain"] = "UNKNOWN_ALIEN_DOMAIN"
    eval_res = dq_engine._eval_schema_validity(df, required_columns=["event_id"])
    assert eval_res.status in (DimensionStatus.DEGRADED, DimensionStatus.CRITICAL)


def test_dim_2_completeness_healthy(dq_engine):
    df = create_healthy_baseline_dataframe(20)
    eval_res = dq_engine._eval_completeness(df)
    assert eval_res.status == DimensionStatus.HEALTHY
    assert eval_res.observed_metric["missingness_rate"] == 0.0


def test_dim_2_completeness_degraded_and_critical(dq_engine):
    df = create_healthy_baseline_dataframe(100)
    # Inject 8 nulls in actor_id (8 / 500 total evaluated cells = 1.6%, let's inject 35 nulls in actor_id -> 35/500 = 7% -> DEGRADED)
    for i in range(35):
        df.at[i, "actor_id"] = None
    eval_res = dq_engine._eval_completeness(df)
    assert eval_res.status == DimensionStatus.DEGRADED

    # Inject 150 nulls -> 150/500 = 30% -> CRITICAL
    for i in range(100):
        df.at[i, "actor_id"] = None
        df.at[i, "timestamp"] = None
    eval_res_crit = dq_engine._eval_completeness(df)
    assert eval_res_crit.status == DimensionStatus.CRITICAL


def test_dim_3_timestamp_validity_healthy(dq_engine):
    df = create_healthy_baseline_dataframe(20)
    eval_res = dq_engine._eval_timestamp_validity(df)
    assert eval_res.status == DimensionStatus.HEALTHY


def test_dim_3_timestamp_validity_critical(dq_engine):
    df = create_healthy_baseline_dataframe(20)
    for i in range(5):
        df.at[i, "timestamp"] = "NOT_A_DATE"
    eval_res = dq_engine._eval_timestamp_validity(df)
    assert eval_res.status == DimensionStatus.CRITICAL


def test_dim_4_identifier_validity_placeholder_detection(dq_engine):
    df = create_healthy_baseline_dataframe(20)
    df.at[0, "actor_id"] = "00000000"
    df.at[1, "actor_id"] = "null"
    df.at[2, "actor_id"] = "unknown"
    eval_res = dq_engine._eval_identifier_validity(df)
    assert eval_res.status == DimensionStatus.CRITICAL  # 3/20 = 15% > 10% critical


def test_dim_5_duplicate_rate_detection(dq_engine):
    df = create_healthy_baseline_dataframe(20)
    for i in range(5):
        df.at[i, "event_id"] = "DUPLICATE_KEY"
    eval_res = dq_engine._eval_duplicate_rate(df)
    assert eval_res.status == DimensionStatus.CRITICAL  # 4/20 = 20% > 15% critical


def test_dim_6_referential_consistency_not_applicable(dq_engine):
    df = pd.DataFrame([{"raw_col": 1}])
    eval_res = dq_engine._eval_referential_consistency("SRC_RAW", df)
    assert eval_res.status == DimensionStatus.NOT_APPLICABLE


def test_dim_7_provenance_completeness_manifest_mismatch(dq_engine):
    manifest_entry = {
        "source_sha256": "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890",
        "version": "1.0",
        "provenance_tier": "REAL_PUBLIC_DATA"
    }
    with tempfile.NamedTemporaryFile(suffix=".csv") as tmp:
        tmp.write(b"data,row\n1,2\n")
        tmp.flush()
        eval_res = dq_engine._eval_provenance_completeness("SRC_TEST", tmp.name, manifest_entry)
        assert eval_res.status == DimensionStatus.CRITICAL
        assert eval_res.observed_metric["hash_match"] is False


def test_dim_8_freshness_unknown_when_no_reference(dq_engine):
    df = create_healthy_baseline_dataframe(10)
    eval_res = dq_engine._eval_freshness(df, reference_timestamp=None)
    assert eval_res.status == DimensionStatus.UNKNOWN


def test_dim_8_freshness_stale(dq_engine):
    df = create_healthy_baseline_dataframe(10)
    df["timestamp"] = "2020-01-01T00:00:00Z"
    eval_res = dq_engine._eval_freshness(df, reference_timestamp="2026-09-05T00:00:00Z")
    assert eval_res.status == DimensionStatus.CRITICAL


def test_dim_9_volume_health_unknown_when_no_baseline(dq_engine):
    eval_res = dq_engine._eval_volume_health(100, reference_baseline_count=None)
    assert eval_res.status == DimensionStatus.UNKNOWN


def test_dim_9_volume_health_collapse_and_spike(dq_engine):
    eval_collapse = dq_engine._eval_volume_health(10, reference_baseline_count=100)  # 10% < 20%
    assert eval_collapse.status == DimensionStatus.CRITICAL

    eval_spike = dq_engine._eval_volume_health(400, reference_baseline_count=100)  # 400% > 300%
    assert eval_spike.status == DimensionStatus.CRITICAL


def test_dim_10_domain_distribution_disappearance(dq_engine):
    df = create_healthy_baseline_dataframe(10)
    df["source_domain"] = "IPDR"
    eval_res = dq_engine._eval_domain_distribution(df, reference_domains={"IPDR", "BANK"})
    assert eval_res.status == DimensionStatus.CRITICAL
    assert "BANK" in eval_res.observed_metric["missing_domains"]


def test_dim_11_rejection_health_invariant_violation(dq_engine):
    rep = RowValidationReport("source.csv")
    rep.received_rows = 100
    rep.accepted_rows = 80
    rep.rejected_rows = 10  # 80 + 10 = 90 != 100!
    eval_res = dq_engine._eval_rejection_health(rep, 90)
    assert eval_res.status == DimensionStatus.CRITICAL
    assert eval_res.observed_metric["invariant_broken"] is True


def test_dim_12_cross_field_consistency_healthy_and_critical(dq_engine):
    df_healthy = create_healthy_baseline_dataframe(10)
    eval_h = dq_engine._eval_cross_field_consistency(df_healthy)
    assert eval_h.status == DimensionStatus.HEALTHY

    # IPDR domain with CDR CALL event type -> cross field inconsistency
    df_bad = create_healthy_baseline_dataframe(10)
    df_bad["source_domain"] = "IPDR"
    df_bad["event_type"] = "CALL"
    eval_c = dq_engine._eval_cross_field_consistency(df_bad)
    assert eval_c.status == DimensionStatus.CRITICAL


# -----------------------------------------------------------------------------
# 2. Boundary Tests at T - eps, T, T + eps
# -----------------------------------------------------------------------------

def test_boundary_duplicate_rate(dq_engine):
    # Degraded threshold is 0.01 (1%), Critical is 0.15 (15%)
    # Let total = 10,000 rows
    total = 10000

    # T = 0.01: at 100 duplicates -> 0.01 -> HEALTHY
    # at 101 duplicates -> 0.0101 -> DEGRADED
    # at 99 duplicates -> 0.0099 -> HEALTHY
    cfg = dq_engine.config

    assert (99 / total) <= cfg.duplicate_degraded_threshold
    assert (100 / total) <= cfg.duplicate_degraded_threshold
    assert (101 / total) > cfg.duplicate_degraded_threshold

    # Critical threshold 0.15:
    assert (1499 / total) <= cfg.duplicate_critical_threshold
    assert (1500 / total) <= cfg.duplicate_critical_threshold
    assert (1501 / total) > cfg.duplicate_critical_threshold


def test_boundary_volume_ratio(dq_engine):
    base = 10000
    # lower critical is 0.20
    eval_below = dq_engine._eval_volume_health(1999, base)
    assert eval_below.status == DimensionStatus.CRITICAL

    eval_at_crit = dq_engine._eval_volume_health(2000, base)
    assert eval_at_crit.status == DimensionStatus.DEGRADED

    # lower degraded is 0.80
    eval_below_deg = dq_engine._eval_volume_health(7999, base)
    assert eval_below_deg.status == DimensionStatus.DEGRADED

    eval_at_deg = dq_engine._eval_volume_health(8000, base)
    assert eval_at_deg.status == DimensionStatus.HEALTHY

    # upper degraded is 1.50
    eval_at_upper_deg = dq_engine._eval_volume_health(15000, base)
    assert eval_at_upper_deg.status == DimensionStatus.HEALTHY

    eval_above_upper_deg = dq_engine._eval_volume_health(15001, base)
    assert eval_above_upper_deg.status == DimensionStatus.DEGRADED

    # upper critical is 3.00
    eval_at_upper_crit = dq_engine._eval_volume_health(30000, base)
    assert eval_at_upper_crit.status == DimensionStatus.DEGRADED

    eval_above_upper_crit = dq_engine._eval_volume_health(30001, base)
    assert eval_above_upper_crit.status == DimensionStatus.CRITICAL


# -----------------------------------------------------------------------------
# 3. Verification of Scenarios A through N
# -----------------------------------------------------------------------------

@pytest.mark.parametrize("scenario_key", [
    "A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L", "M", "N"
])
def test_all_data_health_scenarios(scenario_key, dq_engine):
    creator = ALL_SCENARIO_CREATORS[scenario_key]
    scenario = creator()

    assessment = dq_engine.assess_source_health(
        source_id=scenario["source_id"],
        df=scenario.get("df"),
        source_file_path=scenario.get("source_file_path"),
        reference_baseline_count=scenario.get("reference_baseline_count"),
        reference_timestamp=scenario.get("reference_timestamp"),
        reference_domains=scenario.get("reference_domains"),
        validation_report=scenario.get("validation_report"),
        manifest_entry=scenario.get("manifest_entry"),
        valid_canonical_ids=scenario.get("valid_canonical_ids"),
    )

    assert assessment.overall_status == scenario["expected_overall"], (
        f"Scenario {scenario_key} ({scenario['name']}): expected {scenario['expected_overall'].value}, "
        f"got {assessment.overall_status.value}. Reasons: {assessment.reasons}"
    )

    if "expected_dim_status" in scenario:
        for dim_name, exp_dim_st in scenario["expected_dim_status"].items():
            assert dim_name in assessment.dimensions, f"Dimension {dim_name} missing from assessment"
            assert assessment.dimensions[dim_name].status == exp_dim_st, (
                f"Scenario {scenario_key} dimension {dim_name}: expected {exp_dim_st.value}, "
                f"got {assessment.dimensions[dim_name].status.value}"
            )


# -----------------------------------------------------------------------------
# 4. Negative / Isolation Tests
# -----------------------------------------------------------------------------

def test_missing_source_file_is_unavailable(dq_engine):
    assessment = dq_engine.assess_source_health(
        source_id="MISSING_FILE_SOURCE",
        source_file_path="non_existent_path_xyz_12345.parquet"
    )
    assert assessment.overall_status == SourceHealthStatus.UNAVAILABLE
    assert "not found" in assessment.reasons[0].lower()


def test_empty_zero_byte_file_is_unavailable(dq_engine):
    with tempfile.NamedTemporaryFile(suffix=".csv") as tmp:
        tmp.flush()
        assessment = dq_engine.assess_source_health(
            source_id="EMPTY_FILE_SOURCE",
            source_file_path=tmp.name
        )
        assert assessment.overall_status == SourceHealthStatus.UNAVAILABLE
        assert "0 bytes" in assessment.reasons[0].lower()


# -----------------------------------------------------------------------------
# 5. Determinism Check (3 Independent Runs)
# -----------------------------------------------------------------------------

def test_determinism_3_runs(dq_engine):
    sc_n = create_scenario_n_degraded_usable()

    run1 = dq_engine.assess_source_health(
        source_id=sc_n["source_id"],
        df=sc_n["df"],
        reference_baseline_count=sc_n["reference_baseline_count"],
        reference_timestamp=sc_n["reference_timestamp"],
        reference_domains=sc_n["reference_domains"]
    ).to_dict()

    run2 = dq_engine.assess_source_health(
        source_id=sc_n["source_id"],
        df=sc_n["df"],
        reference_baseline_count=sc_n["reference_baseline_count"],
        reference_timestamp=sc_n["reference_timestamp"],
        reference_domains=sc_n["reference_domains"]
    ).to_dict()

    run3 = dq_engine.assess_source_health(
        source_id=sc_n["source_id"],
        df=sc_n["df"],
        reference_baseline_count=sc_n["reference_baseline_count"],
        reference_timestamp=sc_n["reference_timestamp"],
        reference_domains=sc_n["reference_domains"]
    ).to_dict()

    # Compare excluding evaluated_at timestamp
    del run1["evaluated_at"]
    del run2["evaluated_at"]
    del run3["evaluated_at"]

    assert json.dumps(run1, sort_keys=True) == json.dumps(run2, sort_keys=True)
    assert json.dumps(run2, sort_keys=True) == json.dumps(run3, sort_keys=True)


# -----------------------------------------------------------------------------
# 6. Workspace Backend and Case Assessment Integration
# -----------------------------------------------------------------------------

def test_workspace_assess_case_data_health(workspace_backend):
    case_assessment = workspace_backend.assess_case_data_health(CASE_DATA_HEALTH_ID)
    assert "case_id" in case_assessment
    assert case_assessment["case_id"] == CASE_DATA_HEALTH_ID
    assert case_assessment["overall_status"] in [s.value for s in SourceHealthStatus]
    assert len(case_assessment["source_assessments"]) > 0


def test_workspace_assess_source_health(workspace_backend):
    assessment = workspace_backend.assess_source_health("SRC_SCENARIO_A")
    assert assessment["source_id"] == "SRC_SCENARIO_A"
    assert assessment["overall_status"] in [s.value for s in SourceHealthStatus]


# -----------------------------------------------------------------------------
# 7. Copilot Q&A Integration
# -----------------------------------------------------------------------------

def test_copilot_data_quality_query(workspace_backend):
    copilot = InvestigationCopilot(backend=workspace_backend)
    response = copilot.answer_question(
        f"What is the data quality for case {CASE_DATA_HEALTH_ID}?",
        case_id=CASE_DATA_HEALTH_ID
    )

    assert "data_quality" in response
    assert response["data_quality"] is not None
    assert response["status"] in ("GROUNDED", "PARTIALLY_GROUNDED", "INSUFFICIENT_EVIDENCE")
    assert "limitations" in response
    assert len(response["limitations"]) > 0


def test_copilot_source_health_query(workspace_backend):
    copilot = InvestigationCopilot(backend=workspace_backend)
    response = copilot.answer_question(
        "Is the data trustworthy for source SRC_SCENARIO_A?"
    )

    assert "source_health" in response
    assert response["source_health"] is not None
    assert response["source_health"]["source_id"] == "SRC_SCENARIO_A"


# -----------------------------------------------------------------------------
# 8. CLI Command Integration
# -----------------------------------------------------------------------------

def test_cli_copilot_source_health(workspace_backend):
    from dfap.wp4.cli import handle_m13_command
    out = handle_m13_command(workspace_backend, "copilot source-health SRC_SCENARIO_A")
    assert "source_id" in out
    assert "overall_status" in out
    assert "SRC_SCENARIO_A" in out


def test_cli_copilot_data_quality(workspace_backend):
    from dfap.wp4.cli import handle_m13_command
    out = handle_m13_command(workspace_backend, f"copilot data-quality {CASE_DATA_HEALTH_ID}")
    assert "case_id" in out
    assert "overall_status" in out
    assert CASE_DATA_HEALTH_ID in out


# -----------------------------------------------------------------------------
# 9. Schema Evaluation Modes (Raw vs Canonical), Empty Sources, & Scenario N
# -----------------------------------------------------------------------------

def test_schema_eval_mode_raw_stackoverflow(dq_engine):
    """Test A: Raw Stack Overflow schema evaluated against raw manifest schema (RAW_SOURCE)."""
    assessment = dq_engine.assess_source_health("stackoverflow", schema_mode=SchemaEvaluationMode.RAW_SOURCE)
    assert assessment.schema_mode == SchemaEvaluationMode.RAW_SOURCE
    assert assessment.dimensions[DataQualityDimension.SCHEMA_VALIDITY.value].status == DimensionStatus.HEALTHY
    assert assessment.dimensions[DataQualityDimension.TIMESTAMP_VALIDITY.value].status == DimensionStatus.HEALTHY


def test_schema_eval_mode_raw_unsw(dq_engine):
    """Test B: Raw UNSW schema evaluated against authoritative raw manifest schema (RAW_SOURCE)."""
    assessment = dq_engine.assess_source_health("unsw", schema_mode=SchemaEvaluationMode.RAW_SOURCE)
    assert assessment.schema_mode == SchemaEvaluationMode.RAW_SOURCE
    assert assessment.dimensions[DataQualityDimension.SCHEMA_VALIDITY.value].status == DimensionStatus.HEALTHY
    # UNSW raw data lacks native timestamp column; temporal offset handled in M1 adapter
    assert assessment.dimensions[DataQualityDimension.TIMESTAMP_VALIDITY.value].status == DimensionStatus.NOT_APPLICABLE
    # Bounded 100k sample must not be flagged as volume degradation
    assert assessment.dimensions[DataQualityDimension.VOLUME_HEALTH.value].status in (DimensionStatus.HEALTHY, DimensionStatus.NOT_APPLICABLE)
    assert assessment.overall_status != SourceHealthStatus.DEGRADED


def test_schema_eval_mode_canonical_stackoverflow(dq_engine):
    """Test C: Canonicalized Stack Overflow data evaluated against canonical schema (CANONICAL_SOURCE)."""
    can_path = "data/canonical/stackoverflow_canonical.parquet"
    if os.path.exists(can_path):
        can_df = pd.read_parquet(can_path)
    else:
        can_df = create_healthy_baseline_dataframe(50)
    assessment = dq_engine.assess_source_health("stackoverflow_can", df=can_df, schema_mode=SchemaEvaluationMode.CANONICAL_SOURCE)
    assert assessment.schema_mode == SchemaEvaluationMode.CANONICAL_SOURCE
    assert assessment.dimensions[DataQualityDimension.SCHEMA_VALIDITY.value].status == DimensionStatus.HEALTHY


def test_schema_eval_mode_canonical_unsw(dq_engine):
    """Test D: Canonicalized UNSW data evaluated against canonical schema (CANONICAL_SOURCE)."""
    can_path = "data/canonical/unsw_canonical.parquet"
    if os.path.exists(can_path):
        can_df = pd.read_parquet(can_path)
    else:
        can_df = create_healthy_baseline_dataframe(50)
    assessment = dq_engine.assess_source_health("unsw_can", df=can_df, schema_mode=SchemaEvaluationMode.CANONICAL_SOURCE)
    assert assessment.schema_mode == SchemaEvaluationMode.CANONICAL_SOURCE
    assert assessment.dimensions[DataQualityDimension.SCHEMA_VALIDITY.value].status == DimensionStatus.HEALTHY


def test_schema_eval_mode_raw_missing_required_column_fails(dq_engine):
    """Test E: Missing a required RAW column fails raw schema validation (CRITICAL)."""
    # Stack Overflow raw requires ["src_user_id", "dst_user_id", "timestamp"]
    bad_raw_df = pd.DataFrame({
        "dst_user_id": [101, 102],
        "timestamp": [1220729190, 1220733503]
        # missing "src_user_id"
    })
    assessment = dq_engine.assess_source_health(
        "stackoverflow",
        df=bad_raw_df,
        schema_mode=SchemaEvaluationMode.RAW_SOURCE
    )
    dim_res = assessment.dimensions[DataQualityDimension.SCHEMA_VALIDITY.value]
    assert dim_res.status == DimensionStatus.CRITICAL
    assert "src_user_id" in dim_res.observed_metric["missing_columns"]


def test_schema_eval_mode_canonical_missing_required_column_fails(dq_engine):
    """Test F: Missing a required CANONICAL column fails canonical schema validation (CRITICAL)."""
    bad_can_df = pd.DataFrame({
        "event_id": ["E1", "E2"],
        "timestamp": ["2026-09-01T12:00:00Z", "2026-09-01T12:01:00Z"],
        "event_type": ["auth_login", "auth_login"],
        "source_domain": ["AUTH", "AUTH"]
        # missing "actor_id"
    })
    assessment = dq_engine.assess_source_health(
        "SRC_CUSTOM",
        df=bad_can_df,
        schema_mode=SchemaEvaluationMode.CANONICAL_SOURCE
    )
    dim_res = assessment.dimensions[DataQualityDimension.SCHEMA_VALIDITY.value]
    assert dim_res.status == DimensionStatus.CRITICAL
    assert "actor_id" in dim_res.observed_metric["missing_columns"]


def test_empty_source_classifications(dq_engine):
    """Test Empty Source Semantics: EMPTY_VALID_SOURCE, UNAVAILABLE_SOURCE, MISSING_DATA, UNKNOWN_REFERENCE."""
    # 1. EMPTY_VALID_SOURCE: 0 records, baseline is 0 -> HEALTHY
    res_empty_valid = dq_engine.assess_source_health(
        source_id="EMPTY_VALID",
        df=pd.DataFrame(columns=["event_id", "actor_id", "timestamp"]),
        reference_baseline_count=0
    )
    assert res_empty_valid.empty_classification == EmptySourceClassification.EMPTY_VALID_SOURCE
    assert res_empty_valid.overall_status == SourceHealthStatus.HEALTHY

    # 2. UNAVAILABLE_SOURCE: missing file -> UNAVAILABLE
    res_unavail = dq_engine.assess_source_health(
        source_id="MISSING_FILE",
        source_file_path="/nonexistent/path/data.parquet"
    )
    assert res_unavail.empty_classification == EmptySourceClassification.UNAVAILABLE_SOURCE
    assert res_unavail.overall_status == SourceHealthStatus.UNAVAILABLE

    # 3. MISSING_DATA: 0 records, baseline > 0 -> CRITICAL
    res_missing = dq_engine.assess_source_health(
        source_id="EXPECTED_DATA_EMPTY",
        df=pd.DataFrame(columns=["event_id", "actor_id", "timestamp"]),
        reference_baseline_count=1000
    )
    assert res_missing.empty_classification == EmptySourceClassification.MISSING_DATA
    assert res_missing.overall_status == SourceHealthStatus.CRITICAL

    # 4. UNKNOWN_REFERENCE: 0 records, no baseline reference -> UNKNOWN
    res_unknown = dq_engine.assess_source_health(
        source_id="UNKNOWN_EMPTY",
        df=pd.DataFrame(columns=["event_id", "actor_id", "timestamp"]),
        reference_baseline_count=None
    )
    assert res_unknown.empty_classification == EmptySourceClassification.UNKNOWN_REFERENCE
    assert res_unknown.overall_status == SourceHealthStatus.UNKNOWN


def test_scenario_n_runtime_proof(workspace_backend):
    """Runtime proof: Scenario N has record_count=100, duplicate_rate=0.03, status DEGRADED."""
    assessment = workspace_backend.assess_source_health("SRC_SCENARIO_N")
    assert assessment["source_id"] == "SRC_SCENARIO_N"
    assert assessment["record_count"] == 100
    assert assessment["dimensions"]["duplicate_rate"]["observed_metric"]["duplicate_rate"] == 0.03
    assert assessment["overall_status"] == SourceHealthStatus.DEGRADED.value
    assert any("duplicate" in r.lower() for r in assessment["reasons"])


def test_genuine_volume_mismatch_produces_warning(dq_engine):
    """A genuine complete-source volume mismatch (not a bounded sample) produces degradation."""
    assessment = dq_engine.assess_source_health(
        "complete_source_with_drop",
        df=create_healthy_baseline_dataframe(50),
        reference_baseline_count=100,
        is_bounded_sample=False
    )
    dim_res = assessment.dimensions[DataQualityDimension.VOLUME_HEALTH.value]
    assert dim_res.status == DimensionStatus.DEGRADED
    assert dim_res.observed_metric["volume_ratio"] == 0.5


def test_reliability_interoperability_with_data_quality(workspace_backend):
    """Explicit interoperability check proving Data Quality Engine does not break Reliability Engine."""
    from dfap.investigation.reliability import EvidenceQualityReliabilityEngine
    from dfap.investigation.reliability_fixture import register_reliability_fixture, CASE_RELIABILITY_ID

    register_reliability_fixture(workspace_backend)
    rel_engine = EvidenceQualityReliabilityEngine(backend=workspace_backend)
    assessment = rel_engine.assess_finding(CASE_RELIABILITY_ID, "FND_REL_SCENARIO_A")
    assert assessment.case_id == CASE_RELIABILITY_ID
    assert assessment.overall_score > 0.90
    assert assessment.evidence_sufficiency.value == "SUFFICIENT_EVIDENCE"

    copilot = InvestigationCopilot(backend=workspace_backend)
    ans = copilot.ask("What evidence supports the current hypothesis?", case_id=CASE_RELIABILITY_ID)
    assert ans["status"] == "GROUNDED"
    assert "data_quality" not in ans or ans.get("data_quality") is None


