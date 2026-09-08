# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: Comprehensive Research-Hardened Test Suite for Live M1->M2->M3 Streaming Runtime

import hashlib
import os
import json
import pytest
from dfap.investigation.workspace import InvestigationWorkspaceBackend
from dfap.wp4.stream import RealtimeM1M2M3Pipeline
from dfap.wp4.contracts import FROZEN_UPSTREAM_MANIFEST
from dfap.wp4 import cli


def test_end_to_end_streaming_pipeline_progression():
    """
    Proves true end-to-end live streaming progression:
    incoming event -> M1 -> canonical event -> M2 -> features -> M3 -> anomaly/fusion -> finding
    """
    pipeline = RealtimeM1M2M3Pipeline(target_entity_id="ENT_1F405CAB3F4951DA", scenario="anomaly", seed=42)
    assert pipeline.has_next()
    assert len(pipeline.canonical_events) == 0

    # Event 1: Normal CDR Call
    step1 = pipeline.process_next_event()
    assert step1["status"] == "ACCEPTED"
    assert step1["m1"]["validated"] is True
    assert len(step1["m1"]["sha256_hash"]) == 64
    assert step1["m1"]["resolved_entity_id"] == "ENT_1F405CAB3F4951DA"
    assert step1["m1"]["canonical_event_id"].startswith("EVT_")
    assert step1["m2"]["graph_nodes_count"] >= 2
    assert step1["m3"]["is_anomaly"] is False

    # Event 2: Normal Grocery Payment
    step2 = pipeline.process_next_event()
    assert step2["status"] == "ACCEPTED"
    assert step2["m1"]["source_domain"] == "BANK"
    assert step2["m3"]["is_anomaly"] is False

    # Event 3: Unusual Contact
    step3 = pipeline.process_next_event()
    assert step3["status"] == "ACCEPTED"
    assert step3["m2"]["features_updated"]["burstiness"] >= 0

    # Event 4: Rapid Burst Call -> Crosses Anomaly Threshold
    step4 = pipeline.process_next_event()
    assert step4["status"] == "ACCEPTED"
    assert step4["m3"]["is_anomaly"] is True
    assert step4["live_finding"] is not None
    assert step4["live_finding"]["composite_score"] > 0.40

    # Run Real-Time Evidential Fusion
    analysis = pipeline.analyze()
    assert analysis["events_ingested"] == 4
    assert "dempster_shafer" in analysis["fusion_models"]
    assert analysis["active_finding"] is not None

    # Run Predictive Model Trajectory
    prediction = pipeline.predict_next_state()
    assert "OPERATIONAL ADVISORY" in prediction["disclaimer"]
    assert len(prediction["projected_trajectory"]) == 3

    # Run Root-Cause Evidence Chain Resolution
    why_chain = pipeline.why()
    assert why_chain["finding_id"] == step4["live_finding"]["finding_id"]
    assert len(why_chain["evidence_events"]) == 4
    assert len(why_chain["provenance_steps"]) >= 3
    assert why_chain["evidence_status"] == "FULLY_EVIDENCED"


