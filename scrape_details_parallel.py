"""
Scrapes every project's details page for a district IN PARALLEL,
using several headless browser processes at once.

Run main_district.py first - it does the one-time manual CAPTCHA
search and saves the list of projects (data/results/<district>/
_summary_rows.json). This script then reads that list and does
the slow part (opening ~1000+ details pages) across several
processes simultaneously, since no further CAPTCHA is needed once
you have a project's details URL.

Usage:

    python scrape_details_parallel.py "Gautam Buddha Nagar"
    python scrape_details_parallel.py "Gautam Buddha Nagar" --workers 8
    python scrape_details_parallel.py "Gautam Buddha Nagar" --force

Safe to re-run: only validated successful project files are
skipped, so an interrupted run just picks up where it left off
(use --force to re-scrape everything anyway).
"""

import argparse
import random
import time
from datetime import datetime, timezone
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from src.scraper.browser import BrowserManager
from src.scraper.detail_page import scrape_detail_page
from src.scraper.project_links import project_ids_from_html, DETAILS_URL
from src.scraper.district_dataset import (
    get_district_directory,
    load_summary_rows,
    is_already_scraped,
    save_project_json,
    build_result,
    build_error_result,
    build_dataset_from_directory,
    save_summary_rows,
    atomic_write_json,
)


def chunk_rows(rows: list, worker_count: int) -> list:
    """
    Split rows into `worker_count` roughly-equal contiguous
    chunks (order doesn't matter - each row is independent).
    """

    if worker_count <= 1:
        return [rows]

    chunks = [[] for _ in range(worker_count)]

    for index, row in enumerate(rows):
        chunks[index % worker_count].append(row)

    return [chunk for chunk in chunks if chunk]


def scrape_chunk(
    chunk: list,
    output_directory: str,
    worker_id: int,
    max_attempts: int,
    min_delay_ms: int,
    max_delay_ms: int,
) -> dict:
    """
    Runs in its OWN process with its OWN headless browser.

    Must stay at module level (not a nested function) so it can
    be pickled and sent to the worker process.
    """

    output_directory = Path(output_directory)

    succeeded = 0
    failed = 0

    browser = BrowserManager(headless=True)

    try:
        page = browser.start()

        total = len(chunk)

        for position, search_data in enumerate(chunk, start=1):

            registration_number = (
                search_data.get("registration_number")
                or f"UNKNOWN_W{worker_id}_{position}"
            )

            prefix = (
                f"[worker {worker_id} | {position}/{total}] "
                f"{registration_number}"
            )

            details_url = search_data.get("details_url")

            if not details_url:
                print(f"{prefix} - no details URL, skipping.")

                result = build_error_result(
                    registration_number,
                    search_data,
                    RuntimeError(
                        "Could not determine the project "
                        "details URL."
                    )
                )

                save_project_json(
                    output_directory,
                    registration_number,
                    result
                )

                failed += 1
                continue

            if details_url.startswith("/"):
                details_url = "https://up-rera.in" + details_url

            last_error = None

            for attempt in range(1, max_attempts + 1):
                try:
                    structured_data = scrape_detail_page(page, details_url, registration_number)

                    result = build_result(
                        registration_number,
                        search_data,
                        page.url,
                        structured_data
                    )

                    save_project_json(
                        output_directory,
                        registration_number,
                        result
                    )

                    succeeded += 1

                    print(f"{prefix} - OK")

                    last_error = None
                    break

                except Exception as error:
                    last_error = error

                    print(
                        f"{prefix} - attempt {attempt}/"
                        f"{max_attempts} failed: {error}"
                    )
                    if attempt < max_attempts:
                        time.sleep(min(2 ** attempt, 10) + random.uniform(0, 1))
                        # Recover crashed/closed pages without losing the rest of a chunk.
                        if page.is_closed() or not browser.browser.is_connected():
                            browser.close()
                            browser = BrowserManager(headless=True)
                            page = browser.start()

            if last_error is not None:

                result = build_error_result(
                    registration_number,
                    search_data,
                    last_error
                )

                save_project_json(
                    output_directory,
                    registration_number,
                    result
                )

                failed += 1

            # Small polite random delay so all workers together
            # don't hammer the site with a burst of requests.
            time.sleep(
                random.uniform(
                    min_delay_ms / 1000,
                    max_delay_ms / 1000
                )
            )

    finally:
        browser.close()

    return {
        "worker_id": worker_id,
        "succeeded": succeeded,
        "failed": failed,
    }


