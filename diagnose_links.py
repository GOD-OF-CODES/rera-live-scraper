"""
DIAGNOSTIC ONLY - does not scrape or save anything to your
dataset.

Both attempts to derive a project's details URL from its
registration number's digits failed for the newer
"id/mm/yyyy" registration format. Rather than guess a third
time, this script opens the search results (same one-time
manual CAPTCHA as main_district.py) and dumps the RAW HTML of
a handful of specific rows to a text file, so we can look at
the real <a> tag / onclick / attributes UP-RERA actually uses
for these rows instead of guessing.

Usage:

    python diagnose_links.py "Gautam Buddha Nagar"

It will search, then look for a few known-problem registration
numbers (edit TARGET_REGISTRATION_NUMBERS below if you want to
check different ones) and save their row HTML to:

    diagnostic_output.html

Share that file back and we'll fix the URL resolution based on
what it actually shows, instead of guessing again.
"""

from src.scraper.browser import BrowserManager
from src.scraper.up_rera import UPRERAScraper


# A few of the registration numbers that failed in the last
# scrape run - edit this list if you want to check different
# ones.
TARGET_REGISTRATION_NUMBERS = [
    "UPRERAPRJ467686/09/2025",
    "UPRERAPRJ442226/10/2024",
    "UPRERAPRJ528653/07/2026",
    "UPRERAPRJ477604/04/2026",
]


def main():

    district_name = input(
        "\nEnter District name "
        "(default: Gautam Buddha Nagar): "
    ).strip()

    if not district_name:
        district_name = "Gautam Buddha Nagar"

    browser = BrowserManager(headless=False)

    output_chunks = []

    try:
        page = browser.start()

        scraper = UPRERAScraper(page)

        scraper.open_search_page()

        scraper.select_district(district_name)

        scraper.wait_for_manual_captcha()

        scraper.search_project()

        print(
            "\nSearch completed. Looking for the target rows "
            "across result pages (this may take a moment)...\n"
        )

        grid = page.locator(scraper.GRID_VIEW_ID)

        remaining = set(TARGET_REGISTRATION_NUMBERS)

        page_number = 1

        while remaining:

            print(f"Checking page {page_number}...")

            for registration_number in list(remaining):

                row = grid.locator(
                    f'tr:has(td:text-is('
                    f'"{registration_number}"))'
                ).first

                if row.count() == 0:
                    continue

                html = row.evaluate(
                    "(el) => el.outerHTML"
                )

                print(
                    f"  Found {registration_number} on this "
                    f"page - captured its HTML."
                )

                output_chunks.append(
                    f"\n\n===== {registration_number} =====\n"
                    f"{html}"
                )

                remaining.discard(registration_number)

            if not remaining:
                break

            if not scraper.go_to_next_page():
                print(
                    "\nReached the last page - these targets "
                    "were not found: "
                    f"{sorted(remaining)}"
                )
                break

            page_number += 1

    except Exception as error:
        print(f"\nError: {error}")

    finally:
        browser.close()

    if output_chunks:

        with open(
            "diagnostic_output.html",
            "w",
            encoding="utf-8"
        ) as file:
            file.write("".join(output_chunks))

        print(
            "\nSaved diagnostic_output.html - please share this "
            "file back so the real link format can be fixed "
            "correctly."
        )
    else:
        print("\nNo target rows were captured.")


if __name__ == "__main__":
    main()