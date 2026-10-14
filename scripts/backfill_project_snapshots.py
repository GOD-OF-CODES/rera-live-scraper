"""Fetch complete official project results, checkpoint locally, optionally publish to Neon.

python -m scripts.backfill_project_snapshots --workers 8 --publish
Resumes successful snapshots; --max-age-days refreshes older ones. Failed requests
are reported and never erase saved data. No PDFs or source HTML are stored.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED
from contextlib import redirect_stdout
from datetime import datetime, timezone, timedelta
import io
import json
from pathlib import Path
import time

import requests
from src.project_snapshots import ProjectSnapshots
from src.search_catalog import Catalog, configured_catalog
from src.scraper.live import fetch_project_http
from src.scraper.district_dataset import atomic_write_json

_http = None


def source_unavailable(errors):
    return bool(errors) and all(e['type'] in {'ReadTimeout', 'ConnectTimeout', 'ConnectionError', 'Timeout'}
        or (e['type'] == 'HTTPError' and e.get('http_status') in {429, 500, 502, 503, 504}) for e in errors)


def bounded_results(rows, workers, *, fetcher=None, executor=ProcessPoolExecutor):
    """Keep only a bounded number in flight and stop scheduling during outages."""
    fetcher = fetcher or fetch
    remaining = iter(rows)
    consecutive_outages = 0
    stopped = False
    with executor(max_workers=workers) as pool:
        jobs = {}
        def schedule():
            row = next(remaining, None)
            if row is not None:
                jobs[pool.submit(fetcher, row)] = row['registration_number']
        for _ in range(workers):
            schedule()
        while jobs:
            done, _ = wait(jobs, return_when=FIRST_COMPLETED)
            for future in done:
                reg = jobs.pop(future)
                result, errors = future.result()
                consecutive_outages = consecutive_outages + 1 if not result and source_unavailable(errors) else 0
                if consecutive_outages >= 3 and not stopped:
                    stopped = True
                    print('Source repeatedly unavailable; stopping new requests. Resume this command later.', flush=True)
                yield reg, result, errors
            if not stopped:
                for _ in done:
                    schedule()


def fetch(row):
    global _http
    errors = []
    for attempt in range(4):
        if _http is None:
            _http = requests.Session()
        try:
            with redirect_stdout(io.StringIO()):
                result = fetch_project_http(row['details_url'], row['registration_number'], row, session=_http)
            ProjectSnapshots.pack(result)
            return result, errors
        except Exception as exc:
            error = {'type': type(exc).__name__}
            if isinstance(exc, requests.HTTPError) and exc.response is not None:
                error['http_status'] = exc.response.status_code
            errors.append(error)
            _http.close()
            _http = None
            if attempt < 3:
                time.sleep(3 * 2 ** attempt)
    return None, errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', default='data/search_catalog/_directory.json')
    parser.add_argument('--database', default='data/project_snapshots.sqlite')
    parser.add_argument('--workers', type=int, default=8)
    parser.add_argument('--max-age-days', type=float)
    parser.add_argument('--limit', type=int)
    parser.add_argument('--publish', action='store_true')
    args = parser.parse_args()
    if not 1 <= args.workers <= 12 or (args.limit is not None and args.limit < 1):
        parser.error('workers must be 1–12 and limit must be positive')
    if args.max_age_days is not None and args.max_age_days < 0:
        parser.error('max-age-days must be nonnegative')
    rows = json.loads(Path(args.directory).read_text())['rows']
    local = ProjectSnapshots(Catalog(args.database))
    local.initialize()
    target = None
    if args.publish:
        catalog = configured_catalog()
        if catalog is None or not catalog.postgres:
            parser.error('Configure the existing Neon database before publishing')
        target = ProjectSnapshots(catalog)
        target.initialize()
        remote = target.inventory()
        # Resume uploads independently of scraping, including interrupted runs.
        upload = []
        for reg, stamp in local.inventory().items():
            if stamp > remote.get(reg, ''):
                upload.append(local.get(reg, original=True))
            if len(upload) >= 50:
                target.put_many(upload)
                upload = []
        if upload:
            target.put_many(upload)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=args.max_age_days)).isoformat() if args.max_age_days is not None else None
    existing = local.inventory()
    pending = [r for r in rows if r['registration_number'] not in existing or
               (cutoff and existing[r['registration_number']] < cutoff)]
    if args.limit:
        pending = pending[:args.limit]
    print(f'Directory {len(rows)}; pending {len(pending)}; existing snapshots {len(existing)}', flush=True)
    report = {'directory_projects': len(rows), 'attempted': 0, 'recovered': 0, 'failures': [], 'retries': []}
    report_path = Path(args.database).with_suffix('.report.json')
    upload = []
    for reg, result, errors in bounded_results(pending, args.workers):
        report['attempted'] += 1
        if result:
            local.put_many([result])
            upload.append(result)
            report['recovered'] += 1
            if errors:
                report['retries'].append({'registration_number': reg, 'errors': errors})
        else:
            report['failures'].append({'registration_number': reg, 'errors': errors})
            print(f'Failed {reg}: {errors}', flush=True)
        if len(upload) >= 25:
            if target:
                target.put_many(upload)
            upload = []
        if report['attempted'] % 25 == 0 or report['attempted'] == len(pending):
            report['updated_at'] = datetime.now(timezone.utc).isoformat()
            atomic_write_json(report_path, report)
            print(f"Checked {report['attempted']}/{len(pending)}; saved {report['recovered']}; failed {len(report['failures'])}", flush=True)
    if target and upload:
        target.put_many(upload)
    report['finished_at'] = datetime.now(timezone.utc).isoformat()
    report['unattempted'] = len(pending) - report['attempted']
    report['coverage'] = local.coverage()
    atomic_write_json(report_path, report)
    print(json.dumps(report['coverage']), flush=True)
    if target:
        print('Neon:', json.dumps(target.coverage()), flush=True)
    if report['failures'] or report['unattempted']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
