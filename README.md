# UP-RERA project search

Search the database for project names, builders, registration numbers, districts,
sectors, addresses, plot numbers and khasra numbers. Opening a match loads its
**complete saved details from the database**, even when UP-RERA is unavailable.
The same fields, tables, document links and JSON download are preserved. Each result
shows when the source was retrieved; saved data is never labelled live.

## Start locally

Use **Python 3.12** (the version used for the clean-install checks). Dependencies
are pinned in `requirements.txt`, with optional tooling pinned by
`constraints.txt`; install through the requirements files below.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m playwright install chromium
cp .env.example .env.local
# Configure your database or supply the local data files described below.
python main.py
```

On Windows, create the environment with `py -3.12 -m venv .venv`, activate it
with `.venv\Scripts\Activate.ps1`, and copy the template with
`Copy-Item .env.example .env.local`. The remaining Python commands are the same.

Open http://127.0.0.1:8000. Use `python main.py --port 8002` for another port.
Set `RERA_DATABASE_URL` (or `DATABASE_URL`) in the ignored `.env.local` to use Neon.
Use a pooled PostgreSQL connection URL with TLS. If no URL is configured, the app
uses `data/rera_search.sqlite` when present; otherwise it supports live search only.
Do not put credentials in Git or the browser. Database credentials are configured
locally in `.env.local` and in Vercel environment variables for deployments.

### Handing the repository to a collaborator

The repository contains code and schema, **not database contents or credentials**.
To reproduce saved-data searches, a collaborator needs one of:

- An authorized PostgreSQL connection to the populated Neon database, supplied
  privately as `RERA_DATABASE_URL`. Website reads need SELECT access to the search
  tables, catalog view and `rera_project_snapshots`; maintenance needs additional
  write/schema permissions. A GitHub invitation does not grant Neon access.
- Copies of both `data/rera_search.sqlite` and `data/project_snapshots.sqlite`,
  placed at those paths with no PostgreSQL URL configured. These provide local
  saved-data search and details without connecting to Neon.

Do not send your `.env.local` as part of a code archive. Give each collaborator
appropriate database access separately. Without a populated database, the app
starts in live-only mode and cannot reproduce saved search results during a RERA
outage. PDFs remain external links even when project details are stored locally.

After setup, check `/health` and `/api/catalog/coverage`, then search a known
registration and open its full details. An empty database needs a data import;
creating the tables alone does not populate them.

## How search works

1. Enter `Sector 150 Noida`, a name, builder, registration, `Plot GH-03 Noida`,
   or `Khasra 123/4 Lucknow`. Indexed searches do not contact RERA or ask for a CAPTCHA.
2. The database returns possible matches, addresses, matching parcel evidence and
   the date each source page was inspected. Results are paginated, 100 per page.
3. Open a project in a new tab. The server reads and losslessly decompresses its
   latest successful database snapshot. It displays the same project fields, land
   records, unit tables and document links, with the original source timestamp.
   Missing snapshots produce an explicit message; normal reads never contact RERA.
4. Use **Search RERA live** to check for newer or missing records. This uses RERA's
   normal CAPTCHA and scans source pages when the query needs address/parcel checks.
   Matches remain openable while the original tab continues searching.

Search is token-based and uses SQL indexes, not a live scan of thousands of pages.
`Sector 150` does not match `Sector 1500`. `Sec.150` is recognized. Noida and Greater
Noida map to Gautam Buddha Nagar. Exact parcel matching preserves `/` and `-`:
`123` does not match `123/4` or `1234`; `GH-03` does not match `GH-030`. Comma-separated
source identifiers are supported; ranges are not expanded. Indexed matching does
not perform geocoding, proximity search or fuzzy spelling correction.

A city is optional for a **database** parcel search; adding a district/village
helps distinguish repeated numbers. The live parcel scan still requires a city
or district to bound its work. RERA sometimes publishes combined khasra/plot
columns; their labels are retained rather than inventing a more precise type.
An explicit row type takes precedence over duplicate combined headings. Sector
labels inside parcel cells are excluded from parcel identifiers and remain
available through area search. Untyped combined records remain ambiguous.

Coverage means the projects returned by the public UP-RERA directory at collection
time, not every land parcel or every historical registration. `/api/catalog/coverage`
reports directory size, inspected projects, district counts and refresh dates.
A directory-only project can match its name, builder or district, but its address
and parcel fields remain unavailable until inspected. Zero matches do not prove
that a property does not exist. Source failures remain pending for a later retry.

## Database and refresh

The same search schema works locally with SQLite and online with Neon PostgreSQL.
The application uses these search tables:

| Table | Contents |
| --- | --- |
| `rera_search_projects` | Registration, project name, promoter, district, tehsil, address, locality, sectors, project type, official URL, directory timestamp, source-check timestamp and original parcel evidence |
| `rera_search_tokens` | Indexed search tokens linked to registration numbers |
| `rera_search_parcels` | Separate `kind` (`plot`/`khasra`), exact identifier and registration columns |
| `rera_search_metadata` | Directory provenance and index build dates |

For a single SQL view with separate `plot_numbers` and `khasra_numbers` columns,
query `rera_search_catalog`. For example:

```sql
SELECT registration_number, project_name, district, address, locality,
       sectors, plot_numbers, khasra_numbers, source_checked_at
