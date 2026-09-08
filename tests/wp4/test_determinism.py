# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: Test suite for WP4 Byte-for-Byte Output Determinism & Invariance

import json
import subprocess
import sys
from dfap.wp4.service import WP4Service


def test_evidence_chain_byte_determinism():
    service1 = WP4Service(data_dir="output")
    service2 = WP4Service(data_dir="output")

    fids = [f["finding_id"] for f in service1.list_findings()]
    assert len(fids) > 0

    for fid in fids:
        chain1 = service1.get_evidence_chain(fid)
        chain2 = service2.get_evidence_chain(fid)

        json1 = json.dumps(chain1, sort_keys=True, indent=2)
        json2 = json.dumps(chain2, sort_keys=True, indent=2)

        assert json1 == json2, f"Evidence chain for {fid} was not byte-identical across calls"


def test_timeline_byte_determinism():
    service = WP4Service(data_dir="output")
    entity_id = "ENT_0F0FC38C24C0539E"

    tl1 = service.get_entity_timeline(entity_id)
    tl2 = service.get_entity_timeline(entity_id)

    assert json.dumps(tl1, sort_keys=True) == json.dumps(tl2, sort_keys=True)


def test_subgraph_byte_determinism():
    service = WP4Service(data_dir="output")
    entity_id = "ENT_0F0FC38C24C0539E"

    sub1 = service.get_entity_subgraph(entity_id, hops=2)
    sub2 = service.get_entity_subgraph(entity_id, hops=2)

    assert json.dumps(sub1, sort_keys=True) == json.dumps(sub2, sort_keys=True)


def test_cytoscape_byte_determinism():
    service = WP4Service(data_dir="output")
    entity_id = "ENT_0F0FC38C24C0539E"

    cy1 = service.get_cytoscape_payload(entity_id, hops=2)
    cy2 = service.get_cytoscape_payload(entity_id, hops=2)

    assert json.dumps(cy1, sort_keys=True) == json.dumps(cy2, sort_keys=True)


def test_cross_process_subprocess_determinism():
    """Execute evidence resolution in two independent Python subprocesses and verify exact byte equality."""
    cmd = [
        sys.executable,
        "-m",
        "dfap.wp4.cli",
        "evidence",
        "FND_F7F1AEA41A06"
    ]
    
    proc1 = subprocess.run(cmd, capture_output=True, text=True, check=True)
    proc2 = subprocess.run(cmd, capture_output=True, text=True, check=True)

    assert proc1.stdout == proc2.stdout, "Cross-process CLI output differed!"
    assert len(proc1.stdout) > 100
