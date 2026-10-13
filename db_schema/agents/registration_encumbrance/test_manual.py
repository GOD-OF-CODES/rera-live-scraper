"""
Run the FULL Registration & Encumbrance agent (real LLM decision-making)
against a registration number or project_id of your choice.

    cd db_schema
    python -m agents.registration_encumbrance.test_manual --registration UPRERAPRJ10006
"""

import argparse

from agents.registration_encumbrance.agent import run
from agents.registration_encumbrance.schemas import RegistrationEncumbranceRequest

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-id", type=int, default=None)
    parser.add_argument("--registration", type=str, default=None)
    parser.add_argument("--khasra", type=str, default=None)
    parser.add_argument("--party", type=str, default=None)
    args = parser.parse_args()

    if args.project_id is None and not args.registration:
        args.registration = "UPRERAPRJ10006"

    print(
        "Running Registration & Encumbrance agent for: "
        f"project_id={args.project_id!r}, registration={args.registration!r}\n"
    )

    result = run(
        RegistrationEncumbranceRequest(
            project_id=args.project_id,
            registration_number=args.registration,
            khasra_number=args.khasra,
            party_name_hint=args.party,
        ),
        persist=False,
    )

    print("\nResult:")
    print(result.model_dump_json(indent=2))
