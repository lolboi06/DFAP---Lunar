# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: M14 Agentic Investigation Orchestrator with Local Ollama - Test Suite

import pytest
from dfap.investigation.ollama_client import OllamaClient, OllamaUnavailableError
from dfap.investigation.agentic_orchestrator import (
    AgenticInvestigationOrchestrator,
    ClosedDFAPToolRegistry,
    AgentState,
    AgenticInvestigationResult,
)
from dfap.investigation.workspace import InvestigationWorkspaceBackend
from dfap.investigation.conflict_fixture import register_contradiction_fixture
from dfap.investigation.reliability_fixture import register_reliability_fixture
from dfap.investigation.data_quality_fixture import register_data_quality_fixture
from dfap.investigation.four_domain_fixture import register_four_domain_fixture
from dfap.wp4.cli import handle_m13_command
from dfap.investigation.copilot import InvestigationCopilot


@pytest.fixture
def workspace_backend():
    backend = InvestigationWorkspaceBackend(output_dir="output", canonical_dir="data/canonical", cases_dir="data/cases")
    register_contradiction_fixture(backend)
    register_reliability_fixture(backend)
    register_data_quality_fixture(backend)
    register_four_domain_fixture(backend)
    return backend


@pytest.fixture
def orchestrator(workspace_backend):
    return AgenticInvestigationOrchestrator(workspace_backend)


def test_ollama_health():
    """Verify local Ollama health check responds OK with available models."""
    client = OllamaClient()
    health = client.health_check()
    assert health["status"] == "OK"
    assert health["selected_model"] is not None
    assert len(health["available_models"]) >= 1


def test_ollama_unavailable():
    """Verify client explicit failure when Ollama port is unreachable."""
    bad_client = OllamaClient(base_url="http://localhost:59999", timeout=1.0)
    health = bad_client.health_check()
    assert health["status"] == "UNAVAILABLE"
    with pytest.raises(OllamaUnavailableError):
        bad_client.generate("Test prompt")


def test_model_discovery_and_configuration():
    """Verify auto-discovery of local model or explicit configuration override."""
    client = OllamaClient()
    models = client.available_models()
    assert len(models) >= 1
    assert "qwen3:4b" in models or len(models) > 0
    assert client.model in models


def test_deterministic_tool_registry(workspace_backend):
    """Verify closed registry contains all 14 required DFAP tools."""
    registry = ClosedDFAPToolRegistry(workspace_backend)
    expected_tools = [
        "case_forensic_packet",
        "case_risk",
        "finding_explainability",
        "cross_domain_conflict",
        "temporal_sequence",
        "temporal_patterns",
        "temporal_transitions",
        "temporal_phases",
        "motif_discovery",
        "adaptive_baseline",
        "graph_ml_comparison",
        "evidence_lookup",
        "provenance_lookup",
        "timeline",
    ]
    for t in expected_tools:
        assert registry.is_valid_tool(t) is True
    assert registry.is_valid_tool("arbitrary_bash_tool") is False
    assert registry.is_valid_tool("internet_browser") is False


def test_deterministic_tool_selection(orchestrator):
    """Verify plan_tools produces deterministic canonical tool selection."""
    tools = orchestrator._plan_tools(
        "Why was this finding flagged?",
        case_id="CASE-DFAP-4DOMAIN-001",
        entity_id="ENT_DFAP_4DOM_001",
        finding_id="FND_4DOM_FUSED_001"
    )
    assert "finding_explainability" in tools
    assert "cross_domain_conflict" in tools
    # Verify canonical order preserved
    order = ClosedDFAPToolRegistry.CANONICAL_TOOL_ORDER
    indices = [order.index(t) for t in tools if t in order]
    assert indices == sorted(indices)


def test_single_tool_question(orchestrator):
    """Verify focused single-domain questions route to appropriate tools."""
    tools = orchestrator._plan_tools(
        "What is the status of this case?",
        case_id="CASE-DFAP-4DOMAIN-001",
        entity_id=None,
        finding_id=None
    )
    assert "case_forensic_packet" in tools


def test_compound_investigation(orchestrator):
    """Verify multi-domain compound questions assemble appropriate tool set."""
    tools = orchestrator._plan_tools(
        "Why was finding FND_4DOM_FUSED_001 flagged, what evidence supports it, what conflicts with it, and what should the investigator check next?",
        case_id="CASE-DFAP-4DOMAIN-001",
        entity_id="ENT_DFAP_4DOM_001",
        finding_id="FND_4DOM_FUSED_001"
    )
    assert "finding_explainability" in tools
    assert "case_forensic_packet" in tools
    assert "cross_domain_conflict" in tools
    assert "temporal_sequence" in tools


def test_max_8_tool_calls(orchestrator):
    """Verify orchestrator caps planned tool executions at MAX_TOOL_CALLS = 8."""
    tools = orchestrator._plan_tools(
        "Explain everything about case status, risk, explainability, conflict, sequence, patterns, transitions, phases, motifs, baseline, graph ml, evidence, provenance, and timeline",
        case_id="CASE-DFAP-4DOMAIN-001",
        entity_id="ENT_DFAP_4DOM_001",
        finding_id="FND_4DOM_FUSED_001"
    )
    assert len(tools) <= 8


def test_unavailable_question(orchestrator):
    """Verify out-of-scope query returns UNAVAILABLE without hallucination."""
    res = orchestrator.investigate("What is the recipe for chocolate chip cookies?")
    assert res.status == AgentState.UNAVAILABLE.value
    assert "UNAVAILABLE" in res.answer


