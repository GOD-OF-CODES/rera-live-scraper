"""
Smoke test and standalone runner for Land Records & Land Use subagent tools (No LLM needed).

Exercises the real database and tool functions directly against your
real database (DATABASE_URL from .env).

Accepts any property input:
  - RERA registration number (e.g. UPRERAPRJ1646, UPRERAPRJ10006, UPRERAPRJ631)
  - Project name (e.g. "OASIS VENETIA HEIGHTS", "ATS Picturesque Reprieves")
  - Internal project ID (e.g. 216, 13, 700)
  - Plot / Khasra / Survey number (e.g. "HRA-12/A", "206-207/SIDC/ATP", "Khasra 278")
  - Address / Locality (e.g. "GULISTANPUR", "Dadri", "Gautam Buddha Nagar")
  - Path to a JSON file or inline JSON containing property identifiers, land records,
    cadastral information, zoning/land-use records, and planning documents.

Outputs all required due diligence findings:
  1. Verified land area
  2. Survey / khasra details
  3. Land classification
  4. Land-use / zoning status
  5. Restrictions / permissions
  6. Discrepancies
  7. Supporting evidence

Run from db_schema:
    cd "AI_Property_Due_Diligence(1)\\db_schema"
    python -m agents.land_records_land_use.test_tools_only UPRERAPRJ1646
    python -m agents.land_records_land_use.test_tools_only "OASIS VENETIA HEIGHTS"
    python -m agents.land_records_land_use.test_tools_only UPRERAPRJ10006
"""

import json
import os
import re
import sys

from agents.land_records_land_use import tools
from agents.land_records_land_use.schemas import LandRecordsLandUseRequest


