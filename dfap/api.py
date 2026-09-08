# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research

import json
import os
from typing import Dict, Any, Optional
from fastapi import FastAPI, HTTPException, Query
import pandas as pd

from dfap.schemas import IngestionRequest, IngestionResponse
from dfap.pipeline import DFAPPipeline

app = FastAPI(
    title="DFAP WP1 - Data & Entity Research API Interface",
    description="Research interface for DFAP WP1 execution, contract inspection, and audit ledger retrieval.",
    version="1.0.0"
)

from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from dfap.api_workspace import workspace_router

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(workspace_router)


@app.get("/api")
def read_root():
    return {
        "title": "Digital Footprint Fusion & Analysis Platform (DFAP) - WP1",
        "author": "Sam Roger X",
        "component": "DFAP WP1 - Data & Entity Research",
        "version": "1.0.0",
        "docs_url": "/docs"
    }


FRONTEND_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "frontend", "chandiger hackathon", "dfap-prototype", "frontend")
)

if os.path.exists(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

    assets_dir = os.path.join(FRONTEND_DIR, "assets")
    if os.path.exists(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.api_route("/", methods=["GET", "HEAD"])
    def serve_frontend_root():
        index_path = os.path.join(FRONTEND_DIR, "index.html")
        if os.path.exists(index_path):
            return FileResponse(index_path)
        return read_root()

    @app.api_route("/index.html", methods=["GET", "HEAD"])
    def serve_frontend_index():
        return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))

    @app.api_route("/style.css", methods=["GET", "HEAD"])
    def serve_root_style():
        return FileResponse(os.path.join(FRONTEND_DIR, "style.css"), media_type="text/css")

    @app.api_route("/app.js", methods=["GET", "HEAD"])
    def serve_root_app():
        return FileResponse(os.path.join(FRONTEND_DIR, "app.js"), media_type="application/javascript")

    @app.api_route("/i18n.js", methods=["GET", "HEAD"])
    def serve_root_i18n():
        return FileResponse(os.path.join(FRONTEND_DIR, "i18n.js"), media_type="application/javascript")

    @app.api_route("/3d-force-graph.min.js", methods=["GET", "HEAD"])
    def serve_3d_force_graph():
        return FileResponse(os.path.join(FRONTEND_DIR, "3d-force-graph.min.js"), media_type="application/javascript")


@app.get("/api/v1/health")
def health_check():
    return {"status": "HEALTHY", "service": "DFAP WP1 Pipeline API Interface"}


@app.post("/api/v1/ingest", response_model=IngestionResponse)
def trigger_ingestion(request: IngestionRequest):
    """
    Triggers batch CSV ingestion, cryptographic provenance hashing,
    Splink entity deduplication, and Parquet contract generation.
    """
    try:
        pipeline = DFAPPipeline(
            confirmed_threshold=request.confirmed_threshold,
            possible_threshold=request.possible_threshold
        )
        results = pipeline.run(raw_data_dir=request.raw_data_dir, output_dir=request.output_dir)
        return IngestionResponse(
            status=results["status"],
            events_processed=results["canonical_events"],
            entities_resolved=results["resolved_entities"],
            provenance_records=results["provenance_records"],
            matches_audited=results["candidate_matches"],
            canonical_events_path=results["canonical_events_path"],
            resolved_entities_path=results["resolved_entities_path"],
            provenance_ledger_path=results["provenance_ledger_path"],
            entity_matches_path=results["entity_matches_path"],
            manifest_path=results["manifest_path"],
            execution_timestamp=results["execution_timestamp"]
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Pipeline execution error: {str(e)}")


@app.get("/api/v1/entities")
def get_resolved_entities(
    output_dir: str = Query("./output", description="Directory path of exported parquet contracts"),
    limit: int = Query(100, ge=1, le=1000)
):
    """Queries resolved_entities.parquet contract."""
    file_path = os.path.join(output_dir, "resolved_entities.parquet")
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"Contract output not found: {file_path}")
    df = pd.read_parquet(file_path)
    return df.head(limit).to_dict(orient="records")


@app.get("/api/v1/events")
def get_canonical_events(
    output_dir: str = Query("./output", description="Directory path of exported parquet contracts"),
    limit: int = Query(100, ge=1, le=1000)
):
    """Queries canonical_events.parquet contract."""
    file_path = os.path.join(output_dir, "canonical_events.parquet")
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"Contract output not found: {file_path}")
    df = pd.read_parquet(file_path)
    return df.head(limit).to_dict(orient="records")


@app.get("/api/v1/provenance")
def get_provenance_ledger(
    output_dir: str = Query("./output", description="Directory path of exported parquet contracts"),
    limit: int = Query(100, ge=1, le=1000)
):
    """Queries provenance_ledger.parquet contract."""
    file_path = os.path.join(output_dir, "provenance_ledger.parquet")
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"Contract output not found: {file_path}")
    df = pd.read_parquet(file_path)
    return df.head(limit).to_dict(orient="records")


