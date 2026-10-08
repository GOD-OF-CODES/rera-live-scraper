"""
Inserts one scraper JSON result file into the database.

Usage (from the db_schema project root):

    python -m scripts.insert_json path/to/UPRERAPRJ14636.json
"""

import json
import sys
from pathlib import Path

from db.loader import insert_project_json


def main():

    if len(sys.argv) != 2:
        print("Usage: python -m scripts.insert_json <path-to-json-file>")
        sys.exit(1)

    file_path = Path(sys.argv[1])

    if not file_path.exists():
        print(f"File not found: {file_path}")
        sys.exit(1)

    data = json.loads(file_path.read_text(encoding="utf-8"))

    project_id = insert_project_json(data)

    if project_id:
        print(f"Inserted/updated. projects.id = {project_id}")
    else:
        print("Nothing inserted (project not found / no details available).")


if __name__ == "__main__":
    main()