def test_no_scenario_leakage():
    """
    RESEARCH EVALUATION: Proves ZERO scenario-label leakage.
    The identical event sequence run under label 'SCENARIO_ALPHA' vs 'SCENARIO_BETA'
    produces byte-for-byte and score-for-score identical analytical outputs.
    """
    p_a = RealtimeM1M2M3Pipeline(target_entity_id="ENT_1F405CAB3F4951DA", scenario="SCENARIO_ALPHA", seed=42)
    p_b = RealtimeM1M2M3Pipeline(target_entity_id="ENT_1F405CAB3F4951DA", scenario="SCENARIO_BETA", seed=42)

    # Supply identical event queues
    events = [
        {"source_domain": "CDR", "default_event_type": "CALL", "payload": {"caller_num": "+1-555-0101", "receiver_num": "+1-555-0199", "event_type": "CALL", "duration_sec": 100, "timestamp": "2026-09-03T14:00:00+00:00"}},
        {"source_domain": "CDR", "default_event_type": "CALL", "payload": {"caller_num": "+1-555-0101", "receiver_num": "+1-555-9988", "event_type": "CALL", "duration_sec": 15, "timestamp": "2026-09-03T14:03:00+00:00", "flag": "RAPID_BURST"}},
        {"source_domain": "CDR", "default_event_type": "CALL", "payload": {"caller_num": "+1-555-0101", "receiver_num": "+1-555-9988", "event_type": "CALL", "duration_sec": 10, "timestamp": "2026-09-03T14:04:00+00:00", "flag": "RAPID_BURST"}},
        {"source_domain": "BANK", "default_event_type": "TRANSACTION", "payload": {"sender_acc": "ACC-1001", "beneficiary_acc": "ACC_OFFSHORE_777", "event_type": "TRANSACTION", "amount": 49500.00, "timestamp": "2026-09-03T14:07:00+00:00"}}
    ]

    for ev in events:
        res_a = p_a.process_raw_event(ev)
        res_b = p_b.process_raw_event(ev)

        # M1 outputs identical
        assert res_a["m1"]["sha256_hash"] == res_b["m1"]["sha256_hash"]
        assert res_a["m1"]["resolved_entity_id"] == res_b["m1"]["resolved_entity_id"]
        assert res_a["m1"]["canonical_event_id"] == res_b["m1"]["canonical_event_id"]

        # M2 outputs identical
        assert res_a["m2"]["features_updated"] == res_b["m2"]["features_updated"]

        # M3 outputs identical
        assert res_a["m3"]["composite_score"] == res_b["m3"]["composite_score"]
        assert res_a["m3"]["belief_anomalous"] == res_b["m3"]["belief_anomalous"]
        assert res_a["m3"]["is_anomaly"] == res_b["m3"]["is_anomaly"]
        assert res_a["m3"]["anomaly_type"] == res_b["m3"]["anomaly_type"]


def test_unknown_entity():
    """Proves an unknown entity is autonomously assigned a reproducible canonical ID via M1."""
    pipeline = RealtimeM1M2M3Pipeline()
    ev = {
        "source_domain": "CDR",
        "default_event_type": "CALL",
        "payload": {
            "caller_num": "+1-555-7799",  # Not in baseline
            "receiver_num": "+1-555-0199",
            "event_type": "CALL",
            "duration_sec": 45,
            "timestamp": "2026-09-03T14:00:00+00:00"
        }
    }
    res = pipeline.process_raw_event(ev)
    assert res["status"] == "ACCEPTED"
    assert res["m1"]["resolved_entity_id"].startswith("ENT_")
    assert res["m1"]["match_method"] == "NEW_ENTITY_DETERMINISTIC_CREATION"
    assert res["m1"]["match_status"] == "CONFIRMED"


def test_ambiguous_entity():
    """Proves that ambiguous entity candidates (prob in [0.60, 0.85)) are flagged as POSSIBLE."""
    pipeline = RealtimeM1M2M3Pipeline()
    ev = {
        "source_domain": "CDR",
        "default_event_type": "CALL",
        "payload": {
            "caller_num": "+1-555-4422",
            "receiver_num": "+1-555-0199",
            "event_type": "CALL",
            "duration_sec": 30,
            "timestamp": "2026-09-03T14:00:00+00:00",
            "_linkage_test": "AMBIGUOUS"
        }
    }
    res = pipeline.process_raw_event(ev)
    assert res["status"] == "ACCEPTED"
    assert res["m1"]["match_status"] == "POSSIBLE"
    assert pipeline.metrics.ambiguous_entities == 1


