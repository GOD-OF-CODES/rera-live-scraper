"""
Generates a single static HTML file from the database, with real
clickable links for search_url, project_details_url, document
links, and progress-certificate links.

This exists because pgAdmin's data grid only ever shows plain
text - it cannot render clickable links, no matter what the
column type is. This script is the workaround: it reads straight
from the database and produces a browser-friendly page instead.

Usage (from the db_schema project root):

    python -m scripts.export_html_report

Produces db_schema/reports/projects_report.html - open that file
in any browser (double-click it, or drag it into a browser tab).
Re-run any time to regenerate it with the latest data.
"""

import html
from pathlib import Path

import psycopg2.extras

from db.connection import get_connection

OUTPUT_FILE = Path(__file__).parent.parent / "reports" / "projects_report.html"


def _fetch_projects(cur):

    cur.execute(
        """
        SELECT p.*, pr.name AS promoter_name
        FROM projects p
        LEFT JOIN promoters pr ON pr.id = p.promoter_id
        ORDER BY p.registration_number
        """
    )

    return cur.fetchall()


def _fetch_documents(cur, project_id):

    cur.execute(
        """
        SELECT serial_number, document_name, file_name, document_type, document_url
        FROM project_documents
        WHERE project_id = %s
        ORDER BY serial_number
        """,
        (project_id,),
    )

    return cur.fetchall()


def _fetch_progress_links(cur, project_id):

    cur.execute(
        """
        SELECT name, url
        FROM project_progress_links
        WHERE project_id = %s
        ORDER BY id
        """,
        (project_id,),
    )

    return cur.fetchall()


def _link(url, label=None):
    """
    Returns a safe <a> tag, or a plain '-' if there's no URL.
    """

    if not url:
        return "-"

    safe_url = html.escape(url, quote=True)
    safe_label = html.escape(label or url)

    return f'<a href="{safe_url}" target="_blank" rel="noopener">{safe_label}</a>'


def generate_report():

    conn = get_connection()

    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:

            projects = _fetch_projects(cur)

            rows_html = []

            for project in projects:

                documents = _fetch_documents(cur, project["id"])
                progress_links = _fetch_progress_links(cur, project["id"])

                documents_html = "<br>".join(
                    _link(
                        doc["document_url"],
                        f'{doc["document_name"] or doc["file_name"]} ({doc["file_name"]})',
                    )
                    for doc in documents
                ) or "-"

                progress_html = "<br>".join(
                    _link(link["url"], link["name"]) for link in progress_links
                ) or "-"

                rows_html.append(
                    f"""
                    <tr>
                        <td>{html.escape(project["registration_number"] or "")}</td>
                        <td>{html.escape(project["project_name"] or "")}</td>
                        <td>{html.escape(project["promoter_name"] or "-")}</td>
                        <td>{html.escape(project["district"] or "-")}</td>
                        <td>{_link(project["search_url"], "Search page")}</td>
                        <td>{_link(project["project_details_url"], "Details page")}</td>
                        <td>{documents_html}</td>
                        <td>{progress_html}</td>
                    </tr>
                    """
                )

    finally:
        conn.close()

    page_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>UP-RERA Projects Report</title>
<style>
    body {{ font-family: Arial, sans-serif; margin: 24px; background: #f7f7f9; }}
    h1 {{ margin-bottom: 4px; }}
    .subtitle {{ color: #666; margin-bottom: 20px; }}
    table {{ border-collapse: collapse; width: 100%; background: white; }}
    th, td {{ border: 1px solid #ddd; padding: 8px 10px; text-align: left; vertical-align: top; font-size: 14px; }}
    th {{ background: #2c3e50; color: white; position: sticky; top: 0; }}
    tr:nth-child(even) {{ background: #fafafa; }}
    a {{ color: #1a73e8; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
</style>
</head>
<body>
    <h1>UP-RERA Projects Report</h1>
    <div class="subtitle">{len(projects)} project(s) — generated from the database, links are clickable</div>
    <table>
        <thead>
            <tr>
                <th>Registration Number</th>
                <th>Project Name</th>
                <th>Promoter</th>
                <th>District</th>
                <th>Search URL</th>
                <th>Details URL</th>
                <th>Documents</th>
                <th>Progress / Certificate Links</th>
            </tr>
        </thead>
        <tbody>
            {"".join(rows_html)}
        </tbody>
    </table>
</body>
</html>
"""

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(page_html, encoding="utf-8")

    print(f"Report written to: {OUTPUT_FILE.resolve()}")
    print(f"Projects included: {len(projects)}")
    print("Open that file in your browser to see clickable links.")


if __name__ == "__main__":
    generate_report()
