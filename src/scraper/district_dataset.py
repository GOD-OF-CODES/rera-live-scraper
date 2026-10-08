import json
import re
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from src.scraper.validation import is_valid_result, validate_property_data

SEARCH_URL = "https://up-rera.in/View_projects.aspx"


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    return value.strip("_")


def get_district_directory(district_name: str) -> Path:
    directory = (
        Path("data/results") / slugify(district_name)
    )

    directory.mkdir(
        parents=True,
        exist_ok=True
    )

    return directory


def summary_checkpoint_path(directory: Path) -> Path:
    """
    The list of every project + details URL found for the
    district, saved right after the search step. This is the
    handoff point between the (sequential, manual-CAPTCHA)
    listing phase and the (parallel, headless) detail-scraping
    phase, and also doubles as the resume checkpoint if a long
    run gets interrupted.
    """

    return directory / "_summary_rows.json"


def save_summary_rows(
    directory: Path,
    district_name: str,
    summary_rows: list
) -> Path:

    checkpoint = {
        "district": district_name,
        "generated_at": (
            datetime.now(timezone.utc).isoformat()
        ),
        "total_projects": len(summary_rows),
        "rows": summary_rows,
    }

    path = summary_checkpoint_path(directory)

    atomic_write_json(path, checkpoint)

    return path


def load_summary_rows(directory: Path) -> list:
    path = summary_checkpoint_path(directory)

    if not path.exists():
        raise FileNotFoundError(
            f"No checkpoint found at {path.resolve()}. "
            "Run main_district.py first to search the district "
            "and build the project list."
        )

    checkpoint = json.loads(
        path.read_text(encoding="utf-8")
    )

    return checkpoint["rows"]


def safe_filename(value: str) -> str:
    """
    Turn a registration number into a filesystem-safe filename.

    UP-RERA registration numbers can contain "/" (e.g.
    "UPRERAPRJ913592/01/2026"). On Windows (and Path in general),
    "/" is a directory separator, so using it raw in a filename
    makes Path try to write into a nested folder like
    "UPRERAPRJ913592\\01\\2026.json" - which doesn't exist and
    fails with FileNotFoundError. Replace any character that
    isn't safe in a filename with "_" instead.

    This only affects the filename on disk - the real
    registration_number (with the slashes) is still stored
    as-is inside the JSON content itself.
    """

    value = value.strip()

    value = re.sub(r'[\\/:*?"<>|]+', "_", value)

    value = re.sub(r"\s+", " ", value).strip()

    return value or "unknown"


def project_json_path(
    directory: Path,
    registration_number: str
) -> Path:
    return directory / f"{safe_filename(registration_number)}.json"


def is_already_scraped(
    directory: Path,
    registration_number: str,
    min_version: int = 0,
) -> bool:
    try:
        data = json.loads(project_json_path(directory, registration_number).read_text(encoding="utf-8"))
        return (is_valid_result(data, registration_number)
                and int(data.get("scraper_version", 0)) >= min_version)
    except (OSError, ValueError, TypeError):
        return False


def atomic_write_json(path: Path, data: dict) -> None:
    """Readers see the complete previous or next file, never a partial write."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".scrape-", suffix=".tmp", delete=False) as file:
            temp_path = Path(file.name)
            json.dump(data, file, indent=4, ensure_ascii=False)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def save_project_json(
    directory: Path,
    registration_number: str,
    data: dict
) -> Path:
    """
    Save one project's JSON.

    Uses the SAME structure main.py produces, so this file can be
    inserted with db_schema/scripts/insert_json.py exactly like a
    single-project scrape.
    """

    output_file = project_json_path(
        directory,
        registration_number
    )

    # A transient failure during --force must not destroy the last valid result.
    if not is_valid_result(data, registration_number) and is_already_scraped(directory, registration_number):
        atomic_write_json(directory / "_failures" / output_file.name, data)
        return output_file
    atomic_write_json(output_file, data)
    if is_valid_result(data, registration_number):
        (directory / "_failures" / output_file.name).unlink(missing_ok=True)

    return output_file


def build_dataset_from_directory(
    directory: Path,
    district_name: str
) -> Path:
    """
    Read every per-project JSON file already saved in the
    district directory (skipping "_"-prefixed checkpoint /
    summary files) and combine them into one dataset file.

    Safe to call at any point, including partway through a
    parallel run - it just reflects whatever has been scraped
    so far.
    """

    projects = []

    for file_path in sorted(directory.glob("*.json")):

        if file_path.name.startswith("_"):
            continue

        try:
            projects.append(
                json.loads(
                    file_path.read_text(encoding="utf-8")
                )
            )
        except Exception:
            continue

    dataset = {
        "source": "UP-RERA",
        "district": district_name,
        "generated_at": (
            datetime.now(timezone.utc).isoformat()
        ),
        "total_projects": len(projects),
        "successful_projects": sum(is_valid_result(p) for p in projects),
        "failed_projects": sum(not is_valid_result(p) for p in projects),
        "projects": projects,
    }

    dataset_file = directory / "_dataset.json"

    atomic_write_json(dataset_file, dataset)

    return dataset_file


def build_result(
    registration_number: str,
    search_data: dict,
    details_url: Optional[str],
    structured_data: dict
) -> dict:
    """
    Build the same result shape main.py writes for a single
    project, so district JSON files stay compatible with
    db_schema/scripts/insert_json.py.
    """

    validate_property_data(structured_data, registration_number)
    return {
        "source": "UP-RERA",
        "registration_number": registration_number,
        "project_found": True,
        "project_details_available": True,
        "search_url": SEARCH_URL,
        "project_details_url": details_url,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "scraper_version": 2,
        "search_result": {
            "project_name": search_data.get("project_name"),
            "promoter_name": search_data.get("promoter_name"),
            "district": search_data.get("district"),
            "project_type": search_data.get("project_type"),
            "approval_certificate": (
                search_data.get("approval_certificate")
            ),
        },
        "property_data": structured_data,
    }


def build_error_result(
    registration_number: str,
    search_data: dict,
    error: Exception
) -> dict:

    return {
        "source": "UP-RERA",
        "registration_number": registration_number,
        "project_found": True,
        "project_details_available": False,
        "project_details_url": search_data.get("details_url"),
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "search_url": SEARCH_URL,
        "search_result": {
            "project_name": search_data.get("project_name"),
            "promoter_name": search_data.get("promoter_name"),
            "district": search_data.get("district"),
            "project_type": search_data.get("project_type"),
            "approval_certificate": (
                search_data.get("approval_certificate")
            ),
        },
        "error": str(error),
    }
