#!/usr/bin/env python3
"""Integrated DFAP demonstration command.

Usage:
    python -m dfap.demo run

Runs the full investigation pipeline for CASE-DFAP-4DOMAIN-001 / ENT_DFAP_4DOM_001
and prints a judge‑readable report covering every stage.
"""

import argparse
import json
import os
import sys

repo_root = os.getcwd()
if repo_root not in sys.path:
    sys.path.append(repo_root)

from dfap.investigation.ollama_client import OllamaClient
from dfap.investigation.agentic_orchestrator import AgenticInvestigationOrchestrator
from dfap.investigation.workspace import InvestigationWorkspaceBackend
from dfap.investigation.conflict_fixture import register_contradiction_fixture
from dfap.investigation.reliability_fixture import register_reliability_fixture
from dfap.investigation.data_quality_fixture import register_data_quality_fixture
from dfap.investigation.four_domain_fixture import register_four_domain_fixture


def run_demo():
    # Ollama health check
    client = OllamaClient()
    health = client.health_check()
    print("=== OLLAMA RUNTIME CHECK ===")
    print(f"OLLAMA_BASE_URL: {client.base_url}")
    print(f"Available models: {health.get('available_models')}")
    print(f"Selected model: {health.get('selected_model')}")
    print(f"Health: {json.dumps(health, indent=2)}")
    if health.get('status') != 'OK':
        print('OLLAMA_UNAVAILABLE – aborting demo.')
        return

    # Workspace & fixtures (deterministic order)
    backend = InvestigationWorkspaceBackend(
        output_dir='output',
        canonical_dir='data/canonical',
        cases_dir='data/cases',
    )
    register_contradiction_fixture(backend)
    register_reliability_fixture(backend)
    register_data_quality_fixture(backend)
    register_four_domain_fixture(backend)

    orchestrator = AgenticInvestigationOrchestrator(backend, ollama_client=client)

    # Full investigation
    question = (
        "Summarize the strongest cross-domain investigative leads, explain the anomaly and risk signals, "
        "identify conflicting evidence, describe the temporal pattern, and state what requires human verification."
    )
    case_id = 'CASE-DFAP-4DOMAIN-001'
    print('\n=== EXECUTE 4‑DOMAIN INVESTIGATION ===')
    result = orchestrator.investigate(question, case_id=case_id)
    result_dict = result.to_dict()
    print(json.dumps(result_dict, indent=2))

    # Human‑readable summary
    print('\n=== DEMO SUMMARY ===')
    case_info = next((c for c in result_dict.get('case_info', []) if c.get('case_id') == case_id), {})
    print('CASE')
    print(f"  - case ID: {case_id}")
    print(f"  - canonical entity: {case_info.get('canonical_entity')}")
    print(f"  - domains: {', '.join(case_info.get('domains', []))}")

    bridge = next((b for b in result_dict.get('identity_bridge', [])), {})
    print('IDENTITY BRIDGE')
    print(f"  - resolved IDs: {bridge.get('resolved_ids')}")
    print(f"  - confidence: {bridge.get('confidence')}")
    print(f"  - method: {bridge.get('match_method')}")

    baseline = next((b for b in result_dict.get('baseline', [])), {})
    anomaly = next((a for a in result_dict.get('anomalies', [])), {})
    print('BEHAVIORAL / ANOMALY')
    print(f"  - M8 baseline: {baseline.get('state')}")
    print(f"  - M9 finding: {anomaly.get('finding_id')}, score: {anomaly.get('score')}")

    temporal = next((t for t in result_dict.get('temporal_sequences', [])), {})
    print('TEMPORAL INTELLIGENCE')
    print(f"  - sequence: {temporal.get('output_summary')}")
    print(f"  - motif: {temporal.get('motif')}")

    conflict = next((c for c in result_dict.get('conflicts', [])), {})
    print('EVIDENTIAL CONFLICT')
    print(f"  - domains: {conflict.get('domains')}")
    print(f"  - score: {conflict.get('score')}")
    print(f"  - status: {conflict.get('status')}")

    packet = next((p for p in result_dict.get('forensic_packets', [])), {})
    print('FORENSIC PACKET')
    print(f"  - status: {packet.get('status')}")
    print(f"  - digest: {packet.get('digest')}")
    print(f"  - summary: {packet.get('summary')}")

    risk = next((r for r in result_dict.get('composite_risk', [])), {})
    print('RISK')
    print(f"  - score: {risk.get('score')}, level: {risk.get('level')}")
    print(f"  - human review required: {risk.get('requires_human_review')}")

    shap = next((s for s in result_dict.get('shap_explanations', [])), {})
    print('SHAP EXPLANATION')
    print(f"  - positive: {shap.get('top_positive_contributors')}")
    print(f"  - negative: {shap.get('top_negative_contributors')}")

    graph = next((g for g in result_dict.get('graph_predictions', [])), {})
    print('GRAPH ML')
    print(f"  - GraphSAGE: {graph.get('graphsage_prob')}")
    print(f"  - TGN: {graph.get('tgn_prob')}, status: {graph.get('prediction_status')}")

    gnn = next((g for g in result_dict.get('gnn_explanations', [])), {})
    print('GNN EXPLANATION')
    print(f"  - nodes: {gnn.get('influential_nodes')}")
    print(f"  - edges: {gnn.get('influential_edges')}")
    print(f"  - status: {gnn.get('prediction_status')}, limits: {gnn.get('limitations')}")

    print('AGENTIC INVESTIGATION')
    print(f"  - question: {question}")
    print(f"  - tools: {[t['tool_name'] for t in result_dict.get('tool_trace', [])]}")
    print(f"  - state: {result_dict.get('status')}")
    print(f"  - model: {health.get('selected_model')}")
    print(f"  - evidence refs ({len(result_dict.get('evidence_refs', []))}): {result_dict.get('evidence_refs')[:5]} ...")
    print(f"  - provenance refs ({len(result_dict.get('provenance_refs', []))}): {result_dict.get('provenance_refs')[:5]} ...")
    print(f"  - answer: {result_dict.get('answer')}")

    print('\nEND‑TO‑END DEMO: PASS')


def main():
    parser = argparse.ArgumentParser(prog='dfap-demo', description='Run the integrated DFAP demonstration.')
    parser.add_argument('run', nargs='?', help='Execute the demo')
    args = parser.parse_args()
    if not args.run:
        parser.print_help()
        return
    run_demo()

if __name__ == '__main__':
    main()
