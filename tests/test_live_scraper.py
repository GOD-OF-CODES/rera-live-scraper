import base64
import json
from pathlib import Path

import pytest
import requests
from fastapi.testclient import TestClient

from src.live_api import create_app
from src.scraper.live import (LiveScraper, LiveScrapeError, SEARCH_URL, PREFIX,
                              official_detail_url, fetch_project_live)
from test_scraper import viewstate


REG = "UPRERAPRJ248777/03/2025"
URL = "https://up-rera.in/Frm_View_Project_Details.aspx?id=1300671"
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=")


def source_html(rows=None, notice=""):
    result = f'''<form><input id="__VIEWSTATE" name="__VIEWSTATE" value="{viewstate(rows or [])}">
        <input name="__EVENTVALIDATION" value="source-form-token">
        <select name="{PREFIX}DdlprojectDistrict"><option value="0" selected>All</option></select>
        <input name="{PREFIX}txt_regid1"><input name="{PREFIX}txtProject1">
        <input name="{PREFIX}txtcap"><img src="CaptchaImage.axd?guid=from-live-response">
        <span>{notice}</span>'''
    if rows is not None:
        result += '<table id="ctl00_ContentPlaceHolder1_GridView1">'
        for i, (reg, internal) in enumerate(rows, 1):
            result += f'''<tr><td>{i}</td><td><span>{reg}</span></td><td><span>Project {i}</span></td>
                <td><ul><li>Promoter</li></ul></td><td>District</td><td>Residential</td><td>NA</td>
                <td><a href="javascript:__doPostBack('row','')">View</a></td></tr>'''
        result += '</table>'
    return result + '</form>'


class Response:
    def __init__(self, text="", image=False):
        self.text = text
        self.content = PNG if image else text.encode()
        self.url = "https://up-rera.in/CaptchaImage.axd" if image else SEARCH_URL
        self.headers = {"Content-Type": "image/png" if image else "text/html"}
    def raise_for_status(self):
        pass


class FakeHTTP:
    def __init__(self, posts=None, error=None):
        self.posts = list(posts or [source_html([(REG, "1300671")])])
        self.error = error
        self.calls = []
        self.closed = False
    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        if self.error:
            raise self.error
        return Response(image=True) if "CaptchaImage" in url else Response(source_html())
    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return Response(self.posts.pop(0))
    def close(self):
        self.closed = True


