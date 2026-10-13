"""
Run the FULL Land Records & Land Use agent (real LLM decision-making)
against a registration number or project_id of your choice.

    cd db_schema
    python -m agents.land_records_land_use.test_manual --registration UPRERAPRJ10006
"""

import argparse

from agents.land_records_land_use.agent import run
from agents.land_records_land_use.schemas import LandRecordsLandUseRequest

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-id", type=int, default=None)
    parser.add_argument("--registration", type=str, default=None)
    parser.add_argument("--khasra", type=str, default=None)
    parser.add_argument("--district", type=str, default=None)
    args = parser.parse_args()

    if args.project_id is None and not args.registration:
        args.registration = "UPRERAPRJ10006"

    print(
        "Running Land Records & Land Use agent for: "
        f"project_id={args.project_id!r}, registration={args.registration!r}\n"
    )

    result = run(
        LandRecordsLandUseRequest(
            project_id=args.project_id,
            registration_number=args.registration,
            khasra_number=args.khasra,
            district_hint=args.district,
        ),
        persist=False,
    )

    print("\nResult:")
    print(result.model_dump_json(indent=2))
