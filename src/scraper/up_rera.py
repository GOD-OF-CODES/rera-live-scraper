import re
from typing import Optional

from playwright.sync_api import Page
from src.scraper.project_links import (DETAILS_URL, normalize_details_url,
    normalize_registration, project_ids_from_viewstate)


class UPRERAScraper:
    """
    Handles interaction with the UP-RERA project search page.
    """

    SEARCH_URL = "https://up-rera.in/View_projects.aspx"
    DETAILS_URL = "https://up-rera.in/Frm_View_Project_Details.aspx?id={}"

    DISTRICT_SELECT_ID = (
        "#ctl00_ContentPlaceHolder1_DdlprojectDistrict"
    )

    GRID_VIEW_ID = (
        "#ctl00_ContentPlaceHolder1_GridView1"
    )

    def __init__(self, page: Page):
        self.page = page
        self._project_ids = {}

    # ---------------------------------------------------------
    # SEARCH PAGE
    # ---------------------------------------------------------

    def open_search_page(self):
        print("\nOpening UP-RERA search page...")

        self.page.goto(
            self.SEARCH_URL,
            wait_until="domcontentloaded",
            timeout=60000
        )

        self.page.wait_for_timeout(3000)

        print("Search page opened.")
        print("URL:", self.page.url)

    # ---------------------------------------------------------
    # REGISTRATION NUMBER INPUT
    # ---------------------------------------------------------

    def find_registration_input(self):
        selectors = [
            "#ContentPlaceHolder1_txtRegNo",
            "input[name*='Reg']",
            "input[id*='Reg']",
            "input[placeholder*='Registration']"
        ]

        for selector in selectors:
            try:
                locator = self.page.locator(selector)

                for index in range(locator.count()):
                    element = locator.nth(index)

                    if not element.is_visible():
                        continue

                    attributes = " ".join(
                        [
                            element.get_attribute("id") or "",
                            element.get_attribute("name") or "",
                            element.get_attribute("placeholder") or ""
                        ]
                    ).lower()

                    if (
                        "reg" in attributes
                        or "registration" in attributes
                    ):
                        return element

            except Exception:
                continue

        # Final fallback:
        # inspect visible text inputs
        inputs = self.page.locator(
            "input[type='text'], input:not([type])"
        )

        for index in range(inputs.count()):
            element = inputs.nth(index)

            try:
                if element.is_visible():
                    return element
            except Exception:
                continue

        return None

    def fill_registration_number(
        self,
        registration_number: str
    ):
        registration_number = (
            registration_number.strip().upper()
        )

        input_box = self.find_registration_input()

        if not input_box:
            raise RuntimeError(
                "Registration number input field "
                "could not be found."
            )

        input_box.fill(registration_number)

        self.page.wait_for_timeout(500)

        print(
            f"Registration number entered: "
            f"{registration_number}"
        )

    # ---------------------------------------------------------
    # DISTRICT DROPDOWN (district-wide search)
    # ---------------------------------------------------------

    def select_district(self, district_name: str):
        """
        Select a district from the "Select District" dropdown
        on the search page (used for district-wide scraping,
        as opposed to searching by a single registration number).
        """

        district_name = district_name.strip()

        dropdown = self.page.locator(
            self.DISTRICT_SELECT_ID
        )

        if dropdown.count() == 0:
            raise RuntimeError(
                "District dropdown could not be found."
            )

        try:
            dropdown.select_option(
                value=district_name
            )
        except Exception:
            # Fall back to matching by visible label,
            # in case the option value differs slightly
            # from the display text.
            dropdown.select_option(
                label=district_name
            )

        self.page.wait_for_timeout(500)

        print(
            f"District selected: {district_name}"
        )

    # ---------------------------------------------------------
    # CAPTCHA
    # ---------------------------------------------------------

    def wait_for_manual_captcha(self):
        print("\n" + "=" * 55)
        print("CAPTCHA REQUIRED")
        print("=" * 55)
        print(
            "Enter the CAPTCHA manually in the browser."
        )
        print(
            "This scraper does NOT bypass or solve CAPTCHA."
        )

        input(
            "\nPress ENTER after entering CAPTCHA..."
        )

    # ---------------------------------------------------------
    # SEARCH BUTTON
    # ---------------------------------------------------------

    def find_search_button(self):
        candidates = [
            "input[value*='SEARCH']",
            "button:has-text('SEARCH')",
            "input[type='submit']",
            "input[type='button']"
        ]

        for selector in candidates:
            try:
                locator = self.page.locator(selector)

                for index in range(locator.count()):
                    element = locator.nth(index)

                    if not element.is_visible():
                        continue

                    value = (
                        element.get_attribute("value")
                        or ""
                    ).upper()

                    text = (
                        element.inner_text()
                        or ""
                    ).upper()

                    if (
                        "SEARCH" in value
                        or "SEARCH" in text
                    ):
                        return element

            except Exception:
                continue

        return None

    def search_project(self):
        button = self.find_search_button()

        if not button:
            raise RuntimeError(
                "SEARCH button could not be found."
            )

        print("\nSearching project...")

        try:
            button.click()
        except Exception:
            button.evaluate(
                "(element) => element.click()"
            )

        self.page.wait_for_function("""() => {
            const grid = document.querySelector('#ctl00_ContentPlaceHolder1_GridView1');
            return grid && grid.querySelector('td');
        }""", timeout=60000)

        print("Search completed.")
        print("Current URL:", self.page.url)

    # ---------------------------------------------------------
    # PROJECT ROW
    # ---------------------------------------------------------

    def find_project_row(
        self,
        registration_number: str
    ):
        target = normalize_registration(registration_number)
        rows = self.page.locator(self.GRID_VIEW_ID + " tr")
        for index in range(rows.count()):
            row = rows.nth(index)
            label = row.locator('span[id$="_lblRegistrationNo"]')
            if label.count() and normalize_registration(label.inner_text()) == target:
                return row
        return None

    def _read_project_ids(self):
        encoded = self.page.evaluate("""() => {
            const first = document.getElementById('__VIEWSTATE');
            if (!first) return '';
            const count = Number(document.getElementById('__VIEWSTATEFIELDCOUNT')?.value || 1);
            let value = first.value;
            for (let i = 1; i < count; i++) {
                const part = document.getElementById('__VIEWSTATE' + i);
                if (!part) throw new Error('Incomplete split ViewState');
                value += part.value;
            }
            return value;
        }""")
        self._project_ids = project_ids_from_viewstate(encoded)
        return self._project_ids

    # ---------------------------------------------------------
    # RESULT GRID (district-wide search — many rows, no single
    # registration number known in advance)
    # ---------------------------------------------------------

    def extract_all_rows_data(self) -> list:
        """
        Extract summary data for every data row on the CURRENT
        results page in a single browser round-trip.

        This replaces the old approach of calling .inner_text()
        per cell per row (which for ~1000 rows meant ~18,000
        separate Playwright round-trips and could take 15-30+
        minutes to just read one page). A single page.evaluate()
        call pulls all the row/cell/link text out of the DOM at
        once, in native JS, which takes well under a second.
        """

        self._read_project_ids()
        raw_rows = self.page.evaluate(
            """
            () => {
                const grid = document.querySelector(
                    '#ctl00_ContentPlaceHolder1_GridView1'
                );

                if (!grid) return [];

                const rows = Array.from(
                    grid.querySelectorAll('tr')
                );

                const results = [];

                for (const row of rows) {
                    const cells = Array.from(
                        row.querySelectorAll('td')
                    );

                    if (cells.length === 0) continue;

                    const firstCellText = (
                        cells[0].innerText || ''
                    ).trim();

                    if (!/^\\d+$/.test(firstCellText)) continue;

                    const values = cells.map(
                        (c) => (c.innerText || '').trim()
                    );

                    const links = Array.from(
                        row.querySelectorAll('a')
                    )
                        .flatMap((a) => [a.getAttribute('href'), a.getAttribute('onclick')])
                        .filter(Boolean);

                    results.push({ values, links });
                }

                return results;
            }
            """
        )

        rows_data = []

        for raw in raw_rows:
            try:
                rows_data.append(
                    self._build_row_data_from_raw(raw)
                )
            except Exception as error:
                values = raw.get("values", [])
                rows_data.append({
                    "registration_number": values[1] if len(values) > 1 else "",
                    "project_name": values[2] if len(values) > 2 else "",
                    "promoter_name": values[3] if len(values) > 3 else "",
                    "district": values[4] if len(values) > 4 else "",
                    "project_type": values[5] if len(values) > 5 else "",
                    "approval_certificate": values[6] if len(values) > 6 else "",
                    "details_url": None, "link_resolution_error": str(error),
                    "raw_cells": values,
                })
                print("Could not resolve a row:", error)

        return rows_data

    def _build_row_data_from_raw(self, raw: dict) -> dict:
        """
        Turn one {values, links} dict (as produced by the JS in
        extract_all_rows_data) into the same shape extract_row_data
        used to return, so nothing downstream needs to change.
        """

        values = raw.get("values", [])
        links = raw.get("links", [])

        registration_number = (
            values[1] if len(values) > 1 else ""
        ).strip().upper()

        details_url = next((url for link in links
                            if (url := normalize_details_url(link))), None)
        project_id = self._project_ids.get(registration_number)
        if project_id:
            resolved = DETAILS_URL.format(project_id)
            if details_url and details_url != resolved:
                raise ValueError(f"Conflicting detail links for {registration_number}")
            details_url = resolved
        if not details_url:
            raise ValueError(f"No authoritative internal project ID for {registration_number}; "
                             "registration digits cannot be used as a detail URL")

        return {
            "registration_number": registration_number,
            "project_name": (
                values[2] if len(values) > 2 else ""
            ),
            "promoter_name": (
                values[3] if len(values) > 3 else ""
            ),
            "district": (
                values[4] if len(values) > 4 else ""
            ),
            "project_type": (
                values[5] if len(values) > 5 else ""
            ),
            "approval_certificate": (
                values[6] if len(values) > 6 else ""
            ),
            "raw_cells": values,
            "details_url": details_url,
            "details_url_source": "search_viewstate" if project_id else "search_link",
            "internal_project_id": project_id,
        }

    def get_result_data_rows(self):
        """
        DEPRECATED / SLOW: kept only for backward compatibility.
        Use extract_all_rows_data() instead, which does the same
        job in one browser round-trip instead of thousands.

        Return the GridView's data rows only (header and
        pager rows excluded).

        A row is considered a data row if its first cell is a
        plain integer (the "S.No" column).
        """

        grid = self.page.locator(self.GRID_VIEW_ID)

        if grid.count() == 0:
            return []

        rows = grid.locator("tr")

        data_rows = []

        for index in range(rows.count()):
            row = rows.nth(index)

            try:
                cells = row.locator("td")

                if cells.count() == 0:
                    continue

                first_cell = cells.nth(0).inner_text().strip()

                if not first_cell.isdigit():
                    continue

                data_rows.append(row)

            except Exception:
                continue

        return data_rows

    def extract_row_data(self, row) -> dict:
        """
        Extract summary data from a single GridView row, without
        needing the registration number known ahead of time.

        Column layout (see data/raw/up_rera_result.html):
            0 S.No | 1 Reg.Number | 2 Project Name |
            3 Promoter Name | 4 District | 5 ProjectType |
            6 Approval Certificate | 7 View Details |
            8 View Project on Map
        """

        cells = row.locator("td")

        values = []

        for index in range(cells.count()):
            values.append(
                cells.nth(index).inner_text().strip()
            )

        registration_number = (
            values[1] if len(values) > 1 else ""
        ).strip().upper()

        data = {
            "registration_number": registration_number,
            "project_name": (
                values[2] if len(values) > 2 else ""
            ),
            "promoter_name": (
                values[3] if len(values) > 3 else ""
            ),
            "district": (
                values[4] if len(values) > 4 else ""
            ),
            "project_type": (
                values[5] if len(values) > 5 else ""
            ),
            "approval_certificate": (
                values[6] if len(values) > 6 else ""
            ),
            "raw_cells": values,
        }

        data["details_url"] = (
            self.extract_details_url_from_row(
                row,
                registration_number
            )
        )

        return data

    # ---------------------------------------------------------
    # PAGINATION (ASP.NET GridView "Page$N" postback links)
    # ---------------------------------------------------------

    def get_current_page_number(self) -> int:
        grid = self.page.locator(self.GRID_VIEW_ID)

        pager_current = grid.locator(
            "tr td span, tr td b"
        )

        for index in range(pager_current.count()):
            text = pager_current.nth(index).inner_text().strip()

            if text.isdigit():
                return int(text)

        return 1

    def go_to_next_page(self) -> bool:
        """
        Click the next numbered page link in the GridView pager,
        if one exists. Returns True if navigation happened.
        """

        grid = self.page.locator(self.GRID_VIEW_ID)

        current_page = self.get_current_page_number()

        next_page_link = grid.locator(
            f"a:text-is('{current_page + 1}')"
        )

        if next_page_link.count() == 0:
            next_page_link = grid.locator(
                "a:has-text('Next')"
            )

        if next_page_link.count() == 0:
            return False

        try:
            next_page_link.first.click()
        except Exception:
            next_page_link.first.evaluate(
                "(element) => element.click()"
            )

        self.page.wait_for_timeout(3000)

        return True

    def iterate_all_result_rows(self):
        """
        Generator yielding extracted row data for every project
        across every page of the current search results,
        paginating automatically via the GridView pager.
        """

        page_number = 1

        while True:
            print(
                f"\nReading result page {page_number}..."
            )

            rows = self.extract_all_rows_data()

            print(
                f"Found {len(rows)} project(s) on this page."
            )

            for row in rows:
                yield row

            if not self.go_to_next_page():
                break

            page_number += 1

    def extract_project_data(
        self,
        row,
        registration_number: str
    ):
        cells = row.locator("td")

        values = []

        for index in range(cells.count()):
            values.append(
                cells.nth(index).inner_text().strip()
            )

        data = {
            "registration_number": registration_number,
            "project_name": (
                values[2] if len(values) > 2 else ""
            ),
            "promoter_name": (
                values[3] if len(values) > 3 else ""
            ),
            "district": (
                values[4] if len(values) > 4 else ""
            ),
            "project_type": (
                values[5] if len(values) > 5 else ""
            ),
            "approval_certificate": (
                values[6] if len(values) > 6 else ""
            ),
            "raw_cells": values
        }

        return data

    # ---------------------------------------------------------
    # PROJECT ID
    # ---------------------------------------------------------

    def extract_details_url_from_row(self, row, registration_number: str) -> Optional[str]:
        self._read_project_ids()
        project_id = self._project_ids.get(normalize_registration(registration_number))
        if project_id:
            return DETAILS_URL.format(project_id)
        links = row.locator("a").evaluate_all(
            "els => els.flatMap(a => [a.getAttribute('href'), a.getAttribute('onclick')])"
        )
        return next((url for link in links if (url := normalize_details_url(link))), None)

    def open_project_details(
        self,
        registration_number: str,
        row=None
    ):
        details_url = None

        if row:
            details_url = (
                self.extract_details_url_from_row(
                    row,
                    registration_number
                )
            )

        if not details_url:
            raise RuntimeError(
                "Could not determine project details URL."
            )

        # Handle relative URL
        if details_url.startswith("/"):
            details_url = (
                "https://up-rera.in"
                + details_url
            )

        print("\nProject Details URL:")
        print(details_url)

        self.page.goto(
            details_url,
            wait_until="domcontentloaded",
            timeout=60000
        )

        self.page.wait_for_timeout(3000)

        print("\nProject Details page opened.")
        print("Current URL:", self.page.url)

        return details_url