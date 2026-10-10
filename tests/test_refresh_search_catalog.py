import json

import requests

from scripts import refresh_search_catalog as refresh
from src.scraper.live import LiveScrapeError


ROW = {'registration_number': 'UPRERAPRJ123',
       'details_url': 'https://up-rera.in/Frm_View_Project_Details.aspx?id=456'}


def test_transient_error_retries_with_fresh_session_and_records_recovery(monkeypatch, tmp_path):
    original = requests.Session()
    sessions, delays = [], []

    def fetch(url, reg, summary, *, session, timeout):
        sessions.append(session)
        assert url == ROW['details_url'] and reg == ROW['registration_number']
        assert summary['_search_parcels'] and timeout == (10, 60)
        if len(sessions) == 1:
            raise requests.ReadTimeout('possibly sensitive diagnostic')
        return {'property_data': {'basic_details': {'address': 'Sector 150'}}}

    monkeypatch.setattr(refresh, 'fetch_search_fields', fetch)
    path = tmp_path / 'project.json'
    outcome = refresh.refresh_project(ROW, path, original, sleep=delays.append)
    assert outcome['ok'] and outcome['attempts'] == 2
    assert sessions[0] is original and sessions[1] is not original
    assert delays == [3]
    assert outcome['errors'] == [{'attempt': 1, 'error_type': 'ReadTimeout'}]
    saved = json.loads(path.read_text())
    assert saved['registration_number'] == ROW['registration_number']
    assert saved['property_data']['basic_details']['address'] == 'Sector 150'
    assert saved['indexed_source_at']


def test_invalid_source_never_overwrites_existing_checkpoint(monkeypatch, tmp_path):
    def fetch(*args, **kwargs):
        raise LiveScrapeError('The address check returned an invalid or different project.')

    monkeypatch.setattr(refresh, 'fetch_search_fields', fetch)
    path = tmp_path / 'project.json'
    path.write_text('{"existing": true}')
    delays = []
    outcome = refresh.refresh_project(ROW, path, requests.Session(), attempts=3, sleep=delays.append)
    assert not outcome['ok'] and outcome['attempts'] == 3
    assert [error['error_type'] for error in outcome['errors']] == ['LiveScrapeError'] * 3
    assert delays == [3, 6]
    assert json.loads(path.read_text()) == {'existing': True}


def test_http_status_preserved_without_logging_sensitive_exception():
    response = requests.Response()
    response.status_code = 503
    exc = requests.HTTPError('secret in diagnostic', response=response)
    assert refresh.failure_details(exc) == {'error_type': 'HTTPError', 'http_status': 503}
