"""
FastAPI app exposing the UP-RERA project data already sitting in
Postgres (populated by scripts/backfill_db.py).

This reuses the SAME connection helper the backfill script uses
(db/connection.py -> DATABASE_URL from .env), so no new DB config
is needed.

Run from inside db_schema/ (same place you run backfill_db.py
from), so the "db" package import below resolves the same way:

    cd db_schema
    pip install -r requirements-api.txt
    uvicorn api.main:app --reload --port 8000

Then open http://127.0.0.1:8000/docs for interactive Swagger UI.
"""

from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from db.connection import get_cursor

app = FastAPI(
    title="UP-RERA Property Due Diligence API",
    description=(
        "Read-only API over the scraped UP-RERA project data."
    ),
    version="1.0.0",
)

# Allow a local frontend (React/Vite dev server, etc.) to call
# this API directly during development. Tighten this to your
# real frontend's origin before deploying anywhere public.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


def mask_account_number(account_number: Optional[str]) -> Optional[str]:
    """
    Never return a full bank account number - show only the
    last 4 digits, same precaution called out in schema.sql.
    """

    if not account_number:
        return account_number

    digits = account_number.strip()

    if len(digits) <= 4:
        return "*" * len(digits)

    return ("*" * (len(digits) - 4)) + digits[-4:]


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/districts")
def list_districts():
    """
    Every district currently in the database, with how many
    projects are stored for each - useful for populating a
    filter dropdown in a frontend.
    """

    with get_cursor(commit=False) as cur:
        cur.execute(
            """
            SELECT
                district,
                COUNT(*) AS project_count
            FROM projects
            WHERE district IS NOT NULL
            GROUP BY district
            ORDER BY district
            """
        )

        return cur.fetchall()


@app.get("/projects")
def list_projects(
    district: Optional[str] = Query(
        None,
        description="Exact district name, e.g. 'Gautam Buddha Nagar'"
    ),
    project_type: Optional[str] = Query(
        None,
        description="e.g. 'Residential' or 'Commercial'"
    ),
    q: Optional[str] = Query(
        None,
        description="Search project name or promoter name"
    ),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """
    Paginated, filterable list of projects. This is the endpoint
    a frontend table/list view would call.
    """

    conditions = []
    params: list = []

    if district:
        conditions.append("p.district = %s")
        params.append(district)

    if project_type:
        conditions.append("p.project_type = %s")
        params.append(project_type)

    if q:
        conditions.append(
            "(p.project_name ILIKE %s OR pr.name ILIKE %s)"
        )
        like_value = f"%{q}%"
        params.extend([like_value, like_value])

    where_clause = (
        ("WHERE " + " AND ".join(conditions))
        if conditions
        else ""
    )

    offset = (page - 1) * page_size

    with get_cursor(commit=False) as cur:

        cur.execute(
            f"""
            SELECT COUNT(*)
            FROM projects p
            LEFT JOIN promoters pr ON pr.id = p.promoter_id
            {where_clause}
            """,
            params,
        )

        total = cur.fetchone()["count"]

        cur.execute(
            f"""
            SELECT
                p.id,
                p.registration_number,
                p.rera_project_id,
                p.project_name,
                p.project_type,
                p.district,
                p.approval_certificate,
                p.registration_date,
                pr.name AS promoter_name,
                p.scraped_at
            FROM projects p
            LEFT JOIN promoters pr ON pr.id = p.promoter_id
            {where_clause}
            ORDER BY p.id
            LIMIT %s OFFSET %s
            """,
            params + [page_size, offset],
        )

        results = cur.fetchall()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "results": results,
    }


@app.get("/projects/{registration_number:path}")
def get_project(registration_number: str):
    """
    Full detail for one project: base fields plus every related
    table (basic details, location, professionals, bank details
    [masked], documents, progress links, and the JSONB
    "extensions" sections such as khasra/registry/unit records).
    """

    with get_cursor(commit=False) as cur:

        cur.execute(
            """
            SELECT
                p.*,
                pr.name AS promoter_name
            FROM projects p
            LEFT JOIN promoters pr ON pr.id = p.promoter_id
            WHERE p.registration_number = %s
            """,
            [registration_number],
        )

        project = cur.fetchone()

        if project is None:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"No project found with registration "
                    f"number '{registration_number}'."
                ),
            )

        project_id = project["id"]

        cur.execute(
            """
            SELECT *
            FROM project_basic_details
            WHERE project_id = %s
            """,
            [project_id],
        )
        project["basic_details"] = cur.fetchone()

        cur.execute(
            """
            SELECT *
            FROM project_locations
            WHERE project_id = %s
            """,
            [project_id],
        )
        project["location"] = cur.fetchone()

        cur.execute(
            """
            SELECT
                professional_type,
                name,
                address,
                license_number,
                contact,
                email
            FROM project_professionals
            WHERE project_id = %s
            ORDER BY id
            """,
            [project_id],
        )
        project["professionals"] = cur.fetchall()

        cur.execute(
            """
            SELECT *
            FROM project_bank_details
            WHERE project_id = %s
            """,
            [project_id],
        )
        bank_details = cur.fetchone()

        if bank_details:
            bank_details["account_number"] = mask_account_number(
                bank_details.get("account_number")
            )

        project["bank_details"] = bank_details

        cur.execute(
            """
            SELECT
                serial_number,
                document_name,
                file_name,
                uploaded_date,
                document_type,
                document_url
            FROM project_documents
            WHERE project_id = %s
            ORDER BY serial_number
            """,
            [project_id],
        )
        project["documents"] = cur.fetchall()

        cur.execute(
            """
            SELECT name, url
            FROM project_progress_links
            WHERE project_id = %s
            ORDER BY id
            """,
            [project_id],
        )
        project["progress_links"] = cur.fetchall()

        cur.execute(
            """
            SELECT section_name, data
            FROM project_extensions
            WHERE project_id = %s
            ORDER BY id
            """,
            [project_id],
        )

        # Fold the section_name/data rows into a single dict,
        # e.g. {"khasra_plot_details": [...], "unit_records": [...]}
        project["extensions"] = {
            row["section_name"]: row["data"]
            for row in cur.fetchall()
        }

    return project
