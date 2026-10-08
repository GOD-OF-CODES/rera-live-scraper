"""
Loads every JSON file in a results directory into the database.
Defaults to ../data/results, matching the scraper project layout
(assuming db_schema sits alongside/inside that project) - pass a
different path if yours is elsewhere.

Usage (from the db_schema project root):

    python -m scripts.backfill_db
    python -m scripts.backfill_db /path/to/data/results
    python -m scripts.backfill_db ../data/results/gautam_buddha_nagar

Files starting with "_" (e.g. the combined "_dataset.json" written
by main_district.py) are skipped - they are a summary of every
project, not a single scraper result, and are not shaped for
insert_project_json.
"""

import json
import sys
from pathlib import Path

from db.loader import insert_project_json

DEFAULT_RESULTS_DIR = Path("../data/results")


def backfill(results_dir: Path):

    files = sorted(
        file_path
        for file_path in results_dir.glob("*.json")
        if not file_path.name.startswith("_")
    )

    if not files:
        print(f"No JSON files found in {results_dir.resolve()}")
        return

    print(f"Found {len(files)} file(s) in {results_dir.resolve()}\n")

    succeeded = 0
    skipped = 0
    failed = 0

    for file_path in files:

        registration_number = file_path.stem

        try:
            data = json.loads(file_path.read_text(encoding="utf-8"))

            project_id = insert_project_json(data)

            if project_id:
                print(f"[OK]      {registration_number} -> projects.id={project_id}")
                succeeded += 1
            else:
                print(f"[SKIPPED] {registration_number} (not found / no details)")
                skipped += 1

        except Exception as error:
            print(f"[FAILED]  {registration_number}: {type(error).__name__}: {error}")
            failed += 1

    print("\n" + "=" * 50)
    print(f"Loaded: {succeeded}   Skipped: {skipped}   Failed: {failed}")
    print("=" * 50)


if __name__ == "__main__":

    results_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_RESULTS_DIR

    backfill(results_dir)
