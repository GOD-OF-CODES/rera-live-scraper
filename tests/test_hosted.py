import requests
import pytest
from cryptography.fernet import Fernet
from src.scraper.hosted_sessions import HostedSessions
from src.scraper.live import LiveScraper, LiveScrapeError
from test_live_scraper import FakeHTTP, REG, source_html


def test_hosted_search_survives_fresh_instances_and_rejects_tampering():
    connections = []
    def factory():
        http = FakeHTTP(posts=[source_html([(REG, '1300671'), ('UPRERAPRJ5', '5')])])
        http.cookies = requests.cookies.RequestsCookieJar()
        http.cookies.set('ASP.NET_SessionId', 'test-source-session')
        connections.append(http)
        return LiveScraper(session_factory=lambda: http, fetcher=lambda *args: {'registration_number': args[1]})
    key = Fernet.generate_key()
    challenge = HostedSessions(key, factory).execute('start', 'Oro')
    assert 'test-source-session' not in challenge['session_state']
    token = challenge['session_id']
    candidates = HostedSessions(key, factory).execute('submit_captcha', token, 'ABC12', session_state=challenge['session_state'])
    assert len(candidates['projects']) == 2
    result = HostedSessions(key, factory).execute('select', token, REG, session_state=candidates['session_state'])
    assert result['status'] == 'complete' and 'session_state' not in result
    assert all(http.closed for http in connections)
    with pytest.raises(LiveScrapeError):
        HostedSessions(key, factory).execute('next_matches', token, session_state=challenge['session_state'][:-10]+'tampered')
    with pytest.raises(LiveScrapeError):
        HostedSessions(key, factory).execute('next_matches', 'another-search', session_state=challenge['session_state'])
    with pytest.raises(LiveScrapeError):
        HostedSessions(Fernet.generate_key(), factory).execute('next_matches', token, session_state=challenge['session_state'])


def test_http_extraction_includes_hidden_tables_and_rejects_wrong_registration():
    from src.scraper.http_details import extract_html
    html = f'''<html><title>RERA</title><body><div id="ctl00_ContentPlaceHolder1_main">
    <span id="ctl00_ContentPlaceHolder1_lblProjectNameHeading">Project Name: Test Project</span>
    <span id="ctl00_ContentPlaceHolder1_lblProjectNameWithID">Project Id: ({REG})</span>
    <span id="ctl00_ContentPlaceHolder1_lblProjectName">Test Project</span>
    <span id="ctl00_ContentPlaceHolder1_projetaddress">Sector 150</span>
    <span id="ctl00_ContentPlaceHolder1_ddlDistrict">Noida</span>
    <div style="display:none"><table><tr><th>Sr. No.</th><th>Type</th><th>Khasra No</th><th>Khasra Area</th></tr>
    <tr><td>1</td><td>Plot</td><td>GH-01</td><td>100</td></tr></table></div>
    </div></body></html>'''
    data = extract_html(html, 'https://up-rera.in/Frm_View_Project_Details.aspx?id=5', REG)
    assert data['identification']['project_id'] == REG
    assert data['basic_details']['address'] == 'Sector 150'
    assert data['land_details']['khasra_plot_details'][0]['khasra_plot_number'] == 'GH-01'
    with pytest.raises(ValueError):
        extract_html(html, 'https://up-rera.in/Frm_View_Project_Details.aspx?id=5', 'UPRERAPRJ5')
