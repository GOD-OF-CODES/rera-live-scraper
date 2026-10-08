# Agentic layer

## Setup (one-time)

```
cd db_schema
pip install -r agents/requirements-agents.txt
```

Add to `.env` (alongside the existing `DATABASE_URL`):

```
ANTHROPIC_API_KEY=sk-ant-...
```

Apply the two new migrations against your DB (same way you applied
the existing ones in `db/migrations/`):

```
psql "$DATABASE_URL" -f db/migrations/004_add_agent_runs.sql
psql "$DATABASE_URL" -f db/migrations/005_add_document_extractions.sql
```

## Folder layout

```
agents/
  common/
    persistence.py     - save_agent_run() / get_agent_runs_for_project()
    tool_runner.py      - generic Claude tool-use loop, shared by every subagent
  property_identification/
    schemas.py           - request/response contract (pydantic + JSON schema)
    tools.py              - DB tool functions the agent calls
    prompt.py             - system prompt
    agent.py               - run(request) -> CanonicalPropertyRecord
    test_manual.py          - smoke test, run directly
  document_processing/      - your teammate's subagent (see below)
    storage.py                - DB read/write, already done
    extractor.py                - process_document() - fill this in
  api.py                        - FastAPI endpoints for all of the above
```

## Run it

```
cd db_schema
uvicorn agents.api:app --reload --port 8001
```

`POST /agents/property-identification`
```json
{"raw_query": "UPRERAPRJ14636"}
```
returns a `CanonicalPropertyRecord` (see `property_identification/schemas.py`).

Or without the API, from Python:
```
cd db_schema
python -m agents.property_identification.test_manual
```

## How this connects to the Document Processing subagent

Property Identification's `tools.py` already calls
`get_project_land_details()`, which reads from `document_extractions`
(migration 005) in addition to the raw RERA fields. That table is
empty until the Document Processing tool writes to it via
`agents/document_processing/storage.save_extraction_result()` - until
then, Property Identification just sees an empty list and carries on
(it does not fail or wait on it).

Once your teammate fills in `extractor.py`'s `process_document()` and
runs the pending queue, Property Identification (and later, Ownership
& Title / Registration & Encumbrance once those are built) will
automatically start seeing that data on the next run - no changes
needed on this side.

## Adding the next subagent

Copy the `property_identification/` folder as a template: same four
files (`schemas.py`, `tools.py`, `prompt.py`, `agent.py`), swap in the
new subagent's own tools and output schema, register its endpoint in
`api.py`. `common/tool_runner.py` and `common/persistence.py` are
already generic enough to reuse as-is.

## Ownership & Title subagent

`agents/ownership_title/` follows the same four-file shape, built as
the second subagent (Registration & Encumbrance, Cross-Verification &
Risk, etc. still to come).

Given a `project_id` and/or `registration_number`
(`OwnershipTitleRequest`), it determines the current owner,
reconstructs the ownership/title chain, and flags gaps and conflicts
in it (`OwnershipTitleRecord`).

| Spec tool name | Implemented as | Backed by |
|---|---|---|
| Document Processing Tool | `get_ownership_title_documents`, `search_title_document_text` | `project_extensions`, `project_documents`, `document_extractions` |
| Web Search Tool | `external_land_record_lookup` | `agents/common/access/` (mock, same as Property Identification) |
| Entity & Property Matching Tool | `match_entity_and_property` | `agents/common/matching_tools.py` (shared) |
| Record Comparison Tool | `compare_records` | `agents/common/matching_tools.py` (shared) |

Plus `resolve_project`, the same kind of plumbing tool
`lookup_project_by_registration_number` is for Property
Identification, so the agent can work from either a `project_id` or a
`registration_number`.

`get_ownership_title_documents` pulls every land record, mutation
record, title document and registered deed currently available for a
project from three places: the raw RERA structured fields
(`project_extensions`), the index of documents that look
title-relevant by name/type (`project_documents`, matched against a
generic keyword list - not any specific project's data), and (for
whichever of those the Document Processing tool has already OCR'd)
their structured fields and raw text (`document_extractions`). Like
Property Identification, this degrades gracefully to an empty result
if Document Processing hasn't reached a project yet - it does not
fail or wait on it.

Run it standalone:
```
cd db_schema
python -m agents.ownership_title.test_manual --registration UPRERAPRJ14636
```
Or via the API: `POST /agents/ownership-title`
```json
{"registration_number": "UPRERAPRJ14636"}
```

## Property Identification's full tool set (as of the tools integration)

All 4 tools named in the subagent spec (Property Identification row)
are now implemented and wired into `property_identification/tools.py`:

| Spec tool name | Implemented as | Backed by |
|---|---|---|
| Entity & Property Matching Tool | `match_entity_and_property` | `agents/common/matching_tools.py` (real, exact-match) |
| Record Comparison Tool | `compare_records` | `agents/common/matching_tools.py` (real, generic field diff) |
| Document Processing Tool | (consumed via `get_project_land_details`) | `agents/document_processing/` - real PDF+OCR pipeline, see below |
| Web Search Tool | `external_land_record_lookup` | `agents/common/access/` - **currently MOCK, see warning below** |

Plus the original 3 DB tools (`lookup_project_by_registration_number`,
`search_projects`, `score_candidate_match`) and `get_project_land_details`
- 7 tools total.

### Document Processing is now REAL, not a stub

`agents/document_processing/extractor.py` no longer just marks
documents as "failed" - it actually downloads each PDF, extracts text
(PyMuPDF), falls back to Tesseract OCR per-page when a page is a scan
rather than real text, and deterministically parses out khasra number,
seller/buyer, dates, area, boundaries, etc. via regex
(`document_processing/pdf/structured_parser.py`). Verified working
end-to-end, including OCR, against a real scanned sale-deed PDF.

**System dependency**: this needs Tesseract OCR installed and on your
PATH, separate from pip. `tesseract --version` should work in your
terminal - if not, see the comment block at the top of
`requirements-agents.txt` for the install command per OS.

Run the extraction queue (processes every document that doesn't have
a `document_extractions` row yet):
```
cd db_schema
python -m agents.document_processing.extractor
```

### `external_land_record_lookup` is a MOCK - read this before using it

`agents/common/access/` is a real request/response framework (source
selection, method selection, standardized status codes), but its only
registered mechanism is `MockAccessMechanism`, which returns 2-3
hardcoded sample records for prototyping - it is NOT connected to any
real government portal. The tool's description and the system prompt
both instruct the model to label any output that used this tool as
"from an unverified mock source" rather than presenting it as fact -
but this is a prompt-level safeguard, not a data guarantee. Don't
trust its output for anything beyond testing the plumbing. A real
implementation belongs to the Land Records & Land Use subagent
(not yet built) and would replace `MockAccessMechanism` with one that
actually calls the UP land record portal - everything that calls
`external_land_record_lookup` today would keep working unchanged once
that swap happens.

### Everything here is dynamic - nothing is hardcoded to a specific project

Every tool takes its inputs as parameters (registration_number,
district, khasra_number, project_id, ...) and queries live from
whatever is in your database at call time. None of this code assumes
Gautam Buddha Nagar specifically, or any particular project - it will
work the same way for any district once that district's data has been
scraped and loaded through your existing pipeline (`main_district.py`
-> `db/loader.py`).
