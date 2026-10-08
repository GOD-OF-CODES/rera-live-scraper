"""
Run the Property Identification agent against any user input:
address, plot number, khasra number, registration number, promoter name, or uploaded document text.

Examples:
    cd db_schema
    python -m agents.property_identification.test_manual "Assotech Realty Private Limited" --direct
    python -m agents.property_identification.test_manual "SD 23 sector 45" --direct
    python -m agents.property_identification.test_manual --plot "SD 23" --address "Sector 45 Noida" --direct
    python -m agents.property_identification.test_manual UPRERAPRJ10006 --direct
"""

import argparse
import json
import sys

from agents.property_identification.agent import run
from agents.property_identification.schemas import PropertyIdentificationRequest

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Property Identification Agent CLI Runner")
    parser.add_argument("query", nargs="?", default=None, help="Raw query / address / registration number")
    parser.add_argument("--address", type=str, default=None, help="User provided address")
    parser.add_argument("--plot", type=str, default=None, help="Plot / unit number")
    parser.add_argument("--khasra", type=str, default=None, help="Khasra / survey number")
    parser.add_argument("--registration", type=str, default=None, help="RERA registration number")
    parser.add_argument("--district", type=str, default=None, help="District hint")
    parser.add_argument("--doc-text", type=str, default=None, help="Uploaded document text snippet")
    parser.add_argument(
        "--direct",
        action="store_true",
        help="Bypass LLM tool-calling loop and run deterministic master tool pipeline directly",
    )
    args = parser.parse_args()

    raw_input = (
        args.query
        or args.khasra
        or args.plot
        or args.address
        or args.registration
        or "3534 GH-FTSNO-3456"
    )

    print(f"Running Property Identification agent for: {raw_input!r}\n")

    request = PropertyIdentificationRequest(
        raw_query=raw_input,
        address=args.address,
        plot_number=args.plot,
        khasra_number=args.khasra,
        registration_number=args.registration,
        district_hint=args.district,
        uploaded_document_text=args.doc_text,
    )

    result = run(request, persist=False, force_direct=args.direct)

    # Format for clean terminal reading
    dump_dict = result.model_dump()
    if dump_dict.get("khasra_plot_details") and len(dump_dict["khasra_plot_details"]) > 5:
        total_khasra = len(dump_dict["khasra_plot_details"])
        dump_dict["khasra_plot_details"] = (
            dump_dict["khasra_plot_details"][:3]
            + [f"... and {total_khasra - 3} more records in database"]
        )

    print("\nResolved Canonical Property Record:")
    print(json.dumps(dump_dict, indent=2, default=str))