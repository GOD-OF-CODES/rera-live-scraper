"""Repair parcel classifications using complete saved source data; never fetch RERA.

python -m scripts.reindex_search_parcels --publish
Builds a separate SQLite copy first; publication atomically replaces search tables.
Full snapshots and collaborator tables are not modified.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

from src.project_snapshots import ProjectSnapshots
from src.search_catalog import Catalog, configured_catalog
from src.scraper.search_intent import resolve_parcels, record_identifiers
from scripts.build_search_catalog import publish


def repair(catalog, snapshots, *, require_snapshots=True):
    with catalog.connection() as conn:
        projects = [dict(row) for row in conn.execute('SELECT * FROM rera_search_projects')]
    # Read and validate every snapshot before changing the index.
    updates = []
    for project in projects:
        reg = project['registration_number']
        saved = snapshots.get(reg, original=True)
        if saved is None and require_snapshots:
            raise ValueError('Missing source snapshot for ' + reg)
        if saved and saved['project_details_url'] != project['details_url']:
            raise ValueError('Snapshot URL does not match search project ' + reg)
        records = json.loads(project['parcels_json'])
        # Never override newer indexed source data with an older snapshot.
        if saved and saved['scraped_at'] >= (project['source_checked_at'] or ''):
            authoritative = []
            for row in saved['property_data'].get('land_details', {}).get('khasra_plot_details', []):
                kind = str(row.get('type') or '').strip().lower()
                number = row.get('khasra_plot_number')
                if kind in {'plot', 'khasra'} and number:
                    authoritative.append({'number': str(number), 'kinds': [kind], 'explicit_type': True,
                                    'source': 'Published RERA land record: ' + kind.title()})
            if authoritative:
                records = [dict(record, explicit_type=False) for record in records
                           if not record['source'].startswith('Published RERA land record:')] + authoritative
        # Explicitly labelled project-address plots remain valid evidence.
        for record in records:
            if record.get('source') == 'Published project address':
                record['explicit_type'] = True
        updates.append((reg, resolve_parcels(records)))
    with catalog.connection(write=True) as conn:
        conn.execute('DELETE FROM rera_search_parcels')
        for reg, records in updates:
            catalog.execute(conn, 'UPDATE rera_search_projects SET parcels_json=? WHERE registration_number=?',
                            (json.dumps(records), reg))
            keys = {(kind, number, reg) for record in records for kind in record['kinds']
                    for number in record_identifiers(record)}
            for key in sorted(keys):
                catalog.execute(conn, 'INSERT INTO rera_search_parcels VALUES (?, ?, ?)', key)
    catalog.metadata({'parcel_index_version': 2,
                      'parcel_index_corrected_at': datetime.now(timezone.utc).isoformat()})
    return len(updates)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', default='data/rera_search.sqlite')
    parser.add_argument('--snapshots', default='data/project_snapshots.sqlite')
    parser.add_argument('--output', default='data/rera_search_corrected.sqlite')
    parser.add_argument('--publish', action='store_true')
    args = parser.parse_args()
    if Path(args.source).resolve() == Path(args.output).resolve():
        parser.error('Use a separate output file to retain the original index for comparison')
    if not Path(args.snapshots).is_file():
        parser.error('The saved snapshot database must exist')
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with Catalog(args.source).connection() as source, sqlite3.connect(args.output) as output:
        source.backup(output)
    catalog = Catalog(args.output)
    count = repair(catalog, ProjectSnapshots(Catalog(args.snapshots)))
    print('Corrected parcel index for', count, 'projects', flush=True)
    if args.publish:
        target = configured_catalog()
        if target is None or not target.postgres:
            parser.error('Configure the existing PostgreSQL database before publishing')
        publish(catalog, target)
        print('Published corrected search index to PostgreSQL', flush=True)


if __name__ == '__main__':
    main()
