# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: Forensic Case Dossier Exporter (JSON, Markdown, Parquet) with Strict Provenance Ledger

import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Dict, Any, Optional
import pandas as pd


class CaseDossierExporter:
    """
    Exports comprehensive forensic investigation case dossiers into:
    - JSON (Machine-readable full forensic envelope)
    - Markdown (Executive Law Enforcement & Audit Report)
    - Parquet (High-performance analytical storage)
    Every exported case includes strict end-to-end provenance:
    source dataset, source file hash, source record ID, canonical event ID,
    event hash, case ID, detection method & version, timestamp, and provenance tier.
    """

    def __init__(self, export_dir: str = "output/cases", canonical_dir: str = "data/canonical"):
        self.export_dir = export_dir
        self.canonical_dir = canonical_dir
        os.makedirs(self.export_dir, exist_ok=True)

    def export_case(
        self,
        case_data: Dict[str, Any],
        case_id: str
    ) -> Dict[str, str]:
        """Exports case in JSON, Markdown, and Parquet formats."""
        clean_id = case_id.replace(" ", "_").replace("/", "_")
        timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

        json_path = os.path.join(self.export_dir, f"{clean_id}_{timestamp_str}.json")
        md_path = os.path.join(self.export_dir, f"{clean_id}_{timestamp_str}.md")
        pq_path = os.path.join(self.export_dir, f"{clean_id}_{timestamp_str}.parquet")

        # Enrich provenance metadata if missing
        ds_key = case_data.get("dataset", "elliptic")
        prov_file = os.path.join(self.canonical_dir, f"{ds_key}_provenance_manifest.json")
        src_file_hash = "N/A"
        prov_tier = case_data.get("mapping_status") or "SYNTHETIC_TEST_DATA"
        if os.path.exists(prov_file):
            try:
                with open(prov_file, "r") as pf:
                    pm = json.load(pf)
                    src_hashes = pm.get("source_file_hashes", {})
                    src_file_hash = list(src_hashes.values())[0] if src_hashes else "N/A"
                    prov_tier = pm.get("provenance_tier", prov_tier)
            except Exception:
                pass

        case_data["source_file_hash"] = src_file_hash
        case_data["provenance_tier"] = prov_tier
        case_data["detection_method_and_version"] = "M3_DEMPSTER_SHAFER_v1.1 + TEMPORAL_PREDICTOR_v1.0"

        # 1. JSON Export
        with open(json_path, "w") as f:
            json.dump(case_data, f, indent=2)

        # 2. Markdown Export
        md_content = self._build_markdown_report(case_data, case_id)
        with open(md_path, "w") as f:
            f.write(md_content)

        # 3. Parquet Export (Flattened tabular representation)
        flat_records = self._flatten_case_for_parquet(case_data, case_id)
        df = pd.DataFrame([flat_records])
        df.to_parquet(pq_path, index=False)

        return {
            "case_id": case_id,
            "json_path": json_path,
            "markdown_path": md_path,
            "parquet_path": pq_path
        }

    def _build_markdown_report(self, data: Dict[str, Any], case_id: str) -> str:
        eid = data.get("canonical_entity_id") or data.get("entity_id", "UNKNOWN")
        risk = data.get("fused_composite_score") or data.get("risk_score", 0.0)
        threat = data.get("threat_classification") or data.get("anomaly_type", "ANOMALY")
        tier = data.get("provenance_tier", "SYNTHETIC_TEST_DATA")

        lines = [
            f"# DFAP Forensic Investigation Dossier: {case_id}",
            f"**Generated:** {datetime.now(timezone.utc).isoformat()}",
            f"**Subject Entity:** `{eid}`",
            f"**Risk Score:** `{risk}`",
            f"**Threat Classification:** `{threat}`",
            f"**Provenance Tier:** `{tier}`",
            "",
            "---",
            "",
            "## 1. Executive Summary",
            f"Subject entity `{eid}` was analyzed. "
            f"The entity exhibits an anomalous composite risk score of **{risk}** classified as **{threat}**.",
            "",
            "### Anomaly Reasons & Evidential Signals:"
        ]

        reasons = data.get("top_reasons", [])
        if not reasons and "domain_evidence_breakdown" in data:
            for dom, ev in data["domain_evidence_breakdown"].items():
                for r in ev.get("evidence_reasons", []):
                    reasons.append(f"[{dom.upper()}] {r}")

        for r in reasons:
            lines.append(f"- {r}")

        # Dempster-Shafer evidential fusion
        if "dempster_shafer_masses" in data:
            lines.extend([
                "",
                "## 2. Cross-Domain Evidential Fusion (Dempster-Shafer Rule)",
                f"- **Belief(Anomalous):** `{data['dempster_shafer_masses'].get('A', 0.0)}`",
                f"- **Belief(Normal):** `{data['dempster_shafer_masses'].get('N', 0.0)}`",
                f"- **Uncertainty(Theta):** `{data['dempster_shafer_masses'].get('T', 0.0)}`",
                f"- **Conflict Mass Metric k:** `{data.get('evidential_conflict_metric_k', 0.0)}`"
            ])

        # Timeline
        timeline = data.get("cross_domain_timeline") or data.get("preceding_timeline", [])
        if timeline:
            lines.extend([
                "",
                "## 3. Forensic Event Timeline",
                "| Timestamp | Domain | Event ID | Actor | Target | Amount | Evidence Reference |",
                "| :--- | :---: | :---: | :---: | :---: | :---: | :--- |"
            ])
            for t in timeline[:15]:
                amt = f"${t.get('amount', 0):,.2f}" if t.get('amount') else "-"
                lines.append(f"| {t.get('timestamp')} | {t.get('domain', '-')} | `{t.get('event_id', '-')}` | `{t.get('actor') or t.get('source_entity', '-')}` | `{t.get('target') or t.get('target_entity', '-')}` | {amt} | `{t.get('evidence_ref', '-')}` |")

        # Provenance Traceability
        lines.extend([
            "",
            "## 4. Cryptographic Provenance & Audit Trail",
            f"- **Source Dataset:** `{data.get('dataset', 'multi-domain')}`",
            f"- **Source File Hash:** `{data.get('source_file_hash', 'N/A')}`",
            f"- **Source Record ID:** `{data.get('trigger_event_id', data.get('backing_record_id', 'N/A'))}`",
            f"- **Canonical Event ID:** `{data.get('trigger_event_id', 'N/A')}`",
            f"- **Case ID:** `{case_id}`",
            f"- **Detection Method & Version:** `{data.get('detection_method_and_version', 'M3_DEMPSTER_SHAFER_v1.1')}`",
            f"- **Provenance Tier:** `{tier}`",
            f"- **Dossier SHA-256 Digest:** `{hashlib.sha256(json.dumps(data, default=str).encode()).hexdigest()}`"
        ])

        return "\n".join(lines)

    def _flatten_case_for_parquet(self, data: Dict[str, Any], case_id: str) -> Dict[str, Any]:
        return {
            "case_id": case_id,
            "canonical_entity_id": str(data.get("canonical_entity_id") or data.get("entity_id", "")),
            "risk_score": float(data.get("fused_composite_score") or data.get("risk_score", 0.0)),
            "threat_classification": str(data.get("threat_classification") or data.get("anomaly_type", "")),
            "source_dataset": str(data.get("dataset", "multi-domain")),
            "source_file_hash": str(data.get("source_file_hash", "N/A")),
            "source_record_id": str(data.get("trigger_event_id", data.get("backing_record_id", "N/A"))),
            "canonical_event_id": str(data.get("trigger_event_id", "N/A")),
            "detection_method_and_version": str(data.get("detection_method_and_version", "")),
            "provenance_tier": str(data.get("provenance_tier", "")),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "raw_payload_json": json.dumps(data, default=str)
        }
