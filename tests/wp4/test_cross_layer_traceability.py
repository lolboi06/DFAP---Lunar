# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: Test suite for End-to-End Cross-Layer Traceability on Real Frozen Artifacts

import pytest
import pandas as pd
from dfap.wp4.service import WP4Service


def test_full_cross_layer_traceability_on_real_frozen_artifacts():
    service = WP4Service(data_dir="output")
    findings = service.list_findings()
    assert len(findings) > 0

    # Pick first finding
    fid = findings[0]["finding_id"]
    chain = service.get_evidence_chain(fid)

    assert chain["finding_id"] == fid
    assert len(chain["evidence_events"]) > 0

    # Verify event -> sha256 -> provenance -> source file & row index
    for ev in chain["evidence_events"]:
        event_id = ev["event_id"]
        sha256_hash = ev["sha256_hash"]
        source_file = ev["source_file"]
        source_row_index = ev["source_row_index"]

        assert event_id is not None
        assert sha256_hash is not None and len(sha256_hash) == 64
        assert source_file is not None
        assert source_row_index is not None and source_row_index >= 0

        # Cross-verify directly with provenance ledger DataFrame
        df_prov = pd.read_parquet("output/provenance_ledger.parquet")
        matching_prov = df_prov[df_prov["sha256_hash"] == sha256_hash]
        assert len(matching_prov) == 1
        assert matching_prov["source_file"].iloc[0] == source_file
        assert matching_prov["source_row_index"].iloc[0] == source_row_index
