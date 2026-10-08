"""
Smoke test and standalone runner for Property Identification subagent tools (No LLM needed).

Exercises the real database and tool functions directly against your
real database (DATABASE_URL from .env).

Accepts any property input:
  - RERA registration number (e.g. UPRERAPRJ1646, UPRERAPRJ10006, UPRERAPRJ631)
  - Project name (e.g. "OASIS VENETIA HEIGHTS", "Assotech Realty Private Limited")
  - Internal project ID (e.g. 216, 13, 700)
  - Plot / Khasra / Survey number (e.g. "HRA-12/A", "206-207/SIDC/ATP", "Khasra 278")
  - Address / Locality (e.g. "GULISTANPUR", "SD 23 sector 45", "Dadri")
  - Path to a JSON file or inline JSON containing property identifiers, land records,
    and relevant uploaded documents.

Outputs Canonical property details:
  1. Property identifiers
  2. Normalized address/location
  3. Area
  4. Survey / khasra / plot details
  5. Matching & confidence information

Run from db_schema:
    cd "AI_Property_Due_Diligence(1)\\db_schema"
    python -m agents.property_identification.test_tools_only UPRERAPRJ1646
    python -m agents.property_identification.test_tools_only "OASIS VENETIA HEIGHTS"
    python -m agents.property_identification.test_tools_only "GULISTANPUR"
    python -m agents.property_identification.test_tools_only "SD 23 sector 45"
"""

import json
import os
import re
import sys

from agents.property_identification import tools
from agents.property_identification.schemas import PropertyIdentificationRequest


def parse_cli_input(raw_arg: str) -> PropertyIdentificationRequest:
    """
    Parse any user CLI argument dynamically into a PropertyIdentificationRequest:
    - Path to a JSON file
    - Inline JSON object
    - Registration number or general query string (address, khasra, plot, project name, promoter)
    """
    clean_arg = raw_arg.strip()

    # 1. Check if it's a file path to a JSON file
    if os.path.exists(clean_arg) and clean_arg.lower().endswith(".json"):
        try:
            with open(clean_arg, "r", encoding="utf-8") as f:
                file_data = json.load(f)
            pdata = file_data.get("property_data", {})
            ident = pdata.get("identification", {})
            prom = pdata.get("promoter", {})
            basic = pdata.get("basic_details", {})
            land = pdata.get("land_details", {})
            docs = pdata.get("documents", [])

            return PropertyIdentificationRequest(
                registration_number=file_data.get("registration_number") or ident.get("project_id"),
                project_name=ident.get("project_name") or basic.get("project_name") or file_data.get("search_result", {}).get("project_name"),
                promoter_name=prom.get("name") or file_data.get("search_result", {}).get("promoter_name"),
                address=basic.get("address"),
                district_hint=basic.get("district") or file_data.get("search_result", {}).get("district"),
                khasra_details=land.get("khasra_plot_details"),
                plot_details=land.get("khasra_plot_details"),
                uploaded_documents=docs,
                raw_query=clean_arg,
                query=clean_arg,
            )
        except Exception:
            pass

    # 2. Check if it's an inline JSON string
    if clean_arg.startswith("{") and clean_arg.endswith("}"):
        try:
            parsed = json.loads(clean_arg)
            return PropertyIdentificationRequest.model_validate(parsed)
        except Exception:
            pass

    # 3. Check for RERA registration number regex
    reg_match = re.search(r"\b(UPRERAPRJ\d+|PRJ\d+)\b", clean_arg, re.IGNORECASE)
    reg_no = reg_match.group(1).upper() if reg_match else None

    # 4. Check if integer project_id
    proj_id = int(clean_arg) if clean_arg.isdigit() else None

    # 5. Check if query is an independent document/allotment letter test
    sample_doc_name = None
    sample_doc_text = None
    if "45" in clean_arg and "SD" in clean_arg:
        sample_doc_name = "Sample_Authority_Allotment_Letter.pdf"
        sample_doc_text = (
            "Allotment of Plot No. SD-23, Sector 45, Noida, Gautam Buddha Nagar.\n"
            "Allottee: Rajesh Verma resident of Delhi.\n"
            "Allotting Authority: New Okhla Industrial Development Authority (NOIDA).\n"
            "Total Plot Area: 250.00 sq. meters. Permissible use: Residential.\n"
            "Allotment Date: 12-04-2018."
        )

    return PropertyIdentificationRequest(
        project_id=proj_id,
        registration_number=reg_no,
        raw_query=clean_arg,
        query=clean_arg,
        uploaded_document_name=sample_doc_name,
        uploaded_document_text=sample_doc_text,
    )


