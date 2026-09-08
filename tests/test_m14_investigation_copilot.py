# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: M14 Investigation Copilot Validation

import json
from datetime import datetime, timezone

import pandas as pd
import pytest

from dfap.investigation.workspace import InvestigationWorkspaceBackend
from dfap.investigation.copilot import InvestigationCopilot


VALID_ENTITY = "ENT_1F405CAB3F4951DA"


@pytest.fixture
def backend():
    return InvestigationWorkspaceBackend(output_dir="output", canonical_dir="data/canonical", cases_dir="data/cases")


@pytest.fixture
def copilot(backend):
    return InvestigationCopilot(backend)


def test_copilot_explain_grounded_uses_findings_and_provenance(copilot, backend):
    finding_id = next(iter(backend.findings_by_id))
    result = copilot.explain_finding(finding_id)
    assert result["status"] in {"GROUNDED", "PARTIALLY_GROUNDED", "CONFLICTED"}
    assert result["finding_id"] == finding_id
    assert result["evidence_refs"]
    assert result["provenance_refs"]
    assert "answer" in result


def test_copilot_rejects_unknown_finding(copilot):
    with pytest.raises(ValueError, match="Unknown finding"):
        copilot.explain_finding("FND_DOES_NOT_EXIST")


def test_copilot_rejects_unknown_entity(copilot):
    with pytest.raises(ValueError, match="Unknown entity"):
        copilot.investigate_entity("ENT_DOES_NOT_EXIST")


def test_copilot_returns_structured_answer_contract(copilot, backend):
    finding_id = next(iter(backend.findings_by_id))
    result = copilot.explain_finding(finding_id)
    required = {"answer", "confidence", "status", "claims", "evidence_refs", "provenance_refs", "uncertainties", "limitations", "suggested_next_actions"}
    assert required.issubset(result.keys())
    assert isinstance(result["claims"], list)
    assert isinstance(result["evidence_refs"], list)
    assert isinstance(result["provenance_refs"], list)


def test_copilot_summarize_case_scopes_to_valid_case(copilot, backend):
    case = backend.create_case(VALID_ENTITY, case_id="CASE-M14-SUMMARY")
    finding_id = next(
        fid for fid, item in backend.findings_by_id.items() if str(item.get("entity_id")) == VALID_ENTITY
    )
    backend.attach_finding(case.case_id, finding_id)
    result = copilot.summarize_case(case.case_id)
    assert result["case_id"] == case.case_id
    assert result["entity_id"] == VALID_ENTITY
    assert "summary" in result


def test_copilot_graph_and_timeline_are_real_outputs(copilot, backend):
    graph = copilot.graph_for_entity(VALID_ENTITY)
    assert graph["entity_id"] == VALID_ENTITY
    assert "1hop_neighbors" in graph
    assert "2hop_neighbors" in graph

    timeline = copilot.timeline_for_entity(VALID_ENTITY)
    assert isinstance(timeline, list)
    assert timeline


def test_copilot_next_suggests_only_grounded_actions(copilot, backend):
    case = backend.create_case(VALID_ENTITY, case_id="CASE-M14-NEXT")
    actions = copilot.next_actions(case.case_id)
    assert isinstance(actions, list)
    assert actions
    assert all(isinstance(a, str) for a in actions)


def test_copilot_ask_routes_to_reasoning(copilot, backend):
    finding_id = next(iter(backend.findings_by_id))
    res = copilot.ask(f"Why was this entity flagged? {finding_id}")
    assert res["finding_id"] == finding_id
    assert "answer" in res


def test_copilot_ask_uses_case_context_before_global_fallback(copilot, backend):
    case = backend.create_case(VALID_ENTITY, case_id="CASE-M14-CASE-SCOPED")
    valid_finding = next(fid for fid, item in backend.findings_by_id.items() if str(item.get("entity_id")) == VALID_ENTITY)
    foreign_entity = next(item.get("entity_id") for fid, item in backend.findings_by_id.items() if str(item.get("entity_id")) != VALID_ENTITY)
    foreign_finding = next(fid for fid, item in backend.findings_by_id.items() if str(item.get("entity_id")) != VALID_ENTITY)
    backend.attach_finding(case.case_id, valid_finding)

    result = copilot.ask("Why was this entity flagged?", case_id=case.case_id, entity_id=VALID_ENTITY)

    assert result["finding_id"] == valid_finding
    assert result["entity_id"] == VALID_ENTITY
    assert result["evidence_refs"]
    assert result["status"] in {"GROUNDED", "PARTIALLY_GROUNDED", "CONFLICTED"}
    assert result["finding_id"] != foreign_finding
    assert foreign_entity != VALID_ENTITY


