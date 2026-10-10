import json
import pytest
from fastapi.testclient import TestClient

from src.search_catalog import Catalog
from src.live_api import create_app
from src.scraper.live import LiveScraper


def row(reg, name='Park', district='Gautam Buddha Nagar', internal='123'):
    return dict(registration_number=reg, project_name=name, district=district,
                promoter_name='Example Builder', project_type='Residential',
                details_url='https://up-rera.in/Frm_View_Project_Details.aspx?id=' + internal)


def record(summary, address, number='123/4', kind='khasra', checked='2026-10-10T10:00:00+00:00'):
    return dict(summary, indexed_source_at=checked, property_data={
        'basic_details': {'address': address, 'village_locality_sector': 'Village One', 'tehsil': 'Dadri'},
        'search_parcels': [{'number': number, 'kinds': [kind], 'source': 'Published RERA table: Khasra No'}]})


@pytest.fixture
def catalog(tmp_path):
    db = Catalog(tmp_path / 'search.sqlite')
    db.initialize()
    rows = [row('UPRERAPRJ1'), row('UPRERAPRJ2', name='Other Park'),
            row('UPRERAPRJ3', district='Lucknow'), row('UPRERAPRJ4', name='Pending')]
    db.import_rows(rows, '2026-10-10', {
        rows[0]['registration_number']: record(rows[0], 'Sector-150 Noida Plot GH-03'),
        rows[1]['registration_number']: record(rows[1], 'Sector 1500 Noida', number='1234'),
        rows[2]['registration_number']: record(rows[2], 'Sector 150 Lucknow'),
    })
    return db


def test_sector_alias_and_numeric_boundaries(catalog):
    for query in ['Sector 150 Noida', 'sec.150 Gautam Buddha Nagar']:
        result = catalog.search(query)
        assert [r['registration_number'] for r in result['projects']] == ['UPRERAPRJ1']
        assert result['source'] == 'database'
    assert catalog.search('Sector 150')['total'] == 2


def test_exact_parcels_and_city_optional(catalog):
    assert catalog.search('Khasra 123/4')['total'] == 2
    assert catalog.search('Khasra 123/4 Lucknow')['total'] == 1
    assert catalog.search('Khasra 123')['total'] == 0
    assert catalog.search('Plot 123/4')['total'] == 0
    result = catalog.search('Plot GH-03 Noida')
    assert result['total'] == 1
    assert result['projects'][0]['matched_parcels'][0]['source'] == 'Published project address'
    assert catalog.search('Plot GH-030 Noida')['total'] == 0


def test_coverage_pagination_registration_and_injection(catalog):
    result = catalog.search('Park', limit=1)
    assert result['total'] == 3 and result['next_offset'] == 1
    assert result['coverage']['projects'] == 4 and result['coverage']['inspected'] == 3
    assert catalog.search('UPRERAPRJ1')['total'] == 1
    assert catalog.search("'; DROP TABLE rera_search_projects; --")['total'] == 0
    assert catalog.coverage()['projects'] == 4


def test_old_or_incomplete_import_cannot_erase_verified_fields(catalog):
    summary = row('UPRERAPRJ1')
    catalog.import_rows([summary], '2026-10-11')
    catalog.import_rows([summary], '2026-10-11', {summary['registration_number']:
                        record(summary, 'Sector 9', checked='2026-10-09')})
    assert catalog.search('Sector 150 Noida')['total'] == 1
    catalog.import_rows([summary], '2026-10-11', {summary['registration_number']:
                        record(summary, 'Sector 8', number='999', checked='2026-10-11')})
    assert catalog.search('Sector 150 Noida')['total'] == 0
    assert catalog.search('Sector 8 Noida')['total'] == 1
    assert catalog.search('Khasra 999 Noida')['total'] == 1


def test_reject_untrusted_url_or_mismatched_identity(catalog):
    summary = row('UPRERAPRJ9')
    with pytest.raises(ValueError):
        catalog.import_rows([summary], '2026-10-11', {'UPRERAPRJ9': record(row('UPRERAPRJ8'), 'Sector 2')})
    summary['details_url'] = 'http://127.0.0.1/admin'
    with pytest.raises(Exception):
        catalog.import_rows([summary], '2026-10-11')
    assert catalog.coverage()['projects'] == 4


def test_api_index_avoids_rera_and_live_override_works(catalog, monkeypatch):
    scraper = LiveScraper()
    calls = []
    monkeypatch.setattr(scraper, 'start', lambda query: calls.append(query) or {'status': 'live_called'})
    with TestClient(create_app(scraper, catalog)) as client:
        response = client.post('/api/live/search', json={'query': 'Sector 150 Noida'})
        assert response.status_code == 200 and response.json()['total'] == 1
        assert calls == []
        assert client.get('/api/catalog/coverage').json()['inspected'] == 3
        client.post('/api/live/search', json={'query': 'Sector 150 Noida', 'live': True})
        assert calls == ['Sector 150 Noida']
        client.post('/api/live/search', json={'query': row('UPRERAPRJ1')['details_url']})
        assert len(calls) == 2


def test_database_failure_is_explicit_not_ten_minute_fallback(catalog, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError('secret connection details')
    monkeypatch.setattr(catalog, 'search', broken)
    with TestClient(create_app(LiveScraper(), catalog)) as client:
        response = client.post('/api/live/search', json={'query': 'Sector 150'})
        assert response.status_code == 503
        assert response.json()['code'] == 'database_unavailable'
        assert 'secret' not in response.text


def test_dashboard_index_paging_and_live_override():
    from pathlib import Path
    from playwright.sync_api import sync_playwright
    html = Path('src/live_dashboard.html').read_text()
    requests = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        def respond(route):
            body = route.request.post_data_json
            requests.append(body)
            if body.get('live'):
                route.fulfill(json={'status': 'not_found', 'message': 'Live source searched'})
            else:
                offset = body.get('offset', 0)
                project = dict(row('UPRERAPRJ1', name=f'Indexed page {offset}'),
                               source_checked_at='2026-10-10T00:00:00Z')
                route.fulfill(json={'status': 'select_project', 'source': 'database',
                                   'projects': [project], 'next_offset': 100 if not offset else None,
                                   'message': 'Database results ready', 'has_more': False})

        page.route('http://test.local/api/**', respond)
        page.route('http://test.local/', lambda route: route.fulfill(content_type='text/html', body=html))
        page.goto('http://test.local/')
        page.locator('#query').fill('Sector 150 Noida')
        page.locator('#searchButton').click()
        page.wait_for_function("document.querySelector('.candidate') && !busy")
        assert page.locator('#captchaForm').is_hidden()
        assert 'Location and parcels checked' in page.locator('.candidate').inner_text()
        assert page.locator('.candidate').get_attribute('target') == '_blank'
        page.locator('#moreDatabase').click()
        page.wait_for_function("document.querySelector('.candidate').textContent.includes('page 100') && !busy")
        assert page.locator('#moreDatabase').is_hidden()
        page.locator('#liveSearchButton').click()
        page.wait_for_function("document.getElementById('status').textContent==='Live source searched' && !busy")
        assert requests == [{'query': 'Sector 150 Noida'}, {'query': 'Sector 150 Noida', 'offset': 100},
                            {'query': 'Sector 150 Noida', 'live': True}]
        browser.close()
