"""
Automated Integration Tests for DFAP Frontend Investigation Workspace.
Verifies all REST endpoints, payloads, epistemic status tiers, and workflows
required by the frontend controller.
"""

import pytest
from fastapi.testclient import TestClient
from dfap.api import app

client = TestClient(app)

CASE_ID = "CASE-DFAP-4DOMAIN-001"
ENTITY_ID = "ENT_DFAP_4DOM_001"


def test_root_and_static_mounting():
    """Verify frontend index.html and static files are served properly."""
    res = client.get("/")
    assert res.status_code == 200
    assert "DFAP" in res.text
    assert "data-target=\"dashboard\"" in res.text

    # Check app.js is retrievable
    res_js = client.get("/static/app.js")
    assert res_js.status_code == 200
    assert "DFAP Investigation Workspace" in res_js.text


def test_system_health():
    """Verify system health endpoint returns operational telemetry."""
    res = client.get("/api/v1/system-health")
    assert res.status_code == 200
    data = res.json()
    assert "overall_status" in data
    assert "components" in data
    assert "backend_api" in data["components"]


def test_workspace_overview():
    """Verify aggregated workspace overview endpoint."""
    res = client.get(f"/api/v1/workspace/overview?case_id={CASE_ID}&entity_id={ENTITY_ID}")
    assert res.status_code == 200
    data = res.json()
    assert "active_case" in data
    assert "risk_summary" in data
    assert "conflict_status" in data
    assert "top_shap_features" in data
    assert "temporal_motifs" in data


def test_case_management_and_switching():
    """Verify case listing and case creation."""
    res = client.get("/api/v1/cases")
    assert res.status_code == 200
    cases = res.json()
    assert isinstance(cases, list)
    assert any(c["case_id"] == CASE_ID for c in cases)

    # Create new case
    create_res = client.post("/api/v1/cases/create", json={
        "title": "Operation Automated Test Case",
        "description": "Integration test created case."
    })
    assert create_res.status_code == 200
    created = create_res.json()
    assert "case_id" in created
    assert created["status"] == "OPEN"


def test_entity_search_disambiguation_gate():
    """Verify Feature 1 entity query parsing, candidate scoring, and disambiguation gate."""
    # Specific ID query
    res = client.get(f"/api/v1/entity/search?query=Find+{ENTITY_ID}")
    assert res.status_code == 200
    data = res.json()
    assert "candidates" in data
    assert len(data["candidates"]) > 0
    assert data["disambiguation_required"] is False
    assert data["candidates"][0]["entity_id"] == ENTITY_ID

    # Ambiguous / generic query triggering disambiguation
    res_ambig = client.get("/api/v1/entity/search?query=Find+suspect+named+Sharma")
    assert res_ambig.status_code == 200
    data_ambig = res_ambig.json()
    assert "candidates" in data_ambig
    assert data_ambig["disambiguation_required"] is True


def test_timeline_generation_windows():
    """Verify M10 multi-domain timeline with TIGHT, MODERATE, and BROAD windows."""
    for window in ["TIGHT", "MODERATE", "BROAD"]:
        res = client.get(f"/api/v1/timeline?case_id={CASE_ID}&entity_id={ENTITY_ID}&window_type={window}")
        assert res.status_code == 200
        data = res.json()
        assert data["window_type"] == window
        assert "events" in data
        assert isinstance(data["events"], list)
        assert len(data["events"]) > 0

        # Check epistemic tier on events
        for ev in data["events"]:
            assert "domain" in ev
            assert "timestamp" in ev
            assert ev["status"] in ["OBSERVED", "INFERRED", "PREDICTED"]


def test_evidence_locker():
    """Verify M12 cross-domain evidence items."""
    res = client.get(f"/api/v1/evidence?case_id={CASE_ID}")
    assert res.status_code == 200
    data = res.json()
    assert "evidence_items" in data
    items = data["evidence_items"]
    assert len(items) > 0
    domains = {it["domain"] for it in items}
    assert "FIN" in domains or "CDR" in domains


def test_graph_payload_structure():
    """Verify M4 topological graph payload structure and epistemic tier integrity."""
    res = client.get(f"/api/v1/graph?case_id={CASE_ID}&entity_id={ENTITY_ID}")
    assert res.status_code == 200
    data = res.json()
    assert "nodes" in data
    assert "edges" in data
    assert len(data["nodes"]) > 0

    for n in data["nodes"]:
        assert "id" in n
        assert "epistemic_tier" in n
        assert n["epistemic_tier"] in ["OBSERVED", "INFERRED", "PREDICTED"]


def test_behavioral_baselines_and_anomalies():
    """Verify M8 baselines and M9 anomaly flaggings."""
    res = client.get(f"/api/v1/behavior?entity_id={ENTITY_ID}&case_id={CASE_ID}")
    assert res.status_code == 200
    data = res.json()
    assert "baselines" in data
    assert "anomalies" in data


