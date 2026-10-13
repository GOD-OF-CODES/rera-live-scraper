import re
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, model_validator


class ProjectRegulatoryComplianceRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    # Flexible property input: accepts registration_number, project_id,
    # or a general query (address, plot, khasra, project name, promoter),
    # along with available RERA records, regulatory documents, and planning documents.
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
    rera_records: Optional[list[dict]] = None
    regulatory_documents: Optional[list[dict]] = None
    planning_documents: Optional[list[dict]] = None
    promoter_name_hint: Optional[str] = None
    rera_project_id: Optional[str] = None
    authority_hint: Optional[str] = None
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
                for a in ["khasra", "khasra_no", "survey_number", "survey_no"]:
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
            if not mapped.get("regulatory_documents"):
                for a in ["documents", "docs", "uploaded_documents"]:
                    if mapped.get(a) and isinstance(mapped[a], list):
                        mapped["regulatory_documents"] = mapped[a]
                        break

            # If registration_number is found inside query string
            if not mapped.get("registration_number") and mapped.get("query"):
                m = re.search(r"\b(UPRERAPRJ\d+|PRJ\d+)\b", str(mapped["query"]), re.IGNORECASE)
                if m:
                    mapped["registration_number"] = m.group(1).upper()

            return mapped
        return data


class RegistrationStatusInfo(BaseModel):
    is_registered: bool
    registration_number: Optional[str] = None
    rera_project_id: Optional[str] = None
    status: str
    # registered_active | valid | expired | under_review | revoked | not_found
    registration_date: Optional[str] = None
    valid_until: Optional[str] = None
    approval_certificate_available: bool = False
    approval_certificate_name: Optional[str] = None
    approval_certificate_url: Optional[str] = None
    source_portal: str = "UP-RERA"


class PromoterDetails(BaseModel):
    promoter_id: Optional[int] = None
    name: str
    rera_promoter_id: Optional[str] = None
    promoter_type: Optional[str] = None
    # Authority | Private Limited | Limited Company | Partnership | Proprietorship | Individual
    verification_status: str = "verified"
    # verified | unverified | mismatch
    registered_office: Optional[str] = None


class ProjectBasicDetails(BaseModel):
    project_id: Optional[int] = None
    project_name: str
    project_type: Optional[str] = None
    # Residential | Commercial | Mixed | Plotted
    district: Optional[str] = None
    tehsil: Optional[str] = None
    total_area_sq_m: Optional[float] = None
    project_cost_lakhs: Optional[float] = None
    original_start_date: Optional[str] = None
    proposed_start_date: Optional[str] = None
    proposed_completion_date: Optional[str] = None
    sanctioning_competent_authority: Optional[str] = None


class ProjectProfessional(BaseModel):
    professional_type: str
    # architect | structural_engineer | chartered_accountant | contractor | project_manager
    name: Optional[str] = None
    license_number: Optional[str] = None
    contact: Optional[str] = None
    email: Optional[str] = None


class RegulatoryFinding(BaseModel):
    category: str
    # rera_registration | competent_authority_sanction | commencement_certificate | completion_certificate | escrow_account | environmental_fire_noc | development_progress
    authority_name: Optional[str] = None
    status: str
    # approved | compliant | pending | not_provided | non_compliant | under_scrutiny
    reference_number: Optional[str] = None
    details: str
    document_reference: Optional[str] = None


class ComplianceDiscrepancy(BaseModel):
    issue_type: str
    # missing_information | date_overrun | authority_mismatch | cost_variance | missing_statutory_account | missing_sanction
    severity: str
    # high | medium | low | info
    description: str
    field_or_document: Optional[str] = None
    recommended_action: Optional[str] = None


