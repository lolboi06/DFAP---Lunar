# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: Research Test Suite for Cross-Domain Fusion, Targeted Search, and Case Dossier Export

import os
import pandas as pd
import pytest

from dfap.investigation.cross_domain import CrossDomainInvestigator
from dfap.investigation.search import TargetedSearchEngine
from dfap.investigation.case_export import CaseDossierExporter


def test_identity_bridge_and_cross_domain_fusion():
    """Verifies that controlled identity bridge links domains and fuses evidential masses via Dempster-Shafer."""
    investigator = CrossDomainInvestigator()
    cases = investigator.list_cases()
    assert len(cases) >= 2

    c1 = investigator.investigate_case("CASE-CROSS-001")
    assert c1["case_id"] == "CASE-CROSS-001"
    assert c1["mapping_status"] == "CONTROLLED_CASE_MAPPING"
    assert c1["fused_composite_score"] > 0.50
    assert "dempster_shafer_masses" in c1
    assert "A" in c1["dempster_shafer_masses"]
    assert "evidential_conflict_metric_k" in c1
    assert len(c1["domains_analyzed"]) >= 2

    # Domain explanation
    breakdown = c1["domain_evidence_breakdown"]
    for dom in c1["domains_analyzed"]:
        assert dom in breakdown
        assert "anomaly_score" in breakdown[dom]
        assert "evidence_reasons" in breakdown[dom]


def test_targeted_police_search():
    """Verifies targeted search across names (fuzzy lead), wallets, and IPs."""
    searcher = TargetedSearchEngine()

    # 1. Fuzzy Name lead
    name_res = searcher.search("name", "Sam Roger")
    assert len(name_res) > 0
    assert "Sam Roger" in name_res[0]["candidate"]
    assert "Found in canonical event" in name_res[0]["match_evidence"] or "identity bridge" in name_res[0]["match_evidence"]
    assert name_res[0]["dataset"] in ("DFAP Production Baseline", "SOCIAL", "Stack Overflow")

    # 2. Wallet lookup
    wallet_res = searcher.search("wallet", "1Dark")
    assert len(wallet_res) > 0
    assert wallet_res[0]["query_type"] == "WALLET"
    assert "WALLET_1Dark" in wallet_res[0]["candidate"]

    # 3. IP lookup
    ip_res = searcher.search("ip", "10.0.1")
    assert len(ip_res) > 0
    assert ip_res[0]["query_type"] == "IP_ADDRESS"
    assert "IP_10.0.1" in ip_res[0]["candidate"]


def test_case_dossier_exporter_all_three_formats():
    """Verifies export to JSON, Markdown, and Parquet formats."""
    investigator = CrossDomainInvestigator()
    c_data = investigator.investigate_case("CASE-CROSS-001")

    exporter = CaseDossierExporter()
    res = exporter.export_case(c_data, "CASE-CROSS-001")

    assert os.path.exists(res["json_path"])
    assert os.path.exists(res["markdown_path"])
    assert os.path.exists(res["parquet_path"])

    # Verify Markdown contains required executive sections
    with open(res["markdown_path"], "r") as f:
        md_text = f.read()
    assert "## 1. Executive Summary" in md_text
    assert "## 2. Cross-Domain Evidential Fusion" in md_text
    assert "## 3. Forensic Event Timeline" in md_text
    assert "## 4. Cryptographic Provenance" in md_text

    # Verify Parquet is valid
    pq_df = pd.read_parquet(res["parquet_path"])
    assert len(pq_df) == 1
    assert pq_df["case_id"].iloc[0] == "CASE-CROSS-001"
