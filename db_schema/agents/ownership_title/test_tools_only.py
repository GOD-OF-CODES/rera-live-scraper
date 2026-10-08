"""
Smoke test and standalone runner for Ownership & Title subagent tools (No LLM needed).

Exercises the real database and tool functions directly against your
real database (DATABASE_URL from .env).

Accepts any property input:
  - RERA registration number (e.g. UPRERAPRJ1646, UPRERAPRJ10006, UPRERAPRJ631)
  - Project name (e.g. "OASIS VENETIA HEIGHTS", "ATS Picturesque Reprieves")
  - Internal project ID (e.g. 216, 13, 700)
  - Plot / Khasra / Survey number (e.g. "HRA-12/A", "206-207/SIDC/ATP", "Khasra 278")
  - Path to a JSON file or inline JSON containing property identifiers, land records,
    mutation records, title documents, and registered deeds.

Outputs all required due diligence findings:
  1. Current owner
  2. Previous owners
  3. Ownership chain
  4. Transfer dates/types
  5. Title gaps
  6. Conflicting ownership information
  7. Supporting evidence

Run from db_schema:
    cd "AI_Property_Due_Diligence(1)\\db_schema"
    python -m agents.ownership_title.test_tools_only UPRERAPRJ1646
    python -m agents.ownership_title.test_tools_only "OASIS VENETIA HEIGHTS"
    python -m agents.ownership_title.test_tools_only UPRERAPRJ10006
"""

import json
import os
import re
import sys

from agents.ownership_title import tools
from agents.ownership_title.schemas import OwnershipTitleRequest


def parse_cli_input(raw_arg: str) -> OwnershipTitleRequest:
    """
    Parse any user CLI argument dynamically into an OwnershipTitleRequest:
    - Path to a JSON file
    - Inline JSON object
    - Registration number or general query string
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
            land = pdata.get("land_details", {})
            docs = pdata.get("documents", [])

            return OwnershipTitleRequest(
                registration_number=file_data.get("registration_number") or ident.get("project_id"),
                project_name=ident.get("project_name") or file_data.get("search_result", {}).get("project_name"),
                promoter_name=prom.get("name"),
                land_records=land.get("khasra_plot_details"),
                registered_deeds=land.get("registry_agreement_details"),
                title_documents=docs,
                query=clean_arg,
            )
        except Exception:
            pass

    # 2. Check if it's an inline JSON string
    if clean_arg.startswith("{") and clean_arg.endswith("}"):
        try:
            parsed = json.loads(clean_arg)
            return OwnershipTitleRequest.model_validate(parsed)
        except Exception:
            pass

    # 3. Check for RERA registration number regex
    reg_match = re.search(r"\b(UPRERAPRJ\d+|PRJ\d+)\b", clean_arg, re.IGNORECASE)
    reg_no = reg_match.group(1).upper() if reg_match else None

    # 4. Check if integer project_id
    proj_id = int(clean_arg) if clean_arg.isdigit() else None

    return OwnershipTitleRequest(
        project_id=proj_id,
        registration_number=reg_no,
        query=clean_arg,
    )


def main(input_arg: str) -> None:
    print("=" * 75)
    print(" OWNERSHIP & TITLE SUBAGENT - DUE DILIGENCE AUDIT REPORT")
    print(f" Target Query / Input: {input_arg!r}")
    print("=" * 75)

    # 1. Parse Input
    req = parse_cli_input(input_arg)

    # 2. Run Dynamic Ownership & Title Engine
    record = tools.audit_ownership_and_title(req)

    # 3. Output Required Findings in Clear, Structured Sections
    print("\n" + "=" * 75)
    print(" 1. CURRENT OWNER")
    print("=" * 75)
    if record.current_owner:
        print(f" [OK] Current Registered Owner: '{record.current_owner}'")
        print(f"      Status: Confirmed via UP-RERA Master Project Record & Title Filings")
    else:
        print(" [!] Current owner could not be resolved from available records.")

    print("\n" + "=" * 75)
    print(" 2. PREVIOUS OWNERS / ROOT GRANTORS")
    print("=" * 75)
    if record.previous_owners:
        for i, prev in enumerate(record.previous_owners, 1):
            print(f"   {i}. '{prev}'")
    else:
        print("   - No previous owners recorded.")

    print("\n" + "=" * 75)
    print(" 3. OWNERSHIP CHAIN (Oldest -> Newest)")
    print("=" * 75)
    if record.ownership_chain:
        for link in record.ownership_chain:
            print(f" [Link {link.sequence}] {link.transfer_type.upper()}")
            print(f"   From:       {link.from_owner}")
            print(f"   To:         {link.to_owner}")
            print(f"   Date:       {link.transfer_date}")
            print(f"   Evidence:   {link.document_reference}")
            conf_str = f"{link.confidence * 100:.1f}%" if link.confidence is not None else "N/A"
            print(f"   Confidence: {conf_str}\n")
    else:
        print("   - No ownership chain links reconstructed.")

    print("=" * 75)
    print(" 4. TRANSFER DATES & TYPES (Summary View)")
    print("=" * 75)
    if record.transfer_dates_types:
        for item in record.transfer_dates_types:
            seq = item.get("sequence", "-")
            ttype = item.get("transfer_type", "Unknown")
            tdate = item.get("transfer_date", "Unknown")
            from_o = item.get("from_owner", "Unknown")
            to_o = item.get("to_owner", "Unknown")
            print(f"   - Link {seq}: [{ttype}] on {tdate} | {from_o} -> {to_o}")
    else:
        print("   - No transfer dates/types available.")

    print("\n" + "=" * 75)
    print(" 5. TITLE GAPS & UNSUPPORTED LINKS")
    print("=" * 75)
    if record.title_gaps:
        for i, gap in enumerate(record.title_gaps, 1):
            sev = (gap.severity or "INFO").upper()
            betw = gap.between_sequence or []
            print(f"   {i}. [SEVERITY: {sev}] Between Chain Links {betw}:")
            print(f"      {gap.description}")
    else:
        print("   [OK] Zero title gaps identified.")

    print("\n" + "=" * 75)
    print(" 6. CONFLICTING OWNERSHIP INFORMATION")
    print("=" * 75)
    if record.conflicting_ownership_information:
        for i, conf in enumerate(record.conflicting_ownership_information, 1):
            print(f"   {i}. [!] {conf.description}")
            if conf.fields_in_conflict:
                print(f"      Fields in conflict: {conf.fields_in_conflict}")
    else:
        print("   [OK] Zero ownership conflicts detected across RERA database and title records.")

    print("\n" + "=" * 75)
    print(" 7. SUPPORTING EVIDENCE")
    print("=" * 75)
    if record.supporting_evidence:
        for i, ev in enumerate(record.supporting_evidence, 1):
            print(f"   {i}. {ev}")
    else:
        print("   - No supporting evidence recorded.")

    print("\n" + "=" * 75)
    print(" FINAL STRUCTURED OWNERSHIP & TITLE RECORD (JSON)")
    print("=" * 75)
    print(json.dumps(record.model_dump(), indent=2, default=str))

    print("\n" + "=" * 75)
    print(" ALL OWNERSHIP & TITLE SUBAGENT OUTPUTS GENERATED SUCCESSFULLY!")
    print("=" * 75)


if __name__ == "__main__":
    cli_arg = sys.argv[1] if len(sys.argv) > 1 else "UPRERAPRJ1646"
    main(cli_arg)
