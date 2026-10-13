"""
Smoke test and standalone runner for Project & Regulatory Compliance subagent tools (No LLM needed).

Exercises the real database and tool functions directly against your
real database (DATABASE_URL from .env).

Accepts any property input:
  - RERA registration number (e.g. UPRERAPRJ1646, UPRERAPRJ10006, UPRERAPRJ631)
  - Project name (e.g. "OASIS VENETIA HEIGHTS", "ATS Picturesque Reprieves")
  - Internal project ID (e.g. 216, 13, 700)
  - Plot / Khasra / Survey number (e.g. "HRA-12/A", "206-207/SIDC/ATP", "Khasra 278")
  - Address / Locality (e.g. "GULISTANPUR", "Dadri", "Gautam Buddha Nagar")
  - Path to a JSON file or inline JSON containing property identifiers, RERA records,
    regulatory documents, and planning documents.

Outputs all 5 required property-related due diligence findings:
  1. Project registration status
  2. Promoter / project details
  3. Regulatory findings
  4. Discrepancies / missing information
  5. Supporting evidence

Run from db_schema:
    cd "AI_Property_Due_Diligence(1)\\db_schema"
    python -m agents.project_regulatory_compliance.test_tools_only UPRERAPRJ1646
    python -m agents.project_regulatory_compliance.test_tools_only "OASIS VENETIA HEIGHTS"
    python -m agents.project_regulatory_compliance.test_tools_only "GULISTANPUR"
    python -m agents.project_regulatory_compliance.test_tools_only UPRERAPRJ10006
"""

import json
import os
import re
import sys

from agents.project_regulatory_compliance import tools
from agents.project_regulatory_compliance.schemas import ProjectRegulatoryComplianceRequest


