"""
Smoke test and standalone runner for Registration & Encumbrance subagent tools (No LLM needed).

Exercises the real database and tool functions directly against your
real database (DATABASE_URL from .env).

Accepts any property input:
  - RERA registration number (e.g. UPRERAPRJ1646, UPRERAPRJ10006, UPRERAPRJ631)
  - Project name (e.g. "OASIS VENETIA HEIGHTS", "ATS Picturesque Reprieves")
  - Internal project ID (e.g. 216, 13, 700)
  - Plot / Khasra / Survey number (e.g. "HRA-12/A", "206-207/SIDC/ATP", "Khasra 278")
  - Address / Locality (e.g. "GULISTANPUR", "Dadri", "Gautam Buddha Nagar")
  - Path to a JSON file or inline JSON containing property identifiers, registration records,
    registered deeds, and encumbrance-related records.

Outputs all required due diligence findings:
  1. Transaction timeline
  2. Buyers / sellers
  3. Deed / registration details
  4. Mortgages / liens / charges / attachments
  5. Status where available
  6. Supporting evidence

Run from db_schema:
    cd "AI_Property_Due_Diligence(1)\\db_schema"
    python -m agents.registration_encumbrance.test_tools_only UPRERAPRJ1646
    python -m agents.registration_encumbrance.test_tools_only "OASIS VENETIA HEIGHTS"
    python -m agents.registration_encumbrance.test_tools_only UPRERAPRJ10006
"""

import json
import os
import re
import sys

from agents.registration_encumbrance import tools
from agents.registration_encumbrance.schemas import RegistrationEncumbranceRequest


