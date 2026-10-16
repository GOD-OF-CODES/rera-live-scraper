"""Check every known UP-RERA project and publish only changed source content.

python -m scripts.update_rera_database --dry-run --limit 5
python -m scripts.update_rera_database
The scheduler uses Neon directly; no Mac, local data files or LLM is required.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED
import json
from pathlib import Path
import time
import uuid

from src.project_updater import UpdateStore, content_hash, changed_sections, fetch_candidate, now, source_outage
from src.search_catalog import Catalog, configured_catalog
from src.scraper.district_dataset import atomic_write_json


def run(store, *, workers=4, limit=0, dry_run=False, max_minutes=150,
        report_path=Path('data/daily_update_report.json'), fetcher=fetch_candidate,
        executor=ProcessPoolExecutor, clock=time.monotonic):
    started = clock()
    if dry_run:
        with store.catalog.connection() as conn:
            rows = [dict(row) for row in conn.execute('SELECT * FROM rera_search_projects ORDER BY registration_number')]
    else:
        store.initialize()
        rows = store.rows()
    if not rows:
        raise ValueError('The configured database has no indexed projects to check')
    report = dict(run_id=str(uuid.uuid4()), started_at=now(), finished_at=None, status='running',
                  dry_run=dry_run, known_projects=len(rows), selected=min(limit, len(rows)) if limit else len(rows),
                  attempted=0, changed=0, created=0, unchanged=0, superseded=0, index_updated=0,
                  failed=0, retried=0, changes=[], failures=[], unattempted=0, stop_reason=None)
    if limit:
        rows = rows[:limit]
    remaining = iter(rows)
    consecutive_outages = 0

    def checkpoint():
        report['updated_at'] = now()
        report['unattempted'] = len(rows) - report['attempted']
        atomic_write_json(report_path, report)
        if not dry_run:
            store.save_run(report)

    checkpoint()
    print(f"Checking {len(rows)} of {report['known_projects']} indexed projects; dry_run={dry_run}", flush=True)
    try:
        with executor(max_workers=workers) as pool:
            pending = {}
            def schedule():
                if clock() - started >= max_minutes * 60:
                    report['stop_reason'] = report['stop_reason'] or 'time_budget'
                    return
                if report['stop_reason']:
                    return
                row = next(remaining, None)
                if row is not None:
                    pending[pool.submit(fetcher, row)] = row['registration_number']
            for _ in range(workers):
                schedule()
            while pending:
                done, _ = wait(pending, return_when=FIRST_COMPLETED)
                for future in done:
                    reg = pending.pop(future)
                    candidate, errors = future.result()
                    report['attempted'] += 1
                    if errors:
                        report['retried'] += 1
                    consecutive_outages = consecutive_outages + 1 if candidate is None and source_outage(errors) else 0
                    if candidate:
                        if candidate['result']['registration_number'] != reg:
                            raise ValueError('Worker returned a different project')
                        if dry_run:
                            old = store.snapshots.get(reg, original=True)
                            changed = old is None or content_hash(old) != content_hash(candidate['result'])
                            outcome = {'status': 'created' if old is None else 'changed' if changed else 'unchanged',
                                       'sections': changed_sections(old, candidate['result']) if changed else [],
                                       'index_updated': False}
                        else:
                            outcome = store.apply(candidate, errors)
                        report[outcome['status']] += 1
                        report['index_updated'] += int(outcome['index_updated'])
                        if outcome['status'] in {'changed', 'created'}:
                            report['changes'].append({'registration_number': reg, 'status': outcome['status'],
                                                      'sections': outcome['sections']})
                    else:
                        if not dry_run:
                            store.failed(reg, errors)
                        report['failed'] += 1
                        report['failures'].append({'registration_number': reg, 'errors': errors})
                    if consecutive_outages >= 3:
                        report['stop_reason'] = 'source_unavailable'
                if report['attempted'] % 25 < len(done) or not pending:
                    checkpoint()
                    print(f"Checked {report['attempted']}/{len(rows)}; changed={report['changed']}; "
                          f"unchanged={report['unchanged']}; failed={report['failed']}", flush=True)
                for _ in done:
                    schedule()
        report['status'] = 'partial' if report['failed'] or report['attempted'] < len(rows) else 'success'
    except Exception as exc:
        report['status'] = 'failed'
        report['fatal_error_type'] = type(exc).__name__
        # Do not put database driver/HTTP exception messages into public CI logs.
    finally:
        report['finished_at'] = now()
        atomic_write_json(report_path, report)
        checkpoint()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', help='Optional local SQLite file; defaults to configured Neon')
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--limit', type=int, default=0, help='0 checks every indexed project')
    parser.add_argument('--max-minutes', type=float, default=150)
    parser.add_argument('--dry-run', action='store_true', help='Read and compare only; do not write to the database')
    parser.add_argument('--report', type=Path, default=Path('data/daily_update_report.json'))
    args = parser.parse_args()
    if not 1 <= args.workers <= 8 or args.limit < 0 or args.max_minutes <= 0:
        parser.error('workers must be 1–8, limit nonnegative and max-minutes positive')
    try:
        catalog = Catalog(args.database) if args.database else configured_catalog()
        if catalog is None:
            parser.error('Configure RERA_DATABASE_URL or provide a populated local --database')
        report = run(UpdateStore(catalog), workers=args.workers, limit=args.limit, dry_run=args.dry_run,
                     max_minutes=args.max_minutes, report_path=args.report)
    except Exception as exc:
        # Config/database failures must fail the job without disclosing its URL.
        print('Updater could not finish:', type(exc).__name__, flush=True)
        raise SystemExit(1)
    print(json.dumps({k: v for k, v in report.items() if k not in {'changes', 'failures'}}, indent=2), flush=True)
    raise SystemExit(0 if report['status'] == 'success' else 1)


if __name__ == '__main__':
    main()
