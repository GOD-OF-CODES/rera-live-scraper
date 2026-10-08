from pathlib import Path
import json

from playwright.sync_api import sync_playwright


def main():

    # ---------------------------------------------------------
    # 1. Locate our practice HTML page
    # ---------------------------------------------------------

    html_file = (
        Path(__file__).resolve().parents[2]
        / "tests"
        / "practice_page.html"
    )


    # ---------------------------------------------------------
    # 2. Start Playwright
    # ---------------------------------------------------------

    with sync_playwright() as p:

        # Launch Chromium
        browser = p.chromium.launch(
            headless=False
        )

        # Create a new browser page/tab
        page = browser.new_page()


        # -----------------------------------------------------
        # 3. Open our practice website
        # -----------------------------------------------------

        page.goto(
            html_file.as_uri()
        )

        print("Practice website opened.")


        # -----------------------------------------------------
        # 4. Enter RERA registration number
        # -----------------------------------------------------

        rera_number = "UPRERAPRJ123456"

        page.locator(
            "#registrationNumber"
        ).fill(
            rera_number
        )

        print("RERA number entered:", rera_number)


        # -----------------------------------------------------
        # 5. Click Search
        # -----------------------------------------------------

        page.locator(
            "#searchButton"
        ).click()

        print("Search button clicked.")


        # -----------------------------------------------------
        # 6. Wait for project result
        # -----------------------------------------------------

        page.locator(
            "#projectName"
        ).wait_for()

        print("Project result loaded.")


        # -----------------------------------------------------
        # 7. Extract project information
        # -----------------------------------------------------

        project_name = page.locator(
            "#projectName"
        ).inner_text().strip()


        promoter = page.locator(
            "#promoterName"
        ).inner_text().strip()

        promoter = promoter.replace(
            "Promoter:",
            ""
        ).strip()


        location = page.locator(
            "#location"
        ).inner_text().strip()

        location = location.replace(
            "Location:",
            ""
        ).strip()


        status = page.locator(
            "#status"
        ).inner_text().strip()

        status = status.replace(
            "Status:",
            ""
        ).strip()


        registration_number = page.locator(
            "#registration"
        ).inner_text().strip()

        registration_number = registration_number.replace(
            "Registration Number:",
            ""
        ).strip()


        # -----------------------------------------------------
        # 8. Create structured property data
        # -----------------------------------------------------

        property_data = {

            "registration_number": registration_number,

            "project_name": project_name,

            "promoter_name": promoter,

            "location": location,

            "status": status

        }


        # -----------------------------------------------------
        # 9. Print extracted data
        # -----------------------------------------------------

        print("\n========== PROPERTY DATA ==========")

        print(
            "Registration Number:",
            property_data["registration_number"]
        )

        print(
            "Project Name:",
            property_data["project_name"]
        )

        print(
            "Promoter:",
            property_data["promoter_name"]
        )

        print(
            "Location:",
            property_data["location"]
        )

        print(
            "Status:",
            property_data["status"]
        )

        print(
            "===================================\n"
        )


        # -----------------------------------------------------
        # 10. Create processed data directory
        # -----------------------------------------------------

        output_directory = (
            Path(__file__).resolve().parents[2]
            / "data"
            / "processed"
        )

        output_directory.mkdir(
            parents=True,
            exist_ok=True
        )


        # -----------------------------------------------------
        # 11. JSON output file
        # -----------------------------------------------------

        output_file = (
            output_directory
            / "property.json"
        )


        # -----------------------------------------------------
        # 12. Save property data as JSON
        # -----------------------------------------------------

        with open(
            output_file,
            "w",
            encoding="utf-8"
        ) as file:

            json.dump(
                property_data,
                file,
                indent=4,
                ensure_ascii=False
            )


        print(
            "Property data saved to:",
            output_file
        )


        # -----------------------------------------------------
        # 13. Keep browser open
        # -----------------------------------------------------

        input(
            "\nPress Enter to close the browser..."
        )


        # -----------------------------------------------------
        # 14. Close browser
        # -----------------------------------------------------

        browser.close()


if __name__ == "__main__":
    main()