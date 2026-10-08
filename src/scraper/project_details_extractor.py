import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote, urljoin

from src.scraper.validation import validate_property_data


class ProjectDetailsExtractor:
    """
    Extracts and structures project information from
    the UP-RERA project details page.

    The extractor first reads the actual rendered controls/tables
    and then converts them into a clean property-data schema.
    """

    def __init__(self, page):
        self.page = page
        self._snapshot = None

    # =========================================================
    # PAGE SNAPSHOT (PERFORMANCE)
    # =========================================================

    def _get_snapshot(self) -> Dict[str, Any]:
        """
        Read the entire page's form fields, tables, and links in
        a SINGLE browser round-trip, and cache the result.

        The extraction methods below used to each independently
        re-scan the DOM (page.locator("table"), then loop over
        every row and every cell with a separate .inner_text()
        call per cell). A details page can have dozens of tables
        and hundreds of form controls, and there were up to 7
        separate methods doing this - so a single project could
        cost several thousand individual Playwright round-trips.
        Across 1000+ projects that adds up to millions of round
        trips, which is the main reason detail-scraping was slow.

        Doing the same walk once, in native JS via page.evaluate,
        turns that into one round-trip per project page. Every
        extraction method below reads from this cached snapshot
        instead of touching the live page again.
        """

        if self._snapshot is not None:
            return self._snapshot

        self._snapshot = self.page.evaluate(
            """
            () => {
                function cellText(el) {
                    return (
                        el.innerText
                        || el.textContent
                        || ''
                    )
                        .replace(/\\u00a0/g, ' ')
                        .trim();
                }

                const fields = [];

                document
                    .querySelectorAll(
                        'input, textarea, select, span[id], label[id]'
                    )
                    .forEach((el) => {
                        if (el.tagName === 'INPUT' && el.type === 'hidden') return;

                        let value = '';

                        if (
                            el.tagName.toLowerCase()
                            === 'select'
                        ) {
                            const opt = el.querySelector(
                                'option:checked'
                            );
                            value = opt ? cellText(opt) : '';
                        } else {
                            value = (
                                el.value != null
                                    ? String(el.value)
                                    : cellText(el)
                            );
                        }

                        fields.push({
                            id: el.getAttribute('id') || '',
                            name: el.getAttribute('name') || '',
                            type: (
                                el.getAttribute('type')
                                || el.tagName.toLowerCase()
                            ),
                            value: value,
                        });
                    });

                const tables = [];

                document
                    .querySelectorAll('table')
                    .forEach((table) => {
                        if (table.querySelector('table')) return;

                        const rows = [];

                        table
                            .querySelectorAll('tr')
                            .forEach((tr) => {
                                if (tr.closest('table') !== table) return;
                                const cells = Array.from(tr.cells).map(cellText);

                                rows.push(cells);
                            });

                        tables.push(rows);
                    });

                const links = [];

                document
                    .querySelectorAll('a')
                    .forEach((a) => {
                        if (!a.closest('[id^="ctl00_ContentPlaceHolder1_"]')) return;
                        links.push({
                            text: cellText(a),
                            href: (
                                a.getAttribute('href') || ''
                            ),
                        });
                    });

                return {
                    body_text: cellText(document.body),
                    fields: fields,
                    tables: tables,
                    links: links,
                };
            }
            """
        )

        return self._snapshot

    # =========================================================
    # BASIC UTILITIES
    # =========================================================

    @staticmethod
    def clean_text(value: Any) -> str:
        """
        Normalize whitespace and remove unnecessary spaces.
        """

        if value is None:
            return ""

        value = str(value)

        value = value.replace("\xa0", " ")

        value = re.sub(r"\s+", " ", value)

        return value.strip()

    @staticmethod
    def clean_optional(value: Any) -> Optional[str]:
        """
        Convert empty / placeholder values into None.
        """

        value = ProjectDetailsExtractor.clean_text(value)

        if not value:
            return None

        if value.lower() in {
            "-",
            "--",
            "n/a",
            "na",
            "not applicable",
            "select",
            "--select--",
        }:
            return None

        return value

    # =========================================================
    # PAGE METADATA
    # =========================================================

    def get_page_metadata(self) -> Dict[str, str]:

        return {
            "url": self.page.url,
            "title": self.clean_text(
                self.page.title()
            ),
        }

    # =========================================================
    # FORM FIELD EXTRACTION
    # =========================================================

    def _get_control_value(self, element) -> str:
        """
        Safely retrieve value from input, textarea or select.
        """

        try:

            tag = element.evaluate(
                "(el) => el.tagName.toLowerCase()"
            )

            if tag == "select":

                selected = element.locator(
                    "option:checked"
                )

                if selected.count() > 0:

                    return self.clean_text(
                        selected.first.inner_text()
                    )

                return ""

            try:
                return self.clean_text(
                    element.input_value()
                )

            except Exception:

                return self.clean_text(
                    element.inner_text()
                )

        except Exception:

            return ""

    def extract_form_fields(self) -> List[Dict[str, Any]]:
        """
        Extract populated controls and labels, including collapsed sections.

        This is an internal representation.
        It will NOT be written directly into final JSON.

        Reads from the cached page snapshot (see _get_snapshot)
        instead of re-scanning the DOM control-by-control.
        """

        return self._get_snapshot()["fields"]

    # =========================================================
    # FIELD INDEX
    # =========================================================

    def _build_field_index(
        self,
        fields: List[Dict[str, Any]]
    ) -> Dict[str, str]:
        """
        Create a lookup:

        field_id -> value
        """

        result = {}

        for field in fields:

            field_id = self.clean_text(
                field.get("id")
            )

            if not field_id:
                continue

            result[field_id] = self.clean_text(
                field.get("value")
            )

        return result

    def _field(
        self,
        field_index: Dict[str, str],
        field_id: str,
        default: Optional[str] = None,
    ) -> Optional[str]:
        """
        Read a specific UP-RERA field.
        """

        value = field_index.get(
            field_id,
            ""
        )

        value = self.clean_optional(
            value
        )

        if value is None:
            return default

        return value

    # =========================================================
    # HEADER INFORMATION
    # =========================================================

    def extract_header_information(
        self
    ) -> Dict[str, Optional[str]]:
        """
        Extract:

        - Project name
        - Project ID
        - Registration date
        - Promoter name
        - Promoter ID

        These values are displayed in the project page header.
        """

        body_text = self.clean_text(
            self._get_snapshot()["body_text"]
        )

        result = {
            "project_name": None,
            "project_id": None,
            "registration_date": None,
            "promoter_name": None,
            "promoter_id": None,
        }

        # -----------------------------------------------------
        # Project Name
        # -----------------------------------------------------

        match = re.search(
            r"Project Name\s*:\s*(.*?)\s+Project Id",
            body_text,
            re.IGNORECASE
        )

        if match:

            result["project_name"] = (
                self.clean_optional(
                    match.group(1)
                )
            )

        # -----------------------------------------------------
        # Project ID
        # -----------------------------------------------------

        match = re.search(
            r"Project Id\s*:\s*\(([^)]+)\)",
            body_text,
            re.IGNORECASE
        )

        if match:

            result["project_id"] = (
                self.clean_optional(
                    match.group(1)
                )
            )

        # -----------------------------------------------------
        # Registration Date
        # -----------------------------------------------------

        match = re.search(
            r"Registration Date\s*:\s*"
            r"(\d{1,2}-\d{1,2}-\d{4})",
            body_text,
            re.IGNORECASE
        )

        if match:

            result["registration_date"] = (
                match.group(1)
            )

        # -----------------------------------------------------
        # Promoter Name
        # -----------------------------------------------------

        match = re.search(
            r"Promoter Name\s*:\s*(.*?)\s+Promoter Id",
            body_text,
            re.IGNORECASE
        )

        if match:

            result["promoter_name"] = (
                self.clean_optional(
                    match.group(1)
                )
            )

        # -----------------------------------------------------
        # Promoter ID
        # -----------------------------------------------------

        match = re.search(
            r"Promoter Id\s*:\s*\(([^)]+)\)",
            body_text,
            re.IGNORECASE
        )

        if match:

            result["promoter_id"] = (
                self.clean_optional(
                    match.group(1)
                )
            )

        return result

    # =========================================================
    # BASIC DETAILS
    # =========================================================

    def extract_basic_details(
        self,
        fields: Dict[str, str]
    ) -> Dict[str, Any]:
        """
        Extract basic project information.

        Field IDs are based on the actual UP-RERA detail page
        observed in the current project extraction.
        """

        return {

            "project_type": self._field(
                fields,
                "ctl00_ContentPlaceHolder1_lblProjectType"
            ),

            "project_category": self._field(
                fields,
                "ctl00_ContentPlaceHolder1_lblProjectCategory"
            ),

            "project_name": self._field(
                fields,
                "ctl00_ContentPlaceHolder1_lblProjectName"
            ),

            "total_area_sq_m": self._field(
                fields,
                "ctl00_ContentPlaceHolder1_lblTotalArea"
            ),

            "registration_fee_rs": self._field(
                fields,
                "ctl00_ContentPlaceHolder1_lblRegistrationFee"
            ),

            "address": self._field(
                fields,
                "ctl00_ContentPlaceHolder1_projetaddress"
            ),

            "village_locality_sector": self._field(
                fields,
                "ctl00_ContentPlaceHolder1_lblVillage"
            ),

            "state": self._field(
                fields,
                "ctl00_ContentPlaceHolder1_lblState"
            ),

            "district": self._field(
                fields,
                "ctl00_ContentPlaceHolder1_ddlDistrict"
            ),

            "tehsil": self._field(
                fields,
                "ctl00_ContentPlaceHolder1_ddlTehsil"
            ),

            "original_start_date": self._field(
                fields,
                "ctl00_ContentPlaceHolder1_lblOriginalStartDate"
            ),

            "proposed_start_date": self._field(
                fields,
                "ctl00_ContentPlaceHolder1_lblStartDate"
            ),

            "project_duration_months": self._field(
                fields,
                "ctl00_ContentPlaceHolder1_lblProjectDuration"
            ),

            "sanctioning_competent_authority": self._field(
                fields,
                "ctl00_ContentPlaceHolder1_ddlAuthority"
            ),

            "project_cost_lakhs": self._field(
                fields,
                "ctl00_ContentPlaceHolder1_lblProjectCost"
            ),

            "proposed_completion_date": self._field(
                fields,
                "ctl00_ContentPlaceHolder1_lblEndDate"
            ),
        }

    # =========================================================
    # LOCATION
    # =========================================================

    def extract_geographic_location(
        self,
        fields: Dict[str, str]
    ) -> Dict[str, Any]:
        """
        Extract the latitude/longitude components exactly as
        provided by the source.

        We do NOT calculate decimal coordinates because the
        source exposes separate coordinate fields and we should
        not invent a conversion.
        """

        return {

            "latitude_part_1": self._field(
                fields,
                "ctl00_ContentPlaceHolder1_lblLat1"
            ),

            "latitude_part_2": self._field(
                fields,
                "ctl00_ContentPlaceHolder1_lblLat2"
            ),

            "longitude_part_1": self._field(
                fields,
                "ctl00_ContentPlaceHolder1_lblLong1"
            ),

            "longitude_part_2": self._field(
                fields,
                "ctl00_ContentPlaceHolder1_lblLong2"
            ),

            "agents": self._field(
                fields,
                "ctl00_ContentPlaceHolder1_lblAgents"
            ),
        }

    # =========================================================
    # OTHER DETAILS
    # =========================================================

    def extract_other_details(
        self,
        fields: Dict[str, str]
    ) -> Dict[str, Any]:

        return {

            "contractor": {
                "name": self._field(
                    fields,
                    "ctl00_ContentPlaceHolder1_lblContractorName"
                ),

                "address": self._field(
                    fields,
                    "ctl00_ContentPlaceHolder1_lblContractorAddress"
                ),
            },

            "architect": {
                "name": self._field(
                    fields,
                    "ctl00_ContentPlaceHolder1_lblArchName"
                ),

                "address": self._field(
                    fields,
                    "ctl00_ContentPlaceHolder1_lblArchAddress"
                ),

                "license_number": self._field(
                    fields,
                    "ctl00_ContentPlaceHolder1_lblArchLicNo"
                ),
            },

            "structural_engineer": {
                "name": self._field(
                    fields,
                    "ctl00_ContentPlaceHolder1_lblEnggName"
                ),

                "address": self._field(
                    fields,
                    "ctl00_ContentPlaceHolder1_lblEnggAddress"
                ),
            },

            "project_coordinator_mobile": self._field(
                fields,
                "ctl00_ContentPlaceHolder1_lblMobileNo"
            ),
        }

    # =========================================================
    # DEVELOPMENT WORKS
    # =========================================================

    def extract_development_works(
        self,
        fields: Dict[str, str]
    ) -> Dict[str, Optional[str]]:
        """
        Extract development-work descriptions.

        Empty values are represented as null.
        """

        work_mapping = {

            "demarcation_of_plots":
                "ctl00_ContentPlaceHolder1_"
                "grddevlopmentworkinsert_ctl02_"
                "txtworkdetails",

            "boundary_wall":
                "ctl00_ContentPlaceHolder1_"
                "grddevlopmentworkinsert_ctl03_"
                "txtworkdetails",

            "road_work":
                "ctl00_ContentPlaceHolder1_"
                "grddevlopmentworkinsert_ctl04_"
                "txtworkdetails",

            "footpaths":
                "ctl00_ContentPlaceHolder1_"
                "grddevlopmentworkinsert_ctl05_"
                "txtworkdetails",

            "water_supply":
                "ctl00_ContentPlaceHolder1_"
                "grddevlopmentworkinsert_ctl06_"
                "txtworkdetails",

            "sewer_system":
                "ctl00_ContentPlaceHolder1_"
                "grddevlopmentworkinsert_ctl07_"
                "txtworkdetails",

            "drain":
                "ctl00_ContentPlaceHolder1_"
                "grddevlopmentworkinsert_ctl08_"
                "txtworkdetails",

            "parks":
                "ctl00_ContentPlaceHolder1_"
                "grddevlopmentworkinsert_ctl09_"
                "txtworkdetails",

            "tree_planting":
                "ctl00_ContentPlaceHolder1_"
                "grddevlopmentworkinsert_ctl10_"
                "txtworkdetails",

            "electric_supply_and_street_lighting":
                "ctl00_ContentPlaceHolder1_"
                "grddevlopmentworkinsert_ctl11_"
                "txtworkdetails",

            "community_buildings":
                "ctl00_ContentPlaceHolder1_"
                "grddevlopmentworkinsert_ctl12_"
                "txtworkdetails",

            "sewage_and_sullage_treatment":
                "ctl00_ContentPlaceHolder1_"
                "grddevlopmentworkinsert_ctl13_"
                "txtworkdetails",

            "solid_waste_management":
                "ctl00_ContentPlaceHolder1_"
                "grddevlopmentworkinsert_ctl14_"
                "txtworkdetails",

            "water_conservation":
                "ctl00_ContentPlaceHolder1_"
                "grddevlopmentworkinsert_ctl15_"
                "txtworkdetails",

            "energy_management":
                "ctl00_ContentPlaceHolder1_"
                "grddevlopmentworkinsert_ctl16_"
                "txtworkdetails",

            "fire_protection_and_safety":
                "ctl00_ContentPlaceHolder1_"
                "grddevlopmentworkinsert_ctl17_"
                "txtworkdetails",

            "social_infrastructure_and_public_amenities":
                "ctl00_ContentPlaceHolder1_"
                "grddevlopmentworkinsert_ctl18_"
                "txtworkdetails",

            "emergency_evacuation_services":
                "ctl00_ContentPlaceHolder1_"
                "grddevlopmentworkinsert_ctl19_"
                "txtworkdetails",

            "other_miscellaneous_work":
                "ctl00_ContentPlaceHolder1_"
                "grddevlopmentworkinsert_ctl20_"
                "txtworkdetails",
        }

        result = {}

        for key, field_id in work_mapping.items():

            result[key] = self._field(
                fields,
                field_id
            )

        return result

    # =========================================================
    # BANK DETAILS
    # =========================================================

    def extract_bank_details(
        self,
        fields: Dict[str, str]
    ) -> Dict[str, Optional[str]]:

        return {

            "account_number": self._field(
                fields,
                "ctl00_ContentPlaceHolder1_lblAccNo"
            ),

            "account_holder_name": self._field(
                fields,
                "ctl00_ContentPlaceHolder1_lblAccName"
            ),

            "bank_name": self._field(
                fields,
                "ctl00_ContentPlaceHolder1_lblBankName"
            ),

            "branch_address": self._field(
                fields,
                "ctl00_ContentPlaceHolder1_lblBranchAddress"
            ),

            "branch_name": self._field(
                fields,
                "ctl00_ContentPlaceHolder1_lblBranchName"
            ),

            "ifsc_code": self._field(
                fields,
                "ctl00_ContentPlaceHolder1_lblIFSCCode"
            ),
        }

    # =========================================================
    # TABLE EXTRACTION
    # =========================================================

    def extract_tables(self) -> List[List[List[str]]]:
        """
        Extract leaf data tables, including collapsed sections.

        This is used internally for detecting structured
        Khasra, registry and document rows.

        Reads from the cached page snapshot (see _get_snapshot)
        instead of re-scanning every table/row/cell live.
        """

        all_tables = []

        for raw_rows in self._get_snapshot()["tables"]:

            table_rows = []

            for raw_row in raw_rows:

                values = [
                    self.clean_text(value)
                    for value in raw_row
                ]

                if values:
                    table_rows.append(values)

            if table_rows:
                all_tables.append(table_rows)

        return all_tables

    # =========================================================
    # DOWNLOAD URL RESOLUTION
    # =========================================================

    # UP-RERA document links are ASP.NET LinkButtons whose href
    # is just a `__doPostBack(...)` trigger, not a real URL.
    #
    # Clicking them (and trying to recover via expect_download /
    # expect_page / expect_navigation + go_back) was tried, but
    # go_back() after an ASP.NET postback does not reliably
    # return to the same page/state. In practice it either lands
    # on the wrong page or loses the DOM the rest of the
    # extraction depends on - which is why documents after the
    # first one went missing, and quarterly_progress links (which
    # run after extract_documents) came back empty too.
    #
    # The actual download endpoint UP-RERA uses turned out to be
    # a stable, predictable pattern that just takes the uploaded
    # file name as a query parameter:
    #
    #     https://up-rera.in/ViewDocument?Param=<file_name>
    #
    # Since the file name is already read from the table cell,
    # we can build this URL directly with no clicking at all -
    # which is both correct and leaves the page state untouched
    # for every extraction step that runs afterward.

    DOCUMENT_DOWNLOAD_URL = (
        "https://up-rera.in/ViewDocument?Param={file_name}"
    )

    def _build_download_url(
        self,
        file_name: str
    ) -> Optional[str]:

        file_name = self.clean_text(file_name)

        if not file_name:
            return None

        return self.DOCUMENT_DOWNLOAD_URL.format(
            file_name=quote(file_name)
        )

    # =========================================================
    # DOCUMENTS
    # =========================================================

    def extract_documents(self) -> List[Dict[str, Any]]:
        """
        Extract uploaded documents from the Documents Uploaded
        section.

        We identify document rows by looking for PDF/document
        filenames and their surrounding table row, resolve its download URL without navigating away.
        """

        documents = []

        for raw_rows in self._get_snapshot()["tables"]:

            table_text = self.clean_text(
                " ".join(
                    value
                    for row in raw_rows
                    for value in row
                )
            )

            if (
                "Document Name" not in table_text
                or "Uploaded File Name"
                not in table_text
            ):
                continue

            for raw_row in raw_rows:

                values = [
                    self.clean_text(value)
                    for value in raw_row
                ]

                if len(values) < 5:
                    continue

                # Expected structure:
                #
                # SNo
                # Document Name
                # Uploaded File Name
                # Uploaded Date
                # Upload Doc Type
                # Download

                if not values[0].isdigit():
                    continue

                file_name = values[2]

                if not re.search(
                    r"\.(pdf|jpg|jpeg|png)$",
                    file_name,
                    re.IGNORECASE
                ):
                    continue

                document = {
                    "serial_number": int(
                        values[0]
                    ),

                    "document_name": values[1],

                    "file_name": file_name,

                    "uploaded_date": values[3],

                    "document_type": values[4],
                }

                # -----------------------------------------
                # Build the real download URL directly from
                # the file name, instead of reading the
                # link's href (which is just a
                # __doPostBack() call) or clicking it (which
                # triggers a page reload that breaks the
                # rest of the extraction).
                # -----------------------------------------

                document["download_url"] = (
                    self._build_download_url(
                        file_name
                    )
                )

                documents.append(
                    document
                )

        # Remove duplicates
        unique = []

        seen = set()

        for document in documents:

            key = (
                document.get("serial_number"),
                document.get("file_name")
            )

            if key in seen:
                continue

            seen.add(key)

            unique.append(
                document
            )

        return unique

    # =========================================================
    # KHASRA DETAILS
    # =========================================================

    def extract_khasra_details(self) -> List[Dict[str, Any]]:
        """
        Extract the old Khasra / Plot records.

        The current UP-RERA page exposes these records in a
        table with:

        Sr. No.
        Khasra/Plot Number
        Area
        Type
        Document
        """

        records = []

        for raw_rows in self._get_snapshot()["tables"]:

            text = self.clean_text(
                " ".join(
                    value
                    for row in raw_rows
                    for value in row
                )
            )

            modern = "Khasra No" in text and "Khasra Area" in text
            if not modern and not ("Khasra/Plot Number" in text and "Area" in text):
                continue

            for raw_row in raw_rows:

                values = [
                    self.clean_text(value)
                    for value in raw_row
                ]

                if len(values) < 3:
                    continue

                if not values[0].isdigit():
                    continue

                # Skip header rows
                if (
                    values[0].lower()
                    in {
                        "sr. no.",
                        "sno."
                    }
                ):
                    continue

                record = {
                    "serial_number": int(
                        values[0]
                    ),

                    "khasra_plot_number": (
                        values[2] if modern else values[1]
                    ),

                    "area_sq_m": (
                        values[3] if modern else values[2]
                    ),

                    "type": (
                        values[1] if modern else values[3]
                        if len(values) > 3
                        else None
                    ),
                }

                records.append(
                    record
                )

        # Deduplicate
        unique = []

        seen = set()

        for record in records:

            key = (
                record["serial_number"],
                record["khasra_plot_number"],
                record["area_sq_m"]
            )

            if key in seen:
                continue

            seen.add(key)

            unique.append(
                record
            )

        return unique

    # =========================================================
    # REGISTRY DETAILS
    # =========================================================

    def extract_registry_details(
        self
    ) -> List[Dict[str, Any]]:
        """
        Extract Registry / Agreement records.
        """

        records = []

        for raw_rows in self._get_snapshot()["tables"]:

            text = self.clean_text(
                " ".join(
                    value
                    for row in raw_rows
                    for value in row
                )
            )

            if "Document Name" in text and "Uploaded Document" in text and "Number" in text and "Date" in text:
                for row in raw_rows:
                    values = [self.clean_text(value) for value in row]
                    if len(values) >= 5 and values[0].isdigit():
                        records.append({
                            "serial_number": int(values[0]),
                            "registry_agreement_number": values[2] or None,
                            "registry_agreement_date": values[3] or None,
                            "document_type": values[1] or None,
                            "file_name": values[4] or None,
                            "download_url": self._build_download_url(values[4]),
                        })
                continue

            if (
                "Registry/Agreement Number"
                not in text
            ):
                continue

            for raw_row in raw_rows:

                values = [
                    self.clean_text(value)
                    for value in raw_row
                ]

                if len(values) < 4:
                    continue

                if not values[0].isdigit():
                    continue

                record = {
                    "serial_number": int(
                        values[0]
                    ),

                    "registry_agreement_number": (
                        values[1]
                    ),

                    "registry_agreement_date": (
                        values[2]
                    ),

                    "land_type": (
                        values[3]
                    ),

                    "registry_agreement_area": (
                        values[4]
                        if len(values) > 4
                        else None
                    ),
                }

                records.append(
                    record
                )

        unique = []

        seen = set()

        for record in records:

            key = (
                record[
                    "serial_number"
                ],
                record[
                    "registry_agreement_number"
                ],
                record[
                    "registry_agreement_date"
                ]
            )

            if key in seen:
                continue

            seen.add(key)

            unique.append(
                record
            )

        return unique

    # =========================================================
    # PLAN / UNIT DETAILS
    # =========================================================

    def extract_plan_and_unit_details(
        self
    ) -> Dict[str, Any]:
        """
        Extract visible plan/unit table information.

        This section intentionally keeps records as structured
        arrays because different projects can have different
        numbers/types of units.
        """

        result = {
            "plan_records": [],
            "unit_records": [],
            "villa_plot_records": [],
        }

        for raw_rows in self._get_snapshot()["tables"]:

            text = self.clean_text(
                " ".join(
                    value
                    for row in raw_rows
                    for value in row
                )
            )

            # -------------------------------------------------
            # Unit details
            # -------------------------------------------------

            if (
                ("Unit Carpet Area" in text or "Floor Number" in text)
                and
                "Number of Apartment"
                in text
            ):

                result[
                    "unit_records"
                ].extend(
                    self._extract_generic_data_rows(
                        raw_rows
                    )
                )

            # -------------------------------------------------
            # Villa / Plot
            # -------------------------------------------------

            if (
                "Type Of Plot"
                in text
                and
                "Area Of Plot"
                in text
            ):

                result[
                    "villa_plot_records"
                ].extend(
                    self._extract_generic_data_rows(
                        raw_rows
                    )
                )

            # -------------------------------------------------
            # Plan details
            # -------------------------------------------------

            if (
                "Permit Number"
                in text
                and
                "Permit Date"
                in text
            ):

                result[
                    "plan_records"
                ].extend(
                    self._extract_generic_data_rows(
                        raw_rows
                    )
                )

        return result

    def _extract_generic_data_rows(
        self,
        raw_rows: List[List[str]]
    ) -> List[List[str]]:
        """
        Return non-empty table rows while removing obvious
        header/instruction rows.

        raw_rows is the already-extracted [[cell_text, ...], ...]
        matrix for one table, taken from the cached page snapshot
        (see _get_snapshot) rather than re-read from the live page.
        """

        result = []

        for raw_row in raw_rows:

            values = [
                self.clean_text(value)
                for value in raw_row
            ]

            if not any(values):
                continue

            if not values[0].isdigit():
                continue

            # Don't save obvious headings
            joined = " ".join(
                values
            ).lower()

            if (
                "save & add more" in joined
                or "click here to add" in joined
                or "in case of commercial" in joined
            ):
                continue

            result.append(
                values
            )

        return result

    # =========================================================
    # QUARTERLY PROGRESS
    # =========================================================

    def extract_progress_links(
        self
    ) -> List[Dict[str, Optional[str]]]:

        results = []

        for raw_link in self._get_snapshot()["links"]:

            text = self.clean_text(
                raw_link.get("text", "")
            )

            href = raw_link.get("href", "") or ""

            if not text:
                continue

            if (
                "progress" in text.lower()
                or
                "certificate" in text.lower()
            ):

                if not href or href.lower().startswith(("javascript:", "#")):
                    continue
                href = urljoin(self.page.url, href)

                results.append(
                    {
                        "name": text,
                        "url": href or None,
                    }
                )

        # Remove duplicates
        unique = []

        seen = set()

        for item in results:

            key = (
                item["name"],
                item["url"]
            )

            if key in seen:
                continue

            seen.add(key)

            unique.append(
                item
            )

        return unique

    # =========================================================
    # CLEAN EMPTY VALUES
    # =========================================================

    def remove_empty_values(
        self,
        data: Any
    ) -> Any:
        """
        Recursively remove empty dictionary values.

        None / empty strings are removed.

        Empty lists are kept because they tell us that a section
        was checked but contained no records.
        """

        if isinstance(data, dict):

            cleaned = {}

            for key, value in data.items():

                value = self.remove_empty_values(
                    value
                )

                if value is None:
                    continue

                if value == "":
                    continue

                cleaned[key] = value

            return cleaned

        if isinstance(data, list):

            return [
                self.remove_empty_values(
                    item
                )
                for item in data
            ]

        return data

    # =========================================================
    # FINAL STRUCTURED EXTRACTION
    # =========================================================

    def extract_structured(
        self, expected_registration: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Main method.

        Produces the clean JSON structure that will be used by
        the rest of the AI Property Due-Diligence system.
        """

        print(
            "\nExtracting structured property data..."
        )

        # -----------------------------------------------------
        # Raw internal extraction
        # -----------------------------------------------------

        raw_fields = (
            self.extract_form_fields()
        )

        field_index = (
            self._build_field_index(
                raw_fields
            )
        )

        # -----------------------------------------------------
        # Structured extraction
        # -----------------------------------------------------

        header = (
            self.extract_header_information()
        )

        basic_details = (
            self.extract_basic_details(
                field_index
            )
        )

        location = (
            self.extract_geographic_location(
                field_index
            )
        )

        other_details = (
            self.extract_other_details(
                field_index
            )
        )

        development_works = (
            self.extract_development_works(
                field_index
            )
        )

        bank_details = (
            self.extract_bank_details(
                field_index
            )
        )

        khasra_details = (
            self.extract_khasra_details()
        )

        registry_details = (
            self.extract_registry_details()
        )

        # extract_documents() builds each download URL directly
        # from the file name (no clicking involved), so it has
        # no effect on page state and can safely run in any
        # order relative to the other extraction steps.
        documents = (
            self.extract_documents()
        )

        plan_and_units = (
            self.extract_plan_and_unit_details()
        )

        progress_links = (
            self.extract_progress_links()
        )

        # -----------------------------------------------------
        # Final schema
        # -----------------------------------------------------

        structured = {

            "source": "UP-RERA",

            "page": self.get_page_metadata(),

            "identification": {

                "project_name": (
                    header["project_name"]
                ),

                "project_id": (
                    header["project_id"]
                ),

                "registration_date": (
                    header[
                        "registration_date"
                    ]
                ),
            },

            "promoter": {

                "name": (
                    header["promoter_name"]
                ),

                "promoter_id": (
                    header["promoter_id"]
                ),
            },

            "basic_details": (
                basic_details
            ),

            "geographic_location": (
                location
            ),

            "plan_and_unit_details": (
                plan_and_units
            ),

            "other_details": (
                other_details
            ),

            "development_works": (
                development_works
            ),

            "bank_details": (
                bank_details
            ),

            "land_details": {

                "khasra_plot_details": (
                    khasra_details
                ),

                "registry_agreement_details": (
                    registry_details
                ),
            },

            "documents": documents,

            "quarterly_progress": {
                "links": progress_links
            },
        }

        structured = (
            self.remove_empty_values(
                structured
            )
        )

        validate_property_data(structured, expected_registration)

        print(
            "Structured extraction completed."
        )

        print(
            "Documents found:",
            len(documents)
        )

        print(
            "Khasra records found:",
            len(khasra_details)
        )

        print(
            "Registry records found:",
            len(registry_details)
        )

        return structured

    # =========================================================
    # RAW PAGE TEXT
    # =========================================================

    def save_page_text(
        self,
        registration_number: str,
        output_directory: str = "data/raw"
    ) -> Path:
        """
        Save readable page text for debugging.

        This is NOT included in the final JSON.
        """

        output_dir = Path(
            output_directory
        )

        output_dir.mkdir(
            parents=True,
            exist_ok=True
        )

        text = self.page.locator(
            "body"
        ).inner_text()

        text = self.clean_text(
            text
        )

        file_path = (
            output_dir
            / f"{registration_number}_details.txt"
        )

        file_path.write_text(
            text,
            encoding="utf-8"
        )

        print(
            "\nReadable page text saved to:"
        )

        print(file_path)

        return file_path