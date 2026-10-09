# Live Property Due Diligence Scraper

The main application retrieves a requested project **directly from RERA at request
time**. It does not require PostgreSQL, a district dataset, a saved project index,
or an existing JSON result. It does not automatically save project information.
Current source support is **Uttar Pradesh RERA**.

## Start

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m playwright install chromium
.venv/bin/python main.py
```

Open **http://127.0.0.1:8000**. On Windows, activate `.venv\Scripts\Activate.ps1`
and use `python` in place of `.venv/bin/python`. No `.env`, database credentials,
LLM service, or district preload is needed.

Use `python main.py --port 8002` to select another local port.

## Live workflow

1. Enter any remembered project name, builder, city, or address with city (for
   example `Oro City`, `ACE INFRACITY`, or `Sector 150 Noida`). A full RERA
   registration number or official details URL also works.
2. For name/registration searches, the application loads a fresh search session
   from RERA and shows its CAPTCHA. Enter the displayed characters.
3. Select the intended project from the possible matches. Names and builders
   use the live source form. City aliases such as Noida map to the official district.
   Addresses/localities with a recognized city or district check live details in
   groups of 12, with up to six concurrent lightweight HTTP checks. These read
   only identity and location fields, including the separate village/sector field,
   without launching browsers or extracting unit/document tables. Full extraction
   runs only for the selected project. The browser continues automatically until every candidate has been checked,
   showing accumulated matches and progress without a load-more button. Failed
   pages get up to three attempts; unresolved failures are labelled incomplete. Results show the address for disambiguation; they are possible
   matches, not proof that a vague description identifies a unique property.
   Common locality aliases (such as Gomti Nagar and Indirapuram) also work.
   For an unrecognized locality, include its city. Search coverage depends on
   what RERA publishes; landmark proximity/geocoding is not available.
4. The scraper resolves the internal project ID from that live source response
   and fetches the selected project's details immediately.
5. The page displays the extracted fields, documents, land/deed records, plan/unit
   records, official source URL, and retrieval time.

A known official `https://up-rera.in/Frm_View_Project_Details.aspx?id=...` URL can
be fetched directly, without a separate search. Its internal ID must come from
the source; registration-number digits are **not** a reliable internal ID.

Every new search/fetch contacts RERA again. Source errors are shown explicitly;
there is no fallback to previously saved project data. RERA's CAPTCHA and source
availability still apply. “Live” means fetched on request, not continuous monitoring.

## Search by plot or khasra number

Enter a labelled identifier with its city or district, for example:

- `Khasra 123/4 Lucknow`
- `Plot GH-03 Noida`
- `Plot No. 23 Sector 150 Noida`

The same `/api/live/search` endpoint and CAPTCHA workflow support these inputs
locally and on Vercel. A city/district is required because parcel numbers repeat
across locations. Additional locality words narrow matches against the published
project address/locality. Bare numbers are not a dedicated parcel lookup; use
`Plot` or `Khasra` explicitly.

After the CAPTCHA, the scraper checks the projects returned by RERA for the
chosen district in batches of 12, with up to six concurrent HTTP checks. It reads
identifier columns in old/new land tables and explicitly labelled plot-number
columns, including collapsed tables. Plot queries can also match an explicitly
labelled plot number in the project address. Parcel identifiers are matched
exactly (ignoring case and spaces around `/` and `-`): `123` does not match
`1234` or `123/4`, and `GH-03` does not match `GH-030`. Comma-separated identifiers
in a source cell are supported; ranges are not expanded.

Candidates show the matched published identifier and its source. Select a
project to fetch its complete details afresh. A match identifies a possible RERA
project, not an independently verified land parcel or proof of ownership. Some
RERA columns combine khasra/plot identifiers without distinguishing their type.
Coverage is limited to published RERA projects and supported table/address
fields, not all Bhulekh land records; missing or differently formatted source
records may not match. Source failures are retried and labelled incomplete as in
address searches. No land dataset or result cache is persisted.

## Storage behavior

- Returned project records remain in the user's browser until the page is closed
  or replaced. **Download this result** explicitly exports the current JSON.
- Search sessions hold cookies, form state, candidate summaries and scan position in server memory
  only. They are removed after completion/cancellation or expire after 10 minutes.
- The server holds at most eight active searches and four concurrent full detail fetches, plus at most six lightweight address checks.
- API responses use `Cache-Control: no-store`.
- Linked PDFs/images are not downloaded in bulk. A document opens from the source
  only when selected. Document OCR is a separate, older component.
- `data/results/` and PostgreSQL are not read or written by the live application.

## API

Interactive documentation: **http://127.0.0.1:8000/docs**.