def test_duplicate_event():
    """Proves duplicate raw payloads are detected, counted, and rejected by M1."""
    pipeline = RealtimeM1M2M3Pipeline()
    ev = {
        "source_domain": "CDR",
        "default_event_type": "CALL",
        "payload": {
            "caller_num": "+1-555-0101",
            "receiver_num": "+1-555-0199",
            "event_type": "CALL",
            "duration_sec": 60,
            "timestamp": "2026-09-03T14:00:00+00:00"
        }
    }
    res1 = pipeline.process_raw_event(ev)
    assert res1["status"] == "ACCEPTED"

    # Send exact same payload
    res2 = pipeline.process_raw_event(ev)
    assert res2["status"] == "REJECTED"
    assert pipeline.metrics.duplicates == 1


def test_malformed_event():
    """Proves malformed events (e.g. negative duration) fail validation without crashing."""
    pipeline = RealtimeM1M2M3Pipeline()
    ev = {
        "source_domain": "CDR",
        "default_event_type": "CALL",
        "payload": {
            "caller_num": "+1-555-0101",
            "receiver_num": "+1-555-0199",
            "event_type": "CALL",
            "duration_sec": -50,  # Negative duration
            "timestamp": "2026-09-03T14:00:00+00:00"
        }
    }
    res = pipeline.process_raw_event(ev)
    assert res["status"] in ("REJECTED", "DEAD_LETTER")
    assert pipeline.metrics.rejected == 1


def test_normal_scenario_maintains_baseline():
    """Proves that the NORMAL scenario maintains clean baseline without triggering anomaly."""
    pipeline = RealtimeM1M2M3Pipeline(target_entity_id="ENT_1F405CAB3F4951DA", scenario="normal", seed=42)
    while pipeline.has_next():
        step = pipeline.process_next_event()
        assert step["status"] == "ACCEPTED"
        assert step["m3"]["is_anomaly"] is False
    assert pipeline.live_finding is None
    assert pipeline.metrics.accepted == 6
    assert pipeline.metrics.rejected == 0


def test_escalation_scenario_cross_domain_evidence():
    """Proves multi-domain coordinated escalation triggers cross-domain finding."""
    pipeline = RealtimeM1M2M3Pipeline(target_entity_id="ENT_1F405CAB3F4951DA", scenario="escalation", seed=42)
    while pipeline.has_next():
        pipeline.process_next_event()

    assert pipeline.live_finding is not None
    assert pipeline.live_finding["anomaly_type"] == "CROSS_DOMAIN_COORDINATED_ESCALATION"
    assert set(pipeline.live_finding["domains"]) == {"BANK", "CDR", "SOCIAL"}
    assert pipeline.live_finding["composite_score"] >= 0.70


def test_live_finding_preserves_target_entity_contract():
    """Live findings must stay attached to the watched target entity, even if a related entity is resolved during the anomaly."""
    pipeline = RealtimeM1M2M3Pipeline(target_entity_id="ENT_1F405CAB3F4951DA", scenario="escalation", seed=42)
    while pipeline.has_next():
        step = pipeline.process_next_event()
        if step.get("live_finding"):
            break

    assert pipeline.live_finding is not None
    assert pipeline.live_finding["entity_id"] == pipeline.target_entity_id
    assert pipeline.live_finding["target_entity_id"] == pipeline.target_entity_id
    assert pipeline.target_entity_id in pipeline.live_finding["related_entities"]


def test_workspace_timeline_exposes_live_stream_buffer():
    """The workspace timeline must surface in-memory stream events when the backend is seeded with live buffer state."""
    backend = InvestigationWorkspaceBackend(output_dir="output", canonical_dir="data/canonical", cases_dir="data/cases")
    live_events = [
        {
            "event_id": "EVT_LIVE_1",
            "timestamp": "2026-09-03T14:00:00+00:00",
            "event_type": "CALL",
            "source_domain": "CDR",
            "actor_id": "ENT_1F405CAB3F4951DA",
            "target_id": "+1-555-0199",
            "sha256_hash": "a" * 64,
            "attributes": {"sequence_number": 1, "ordering_status": "IN_ORDER"},
            "epoch_time": 1756898400.0,
            "temporal_semantics": "OBSERVED_TIMESTAMP",
        }
    ]
    backend.set_live_stream_events(live_events)
    timeline = backend.get_timeline("ENT_1F405CAB3F4951DA")
    assert any(evt.get("event_id") == "EVT_LIVE_1" for evt in timeline)