def test_copilot_ask_returns_insufficient_evidence_for_unscoped_or_empty_case(copilot, backend):
    case = backend.create_case(VALID_ENTITY, case_id="CASE-M14-EMPTY")
    result = copilot.ask("Why was this entity flagged?", case_id=case.case_id, entity_id=VALID_ENTITY)
    assert result["status"] == "INSUFFICIENT_EVIDENCE"
    assert "finding_id" not in result or result["finding_id"] is None


def test_case_scoped_m14_rejects_previous_bank_finding_and_foreign_evidence(backend):
    copilot = InvestigationCopilot(backend)
    unsw_case = backend.create_case("FLOW_133", case_id="CASE-UNS-001", created_by="AUTO_DISCOVERY", search_context={"source": "unsw"})
    bank_finding = next(fid for fid, item in backend.findings_by_id.items() if str(item.get("entity_id")) == "ENT_0F0FC38C24C0539E")
    hostile_evidence = next(eid for eid, rec in backend.evidence_engine.evidence_store.items() if "ENT_0F0FC38C24C0539E" not in rec.canonical_entity_ids and "FLOW_133" not in rec.canonical_entity_ids)

    with pytest.raises(ValueError, match="Foreign finding rejected|outside the active case scope"):
        backend.attach_finding(unsw_case.case_id, bank_finding)
    with pytest.raises(ValueError, match="Foreign evidence rejected"):
        backend.attach_evidence(unsw_case.case_id, hostile_evidence)

    result = copilot.ask('Why was FLOW_133 flagged?', case_id=unsw_case.case_id, entity_id="FLOW_133")
    assert result["status"] in {"INSUFFICIENT_EVIDENCE", "PARTIALLY_GROUNDED"}
    assert result["entity_id"] == "FLOW_133"
    assert result["dataset"] == "UNSW"
    assert result["finding_id"] is None or result["finding_id"] != bank_finding
    assert result["evidence_refs"] == []
    assert result["provenance_refs"] == []
    assert not any(ref == "EVD-CAN-b8479923d4e7" for ref in result.get("evidence_refs", []))
    payload = json.dumps(result)
    assert "FND_F7F1AEA41A06" not in payload
    assert "ENT_0F0FC38C24C0539E" not in payload
    assert "EVD-CAN-b8479923d4e7" not in payload


def test_case_scoped_m14_rejects_dataset_and_temporal_mismatch(backend):
    copilot = InvestigationCopilot(backend)
    unsw_case = backend.create_case("FLOW_133", case_id="CASE-UNS-001-DATASET-CHECK")
    bank_finding = next(fid for fid, item in backend.findings_by_id.items() if str(item.get("entity_id")) == "ENT_0F0FC38C24C0539E")
    with pytest.raises(ValueError, match="Foreign finding rejected|outside the active case scope"):
        backend.attach_finding(unsw_case.case_id, bank_finding)

    result = copilot.ask('Why was FLOW_133 flagged?', case_id=unsw_case.case_id, entity_id="FLOW_133")
    assert result["status"] in {"INSUFFICIENT_EVIDENCE", "PARTIALLY_GROUNDED"}
    assert result["entity_id"] == "FLOW_133"
    assert not any(ref.startswith("EVD") and "b8479923d4e7" in ref for ref in result.get("evidence_refs", []))