class ProjectRegulatoryComplianceRecord(BaseModel):
    compliance_status: str
    # compliant | partially_compliant | non_compliant | discrepancy_detected | not_found
    project_registration_status: RegistrationStatusInfo
    promoter_details: Optional[PromoterDetails] = None
    project_details: Optional[ProjectBasicDetails] = None
    regulatory_findings: list[RegulatoryFinding]
    discrepancies_and_missing_info: list[ComplianceDiscrepancy]
    professionals: Optional[list[ProjectProfessional]] = None
    escrow_bank_account: Optional[dict] = None
    supporting_evidence: list[str]
    notes: Optional[str] = None


# JSON schema handed to Claude/Ollama as the submit tool's input_schema.
SUBMIT_RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "compliance_status": {
            "type": "string",
            "enum": [
                "compliant",
                "partially_compliant",
                "non_compliant",
                "discrepancy_detected",
                "not_found",
            ],
        },
        "project_registration_status": {
            "type": "object",
            "properties": {
                "is_registered": {"type": "boolean"},
                "registration_number": {"type": ["string", "null"]},
                "rera_project_id": {"type": ["string", "null"]},
                "status": {"type": "string"},
                "registration_date": {"type": ["string", "null"]},
                "valid_until": {"type": ["string", "null"]},
                "approval_certificate_available": {"type": "boolean"},
                "approval_certificate_name": {"type": ["string", "null"]},
                "approval_certificate_url": {"type": ["string", "null"]},
                "source_portal": {"type": "string"},
            },
            "required": ["is_registered", "status"],
        },
        "promoter_details": {
            "type": ["object", "null"],
            "properties": {
                "promoter_id": {"type": ["integer", "null"]},
                "name": {"type": "string"},
                "rera_promoter_id": {"type": ["string", "null"]},
                "promoter_type": {"type": ["string", "null"]},
                "verification_status": {"type": "string"},
                "registered_office": {"type": ["string", "null"]},
            },
            "required": ["name"],
        },
        "project_details": {
            "type": ["object", "null"],
            "properties": {
                "project_id": {"type": ["integer", "null"]},
                "project_name": {"type": "string"},
                "project_type": {"type": ["string", "null"]},
                "district": {"type": ["string", "null"]},
                "tehsil": {"type": ["string", "null"]},
                "total_area_sq_m": {"type": ["number", "null"]},
                "project_cost_lakhs": {"type": ["number", "null"]},
                "original_start_date": {"type": ["string", "null"]},
                "proposed_start_date": {"type": ["string", "null"]},
                "proposed_completion_date": {"type": ["string", "null"]},
                "sanctioning_competent_authority": {"type": ["string", "null"]},
            },
            "required": ["project_name"],
        },
        "regulatory_findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "category": {"type": "string"},
                    "authority_name": {"type": ["string", "null"]},
                    "status": {"type": "string"},
                    "reference_number": {"type": ["string", "null"]},
                    "details": {"type": "string"},
                    "document_reference": {"type": ["string", "null"]},
                },
                "required": ["category", "status", "details"],
            },
        },
        "discrepancies_and_missing_info": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "issue_type": {"type": "string"},
                    "severity": {"type": "string"},
                    "description": {"type": "string"},
                    "field_or_document": {"type": ["string", "null"]},
                    "recommended_action": {"type": ["string", "null"]},
                },
                "required": ["issue_type", "severity", "description"],
            },
        },
        "professionals": {
            "type": ["array", "null"],
            "items": {
                "type": "object",
                "properties": {
                    "professional_type": {"type": "string"},
                    "name": {"type": ["string", "null"]},
                    "license_number": {"type": ["string", "null"]},
                    "contact": {"type": ["string", "null"]},
                    "email": {"type": ["string", "null"]},
                },
                "required": ["professional_type"],
            },
        },
        "escrow_bank_account": {"type": ["object", "null"]},
        "supporting_evidence": {
            "type": "array",
            "items": {"type": "string"},
        },
        "notes": {"type": ["string", "null"]},
    },
    "required": [
        "compliance_status",
        "project_registration_status",
        "regulatory_findings",
        "discrepancies_and_missing_info",
        "supporting_evidence",
    ],
}
