"""Daily source checks and atomic publication of full details plus their search index.

No LLM rewrites data. Hashes compare exact JSON values while ignoring delivery and
request timestamps. Only the latest successful compressed payload is retained.
"""
from contextlib import redirect_stdout
from datetime import datetime, timezone
import hashlib
import io
import json
import time

import requests

from src.project_snapshots import ProjectSnapshots
from src.scraper.http_details import extract_html
from src.scraper.live import SEARCH_URL, official_detail_url, parse_search_fields
from src.scraper.project_links import normalize_registration
from src.scraper.search_intent import resolve_parcels

SCHEMA = '''
CREATE TABLE IF NOT EXISTS rera_update_state (
 registration_number TEXT PRIMARY KEY,
 last_attempt_at TEXT NOT NULL,
 last_checked_at TEXT,
 last_changed_at TEXT,
 content_sha256 TEXT,
 index_sha256 TEXT,
 status TEXT NOT NULL,
 errors_json TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS rera_update_runs (
 run_id TEXT PRIMARY KEY,
 started_at TEXT NOT NULL,
 finished_at TEXT,
 status TEXT NOT NULL,
 report_json TEXT NOT NULL
);
'''
_http = None


def now():
    return datetime.now(timezone.utc).isoformat()


def utc_stamp(value):
    if not value:
        return ''
    stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    return stamp.replace(tzinfo=stamp.tzinfo or timezone.utc).astimezone(timezone.utc).isoformat()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def content_hash(result):
    # property_data includes all source sections, document links and unknown future
    # fields. Do not strip whitespace, reorder arrays or coerce any source values.
    source = {key: result.get(key) for key in ('registration_number', 'project_details_url', 'property_data')}
    return hashlib.sha256(canonical(source).encode('utf-8')).hexdigest()


def index_hash(candidate):
    source = {'row': {k: candidate['row'].get(k) for k in
                     ('registration_number', 'details_url', 'project_name', 'promoter_name', 'district', 'project_type')},
              'fields': candidate['record']['property_data']}
    return hashlib.sha256(canonical(source).encode('utf-8')).hexdigest()


def changed_sections(old, new):
    before = old['property_data'] if old else {}
    after = new['property_data']
    return sorted(k for k in before.keys() | after.keys()
                  if canonical(before.get(k)) != canonical(after.get(k)) or (k in before) != (k in after))


def source_outage(errors):
    return bool(errors) and all(e['type'] in {'ReadTimeout', 'ConnectTimeout', 'ConnectionError', 'Timeout', 'SourceBlocked'}
        or (e['type'] == 'HTTPError' and e.get('http_status') in {403, 429, 500, 502, 503, 504}) for e in errors)


class SourceBlocked(ValueError):
    pass


def parse_candidate(html, row, requested_at, scraped_at):
    reg = normalize_registration(row['registration_number'])
    url = official_detail_url(row['details_url'])
    # Both the full payload and the search fields come from this SAME response.
    try:
        with redirect_stdout(io.StringIO()):
            data = extract_html(html, url, reg)
    except ValueError:
        if any(marker in html.lower() for marker in ('captchaimage', 'under maintenance', 'access denied')):
            raise SourceBlocked('The source requires intervention') from None
        raise
    fields = parse_search_fields(html, reg, include_parcels=True)['property_data']
    identity, basic = data['identification'], data.get('basic_details', {})
    summary = {key: row.get(key, '') for key in
               ('registration_number', 'details_url', 'project_name', 'promoter_name', 'district', 'project_type')}
    summary.update(registration_number=reg, details_url=url, project_name=identity['project_name'],
                   promoter_name=data.get('promoter', {}).get('name') or '',
                   district=basic.get('district') or row.get('district', ''),
                   project_type=basic.get('project_category') or row.get('project_type', ''))
    # Preserve explicit land-record types, including fields whose table headings
    # use an older combined Khasra/Plot label.
    authoritative = []
    for land in data.get('land_details', {}).get('khasra_plot_details', []):
        kind = str(land.get('type') or '').strip().lower()
        if kind in {'khasra', 'plot'} and land.get('khasra_plot_number'):
            authoritative.append({'number': str(land['khasra_plot_number']), 'kinds': [kind],
                                  'explicit_type': True, 'source': 'Published RERA land record: ' + kind.title()})
    fields['search_parcels'] = resolve_parcels(fields.get('search_parcels', []) + authoritative)
    result = dict(source='UP-RERA', fetch_mode='live', from_cache=False, persisted=False,
                  registration_number=reg, project_found=True, project_details_available=True,
                  requested_at=requested_at, scraped_at=scraped_at, search_url=SEARCH_URL,
                  project_details_url=url, search_result=summary, property_data=data)
    ProjectSnapshots.pack(result)
    return {'result': result, 'row': dict(summary, directory_at=row.get('directory_at', scraped_at)),
            'record': dict(summary, indexed_source_at=scraped_at, property_data=fields)}


def fetch_candidate(row, *, attempts=3, delay=0.5, sleep=time.sleep):
    """Bounded retries; HTTP failures, CAPTCHA and invalid pages never reach storage."""
    global _http
    errors = []
    for attempt in range(attempts):
        sleep(delay if attempt == 0 else min(30, 3 * 2 ** (attempt - 1)))
        if _http is None:
            _http = requests.Session()
        try:
            requested_at = now()
            url = official_detail_url(row['details_url'])
            with _http.get(url, timeout=(10, 60)) as response:
                response.raise_for_status()
                if official_detail_url(response.url) != url:
                    raise SourceBlocked('Unexpected source redirect')
                html = response.text
            candidate = parse_candidate(html, row, requested_at, now())
            return candidate, errors
        except Exception as exc:
            detail = {'type': type(exc).__name__}
            if isinstance(exc, requests.HTTPError) and exc.response is not None:
                detail['http_status'] = exc.response.status_code
            errors.append(detail)  # Never log exception text, credentials or payloads.
            _http.close()
            _http = None
    return None, errors


