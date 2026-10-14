"""Export complete saved JSON for collaborator loaders without contacting RERA.

python -m scripts.export_project_snapshots --registration UPRERAPRJ256261
python -m scripts.export_project_snapshots --all
"""
import argparse
from pathlib import Path

from src.project_snapshots import ProjectSnapshots
from src.search_catalog import Catalog, configured_catalog
from src.scraper.district_dataset import atomic_write_json, safe_filename


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument('--registration')
    selection.add_argument('--all', action='store_true')
    parser.add_argument('--database', help='Optional local SQLite snapshot database; otherwise uses configured Neon')
    parser.add_argument('--output', default='data/full_project_results')
    args = parser.parse_args()
    catalog = Catalog(args.database) if args.database else configured_catalog()
    if catalog is None:
        parser.error('Configure a database first')
    snapshots = ProjectSnapshots(catalog)
    registrations = snapshots.inventory() if args.all else [args.registration]
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    count = 0
    for reg in registrations:
        result = snapshots.get(reg)
        if result is None:
            parser.error('No complete saved snapshot for ' + reg)
        atomic_write_json(output / (safe_filename(reg) + '.json'), result)
        count += 1
    print(f'Exported {count} full project results to {output}')


if __name__ == '__main__':
    main()
