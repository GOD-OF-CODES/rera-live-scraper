import copy
import json

import pytest
from fastapi.testclient import TestClient

from src.project_snapshots import ProjectSnapshots
from src.search_catalog import Catalog
from src.scraper.live import LiveScraper
from src.live_api import create_app

REG = 'UPRERAPRJ256261'
URL = 'https://up-rera.in/Frm_View_Project_Details.aspx?id=178631'


@pytest.fixture
def result():
    return dict(source='UP-RERA', fetch_mode='live', from_cache=False, persisted=False,
                registration_number=REG, project_found=True, project_details_available=True,
                scraped_at='2026-10-14T00:00:00+00:00', project_details_url=URL,
                property_data={'page': {'url': URL},
                    'identification': {'project_id': REG, 'project_name': 'SANFRAN PLAZA'},
                    'basic_details': {'district': 'Jhansi'},
                    'documents': [{'download_url': 'https://up-rera.in/ViewDocument?Param=test.pdf'}],
                    'land_details': {'khasra_plot_details': [{'khasra_plot_number': '254'}]},
                    'plan_and_unit_details': {'unit_records': [['हिन्दी', '001', '1.00']] * 100},
                    'unknown_future_field': {'preserve': [None, False, 0, '']}})


@pytest.fixture
def store(tmp_path):
    catalog = Catalog(tmp_path / 'test.sqlite')
    catalog.initialize()
    return ProjectSnapshots(catalog)


def test_lossless_compression_and_no_duplicate_versions(store, result):
    store.put_many([result])
    saved = store.get(REG)
    assert store.get(REG, original=True) == result
    assert saved == dict(result, fetch_mode='database', from_cache=True, persisted=True)
    assert saved['property_data'] == result['property_data']
    assert saved['scraped_at'] == result['scraped_at']
    assert saved['fetch_mode'] == 'database' and saved['persisted'] and saved['from_cache']
    assert store.get(URL)['property_data'] == result['property_data']
    store.put_many([result])
    assert store.coverage()['snapshots'] == 1
    assert store.coverage()['stored_bytes'] < store.coverage()['json_bytes'] / 2


def test_failed_and_older_refreshes_preserve_good_snapshot(store, result):
    store.put_many([result])
    invalid = copy.deepcopy(result)
    invalid['property_data']['identification']['project_id'] = 'UPRERAPRJ999'
    with pytest.raises(ValueError):
        store.put_many([invalid])
    older = copy.deepcopy(result)
    older['scraped_at'] = '2026-10-13T00:00:00Z'
    older['property_data']['basic_details']['district'] = 'Wrong'
    store.put_many([older])
    assert store.get(REG)['property_data'] == result['property_data']
    newer = copy.deepcopy(result)
    newer['scraped_at'] = '2026-10-15T00:00:00Z'
    newer['property_data']['basic_details']['district'] = 'Updated'
    store.put_many([newer])
    assert store.get(REG)['property_data']['basic_details']['district'] == 'Updated'
    assert store.coverage()['snapshots'] == 1


def test_search_index_replacement_does_not_delete_details(store, result):
    store.put_many([result])
    with store.catalog.connection(write=True) as conn:
        for table in ['rera_search_tokens', 'rera_search_parcels', 'rera_search_projects', 'rera_search_metadata']:
            conn.execute('DELETE FROM '+table)
    store.catalog.initialize()
    assert store.get(REG)['property_data'] == result['property_data']


def test_outage_database_and_missing_snapshot_never_call_source(store, result, monkeypatch):
    store.put_many([result])
    scraper = LiveScraper()
    def offline(*args, **kwargs):
        pytest.fail('A saved project lookup attempted to contact RERA')
    monkeypatch.setattr(scraper, 'start', offline)
    with TestClient(create_app(scraper, store.catalog)) as client:
        response = client.post('/api/live/search', json={'query': URL})
        assert response.status_code == 200
        assert response.json()['result']['property_data'] == result['property_data']
        assert client.get('/api/projects/'+REG).status_code == 200
        assert client.get('/api/catalog/coverage').json()['snapshots'] == 1
        assert client.get('/api/projects/UPRERAPRJ999').status_code == 404
        assert client.post('/api/live/search', json={'query': URL.replace('178631', '999')}).status_code == 404
        def broken(*args):
            raise RuntimeError('secret connection details')
        monkeypatch.setattr(ProjectSnapshots, 'get', broken)
        failed = client.post('/api/live/search', json={'query': URL})
        assert failed.status_code == 503 and 'secret' not in failed.text


def test_corrupted_payload_is_not_served(store, result):
    store.put_many([result])
    with store.catalog.connection(write=True) as conn:
        conn.execute("UPDATE rera_project_snapshots SET sha256='wrong'")
    with pytest.raises(ValueError, match='integrity'):
        store.get(REG)


def test_registration_with_slashes_and_untrusted_urls(store, result):
    result['registration_number'] = 'UPRERAPRJ256261/10/2026'
    result['property_data']['identification']['project_id'] = result['registration_number']
    store.put_many([result])
    with TestClient(create_app(LiveScraper(), store.catalog)) as client:
        assert client.get('/api/projects/UPRERAPRJ256261/10/2026').status_code == 200
        assert client.post('/api/live/search', json={'query': 'https://example.com/project'}).status_code == 422


def test_dashboard_preserves_full_snapshot_and_download(store, result, tmp_path):
    from pathlib import Path
    from playwright.sync_api import sync_playwright
    store.put_many([result])
    saved = store.get(REG)
    html = Path('src/live_dashboard.html').read_text()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(accept_downloads=True)
        calls = []
        def respond(route):
            calls.append(route.request.url)
            if '/api/' in route.request.url:
                route.fulfill(json={'status': 'complete', 'result': saved})
            else:
                route.fulfill(content_type='text/html', body=html)
        page.route('**/*', respond)
        from urllib.parse import urlencode
        page.goto('http://test.local/?'+urlencode({'project': URL, 'registration': REG}))
        page.locator('#result').wait_for(state='visible')
        assert page.locator('#projectName').inner_text() == 'SANFRAN PLAZA'
        assert page.locator('#resultSource').inner_text() == 'Saved database snapshot'
        assert 'Source retrieved' in page.locator('#fetchedAt').inner_text()
        assert page.locator('#documentList a').get_attribute('href') == result['property_data']['documents'][0]['download_url']
        assert '254' in page.locator('#landData').inner_text()
        page.get_by_text('Raw JSON (advanced)', exact=True).click()
        assert json.loads(page.locator('#rawJson').inner_text())['property_data'] == result['property_data']
        with page.expect_download() as download:
            page.locator('#exportButton').click()
        path = tmp_path / 'download.json'
        download.value.save_as(path)
        assert json.loads(path.read_text())['property_data'] == result['property_data']
        assert all(url.startswith('http://test.local/') for url in calls)
        browser.close()


def test_local_configuration_uses_separate_snapshot_file(store, result, tmp_path, monkeypatch):
    import src.live_api as api
    store.put_many([result])
    search = Catalog(tmp_path / 'search.sqlite')
    search.initialize()
    monkeypatch.setattr(api, 'configured_catalog', lambda: search)
    monkeypatch.setenv('RERA_SNAPSHOT_PATH', store.catalog.target)
    with TestClient(api.create_app()) as client:
        response = client.get('/api/projects/'+REG)
        assert response.status_code == 200
        assert response.json()['result']['property_data'] == result['property_data']
