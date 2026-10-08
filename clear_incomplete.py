"""
Find project JSON files that are either:

  1. Explicitly marked failed
     ("project_details_available": false), OR

  2. Old "successful" saves that are actually sparse/wrong -
     this is the bug where a wrong details URL was silently
     built (from the trailing digits of a registration number
     like "UPRERAPRJ307878/07/2025" being misread as a project
     id), so the scraper fetched an unrelated or near-empty
     page and saved it as if it worked fine. These have no
     project name, no documents, no khasra records and no
     registry records.

...then delete just those JSON files, so the next
scrape_details_parallel.py run retries them (everything else
is left alone).

Usage:

    # See what would be deleted, without deleting anything:
    python clear_incomplete.py "Gautam Buddha Nagar" --dry-run

    # Actually delete them:
    python clear_incomplete.py "Gautam Buddha Nagar"

Then re-run the normal scrape command - it will only pick up
the ones just deleted:

    python scrape_details_parallel.py "Gautam Buddha Nagar" --workers 6
"""

import argparse
import json

from src.scraper.district_dataset import get_district_directory
from src.scraper.validation import is_valid_result


def looks_incomplete(data: dict) -> bool:

    return not is_valid_result(data)


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Delete failed or sparse/wrong project JSON files "
            "so they get retried on the next scrape run."
        )
    )

    parser.add_argument(
        "district",
        nargs="?",
        default="Gautam Buddha Nagar",
        help="District name (default: Gautam Buddha Nagar)"
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List incomplete projects without deleting anything"
    )

    args = parser.parse_args()

    directory = get_district_directory(args.district)

    incomplete_files = []

    for file_path in sorted(directory.glob("*.json")):

        if file_path.name.startswith("_"):
            continue

        try:
            with file_path.open(
                "r", encoding="utf-8"
            ) as file:
                data = json.load(file)
        except Exception as error:
            print(
                f"Could not read {file_path.name}: {error}"
            )
            continue

        if looks_incomplete(data):
            incomplete_files.append(file_path)

    total_files = sum(
        1
        for f in directory.glob("*.json")
        if not f.name.startswith("_")
    )

    if not incomplete_files:
        print(
            f"No failed/sparse projects found in "
            f"{directory.resolve()} "
            f"({total_files} file(s) checked)."
        )
        return

    print(
        f"Found {len(incomplete_files)} of {total_files} "
        f"project file(s) in {directory.resolve()} that look "
        f"failed or sparse/wrong:\n"
    )

    for file_path in incomplete_files:
        print(f"  - {file_path.name}")

    if args.dry_run:
        print(
            "\nDry run - nothing deleted. Re-run without "
            "--dry-run to delete these and allow a retry."
        )
        return

    for file_path in incomplete_files:
        file_path.unlink()

    print(
        f"\nDeleted {len(incomplete_files)} file(s). "
        f"Re-run scrape_details_parallel.py for "
        f"\"{args.district}\" to retry them."
    )


if __name__ == "__main__":
    main()