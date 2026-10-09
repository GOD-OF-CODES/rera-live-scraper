"""Parcel discovery checks: source parsing, exact matches and hosted continuity."""
import requests
import pytest
from bs4 import BeautifulSoup
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from src.live_api import create_app
from src.scraper.hosted_sessions import HostedSessions
from src.scraper.live import LiveScraper, PREFIX, parse_search_fields
from src.scraper.search_intent import interpret, identifier_matches
from test_live_scraper import FakeHTTP, REG, source_html


def page(reg, number, *, modern=False, kind='Khasra', address='Village Example'):
    prefix = 'ctl00_ContentPlaceHolder1_'
    header = '<th>Type</th><th>Khasra No</th><th>Khasra Area</th>' if modern else '<th>Khasra/Plot Number</th><th>Area</th><th>Type</th>'
    cells = f'<td>{kind}</td><td>{number}</td><td>12345</td>' if modern else f'<td>{number}</td><td>12345</td><td>{kind}</td>'
    return f'''<span id="{prefix}lblProjectNameWithID">Project Id: ({reg})</span>
    <span id="{prefix}lblProjectName">Test project</span>
    <input id="{prefix}projetaddress" value="{address}">
    <span id="{prefix}lblVillage">Sector 150</span>
    <div hidden><table><tr><th>Sr. No.</th>{header}</tr>
    <tr><td>1</td>{cells}</tr></table></div>
    <table><tr><th>Unit No</th><th>Area</th></tr><tr><td>99</td><td>123</td></tr></table>'''


@pytest.mark.parametrize('query,number,kind,terms', [
    ('Khasra 123/4 Lucknow', '123/4', 'khasra', []),
    ('Plot No. GH - 03 Noida', 'GH-03', 'plot', []),
    ('plot number 23 Sector 150 Noida', '23', 'plot', ['sector', '150']),
    ('Khasra No: 123 Lucknow', '123', 'khasra', []),
])
def test_parcel_intent_preserves_identifiers(query, number, kind, terms):
    soup = BeautifulSoup(f'<select name="{PREFIX}DdlprojectDistrict"><option value="Lucknow">Lucknow</option></select>', 'html.parser')
    intent = interpret(query, soup, PREFIX)
    assert intent['parcels'] == [{'kind': kind, 'number': number}]
    assert intent['terms'] == terms
    assert intent['inspect_details'] and intent['project_name'] == ''


@pytest.mark.parametrize('number,source,expected', [
    ('123', '1234', False), ('123', '123/4', False),
    ('12345', '12346', False), ('GH-03', 'GH-030', False),
    ('123/4', '123 / 4, 456', True), ('GH-03', 'gh - 03', True),
    ('123', '1123; 123; 456', True), ('124', '123-125', False),
])
def test_parcel_numbers_never_use_substring_or_fuzzy_matching(number, source, expected):
    assert identifier_matches(number, source) is expected


@pytest.mark.parametrize('modern', [False, True])
def test_hidden_land_tables_only_extract_identifier_columns(modern):
    data = parse_search_fields(page(REG, '123/4', modern=modern), REG, include_parcels=True)
    records = data['property_data']['search_parcels']
    assert [record['number'] for record in records] == ['123/4']
    assert 'khasra' in records[0]['kinds']
    assert 'search_parcels' not in parse_search_fields(page(REG, '123/4'), REG)['property_data']


def test_modern_plot_type_and_dedicated_plot_columns():
    html = page(REG, 'GH-03', modern=True, kind='Plot')
    html += '<table><tr><th>Plot Number</th><th>Area</th></tr><tr><td>SD-23</td><td>100</td></tr></table>'
    records = parse_search_fields(html, REG, include_parcels=True)['property_data']['search_parcels']
    assert [(r['number'], r['kinds']) for r in records] == [('GH-03', ['plot']), ('SD-23', ['plot'])]


def test_table_totals_are_not_parcel_identifiers():
    html = page(REG, '123/4').replace('</table>', '<tr><td colspan="2">Total</td><td>123</td></tr></table>', 1)
    records = parse_search_fields(html, REG, include_parcels=True)['property_data']['search_parcels']
    assert [r['number'] for r in records] == ['123/4']


def test_missing_district_returns_actionable_error_and_closes_session():
    http = FakeHTTP()
    service = LiveScraper(session_factory=lambda: http)
    with TestClient(create_app(service)) as client:
        response = client.post('/api/live/search', json={'query': 'Khasra 123/4'})
        assert response.status_code == 422
        assert response.json()['code'] == 'refine_query'
        assert 'city or district' in response.json()['message']
    assert not service.sessions and http.closed
    assert not any('CaptchaImage' in url for _, url, _ in http.calls)


