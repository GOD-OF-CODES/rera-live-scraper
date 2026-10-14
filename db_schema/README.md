# UP-RERA Database Schema Design

## Purpose

This folder is the **database/schema design deliverable** for the UP-RERA scraper, now with a working DB integration layer added on top of it (`db/`, `scripts/`).

Current flow:

UP-RERA or saved snapshots -> full project JSON -> PostgreSQL (via `db/loader.py`) -> collaborator API / agents

These normalized tables are separate from the website's compressed snapshots.
They support collaborator queries and agents; they are not a lossless archive of
every source field. Use the snapshot export/API when you need the complete
original result. Run the commands in this document from `db_schema/` with the
root Python 3.12 virtual environment activated.

The schema was designed from the three project JSON variations currently reviewed:

- UPRERAPRJ14636 — BALAJI GREENS
- UPRERAPRJ12366 — MALL
- UPRERAPRJ4232 — The Hemisphere_Phase-1

## Deliverables

| File / Folder | Purpose |
|---|---|
| `schema_design.md` | Overall tables, relationships and design decisions |
| `data_dictionary.md` | Column-by-column database specification |
| `ui_field_mapping.md` | What should eventually appear on the UI |
| `er_diagram.md` | ER diagram in Mermaid format |
| `schema.sql` | PostgreSQL DDL for a fresh collaborator database |
| `ui_mockup.html` | Static UI mockup to visualize the proposed fields |
| `db/connection.py` | Opens a DB connection using `DATABASE_URL` from `.env` |
| `db/init_db.py` | Applies `schema.sql` to a fresh database |
| `db/loader.py` | Maps scraper JSON into every table per `data_dictionary.md` |
| `scripts/insert_json.py` | Inserts one JSON result file |
| `scripts/backfill_db.py` | Bulk-loads a directory of JSON result files |
| `scripts/export_html_report.py` | Generates a static HTML page with real, clickable links (pgAdmin's data grid can't render clickable links, so use this instead when you want to click through) |
| `db/migrations/001_add_documents_json.sql` | Adds `projects.documents_json`, a denormalized copy of a project's documents for quick viewing without a join |
| `db/migrations/002_project_documents_view.sql` | Adds `project_documents_view` (see "Project Documents section" above) — also added `documents_summary`, which migration 003 then removed |
| `db/migrations/003_remove_documents_summary.sql` | Removes `projects.documents_summary` (dropped in favor of `project_documents_view`) |

## If you already applied schema.sql before this update

Run each migration once, in order, against your existing database (in pgAdmin: open the Query Tool on your database, paste in the contents of the migration file, and execute):

1. `db/migrations/001_add_documents_json.sql`
2. `db/migrations/002_project_documents_view.sql`
3. `db/migrations/003_remove_documents_summary.sql` (only needed if you applied migration 002 before this update)
4. `db/migrations/006_project_name_text.sql` (allows complete project names longer than 255 characters; safe to rerun)

The agent services additionally require migrations 004 and 005 as described in
[agents/README.md](agents/README.md). Apply those once if their tables do not yet
exist. Fresh `schema.sql` already includes the current core schema, but not the
agent tables. Migration 006 preserves the documents view and its explicit grants;
unexpected custom dependent views cause an atomic failure rather than being deleted.

Then re-run `scripts/backfill_db.py` / `scripts/insert_json.py` so `documents_json` gets populated for projects already in your database.

## Viewing clickable links

pgAdmin's table grid always shows URLs as plain text — that's a limitation of the tool itself, not something fixable via schema or data changes. To get real clickable links, run:

```
python -m scripts.export_html_report
```

This creates `reports/projects_report.html`. Open that file in any browser (double-click it, or drag it into a browser tab) to see every project's search URL, details URL, documents, and progress-certificate links as clickable links. Re-run the script any time to refresh it with the latest data.

## Project Documents section

Every project's documents are visible in two ways:

1. **`project_documents` table** — the source of truth, one row per document.
2. **`project_documents_view`** — a VIEW joining `projects` + `project_documents`, so you get `registration_number`, `project_name`, `document_name`, and `document_url` as separate columns, with one row per document, sorted per project. In pgAdmin, this shows up under **Databases → your DB → Schemas → public → Views**, and you browse it exactly like a table (right-click → View/Edit Data → All Rows). This is the recommended way to see "all documents for all projects" in one place.

`projects.documents_json` also carries a denormalized JSON copy of a project's documents directly on the `projects` row, for quick viewing without a join.

## Setup

1. Create a Postgres database, e.g. `createdb up_rera`.
2. `cp .env.example .env` and set `DATABASE_URL`.
3. `pip install -r requirements-db.txt` (on top of the scraper project's own requirements).
4. `python -m db.init_db` — applies `schema.sql` (run once, against a fresh/empty database — see the docstring in `db/init_db.py`).
5. Load data:
   - Single file: `python -m scripts.insert_json path/to/UPRERAPRJ14636.json`
   - Whole directory: `python -m scripts.backfill_db path/to/data/results`

Use an empty development database you own for initial setup. `db.init_db` is not
a migration command for an existing database. The collaborator tools read
`db_schema/.env` or shell `DATABASE_URL`, not the website's `.env.local`.

Input must contain complete `property_data` and its project identification.
Directory summaries and empty detail payloads are rejected before opening a
database connection, preventing placeholder names and misleading empty rows.
From the repository root, export existing snapshots with
`python -m scripts.export_project_snapshots --all`, then return here and run
`python -m scripts.backfill_db ../data/full_project_results`.

Backfill is repeatable: it updates the matching registration rather than creating
another project. It reports loaded, skipped and failed files. Its exit code is 1
if any file fails/is skipped, the directory is missing, or no project JSON exists;
0 means all selected files loaded. Successful files remain committed even if
another file fails, so correct the failed input and rerun. Missing source fields
can legitimately remain NULL; a successful import does not invent missing data.

## Important design decision

Some sections are empty in all currently reviewed JSONs, including:

- `plan_records`
- `unit_records`
- `villa_plot_records`
- `khasra_plot_details`
- `registry_agreement_details`
- `development_works`

Their internal fields cannot be safely invented from empty arrays/objects. The schema therefore keeps these as JSONB extension areas in `project_extensions`. `db/loader.py` inserts a row per section only when that section actually has data — so this table naturally fills in once a project JSON containing real plan/khasra/registry records is scraped. They can be normalized into dedicated child tables once real examples are available.

Two source fields have no column anywhere in this schema yet and are currently dropped by the loader (documented in a comment at the bottom of `db/loader.py`):

- `other_details.project_coordinator_mobile`
- `geographic_location.agents`

## Current scope

The design + integration covers:

- project identity
- promoter
- basic project details
- geographic information
- professionals
- bank details
- project documents
- quarterly-progress links
- variable/unknown sections using JSONB
- source/provenance information
- inserting/updating scraper JSON into PostgreSQL (single file or bulk)

## API and remaining scope

The read API is implemented in `api/main.py`. Install
`pip install -r requirements-api.txt`, then run
`uvicorn api.main:app --port 8002`; browse `/docs`. Agent endpoints are a separate
service documented in `agents/README.md`.

The static UI mockup is not a deployed collaborator frontend. Document processing
has additional dependencies and external access requirements; full document
mirroring and a verified legal-risk assessment are not provided by this schema.
