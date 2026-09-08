# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: Test suite for M12 W3C PROV-O Model Compliance & Determinism

import json
from dfap.wp4.provenance import W3CProvenanceBuilder


def test_prov_o_document_structure():
    doc = W3CProvenanceBuilder.build_finding_prov_document(
        finding_id="FND_TEST_001",
        entity_id="ENT_TARGET_001",
        event_records=[{
            "event_id": "EVT_TEST_01",
            "timestamp": "2026-09-01T10:00:00+00:00",
            "event_type": "TRANSACTION",
            "source_domain": "BANK",
            "sha256_hash": "abcd1234efgh5678",
            "source_file": "banking_records.csv",
            "source_row_index": 5
        }],
        feature_names=["degree", "weighted_degree"],
        anomaly_type="BEHAVIORAL_DEVIATION",
        created_at="2026-09-01T12:00:00+00:00"
    )

    assert "@context" in doc
    assert "entities" in doc
    assert "activities" in doc
    assert "agents" in doc
    assert "relations" in doc

    # Verify W3C PROV-O standard predicates
    rel_types = {r["@type"] for r in doc["relations"]}
    assert "prov:wasGeneratedBy" in rel_types
    assert "prov:wasDerivedFrom" in rel_types
    assert "prov:used" in rel_types
    assert "prov:wasAssociatedWith" in rel_types


def test_prov_o_deterministic_uri_generation():
    uri1 = W3CProvenanceBuilder.entity_uri("finding", "FND_100")
    uri2 = W3CProvenanceBuilder.entity_uri("finding", "FND_100")
    assert uri1 == uri2 == "urn:dfap:entity:finding:FND_100"

    act_uri = W3CProvenanceBuilder.activity_uri("fusion", "FND_100")
    assert act_uri == "urn:dfap:activity:fusion:FND_100"
