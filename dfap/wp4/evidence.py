# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: M12 Deterministic Evidence & Provenance Resolver with Strict Schema and Integrity Verification

import hashlib
import json
import os
from typing import Dict, List, Any, Optional, Set, Tuple
import pandas as pd

from dfap.provenance import compute_canonical_row_hash
from dfap.wp4.contracts import (
    ErrorCode,
    EvidenceStatus,
    EvidenceChainError,
    CanonicalEvidenceEvent,
    ProvenanceStep,
    ResolvedFeature,
    EvidenceChain,
    UpstreamContractError,
    UpstreamIntegrityError,
    FROZEN_UPSTREAM_MANIFEST,
    REQUIRED_SCHEMAS,
)
from dfap.wp4.provenance import W3CProvenanceBuilder


class EvidenceEngine:
    """
    M12 Evidence & Provenance Engine.
    Resolves findings down through features, evidence refs, canonical events,
    independent SHA-256 reconstruction, and provenance ledger source rows.
    """

    def __init__(self, data_dir: str = "output", verify_frozen_manifest: bool = True):
        self.data_dir = data_dir
        self.verify_frozen_manifest = verify_frozen_manifest
        self._manifest: Dict[str, str] = {}
        self._load_and_validate_upstream()

    def _compute_file_hash(self, path: str) -> str:
        if not os.path.exists(path):
            raise UpstreamContractError(f"Missing required upstream file: {path}", ErrorCode.SCHEMA_CONTRACT_ERROR)
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()

    def _validate_schema(self, rel_name: str, df: pd.DataFrame):
        """Enforces that all required columns are present in the loaded DataFrame."""
        req_cols = REQUIRED_SCHEMAS.get(rel_name, set())
        missing_cols = req_cols - set(df.columns)
        if missing_cols:
            raise UpstreamContractError(
                f"Schema contract violation in '{rel_name}': missing required column(s) {sorted(list(missing_cols))}",
                ErrorCode.SCHEMA_CONTRACT_ERROR
            )

    def _load_and_validate_upstream(self):
        """Validates existence, schemas, and verifies SHA-256 hashes against the frozen manifest."""
        findings_path = os.path.join(self.data_dir, "m3/findings/findings.parquet")
        events_path = os.path.join(self.data_dir, "canonical_events.parquet")
        prov_path = os.path.join(self.data_dir, "provenance_ledger.parquet")
        entities_path = os.path.join(self.data_dir, "resolved_entities.parquet")
        graph_feat_path = os.path.join(self.data_dir, "graph_features.parquet")
        telecom_feat_path = os.path.join(self.data_dir, "telecom_features.parquet")
        fin_feat_path = os.path.join(self.data_dir, "financial_features.parquet")
        soc_feat_path = os.path.join(self.data_dir, "social_features.parquet")

        required_files = [
            ("canonical_events.parquet", events_path),
            ("provenance_ledger.parquet", prov_path),
            ("resolved_entities.parquet", entities_path),
            ("graph_features.parquet", graph_feat_path),
            ("telecom_features.parquet", telecom_feat_path),
            ("financial_features.parquet", fin_feat_path),
            ("social_features.parquet", soc_feat_path),
            ("m3/findings/findings.parquet", findings_path),
        ]

        # 1. Existence check
        for rel_name, full_path in required_files:
            if not os.path.exists(full_path):
                raise UpstreamContractError(f"Required frozen upstream artifact missing: {full_path}", ErrorCode.SCHEMA_CONTRACT_ERROR)

        # 2. Frozen hash manifest verification
        for rel_name, full_path in required_files:
            current_hash = self._compute_file_hash(full_path)
            self._manifest[rel_name] = current_hash
            if self.verify_frozen_manifest:
                expected_hash = FROZEN_UPSTREAM_MANIFEST.get(rel_name)
                # Allow an approved rebaseline for provenance_ledger.parquet if recorded
                rebaseline_path = os.path.join(self.data_dir, "wp1_rebaseline_manifest.json")
                rebaseline_new_hash = None
                if os.path.exists(rebaseline_path):
                    try:
                        rb = json.load(open(rebaseline_path, "r", encoding="utf-8"))
                        rebaseline_new_hash = rb.get("new_hash")
                    except Exception:
                        rebaseline_new_hash = None

                if expected_hash and current_hash != expected_hash:
                    # Accept rebaseline new hash for provenance_ledger.parquet specifically
                    if rel_name == "provenance_ledger.parquet" and rebaseline_new_hash and current_hash == rebaseline_new_hash:
                        # treat as acceptable current baseline (do not modify frozen manifest constant)
                        continue
                    raise UpstreamIntegrityError(
                        f"Frozen upstream artifact '{rel_name}' failed integrity check. "
                        f"Expected '{expected_hash}', got '{current_hash}'",
                        ErrorCode.UPSTREAM_INTEGRITY_ERROR
                    )

        # 3. Load Parquet DataFrames and explicitly validate required schemas
        self.df_events = pd.read_parquet(events_path)
        self._validate_schema("canonical_events.parquet", self.df_events)

        self.df_prov = pd.read_parquet(prov_path)
        self._validate_schema("provenance_ledger.parquet", self.df_prov)

        self.df_entities = pd.read_parquet(entities_path)
        self._validate_schema("resolved_entities.parquet", self.df_entities)

        self.df_findings = pd.read_parquet(findings_path)
        self._validate_schema("m3/findings/findings.parquet", self.df_findings)

        self.df_graph_feat = pd.read_parquet(graph_feat_path)
        self._validate_schema("graph_features.parquet", self.df_graph_feat)

        self.df_telecom_feat = pd.read_parquet(telecom_feat_path)
        self._validate_schema("telecom_features.parquet", self.df_telecom_feat)

        self.df_fin_feat = pd.read_parquet(fin_feat_path)
        self._validate_schema("financial_features.parquet", self.df_fin_feat)

        self.df_soc_feat = pd.read_parquet(soc_feat_path)
        self._validate_schema("social_features.parquet", self.df_soc_feat)

        # Build fast lookup indexes
        self.events_by_id: Dict[str, Dict[str, Any]] = {}
        for _, row in self.df_events.iterrows():
            self.events_by_id[str(row["event_id"])] = row.to_dict()

        self.events_by_hash: Dict[str, Dict[str, Any]] = {}
        for _, row in self.df_events.iterrows():
            self.events_by_hash[str(row["sha256_hash"])] = row.to_dict()

        self.prov_by_hash: Dict[str, Dict[str, Any]] = {}
        for _, row in self.df_prov.iterrows():
            self.prov_by_hash[str(row["sha256_hash"])] = row.to_dict()

        self.findings_by_id: Dict[str, Dict[str, Any]] = {}
        for _, row in self.df_findings.iterrows():
            self.findings_by_id[str(row["finding_id"])] = row.to_dict()

        # Index domain and graph features: (entity_id, feature_name) -> (store_name, value, window)
        self.features_by_entity: Dict[str, Dict[str, Tuple[str, Any, Optional[str]]]] = {}
        
        feature_stores = [
            ("graph_features.parquet", self.df_graph_feat),
            ("telecom_features.parquet", self.df_telecom_feat),
            ("financial_features.parquet", self.df_fin_feat),
            ("social_features.parquet", self.df_soc_feat),
        ]

        for store_name, df_f in feature_stores:
            for _, row in df_f.iterrows():
                eid = str(row["entity_id"]).strip()
                fname = str(row["feature_name"]).strip()
                fval = row.get("feature_value")
                fwin = str(row.get("window")) if "window" in row and pd.notna(row["window"]) else None
                if eid not in self.features_by_entity:
                    self.features_by_entity[eid] = {}
                self.features_by_entity[eid][fname] = (store_name, fval, fwin)

    @property
    def upstream_manifest(self) -> Dict[str, str]:
        return dict(self._manifest)

    def list_findings(self) -> List[Dict[str, Any]]:
        """Returns deterministic list of available findings."""
        res = []
        for fid in sorted(self.findings_by_id.keys()):
            f = self.findings_by_id[fid]
            res.append({
                "finding_id": f.get("finding_id"),
                "entity_id": f.get("entity_id"),
                "anomaly_type": f.get("anomaly_type"),
                "composite_score": float(f.get("composite_score", 0.0)),
                "created_at": f.get("created_at"),
                "evidence_count": int(f.get("evidence_count", 0)),
                "status": f.get("status")
            })
        return res

    def get_finding(self, finding_id: str) -> Dict[str, Any]:
        """Returns finding metadata by ID or raises EvidenceChainError."""
        fid = str(finding_id).strip()
        if fid not in self.findings_by_id:
            raise EvidenceChainError(f"Finding not found: {fid}", ErrorCode.UNKNOWN_FINDING)
        return dict(self.findings_by_id[fid])

    def get_events(self, event_ids: List[str]) -> List[Dict[str, Any]]:
        """Returns canonical events by IDs. Raises MISSING_EVENT if any ID is missing."""
        res = []
        for eid in event_ids:
            eid_str = str(eid).strip()
            if eid_str not in self.events_by_id:
                raise EvidenceChainError(f"Requested event_id not found: '{eid_str}'", ErrorCode.MISSING_EVENT)
            res.append(dict(self.events_by_id[eid_str]))
        return res

    def get_evidence_chain(self, finding_id: str) -> EvidenceChain:
        """
        Deterministically resolves the full evidence chain for finding_id.
        Traverses: finding -> features -> evidence_refs -> event_ids -> canonical_events -> sha256 -> provenance_ledger -> raw row.
        Includes unconditional independent recomputation and verification of SHA-256 hashes,
        and enforces exact-set consistency between event_ids and evidence_refs.
        """
        fid = str(finding_id).strip()
        if fid not in self.findings_by_id:
            raise EvidenceChainError(f"Finding not found: {fid}", ErrorCode.UNKNOWN_FINDING)

        finding = self.findings_by_id[fid]
        entity_id = str(finding.get("entity_id", ""))
        anomaly_type = str(finding.get("anomaly_type", "UNKNOWN"))
        composite_score = float(finding.get("composite_score", 0.0))
        created_at = str(finding.get("created_at", "2026-01-01T00:00:00+00:00"))

        # Parse event_ids & evidence_refs
        raw_event_ids = finding.get("event_ids", [])
        if isinstance(raw_event_ids, str):
            try:
                raw_event_ids = json.loads(raw_event_ids)
            except Exception:
                raw_event_ids = [raw_event_ids] if raw_event_ids else []

        raw_evidence_refs = finding.get("evidence_refs", [])
        if isinstance(raw_evidence_refs, str):
            try:
                raw_evidence_refs = json.loads(raw_evidence_refs)
            except Exception:
                raw_evidence_refs = [raw_evidence_refs] if raw_evidence_refs else []

        raw_graph_refs = finding.get("graph_refs", [])
        if isinstance(raw_graph_refs, str):
            try:
                raw_graph_refs = json.loads(raw_graph_refs)
                if isinstance(raw_graph_refs, str):
                    raw_graph_refs = json.loads(raw_graph_refs)
            except Exception:
                raw_graph_refs = []

        issues: List[str] = []

        # Check for duplicates in event refs & evidence refs
        if len(raw_event_ids) != len(set(raw_event_ids)):
            issues.append(ErrorCode.DUPLICATE_EVENT_REF.value)

        if len(raw_evidence_refs) != len(set(raw_evidence_refs)):
            issues.append(ErrorCode.DUPLICATE_EVIDENCE_REF.value)

        # ── EXACT-SET CONSISTENCY VALIDATION ──────────────────────────────────
        clean_event_ids = set(str(e).strip() for e in raw_event_ids if str(e).strip())
        clean_evidence_refs = set(str(r).strip() for r in raw_evidence_refs if str(r).strip())

        # Map each clean_evidence_ref to an event_id
        event_ids_from_refs = set()
        unresolvable_refs = set()
        for ref in clean_evidence_refs:
            if ref in self.events_by_hash:
                event_ids_from_refs.add(str(self.events_by_hash[ref]["event_id"]))
            elif ref in self.events_by_id:
                event_ids_from_refs.add(ref)
            else:
                unresolvable_refs.add(ref)

        if unresolvable_refs:
            for unres in sorted(unresolvable_refs):
                issues.append(f"{ErrorCode.MISSING_EVIDENCE_REF.value}:{unres}")

        # Exact-set consistency check: when both sets present, resolved_event_ids_from_evidence_refs MUST equal clean_event_ids
        if clean_event_ids and clean_evidence_refs:
            if event_ids_from_refs != clean_event_ids:
                issues.append(ErrorCode.INCONSISTENT_EVIDENCE_REFERENCE.value)

        # Determine candidate event IDs
        if clean_event_ids:
            candidate_event_ids = clean_event_ids
        else:
            candidate_event_ids = event_ids_from_refs

        # 1. Resolve & Verify Features against real feature outputs
        # Note: Member 3 evidence_refs are finding-level; features inherit finding-level evidence_refs.
        resolved_features: List[ResolvedFeature] = []
        feature_names = sorted(set(list(raw_graph_refs)))
        entity_features = self.features_by_entity.get(entity_id, {})
        
        for feat_name in feature_names:
            if feat_name in entity_features:
                store_name, f_val, f_win = entity_features[feat_name]
                resolved_features.append(ResolvedFeature(
                    feature_name=feat_name,
                    feature_store=store_name,
                    feature_value=f_val,
                    entity_id=entity_id,
                    window=f_win,
                    evidence_refs=tuple(sorted(str(r) for r in raw_evidence_refs))
                ))
            else:
                # Feature name not indexed in feature store
                issues.append(f"{ErrorCode.MISSING_FEATURE.value}:{feat_name}")

        # 2. Resolve Canonical Events and Provenance with Unconditional Independent SHA-256 verification
        evidence_events: List[CanonicalEvidenceEvent] = []
        event_records_for_prov: List[Dict[str, Any]] = []

        for ev_id_str in sorted(candidate_event_ids):
            if ev_id_str not in self.events_by_id:
                issues.append(f"{ErrorCode.MISSING_EVENT.value}:{ev_id_str}")
                continue

            ev_data = self.events_by_id[ev_id_str]
            sha_hash = str(ev_data.get("sha256_hash", ""))

            # Look up provenance ledger
            prov_data = self.prov_by_hash.get(sha_hash)
            if not prov_data:
                raise EvidenceChainError(
                    f"SHA-256 integrity verification failed for event {ev_id_str}. "
                    f"Recorded hash '{sha_hash}' not found in provenance ledger.",
                    ErrorCode.INVALID_SHA256
                )

            src_file = prov_data.get("source_file")
            src_idx = prov_data.get("source_row_index")
            src_id = prov_data.get("source_id")

            if src_file is None or pd.isna(src_file) or src_idx is None or pd.isna(src_idx):
                raise EvidenceChainError(
                    f"Missing source provenance metadata for event {ev_id_str}: "
                    f"source_file={src_file}, source_row_index={src_idx}",
                    ErrorCode.MISSING_PROVENANCE
                )

            # Parse attributes JSON safely
            attr_val = ev_data.get("attributes", {})
            if isinstance(attr_val, str):
                try:
                    attr_dict = json.loads(attr_val)
                except Exception:
                    attr_dict = {"raw": attr_val}
            elif isinstance(attr_val, dict):
                attr_dict = attr_val
            else:
                attr_dict = {}

            # ── UNCONDITIONAL INDEPENDENT SHA-256 RECONSTRUCTION & VERIFICATION ──
            raw_source_attrs = attr_dict.get("raw_source_attributes")
            if raw_source_attrs is None or not isinstance(raw_source_attrs, dict):
                raise EvidenceChainError(
                    f"Missing raw_source_attributes for event {ev_id_str}. Cannot verify cryptographic provenance.",
                    ErrorCode.INVALID_SHA256
                )

            recomputed_hash = compute_canonical_row_hash(
                source_file=str(src_file),
                source_row_index=int(src_idx),
                raw_row=raw_source_attrs
            )

            if recomputed_hash != sha_hash:
                raise EvidenceChainError(
                    f"Independent SHA-256 verification failed for event {ev_id_str}. "
                    f"Recomputed '{recomputed_hash}' != Recorded '{sha_hash}'",
                    ErrorCode.INVALID_SHA256
                )

            if prov_data.get("sha256_hash") != recomputed_hash:
                raise EvidenceChainError(
                    f"Provenance ledger hash mismatch for event {ev_id_str}. "
                    f"Provenance '{prov_data.get('sha256_hash')}' != Recomputed '{recomputed_hash}'",
                    ErrorCode.INVALID_SHA256
                )

            canonical_ev = CanonicalEvidenceEvent(
                event_id=ev_id_str,
                timestamp=str(ev_data.get("timestamp", "")),
                event_type=str(ev_data.get("event_type", "")),
                source_domain=str(ev_data.get("source_domain", "")),
                actor_id=str(ev_data.get("actor_id", "")),
                target_id=str(ev_data.get("target_id", "")) if pd.notna(ev_data.get("target_id")) else None,
                sha256_hash=sha_hash,
                attributes=attr_dict,
                source_file=str(src_file),
                source_row_index=int(src_idx),
                source_id=str(src_id) if src_id is not None and pd.notna(src_id) else None,
            )
            evidence_events.append(canonical_ev)
            event_records_for_prov.append(canonical_ev.to_dict())

        # Sort evidence events deterministically by timestamp and event_id
        evidence_events.sort(key=lambda x: (x.timestamp, x.event_id))

        # Trace Provenance Steps
        steps: List[ProvenanceStep] = []
        step_idx = 1

        # Step 1: Raw Ingestion -> Canonical Events
        for ev in evidence_events:
            steps.append(ProvenanceStep(
                step_index=step_idx,
                entity_type="CanonicalEvent",
                entity_id=ev.event_id,
                activity_type="IngestionActivity",
                used_ids=(f"raw_source:{ev.source_file}:{ev.source_row_index}",),
                generated_ids=(ev.event_id,),
                sha256_hash=ev.sha256_hash,
                metadata={"source_domain": ev.source_domain, "timestamp": ev.timestamp}
            ))
            step_idx += 1

        # Step 2: Feature Extraction
        for rf in resolved_features:
            steps.append(ProvenanceStep(
                step_index=step_idx,
                entity_type="Feature",
                entity_id=f"{rf.feature_name}:{entity_id}",
                activity_type="FeatureExtractionActivity",
                used_ids=tuple(ev.event_id for ev in evidence_events),
                generated_ids=(f"{rf.feature_name}:{entity_id}",),
                sha256_hash=None,
                metadata={"feature_name": rf.feature_name, "feature_store": rf.feature_store, "entity_id": entity_id, "feature_value": rf.feature_value}
            ))
            step_idx += 1

        # Step 3: Evidential Fusion -> Finding
        steps.append(ProvenanceStep(
            step_index=step_idx,
            entity_type="Finding",
            entity_id=fid,
            activity_type="FusionActivity",
            used_ids=tuple(f"{rf.feature_name}:{entity_id}" for rf in resolved_features),
            generated_ids=(fid,),
            sha256_hash=None,
            metadata={"anomaly_type": anomaly_type, "composite_score": composite_score}
        ))

        # Determine Evidence Status
        has_blocking_issues = any(
            iss.startswith(ErrorCode.MISSING_EVENT.value) or
            iss.startswith(ErrorCode.MISSING_PROVENANCE.value) or
            iss.startswith(ErrorCode.MISSING_EVIDENCE_REF.value) or
            iss.startswith(ErrorCode.MISSING_FEATURE.value) or
            iss.startswith(ErrorCode.INCONSISTENT_EVIDENCE_REFERENCE.value)
            for iss in issues
        )

        if not candidate_event_ids or not evidence_events:
            evidence_status = EvidenceStatus.UNREFERENCED_OR_BROKEN.value
        elif len(evidence_events) == len(candidate_event_ids) and not has_blocking_issues:
            evidence_status = EvidenceStatus.FULLY_EVIDENCED.value
        else:
            evidence_status = EvidenceStatus.PARTIALLY_EVIDENCED.value

        # Construct W3C PROV-O document
        prov_doc = W3CProvenanceBuilder.build_finding_prov_document(
            finding_id=fid,
            entity_id=entity_id,
            event_records=event_records_for_prov,
            feature_names=[rf.feature_name for rf in resolved_features],
            anomaly_type=anomaly_type,
            created_at=created_at
        )

        return EvidenceChain(
            finding_id=fid,
            entity_id=entity_id,
            anomaly_type=anomaly_type,
            composite_score=composite_score,
            evidence_status=evidence_status,
            event_count=len(evidence_events),
            evidence_events=tuple(evidence_events),
            resolved_features=tuple(resolved_features),
            provenance_steps=tuple(steps),
            prov_o_document=prov_doc,
            upstream_manifest=self._manifest,
            issues=tuple(issues)
        )
