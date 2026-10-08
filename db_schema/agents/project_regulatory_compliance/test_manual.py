"""
Run the FULL Project & Regulatory Compliance agent (real LLM decision-making)
against a registration number or project_id of your choice.

    cd db_schema
    python -m agents.project_regulatory_compliance.test_manual --registration UPRERAPRJ10006
"""

import argparse

from agents.project_regulatory_compliance.agent import run
from agents.project_regulatory_compliance.schemas import ProjectRegulatoryComplianceRequest

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-id", type=int, default=None)
    parser.add_argument("--registration", type=str, default=None)
    parser.add_argument("--promoter", type=str, default=None)
    parser.add_argument("--authority", type=str, default=None)
    args = parser.parse_args()

    if args.project_id is None and not args.registration:
        args.registration = "UPRERAPRJ10006"

    print(
        "Running Project & Regulatory Compliance agent for: "
        f"project_id={args.project_id!r}, registration={args.registration!r}\n"
    )

    result = run(
        ProjectRegulatoryComplianceRequest(
            project_id=args.project_id,
            registration_number=args.registration,
            promoter_name_hint=args.promoter,
            authority_hint=args.authority,
        ),
        persist=False,
    )

    print("\nResult:")
    print(result.model_dump_json(indent=2))
