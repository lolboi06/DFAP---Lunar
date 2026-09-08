# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: Test 7 — Temporal Causality & Zero Future Leakage Verification

import hashlib
import pytest
import pandas as pd
from typing import Dict, Any, List

from dfap.investigation.workspace import InvestigationWorkspaceBackend
from dfap.investigation.copilot import InvestigationCopilot
from dfap.investigation.evidence_provenance import CanonicalEvidenceRecord, EvidenceStatus
from dfap.investigation.temporal_engine import TemporalEventEngine
from dfap.wp4.cli import handle_m13_command


SYNTHETIC_ENTITY = "ENT_TEMPORAL_CAUSALITY_SYNTHETIC"
TRIGGER_TIMESTAMP_EPOCH = 1700000000.0


def _hash_payload(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


@pytest.fixture
def temporal_fixture():
    """
    Creates the deterministic Test 7 synthetic temporal fixture:
      E1 = T-3 (normal)
      E2 = T-2 (normal)
      E3 = T-1 (suspicious precursor)
      E4 = T   (trigger event)
      E5 = T+1 (highly suspicious subsequent)
      E6 = T+2 (highly suspicious subsequent)
      E7 = T   (equal timestamp event, unsequenced)
    """
    T = TRIGGER_TIMESTAMP_EPOCH
    raw_events = [
        {
            "event_id": "EVT_SYNTH_E1",
            "actor_id": SYNTHETIC_ENTITY,
            "target_id": "RECIPIENT_ALPHA",
            "timestamp": pd.to_datetime(T - 3, unit="s", utc=True).isoformat(),
            "epoch_time": T - 3,
            "amount": 10.0,
            "source_domain": "FINANCIAL",
            "temporal_semantics": "OBSERVED_TIMESTAMP",
            "sha256_hash": _hash_payload("E1"),
            "event_type": "TRANSFER",
            "description": "normal baseline transaction",
        },
        {
            "event_id": "EVT_SYNTH_E2",
            "actor_id": SYNTHETIC_ENTITY,
            "target_id": "RECIPIENT_BETA",
            "timestamp": pd.to_datetime(T - 2, unit="s", utc=True).isoformat(),
            "epoch_time": T - 2,
            "amount": 15.0,
            "source_domain": "FINANCIAL",
            "temporal_semantics": "OBSERVED_TIMESTAMP",
            "sha256_hash": _hash_payload("E2"),
            "event_type": "TRANSFER",
            "description": "normal baseline transaction",
        },
        {
            "event_id": "EVT_SYNTH_E3",
            "actor_id": SYNTHETIC_ENTITY,
            "target_id": "RECIPIENT_GAMMA",
            "timestamp": pd.to_datetime(T - 1, unit="s", utc=True).isoformat(),
            "epoch_time": T - 1,
            "amount": 500.0,
            "source_domain": "FINANCIAL",
            "temporal_semantics": "OBSERVED_TIMESTAMP",
            "sha256_hash": _hash_payload("E3"),
            "event_type": "TRANSFER",
            "description": "suspicious precursor transfer",
        },
        {
            "event_id": "EVT_SYNTH_E4",
            "actor_id": SYNTHETIC_ENTITY,
            "target_id": "RECIPIENT_DELTA",
            "timestamp": pd.to_datetime(T, unit="s", utc=True).isoformat(),
            "epoch_time": T,
            "amount": 100000.0,
            "source_domain": "FINANCIAL",
            "temporal_semantics": "OBSERVED_TIMESTAMP",
            "sha256_hash": _hash_payload("E4"),
            "event_type": "TRANSFER",
            "description": "trigger event: massive anomalous transaction",
        },
        {
            "event_id": "EVT_SYNTH_E5",
            "actor_id": SYNTHETIC_ENTITY,
            "target_id": "RECIPIENT_EPSILON",
            "timestamp": pd.to_datetime(T + 1, unit="s", utc=True).isoformat(),
            "epoch_time": T + 1,
            "amount": 95000.0,
            "source_domain": "FINANCIAL",
            "temporal_semantics": "OBSERVED_TIMESTAMP",
            "sha256_hash": _hash_payload("E5"),
            "event_type": "TRANSFER",
            "description": "subsequent rapid dissipation",
        },
        {
            "event_id": "EVT_SYNTH_E6",
            "actor_id": SYNTHETIC_ENTITY,
            "target_id": "RECIPIENT_ZETA",
            "timestamp": pd.to_datetime(T + 2, unit="s", utc=True).isoformat(),
            "epoch_time": T + 2,
            "amount": 80000.0,
            "source_domain": "FINANCIAL",
            "temporal_semantics": "OBSERVED_TIMESTAMP",
            "sha256_hash": _hash_payload("E6"),
            "event_type": "TRANSFER",
            "description": "subsequent structuring outflow",
        },
        {
            "event_id": "EVT_SYNTH_E7",
            "actor_id": SYNTHETIC_ENTITY,
            "target_id": "RECIPIENT_ETA",
            "timestamp": pd.to_datetime(T, unit="s", utc=True).isoformat(),
            "epoch_time": T,
            "amount": 5.0,
            "source_domain": "FINANCIAL",
            "temporal_semantics": "OBSERVED_TIMESTAMP",
            "sha256_hash": _hash_payload("E7"),
            "event_type": "TRANSFER",
            "description": "equal timestamp event without sequence proof",
            # Note: no sequence_number or pivot_sequence_number
        },
    ]

    backend = InvestigationWorkspaceBackend(
        output_dir="output",
        canonical_dir="data/canonical",
        cases_dir="data/cases"
    )

    # Register synthetic entity in valid_entities and events_df
    backend.valid_entities.add(SYNTHETIC_ENTITY)
    df_synthetic = pd.DataFrame(raw_events)

    if backend.events_df.empty:
        backend.events_df = df_synthetic
    else:
        backend.events_df = pd.concat([backend.events_df, df_synthetic], ignore_index=True)

    # Also register dataset in temporal engine
    backend.temporal_engine.datasets["synthetic_causality"] = df_synthetic

    # Register evidence records in evidence engine
    for r in raw_events:
        ev_id = f"EV_{r['event_id']}"
        rec = CanonicalEvidenceRecord(
            evidence_type="EVENT_OBSERVATION",
            source_domain="FINANCIAL",
            source_id=r["event_id"],
            source_file="synthetic_causality.parquet",
            source_row_index=0,
            canonical_entity_ids=[SYNTHETIC_ENTITY],
            event_ids=[r["event_id"]],
            observation_timestamp=r["epoch_time"],
            ingestion_timestamp="2026-09-05T00:00:00Z",
            derivation_method="SYNTHETIC_FIXTURE",
            evidence_id=ev_id,
            evidence_category="SUPPORTING",
        )
        backend.evidence_engine.register_evidence(rec)
        backend._evidence_by_hash[r["sha256_hash"]] = ev_id

    # Register Finding for E4 (Trigger event)
    finding_id = "FND_SYNTH_TRIGGER_E4"
    backend.findings_by_id[finding_id] = {
        "finding_id": finding_id,
        "entity_id": SYNTHETIC_ENTITY,
        "canonical_entity_id": SYNTHETIC_ENTITY,
        "detector": "M9_ANOMALY_DETECTOR",
        "composite_score": 0.96,
        "anomaly_score": 0.96,
        "confidence": 0.95,
        "status": "ACTIVE",
        "timestamp": T,
        "observation_timestamp": T,
        "temporal_semantics": "OBSERVED_TIMESTAMP",
        "anomaly_reasons": ["Outlier amount exceeding 10x baseline", "High risk transaction"],
        "supporting_evidence": [f"EV_EVT_SYNTH_E4", f"EV_EVT_SYNTH_E3"],
        "contextual_evidence": [f"EV_EVT_SYNTH_E1", f"EV_EVT_SYNTH_E2"],
        "contradicting_evidence": [],
    }
    # Map finding to evidence and register in provenance graph
    backend.evidence_engine.finding_evidence_map[finding_id] = [
        "EV_EVT_SYNTH_E1",
        "EV_EVT_SYNTH_E2",
        "EV_EVT_SYNTH_E3",
        "EV_EVT_SYNTH_E4",
        "EV_EVT_SYNTH_E5",  # Adversarial inclusion: subsequent event attached in raw finding
        "EV_EVT_SYNTH_E6",  # Adversarial inclusion: subsequent event attached in raw finding
    ]
    backend.evidence_engine.graph.add_node(finding_id, node_type="FINDING", domain="FINANCIAL", metadata={"finding_id": finding_id})
    for ev_id in backend.evidence_engine.finding_evidence_map[finding_id]:
        backend.evidence_engine.graph.add_edge(ev_id, finding_id, relation="SUPPORTS", method="RULE_EVALUATION")

    return {
        "backend": backend,
        "copilot": InvestigationCopilot(backend),
        "entity_id": SYNTHETIC_ENTITY,
        "pivot_T": T,
        "finding_id": finding_id,
        "events": {r["event_id"]: r for r in raw_events},
    }


def test_1_history_strictly_enforces_causal_cutoff(temporal_fixture):
    """
    1. history(entity, T)
    Expected:
    - E1/E2/E3 only
    - E4 excluded
    - E5/E6 excluded
    - E7 excluded unless authoritative sequence semantics explicitly place it before T.
    """
    backend = temporal_fixture["backend"]
    ent = temporal_fixture["entity_id"]
    T = temporal_fixture["pivot_T"]

    # Test via workspace history API
    hist_ws = backend.history(ent, pivot=T)
    hist_ws_ids = [e["event_id"] for e in hist_ws]

    assert "EVT_SYNTH_E1" in hist_ws_ids
    assert "EVT_SYNTH_E2" in hist_ws_ids
    assert "EVT_SYNTH_E3" in hist_ws_ids
    assert "EVT_SYNTH_E4" not in hist_ws_ids
    assert "EVT_SYNTH_E5" not in hist_ws_ids
    assert "EVT_SYNTH_E6" not in hist_ws_ids
    assert "EVT_SYNTH_E7" not in hist_ws_ids
    assert len(hist_ws_ids) == 3

    # Test via temporal engine directly
    hist_engine = backend.temporal_engine.history(ent, pivot=T, dataset="synthetic_causality")
    hist_engine_ids = [e["event_id"] for e in hist_engine]

    assert "EVT_SYNTH_E1" in hist_engine_ids
    assert "EVT_SYNTH_E2" in hist_engine_ids
    assert "EVT_SYNTH_E3" in hist_engine_ids
    assert "EVT_SYNTH_E4" not in hist_engine_ids
    assert "EVT_SYNTH_E5" not in hist_engine_ids
    assert "EVT_SYNTH_E6" not in hist_engine_ids
    assert "EVT_SYNTH_E7" not in hist_engine_ids
    assert len(hist_engine_ids) == 3


def test_2_backtrack_contains_only_strictly_prior_events(temporal_fixture):
    """
    2. backtrack(entity, T)
    Expected:
    - only events strictly before T
    - no future event leakage.
    """
    backend = temporal_fixture["backend"]
    ent = temporal_fixture["entity_id"]
    T = temporal_fixture["pivot_T"]

    bt = backend.backtrack(ent, pivot=T)
    preceding_ids = [e["event_id"] for e in bt.get("preceding_events", [])]

    assert "EVT_SYNTH_E1" in preceding_ids
    assert "EVT_SYNTH_E2" in preceding_ids
    assert "EVT_SYNTH_E3" in preceding_ids
    assert "EVT_SYNTH_E4" not in preceding_ids
    assert "EVT_SYNTH_E5" not in preceding_ids
    assert "EVT_SYNTH_E6" not in preceding_ids
    assert "EVT_SYNTH_E7" not in preceding_ids
    for e in bt.get("preceding_events", []):
        assert e["epoch_time"] < T
        assert e.get("history_scope") == "OBSERVED_PAST_HISTORY"


def test_3_forwardtrack_contains_future_events_with_safe_label(temporal_fixture):
    """
    3. forwardtrack(entity, T)
    Expected:
    - E5/E6 are visible as future events
    - labeled OBSERVED_FUTURE_HISTORY or equivalent safe vocabulary
    - never represented as causal history.
    """
    backend = temporal_fixture["backend"]
    ent = temporal_fixture["entity_id"]
    T = temporal_fixture["pivot_T"]

    ft = backend.forwardtrack(ent, pivot=T)
    subsequent_ids = [e["event_id"] for e in ft.get("subsequent_events", [])]

    assert "EVT_SYNTH_E5" in subsequent_ids
    assert "EVT_SYNTH_E6" in subsequent_ids
    assert "EVT_SYNTH_E1" not in subsequent_ids
    assert "EVT_SYNTH_E2" not in subsequent_ids
    assert "EVT_SYNTH_E3" not in subsequent_ids
    assert "EVT_SYNTH_E4" not in subsequent_ids
    assert "EVT_SYNTH_E7" not in subsequent_ids

    for e in ft.get("subsequent_events", []):
        assert e["epoch_time"] > T
        assert e.get("history_scope") == "OBSERVED_FUTURE_HISTORY"


def test_4_anomaly_explanation_omits_future_evidence(temporal_fixture):
    """
    4. Anomaly explanation for E4:
    'Why was the trigger event considered suspicious?'
    Explanation must:
    - use E1, E2, E3 as context if relevant
    - use E4 features/anomaly reasons
    - strictly omit E5 and E6 from explanatory evidence and evidence_refs.
    """
    copilot = temporal_fixture["copilot"]
    fid = temporal_fixture["finding_id"]

    exp = copilot.explain_finding(fid)
    ev_refs = exp.get("evidence_refs", [])

    # E4 and precursors are included if attached
    assert "EV_EVT_SYNTH_E4" in ev_refs or "EV_EVT_SYNTH_E3" in ev_refs or "EV_EVT_SYNTH_E1" in ev_refs

    # CRITICAL: Future evidence (E5, E6) must be strictly omitted from evidence_refs
    assert "EV_EVT_SYNTH_E5" not in ev_refs
    assert "EV_EVT_SYNTH_E6" not in ev_refs

    # Claims must also not cite future evidence
    for claim in exp.get("claims", []):
        claim_evs = claim.get("evidence_ids", [])
        assert "EV_EVT_SYNTH_E5" not in claim_evs
        assert "EV_EVT_SYNTH_E6" not in claim_evs

    # Anomaly reasons / features used
    assert "Outlier amount" in exp.get("answer", "") or "score" in exp.get("answer", "")


def test_5_copilot_query_distinguishes_post_trigger_from_causal_evidence(temporal_fixture):
    """
    5. Copilot query:
    'Would the events after the trigger change why the trigger was suspicious?'
    Copilot must answer:
    - clearly distinguishing post-trigger context from causal evidence
    - post-trigger events do not justify past trigger
    - post-trigger events can show subsequent developments or follow-on activity
    - return evidence_refs that do not cite post-trigger events as justification for the trigger itself.
    """
    copilot = temporal_fixture["copilot"]
    ent = temporal_fixture["entity_id"]
    fid = temporal_fixture["finding_id"]

    query = "Would the events after the trigger change why the trigger was suspicious?"
    resp = copilot.ask(query, entity_id=ent)

    answer_text = resp["answer"].lower()

    # Distinguishes post-trigger context from causal evidence
    assert "post-trigger" in answer_text or "after the trigger" in answer_text
    assert "do not justify" in answer_text or "cannot serve as causal evidence" in answer_text or "cannot justify" in answer_text
    assert "subsequent" in answer_text or "follow-on" in answer_text or "forwardtrack" in answer_text

    # Evidence refs must NOT cite post-trigger events
    for ev in resp.get("evidence_refs", []):
        assert "EVT_SYNTH_E5" not in ev
        assert "EVT_SYNTH_E6" not in ev

    # Claims must also not cite post-trigger events as causal evidence
    for claim in resp.get("claims", []):
        assert "do not justify" in claim.get("claim", "").lower() or "strictly confined" in claim.get("claim", "").lower()


def test_6_equal_timestamp_excluded_without_authoritative_sequence(temporal_fixture):
    """
    6. Equal-timestamp event:
    E7 has timestamp T.
    Expected:
    - excluded from pre-T history unless authoritative sequence number orders it before T.
    - if sequence number missing/equal, do not leak into causal baseline.
    """
    backend = temporal_fixture["backend"]
    ent = temporal_fixture["entity_id"]
    T = temporal_fixture["pivot_T"]

    hist = backend.history(ent, pivot=T)
    event_ids = [e["event_id"] for e in hist]
    assert "EVT_SYNTH_E7" not in event_ids

    # With explicit sequence proof placing an event before pivot sequence
    evt_with_seq = {
        "event_id": "EVT_SYNTH_E7_ORDERED",
        "actor_id": ent,
        "target_id": "RECIPIENT_ETA",
        "timestamp": pd.to_datetime(T, unit="s", utc=True).isoformat(),
        "epoch_time": T,
        "sequence_number": 1,
        "pivot_sequence_number": 2,
        "source_domain": "FINANCIAL",
        "temporal_semantics": "SEQUENCE_ORDER_SURROGATE",
    }
    backend.live_stream_events.append(evt_with_seq)
    hist_ordered = backend.history(ent, pivot=T)
    hist_ordered_ids = [e["event_id"] for e in hist_ordered]
    assert "EVT_SYNTH_E7_ORDERED" in hist_ordered_ids


def test_7_explicit_test_assertions_matrix(temporal_fixture):
    """
    7. Explicit test assertions:
    - assert E1 in history
    - assert E2 in history
    - assert E3 in history
    - assert E4 not in history
    - assert E5 not in history
    - assert E6 not in history
    - assert E7 not in history without sequence proof
    - assert E5 in forwardtrack
    - assert E6 in forwardtrack
    - assert E5 not in explanatory evidence for E4
    - assert E6 not in explanatory evidence for E4
    """
    backend = temporal_fixture["backend"]
    copilot = temporal_fixture["copilot"]
    ent = temporal_fixture["entity_id"]
    T = temporal_fixture["pivot_T"]
    fid = temporal_fixture["finding_id"]

    # History assertions
    hist = backend.history(ent, pivot=T)
    hist_ids = {e["event_id"] for e in hist}
    assert "EVT_SYNTH_E1" in hist_ids
    assert "EVT_SYNTH_E2" in hist_ids
    assert "EVT_SYNTH_E3" in hist_ids
    assert "EVT_SYNTH_E4" not in hist_ids
    assert "EVT_SYNTH_E5" not in hist_ids
    assert "EVT_SYNTH_E6" not in hist_ids
    assert "EVT_SYNTH_E7" not in hist_ids

    # Forwardtrack assertions
    ft = backend.forwardtrack(ent, pivot=T)
    ft_ids = {e["event_id"] for e in ft.get("subsequent_events", [])}
    assert "EVT_SYNTH_E5" in ft_ids
    assert "EVT_SYNTH_E6" in ft_ids

    # Explanatory evidence assertions for E4
    exp = copilot.explain_finding(fid)
    exp_refs = set(exp.get("evidence_refs", []))
    assert "EV_EVT_SYNTH_E5" not in exp_refs
    assert "EV_EVT_SYNTH_E6" not in exp_refs


def test_8_temporal_guard_rejects_future_evidence_injection(temporal_fixture):
    """
    8. Temporal guard:
    Assert that any attempt to include a future event or unsequenced equal-timestamp event
    in a historical evidence set raises ValueError.
    """
    backend = temporal_fixture["backend"]
    T = temporal_fixture["pivot_T"]
    events = temporal_fixture["events"]

    # Valid past evidence passes
    valid_past = [events["EVT_SYNTH_E1"], events["EVT_SYNTH_E2"], events["EVT_SYNTH_E3"]]
    assert backend.validate_historical_evidence_set(valid_past, pivot=T) is True

    # Injection of future event E5 raises ValueError
    with pytest.raises(ValueError) as exc_e5:
        backend.validate_historical_evidence_set(valid_past + [events["EVT_SYNTH_E5"]], pivot=T)
    assert "Future leakage rejected" in str(exc_e5.value)

    # Injection of future event E6 raises ValueError
    with pytest.raises(ValueError) as exc_e6:
        backend.validate_historical_evidence_set([events["EVT_SYNTH_E6"]], pivot=T)
    assert "Future leakage rejected" in str(exc_e6.value)

    # Injection of unsequenced equal-timestamp event E7 raises ValueError
    with pytest.raises(ValueError) as exc_e7:
        backend.validate_historical_evidence_set([events["EVT_SYNTH_E7"]], pivot=T)
    assert "Equal-timestamp leakage rejected" in str(exc_e7.value)


def test_console_m13_smoke_workflow(temporal_fixture):
    """
    Executes a real smoke scenario through the console:
    - history command
    - backtrack command
    - forwardtrack command
    - copilot ask causal question
    """
    backend = temporal_fixture["backend"]
    ent = temporal_fixture["entity_id"]
    T = temporal_fixture["pivot_T"]

    # 1. history command
    out_hist = handle_m13_command(backend, f"history {ent} {T}")
    assert "HISTORY" in out_hist
    assert "EVT_SYNTH_E1" in out_hist
    assert "EVT_SYNTH_E2" in out_hist
    assert "EVT_SYNTH_E3" in out_hist
    assert "EVT_SYNTH_E4" not in out_hist
    assert "EVT_SYNTH_E5" not in out_hist
    assert "EVT_SYNTH_E6" not in out_hist

    # 2. backtrack command
    out_bt = handle_m13_command(backend, f"backtrack {ent} 24h {T}")
    assert "BACKTRACK" in out_bt
    assert "EVT_SYNTH_E1" in out_bt or "EVT_SYNTH_E2" in out_bt or "EVT_SYNTH_E3" in out_bt
    assert "EVT_SYNTH_E4" not in out_bt
    assert "EVT_SYNTH_E5" not in out_bt
    assert "EVT_SYNTH_E6" not in out_bt

    # 3. forwardtrack command
    out_ft = handle_m13_command(backend, f"forwardtrack {ent} 24h {T}")
    assert "FORWARDTRACK" in out_ft
    assert "EVT_SYNTH_E5" in out_ft
    assert "EVT_SYNTH_E6" in out_ft
    assert "OBSERVED_FUTURE_HISTORY" in out_ft
    assert "EVT_SYNTH_E1" not in out_ft

    # 4. copilot ask causal question
    out_ask = handle_m13_command(backend, 'copilot ask "Would the events after the trigger change why the trigger was suspicious?"')
    assert "strict temporal causality" in out_ask.lower() or "do not justify" in out_ask.lower()
    assert "EVT_SYNTH_E5" not in out_ask
    assert "EVT_SYNTH_E6" not in out_ask
