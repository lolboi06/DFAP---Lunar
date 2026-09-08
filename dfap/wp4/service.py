# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: Unified WP4 Backend Service & Member 5 Secure Retrieval Interfaces

import os
import hashlib
from typing import Dict, List, Any, Optional
import pandas as pd

from dfap.wp4.contracts import (
    EvidenceChain,
    WorkspaceState,
    EvidenceChainError,
    WorkspaceError,
    UpstreamContractError,
    UpstreamIntegrityError,
    ErrorCode,
)
from dfap.wp4.evidence import EvidenceEngine
from dfap.wp4.workspace import InvestigationWorkspace
from dfap.wp4.timeline import TimelineService
from dfap.wp4.network import NetworkService


class WP4Service:
    """
    Unified Work Package 4 (Member 4) Service.
    Integrates M12 Evidence & Provenance Engine with M13 Investigation Workspace.
    Exposes strictly scoped, read-only, deterministic retrieval APIs for Member 5.
    """

    def __init__(self, data_dir: str = "output", verify_frozen_manifest: bool = True):
        self.data_dir = data_dir
        self.evidence_engine = EvidenceEngine(data_dir=data_dir, verify_frozen_manifest=verify_frozen_manifest)
        
        events_path = os.path.join(data_dir, "canonical_events.parquet")
        entities_path = os.path.join(data_dir, "resolved_entities.parquet")
        
        self.df_events = pd.read_parquet(events_path)
        self.df_entities = pd.read_parquet(entities_path)
        
        self.timeline_service = TimelineService(self.df_events, self.df_entities)
        self.network_service = NetworkService(events_path, entities_path)
        
        valid_entities = set(self.df_entities["canonical_entity_id"].dropna().astype(str).tolist())
        valid_findings = set(self.evidence_engine.findings_by_id.keys())
        self.workspace = InvestigationWorkspace(valid_entity_ids=valid_entities, valid_finding_ids=valid_findings)

    # ── MEMBER 5 READ-ONLY RETRIEVAL APIS ────────────────────────────────────────

    def verify_upstream_integrity(self) -> Dict[str, Any]:
        """
        Verifies existence, schema, and SHA-256 hashes of all frozen upstream contracts.
        Returns diagnostic manifest or raises UpstreamIntegrityError.
        """
        manifest = self.evidence_engine.upstream_manifest
        return {
            "status": "HEALTHY",
            "read_only": True,
            "artifact_count": len(manifest),
            "manifest": manifest,
        }

    def list_findings(self) -> List[Dict[str, Any]]:
        """Returns deterministic list of available findings."""
        return self.evidence_engine.list_findings()

    def get_finding(self, finding_id: str) -> Dict[str, Any]:
        """Returns metadata for a specific finding."""
        return self.evidence_engine.get_finding(finding_id)

    def get_evidence_chain(self, finding_id: str) -> Dict[str, Any]:
        """
        Resolves finding down to raw source provenance and W3C PROV-O model.
        Returns complete structured evidence chain.
        """
        chain = self.evidence_engine.get_evidence_chain(finding_id)
        return chain.to_dict()

    def get_events(self, event_ids: List[str]) -> List[Dict[str, Any]]:
        """Returns canonical event details for the given event_ids."""
        return self.evidence_engine.get_events(event_ids)

    def get_entity_timeline(
        self,
        entity_id: str,
        start: Optional[str] = None,
        end: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Extracts canonical event timeline for entity_id within [start, end) half-open window.
        """
        return self.timeline_service.get_entity_timeline(entity_id=entity_id, start=start, end=end)

    def get_entity_subgraph(self, entity_id: str, hops: int = 2) -> Dict[str, Any]:
        """
        Extracts bounded subgraph (0 <= hops <= 2) for entity_id with independent distance validation.
        """
        return self.network_service.get_entity_subgraph(entity_id=entity_id, hops=hops)

    def get_cytoscape_payload(self, entity_id: str, hops: int = 2) -> Dict[str, Any]:
        """
        Returns deterministic Cytoscape node/edge dictionary for entity subgraph.
        """
        sub = self.get_entity_subgraph(entity_id=entity_id, hops=hops)
        cy = self.network_service.to_cytoscape_payload(sub)
        return cy.to_dict()

    # ── WORKSPACE STATE OPERATIONS ───────────────────────────────────────────────

    def get_workspace_state(self) -> Dict[str, Any]:
        """Returns current workspace state dictionary."""
        return self.workspace.get_state().to_dict()

    def update_workspace_state(self, **kwargs) -> Dict[str, Any]:
        """Updates workspace state and returns updated state dictionary."""
        return self.workspace.update_state(**kwargs).to_dict()

    def reset_workspace_state(self) -> Dict[str, Any]:
        """Resets workspace state to empty default."""
        return self.workspace.reset_state().to_dict()
