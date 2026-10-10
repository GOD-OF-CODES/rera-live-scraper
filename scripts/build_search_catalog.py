"""Build a local search database and optionally publish it to Neon.

python -m scripts.build_search_catalog [--publish]
Set RERA_DATABASE_URL (or DATABASE_URL) in .env.local for publishing.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from src.search_catalog import Catalog, ROOT


def publish(source, target):
    """Atomically replace only our search tables, using COPY for efficient uploads."""
    if not target.postgres:
        raise ValueError('Publish target must be PostgreSQL')
    target.initialize()
    tables = ['rera_search_projects', 'rera_search_tokens', 'rera_search_parcels', 'rera_search_metadata']
    with source.connection() as src, target.connection(write=True) as dst:
        # Serialize concurrent publishers; readers retain the previous snapshot until commit.
        dst.execute('SELECT pg_advisory_xact_lock(74239102)')
        dst.execute("SET LOCAL statement_timeout='120s'")
        for table in reversed(tables):
            dst.execute('DELETE FROM ' + table)
        for table in tables:
            with dst.cursor().copy('COPY ' + table + ' FROM STDIN') as copy:
                for row in src.execute('SELECT * FROM ' + table):
                    copy.write_row(tuple(row))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', default='data/search_catalog')
    parser.add_argument('--output', default='data/rera_search.sqlite')
    parser.add_argument('--publish', action='store_true')
    args = parser.parse_args()
    source = Path(args.source)
    directory = json.loads((source / '_directory.json').read_text())
    records = {}
    for path in source.glob('UPRERAPRJ*.json'):
        record = json.loads(path.read_text())
        records[record['registration_number']] = record
    catalog = Catalog(args.output)
    catalog.initialize()
    catalog.import_rows(directory['rows'], directory['generated_at'], records)
    catalog.metadata({'directory_fetched_at': directory['generated_at'],
                      'directory_projects': len(directory['rows']),
                      'index_built_at': datetime.now(timezone.utc).isoformat(),
                      'source': 'UP-RERA public project directory'})
    print(json.dumps(catalog.coverage(), indent=2))
    if args.publish:
        load_dotenv(ROOT / '.env.local', override=False)
        url = os.getenv('RERA_DATABASE_URL') or os.getenv('DATABASE_URL')
        if not url:
            raise SystemExit('Configure RERA_DATABASE_URL in .env.local before publishing.')
        target = Catalog(url)
        publish(catalog, target)
        print('Published to PostgreSQL; indexed projects:', target.coverage()['projects'])


if __name__ == '__main__':
    main()
