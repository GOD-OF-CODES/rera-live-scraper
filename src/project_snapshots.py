"""Lossless, compressed, latest-successful project snapshots.

Independent of the replaceable search index and the collaborator's normalized
tables. Reads never contact UP-RERA. Only maintenance commands write snapshots.
"""
from datetime import datetime, timezone
from contextlib import nullcontext
import hashlib
import json
import zlib

from src.scraper.live import official_detail_url
from src.scraper.project_links import normalize_registration
from src.scraper.validation import is_valid_result


class ProjectSnapshots:
    def __init__(self, catalog):
        self.catalog = catalog

    def initialize(self):
        binary = 'BYTEA' if self.catalog.postgres else 'BLOB'
        with self.catalog.connection(write=True) as conn:
            conn.execute(f'''CREATE TABLE IF NOT EXISTS rera_project_snapshots (
                registration_number TEXT PRIMARY KEY,
                details_url TEXT NOT NULL UNIQUE,
                scraped_at TEXT NOT NULL,
                encoding TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                raw_bytes INTEGER NOT NULL,
                payload {binary} NOT NULL
            )''')

    @staticmethod
    def pack(result):
        if not is_valid_result(result):
            raise ValueError('Only complete, identity-checked project results can be saved')
        reg = normalize_registration(result['registration_number'])
        url = official_detail_url(result['project_details_url'])
        if official_detail_url(result['property_data']['page']['url']) != url:
            raise ValueError('Snapshot page URL does not match its source URL')
        stamp = datetime.fromisoformat(result['scraped_at'].replace('Z', '+00:00'))
        if stamp.tzinfo is None:
            raise ValueError('Source timestamp must include a timezone')
        raw = json.dumps(result, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()
        return (reg, url, stamp.astimezone(timezone.utc).isoformat(), 'zlib-json-v1',
                hashlib.sha256(raw).hexdigest(), len(raw), zlib.compress(raw, level=9))

    def put_many(self, records, *, connection=None):
        # Validate all inputs before starting a transaction; failed scrapes never
        # replace a good snapshot. Older workers cannot overwrite newer results.
        rows = [self.pack(record) for record in records]
        with (nullcontext(connection) if connection is not None else self.catalog.connection(write=True)) as conn:
            for row in rows:
                self.catalog.execute(conn, '''INSERT INTO rera_project_snapshots
                    (registration_number, details_url, scraped_at, encoding, sha256, raw_bytes, payload)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(registration_number) DO UPDATE SET
                    details_url=excluded.details_url, scraped_at=excluded.scraped_at,
                    encoding=excluded.encoding, sha256=excluded.sha256,
                    raw_bytes=excluded.raw_bytes, payload=excluded.payload
                    WHERE excluded.scraped_at > rera_project_snapshots.scraped_at''', row)

    def inventory(self):
        with self.catalog.connection() as conn:
            return {row['registration_number']: row['scraped_at'] for row in
                    conn.execute('SELECT registration_number, scraped_at FROM rera_project_snapshots')}

    def coverage(self):
        with self.catalog.connection() as conn:
            row = conn.execute('''SELECT COUNT(*) AS snapshots,
                COALESCE(SUM(raw_bytes),0) AS json_bytes,
                COALESCE(SUM(length(payload)),0) AS stored_bytes,
                MIN(scraped_at) AS oldest_snapshot_at, MAX(scraped_at) AS newest_snapshot_at
                FROM rera_project_snapshots''').fetchone()
            return dict(row)

    def get(self, identifier, *, original=False, connection=None):
        if identifier.lower().startswith(('http:', 'https:')):
            column, value = 'details_url', official_detail_url(identifier)
        else:
            column, value = 'registration_number', normalize_registration(identifier)
        if connection is None:
            with self.catalog.connection() as conn:
                return self.get(identifier, original=original, connection=conn)
        row = self.catalog.execute(connection, 'SELECT * FROM rera_project_snapshots WHERE '+column+'=?', (value,)).fetchone()
        if row is None:
            return None
        if row['encoding'] != 'zlib-json-v1':
            raise ValueError('Unsupported snapshot encoding')
        raw = zlib.decompress(bytes(row['payload']))
        if len(raw) != row['raw_bytes'] or hashlib.sha256(raw).hexdigest() != row['sha256']:
            raise ValueError('Snapshot integrity check failed')
        result = json.loads(raw)
        if not is_valid_result(result, row['registration_number']):
            raise ValueError('Invalid stored project identity')
        if official_detail_url(result['project_details_url']) != row['details_url']:
            raise ValueError('Invalid stored project URL')
        if not original:
            # Only delivery metadata changes. Preserve every source field and
            # both original timestamps exactly, including whitespace and types.
            result.update(fetch_mode='database', from_cache=True, persisted=True)
        return result