def main():

    parser = argparse.ArgumentParser(
        description=(
            "Scrape UP-RERA project details for a district in "
            "parallel, using the checkpoint saved by "
            "main_district.py."
        )
    )

    parser.add_argument(
        "district",
        nargs="?",
        default="Gautam Buddha Nagar",
        help="District name (default: Gautam Buddha Nagar)"
    )

    parser.add_argument(
        "--workers",
        type=int,
        default=6,
        help=(
            "Number of parallel headless browser processes "
            "(default: 6). Start modest (4-8) - too many at "
            "once risks the site rate-limiting or blocking you."
        )
    )

    parser.add_argument(
        "--retries",
        type=int,
        default=2,
        help="Retry attempts per project on failure (default: 2)"
    )

    parser.add_argument(
        "--min-delay-ms",
        type=int,
        default=400,
        help="Minimum polite delay between requests per worker"
    )

    parser.add_argument(
        "--max-delay-ms",
        type=int,
        default=1200,
        help="Maximum polite delay between requests per worker"
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-scrape projects that already have a saved JSON"
    )
    parser.add_argument("--search-html", type=Path,
                        help="Repair legacy checkpoint URLs from a saved district search response")
    parser.add_argument("--limit", type=int, help="Process at most this many pending projects")
    parser.add_argument("--refresh-outdated", action="store_true",
                        help="Also refresh successful files created by the old extractor")

    args = parser.parse_args()
    if args.workers < 1 or args.retries < 0:
        parser.error("--workers must be positive and --retries nonnegative")
    if args.min_delay_ms < 0 or args.max_delay_ms < args.min_delay_ms:
        parser.error("delays must satisfy 0 <= min-delay-ms <= max-delay-ms")
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")

    output_directory = get_district_directory(args.district)

    all_rows = load_summary_rows(output_directory)
    if args.search_html:
        mapping = project_ids_from_html(args.search_html.read_text(encoding="utf-8"))
        missing = [r["registration_number"] for r in all_rows if r["registration_number"] not in mapping]
        if missing:
            parser.error(f"Search HTML lacks authoritative IDs for {len(missing)} checkpoint rows")
        for row in all_rows:
            row["internal_project_id"] = mapping[row["registration_number"]]
            row["details_url"] = DETAILS_URL.format(row["internal_project_id"])
            row["details_url_source"] = "search_viewstate"
        save_summary_rows(output_directory, args.district, all_rows)

    print(f"Loaded {len(all_rows)} project(s) for {args.district}.")

    if args.force:
        pending_rows = all_rows
    else:
        pending_rows = [
            row for row in all_rows
            if not is_already_scraped(
                output_directory,
                row.get("registration_number") or "",
                min_version=2 if args.refresh_outdated else 0,
            )
        ]

    already_done = len(all_rows) - len(pending_rows)
    pending_count = len(pending_rows)
    if args.limit:
        pending_rows = pending_rows[:args.limit]
    total_succeeded = 0
    total_failed = 0

    if already_done:
        print(
            f"{already_done} already scraped - skipping "
            f"(use --force to re-scrape everything)."
        )

    if not pending_rows:
        print("Nothing left to scrape.")
    else:
        worker_count = max(1, min(args.workers, len(pending_rows)))

        chunks = chunk_rows(pending_rows, worker_count)

        print(
            f"Scraping {len(pending_rows)} project(s) across "
            f"{len(chunks)} parallel worker(s)...\n"
        )

        total_succeeded = 0
        total_failed = 0

        with ProcessPoolExecutor(
            max_workers=worker_count
        ) as executor:

            futures = [
                executor.submit(
                    scrape_chunk,
                    chunk,
                    str(output_directory),
                    worker_id,
                    args.retries + 1,
                    args.min_delay_ms,
                    args.max_delay_ms,
                )
                for worker_id, chunk in enumerate(chunks, start=1)
            ]

            for future in as_completed(futures):
                try:
                    summary = future.result()
                except Exception as error:
                    total_failed += 1
                    print(f"Worker failed unexpectedly: {error}; rerun to resume unfinished rows.")
                    continue

                total_succeeded += summary["succeeded"]
                total_failed += summary["failed"]

                print(
                    f"\nWorker {summary['worker_id']} finished: "
                    f"{summary['succeeded']} OK, "
                    f"{summary['failed']} failed."
                )

        print(
            f"\nAll workers done. "
            f"Total: {total_succeeded} OK, {total_failed} failed."
        )

    # =============================================================
    # REBUILD COMBINED DATASET FROM WHATEVER IS ON DISK
    # =============================================================

    dataset_file = build_dataset_from_directory(
        output_directory,
        args.district
    )

    print("\n" + "=" * 65)
    print("DISTRICT DATASET UPDATED")
    print("=" * 65)

    print(f"\nDistrict: {args.district}")
    print(f"Individual JSON files: {output_directory.resolve()}")
    print(f"Combined dataset file: {dataset_file.resolve()}")
    atomic_write_json(output_directory / "_scrape_report.json", {
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "district": args.district,
        "checkpoint_projects": len(all_rows),
        "previously_complete": already_done,
        "attempted": len(pending_rows),
        "succeeded_this_run": total_succeeded,
        "failed_this_run": total_failed,
        "deferred_by_limit": pending_count - len(pending_rows),
        "incomplete_registrations": [r["registration_number"] for r in all_rows
                                     if not is_already_scraped(output_directory, r["registration_number"])],
    })
    return 1 if total_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
