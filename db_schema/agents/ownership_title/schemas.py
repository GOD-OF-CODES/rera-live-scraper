import re
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, model_validator


class OwnershipTitleRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    # Flexible property input: can accept registration_number, project_id,
    # or a general query (project name, promoter name, khasra, plot, address),
    # along with available land records, mutation records, title documents, and registered deeds.
    project_id: Optional[int] = None
    registration_number: Optional[str] = None
    query: Optional[str] = None
    raw_query: Optional[str] = None
    address: Optional[str] = None
    project_name: Optional[str] = None
    promoter_name: Optional[str] = None
    khasra_number: Optional[str] = None
    plot_number: Optional[str] = None
    district_hint: Optional[str] = None
    land_records: Optional[list[dict]] = None
    mutation_records: Optional[list[dict]] = None
    title_documents: Optional[list[dict]] = None
    registered_deeds: Optional[list[dict]] = None
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
                for a in ["khasra", "khasra_no"]:
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
            if not mapped.get("title_documents"):
                for a in ["documents", "docs", "uploaded_documents"]:
                    if mapped.get(a) and isinstance(mapped[a], list):
                        mapped["title_documents"] = mapped[a]
                        break

            # If registration_number is found inside query string
            if not mapped.get("registration_number") and mapped.get("query"):
                m = re.search(r"\b(UPRERAPRJ\d+|PRJ\d+)\b", str(mapped["query"]), re.IGNORECASE)
                if m:
                    mapped["registration_number"] = m.group(1).upper()

            return mapped
        return data


class TitleChainLink(BaseModel):
    sequence: Optional[int] = None
    # 1-based position in the reconstructed chain, oldest first.
    from_owner: Optional[str] = None
    to_owner: Optional[str] = None
    transfer_type: Optional[str] = None
    # e.g. sale deed, gift deed, inheritance/mutation, lease, other -
    # whatever the source document/record actually says.
    transfer_date: Optional[str] = None
    document_reference: Optional[str] = None
    # project_document_id, document_name, or external source id this
    # link is drawn from - always traceable back to evidence.
    source: Optional[str] = None
    # 'document_processing' | 'rera_structured_fields' | 'external_mock'
    confidence: Optional[float] = None


class TitleGap(BaseModel):
    description: str
    between_sequence: Optional[list[int]] = None
    # e.g. [2, 3] - the chain link numbers the gap falls between.
    severity: Optional[str] = None
    # low | medium | high


class OwnershipConflict(BaseModel):
    description: str
    conflicting_sources: Optional[list[str]] = None
    fields_in_conflict: Optional[list[str]] = None


class OwnershipTitleRecord(BaseModel):
    match_status: str
    # resolved | partial | not_found
    project_id: Optional[int] = None
    registration_number: Optional[str] = None
    current_owner: Optional[str] = None
    previous_owners: Optional[list[str]] = None
    ownership_chain: Optional[list[TitleChainLink]] = None
    transfer_dates_types: Optional[list[dict]] = None
    # convenience flattened view of ownership_chain's
    # transfer_date/transfer_type pairs, for consumers that don't
    # want to walk the full chain objects.
    title_gaps: Optional[list[TitleGap]] = None
    conflicting_ownership_information: Optional[list[OwnershipConflict]] = None
    supporting_evidence: Optional[list[str]] = None
    # document references / URLs / external source ids the whole
    # result is grounded in.
    notes: Optional[str] = None


# JSON schema handed to Claude as the "submit_result" tool's
# input_schema. Kept in sync with OwnershipTitleRecord by hand - if
# you add/change a field above, update this too.
SUBMIT_RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "match_status": {
            "type": "string",
            "enum": ["resolved", "partial", "not_found"],
        },
        "project_id": {"type": ["integer", "null"]},
        "registration_number": {"type": ["string", "null"]},
        "current_owner": {"type": ["string", "null"]},
        "previous_owners": {"type": ["array", "null"], "items": {"type": "string"}},
        "ownership_chain": {
            "type": ["array", "null"],
            "items": {
                "type": "object",
                "properties": {
                    "sequence": {"type": ["integer", "null"]},
                    "from_owner": {"type": ["string", "null"]},
                    "to_owner": {"type": ["string", "null"]},
                    "transfer_type": {"type": ["string", "null"]},
                    "transfer_date": {"type": ["string", "null"]},
                    "document_reference": {"type": ["string", "null"]},
                    "source": {"type": ["string", "null"]},
                    "confidence": {"type": ["number", "null"]},
                },
            },
        },
        "transfer_dates_types": {"type": ["array", "null"]},
        "title_gaps": {
            "type": ["array", "null"],
            "items": {
                "type": "object",
                "properties": {
                    "description": {"type": "string"},
                    "between_sequence": {
                        "type": ["array", "null"],
                        "items": {"type": "integer"},
                    },
                    "severity": {"type": ["string", "null"]},
                },
                "required": ["description"],
            },
        },
        "conflicting_ownership_information": {
            "type": ["array", "null"],
            "items": {
                "type": "object",
                "properties": {
                    "description": {"type": "string"},
                    "conflicting_sources": {
                        "type": ["array", "null"],
                        "items": {"type": "string"},
                    },
                    "fields_in_conflict": {
                        "type": ["array", "null"],
                        "items": {"type": "string"},
                    },
                },
                "required": ["description"],
            },
        },
        "supporting_evidence": {"type": ["array", "null"], "items": {"type": "string"}},
        "notes": {"type": ["string", "null"]},
    },
    "required": ["match_status", "current_owner"],
}
