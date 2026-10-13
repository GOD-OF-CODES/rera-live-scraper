"""
Run the FULL agent (real LLM decision-making, via whichever backend
AGENT_LLM_BACKEND in .env points to) against a project_id or
registration_number of your choice.

    cd db_schema
    $env:AGENT_DEBUG="1"
    python -m agents.ownership_title.test_manual --registration UPRERAPRJ14636

or by internal id, once you know it (e.g. from Property Identification's
output):

    python -m agents.ownership_title.test_manual --project-id 42

Requires DATABASE_URL always, plus either ANTHROPIC_API_KEY (if
AGENT_LLM_BACKEND=anthropic) or a running Ollama with the model pulled
(if AGENT_LLM_BACKEND=ollama).
"""

import argparse

from agents.ownership_title.agent import run
from agents.ownership_title.schemas import OwnershipTitleRequest

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-id", type=int, default=None)
    parser.add_argument("--registration", type=str, default=None)
    parser.add_argument("--khasra", type=str, default=None)
    parser.add_argument("--district", type=str, default=None)
    args = parser.parse_args()

    if args.project_id is None and not args.registration:
        args.registration = "UPRERAPRJ14636"

    print(
        "Running Ownership & Title agent for: "
        f"project_id={args.project_id!r}, registration={args.registration!r}\n"
    )

    result = run(
        OwnershipTitleRequest(
            project_id=args.project_id,
            registration_number=args.registration,
            khasra_number=args.khasra,
            district_hint=args.district,
        ),
        persist=False,
    )

    print("\nResult:")
    print(result.model_dump_json(indent=2))