def parse_cli_input(raw_arg: str) -> ProjectRegulatoryComplianceRequest:
    """
    Parse any user CLI argument dynamically into a ProjectRegulatoryComplianceRequest:
    - Path to a JSON file
    - Inline JSON object
    - Registration number or general query string (address, khasra, project name, promoter)
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
            docs = pdata.get("documents", [])

            return ProjectRegulatoryComplianceRequest(
                registration_number=file_data.get("registration_number") or ident.get("project_id"),
                project_name=ident.get("project_name") or basic.get("project_name") or file_data.get("search_result", {}).get("project_name"),
                promoter_name=prom.get("name") or file_data.get("search_result", {}).get("promoter_name"),
                address=basic.get("address"),
                district_hint=basic.get("district") or file_data.get("search_result", {}).get("district"),
                regulatory_documents=docs,
                planning_documents=docs,
                query=clean_arg,
            )
        except Exception:
            pass

    # 2. Check if it's an inline JSON string
    if clean_arg.startswith("{") and clean_arg.endswith("}"):
        try:
            parsed = json.loads(clean_arg)
            return ProjectRegulatoryComplianceRequest.model_validate(parsed)
        except Exception:
            pass

    # 3. Check for RERA registration number regex
    reg_match = re.search(r"\b(UPRERAPRJ\d+|PRJ\d+)\b", clean_arg, re.IGNORECASE)
    reg_no = reg_match.group(1).upper() if reg_match else None

    # 4. Check if integer project_id
    proj_id = int(clean_arg) if clean_arg.isdigit() else None

    return ProjectRegulatoryComplianceRequest(
        project_id=proj_id,
        registration_number=reg_no,
        query=clean_arg,
    )


def main(input_arg: str) -> None:
    print("=" * 75)
    print(" PROJECT & REGULATORY COMPLIANCE SUBAGENT - AUDIT REPORT")
    print(f" Target Query / Input: {input_arg!r}")
    print("=" * 75)

    # 1. Parse Input
    req = parse_cli_input(input_arg)

    # 2. Run Dynamic Project & Regulatory Compliance Engine
    record = tools.audit_project_and_regulatory_compliance(req)

    # 3. Output Required Findings in Clear, Structured Sections
    print("\n" + "=" * 75)
    print(" 1. PROJECT REGISTRATION STATUS")
    print("=" * 75)
    reg_st = record.project_registration_status
    print(f" [OK] RERA Registration Number: {reg_st.registration_number or 'N/A'}")
    print(f"      RERA Project ID:          {reg_st.rera_project_id or 'N/A'}")
    print(f"      Registration Status:      {reg_st.status.upper()}")
    print(f"      Registration Date:        {reg_st.registration_date or 'Recorded on portal'}")
    print(f"      Valid Until (Completion): {reg_st.valid_until or 'Not specified'}")
    print(f"      Approval Certificate:     {reg_st.approval_certificate_name or 'N/A'} (Available: {reg_st.approval_certificate_available})")
    if reg_st.approval_certificate_url:
        print(f"      Certificate Document URL: {reg_st.approval_certificate_url}")
    print(f"      Source Portal:            {reg_st.source_portal}")

    # External portal check
    ext_check = tools.external_regulatory_portal_lookup(
        registration_number=reg_st.registration_number,
        promoter_name=record.promoter_details.name if record.promoter_details else None,
        authority=record.project_details.sanctioning_competent_authority if record.project_details else None,
        district=record.project_details.district if record.project_details else None,
    )
    print(f"      External Registry Status: {ext_check.get('status', 'OK')} ({ext_check.get('message', 'Active on UP-RERA')})")

    print("\n" + "=" * 75)
    print(" 2. PROMOTER / PROJECT DETAILS")
    print("=" * 75)
    if record.promoter_details:
        prom = record.promoter_details
        print(f" [Promoter Information]")
        print(f"   Name:                 {prom.name}")
        print(f"   Promoter Type:        {prom.promoter_type}")
        print(f"   RERA Promoter ID:     {prom.rera_promoter_id or 'N/A'}")
        print(f"   Verification Status:  {prom.verification_status.upper()}")
        print(f"   Registered Office:    {prom.registered_office or 'N/A'}")

    if record.project_details:
        prj = record.project_details
        print(f"\n [Project Basic Details]")
        print(f"   Project Name:         {prj.project_name}")
        print(f"   Project Type:         {prj.project_type or 'Residential / Commercial'}")
        print(f"   Location:             {prj.district or 'N/A'} (Tehsil: {prj.tehsil or 'N/A'})")
        print(f"   Total Land Area:      {prj.total_area_sq_m or 'N/A'} sq.m")
        print(f"   Project Cost:         INR {prj.project_cost_lakhs} Lakhs" if prj.project_cost_lakhs else "   Project Cost:         N/A")
        print(f"   Original Start Date:  {prj.original_start_date or 'N/A'}")
        print(f"   Proposed Start Date:  {prj.proposed_start_date or 'N/A'}")
        print(f"   Proposed Completion:  {prj.proposed_completion_date or 'N/A'}")
        print(f"   Sanctioning Authority:{prj.sanctioning_competent_authority or 'N/A'}")

    if record.professionals:
        print(f"\n [Statutory Appointed Professionals ({len(record.professionals)})]")
        for p in record.professionals:
            print(f"   - {p.professional_type.title()}: {p.name} (License: {p.license_number or 'N/A'}, Contact: {p.contact or 'N/A'})")

    if record.escrow_bank_account:
        b = record.escrow_bank_account
        print(f"\n [RERA Section 4(2)(l)(D) Statutory 70% Escrow Account]")
        print(f"   Bank Name:            {b.get('bank_name')}")
        print(f"   Account Number:       {b.get('account_number')}")
        print(f"   Branch:               {b.get('branch_name') or b.get('branch_address')}")
        print(f"   IFSC Code:            {b.get('ifsc_code')}")
        print(f"   Account Holder:       {b.get('account_holder_name') or 'Project Escrow'}")

    print("\n" + "=" * 75)
    print(" 3. REGULATORY FINDINGS")
    print("=" * 75)
    if record.regulatory_findings:
        for i, f in enumerate(record.regulatory_findings, 1):
            stat = f.status.upper()
            cat = f.category.replace("_", " ").title()
            print(f"   {i}. [{stat}] {cat}:")
            print(f"      Authority: {f.authority_name or 'UP-RERA / Competent Authority'}")
            print(f"      Details:   {f.details}")
            if f.reference_number:
                print(f"      Ref No:    {f.reference_number}")
            if f.document_reference:
                print(f"      Evidence:  {f.document_reference}\n")
    else:
        print("   - No regulatory findings recorded.")

    print("=" * 75)
    print(" 4. DISCREPANCIES / MISSING INFORMATION")
    print("=" * 75)
    if record.discrepancies_and_missing_info:
        for i, d in enumerate(record.discrepancies_and_missing_info, 1):
            sev = d.severity.upper()
            itype = d.issue_type.replace("_", " ").title()
            print(f"   {i}. [{sev}] {itype}:")
            print(f"      Description: {d.description}")
            if d.field_or_document:
                print(f"      Field/Doc:   {d.field_or_document}")
            if d.recommended_action:
                print(f"      Action:      {d.recommended_action}\n")
    else:
        print("   [OK] Zero discrepancies or missing information detected.")

    print("=" * 75)
    print(" 5. SUPPORTING EVIDENCE")
    print("=" * 75)
    if record.supporting_evidence:
        for i, ev in enumerate(record.supporting_evidence, 1):
            print(f"   {i}. {ev}")
    else:
        print("   - No supporting evidence recorded.")

    print("\n" + "=" * 75)
    print(" FINAL STRUCTURED PROJECT & REGULATORY COMPLIANCE RECORD (JSON)")
    print("=" * 75)
    print(json.dumps(record.model_dump(), indent=2, default=str))

    print("\n" + "=" * 75)
    print(" ALL 5 PROJECT & REGULATORY COMPLIANCE OUTPUTS GENERATED SUCCESSFULLY!")
    print("=" * 75)


if __name__ == "__main__":
    cli_arg = sys.argv[1] if len(sys.argv) > 1 else "UPRERAPRJ1646"
    main(cli_arg)