Start a fresh lookup:

```http
POST /api/live/search
Content-Type: application/json

{"query":"UPRERAPRJ248777/03/2025"}
```

The response is `captcha_required` with a `session_id` and a CAPTCHA data URL.
Submit that CAPTCHA to the same running API instance:

```http
POST /api/live/search/{session_id}/captcha
Content-Type: application/json

{"captcha":"THE_DISPLAYED_CHARACTERS"}
```

A unique match returns `complete` and a fresh `result`. Multiple matches return
`select_project` and the candidates; choose one with:

```http
POST /api/live/search/{session_id}/project
Content-Type: application/json

{"registration_number":"UPRERAPRJ248777/03/2025"}
```

Other endpoints:

- `POST /api/live/search/{session_id}/refresh-captcha` — refresh the source challenge.
- `DELETE /api/live/search/{session_id}` — cancel a pending search.
- `GET /health` — reports live mode, supported sources, and no database requirement.

Returned records include `fetch_mode: "live"`, `from_cache: false`,
`persisted: false`, and `scraped_at`. The existing `property_data` schema is
retained for downstream consumers. No due-diligence conclusion is generated by
this scraper interface; it exposes the source records.

Run a single API worker for local in-memory CAPTCHA sessions. The Vercel deployment
uses encrypted request-carried sessions instead, so requests can reach different instances.
Additional state RERA portals require their own search/detail adapters; this
code does not claim all-India coverage yet.

## Implementation

- `main.py` — default launcher for the live application.
- `src/live_api.py` — request-driven API and session cleanup.
- `src/live_dashboard.html` — live search, CAPTCHA, candidate selection, result/export UI.
- `src/scraper/live.py` — fresh source search and per-project fetch; no database/cache access.
- `src/scraper/project_links.py` — authoritative internal ID resolution from RERA ViewState.
- `src/scraper/detail_page.py` — live page loading and response validation.
- `src/scraper/project_details_extractor.py` — structured extraction, including collapsed tables.
- `src/scraper/validation.py` — project identity/basic-data validation.

## Tests

```bash
.venv/bin/python -m pip install pytest
.venv/bin/python -m pytest tests -q
```

The automated tests use synthetic source responses and local HTML; they do not
need live RERA access, CAPTCHA answers, PostgreSQL, or LLM credentials. They cover
correct internal IDs, new-format registrations, extraction, live request/session
lifecycle, repeated fresh fetches, no disk persistence, and no stale-data fallback.

## Legacy components

The earlier batch/database pipeline remains available as an optional utility;
**the main live application does not call it**:

- `main_district.py` and `scrape_details_parallel.py`: explicitly requested district
  collection/export, including resumable `--refresh-outdated` and `--search-html` repair.
- `db_schema/db/` and `db_schema/scripts/`: optional PostgreSQL loading/export tools.
- `db_schema/api/` and `db_schema/agents/`: the older database-oriented data and
  due-diligence services. These agents have not been converted to live-only analysis.
- `data/results/`: the historical district dataset; unused by live search.
- `backups/`: pre-repair copies retained locally.

The October 2026 scraper repair corrected guessed project IDs, empty successes,
failed-file resume behavior, repeated nested tables, and missing collapsed fields.
Those extraction and identity fixes are shared by the live and optional batch paths.

Automatic address search continuation (internal browser API): `POST /api/live/search/{session_id}/more`.
No full district detail dataset is downloaded or retained. Failed address checks
are retried automatically, up to three attempts and are never reported as definitive non-matches.


## Vercel deployment

`vercel.json` configures the FastAPI entrypoint in `main.py`, the Mumbai region,
and a 300-second per-request limit. The browser automatically continues bounded
address scans across requests; it must remain open during the search.

Set `RERA_SESSION_KEY` to a Fernet key in Vercel environment settings before
building. Generate one with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
Never commit this key. Changing it invalidates active searches.

The hosted app uses direct HTTP extraction of server-rendered pages, with the
same structured extractor and identity validation as the local browser path.
It does not install or launch Chromium. CAPTCHA/session cookies, source form
fields, candidates and scan progress are compressed and encrypted into an opaque
`session_state` response field. The browser returns this field in each continuation
request. It stays only in browser memory and expires after ten minutes of inactivity;
no project database or persistent cache is used. Treat this token as a temporary
search credential. Cancellation drops it from the browser; no server-side revocation
store is maintained, and copies expire automatically.

Source failures, CAPTCHA restrictions and RERA response times still apply.
No data files, backups, local credentials or legacy database services are bundled
into the Vercel app. `.vercelignore` controls the deployment package.

Hosted-session and HTTP extraction checks are included in `tests/test_hosted.py`.