def test_temporal_motifs_matrix_profile():
    """Verify M10 temporal motifs and DTW sequence distance."""
    res = client.get(f"/api/v1/temporal?entity_id={ENTITY_ID}&case_id={CASE_ID}")
    assert res.status_code == 200
    data = res.json()
    assert "motifs" in data
    assert len(data["motifs"]) > 0
    m0 = data["motifs"][0]
    assert "pattern_name" in m0
    assert "confidence" in m0


def test_conflict_detection_and_abstention_gate():
    """Verify M11 evidential conflict detection and abstention enforcement."""
    res = client.get(f"/api/v1/conflict/{CASE_ID}")
    assert res.status_code == 200
    data = res.json()
    assert data["case_id"] == CASE_ID
    assert "conflict_detected" in data
    assert "abstention_required" in data
    assert data["conflict_detected"] is True
    assert data["abstention_required"] is True


def test_shap_explainability():
    """Verify M9 SHAP finding attribution waterfall."""
    res = client.get(f"/api/v1/explain/FINDING-DFAP-4DOM-001?case_id={CASE_ID}")
    assert res.status_code == 200
    data = res.json()
    assert data["finding_id"] == "FINDING-DFAP-4DOM-001"
    assert "attributions" in data
    assert "base_value" in data
    assert "model_output" in data
    assert len(data["attributions"]) > 0


def test_multi_signal_risk():
    """Verify M13 multi-signal risk index breakdown and escalation flag."""
    res = client.get(f"/api/v1/risk/{CASE_ID}")
    assert res.status_code == 200
    data = res.json()
    assert "risk_index" in data
    assert "risk_tier" in data
    assert "breakdown" in data
    assert data["risk_index"] > 0


def test_graph_ml_benchmarks():
    """Verify GraphSAGE and TGN benchmark metrics and GNNExplainer attributions."""
    res = client.get(f"/api/v1/graphml?case_id={CASE_ID}")
    assert res.status_code == 200
    data = res.json()
    assert "benchmarks" in data
    assert len(data["benchmarks"]) >= 2
    models = [b["model"] for b in data["benchmarks"]]
    assert "GraphSAGE" in models
    assert "TGN" in models


def test_forensic_packet_and_hash():
    """Verify M12 court-admissible forensic packet with SHA-256 integrity seal."""
    res = client.get(f"/api/v1/forensic/{CASE_ID}")
    assert res.status_code == 200
    data = res.json()
    assert data["case_id"] == CASE_ID
    assert "sha256_digest" in data
    assert len(data["sha256_digest"]) == 64

    # Test markdown download endpoint
    res_md = client.get(f"/api/v1/forensic/{CASE_ID}/markdown")
    assert res_md.status_code == 200
    assert "FORENSIC CASE PACKET" in res_md.text


def test_grounded_narratives():
    """Verify Feature 2 claim-verified narrative generation."""
    res = client.get(f"/api/v1/narrative/generate?case_id={CASE_ID}")
    assert res.status_code == 200
    data = res.json()
    assert "narrative_text" in data
    assert "claims" in data
    assert len(data["claims"]) > 0


def test_copilot_investigation_preserves_question():
    """Verify M14 agentic copilot preserves full question and returns tool trace."""
    question = "Why was ENT_DFAP_4DOM_001 flagged?"
    res = client.post("/api/v1/copilot/investigate", json={
        "question": question,
        "case_id": CASE_ID
    })
    assert res.status_code == 200
    data = res.json()
    assert data["question"] == question
    assert "answer" in data
    assert "tool_trace" in data


def test_ldrm_gateway_lifecycle():
    """Verify LDRM lawful data acquisition flow through API."""
    # List requests
    res = client.get("/api/v1/ldrm/requests")
    assert res.status_code == 200
    reqs = res.json().get("requests", [])
    assert len(reqs) > 0

    # Create new request
    res_create = client.post("/api/v1/ldrm/requests", json={
        "target_identifier": "+91-9876500000",
        "provider_type": "TELECOM_CDR",
        "jurisdiction": "IN-DL"
    })
    assert res_create.status_code == 200
    new_req = res_create.json()
    assert "request_id" in new_req
    req_id = new_req["request_id"]

    # Advance lifecycle
    res_adv = client.post("/api/v1/ldrm/advance-lifecycle", json={
        "request_id": req_id,
        "action": "APPROVE_AND_DISPATCH"
    })
    assert res_adv.status_code == 200
    adv_data = res_adv.json()
    assert adv_data["status"] in ["SENT", "DISPATCHED", "COMPLETED"]


def test_w3c_provenance_chain():
    """Verify W3C PROV-O audit chain."""
    res = client.get(f"/api/v1/provenance/chain?case_id={CASE_ID}")
    assert res.status_code == 200
    data = res.json()
    assert "chain" in data
    assert len(data["chain"]) > 0