def test_live_request_resolves_source_id_without_dataset_or_database(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    http = FakeHTTP()
    fetches = []
    def fetch(url, reg, summary):
        fetches.append((url, reg, summary))
        return {"registration_number": reg, "fetch_mode": "live", "persisted": False}
    service = LiveScraper(session_factory=lambda: http, fetcher=fetch)
    challenge = service.start(REG)
    assert challenge["status"] == "captcha_required"
    assert not fetches
    answer = service.submit_captcha(challenge["session_id"], "ABC12")
    assert answer["status"] == "complete"
    assert fetches[0][:2] == (URL, REG)
    payload = next(c[2]["data"] for c in http.calls if c[0] == "POST")
    assert payload[PREFIX + "txt_regid1"] == REG
    assert payload[PREFIX + "txtProject1"] == ""
    assert payload["__EVENTVALIDATION"] == "source-form-token"
    assert http.closed and not service.sessions
    assert list(tmp_path.iterdir()) == []


def test_repeated_searches_fetch_the_source_again():
    connections = []
    fetches = []
    def factory():
        http = FakeHTTP()
        connections.append(http)
        return http
    def fetch(*args):
        fetches.append(args)
        return {"revision": len(fetches)}
    service = LiveScraper(session_factory=factory, fetcher=fetch)
    results = []
    for _ in range(2):
        challenge = service.start(REG)
        results.append(service.submit_captcha(challenge["session_id"], "ABC12"))
    assert [r["result"]["revision"] for r in results] == [1, 2]
    assert len(connections) == 2 and all(c.closed for c in connections)


def test_name_search_requires_explicit_selection_and_fetches_only_that_project():
    rows = [(REG, "1300671"), ("UPRERAPRJ697894", "19021")]
    http = FakeHTTP(posts=[source_html(rows)])
    fetches = []
    service = LiveScraper(session_factory=lambda: http, fetcher=lambda *args: fetches.append(args) or {})
    token = service.start("Project")["session_id"]
    candidates = service.submit_captcha(token, "ABC12")
    assert candidates["status"] == "select_project" and len(candidates["projects"]) == 2
    assert not fetches
    with pytest.raises(LiveScrapeError, match="returned by this live search"):
        service.select(token, "UPRERAPRJ918")
    service.select(token, "UPRERAPRJ697894")
    assert len(fetches) == 1 and fetches[0][0].endswith("id=19021")


def test_wrong_captcha_gets_a_new_challenge_without_fetching():
    http = FakeHTTP(posts=[source_html(notice="Invalid Captcha")])
    service = LiveScraper(session_factory=lambda: http, fetcher=lambda *args: pytest.fail("Must not fetch"))
    token = service.start(REG)["session_id"]
    answer = service.submit_captcha(token, "WRONG")
    assert answer["status"] == "captcha_required" and answer["session_id"] == token
    assert sum("CaptchaImage" in c[1] for c in http.calls) == 2
    service.cancel(token)
    assert http.closed


def test_source_no_match_is_not_an_empty_success():
    http = FakeHTTP(posts=[source_html([], "No Records Found")])
    service = LiveScraper(session_factory=lambda: http, fetcher=lambda *args: pytest.fail("Must not fetch"))
    token = service.start(REG)["session_id"]
    assert service.submit_captcha(token, "ABC12")["status"] == "not_found"
    assert not service.sessions


def test_exact_registration_does_not_choose_a_prefix_match():
    http = FakeHTTP(posts=[source_html([("UPRERAPRJ9180", "12345")])])
    service = LiveScraper(session_factory=lambda: http, fetcher=lambda *args: pytest.fail("Must not fetch"))
    token = service.start("UPRERAPRJ918")["session_id"]
    assert service.submit_captcha(token, "ABC12")["status"] == "not_found"


def test_sessions_expire_and_release_connections():
    now = [0]
    http = FakeHTTP()
    service = LiveScraper(session_factory=lambda: http, clock=lambda: now[0], ttl=10)
    token = service.start(REG)["session_id"]
    now[0] = 11
    with pytest.raises(LiveScrapeError) as error:
        service.submit_captcha(token, "ABC12")
    assert error.value.status_code == 410 and http.closed and not service.sessions


def test_sessions_are_bounded_and_isolated():
    http = FakeHTTP()
    service = LiveScraper(session_factory=lambda: http, max_sessions=1)
    token = service.start(REG)["session_id"]
    with pytest.raises(LiveScrapeError) as error:
        service.start("Another project")
    assert error.value.status_code == 429
    state = service.sessions[token]
    state.lock.acquire()
    try:
        with pytest.raises(LiveScrapeError) as error:
            service.submit_captcha(token, "ABC12")
        assert error.value.status_code == 409
    finally:
        state.lock.release()
    service.cancel(token)


@pytest.mark.parametrize("url", ["http://up-rera.in/Frm_View_Project_Details.aspx?id=1",
    "https://example.com/Frm_View_Project_Details.aspx?id=1", "https://up-rera.in:abc/Frm_View_Project_Details.aspx?id=1",
    "https://up-rera.in/Frm_View_Project_Details.aspx?id=1&id=2", "https://up-rera.in/login"])
def test_only_official_details_urls_can_be_fetched(url):
    with pytest.raises(LiveScrapeError) as error:
        official_detail_url(url)
    assert error.value.status_code == 422


def test_direct_url_requests_are_also_fresh_and_do_not_search():
    fetches = []
    service = LiveScraper(session_factory=lambda: pytest.fail("No search needed"),
                          fetcher=lambda *args: fetches.append(args) or {"revision": len(fetches)})
    assert service.start(URL)["result"]["revision"] == 1
    assert service.start(URL)["result"]["revision"] == 2
    assert not service.sessions


def test_source_failure_returns_error_and_never_uses_existing_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data/results").mkdir(parents=True)
    existing = tmp_path / "data/results/UPRERAPRJ248777_03_2025.json"
    existing.write_text('{"project_name":"OLD CACHED RESULT"}')
    http = FakeHTTP(error=requests.Timeout("source offline"))
    service = LiveScraper(session_factory=lambda: http)
    with TestClient(create_app(service)) as client:
        response = client.post("/api/live/search", json={"query": REG})
        assert response.status_code == 502
        assert response.json()["code"] == "source_unavailable"
        assert "OLD CACHED RESULT" not in response.text
        assert response.headers["cache-control"] == "no-store"
    assert http.closed and not service.sessions


def test_api_contract_and_no_database_requirement():
    http = FakeHTTP()
    service = LiveScraper(session_factory=lambda: http, fetcher=lambda *args: {"fetch_mode": "live"})
    with TestClient(create_app(service)) as client:
        assert client.get("/health").json()["database_required"] is False
        assert "Search a project" in client.get("/").text
        response = client.post("/api/live/search", json={"query": REG})
        token = response.json()["session_id"]
        assert response.headers["cache-control"] == "no-store"
        response = client.post(f"/api/live/search/{token}/captcha", json={"captcha": "ABC12"})
        assert response.json()["status"] == "complete"
        assert client.post(f"/api/live/search/{token}/project", json={"registration_number": REG}).status_code == 410


def test_real_fetch_function_uses_browser_each_time_and_writes_nothing(tmp_path, monkeypatch):
    from src.scraper import live
    monkeypatch.chdir(tmp_path)
    calls = []
    class Page:
        url = URL
    class Browser:
        def __init__(self, **kwargs):
            calls.append("new browser")
        def start(self):
            return Page()
        def close(self):
            calls.append("closed")
    monkeypatch.setattr(live, "BrowserManager", Browser)
    monkeypatch.setattr(live, "scrape_detail_page", lambda *args: {"identification": {"project_id": REG}})
    for _ in range(2):
        result = fetch_project_live(URL, REG)
        assert result["persisted"] is False and result["from_cache"] is False
    assert calls == ["new browser", "closed", "new browser", "closed"]
    assert list(tmp_path.iterdir()) == []


def test_free_text_interpretation_uses_live_options():
    from bs4 import BeautifulSoup
    from src.scraper.search_intent import interpret, matches
    soup = BeautifulSoup(f'''<select name="{PREFIX}DdlprojectDistrict">
      <option value="Lucknow">Lucknow</option></select>
      <select name="{PREFIX}ddl_prm"><option value="123">Oro Builders Private Limited</option></select>''', 'html.parser')
    intent = interpret('show me sec. 150 in Noida', soup, PREFIX)
    assert intent['district'] == 'Gautam Buddha Nagar'
    assert intent['terms'] == ['sector', '150'] and intent['inspect_details']
    assert interpret('Oro Builders', soup, PREFIX)['promoter'] == '123'
    assert interpret('Oro City', soup, PREFIX)['project_name'] == 'oro city'
    assert interpret('Gomti Nagar', soup, PREFIX)['terms'] == ['gomti', 'nagar']
    assert matches(['sector', '150'], 'Plot 2, Sector-150, Noida')
    assert not matches(['sector', '150'], 'Sector 1500 Noida')
    assert matches(['acrevile'], 'ACE Acreville')


def test_address_search_checks_bounded_live_pages_and_refetches_selection(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rows = [(f'UPRERAPRJ{i}', str(100+i)) for i in range(1, 15)]
    http = FakeHTTP(posts=[source_html(rows)])
    fetches = []
    def fetch(url, reg, summary):
        fetches.append(reg)
        address = 'Sector 150 Noida' if reg == 'UPRERAPRJ13' else 'Sector 15 Noida'
        return {'property_data': {'basic_details': {'address': address}}}
    service = LiveScraper(session_factory=lambda: http, fetcher=fetch, scanner=fetch)
    token = service.start('sector 150 Noida')['session_id']
    first = service.submit_captcha(token, 'ABC12')
    assert first['projects'] == [] and first['has_more'] and len(fetches) == 12
    payload = next(c[2]['data'] for c in http.calls if c[0] == 'POST')
    assert payload[PREFIX+'DdlprojectDistrict'] == 'Gautam Buddha Nagar'
    assert payload[PREFIX+'txtProject1'] == ''
    second = service.next_matches(token)
    assert not second['has_more'] and len(fetches) == 14
    assert [p['registration_number'] for p in second['projects']] == ['UPRERAPRJ13']
    with pytest.raises(LiveScrapeError):
        service.select(token, 'UPRERAPRJ1')
    service.select(token, 'UPRERAPRJ13')
    assert fetches.count('UPRERAPRJ13') == 2
    assert not service.sessions and list(tmp_path.iterdir()) == []


def test_address_source_failure_is_retryable_not_no_match():
    http = FakeHTTP()
    attempts = []
    def fetch(*args):
        attempts.append(1)
        if len(attempts) == 1:
            raise LiveScrapeError('Temporary failure')
        return {'property_data': {'basic_details': {'address': 'Sector 150'}}}
    service = LiveScraper(session_factory=lambda: http, fetcher=fetch, scanner=fetch)
    token = service.start('sector 150 Noida')['session_id']
    result = service.submit_captcha(token, 'ABC12')
    assert result['has_more'] and 'queued to retry' in result['message']
    result = service.next_matches(token)
    assert len(result['projects']) == 1 and not result['has_more']
    service.close()


def test_address_scan_terminates_with_explicit_incomplete_on_permanent_failure():
    http = FakeHTTP()
    def fail(*args):
        raise LiveScrapeError('Source offline')
    service = LiveScraper(session_factory=lambda: http, fetcher=fail, scanner=fail)
    token = service.start('sector 150 Noida')['session_id']
    result = service.submit_captcha(token, 'ABC12')
    for _ in range(2):
        assert result['has_more'] and not result['search_complete']
        result = service.next_matches(token)
    assert not result['has_more'] and not result['search_complete']
    assert result['failed'] == 1 and result['total'] == 1
    assert 'incomplete' in result['message']
    service.close()


def test_browser_automatically_loads_all_address_matches():
    from playwright.sync_api import sync_playwright
    calls = []
    html = Path(__file__).resolve().parents[1].joinpath('src/live_dashboard.html').read_text()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        def respond(route):
            calls.append(route.request.url)
            final = len(calls) == 3
            route.fulfill(json={
                'status': 'select_project', 'session_id': 'live-search',
                'has_more': not final, 'projects': [] if not final else [{
                    'registration_number': REG, 'project_name': 'Area match',
                    'district': 'Noida', 'promoter_name': 'Builder', 'address': 'Sector 150'}],
                'message': 'Search complete' if final else 'Search still running',
            })
        page.route('http://test.local/api/**', respond)
        page.route('http://test.local/', lambda route: route.fulfill(content_type='text/html', body=html))
        page.goto('http://test.local/')
        page.locator('#query').fill('sector 150 Noida')
        page.locator('#searchButton').click()
        page.wait_for_function("document.getElementById('status').textContent==='Search complete' && !busy")
        assert len(calls) == 3 and all(url.endswith('/more') for url in calls[1:])
        assert page.locator('.candidate').count() == 1
        assert page.get_by_text('Check more live projects').count() == 0
        browser.close()


def test_lightweight_scan_reads_location_fields_and_checks_identity():
    from src.scraper.live import parse_search_fields
    prefix = 'ctl00_ContentPlaceHolder1_'
    html = f'''<span id="{prefix}lblProjectNameWithID">Project Id: ({REG})</span>
    <span id="{prefix}lblProjectName">ACE</span>
    <input id="{prefix}projetaddress" value="Plot 2">
    <span id="{prefix}lblVillage">Sector 150</span>
    <select id="{prefix}ddlDistrict"><option>All</option><option selected>Noida</option></select>
    <table><tr><td>Unneeded unit information</td></tr></table>'''
    basic = parse_search_fields(html, REG)['property_data']['basic_details']
    assert basic == {'address': 'Plot 2', 'village_locality_sector': 'Sector 150', 'district': 'Noida'}
    with pytest.raises(LiveScrapeError):
        parse_search_fields(html, 'UPRERAPRJ5')
    with pytest.raises(LiveScrapeError):
        parse_search_fields('<html>Maintenance</html>', REG)


def test_address_scan_uses_lightweight_locality_without_full_extraction():
    http = FakeHTTP()
    def scan(*args):
        return {'property_data': {'basic_details': {'address': 'Plot 2', 'village_locality_sector': 'Sector 150'}}}
    service = LiveScraper(session_factory=lambda: http, scanner=scan,
                          fetcher=lambda *args: pytest.fail('Must not fully extract candidates'))
    token = service.start('Sector 150 Noida')['session_id']
    result = service.submit_captcha(token, 'ABC12')
    assert len(result['projects']) == 1 and result['search_complete']
    service.close()
