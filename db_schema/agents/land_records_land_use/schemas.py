import re
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, model_validator


class LandRecordsLandUseRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    # Flexible property input: accepts registration_number, project_id,
    # or a general query (address, plot, khasra, project name, promoter),
    # along with available land records, cadastral information, zoning records, and planning documents.
    project_id: Optional[int] = None
    registration_number: Optional[str] = None
    query: Optional[str] = None
    raw_query: Optional[str] = None
    address: Optional[str] = None
    plot_number: Optional[str] = None
    khasra_number: Optional[str] = None
    project_name: Optional[str] = None
    promoter_name: Optional[str] = None
    district_hint: Optional[str] = None
    cadastral_survey_number: Optional[str] = None
    declared_land_use: Optional[str] = None
    land_records: Optional[list[dict]] = None
    cadastral_information: Optional[dict] = None
    zoning_records: Optional[list[dict]] = None
    planning_documents: Optional[list[dict]] = None
    uploaded_document_name: Optional[str] = None
    uploaded_document_text: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def pre_process_input(cls, data: Any) -> Any:
        if isinstance(data, str):
            clean = data.strip()
            mapped = {"query": clean, "raw_query": clean}
            m = re.search(r"\b(UPRERAPRJ\d+|PRJ\d+)\b", clean, re.IGNORECASE)
            if m:
                mapped["registration_number"] = m.group(1).upper()
            return mapped

        # Handle Pydantic model passed from another agent
        if hasattr(data, "model_dump"):
            data = data.model_dump()
        elif hasattr(data, "__dict__"):
            data = dict(data.__dict__)

        if isinstance(data, dict):
            mapped = dict(data)
            # Unpack upstream subagent output object (e.g. from Property Identification)
            if "identifiers" in mapped and isinstance(mapped["identifiers"], dict):
                ids = mapped["identifiers"]
                for k in ["registration_number", "project_name", "promoter_name", "khasra_number", "plot_number", "address"]:
                    if ids.get(k) and not mapped.get(k):
                        mapped[k] = ids[k]
            if "location" in mapped and isinstance(mapped["location"], dict):
                loc = mapped["location"]
                if loc.get("district") and not mapped.get("district_hint"):
                    mapped["district_hint"] = loc["district"]
                if loc.get("address") and not mapped.get("address"):
                    mapped["address"] = loc["address"]

            # Map aliases
            if not mapped.get("query"):
                for a in ["raw_query", "input", "text", "prompt", "q", "search"]:
                    if mapped.get(a):
                        mapped["query"] = str(mapped[a])
                        break
            if not mapped.get("registration_number"):
                for a in ["reg_no", "rera_number", "rera_no", "reg_number", "rera_registration_number"]:
                    if mapped.get(a):
                        mapped["registration_number"] = str(mapped[a])
                        break
            if not mapped.get("khasra_number"):
                for a in ["khasra", "khasra_no", "survey_number", "survey_no", "cadastral_survey_number"]:
                    if mapped.get(a):
                        mapped["khasra_number"] = str(mapped[a])
                        break
            if not mapped.get("plot_number"):
                for a in ["plot", "plot_no"]:
                    if mapped.get(a):
                        mapped["plot_number"] = str(mapped[a])
                        break
            if not mapped.get("project_name"):
                for a in ["project", "property_name", "name"]:
                    if mapped.get(a):
                        mapped["project_name"] = str(mapped[a])
                        break
            if not mapped.get("promoter_name"):
                for a in ["promoter", "developer", "builder"]:
                    if mapped.get(a):
                        mapped["promoter_name"] = str(mapped[a])
                        break
            if not mapped.get("district_hint"):
                for a in ["district", "city"]:
                    if mapped.get(a):
                        mapped["district_hint"] = str(mapped[a])
                        break
            if not mapped.get("uploaded_document_text"):
                for a in ["document_text", "doc_text", "document", "file_text"]:
                    if mapped.get(a):
                        mapped["uploaded_document_text"] = str(mapped[a])
                        break
            if not mapped.get("planning_documents"):
                for a in ["documents", "docs", "uploaded_documents"]:
                    if mapped.get(a) and isinstance(mapped[a], list):
                        mapped["planning_documents"] = mapped[a]
                        break

            # If registration_number is found inside query string
            if not mapped.get("registration_number") and mapped.get("query"):
                m = re.search(r"\b(UPRERAPRJ\d+|PRJ\d+)\b", str(mapped["query"]), re.IGNORECASE)
                if m:
                    mapped["registration_number"] = m.group(1).upper()

            return mapped
        return data