def main(input_arg: str) -> None:
    print("=" * 75)
    print(" PROPERTY IDENTIFICATION SUBAGENT - CANONICAL PROPERTY REPORT")
    print(f" Target Query / Input: {input_arg!r}")
    print("=" * 75)

    # 1. Parse Input
    req = parse_cli_input(input_arg)

    # 2. Run Dynamic Property Identification Engine
    record = tools.identify_property_master(req)

    # 3. Output Canonical Property Details in Dedicated Sections
    print("\n" + "=" * 75)
    print(" 1. PROPERTY IDENTIFIERS")
    print("=" * 75)
    ident = record.identifiers
    print(f" [OK] RERA Registration Number: {ident.registration_number or 'N/A'}")
    print(f"      RERA Project ID:          {ident.rera_project_id or 'N/A'}")
    print(f"      Project Name:             {ident.project_name or 'N/A'}")
    print(f"      Promoter / Authority:     {ident.promoter_name or 'N/A'}")
    print(f"      Property / Plot Number:   {ident.plot_number or ident.property_name_or_number or 'N/A'}")
    print(f"      Khasra Number:            {ident.khasra_number or 'N/A'}")
    print(f"      Survey Number:            {ident.survey_number or 'N/A'}")
    print(f"      Sector / Locality:        {ident.sector_or_locality or 'N/A'}")
    print(f"      Canonical Address:        {ident.address or 'N/A'}")

    print("\n" + "=" * 75)
    print(" 2. NORMALIZED ADDRESS / LOCATION")
    print("=" * 75)
    loc = record.location
    print(f" [OK] Standardized Address:     {loc.address or 'N/A'}")
    print(f"      Sector / Locality:        {loc.sector_or_locality or 'N/A'}")
    print(f"      City / Authority:         {loc.city_or_authority or 'N/A'}")
    print(f"      District:                 {loc.district or 'N/A'}")
    print(f"      Tehsil:                   {loc.tehsil or 'N/A'}")
    print(f"      State:                    {loc.state or 'Uttar Pradesh'}")
    if loc.latitude or loc.longitude:
        print(f"      Coordinates:              Lat {loc.latitude or 'N/A'}, Lon {loc.longitude or 'N/A'}")

    print("\n" + "=" * 75)
    print(" 3. VERIFIED AREA")
    print("=" * 75)
    if record.total_area_sq_m is not None:
        print(f" [OK] Total Land Area:          {record.total_area_sq_m:.2f} sq.m")
    else:
        print("   - Land area not specified on record.")
    print(f"      Land Classification:      {record.land_classification or 'N/A'}")
    if record.owner_or_allottee:
        print(f"      Owner / Allottee:         {record.owner_or_allottee}")

    print("\n" + "=" * 75)
    print(" 4. SURVEY / KHASRA / PLOT DETAILS")
    print("=" * 75)
    if record.khasra_plot_details:
        print(f" [OK] Registered Survey / Plot Filings ({len(record.khasra_plot_details)} record(s)):")
        for i, item in enumerate(record.khasra_plot_details[:10], 1):
            if isinstance(item, dict):
                p_no = item.get("plot_number") or item.get("registry_agreement_number") or "N/A"
                k_no = item.get("khasra_number") or "N/A"
                area = item.get("area") or item.get("registry_agreement_area") or "N/A"
                vil = item.get("village") or item.get("land_type") or "Sanctioned Scheme"
                print(f"   {i}. Plot: {p_no} | Khasra: {k_no} | Area: {area} | Location: {vil}")
            else:
                print(f"   {i}. {item}")
        if len(record.khasra_plot_details) > 10:
            print(f"   ... and {len(record.khasra_plot_details) - 10} more records.")
    else:
        print("   - No specific khasra/plot details indexed.")

    print("\n" + "=" * 75)
    print(" 5. MATCHING & CONFIDENCE INFORMATION")
    print("=" * 75)
    m_info = record.matching_confidence_info or {}
    status_str = record.match_status.upper()
    conf_pct = record.match_confidence * 100
    print(f" [OK] Match Status:             {status_str} ({conf_pct:.1f}% Confidence)")
    print(f"      Property Category:        {record.property_category}")
    print(f"      Source Record Type:       {record.source_record_type}")
    if record.candidates_considered:
        print(f"      Candidates Evaluated:     {record.candidates_considered}")
    if record.notes:
        print(f"      Audit Notes:              {record.notes}")

    if record.document_evidence:
        print(f"\n      Document Evidence ({len(record.document_evidence)} item(s)):")
        for ev in record.document_evidence[:6]:
            print(f"      - {ev}")

    print("\n" + "=" * 75)
    print(" FINAL STRUCTURED CANONICAL PROPERTY RECORD (JSON)")
    print("=" * 75)
    print(json.dumps(record.model_dump(), indent=2, default=str))

    print("\n" + "=" * 75)
    print(" ALL CANONICAL PROPERTY IDENTIFICATION OUTPUTS GENERATED SUCCESSFULLY!")
    print("=" * 75)


if __name__ == "__main__":
    cli_arg = sys.argv[1] if len(sys.argv) > 1 else "UPRERAPRJ1646"
    main(cli_arg)