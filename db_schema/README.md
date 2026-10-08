# UP-RERA Database Schema Design

## Purpose

This folder is the **database/schema design deliverable** for the UP-RERA scraper, now with a working DB integration layer added on top of it (`db/`, `scripts/`).

Current flow:

UP-RERA -> Browser/Scraper -> JSON -> PostgreSQL (via `db/loader.py`) -> API -> UI later

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
| `schema.sql` | PostgreSQL DDL (approved design, unchanged) |
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

## Not included yet

- FastAPI/Flask API
- frontend framework integration
- document downloading/storage
- AI risk scoring

Those are later implementation phases.

