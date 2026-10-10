"""Refresh known official project links; resumable, bounded source concurrency.

Run from the repository root: python -m scripts.refresh_search_catalog
The directory must first be collected through RERA's normal search/CAPTCHA.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
from pathlib import Path
import time
import threading
import requests
import subprocess
import sys

from src.scraper.live import fetch_search_fields
from src.scraper.district_dataset import atomic_write_json, safe_filename


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', default='data/results/all_up/_summary_rows.json')
    parser.add_argument('--output', default='data/search_catalog')
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--max-age-hours', type=float, default=168)
    parser.add_argument('--publish', action='store_true', help='Build and publish checkpoints to the configured Neon database')
    parser.add_argument('--publish-every', type=int, default=250)
    args = parser.parse_args()
    source = json.loads(Path(args.directory).read_text())
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    atomic_write_json(output / '_directory.json', source)
    pending = []
    for row in source['rows']:
        path = output / (safe_filename(row['registration_number']) + '.json')
        if path.exists() and time.time() - path.stat().st_mtime < args.max_age_hours * 3600:
            continue
        pending.append((row, path))
    # Prioritize Noida to make the user's sector searches available first.
    pending.sort(key=lambda item: item[0].get('district') != 'Gautam Buddha Nagar')
    print(f"Directory: {len(source['rows'])}; to refresh: {len(pending)}", flush=True)

    local = threading.local()

    def fetch(item):
        row, path = item
        if not hasattr(local, 'http'):
            local.http = requests.Session()
        for attempt in range(3):
            try:
                result = fetch_search_fields(row['details_url'], row['registration_number'],
                                             dict(row, _search_parcels=True), session=local.http)
                record = dict(row, **result, indexed_source_at=datetime.now(timezone.utc).isoformat())
                atomic_write_json(path, record)
                return row['registration_number'], True
            except Exception:
                if attempt < 2:
                    time.sleep(2 ** attempt)
        return row['registration_number'], False

    failures = []
    def publish_checkpoint():
        if args.publish:
            completed = subprocess.run([sys.executable, '-m', 'scripts.build_search_catalog',
                                        '--source', str(output), '--publish'], capture_output=True, text=True)
            if completed.returncode:
                # Credentials/driver diagnostics must not enter progress logs.
                print('Publish failed; local checkpoints retained. Retry build_search_catalog --publish.', flush=True)
                return False
            print('Published current checkpoint to Neon.', flush=True)
        return True

    with ThreadPoolExecutor(max_workers=max(1, min(args.workers, 12))) as pool:
        for i, future in enumerate(as_completed([pool.submit(fetch, item) for item in pending]), 1):
            reg, ok = future.result()
            if not ok:
                failures.append(reg)
            if i % 50 == 0 or i == len(pending):
                print(f"Checked {i}/{len(pending)}; failed {len(failures)}; last {reg}", flush=True)
            if i % max(50, args.publish_every) == 0:
                publish_checkpoint()
    atomic_write_json(output / '_refresh_report.json', {
        'finished_at': datetime.now(timezone.utc).isoformat(),
        'directory_projects': len(source['rows']), 'attempted': len(pending),
        'failed_registrations': failures,
    })
    if not publish_checkpoint():
        raise SystemExit(1)


if __name__ == '__main__':
    main()
