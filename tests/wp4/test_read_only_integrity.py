# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: Test suite for verifying Read-Only Invariance & Zero Upstream Mutation

import hashlib
import glob
import os
import pytest
from dfap.wp4.service import WP4Service


def get_output_hashes():
    hashes = {}
    for p in glob.glob("output/**/*.parquet", recursive=True) + glob.glob("output/**/*.json", recursive=True):
        with open(p, "rb") as f:
            hashes[p] = hashlib.sha256(f.read()).hexdigest()
    return hashes


def test_zero_upstream_mutation_across_all_wp4_operations():
    # 1. Compute initial hashes of all output artifacts
    before_hashes = get_output_hashes()
    assert len(before_hashes) > 0

    # 2. Run all WP4 services and operations
    service = WP4Service(data_dir="output")
    service.verify_upstream_integrity()
    
    findings = service.list_findings()
    for f in findings:
        fid = f["finding_id"]
        service.get_finding(fid)
        service.get_evidence_chain(fid)

    entities = ["ENT_0F0FC38C24C0539E", "ENT_10235790E9A254DE"]
    for ent in entities:
        service.get_entity_timeline(ent)
        service.get_entity_subgraph(ent, hops=2)
        service.get_cytoscape_payload(ent, hops=2)

    service.update_workspace_state(selected_entity_id="ENT_0F0FC38C24C0539E")
    service.reset_workspace_state()

    # 3. Compute after hashes and assert 100% byte equality
    after_hashes = get_output_hashes()
    assert before_hashes == after_hashes, "WP4 operations mutated upstream artifacts!"