FROM rera_search_catalog
WHERE district = 'Gautam Buddha Nagar';
```

The schema is idempotent. Unrelated database tables are not dropped or modified.
A summary-only or older import cannot overwrite newer inspected fields. Normal
public API requests only read the database; imports run through local maintenance
commands and the daily updater, outside Vercel's request time limit.

Collect a fresh all-UP directory through the official search form and its CAPTCHA:

```bash
python -m scripts.collect_search_directory
```

Then inspect the official project links and build the local database:

```bash
python -m scripts.refresh_search_catalog --workers 6
python -m scripts.build_search_catalog
```

To correct an existing parcel index using saved full source records, without
requesting RERA again:

```bash
python -m scripts.reindex_search_parcels --publish
```

This builds `data/rera_search_corrected.sqlite` separately, then atomically
publishes only the search tables. It preserves full snapshots and collaborator
tables. `build_search_catalog` also applies these classifications when
`data/project_snapshots.sqlite` is available (`--snapshots` selects another file),
so rebuilding from older checkpoints does not restore the incorrect types.

The refresh writes atomic per-project checkpoints in `data/search_catalog/` and
resumes after interruptions. It skips pages checked in the last seven days by
default; use `--max-age-hours 0` to force a refresh. Failed pages are tried four
times, with increasing delays and fresh HTTP sessions after the first failure.
The maintenance job allows 60 seconds for source reads; change these limits with
`--attempts` and `--read-timeout`. `_refresh_report.json` records each project's
outcome, attempt count, error types and HTTP status when available, including
errors recovered by a retry. Reports are checkpointed every 50 completed projects.
Missing pages are retried on the next run. Four concurrent source requests are
used by default (configurable, capped at 12). These jobs can take substantial time;
user searches query their completed index instead of waiting for the job.

Publish the completed local index to the configured Neon database:

```bash
python -m scripts.build_search_catalog --publish
```

For a long refresh, `python -m scripts.refresh_search_catalog --workers 6 --publish`
also publishes progress every 250 attempted pages and at completion. A failed
publish retains the local checkpoints for retry. There is no public write/admin
endpoint. The daily updater runs separately in GitHub Actions.

Publishing uses PostgreSQL COPY in one transaction. Existing readers see the
previous index until commit; a failed upload rolls back. It replaces only the
four search tables above. The local SQLite database and source checkpoints stay
outside Git. Recollect the directory periodically to discover new registrations;
refreshing known links alone cannot discover newly listed projects.

## API

`POST /api/live/search` with `{"query":"Sector 150 Noida"}` returns database
matches when configured: `status: "select_project"`, `source: "database"`, `total`,
`projects`, `coverage`, `elapsed_ms` and `next_offset`. Send `offset` for another
page. The historical endpoint name is retained for client compatibility.

Use `{"query":"Sector 150 Noida", "live":true}` for the source/CAPTCHA flow.
With a configured database, an official
`https://up-rera.in/Frm_View_Project_Details.aspx?id=...` URL reads a saved snapshot.
Only an explicit `live: true` request uses RERA. Without any configured database,
the existing standalone live mode remains available. Internal IDs come from RERA's response; registration digits are
**not** reliable internal project IDs.

Live continuation endpoints:

- `POST /api/live/search/{session_id}/captcha` with `captcha`.
- `POST /api/live/search/{session_id}/refresh-captcha`.
- `POST /api/live/search/{session_id}/more` for the next scan batch.
- `POST /api/live/search/{session_id}/project` with `registration_number`.
- `DELETE /api/live/search/{session_id}` to discard a search.

`GET /health` reports configured mode; `GET /api/catalog/coverage` checks the
catalog. Interactive API documentation is at `/docs`. Database errors produce an
explicit 503 and the UI retains the live-search option. They do not silently start
a lengthy source scan. Missing snapshots return 404 (`snapshot_unavailable`);
database read/integrity failures return 503. `GET /api/projects/{registration_number}`
returns the same `complete` result envelope as opening a project, including
registrations containing `/`. Coverage includes snapshot count, uncompressed JSON
bytes, compressed payload bytes, and oldest/newest retrieval dates.