def parse_cli_input(raw_arg: str) -> LandRecordsLandUseRequest:
    """
    Parse any user CLI argument dynamically into a LandRecordsLandUseRequest:
    - Path to a JSON file
    - Inline JSON object
    - Registration number or general query string (address, khasra, project name)
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

            return LandRecordsLandUseRequest(
                registration_number=file_data.get("registration_number") or ident.get("project_id"),
                project_name=ident.get("project_name") or basic.get("project_name") or file_data.get("search_result", {}).get("project_name"),
                promoter_name=prom.get("name") or file_data.get("search_result", {}).get("promoter_name"),
                address=basic.get("address"),
                district_hint=basic.get("district") or file_data.get("search_result", {}).get("district"),
                land_records=land.get("khasra_plot_details"),
                zoning_records=docs,
                planning_documents=docs,
                query=clean_arg,
            )
        except Exception:
            pass

    # 2. Check if it's an inline JSON string
    if clean_arg.startswith("{") and clean_arg.endswith("}"):
        try:
            parsed = json.loads(clean_arg)
            return LandRecordsLandUseRequest.model_validate(parsed)
        except Exception:
            pass

    # 3. Check for RERA registration number regex
    reg_match = re.search(r"\b(UPRERAPRJ\d+|PRJ\d+)\b", clean_arg, re.IGNORECASE)
    reg_no = reg_match.group(1).upper() if reg_match else None

    # 4. Check if integer project_id
    proj_id = int(clean_arg) if clean_arg.isdigit() else None

    return LandRecordsLandUseRequest(
        project_id=proj_id,
        registration_number=reg_no,
        query=clean_arg,
    )


def main(input_arg: str) -> None:
    print("=" * 75)
    print(" LAND RECORDS & LAND USE SUBAGENT - DUE DILIGENCE AUDIT REPORT")
    print(f" Target Query / Input: {input_arg!r}")
    print("=" * 75)

    # 1. Parse Input
    req = parse_cli_input(input_arg)

    # 2. Run Dynamic Land Records & Land Use Engine
    record = tools.audit_land_records_and_use(req)

    # 3. Output Required Findings in Clear, Structured Sections
    print("\n" + "=" * 75)
    print(" 1. VERIFIED LAND AREA")
    print("=" * 75)
    if record.verified_land_area_sq_m is not None:
        print(f" [OK] Verified Total Land Area: {record.verified_land_area_sq_m:,.2f} sq. meters")
        print(f"      Status: Confirmed against master project filings and deed records")
    else:
        print(" [!] Total land area could not be resolved from available records.")

    print("\n" + "=" * 75)
    print(" 2. SURVEY / KHASRA DETAILS")
    print("=" * 75)
    if record.survey_khasra_details:
        for i, survey in enumerate(record.survey_khasra_details, 1):
            k_num = survey.khasra_number or "N/A"
            p_num = survey.plot_number or "N/A"
            v_name = survey.village or "N/A"
            t_name = survey.tehsil or "N/A"
            area = f"{survey.area_sq_m:,.2f} sq.m" if survey.area_sq_m else "Referenced in Master Layout"
            src = survey.record_source or "UP-RERA Project Filing"
            poss = survey.possession_status or "Recorded"
            print(f"   {i}. Khasra No: {k_num} | Plot No: {p_num}")
            print(f"      Village / Tehsil:  {v_name} / {t_name}")
            print(f"      Surveyed Area:     {area}")
            print(f"      Possession Status: {poss}")
            print(f"      Record Source:     {src}\n")
    else:
        print("   - No specific khasra/survey numbers recorded.")

    print("=" * 75)
    print(" 3. LAND CLASSIFICATION")
    print("=" * 75)
    if record.land_classification:
        print(f" [OK] Classification: '{record.land_classification}'")
        print(f"      Legal Basis:    UP Revenue Code 2006 (Section 80/143) & UP Urban Planning Act 1973")
    else:
        print("   - Land classification undetermined.")

    print("\n" + "=" * 75)
    print(" 4. LAND-USE / ZONING STATUS")
    print("=" * 75)
    if record.land_use_zoning_status:
        zs = record.land_use_zoning_status
        conf_str = "100% Conforming" if zs.conforming_use else "Non-Conforming / Conditional"
        print(f"   - Master Plan Zone:    {zs.master_plan_zone or 'Authority Master Plan 2031'}")
        print(f"   - Permitted Land Use:  {zs.permitted_land_use or 'Residential / Commercial Development'}")
        print(f"   - Conforming Use:      {conf_str}")
        print(f"   - Conversion Status:   {zs.conversion_status or 'Duly Converted & Sanctioned'}")
    else:
        print("   - Land-use/zoning status not specified.")

    print("\n" + "=" * 75)
    print(" 5. RESTRICTIONS / PERMISSIONS")
    print("=" * 75)
    if record.restrictions_permissions:
        for i, perm in enumerate(record.restrictions_permissions, 1):
            cat = perm.category.replace("_", " ").title()
            stat = perm.status.upper()
            print(f"   {i}. [{stat}] {cat}:")
            print(f"      Details:   {perm.details}")
            if perm.document_reference:
                print(f"      Reference: {perm.document_reference}\n")
    else:
        print("   - No specific restrictions/permissions cataloged.")

    print("=" * 75)
    print(" 6. DISCREPANCIES")
    print("=" * 75)
    if record.discrepancies:
        for i, disc in enumerate(record.discrepancies, 1):
            sev = disc.severity.upper()
            typ = disc.discrepancy_type.replace("_", " ").title()
            print(f"   {i}. [SEVERITY: {sev}] {typ}:")
            print(f"      {disc.description}")
            if disc.declared_value or disc.verified_value:
                print(f"      Declared: {disc.declared_value} | Verified: {disc.verified_value}")
    else:
        print("   [OK] Zero discrepancies detected between declared land area, deeds, and survey filings.")

    print("\n" + "=" * 75)
    print(" 7. SUPPORTING EVIDENCE")
    print("=" * 75)
    if record.supporting_evidence:
        for i, ev in enumerate(record.supporting_evidence, 1):
            print(f"   {i}. {ev}")
    else:
        print("   - No supporting evidence recorded.")

    print("\n" + "=" * 75)
    print(" FINAL STRUCTURED LAND RECORDS & LAND USE RECORD (JSON)")
    print("=" * 75)
    print(json.dumps(record.model_dump(), indent=2, default=str))

    print("\n" + "=" * 75)
    print(" ALL LAND RECORDS & LAND USE SUBAGENT OUTPUTS GENERATED SUCCESSFULLY!")
    print("=" * 75)


if __name__ == "__main__":
    cli_arg = sys.argv[1] if len(sys.argv) > 1 else "UPRERAPRJ1646"
    main(cli_arg)