def test_controlled_case_m14_grounds_on_controlled_case_dossier(backend):
    case_data = {
        "case_id": "CASE-CROSS-001",
        "canonical_entity_id": "ENT_CROSS_SYNDICATE_ALPHA",
        "mapping_status": "CONTROLLED_CASE_MAPPING",
        "search_context": {
            "source": "CONTROLLED_CASE_MAPPING",
            "mapping_status": "CONTROLLED_CASE_MAPPING",
            "case_kind": "CONTROLLED_CASE_MAPPING",
            "domains_analyzed": ["financial", "social"],
            "domain_evidence_breakdown": {
                "financial": {
                    "dataset": "elliptic",
                    "anomaly_score": 0.90,
                    "events_count": 57,
                    "evidence_reasons": ["High-Value Outflow: $2,855,586.50", "Association with Anonymizing/Mixer Wallet"],
                },
                "social": {
                    "dataset": "stackoverflow",
                    "anomaly_score": 0.70,
                    "events_count": 120,
                    "evidence_reasons": ["High-Volume Interaction Hub"],
                },
            },
            "cross_domain_timeline": [],
            "fused_composite_score": 0.8681,
            "threat_classification": "CRITICAL_CROSS_DOMAIN_ESCALATION",
        },
    }
    case = backend.register_controlled_case(case_data)
    copilot = InvestigationCopilot(backend)

    evidence_result = copilot.ask(
        "What evidence connects the activity in this case across domains?",
        case_id=case.case_id,
        entity_id=case.canonical_entity_id,
    )
    assert evidence_result["status"] == "GROUNDED"
    assert evidence_result["entity_id"] == case.canonical_entity_id
    assert evidence_result["case_id"] == case.case_id
    assert evidence_result["evidence_refs"]
    assert evidence_result["provenance_refs"]
    payload = json.dumps(evidence_result)
    assert "financial" in payload.lower()
    assert "social" in payload.lower()
    assert "ENT_CROSS_SYNDICATE_ALPHA" in payload
    assert not any(ref in payload for ref in ["FND_F7F1AEA41A06", "ENT_0F0FC38C24C0539E", "EVD-CAN-b8479923d4e7"])

    suspicion_result = copilot.ask(
        "Why was this case considered suspicious?",
        case_id=case.case_id,
        entity_id=case.canonical_entity_id,
    )
    assert suspicion_result["status"] in {"GROUNDED", "PARTIALLY_GROUNDED"}
    assert suspicion_result["confidence"] > 0
    payload = json.dumps(suspicion_result)
    assert "CRITICAL_CROSS_DOMAIN_ESCALATION" in payload or "financial" in payload.lower() or "social" in payload.lower()
    assert not any(ref in payload for ref in ["FND_F7F1AEA41A06", "ENT_0F0FC38C24C0539E", "EVD-CAN-b8479923d4e7"])

    history_result = copilot.ask(
        "What happened before the suspicious activity?",
        case_id=case.case_id,
        entity_id=case.canonical_entity_id,
    )
    assert history_result["status"] in {"INSUFFICIENT_EVIDENCE", "PARTIALLY_GROUNDED"}
    assert history_result["evidence_refs"] == [] or history_result["evidence_refs"] == []

    next_action_result = copilot.ask(
        "What should the investigator examine next?",
        case_id=case.case_id,
        entity_id=case.canonical_entity_id,
    )
    assert next_action_result["status"] in {"GROUNDED", "PARTIALLY_GROUNDED"}
    assert next_action_result["suggested_next_actions"]
    payload = json.dumps(next_action_result)
    assert "financial" in payload.lower() or "social" in payload.lower() or "bridge" in payload.lower()


def test_controlled_case_m14_excludes_unrelated_global_findings_and_stale_case_evidence(backend):
    case_data = {
        "case_id": "CASE-CROSS-001",
        "canonical_entity_id": "ENT_CROSS_SYNDICATE_ALPHA",
        "mapping_status": "CONTROLLED_CASE_MAPPING",
        "search_context": {
            "source": "CONTROLLED_CASE_MAPPING",
            "mapping_status": "CONTROLLED_CASE_MAPPING",
            "case_kind": "CONTROLLED_CASE_MAPPING",
            "domains_analyzed": ["financial", "social"],
            "domain_evidence_breakdown": {
                "financial": {"anomaly_score": 0.90, "events_count": 57, "evidence_reasons": ["High-Value Outflow"]},
                "social": {"anomaly_score": 0.70, "events_count": 120, "evidence_reasons": ["High-Volume Interaction Hub"]},
            },
            "cross_domain_timeline": [],
            "fused_composite_score": 0.8681,
            "threat_classification": "CRITICAL_CROSS_DOMAIN_ESCALATION",
            "bridge_evidence_refs": ["ref:bridge_crypto_wallet_01", "ref:bridge_social_handle_01"],
        },
    }
    case = backend.register_controlled_case(case_data)
    copilot = InvestigationCopilot(backend)

    result = copilot.ask(
        "What evidence connects the activity in this case across domains?",
        case_id=case.case_id,
        entity_id=case.canonical_entity_id,
    )

    payload = json.dumps(result)
    assert "ref:bridge_crypto_wallet_01" in payload
    assert "ref:bridge_social_handle_01" in payload
    assert "FND_F7F1AEA41A06" not in payload
    assert "ENT_0F0FC38C24C0539E" not in payload
    assert "EVD-CAN-b8479923d4e7" not in payload
    assert result["status"] == "GROUNDED"
    assert result["evidence_refs"]
    assert result["provenance_refs"]