class KhasraSurveyDetail(BaseModel):
    khasra_number: Optional[str] = None
    plot_number: Optional[str] = None
    village: Optional[str] = None
    tehsil: Optional[str] = None
    area_sq_m: Optional[float] = None
    record_source: Optional[str] = None
    possession_status: Optional[str] = None


class LandUseZoningStatus(BaseModel):
    master_plan_zone: Optional[str] = None
    permitted_land_use: Optional[str] = None
    conforming_use: Optional[bool] = None
    conversion_status: Optional[str] = None


class RestrictionPermission(BaseModel):
    category: str
    status: str
    details: str
    document_reference: Optional[str] = None


class LandDiscrepancy(BaseModel):
    discrepancy_type: str
    severity: str
    description: str
    declared_value: Optional[str] = None
    verified_value: Optional[str] = None


class LandRecordsLandUseRecord(BaseModel):
    match_status: str
    # verified | partial | discrepancy_detected | not_found
    project_id: Optional[int] = None
    registration_number: Optional[str] = None
    verified_land_area_sq_m: Optional[float] = None
    survey_khasra_details: Optional[list[KhasraSurveyDetail]] = None
    land_classification: Optional[str] = None
    # e.g. "Converted Non-Agricultural (Section 143/80 UP Revenue Code)", "Urban Residential Abadi", "Commercial/Mixed Development"
    land_use_zoning_status: Optional[LandUseZoningStatus] = None
    restrictions_permissions: Optional[list[RestrictionPermission]] = None
    discrepancies: Optional[list[LandDiscrepancy]] = None
    supporting_evidence: Optional[list[str]] = None
    notes: Optional[str] = None


# JSON schema handed to Claude/Ollama as the submit tool's input_schema.
SUBMIT_RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "match_status": {
            "type": "string",
            "enum": ["verified", "partial", "discrepancy_detected", "not_found"],
        },
        "project_id": {"type": ["integer", "null"]},
        "registration_number": {"type": ["string", "null"]},
        "verified_land_area_sq_m": {"type": ["number", "null"]},
        "survey_khasra_details": {
            "type": ["array", "null"],
            "items": {
                "type": "object",
                "properties": {
                    "khasra_number": {"type": ["string", "null"]},
                    "plot_number": {"type": ["string", "null"]},
                    "village": {"type": ["string", "null"]},
                    "tehsil": {"type": ["string", "null"]},
                    "area_sq_m": {"type": ["number", "null"]},
                    "record_source": {"type": ["string", "null"]},
                    "possession_status": {"type": ["string", "null"]},
                },
            },
        },
        "land_classification": {"type": ["string", "null"]},
        "land_use_zoning_status": {
            "type": ["object", "null"],
            "properties": {
                "master_plan_zone": {"type": ["string", "null"]},
                "permitted_land_use": {"type": ["string", "null"]},
                "conforming_use": {"type": ["boolean", "null"]},
                "conversion_status": {"type": ["string", "null"]},
            },
        },
        "restrictions_permissions": {
            "type": ["array", "null"],
            "items": {
                "type": "object",
                "properties": {
                    "category": {"type": "string"},
                    "status": {"type": "string"},
                    "details": {"type": "string"},
                    "document_reference": {"type": ["string", "null"]},
                },
                "required": ["category", "status", "details"],
            },
        },
        "discrepancies": {
            "type": ["array", "null"],
            "items": {
                "type": "object",
                "properties": {
                    "discrepancy_type": {"type": "string"},
                    "severity": {"type": "string"},
                    "description": {"type": "string"},
                    "declared_value": {"type": ["string", "null"]},
                    "verified_value": {"type": ["string", "null"]},
                },
                "required": ["discrepancy_type", "severity", "description"],
            },
        },
        "supporting_evidence": {"type": ["array", "null"], "items": {"type": "string"}},
        "notes": {"type": ["string", "null"]},
    },
    "required": ["match_status", "verified_land_area_sq_m", "land_classification"],
}
