"""
Maps the scraper's JSON output (the structure written to
data/results/<registration_number>.json) into the tables defined
in ../schema.sql.

Public entry point:

    insert_project_json(data: dict) -> Optional[int]

    Returns the project's internal `projects.id` on success, or
    None if the JSON represents a not-found / failed scrape
    (project_found is False or property_data is missing).

Mapping (see ../data_dictionary.md for the authoritative spec):

    promoters                  <- property_data.promoter
    projects                   <- top-level fields + identification + search_result
    project_basic_details      <- property_data.basic_details        (1:1)
    project_locations          <- property_data.geographic_location  (1:1)
    project_professionals      <- property_data.other_details.{contractor,architect,structural_engineer}  (1:N)
    project_bank_details       <- property_data.bank_details         (1:1)
    project_documents          <- property_data.documents            (1:N)
    project_progress_links     <- property_data.quarterly_progress.links (1:N)
    project_extensions         <- plan_records / unit_records / villa_plot_records /
                                   khasra_plot_details / registry_agreement_details /
                                   development_works, stored as JSONB, one row per
                                   non-empty section (per schema_design.md section 7)

Notes on fields NOT covered by this schema (by design, not an
oversight - the approved schema simply doesn't have a column for
them yet):

    - other_details.project_coordinator_mobile
    - geographic_location.agents

These are skipped. If you want them captured, the cleanest fix is
adding them to project_extensions as an additional section, or
adding columns via a migration - see the note at the bottom of
this file.

Strategy:
    - 1:1 sections use INSERT ... ON CONFLICT (project_id) DO
      UPDATE, since schema.sql already declares project_id UNIQUE
      on those tables.
    - promoters.rera_promoter_id is UNIQUE but nullable, so when a
      promoter has no RERA promoter id we fall back to a manual
      SELECT-then-INSERT keyed on name (no schema change needed).
    - 1:N sections (professionals, documents, progress links,
      extensions) have no unique constraint in the approved
      schema, so they're replaced wholesale per project on every
      save: DELETE existing rows for the project, then INSERT the
      freshly scraped set. This keeps re-scrapes correct without
      requiring a schema migration.
    - Everything for one project runs in a single transaction.
"""

import json
from datetime import datetime
from typing import Any, Dict, Optional

import psycopg2.extras

from db.connection import get_connection


# =================================================================
# PARSING HELPERS
# =================================================================