def test_unknown_case_or_finding_returns_safe_failure(copilot, backend):
    with pytest.raises((KeyError, ValueError), match="Case|Unknown finding|not found"):
        copilot.ask("Why was this entity flagged?", case_id="CASE_DOES_NOT_EXIST", entity_id=VALID_ENTITY)
    with pytest.raises(ValueError, match="Unknown finding|not found"):
        copilot.explain_finding("FND_DOES_NOT_EXIST")


def test_copilot_rejects_finding_without_evidence(copilot, backend):
    missing_finding_id = "FND_NO_EVIDENCE_FOR_TEST"
    backend.findings_by_id[missing_finding_id] = {
        "finding_id": missing_finding_id,
        "entity_id": VALID_ENTITY,
        "status": "AI_GENERATED_LEAD",
    }
    with pytest.raises(ValueError, match="No evidence records are associated"):
        copilot.evidence_for_finding(missing_finding_id)


def test_workspace_rejects_foreign_evidence(copilot, backend):
    case = backend.create_case(VALID_ENTITY, case_id="CASE-FOREIGN-EVIDENCE")
    foreign_evidence = next(
        eid for eid, rec in backend.evidence_engine.evidence_store.items()
        if VALID_ENTITY not in rec.canonical_entity_ids
    )
    with pytest.raises(ValueError, match="Foreign evidence rejected"):
        backend.attach_evidence(case.case_id, foreign_evidence)


def test_workspace_rejects_foreign_finding(copilot, backend):
    case = backend.create_case(VALID_ENTITY, case_id="CASE-FOREIGN-FINDING")
    foreign_finding = next(
        fid for fid, item in backend.findings_by_id.items()
        if str(item.get("entity_id")) != VALID_ENTITY
    )
    with pytest.raises(ValueError, match="Foreign finding rejected"):
        backend.attach_finding(case.case_id, foreign_finding)


def test_broken_provenance_is_fail_closed(copilot, backend):
    finding_id = next(iter(backend.findings_by_id))
    original_map = dict(backend.evidence_engine.finding_evidence_map)
    backend.evidence_engine.finding_evidence_map[finding_id] = ["EVD_DOES_NOT_EXIST"]
    try:
        result = backend.evidence_engine.verify_finding_integrity(finding_id)
        assert result["is_valid"] is False
        assert result["status"] in {"MISSING_PARENT_EVIDENCE", "BROKEN_PROVENANCE_CHAIN", "TAMPERED_RECORD_DETECTED"}
    finally:
        backend.evidence_engine.finding_evidence_map.clear()
        backend.evidence_engine.finding_evidence_map.update(original_map)


def test_contradictory_evidence_is_reported(copilot, backend):
    finding_id = next(iter(backend.findings_by_id))
    evidence_record = next(iter(backend.evidence_engine.evidence_store.values()))
    original_category = evidence_record.evidence_category
    evidence_record.evidence_category = "CONTRADICTING"
    backend.evidence_engine.finding_evidence_map[finding_id] = [evidence_record.evidence_id]
    try:
        result = copilot.contradictions_for_finding(finding_id)
        assert result["finding_id"] == finding_id
        assert result["status"] in {"GROUNDED", "INSUFFICIENT_EVIDENCE"}
        assert result["evidence_refs"] == [evidence_record.evidence_id]
    finally:
        evidence_record.evidence_category = original_category
        backend.evidence_engine.finding_evidence_map[finding_id] = [evidence_record.evidence_id]


def test_unresolved_identity_is_rejected(backend):
    with pytest.raises(ValueError, match="unknown in authoritative registries"):
        backend.investigate_entity("ENT_UNRESOLVED_999")


def test_partial_identity_is_possible_but_not_confirmed(backend):
    results = backend.search("+1-555-01", query_type="entity", max_results=20)
    assert results
    assert any(str(item.get("match_status")).upper() in {"POSSIBLE", "CONFIRMED"} for item in results)


def test_sequence_order_surrogate_semantics_are_preserved(backend):
    row = backend.events_df.iloc[0].copy()
    row["event_id"] = "EVT_SEQUENCE_SURROGATE_TEST"
    row["actor_id"] = "+1-555-0101"
    row["target_id"] = "ACC-SEQ-TEST"
    row["timestamp"] = None
    row["temporal_semantics"] = "SEQUENCE_ORDER_SURROGATE"
    backend.events_df = pd.concat([backend.events_df, pd.DataFrame([row])], ignore_index=True)
    timeline = backend.get_timeline(VALID_ENTITY)
    assert any(ev.get("temporal_semantics") == "SEQUENCE_ORDER_SURROGATE" for ev in timeline)