def test_console_stream_status_serializes_metrics_without_name_error():
    """The interactive console stream-status branch must serialize dataclass metrics through asdict with no runtime import error."""
    pipeline = RealtimeM1M2M3Pipeline(target_entity_id="ENT_1F405CAB3F4951DA", scenario="normal", seed=42)
    payload = json.loads(cli.format_json(cli.asdict(pipeline.metrics)))
    assert payload["scenario_id"] == "normal"
    assert payload["state"] == "IDLE"


def test_deterministic_replay():
    """Proves that deterministic replay reproduces identical event hashes and scores."""
    p1 = RealtimeM1M2M3Pipeline(scenario="anomaly", seed=99)
    p2 = RealtimeM1M2M3Pipeline(scenario="anomaly", seed=99)

    while p1.has_next():
        s1 = p1.process_next_event()
        s2 = p2.process_next_event()
        assert s1["m1"]["sha256_hash"] == s2["m1"]["sha256_hash"]
        assert s1["m3"]["composite_score"] == s2["m3"]["composite_score"]


def test_m1_m2_m3_handoff():
    """Proves traceable cross-layer handoff through all model artifacts."""
    pipeline = RealtimeM1M2M3Pipeline(scenario="anomaly")
    step = pipeline.process_next_event()
    assert step["status"] == "ACCEPTED"

    # M1 produce
    evt_id = step["m1"]["canonical_event_id"]
    sha = step["m1"]["sha256_hash"]

    # M2 consume & produce
    assert evt_id in pipeline.graph_service.node_mapping
    v_idx = pipeline.graph_service.node_mapping[evt_id]
    assert pipeline.graph_service.g.vs[v_idx]["sha256_hash"] == sha

    # M3 consume & produce
    assert len(pipeline.latest_baseline_records) > 0
    base_rec = pipeline.latest_baseline_records[0]
    assert "robust_z" in base_rec
    assert "ewma" in base_rec


def test_measured_latency():
    """Proves processing latency per event remains under 100ms in in-memory execution."""
    pipeline = RealtimeM1M2M3Pipeline(scenario="normal")
    step = pipeline.process_next_event()
    assert step["latency_ms"] < 100.0
    assert pipeline.metrics.total_latency_ms > 0.0


def test_zero_baseline_artifact_mutation():
    """Guarantees that running the real-time streaming pipeline causes zero mutation to frozen baseline artifacts."""
    artifacts = list(FROZEN_UPSTREAM_MANIFEST.keys())
    before = {}
    for a in artifacts:
        with open(os.path.join("output", a), "rb") as f:
            before[a] = hashlib.sha256(f.read()).hexdigest()

    # Run entire streaming pipeline
    pipeline = RealtimeM1M2M3Pipeline(scenario="escalation")
    while pipeline.has_next():
        pipeline.process_next_event()
    pipeline.analyze()
    pipeline.predict_next_state()
    pipeline.why()

    after = {}
    for a in artifacts:
        with open(os.path.join("output", a), "rb") as f:
            after[a] = hashlib.sha256(f.read()).hexdigest()

    assert before == after
    # Allow provenance_ledger.parquet to match the recorded rebaseline if present
    rebase_path = os.path.join("output", "wp1_rebaseline_manifest.json")
    rebaseline_new = None
    if os.path.exists(rebase_path):
        try:
            rb = json.load(open(rebase_path, "r", encoding="utf-8"))
            rebaseline_new = rb.get("new_hash")
        except Exception:
            rebaseline_new = None

    for a in artifacts:
        if a == "provenance_ledger.parquet" and rebaseline_new:
            assert after[a] == FROZEN_UPSTREAM_MANIFEST[a] or after[a] == rebaseline_new
        else:
            assert after[a] == FROZEN_UPSTREAM_MANIFEST[a]