## Vercel

`vercel.json` deploys FastAPI from `main.py` in Mumbai with a 300-second request
limit. Configure Neon `DATABASE_URL` and `RERA_SESSION_KEY` in Vercel before deploying.
The Neon Marketplace integration can supply the database variables automatically.
Use a pooled TLS URL. Never copy production credentials into frontend code.

The hosted app reads saved details from Neon. Explicit live requests extract
server-rendered pages over HTTP without launching Chromium. CAPTCHA state is compressed and encrypted with the Fernet session key,
returned as `session_state`, and supplied with continuation requests. Sessions
expire after ten minutes. Local development uses one worker with in-memory state.
Responses use `Cache-Control: no-store`; the search index and detail snapshots are persistent.
Documents/PDFs are fetched from RERA only when opened, not bulk-downloaded.

## Complete project snapshots

`rera_project_snapshots` stores one latest successful result per registration. Its
`payload` is UTF-8 JSON, compactly serialized and compressed with zlib level 9 in a
PostgreSQL BYTEA (SQLite BLOB locally). This preserves every extracted value,
including unknown fields, lists, unit inventories, bank details and document URLs.
It stores no duplicated normalized copies, previous versions, source HTML or PDF
binaries. Raw size and SHA-256 checks detect corrupted payloads before serving.
Document/PDF links still require the source website when clicked.

Backfill known official directory links and publish resumable progress to Neon:

```bash
python -m scripts.backfill_project_snapshots --workers 8 --publish
```

This identity-checks each full source response, saves compressed local checkpoints
in `data/project_snapshots.sqlite`, and publishes every 25 successful records.
It retries failed source requests up to four times with fresh connections. Three
consecutive connection/service failures stop scheduling additional pages, so an
outage does not cause requests across the entire directory. Reruns
skip successful records and first upload any local snapshots that were not yet
published. Failures are recorded in `data/project_snapshots.report.json` and cause
a nonzero exit status; they never erase a good snapshot. It refreshes known project
URLs; collect a fresh directory separately to discover newly registered projects.

To refresh snapshots older than seven days, run manually or from a trusted job:

```bash
python -m scripts.backfill_project_snapshots --workers 8 --max-age-days 7 --publish
```

The daily updater described below checks known projects each morning. Read
requests never refresh the data.
An older worker cannot overwrite newer data. Search-index publication only replaces
its four search tables and leaves snapshots and collaborator tables intact. Local
full-detail storage is separate from the local search index. Without a PostgreSQL
URL, the app automatically reads `data/project_snapshots.sqlite` when present;
`RERA_SNAPSHOT_PATH` can select another local snapshot file.

## Daily update agent

[Daily UP-RERA update](.github/workflows/daily-rera-update.yml) runs every day at
**06:00 IST** (`30 0 * * *` UTC) on GitHub Actions, independently of your Mac and
Vercel. Configure the repository secret **`RERA_UPDATER_DATABASE_URL`** with an
authorized connection to the populated Neon database. It needs SELECT/INSERT/
UPDATE on snapshots and updater tables, SELECT/INSERT/UPDATE/DELETE on the search
tables, and CREATE for the two updater tables on the first run. Do not commit the
connection URL. The workflow runs only on `main`, with one update job at a time.

1. Read all known project registrations and official detail URLs from Neon.
2. Fetch each project's public detail page once, using the same extractor as live
   results. Derive search fields from that same response. Four workers, request
   delays and at most three attempts bound the load on RERA.
3. Compare SHA-256 hashes of the exact source JSON values, including unknown
   fields and document links. Request/delivery timestamps are excluded; whitespace,
   types, field values and array order are retained. No LLM rewrites the data.
4. If changed, replace the latest compressed full result and update its names,
   address, area tokens and plot/khasra index **in one transaction**. Old search
   tokens are removed. A failed write rolls back both details and index.
5. If unchanged, retain the original compressed snapshot and retrieval timestamp;
   record the successful check separately. The first run also aligns the search
   index with the fetched source. It does not duplicate full project versions.
6. On a timeout, CAPTCHA, wrong identity or other source error, retain the saved
   result. Repeated service/access failures stop new requests; incomplete runs
   exit unsuccessfully and report unattempted projects. Old/unchecked records are
   prioritized next time. Failed requests never mean a project should be deleted.

Run manually from GitHub's **Actions → Daily UP-RERA update → Run workflow**.
Manual dispatch defaults to a read-only dry run; set `dry_run=false` to publish.
`limit=0` checks all indexed projects. The scheduled run always publishes changes.
For local use, with `.env.local` configured:

```bash
python -m scripts.update_rera_database --dry-run --limit 5
python -m scripts.update_rera_database
# Optional: --database /path/to/populated-local.sqlite
```