def parse_cli_input(raw_arg: str) -> RegistrationEncumbranceRequest:
    """
    Parse any user CLI argument dynamically into a RegistrationEncumbranceRequest:
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

            return RegistrationEncumbranceRequest(
                registration_number=file_data.get("registration_number") or ident.get("project_id"),
                project_name=ident.get("project_name") or basic.get("project_name") or file_data.get("search_result", {}).get("project_name"),
                promoter_name=prom.get("name") or file_data.get("search_result", {}).get("promoter_name"),
                address=basic.get("address"),
                district_hint=basic.get("district") or file_data.get("search_result", {}).get("district"),
                registered_deeds=land.get("registry_agreement_details"),
                registration_records=land.get("registry_agreement_details"),
                encumbrance_records=docs,
                query=clean_arg,
            )
        except Exception:
            pass

    # 2. Check if it's an inline JSON string
    if clean_arg.startswith("{") and clean_arg.endswith("}"):
        try:
            parsed = json.loads(clean_arg)
            return RegistrationEncumbranceRequest.model_validate(parsed)
        except Exception:
            pass

    # 3. Check for RERA registration number regex
    reg_match = re.search(r"\b(UPRERAPRJ\d+|PRJ\d+)\b", clean_arg, re.IGNORECASE)
    reg_no = reg_match.group(1).upper() if reg_match else None

    # 4. Check if integer project_id
    proj_id = int(clean_arg) if clean_arg.isdigit() else None

    return RegistrationEncumbranceRequest(
        project_id=proj_id,
        registration_number=reg_no,
        query=clean_arg,
    )


def main(input_arg: str) -> None:
    print("=" * 75)
    print(" REGISTRATION & ENCUMBRANCE SUBAGENT - DUE DILIGENCE AUDIT REPORT")
    print(f" Target Query / Input: {input_arg!r}")
    print("=" * 75)

    # 1. Parse Input
    req = parse_cli_input(input_arg)

    # 2. Run Dynamic Registration & Encumbrance Engine
    record = tools.audit_registration_and_encumbrance(req)

    # 3. Output Required Findings in Clear, Structured Sections
    print("\n" + "=" * 75)
    print(" 1. TRANSACTION TIMELINE")
    print("=" * 75)
    if record.transaction_timeline:
        for txn in record.transaction_timeline:
            seq = txn.sequence or "-"
            print(f" [Link {seq}] {txn.deed_type.upper()}")
            print(f"   Transaction ID:     {txn.transaction_id}")
            print(f"   Registration No:    {txn.registration_number}")
            print(f"   Registration Date:  {txn.registration_date}")
            print(f"   Sellers / Grantors: {txn.sellers}")
            print(f"   Buyers / Grantees:  {txn.buyers}")
            print(f"   Property Details:   {txn.property_description}")
            print(f"   Evidence Reference: {txn.document_reference}\n")
    else:
        print("   - No transaction timeline recorded.")

    print("=" * 75)
    print(" 2. BUYERS / SELLERS")
    print("=" * 75)
    if record.buyers_sellers:
        for i, party in enumerate(record.buyers_sellers, 1):
            ref_str = f" | Ref: {party.transaction_reference}" if party.transaction_reference else ""
            print(f"   {i}. [{party.role.upper()}] '{party.party_name}'{ref_str}")
    else:
        print("   - No buyers/sellers recorded.")

    print("\n" + "=" * 75)
    print(" 3. DEED / REGISTRATION DETAILS")
    print("=" * 75)
    if record.deed_registration_details:
        for i, deed in enumerate(record.deed_registration_details, 1):
            d_no = deed.deed_number or "N/A"
            d_dt = deed.registration_date or "N/A"
            sro = deed.sub_registrar_office or "SRO Filing"
            ref = deed.document_reference or "Registered on Record"
            print(f"   {i}. Deed Type:        {deed.deed_type}")
            print(f"      Deed / Reg No:    {d_no}")
            print(f"      Registration Dt:  {d_dt}")
            print(f"      Issuing SRO:      {sro}")
            print(f"      Document Ref:     {ref}\n")
    else:
        print("   - No specific deed details recorded.")

    print("=" * 75)
    print(" 4. MORTGAGES / LIENS / CHARGES / ATTACHMENTS")
    print("=" * 75)
    claims = record.mortgages_liens_charges_attachments or record.encumbrances_and_charges
    if claims:
        for i, claim in enumerate(claims, 1):
            stat = claim.status.upper()
            c_type = claim.claim_type.replace("_", " ").title()
            print(f"   {i}. [{stat}] {c_type}:")
            print(f"      Details:     {claim.details}")
            if claim.financial_institution:
                print(f"      Institution: {claim.financial_institution}")
            if claim.document_reference:
                print(f"      Evidence:    {claim.document_reference}\n")
    else:
        print("   [OK] Zero mortgages, liens, or charges recorded.")

    print("=" * 75)
    print(" 5. STATUS WHERE AVAILABLE")
    print("=" * 75)
    enc_status = "ENCUMBERED (Active Mortgage / Charge)" if not record.encumbrance_free_status else "CLEAR TITLE (100% Encumbrance-Free)"
    print(f" [OK] Overall Property Status: {enc_status}")
    print(f"      Summary:                {record.status_summary}")
    print(f"      Match Status:           {record.match_status.upper()}")

    if record.bank_accounts:
        print(f"\n      Project Escrow Bank Accounts ({len(record.bank_accounts)} registered):")
        for b in record.bank_accounts:
            print(f"      - Bank: {b.get('bank_name')} | A/C: {b.get('account_number')} | IFSC: {b.get('ifsc_code')}")

    print("\n" + "=" * 75)
    print(" 6. SUPPORTING EVIDENCE")
    print("=" * 75)
    if record.supporting_evidence:
        for i, ev in enumerate(record.supporting_evidence, 1):
            print(f"   {i}. {ev}")
    else:
        print("   - No supporting evidence recorded.")

    print("\n" + "=" * 75)
    print(" FINAL STRUCTURED REGISTRATION & ENCUMBRANCE RECORD (JSON)")
    print("=" * 75)
    print(json.dumps(record.model_dump(), indent=2, default=str))

    print("\n" + "=" * 75)
    print(" ALL REGISTRATION & ENCUMBRANCE SUBAGENT OUTPUTS GENERATED SUCCESSFULLY!")
    print("=" * 75)


if __name__ == "__main__":
    cli_arg = sys.argv[1] if len(sys.argv) > 1 else "UPRERAPRJ1646"
    main(cli_arg)
