from concurrent.futures import ThreadPoolExecutor

from scripts.backfill_project_snapshots import bounded_results, source_unavailable


def test_outage_stops_scheduling_remaining_directory():
    rows = [{'registration_number': str(i)} for i in range(100)]
    def unavailable(row):
        return None, [{'type': 'ReadTimeout'}]
    results = list(bounded_results(rows, 2, fetcher=unavailable, executor=ThreadPoolExecutor))
    assert 3 <= len(results) <= 5
    assert all(result is None for _, result, _ in results)


def test_invalid_individual_pages_do_not_stop_other_projects():
    rows = [{'registration_number': str(i)} for i in range(10)]
    def fetch(row):
        if int(row['registration_number']) < 4:
            return None, [{'type': 'LiveScrapeError'}]
        return row, []
    results = list(bounded_results(rows, 2, fetcher=fetch, executor=ThreadPoolExecutor))
    assert len(results) == 10
    assert sum(result is not None for _, result, _ in results) == 6
    assert source_unavailable([{'type': 'HTTPError', 'http_status': 503}])
    assert not source_unavailable([{'type': 'HTTPError', 'http_status': 404}])
