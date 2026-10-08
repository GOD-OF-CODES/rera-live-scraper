from src.scraper.browser import BrowserManager
from src.scraper.up_rera import UPRERAScraper
from src.scraper.district_dataset import (
    get_district_directory,
    save_summary_rows,
)


def main():

    print("=" * 65)
    print("AI PROPERTY DUE DILIGENCE")
    print("UP-RERA DISTRICT PROJECT LISTING")
    print("=" * 65)
    print(
        "\nThis step only searches the district and collects the "
        "list of projects + their details URLs (fast, one-time "
        "manual CAPTCHA)."
    )
    print(
        "Actual project-details scraping happens afterwards, in "
        "parallel, via scrape_details_parallel.py."
    )

    # =========================================================
    # USER INPUT
    # =========================================================

    district_name = input(
        "\nEnter District name "
        "(default: Gautam Buddha Nagar): "
    ).strip()

    if not district_name:
        district_name = "Gautam Buddha Nagar"

    output_directory = get_district_directory(district_name)

    browser = BrowserManager(headless=False)

    try:

        # =====================================================
        # START BROWSER
        # =====================================================

        page = browser.start()

        scraper = UPRERAScraper(page)

        # =====================================================
        # OPEN SEARCH PAGE
        # =====================================================

        scraper.open_search_page()

        # =====================================================
        # SELECT DISTRICT
        # =====================================================

        scraper.select_district(district_name)

        # =====================================================
        # MANUAL CAPTCHA
        # =====================================================

        scraper.wait_for_manual_captcha()

        # =====================================================
        # SEARCH
        # =====================================================

        scraper.search_project()

        # =====================================================
        # COLLECT ALL SUMMARY ROWS ACROSS ALL RESULT PAGES
        # =====================================================

        summary_rows = list(
            scraper.iterate_all_result_rows()
        )

        print(
            f"\nTotal projects found in {district_name}: "
            f"{len(summary_rows)}"
        )

        checkpoint_file = save_summary_rows(
            output_directory,
            district_name,
            summary_rows
        )

        print("\n" + "=" * 65)
        print("PROJECT LISTING SAVED")
        print("=" * 65)

        print(f"\nDistrict: {district_name}")
        print(f"Projects found: {len(summary_rows)}")
        print(f"Checkpoint file: {checkpoint_file.resolve()}")

        print(
            "\nNext step - scrape all project details in "
            "parallel (headless, no further CAPTCHA needed):"
        )

        print(
            f"\n    python scrape_details_parallel.py "
            f"\"{district_name}\" --workers 6"
        )

    except Exception as error:

        print("\n" + "=" * 65)
        print("SCRAPER ERROR")
        print("=" * 65)

        print(f"\n{type(error).__name__}: {error}")

    finally:

        print(
            "\nPress ENTER to close browser..."
        )

        input()

        browser.close()


if __name__ == "__main__":
    main()