The job summary and a 14-day report artifact show counts and changed section names,
without publishing project payloads or database secrets. Neon also records
`rera_update_state` (latest attempt, successful check, content change and hashes)
and `rera_update_runs` (run summaries). The report defaults to the ignored
`data/daily_update_report.json`. A partial run is never reported as complete.
The job stops scheduling new source reads after 150 minutes and has a 180-minute
host limit; committed progress survives interruption.

Scope is the projects in `rera_search_projects`. The all-project directory still
requires a human CAPTCHA: use `collect_search_directory` and the documented
catalog import/publish workflow to add new registrations. The updater then checks
them too. It checks extracted project fields and links, **not the contents of a PDF
replaced behind an unchanged URL**. It does not synchronize separate collaborator
databases; collaborators can re-export and backfill the updated snapshots.

GitHub schedules can be delayed or dropped, and public-repository schedules are
disabled after 60 days without repository activity. Monitor the Actions page and
the latest `rera_update_runs` entry; re-enable the workflow if GitHub disables it.
See [GitHub's scheduling rules](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).

Collaborators can read `GET /api/projects/{registration_number}`, use
`ProjectSnapshots(configured_catalog()).get(registration_number)` in Python, or
export ordinary full JSON accepted by the existing loader:

```bash
python -m scripts.export_project_snapshots --registration UPRERAPRJ256261
python -m scripts.export_project_snapshots --all
# Optional local source: --database data/project_snapshots.sqlite
```

Exports go to `data/full_project_results/`. Unlike raw BYTEA values in a SQL grid,
these commands/API responses decompress the payload and preserve the original
`property_data` structure. Then, from `db_schema/`, collaborators can run:

```bash
python -m scripts.backfill_db ../data/full_project_results
```

That optional normalized import uses additional storage and writes to the database
configured for the collaborator tools. The website needs only the search index and
compressed snapshots; it does not require the normalized copies.

## Collaborator database and agent workflow

`db_schema/` is maintained for collaborators. It contains the detailed project
schema, migrations, JSON loader, backfill commands, API, and agent services. It is
separate from the website's `rera_search_*` index and excluded from Vercel builds.
Being unused by the website does **not** make these tools unused by the team.

For the detailed-data import tools:

```bash
python -m pip install -r db_schema/requirements-db.txt
cd db_schema
python -m scripts.insert_json /path/to/full-project-result.json
# Or import a directory containing full individual project results:
python -m scripts.backfill_db /path/to/full-project-results
```

Before importing, configure `DATABASE_URL` in the shell environment or the ignored
`db_schema/.env` to point to the intended database (including Neon when appropriate).
These collaborator tools do not automatically load the website's `.env.local`.
Follow [the database setup and migration instructions](db_schema/README.md) to
prepare the detailed tables. Do not reinitialize an existing database blindly.

Imports need **full project result JSON**, not the lightweight files in
`data/search_catalog/`. Restoring the tools does not backfill data or create tables
automatically. See [the agent documentation](db_schema/agents/README.md) for agent
setup and dependencies.

When cleaning up this repository, preserve collaborator commands, schema files,
migrations, loaders, and agent interfaces. Check their workflows and confirm with
their owners before removing them; website-only tests are not sufficient evidence
that a module is unused.

## Verification and code

```bash
python -m pip install -r requirements-dev.txt
python -m playwright install chromium
python -m pytest tests -q
```

Tests use local fixtures; they cover authoritative ID mapping, exact identifiers,
sector boundaries, coverage/paging, invalid imports, query safety, index failure,
CAPTCHA continuation and opening independent project tabs during a search.

For real PostgreSQL loader, migration, backfill and API/agent integration checks:

```bash
python -m pip install -r db_schema/agents/requirements-agents.txt
export TEST_DATABASE_URL=postgresql://USER:PASSWORD@localhost/isolated_test_db
python -m pytest tests -q
```

Use a disposable development database. These tests create and drop their own
randomly named schemas; they do not use `RERA_DATABASE_URL`. Without
`TEST_DATABASE_URL`, PostgreSQL checks are explicitly skipped. Agent smoke checks
use deterministic direct mode; they do not verify an external LLM, real external
land-record searches, or OCR. The external land-record adapter is currently a
mock. OCR additionally needs the system Tesseract executable; LLM mode needs its
own configured provider/server. See the collaborator docs for these prerequisites.

- `src/search_catalog.py`: schema, normalization, ingestion and indexed queries.
- `src/live_api.py`, `src/live_dashboard.html`: API and search/detail UI.
- `src/scraper/live.py`: live searches, identity validation, fast location/parcel parsing.
- `scripts/`: collect, resume, build and publish the search catalog.
