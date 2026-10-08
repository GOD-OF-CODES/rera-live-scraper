import re
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, model_validator


class RegistrationEncumbranceRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    # Flexible property input: accepts registration_number, project_id,
    # or a general query (address, plot, khasra, project name, promoter),
    # along with available registration records, registered deeds, and encumbrance-related records.
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
    registration_records: Optional[list[dict]] = None
    registered_deeds: Optional[list[dict]] = None
    encumbrance_records: Optional[list[dict]] = None
    party_name_hint: Optional[str] = None
    encumbrance_type_hint: Optional[str] = None
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
            if not mapped.get("registered_deeds"):
                for a in ["deeds", "documents", "docs", "uploaded_documents"]:
                    if mapped.get(a) and isinstance(mapped[a], list):
                        mapped["registered_deeds"] = mapped[a]
                        break

            # If registration_number is found inside query string
            if not mapped.get("registration_number") and mapped.get("query"):
                m = re.search(r"\b(UPRERAPRJ\d+|PRJ\d+)\b", str(mapped["query"]), re.IGNORECASE)
                if m:
                    mapped["registration_number"] = m.group(1).upper()

            return mapped
        return data


class PartyDetail(BaseModel):
    name: str
    role: str
    # seller | buyer | mortgagor | mortgagee | allotting_authority | lender_bank | borrower | lessor | lessee
    id_or_pan_hint: Optional[str] = None


class DeedRegistrationDetail(BaseModel):
    deed_type: str
    # Master Lease Deed | Conveyance Deed | Agreement to Sell | Possession Memo | Sanction Order
    deed_number: Optional[str] = None
    registration_date: Optional[str] = None
    sub_registrar_office: Optional[str] = None
    book_volume_page: Optional[str] = None
    stamp_duty_inr: Optional[float] = None
    consideration_amount_inr: Optional[float] = None
    document_reference: Optional[str] = None


class RegisteredTransaction(BaseModel):
    sequence: Optional[int] = None
    transaction_id: Optional[str] = None
    deed_type: str
    # Sale Deed | Conveyance Deed | Mortgage Deed | Lease Deed | Development Agreement | Allotment Letter
    registration_number: Optional[str] = None
    registration_date: Optional[str] = None
    buyers: Optional[list[str]] = None
    sellers: Optional[list[str]] = None
    parties: Optional[list[PartyDetail]] = None
    deed_details: Optional[DeedRegistrationDetail] = None
    consideration_amount_inr: Optional[float] = None
    property_description: Optional[str] = None
    document_reference: Optional[str] = None


class EncumbranceClaim(BaseModel):
    claim_type: str
    # mortgage | charge | lien | court_attachment | statutory_liability | clear_declaration
    financial_institution: Optional[str] = None
    # Bank / Financial Institution / Creditor / Authority
    amount_inr: Optional[float] = None
    status: str
    # active | satisfied | discharged | unverified_claim | no_encumbrance_declared
    creation_date: Optional[str] = None
    satisfaction_date: Optional[str] = None
    details: str
    document_reference: Optional[str] = None


class BuyerSellerSummary(BaseModel):
    party_name: str
    role: str
    # Seller / Developer | Buyer / Allottee | Allotting Authority / Lessor | Lessee | Mortgagor | Mortgagee
    transaction_reference: Optional[str] = None
    id_or_pan_hint: Optional[str] = None