def parse_date(value: Any) -> Optional[str]:
    """
    UP-RERA dates come as 'DD-MM-YYYY' strings. Convert to
    'YYYY-MM-DD' (what Postgres DATE expects) or None.
    """

    if not value:
        return None

    value = str(value).strip()

    for fmt in ("%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue

    return None


def parse_numeric(value: Any) -> Optional[float]:
    """
    Convert source strings like '1,18,000' or '6500' into a
    float. Returns None (rather than raising) for anything that
    isn't a clean number, since these are free-text fields on the
    source site.
    """

    if value is None:
        return None

    value = str(value).replace(",", "").strip()

    if not value:
        return None

    try:
        return float(value)
    except ValueError:
        return None


# =================================================================
# PROMOTERS
# =================================================================

def _upsert_promoter(cur, rera_promoter_id: Optional[str], name: Optional[str]) -> Optional[int]:

    if not name:
        return None

    if rera_promoter_id:
        cur.execute(
            """
            INSERT INTO promoters (rera_promoter_id, name)
            VALUES (%s, %s)
            ON CONFLICT (rera_promoter_id)
            DO UPDATE SET name = EXCLUDED.name, updated_at = CURRENT_TIMESTAMP
            RETURNING id
            """,
            (rera_promoter_id, name),
        )

        return cur.fetchone()["id"]

    # No rera_promoter_id available - schema.sql has no partial
    # unique index for this case, so dedupe manually by name.
    cur.execute(
        "SELECT id FROM promoters WHERE rera_promoter_id IS NULL AND name = %s",
        (name,),
    )

    row = cur.fetchone()

    if row:
        return row["id"]

    cur.execute(
        "INSERT INTO promoters (rera_promoter_id, name) VALUES (NULL, %s) RETURNING id",
        (name,),
    )

    return cur.fetchone()["id"]


# =================================================================
# PROJECTS (core row)
# =================================================================

def _upsert_project(cur, data: Dict[str, Any], promoter_id: Optional[int]) -> int:

    property_data = data.get("property_data", {}) or {}
    identification = property_data.get("identification", {}) or {}
    search_result = data.get("search_result", {}) or {}
    page = property_data.get("page", {}) or {}

    project_name = (
        identification.get("project_name")
        or search_result.get("project_name")
        or data.get("registration_number")
    )

    documents = property_data.get("documents", []) or []

    cur.execute(
        """
        INSERT INTO projects (
            registration_number, rera_project_id, project_name, project_type,
            district, approval_certificate, registration_date, promoter_id,
            source, search_url, project_details_url, documents_json, scraped_at
        )
        VALUES (
            %(registration_number)s, %(rera_project_id)s, %(project_name)s, %(project_type)s,
            %(district)s, %(approval_certificate)s, %(registration_date)s, %(promoter_id)s,
            %(source)s, %(search_url)s, %(project_details_url)s, %(documents_json)s, CURRENT_TIMESTAMP
        )
        ON CONFLICT (registration_number) DO UPDATE SET
            rera_project_id           = EXCLUDED.rera_project_id,
            project_name                = EXCLUDED.project_name,
            project_type                  = EXCLUDED.project_type,
            district                        = EXCLUDED.district,
            approval_certificate              = EXCLUDED.approval_certificate,
            registration_date                   = EXCLUDED.registration_date,
            promoter_id                           = EXCLUDED.promoter_id,
            source                                  = EXCLUDED.source,
            search_url                                = EXCLUDED.search_url,
            project_details_url                         = EXCLUDED.project_details_url,
            documents_json                                = EXCLUDED.documents_json,
            scraped_at                                      = CURRENT_TIMESTAMP
        RETURNING id
        """,
        {
            "registration_number": data.get("registration_number"),
            "rera_project_id": identification.get("project_id"),
            "project_name": project_name,
            "project_type": search_result.get("project_type"),
            "district": search_result.get("district"),
            "approval_certificate": search_result.get("approval_certificate"),
            "registration_date": parse_date(identification.get("registration_date")),
            "promoter_id": promoter_id,
            "source": data.get("source", "UP-RERA"),
            "search_url": data.get("search_url"),
            "project_details_url": data.get("project_details_url") or page.get("url"),
            "documents_json": json.dumps(documents, ensure_ascii=False) if documents else None,
        },
    )

    return cur.fetchone()["id"]


# =================================================================
# 1:1 SECTIONS
# =================================================================

def _upsert_basic_details(cur, project_id: int, section: Dict[str, Any]):

    cur.execute(
        """
        INSERT INTO project_basic_details (
            project_id, total_area_sq_m, district, tehsil,
            original_start_date, proposed_start_date,
            sanctioning_competent_authority, project_cost_lakhs,
            proposed_completion_date
        )
        VALUES (
            %(project_id)s, %(total_area_sq_m)s, %(district)s, %(tehsil)s,
            %(original_start_date)s, %(proposed_start_date)s,
            %(sanctioning_competent_authority)s, %(project_cost_lakhs)s,
            %(proposed_completion_date)s
        )
        ON CONFLICT (project_id) DO UPDATE SET
            total_area_sq_m                    = EXCLUDED.total_area_sq_m,
            district                             = EXCLUDED.district,
            tehsil                                 = EXCLUDED.tehsil,
            original_start_date                      = EXCLUDED.original_start_date,
            proposed_start_date                        = EXCLUDED.proposed_start_date,
            sanctioning_competent_authority               = EXCLUDED.sanctioning_competent_authority,
            project_cost_lakhs                              = EXCLUDED.project_cost_lakhs,
            proposed_completion_date                          = EXCLUDED.proposed_completion_date
        """,
        {
            "project_id": project_id,
            "total_area_sq_m": parse_numeric(section.get("total_area_sq_m")),
            "district": section.get("district"),
            "tehsil": section.get("tehsil"),
            "original_start_date": parse_date(section.get("original_start_date")),
            "proposed_start_date": parse_date(section.get("proposed_start_date")),
            "sanctioning_competent_authority": section.get("sanctioning_competent_authority"),
            "project_cost_lakhs": parse_numeric(section.get("project_cost_lakhs")),
            "proposed_completion_date": parse_date(section.get("proposed_completion_date")),
        },
    )


def _upsert_location(cur, project_id: int, section: Dict[str, Any]):

    cur.execute(
        """
        INSERT INTO project_locations (
            project_id, latitude_part_1, latitude_part_2,
            longitude_part_1, longitude_part_2
        )
        VALUES (%(project_id)s, %(lat1)s, %(lat2)s, %(long1)s, %(long2)s)
        ON CONFLICT (project_id) DO UPDATE SET
            latitude_part_1   = EXCLUDED.latitude_part_1,
            latitude_part_2     = EXCLUDED.latitude_part_2,
            longitude_part_1      = EXCLUDED.longitude_part_1,
            longitude_part_2        = EXCLUDED.longitude_part_2
        """,
        {
            "project_id": project_id,
            "lat1": section.get("latitude_part_1"),
            "lat2": section.get("latitude_part_2"),
            "long1": section.get("longitude_part_1"),
            "long2": section.get("longitude_part_2"),
        },
    )


def _upsert_bank_details(cur, project_id: int, section: Dict[str, Any]):

    cur.execute(
        """
        INSERT INTO project_bank_details (
            project_id, account_number, account_holder_name,
            bank_name, branch_address, branch_name, ifsc_code
        )
        VALUES (
            %(project_id)s, %(account_number)s, %(account_holder_name)s,
            %(bank_name)s, %(branch_address)s, %(branch_name)s, %(ifsc_code)s
        )
        ON CONFLICT (project_id) DO UPDATE SET
            account_number         = EXCLUDED.account_number,
            account_holder_name      = EXCLUDED.account_holder_name,
            bank_name                  = EXCLUDED.bank_name,
            branch_address               = EXCLUDED.branch_address,
            branch_name                    = EXCLUDED.branch_name,
            ifsc_code                        = EXCLUDED.ifsc_code
        """,
        {
            "project_id": project_id,
            "account_number": section.get("account_number"),
            "account_holder_name": section.get("account_holder_name"),
            "bank_name": section.get("bank_name"),
            "branch_address": section.get("branch_address"),
            "branch_name": section.get("branch_name"),
            "ifsc_code": section.get("ifsc_code"),
        },
    )


# =================================================================
# 1:N SECTIONS (delete + reinsert)
# =================================================================

def _replace_professionals(cur, project_id: int, other_details: Dict[str, Any]):

    cur.execute(
        "DELETE FROM project_professionals WHERE project_id = %s",
        (project_id,),
    )

    roles = {
        "contractor": other_details.get("contractor", {}) or {},
        "architect": other_details.get("architect", {}) or {},
        "structural_engineer": other_details.get("structural_engineer", {}) or {},
    }

    for professional_type, role_data in roles.items():

        name = role_data.get("name")
        address = role_data.get("address")
        license_number = role_data.get("license_number")

        # Skip roles with nothing at all rather than inserting an
        # empty placeholder row for every project.
        if not (name or address or license_number):
            continue

        cur.execute(
            """
            INSERT INTO project_professionals (
                project_id, professional_type, name, address, license_number
            )
            VALUES (%s, %s, %s, %s, %s)
            """,
            (project_id, professional_type, name, address, license_number),
        )


def _replace_documents(cur, project_id: int, documents: list):

    cur.execute(
        "DELETE FROM project_documents WHERE project_id = %s",
        (project_id,),
    )

    for document in documents or []:

        cur.execute(
            """
            INSERT INTO project_documents (
                project_id, serial_number, document_name, file_name,
                uploaded_date, document_type, document_url
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                project_id,
                document.get("serial_number"),
                document.get("document_name"),
                document.get("file_name"),
                parse_date(document.get("uploaded_date")),
                document.get("document_type"),
                document.get("download_url"),
            ),
        )


def _replace_progress_links(cur, project_id: int, links: list):

    cur.execute(
        "DELETE FROM project_progress_links WHERE project_id = %s",
        (project_id,),
    )

    for link in links or []:

        cur.execute(
            """
            INSERT INTO project_progress_links (project_id, name, url)
            VALUES (%s, %s, %s)
            """,
            (project_id, link.get("name"), link.get("url")),
        )


def _replace_extensions(cur, project_id: int, property_data: Dict[str, Any]):
    """
    Stores the sections whose internal shape isn't normalized yet
    (per schema_design.md section 7) as JSONB rows in
    project_extensions - one row per section, and only for
    sections that actually contain data, so this table doesn't
    fill up with empty placeholders for every project.
    """

    cur.execute(
        "DELETE FROM project_extensions WHERE project_id = %s",
        (project_id,),
    )

    plan_and_units = property_data.get("plan_and_unit_details", {}) or {}
    land_details = property_data.get("land_details", {}) or {}
    development_works = property_data.get("development_works", {}) or {}

    sections = {
        "plan_records": plan_and_units.get("plan_records", []),
        "unit_records": plan_and_units.get("unit_records", []),
        "villa_plot_records": plan_and_units.get("villa_plot_records", []),
        "khasra_plot_details": land_details.get("khasra_plot_details", []),
        "registry_agreement_details": land_details.get("registry_agreement_details", []),
        "development_works": development_works,
    }

    for section_name, section_data in sections.items():

        if not section_data:
            continue

        cur.execute(
            """
            INSERT INTO project_extensions (project_id, section_name, data)
            VALUES (%s, %s, %s)
            """,
            (project_id, section_name, json.dumps(section_data, ensure_ascii=False)),
        )


# =================================================================
# PUBLIC ENTRY POINT
# =================================================================

def insert_project_json(data: Dict[str, Any]) -> Optional[int]:
    """
    Inserts/updates one scraper JSON result into the database in
    a single transaction.

    Returns the project's `projects.id` on success, or None if
    the JSON is a not-found / failed scrape (no property_data to
    insert).
    """

    registration_number = data.get("registration_number")

    if not registration_number:
        raise ValueError("data['registration_number'] is required")

    project_found = bool(data.get("project_found", False))
    details_available = bool(data.get("project_details_available", False))

    if not project_found or not details_available:
        print(
            f"Skipping {registration_number}: "
            f"project_found={project_found}, "
            f"project_details_available={details_available}"
        )
        return None

    conn = get_connection()

    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:

            property_data = data.get("property_data", {}) or {}
            promoter_section = property_data.get("promoter", {}) or {}

            promoter_id = _upsert_promoter(
                cur,
                promoter_section.get("promoter_id"),
                promoter_section.get("name"),
            )

            project_id = _upsert_project(cur, data, promoter_id)

            _upsert_basic_details(
                cur, project_id, property_data.get("basic_details", {}) or {}
            )

            _upsert_location(
                cur, project_id, property_data.get("geographic_location", {}) or {}
            )

            _replace_professionals(
                cur, project_id, property_data.get("other_details", {}) or {}
            )

            _upsert_bank_details(
                cur, project_id, property_data.get("bank_details", {}) or {}
            )

            _replace_documents(
                cur, project_id, property_data.get("documents", [])
            )

            _replace_progress_links(
                cur,
                project_id,
                (property_data.get("quarterly_progress", {}) or {}).get("links", []),
            )

            _replace_extensions(cur, project_id, property_data)

        conn.commit()

        return project_id

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


# =================================================================
# NOTE: fields not covered by the approved schema
# =================================================================
#
# other_details.project_coordinator_mobile and
# geographic_location.agents are read from the JSON but have no
# column to go into under this schema. If you want them captured,
# the lowest-friction option is adding them as an extra
# project_extensions section, e.g.:
#
#   sections["other_details_extra"] = {
#       "project_coordinator_mobile": other_details.get("project_coordinator_mobile"),
#       "geographic_agents": geographic_location.get("agents"),
#   }
#
# inside _replace_extensions(), once that's confirmed as the
# desired approach.