class UpdateStore:
    def __init__(self, catalog):
        self.catalog = catalog
        self.snapshots = ProjectSnapshots(catalog)

    def initialize(self):
        # The existing populated catalog is a prerequisite. Never bootstrap an
        # empty production database or modify collaborator schemas here.
        with self.catalog.connection(write=True) as conn:
            conn.execute('SELECT registration_number FROM rera_search_projects LIMIT 1')
            conn.execute('SELECT registration_number FROM rera_project_snapshots LIMIT 1')
            for statement in SCHEMA.split(';'):
                if statement.strip():
                    conn.execute(statement)

    def rows(self):
        with self.catalog.connection() as conn:
            return [dict(row) for row in conn.execute('''SELECT p.* FROM rera_search_projects p
                LEFT JOIN rera_update_state s ON s.registration_number=p.registration_number
                ORDER BY COALESCE(s.last_checked_at, ''), COALESCE(s.last_attempt_at, ''), p.registration_number''')]

    def _lock(self, conn):
        if self.catalog.postgres:
            # Same transaction lock used by index publication. Compatible with
            # Neon's transaction pool; no session lock can leak to another client.
            conn.execute('SELECT pg_advisory_xact_lock(74239102)')
        else:
            conn.execute('BEGIN IMMEDIATE')

    def apply(self, candidate, errors=()):
        result, row, record = candidate['result'], candidate['row'], candidate['record']
        packed = self.snapshots.pack(result)
        reg, url, checked = packed[:3]
        if (normalize_registration(row['registration_number']) != reg or
                official_detail_url(row['details_url']) != url or
                normalize_registration(record['registration_number']) != reg or
                official_detail_url(record['details_url']) != url):
            raise ValueError('Candidate identity does not match its search index')
        if utc_stamp(record['indexed_source_at']) != checked:
            raise ValueError('Search and detail data must come from the same source check')
        digest, search_digest = content_hash(result), index_hash(candidate)
        with self.catalog.connection(write=True) as conn:
            self._lock(conn)
            project = self.catalog.execute(conn, 'SELECT * FROM rera_search_projects WHERE registration_number=?', (reg,)).fetchone()
            if project is None or official_detail_url(project['details_url']) != url:
                raise ValueError('Candidate is not a known official project')
            old = self.snapshots.get(reg, original=True, connection=conn)
            state = self.catalog.execute(conn, 'SELECT * FROM rera_update_state WHERE registration_number=?', (reg,)).fetchone()
            newest = max(utc_stamp(old['scraped_at']) if old else '',
                         utc_stamp(state['last_checked_at']) if state else '',
                         utc_stamp(project['source_checked_at']))
            if checked <= newest:
                return {'status': 'superseded', 'sections': [], 'index_updated': False}
            changed = old is None or content_hash(old) != digest
            refresh_index = changed or state is None or state['index_sha256'] != search_digest
            if state and (project['source_checked_at'] or '') < (state['last_checked_at'] or ''):
                refresh_index = True
            if changed:
                self.snapshots.put_many([result], connection=conn)
            if refresh_index:
                # Details, tokens, parcel rows and progress commit or roll back together.
                self.catalog.import_rows([row], project['directory_at'], {reg: record}, connection=conn)
            else:
                self.catalog.execute(conn, 'UPDATE rera_search_projects SET source_checked_at=? WHERE registration_number=?', (checked, reg))
            status = 'created' if old is None else 'changed' if changed else 'unchanged'
            last_changed = checked if changed else state['last_changed_at'] if state else None
            self.catalog.execute(conn, '''INSERT INTO rera_update_state
                (registration_number,last_attempt_at,last_checked_at,last_changed_at,content_sha256,index_sha256,status,errors_json)
                VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(registration_number) DO UPDATE SET
                last_attempt_at=excluded.last_attempt_at,last_checked_at=excluded.last_checked_at,
                last_changed_at=excluded.last_changed_at,content_sha256=excluded.content_sha256,
                index_sha256=excluded.index_sha256,status=excluded.status,errors_json=excluded.errors_json''',
                (reg, checked, checked, last_changed, digest, search_digest, status, canonical(errors)))
        return {'status': status, 'sections': changed_sections(old, result) if changed else [], 'index_updated': refresh_index}

    def failed(self, reg, errors):
        with self.catalog.connection(write=True) as conn:
            self.catalog.execute(conn, '''INSERT INTO rera_update_state
                (registration_number,last_attempt_at,status,errors_json) VALUES (?,?,?,?)
                ON CONFLICT(registration_number) DO UPDATE SET last_attempt_at=excluded.last_attempt_at,
                status=excluded.status,errors_json=excluded.errors_json
                WHERE excluded.last_attempt_at > rera_update_state.last_attempt_at''',
                (reg, now(), 'failed', canonical(errors)))

    def save_run(self, report):
        with self.catalog.connection(write=True) as conn:
            self.catalog.execute(conn, '''INSERT INTO rera_update_runs VALUES (?,?,?,?,?)
                ON CONFLICT(run_id) DO UPDATE SET finished_at=excluded.finished_at,
                status=excluded.status,report_json=excluded.report_json''',
                (report['run_id'], report['started_at'], report.get('finished_at'), report['status'], canonical(report)))
