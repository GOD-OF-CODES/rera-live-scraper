"""Indexed official UP-RERA discovery, with PostgreSQL and local SQLite storage.

Only the offline import/refresh commands write this database. Public requests
use parameterized read queries and fetch project details from RERA on demand.
"""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import sqlite3
import time

from dotenv import load_dotenv
from src.scraper.live import official_detail_url
from src.scraper.project_links import REGISTRATION, normalize_registration
from src.scraper.search_intent import parcel_clues, words, matching_parcels

ROOT = Path(__file__).resolve().parent.parent
SECTOR = re.compile(r'\b(?:sector|sec\.?)\s*[-:]?\s*(\d+[a-z]?)\b', re.I)
STOP = {'find', 'show', 'me', 'project', 'projects', 'property', 'properties',
        'in', 'at', 'near', 'by', 'the', 'please', 'uttar', 'pradesh', 'india'}

SCHEMA = """
CREATE TABLE IF NOT EXISTS rera_search_projects (
 registration_number TEXT PRIMARY KEY,
 project_name TEXT NOT NULL, promoter_name TEXT NOT NULL,
 district TEXT NOT NULL, tehsil TEXT NOT NULL DEFAULT '',
 address TEXT NOT NULL DEFAULT '', locality TEXT NOT NULL DEFAULT '',
 sectors TEXT NOT NULL DEFAULT '[]', project_type TEXT NOT NULL DEFAULT '',
 details_url TEXT NOT NULL, directory_at TEXT NOT NULL,
 source_checked_at TEXT, parcels_json TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS rera_search_district ON rera_search_projects(district);
CREATE TABLE IF NOT EXISTS rera_search_tokens (
 token TEXT NOT NULL, registration_number TEXT NOT NULL
 REFERENCES rera_search_projects(registration_number) ON DELETE CASCADE,
 PRIMARY KEY(token, registration_number)
);
CREATE INDEX IF NOT EXISTS rera_search_tokens_project ON rera_search_tokens(registration_number);
CREATE TABLE IF NOT EXISTS rera_search_parcels (
 kind TEXT NOT NULL, identifier TEXT NOT NULL, registration_number TEXT NOT NULL
 REFERENCES rera_search_projects(registration_number) ON DELETE CASCADE,
 PRIMARY KEY(kind, identifier, registration_number)
);
CREATE INDEX IF NOT EXISTS rera_search_parcels_project ON rera_search_parcels(registration_number);
CREATE TABLE IF NOT EXISTS rera_search_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def aliases(text):
    text = re.sub(r'\b(?:greater\s+)?noida\b', 'gautam buddha nagar', text, flags=re.I)
    text = re.sub(r'\ballahabad\b', 'prayagraj', text, flags=re.I)
    return re.sub(r'\bbanaras\b', 'varanasi', text, flags=re.I)


def tokens(text, query=False):
    sectors = {'sector:' + m[1].lower() for m in SECTOR.finditer(text)}
    text = SECTOR.sub(' ', text) if query else text
    return sectors | (set(words(aliases(text))) - STOP)


def identifiers(value):
    return {re.sub(r'\s+', '', token).upper() for token in
            re.findall(r'[a-z0-9]+(?:\s*[/\-]\s*[a-z0-9]+)*', str(value), re.I)
            if any(c.isdigit() for c in token)}


class Catalog:
    def __init__(self, target):
        self.target = str(target)
        self.postgres = self.target.startswith(('postgres://', 'postgresql://'))

    @contextmanager
    def connection(self, write=False):
        if self.postgres:
            import psycopg
            from psycopg.rows import dict_row
            connection = psycopg.connect(self.target, connect_timeout=8, row_factory=dict_row)
            # Neon transaction pooling rejects statement_timeout in startup options.
            connection.execute("SET LOCAL statement_timeout = '15s'")
        else:
            path = Path(self.target)
            if write:
                path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(str(path) if write else path.resolve().as_uri() + '?mode=ro',
                                         uri=not write, timeout=10)
            connection.row_factory = sqlite3.Row
            connection.execute('PRAGMA foreign_keys=ON')
        try:
            yield connection
            if write:
                connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def execute(self, connection, sql, values=()):
        return connection.execute(sql.replace('?', '%s') if self.postgres else sql, values)

    def initialize(self):
        with self.connection(write=True) as connection:
            for statement in SCHEMA.split(';'):
                if statement.strip():
                    self.execute(connection, statement)
            create = 'CREATE OR REPLACE VIEW' if self.postgres else 'CREATE VIEW IF NOT EXISTS'
            aggregate = 'string_agg' if self.postgres else 'group_concat'
            # A convenient spreadsheet-like view, backed by normalized parcel rows.
            self.execute(connection, f"""{create} rera_search_catalog AS
                SELECT p.*,
                (SELECT {aggregate}(identifier, ', ') FROM
                    (SELECT identifier FROM rera_search_parcels
                     WHERE registration_number=p.registration_number AND kind='plot'
                     ORDER BY identifier) n) AS plot_numbers,
                (SELECT {aggregate}(identifier, ', ') FROM
                    (SELECT identifier FROM rera_search_parcels
                     WHERE registration_number=p.registration_number AND kind='khasra'
                     ORDER BY identifier) n) AS khasra_numbers
                FROM rera_search_projects p""")

    def metadata(self, values):
        with self.connection(write=True) as connection:
            for key, value in values.items():
                self.execute(connection, 'INSERT INTO rera_search_metadata VALUES (?, ?) '
                             'ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                             (key, json.dumps(value)))

    def import_rows(self, rows, directory_at, records=None):
        """One transaction; an old or summary-only import never downgrades details."""
        records = records or {}
        with self.connection(write=True) as connection:
            for row in rows:
                reg = normalize_registration(row['registration_number'])
                if not REGISTRATION.fullmatch(reg):
                    raise ValueError('Invalid registration in directory')
                url = official_detail_url(row['details_url'])
                old = self.execute(connection, 'SELECT * FROM rera_search_projects WHERE registration_number=?', (reg,)).fetchone()
                record = records.get(reg) or {}
                if record and (normalize_registration(record.get('registration_number')) != reg
                               or official_detail_url(record['details_url']) != url):
                    raise ValueError('Search record does not match the official directory')
                checked = record.get('indexed_source_at')
                if old and old['source_checked_at'] and (not checked or checked <= old['source_checked_at']):
                    continue
                basic = record.get('property_data', {}).get('basic_details', {})
                address = basic.get('address') or ''
                locality = basic.get('village_locality_sector') or ''
                parcels = record.get('property_data', {}).get('search_parcels', [])
                # Explicitly labelled plot numbers in the official address are searchable too.
                clues, _ = parcel_clues(address)
                parcels = parcels + [dict(number=c['number'], kinds=['plot'], source='Published project address')
                                     for c in clues if c['kind'] == 'plot']
                text = ' '.join(str(v or '') for v in [row['project_name'], row.get('promoter_name'),
                                row['district'], basic.get('tehsil'), address, locality,
                                ' '.join(p['number'] for p in parcels)])
                sector_values = sorted({m[1].lower() for m in SECTOR.finditer(text)})
                columns = ['registration_number', 'project_name', 'promoter_name', 'district', 'tehsil',
                           'address', 'locality', 'sectors', 'project_type', 'details_url', 'directory_at',
                           'source_checked_at', 'parcels_json']
                values = [reg, row['project_name'], row.get('promoter_name') or '', row['district'],
                          basic.get('tehsil') or '', address, locality, json.dumps(sector_values),
                          row.get('project_type') or '', url, directory_at, checked, json.dumps(parcels)]
                self.execute(connection, 'INSERT INTO rera_search_projects (' + ','.join(columns) + ') VALUES (' +
                             ','.join('?' for _ in columns) + ') ON CONFLICT(registration_number) DO UPDATE SET ' +
                             ','.join(c+'=excluded.'+c for c in columns[1:]), values)
                for table in ['rera_search_tokens', 'rera_search_parcels']:
                    self.execute(connection, f'DELETE FROM {table} WHERE registration_number=?', (reg,))
                for token in sorted(tokens(text)):
                    self.execute(connection, 'INSERT INTO rera_search_tokens VALUES (?, ?)', (token, reg))
                parcel_keys = {(kind, identifier, reg) for p in parcels for kind in p['kinds']
                               if kind in {'plot', 'khasra'} for identifier in identifiers(p['number'])}
                for key in sorted(parcel_keys):
                    self.execute(connection, 'INSERT INTO rera_search_parcels VALUES (?, ?, ?)', key)

    def coverage(self, connection=None):
        if connection is None:
            with self.connection() as c:
                return self.coverage(c)
        rows = self.execute(connection, 'SELECT district, count(*) AS projects, '
                            'count(source_checked_at) AS inspected FROM rera_search_projects '
                            'GROUP BY district ORDER BY district').fetchall()
        meta = self.execute(connection, 'SELECT key, value FROM rera_search_metadata').fetchall()
        return {'projects': sum(r['projects'] for r in rows),
                'inspected': sum(r['inspected'] for r in rows),
                'districts': [dict(r) for r in rows],
                **{r['key']: json.loads(r['value']) for r in meta}}

    def search(self, query, offset=0, limit=100):
        start = time.perf_counter()
        reg = normalize_registration(query)
        clues, remaining = parcel_clues(query)
        parameters = []
        conditions = []
        if REGISTRATION.fullmatch(reg):
            conditions.append('p.registration_number=?')
            parameters.append(reg)
        else:
            for token in sorted(tokens(remaining, query=True)):
                conditions.append('EXISTS (SELECT 1 FROM rera_search_tokens t '
                                  'WHERE t.token=? AND t.registration_number=p.registration_number)')
                parameters.append(token)
            for clue in clues:
                conditions.append('EXISTS (SELECT 1 FROM rera_search_parcels n WHERE n.kind=? '
                                  'AND n.identifier=? AND n.registration_number=p.registration_number)')
                parameters.extend([clue['kind'], clue['number']])
        where = ' AND '.join(conditions) if conditions else '1=0'
        with self.connection() as connection:
            total = self.execute(connection, 'SELECT count(*) AS n FROM rera_search_projects p WHERE ' + where,
                                 parameters).fetchone()['n']
            rows = self.execute(connection, 'SELECT p.* FROM rera_search_projects p WHERE ' + where +
                                ' ORDER BY p.project_name, p.registration_number LIMIT ? OFFSET ?',
                                parameters + [limit, offset]).fetchall()
            coverage = self.coverage(connection)
        projects = []
        for row in rows:
            item = dict(row)
            parcels = json.loads(item.pop('parcels_json'))
            item['sectors'] = json.loads(item['sectors'])
            if clues:
                item['matched_parcels'] = matching_parcels(clues, parcels, item['address'])
            projects.append(item)
        inspected, count = coverage['inspected'], coverage['projects']
        return {'status': 'select_project', 'source': 'database', 'projects': projects,
                'total': total, 'offset': offset, 'limit': limit, 'has_more': False,
                'next_offset': offset + limit if offset + limit < total else None,
                'coverage': coverage, 'elapsed_ms': round((time.perf_counter() - start) * 1000, 2),
                'message': f'{total} database matches. Locations and parcels checked for {inspected} of {count} indexed projects. '
                           'Open a project for current RERA details. The index reflects its last refresh; use live search to check for newer or missing records.'}


def configured_catalog():
    load_dotenv(ROOT / '.env.local', override=False)
    target = os.getenv('RERA_DATABASE_URL') or os.getenv('DATABASE_URL')
    if target:
        return Catalog(target)
    path = Path(os.getenv('RERA_CATALOG_PATH', ROOT / 'data/rera_search.sqlite'))
    return Catalog(path) if path.exists() else None