class RegistrationEncumbranceRecord(BaseModel):
    match_status: str
    # verified | encumbered | discrepancy_detected | not_found
    project_id: Optional[int] = None
    registration_number: Optional[str] = None
    project_name: Optional[str] = None
    promoter_name: Optional[str] = None
    transaction_timeline: Optional[list[RegisteredTransaction]] = None
    buyers_sellers: Optional[list[BuyerSellerSummary]] = None
    deed_registration_details: Optional[list[DeedRegistrationDetail]] = None
    mortgages_liens_charges_attachments: Optional[list[EncumbranceClaim]] = None
    encumbrances_and_charges: Optional[list[EncumbranceClaim]] = None
    encumbrance_free_status: bool = False
    status_summary: Optional[str] = None
    bank_accounts: Optional[list[dict]] = None
    # Escrow project bank accounts from project_bank_details
    discrepancies: Optional[list[dict]] = None
    supporting_evidence: Optional[list[str]] = None
    notes: Optional[str] = None

    @model_validator(mode="after")
    def sync_encumbrances(self):
        if self.mortgages_liens_charges_attachments and not self.encumbrances_and_charges:
            self.encumbrances_and_charges = self.mortgages_liens_charges_attachments
        elif self.encumbrances_and_charges and not self.mortgages_liens_charges_attachments:
            self.mortgages_liens_charges_attachments = self.encumbrances_and_charges
        return self


# JSON schema handed to Claude/Ollama as the submit tool's input_schema.
SUBMIT_RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "match_status": {
            "type": "string",
            "enum": ["verified", "encumbered", "discrepancy_detected", "not_found"],
        },
        "project_id": {"type": ["integer", "null"]},
        "registration_number": {"type": ["string", "null"]},
        "project_name": {"type": ["string", "null"]},
        "promoter_name": {"type": ["string", "null"]},
        "transaction_timeline": {
            "type": ["array", "null"],
            "items": {
                "type": "object",
                "properties": {
                    "sequence": {"type": ["integer", "null"]},
                    "transaction_id": {"type": ["string", "null"]},
                    "deed_type": {"type": "string"},
                    "registration_number": {"type": ["string", "null"]},
                    "registration_date": {"type": ["string", "null"]},
                    "buyers": {"type": ["array", "null"], "items": {"type": "string"}},
                    "sellers": {"type": ["array", "null"], "items": {"type": "string"}},
                    "consideration_amount_inr": {"type": ["number", "null"]},
                    "property_description": {"type": ["string", "null"]},
                    "document_reference": {"type": ["string", "null"]},
                },
                "required": ["deed_type"],
            },
        },
        "buyers_sellers": {
            "type": ["array", "null"],
            "items": {
                "type": "object",
                "properties": {
                    "party_name": {"type": "string"},
                    "role": {"type": "string"},
                    "transaction_reference": {"type": ["string", "null"]},
                },
                "required": ["party_name", "role"],
            },
        },
        "deed_registration_details": {
            "type": ["array", "null"],
            "items": {
                "type": "object",
                "properties": {
                    "deed_type": {"type": "string"},
                    "deed_number": {"type": ["string", "null"]},
                    "registration_date": {"type": ["string", "null"]},
                    "sub_registrar_office": {"type": ["string", "null"]},
                    "document_reference": {"type": ["string", "null"]},
                },
                "required": ["deed_type"],
            },
        },
        "mortgages_liens_charges_attachments": {
            "type": ["array", "null"],
            "items": {
                "type": "object",
                "properties": {
                    "claim_type": {"type": "string"},
                    "financial_institution": {"type": ["string", "null"]},
                    "amount_inr": {"type": ["number", "null"]},
                    "status": {"type": "string"},
                    "creation_date": {"type": ["string", "null"]},
                    "satisfaction_date": {"type": ["string", "null"]},
                    "details": {"type": "string"},
                    "document_reference": {"type": ["string", "null"]},
                },
                "required": ["claim_type", "status", "details"],
            },
        },
        "encumbrance_free_status": {"type": "boolean"},
        "status_summary": {"type": ["string", "null"]},
        "bank_accounts": {"type": ["array", "null"]},
        "discrepancies": {"type": ["array", "null"]},
        "supporting_evidence": {"type": ["array", "null"], "items": {"type": "string"}},
        "notes": {"type": ["string", "null"]},
    },
    "required": ["match_status", "encumbrance_free_status"],
}