def test_real_http_scanner_finds_parcel_in_later_batch_and_refetches_selection(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    rows = [(f'UPRERAPRJ{i}', str(100+i)) for i in range(1, 15)]
    http = FakeHTTP(posts=[source_html(rows)])
    checks, full_fetches = [], []
    class DetailResponse:
        def __init__(self, url):
            self.url = url
            i = int(url.rsplit('=', 1)[1]) - 100
            self.text = page(f'UPRERAPRJ{i}', '123/4' if i == 13 else '123/45', modern=True)
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def raise_for_status(self): pass
    def get(url, **kwargs):
        checks.append(url)
        return DetailResponse(url)
    monkeypatch.setattr(requests, 'get', get)
    service = LiveScraper(session_factory=lambda: http,
                          fetcher=lambda *args: full_fetches.append(args) or {'registration_number': args[1]})
    with TestClient(create_app(service)) as client:
        challenge = client.post('/api/live/search', json={'query': 'Khasra 123/4 Noida'}).json()
        token = challenge['session_id']
        first = client.post(f'/api/live/search/{token}/captcha', json={'captcha': 'ABC12'}).json()
        assert first['has_more'] and first['projects'] == [] and len(checks) == 12
        result = client.post(f'/api/live/search/{token}/more', json={}).json()
        assert result['search_complete'] and len(checks) == 14 and not full_fetches
        assert [r['registration_number'] for r in result['projects']] == ['UPRERAPRJ13']
        match = result['projects'][0]['matched_parcels'][0]
        assert match['published_number'] == '123/4' and 'Khasra No' in match['source']
        selected = client.post(f'/api/live/search/{token}/project', json={'registration_number': 'UPRERAPRJ13'}).json()
        assert selected['status'] == 'complete'
    assert len(full_fetches) == 1 and list(tmp_path.iterdir()) == []
    payload = next(kwargs['data'] for method, _, kwargs in http.calls if method == 'POST')
    assert payload[PREFIX+'txtProject1'] == ''
    assert payload[PREFIX+'DdlprojectDistrict'] == 'Gautam Buddha Nagar'


@pytest.mark.parametrize('query,address,number,expected', [
    ('Plot 23 Noida', 'Plot No. 23 Sector 150', '999', True),
    ('Plot 23 Noida', 'Sector 23', '999', False),
    ('Khasra 23 Noida', 'Plot 23', '999', False),
    ('Plot 23 Sector 150 Noida', 'Plot 23 Sector 15', '23', False),
    ('Khasra 123 Noida', 'Area 123', '1234', False),
])
def test_matching_uses_correct_identifier_and_remaining_location_clues(query, address, number, expected):
    http = FakeHTTP()
    def scanner(url, reg, summary):
        return parse_search_fields(page(reg, number, address=address).replace('>Sector 150<', '>Other village<'), reg, include_parcels=True)
    service = LiveScraper(session_factory=lambda: http, scanner=scanner)
    token = service.start(query)['session_id']
    result = service.submit_captcha(token, 'ABC12')
    assert bool(result['projects']) is expected
    assert result['search_complete']
    service.close()


def test_hosted_parcel_search_preserves_intent_and_evidence_across_instances():
    rows = [(f'UPRERAPRJ{i}', str(100+i)) for i in range(1, 14)]
    def factory():
        http = FakeHTTP(posts=[source_html(rows)])
        http.cookies = requests.cookies.RequestsCookieJar()
        def scanner(url, reg, summary):
            assert summary['_search_parcels']
            return parse_search_fields(page(reg, 'GH-03' if reg == 'UPRERAPRJ13' else 'GH-030', kind='Plot'), reg, include_parcels=True)
        return LiveScraper(session_factory=lambda: http, scanner=scanner,
                           fetcher=lambda *args: {'registration_number': args[1]})
    key = Fernet.generate_key()
    challenge = HostedSessions(key, factory).execute('start', 'Plot GH-03 Noida')
    token = challenge['session_id']
    first = HostedSessions(key, factory).execute('submit_captcha', token, 'ABC12', session_state=challenge['session_state'])
    assert first['has_more'] and first['projects'] == []
    final = HostedSessions(key, factory).execute('next_matches', token, session_state=first['session_state'])
    assert final['search_complete']
    assert final['projects'][0]['matched_parcels'][0]['published_number'] == 'GH-03'
    selected = HostedSessions(key, factory).execute('select', token, 'UPRERAPRJ13', session_state=final['session_state'])
    assert selected['status'] == 'complete' and 'session_state' not in selected


def test_dashboard_submits_parcel_query_and_displays_match_evidence():
    from pathlib import Path
    from playwright.sync_api import sync_playwright
    from test_live_scraper import PNG
    import base64
    html = Path('src/live_dashboard.html').read_text()
    calls = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        def respond(route):
            payload = route.request.post_data_json
            calls.append(payload)
            if route.request.url.endswith('/captcha'):
                assert payload['captcha'] == 'ABC12'
                route.fulfill(json={'status': 'select_project', 'session_id': 'parcel-session',
                    'projects': [{'registration_number': REG, 'project_name': 'Parcel match',
                        'district': 'Noida', 'promoter_name': 'Builder',
                        'matched_parcels': [{'query': 'plot GH-03', 'published_number': 'GH-03',
                                            'source': 'Published RERA table: Plot Number'}]}],
                    'message': 'Search complete'})
            else:
                assert payload == {'query': 'Plot GH-03 Noida'}
                route.fulfill(json={'status': 'captcha_required', 'session_id': 'parcel-session',
                    'captcha_image': 'data:image/png;base64,' + base64.b64encode(PNG).decode(),
                    'message': 'Enter CAPTCHA'})
        page.route('http://test.local/api/**', respond)
        page.route('http://test.local/', lambda route: route.fulfill(content_type='text/html', body=html))
        page.goto('http://test.local/')
        page.locator('#query').fill('Plot GH-03 Noida')
        page.locator('#searchButton').click()
        page.locator('#captchaInput').fill('ABC12')
        page.locator('#captchaButton').click()
        page.wait_for_function("document.getElementById('status').textContent==='Search complete' && !busy")
        assert page.locator('.candidate').count() == 1
        assert 'Matched plot GH-03: GH-03' in page.locator('.candidate').inner_text()
        assert len(calls) == 2
        browser.close()