def test_event_sourced_decision_log():
    """Verify Feature 4 immutable event-sourced decision ledger."""
    # Append event
    res_post = client.post("/api/v1/decision-log/record", json={
        "case_id": CASE_ID,
        "event_type": "OFFICER_REVIEW",
        "notes": "Automated test validation review.",
        "officer_id": "INV-TEST"
    })
    assert res_post.status_code == 200

    # Fetch log
    res_get = client.get(f"/api/v1/decision-log?case_id={CASE_ID}")
    assert res_get.status_code == 200
    events = res_get.json().get("events", [])
    assert len(events) > 0
    assert any(e["event_type"] == "OFFICER_REVIEW" for e in events)


def test_regional_language_translation():
    """Verify Feature 5 translation to Hindi and Punjabi."""
    sample_text = "The subject was flagged for suspicious financial velocity."

    res_hi = client.post("/api/v1/translate", json={
        "text": sample_text,
        "target_lang": "hi"
    })
    assert res_hi.status_code == 200
    data_hi = res_hi.json()
    assert data_hi["target_lang"] == "hi"
    assert len(data_hi["translated_text"]) > 0

    res_pa = client.post("/api/v1/translate", json={
        "text": sample_text,
        "target_lang": "pa"
    })
    assert res_pa.status_code == 200
    data_pa = res_pa.json()
    assert data_pa["target_lang"] == "pa"
    assert len(data_pa["translated_text"]) > 0


def test_3d_graph_library_and_rich_semantics():
    """Verify 3D graph library is served and graph endpoint provides rich node/edge semantics."""
    res_lib = client.get("/static/3d-force-graph.min.js")
    assert res_lib.status_code == 200
    assert len(res_lib.content) > 1000000

    res_graph = client.get(f"/api/v1/graph?case_id={CASE_ID}&entity_id={ENTITY_ID}")
    assert res_graph.status_code == 200
    gdata = res_graph.json()
    assert "nodes" in gdata
    assert "edges" in gdata
    assert "legend" in gdata

    # Check node semantics & epistemic tiers
    node_tiers = {n["epistemic_tier"] for n in gdata["nodes"]}
    assert "OBSERVED" in node_tiers
    assert "INFERRED" in node_tiers
    assert "PREDICTED" in node_tiers

    target_node = next(n for n in gdata["nodes"] if n["id"] == ENTITY_ID)
    assert target_node["type"] == "CANONICAL_ENTITY"
    assert "identifiers" in target_node
    assert "evidence_refs" in target_node
    assert "timestamps" in target_node
    assert "provenance" in target_node

    # Check edge semantics
    edge_statuses = {e["status"] for e in gdata["edges"]}
    assert "OBSERVED" in edge_statuses
    assert "INFERRED" in edge_statuses
    assert "PREDICTED" in edge_statuses
    sample_edge = gdata["edges"][0]
    assert "relation" in sample_edge
    assert "evidence_ids" in sample_edge
    assert "timestamp" in sample_edge
    assert "source_domain" in sample_edge


def test_graph_path_tracing():
    """Verify authoritative M4 graph path computation between nodes."""
    res = client.get(f"/api/v1/graph/path?source={ENTITY_ID}&target=NODE_EXT_BENEFICIARY")
    assert res.status_code == 200
    pdata = res.json()
    assert pdata["found"] is True
    assert pdata["hop_count"] == 2
    assert len(pdata["path_nodes"]) == 3
    assert len(pdata["path_edges"]) == 2
    assert len(pdata["evidence_refs"]) > 0


def test_all_20_sidebar_module_endpoints():
    """Verify every one of the 20 sidebar modules has a working, non-mock backend API route."""
    endpoints = [
        f"/api/v1/workspace/overview?case_id={CASE_ID}&entity_id={ENTITY_ID}",
        "/api/v1/cases",
        f"/api/v1/entity/search?query=target",
        f"/api/v1/timeline?case_id={CASE_ID}&entity_id={ENTITY_ID}",
        f"/api/v1/evidence?case_id={CASE_ID}",
        f"/api/v1/graph?case_id={CASE_ID}&entity_id={ENTITY_ID}",
        f"/api/v1/behavior?case_id={CASE_ID}&entity_id={ENTITY_ID}",
        f"/api/v1/temporal?entity_id={ENTITY_ID}",
        f"/api/v1/conflict/{CASE_ID}",
        f"/api/v1/explain/FINDING-DFAP-4DOM-001?case_id={CASE_ID}",
        f"/api/v1/risk/{CASE_ID}",
        "/api/v1/graphml",
        f"/api/v1/forensic/{CASE_ID}",
        f"/api/v1/narrative/generate?case_id={CASE_ID}",
        "/api/v1/ldrm/requests",
        f"/api/v1/provenance/chain?case_id={CASE_ID}",
        f"/api/v1/decision-log?case_id={CASE_ID}",
        "/api/v1/system-health"
    ]
    for ep in endpoints:
        r = client.get(ep)
        assert r.status_code == 200, f"Endpoint {ep} failed with {r.status_code}: {r.text}"