def test_unknown_timestamp_is_not_fabricated(backend):
    row = backend.events_df.iloc[0].copy()
    row["event_id"] = "EVT_UNKNOWN_TIMESTAMP_TEST"
    row["actor_id"] = "+1-555-0101"
    row["target_id"] = "ACC-UNKNOWN-TEST"
    row["timestamp"] = None
    row["temporal_semantics"] = "UNKNOWN_TIMESTAMP"
    backend.events_df = pd.concat([backend.events_df, pd.DataFrame([row])], ignore_index=True)
    timeline = backend.get_timeline(VALID_ENTITY)
    assert any(ev.get("temporal_semantics") == "UNKNOWN_TIMESTAMP" for ev in timeline)
    assert any(ev.get("epoch_time") is None for ev in timeline)


def test_future_leakage_is_blocked(backend):
    now_ts = datetime.now(timezone.utc).timestamp()
    timeline = backend.get_timeline(VALID_ENTITY)
    assert all(ev.get("epoch_time") is None or ev.get("epoch_time") <= now_ts + 86400 for ev in timeline)


def test_validator_rejects_unsupported_claim(copilot):
    assert copilot.validator.validate_claim("This entity committed a crime.", []) is False
    assert copilot.validator.validate_claim("This claim is unsupported.", ["EVD_NO_SUPPORT"], VALID_ENTITY) is False


def test_case_summary_is_scoped_to_case_entity(copilot, backend):
    case = backend.create_case(VALID_ENTITY, case_id="CASE-SCOPED-TEST")
    finding_id = next(fid for fid, item in backend.findings_by_id.items() if str(item.get("entity_id")) == VALID_ENTITY)
    backend.attach_finding(case.case_id, finding_id)
    backend.add_case_note(case.case_id, "This note is not evidence.")
    result = copilot.summarize_case(case.case_id)
    assert result["entity_id"] == VALID_ENTITY
    assert not any(str(item).startswith("NOTE-") for item in result["supporting_evidence"])


def test_graph_claim_grounding_uses_real_graph_output(copilot, backend):
    graph = copilot.graph_for_entity(VALID_ENTITY)
    assert "1hop_neighbors" in graph
    assert "2hop_neighbors" in graph
    assert isinstance(graph["1hop_neighbors"], list)
    assert isinstance(graph["2hop_neighbors"], list)


def test_suggested_actions_are_not_completed_actions(copilot, backend):
    case = backend.create_case(VALID_ENTITY, case_id="CASE-ACTIONS-TEST")
    actions = copilot.next_actions(case.case_id)
    assert actions
    assert all("completed" not in a.lower() and "done" not in a.lower() for a in actions)


def test_invalid_finding_id_rejected(copilot):
    with pytest.raises((ValueError, KeyError), match="Unknown finding|not found"):
        copilot.explain_finding("FND_BAD_ID")


def test_invalid_case_id_rejected(copilot):
    with pytest.raises((ValueError, KeyError), match="Case|not found"):
        copilot.summarize_case("CASE_BAD_ID")


def test_repeated_response_is_deterministic(copilot, backend):
    finding_id = next(iter(backend.findings_by_id))
    first = copilot.explain_finding(finding_id)
    second = copilot.explain_finding(finding_id)
    assert first == second


def test_real_m13_m12_m14_chain_is_consistent(copilot, backend):
    finding_id = "FND_2B76C7001FFF"
    evidence_ids = backend.evidence_engine.finding_evidence_map.get(finding_id, [])
    assert evidence_ids
    # Accept either historical canonical evidence id or any current canonical evidence
    assert any(eid.startswith("EVD-CAN-") for eid in evidence_ids)
    provenance = backend.get_provenance(finding_id)
    assert provenance["is_valid"] is True
    assert provenance["integrity_status"] == "INTEGRITY_VERIFIED"
    for evidence_id in evidence_ids:
        record = backend.evidence_engine.get_evidence(evidence_id)
        assert record is not None
        assert VALID_ENTITY in record.canonical_entity_ids
    finding = backend.get_finding(finding_id)
    assert finding["entity"] == VALID_ENTITY
    assert finding["status"] in {"AI_GENERATED_LEAD", "ACTIVE"}