@app.get("/api/v1/matches")
def get_entity_matches(
    output_dir: str = Query("./output", description="Directory path of exported parquet contracts"),
    limit: int = Query(100, ge=1, le=1000)
):
    """Queries entity_matches.parquet audit artifact."""
    file_path = os.path.join(output_dir, "entity_matches.parquet")
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"Audit artifact not found: {file_path}")
    df = pd.read_parquet(file_path)
    return df.head(limit).to_dict(orient="records")


@app.get("/api/v1/manifest")
def get_pipeline_manifest(
    output_dir: str = Query("./output", description="Directory path of exported parquet contracts")
):
    """Queries wp1_manifest.json execution report."""
    file_path = os.path.join(output_dir, "wp1_manifest.json")
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"Manifest not found: {file_path}")
    with open(file_path, "r", encoding="utf-8") as fh:
        return json.load(fh)


# ── WORK PACKAGE 4 (MEMBER 4) API ROUTES ──────────────────────────────────────

from dfap.wp4.service import WP4Service
from dfap.wp4.contracts import (
    EvidenceChainError,
    WorkspaceError,
    UpstreamContractError,
    UpstreamIntegrityError,
)

_wp4_service = None

def get_wp4_service() -> WP4Service:
    global _wp4_service
    if _wp4_service is None:
        _wp4_service = WP4Service(data_dir="./output", verify_frozen_manifest=True)
    return _wp4_service


@app.get("/api/v1/wp4/integrity")
def wp4_verify_integrity():
    """Verifies existence, schemas, and SHA-256 integrity of all frozen upstream contracts."""
    try:
        service = get_wp4_service()
        return service.verify_upstream_integrity()
    except (UpstreamIntegrityError, UpstreamContractError) as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/findings")
def list_findings():
    """Lists all available findings from the authoritative Member 3 findings store."""
    try:
        service = get_wp4_service()
        return service.list_findings()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/findings/{finding_id}")
def get_finding(finding_id: str):
    """Retrieves metadata for a specific finding."""
    try:
        service = get_wp4_service()
        return service.get_finding(finding_id)
    except EvidenceChainError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/api/v1/findings/{finding_id}/evidence")
def get_evidence_chain(finding_id: str):
    """Resolves full evidence chain, feature lineage, source row provenance, and W3C PROV-O document."""
    try:
        service = get_wp4_service()
        return service.get_evidence_chain(finding_id)
    except EvidenceChainError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/timeline/{entity_id}")
def get_timeline(
    entity_id: str,
    start: Optional[str] = Query(None, description="Start ISO timestamp (inclusive)"),
    end: Optional[str] = Query(None, description="End ISO timestamp (exclusive)")
):
    """Queries canonical events for an entity within a strict [start, end) half-open window."""
    try:
        service = get_wp4_service()
        return service.get_entity_timeline(entity_id=entity_id, start=start, end=end)
    except WorkspaceError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/v1/subgraph/{entity_id}")
def get_subgraph(
    entity_id: str,
    hops: int = Query(2, ge=0, le=2, description="Bounded hop distance (0, 1, or 2)")
):
    """Extracts bounded 2-hop neighborhood subgraph for an entity."""
    try:
        service = get_wp4_service()
        return service.get_entity_subgraph(entity_id=entity_id, hops=hops)
    except WorkspaceError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/v1/subgraph/{entity_id}/cytoscape")
def get_cytoscape_subgraph(
    entity_id: str,
    hops: int = Query(2, ge=0, le=2, description="Bounded hop distance (0, 1, or 2)")
):
    """Extracts bounded subgraph in Cytoscape-compatible JSON payload format."""
    try:
        service = get_wp4_service()
        return service.get_cytoscape_payload(entity_id=entity_id, hops=hops)
    except WorkspaceError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/v1/workspace")
def get_workspace_state():
    """Retrieves current investigation workspace focus state."""
    service = get_wp4_service()
    return service.get_workspace_state()


@app.post("/api/v1/workspace")
def update_workspace_state(
    entity_id: Optional[str] = None,
    finding_id: Optional[str] = None,
    timeline_start: Optional[str] = None,
    timeline_end: Optional[str] = None,
):
    """Updates investigation workspace focus state."""
    try:
        service = get_wp4_service()
        return service.update_workspace_state(
            selected_entity_id=entity_id,
            selected_finding_id=finding_id,
            timeline_start=timeline_start,
            timeline_end=timeline_end,
        )
    except WorkspaceError as e:
        raise HTTPException(status_code=400, detail=str(e))
