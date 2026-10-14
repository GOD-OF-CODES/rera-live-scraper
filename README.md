# UP-RERA project search

Search the database for project names, builders, registration numbers, districts,
sectors, addresses, plot numbers and khasra numbers. Opening a match loads its
**complete saved details from the database**, even when UP-RERA is unavailable.
The same fields, tables, document links and JSON download are preserved. Each result
shows when the source was retrieved; saved data is never labelled live.

## Start locally

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m playwright install chromium
.venv/bin/python main.py
```

Open http://127.0.0.1:8000. Use `python main.py --port 8002` for another port.
Set `RERA_DATABASE_URL` (or `DATABASE_URL`) in the ignored `.env.local` to use Neon.
Use a pooled PostgreSQL connection URL with TLS. If no URL is configured, the app
uses `data/rera_search.sqlite` when present; otherwise it supports live search only.
Do not put credentials in Git or the browser. Database credentials are configured
locally in `.env.local` and in Vercel environment variables for deployments.

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
commands, outside Vercel's request time limit.

Collect a fresh all-UP directory through the official search form and its CAPTCHA:

```bash
python -m scripts.collect_search_directory
```

Then inspect the official project links and build the local database:

```bash
python -m scripts.refresh_search_catalog --workers 6
python -m scripts.build_search_catalog
```

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
endpoint and no automatic recurring scrape scheduled by the web application.

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

No recurring job is scheduled automatically. Read requests never refresh the data.
An older worker cannot overwrite newer data. Search-index publication only replaces
its four search tables and leaves snapshots and collaborator tables intact. Local
full-detail storage is separate from the local search index. Without a PostgreSQL
URL, the app automatically reads `data/project_snapshots.sqlite` when present;
`RERA_SNAPSHOT_PATH` can select another local snapshot file.

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
python -m pip install pytest
python -m pytest tests -q
```

Tests use local fixtures; they cover authoritative ID mapping, exact identifiers,
sector boundaries, coverage/paging, invalid imports, query safety, index failure,
CAPTCHA continuation and opening independent project tabs during a search.

- `src/search_catalog.py`: schema, normalization, ingestion and indexed queries.
- `src/live_api.py`, `src/live_dashboard.html`: API and search/detail UI.
- `src/scraper/live.py`: live searches, identity validation, fast location/parcel parsing.
- `scripts/`: collect, resume, build and publish the search catalog.