def test_evidence_binding(orchestrator):
    """Verify actual tool execution populates authentic evidence references."""
    res = orchestrator.investigate(
        "Why was finding FND_4DOM_FUSED_001 flagged?",
        case_id="CASE-DFAP-4DOMAIN-001"
    )
    assert len(res.evidence_refs) > 0
    assert any("EVD-" in ref or "ref:" in ref for ref in res.evidence_refs)


def test_provenance_binding(orchestrator):
    """Verify actual tool execution populates authentic provenance references."""
    res = orchestrator.investigate(
        "What evidence supports finding FND_4DOM_FUSED_001?",
        case_id="CASE-DFAP-4DOMAIN-001"
    )
    assert len(res.provenance_refs) > 0
    assert any("PROV-" in ref for ref in res.provenance_refs)


def test_m11_conflict_propagation(orchestrator):
    """Verify M11 evidential conflict propagates CONFLICTED status and human review requirement."""
    res = orchestrator.investigate(
        "Is there conflicting evidence in this case?",
        case_id="CASE-DFAP-4DOMAIN-001"
    )
    assert res.status == "CONFLICTED"
    assert res.requires_human_review is True
    assert "FINANCIAL vs SOCIAL" in res.answer or any("FINANCIAL vs SOCIAL" in str(c) for c in res.claims) or any("FINANCIAL vs SOCIAL" in a for a in res.next_actions)


def test_m12_conflict_propagation(orchestrator):
    """Verify M12 forensic packet status CONFLICTED sets orchestrator status."""
    res = orchestrator.investigate(
        "What is the status of this case?",
        case_id="CASE-DFAP-4DOMAIN-001"
    )
    assert res.status == "CONFLICTED"
    assert res.requires_human_review is True


def test_human_review_requirement(orchestrator):
    """Verify human review flag is strictly active on evidential conflict."""
    res = orchestrator.investigate(
        "What should the investigator check next?",
        case_id="CASE-DFAP-4DOMAIN-001"
    )
    assert res.requires_human_review is True
    assert len(res.next_actions) >= 1


def test_unsupported_claim_rejection(orchestrator):
    """Verify all factual claims map to actual executed tool trace records."""
    res = orchestrator.investigate(
        "Why was finding FND_4DOM_FUSED_001 flagged?",
        case_id="CASE-DFAP-4DOMAIN-001"
    )
    tool_names = {t["tool_name"] for t in res.tool_trace}
    for c in res.claims:
        assert c["tool"] in tool_names


def test_no_guilt_intent_inference(orchestrator):
    """Verify guilt query strictly refuses legal culpability determination."""
    res = orchestrator.investigate(
        "Can you prove the suspect is guilty?",
        case_id="CASE-DFAP-4DOMAIN-001"
    )
    assert "refrains from making legal determinations of guilt" in res.answer or "not establish" in res.answer
    assert "Strict Non-Culpability" in res.limitations[0]


def test_deterministic_repeated_execution(orchestrator):
    """Verify repeated execution produces identical tool trace sequence and status."""
    q = "What is the status of this case?"
    r1 = orchestrator.investigate(q, case_id="CASE-DFAP-4DOMAIN-001")
    r2 = orchestrator.investigate(q, case_id="CASE-DFAP-4DOMAIN-001")
    assert r1.status == r2.status
    assert [t["tool_name"] for t in r1.tool_trace] == [t["tool_name"] for t in r2.tool_trace]
    assert r1.requires_human_review == r2.requires_human_review


def test_four_domain_e2e_investigation(orchestrator):
    """Full 4-domain forensic E2E investigation demonstrating complete DFAP thesis."""
    res = orch = orchestrator.investigate(
        "Why was finding FND_4DOM_FUSED_001 flagged, what evidence supports it, what conflicts with it, and what should the investigator check next?",
        case_id="CASE-DFAP-4DOMAIN-001"
    )
    assert res.status == "CONFLICTED"
    assert res.requires_human_review is True
    assert len(res.tool_trace) >= 4
    assert len(res.evidence_refs) >= 4
    assert "FINANCIAL vs SOCIAL" in res.answer or any("FINANCIAL vs SOCIAL" in a for a in res.next_actions) or any("FINANCIAL vs SOCIAL" in t["output_summary"] for t in res.tool_trace)


def test_m13_cli_agent_investigate_and_trace(workspace_backend):
    """Verify M13 CLI integration for agent investigate and agent trace commands."""
    out_inv = handle_m13_command(
        workspace_backend,
        "agent investigate \"Why was finding FND_4DOM_FUSED_001 flagged?\" CASE-DFAP-4DOMAIN-001"
    )
    assert "AGENTIC INVESTIGATION" in out_inv
    assert "Status:" in out_inv
    assert "Tool Trace:" in out_inv
    assert "Answer:" in out_inv

    out_trace = handle_m13_command(
        workspace_backend,
        "agent trace \"What is the status of this case?\" CASE-DFAP-4DOMAIN-001"
    )
    assert "AGENTIC INVESTIGATION TRACE" in out_trace
    assert "Deterministic Tool Execution Trace" in out_trace
    assert "State Transitions" in out_trace


def test_m14_copilot_routing(workspace_backend):
    """Verify InvestigationCopilot routes agent queries to agentic orchestrator."""
    copilot = InvestigationCopilot(workspace_backend)
    res = copilot.ask("agent investigate \"What is the status of this case?\"", case_id="CASE-DFAP-4DOMAIN-001")
    assert res["status"] in ("CONFLICTED", "GROUNDED", "HUMAN_REVIEW_REQUIRED")
    assert "answer" in res
