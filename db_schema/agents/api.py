"""
FastAPI app for the agentic layer, separate from the read-only data
API in api/main.py so agent runs (which cost tokens / take longer /
can fail) never risk that endpoint's stability.

Run from db_schema/:

    pip install -r agents/requirements-agents.txt
    uvicorn agents.api:app --reload --port 8001

Then open http://127.0.0.1:8001/docs

To call this from the SAME app as the data API instead of running it
separately, in api/main.py add:

    from agents.api import router as agents_router
    app.include_router(agents_router)
"""

import os
from pathlib import Path
from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from agents.common.tool_runner import AgentToolError
from agents.land_records_land_use import agent as land_records_agent
from agents.land_records_land_use.schemas import (
    LandRecordsLandUseRecord,
    LandRecordsLandUseRequest,
)
from agents.ownership_title import agent as ownership_title_agent
from agents.ownership_title.schemas import (
    OwnershipTitleRecord,
    OwnershipTitleRequest,
)
from agents.property_identification import agent as property_identification_agent
from agents.property_identification.schemas import (
    CanonicalPropertyRecord,
    PropertyIdentificationRequest,
)
from agents.registration_encumbrance import agent as registration_encumbrance_agent
from agents.registration_encumbrance.schemas import (
    RegistrationEncumbranceRecord,
    RegistrationEncumbranceRequest,
)
from agents.project_regulatory_compliance import agent as project_regulatory_compliance_agent
from agents.project_regulatory_compliance.schemas import (
    ProjectRegulatoryComplianceRecord,
    ProjectRegulatoryComplianceRequest,
)

router = APIRouter(prefix="/agents", tags=["agents"])


@router.post("/property-identification", response_model=CanonicalPropertyRecord)
def identify_property(request: PropertyIdentificationRequest):
    try:
        return property_identification_agent.run(request)
    except AgentToolError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.post("/ownership-title", response_model=OwnershipTitleRecord)
def determine_ownership_title(request: OwnershipTitleRequest):
    try:
        return ownership_title_agent.run(request)
    except AgentToolError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.post("/land-records-land-use", response_model=LandRecordsLandUseRecord)
def verify_land_records_land_use(request: LandRecordsLandUseRequest):
    try:
        return land_records_agent.run(request)
    except AgentToolError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.post("/registration-encumbrance", response_model=RegistrationEncumbranceRecord)
def investigate_registration_encumbrance(request: RegistrationEncumbranceRequest):
    try:
        return registration_encumbrance_agent.run(request)
    except AgentToolError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.post("/project-regulatory-compliance", response_model=ProjectRegulatoryComplianceRecord)
def audit_project_regulatory_compliance(request: ProjectRegulatoryComplianceRequest):
    try:
        return project_regulatory_compliance_agent.run(request)
    except AgentToolError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


# Standalone app, for running this file directly with uvicorn.
app = FastAPI(
    title="UP-RERA Agentic Layer",
    description="Subagent endpoints over the UP-RERA property due-diligence database.",
    version="0.1.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)
app.include_router(router)


@app.get("/health")
def health():
    return {"status": "ok"}


DASHBOARD_FILE = Path(__file__).parent / "dashboard.html"


@app.get("/", response_class=HTMLResponse)
@app.get("/dashboard", response_class=HTMLResponse)
def get_dashboard():
    if DASHBOARD_FILE.exists():
        return HTMLResponse(content=DASHBOARD_FILE.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h2>Live Agent Dashboard HTML not found.</h2>", status_code=404)
