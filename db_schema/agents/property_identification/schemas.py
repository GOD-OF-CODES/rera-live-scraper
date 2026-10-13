from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, model_validator


class PropertyIdentificationRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    project_id: Optional[int] = None
    query: Optional[str] = None
    raw_query: Optional[str] = None
    address: Optional[str] = None
    plot_number: Optional[str] = None
    survey_number: Optional[str] = None
    khasra_number: Optional[str] = None
    property_number: Optional[str] = None
    registration_number: Optional[str] = None
    project_name: Optional[str] = None
    promoter_name: Optional[str] = None
    district_hint: Optional[str] = None
    tehsil_hint: Optional[str] = None
    khasra_details: Optional[list[dict]] = None
    plot_details: Optional[list[dict]] = None
    uploaded_document_name: Optional[str] = None
    uploaded_document_text: Optional[str] = None
    uploaded_documents: Optional[list[dict]] = None
    document_ids: Optional[list[int]] = None

    @model_validator(mode="before")
    @classmethod
    def pre_process_input(cls, data: Any) -> Any:
        if isinstance(data, str):
            clean = data.strip()
            return {"raw_query": clean, "query": clean}
        if isinstance(data, dict):
            mapped = dict(data)
            # Unpack upstream subagent output object if passed directly
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

            # Map common aliases from another system
            if not mapped.get("raw_query"):
                for a in ["query", "input", "text", "prompt", "q", "search"]:
                    if mapped.get(a):
                        mapped["raw_query"] = str(mapped[a])
                        break
            if not mapped.get("registration_number"):
                for a in ["reg_no", "rera_number", "rera_no", "reg_number", "rera_registration_number"]:
                    if mapped.get(a):
                        mapped["registration_number"] = str(mapped[a])
                        break
            if not mapped.get("khasra_number"):
                for a in ["khasra", "khasra_no"]:
                    if mapped.get(a):
                        mapped["khasra_number"] = str(mapped[a])
                        break
            if not mapped.get("plot_number"):
                for a in ["plot", "plot_no"]:
                    if mapped.get(a):
                        mapped["plot_number"] = str(mapped[a])
                        break
            if not mapped.get("survey_number"):
                for a in ["survey", "survey_no"]:
                    if mapped.get(a):
                        mapped["survey_number"] = str(mapped[a])
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
            return mapped
        return data

    @model_validator(mode="after")
    def populate_raw_query(self) -> "PropertyIdentificationRequest":
        """Ensure raw_query is populated from other fields if not provided directly."""
        if not self.raw_query and self.query:
            self.raw_query = self.query
        elif not self.raw_query:
            parts = []
            if self.registration_number:
                parts.append(self.registration_number)
            if self.project_name:
                parts.append(self.project_name)
            if self.promoter_name:
                parts.append(self.promoter_name)
            if self.address:
                parts.append(self.address)
            if self.plot_number:
                parts.append(f"Plot {self.plot_number}")
            if self.khasra_number:
                parts.append(f"Khasra {self.khasra_number}")
            if self.survey_number:
                parts.append(f"Survey {self.survey_number}")
            if self.property_number:
                parts.append(f"Property {self.property_number}")
            if self.project_id is not None:
                parts.append(str(self.project_id))
            if self.district_hint:
                parts.append(self.district_hint)
            self.raw_query = ", ".join(parts) if parts else "unspecified"
        return self


class MatchedIdentifiers(BaseModel):
    registration_number: Optional[str] = None
    rera_project_id: Optional[str] = None
    project_name: Optional[str] = None
    promoter_name: Optional[str] = None
    property_name_or_number: Optional[str] = None
    plot_number: Optional[str] = None
    khasra_number: Optional[str] = None
    survey_number: Optional[str] = None
    address: Optional[str] = None
    sector_or_locality: Optional[str] = None


class CanonicalLocation(BaseModel):
    address: Optional[str] = None
    sector_or_locality: Optional[str] = None
    city_or_authority: Optional[str] = None
    district: Optional[str] = None
    tehsil: Optional[str] = None
    state: str = "Uttar Pradesh"
    latitude: Optional[str] = None
    longitude: Optional[str] = None


class CanonicalPropertyRecord(BaseModel):
    match_status: str
    # exact | verified_external | fuzzy | ambiguous | not_found
    match_confidence: float
    # 0.0 - 1.0
    property_category: str = "rera_project_unit"
    # independent_plot_or_building | rera_project_unit | rera_plotted_colony | revenue_land_parcel
    project_id: Optional[int] = None
    # internal DB id - set when a project was resolved; None for independent municipal/revenue plots
    identifiers: MatchedIdentifiers
    location: CanonicalLocation
    total_area_sq_m: Optional[float] = None
    land_classification: Optional[str] = None
    owner_or_allottee: Optional[str] = None
    khasra_plot_details: Optional[list] = None
    matching_confidence_info: Optional[dict] = None
    source_record_type: str = "rera_database"
    # rera_database | official_land_records | uploaded_document_extraction | hybrid
    document_evidence: Optional[list[str]] = None
    supporting_evidence: Optional[list[str]] = None
    candidates_considered: Optional[list] = None
    notes: Optional[str] = None


# JSON schema handed to Claude/Ollama as the "submit_result" tool's input_schema.
SUBMIT_RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "match_status": {
            "type": "string",
            "enum": ["exact", "verified_external", "fuzzy", "ambiguous", "not_found"],
        },
        "match_confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "property_category": {
            "type": "string",
            "enum": [
                "independent_plot_or_building",
                "rera_project_unit",
                "rera_plotted_colony",
                "revenue_land_parcel",
            ],
        },
        "project_id": {"type": ["integer", "null"]},
        "identifiers": {
            "type": "object",
            "properties": {
                "registration_number": {"type": ["string", "null"]},
                "rera_project_id": {"type": ["string", "null"]},
                "project_name": {"type": ["string", "null"]},
                "promoter_name": {"type": ["string", "null"]},
                "property_name_or_number": {"type": ["string", "null"]},
                "plot_number": {"type": ["string", "null"]},
                "khasra_number": {"type": ["string", "null"]},
                "survey_number": {"type": ["string", "null"]},
                "address": {"type": ["string", "null"]},
                "sector_or_locality": {"type": ["string", "null"]},
            },
        },
        "location": {
            "type": "object",
            "properties": {
                "address": {"type": ["string", "null"]},
                "sector_or_locality": {"type": ["string", "null"]},
                "city_or_authority": {"type": ["string", "null"]},
                "district": {"type": ["string", "null"]},
                "tehsil": {"type": ["string", "null"]},
                "state": {"type": "string"},
                "latitude": {"type": ["string", "null"]},
                "longitude": {"type": ["string", "null"]},
            },
            "required": ["district"],
        },
        "total_area_sq_m": {"type": ["number", "null"]},
        "land_classification": {"type": ["string", "null"]},
        "owner_or_allottee": {"type": ["string", "null"]},
        "khasra_plot_details": {"type": ["array", "null"]},
        "source_record_type": {"type": "string"},
        "document_evidence": {"type": ["array", "null"], "items": {"type": "string"}},
        "candidates_considered": {"type": ["array", "null"]},
        "notes": {"type": ["string", "null"]},
    },
    "required": ["match_status", "match_confidence", "identifiers", "location"],
}
