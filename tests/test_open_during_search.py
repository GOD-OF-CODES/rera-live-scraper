"""Opening a project must not interfere with the ongoing scan or its token."""
from pathlib import Path
from urllib.parse import urlparse

import pytest
from playwright.sync_api import sync_playwright

from test_live_scraper import REG, URL


@pytest.mark.parametrize('outcome', ['success', 'failure', 'wrong_project'])
def test_project_opens_while_scan_continues_with_independent_state(outcome):
    html = Path('src/live_dashboard.html').read_text()
    first_project = {'registration_number': REG, 'project_name': 'First match',
                     'district': 'Lucknow', 'promoter_name': 'Builder', 'details_url': URL}
    second_project = {**first_project, 'registration_number': 'UPRERAPRJ5',
                      'project_name': 'Later match',
                      'details_url': 'https://up-rera.in/Frm_View_Project_Details.aspx?id=5'}
    pending = []
    scan_bodies = []
    detail_queries = []

    def scan_result(version, more, projects):
        return {'status': 'select_project', 'session_id': 'original-search',
                'session_state': f'scan-v{version}', 'projects': projects,
                'has_more': more, 'message': 'Still searching' if more else 'Search complete'}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()

        def respond(route):
            path = urlparse(route.request.url).path
            if path == '/':
                route.fulfill(content_type='text/html', body=html)
                return
            body = route.request.post_data_json
            if path == '/api/live/search':
                if body['query'] == 'Plot CP-4/2 Lucknow':
                    route.fulfill(json=scan_result(1, True, [first_project]))
                else:
                    assert body == {'query': URL}, 'Project tabs must not inherit the scan token'
                    detail_queries.append(body)
                    if outcome == 'failure':
                        route.fulfill(status=502, json={'message': 'Details temporarily unavailable'})
                    else:
                        route.fulfill(json={'status': 'complete', 'result': {
                            'registration_number': 'UPRERAPRJ999' if outcome == 'wrong_project' else REG, 'project_details_url': URL,
                            'scraped_at': '2026-10-09T10:00:00Z',
                            'property_data': {'identification': {'project_name': 'First match'},
                                              'basic_details': {'district': 'Lucknow'}}}})
                return
            assert path == '/api/live/search/original-search/more', 'Opening must not select or cancel the search'
            scan_bodies.append(body)
            if len(scan_bodies) == 1:
                pending.append(route)  # Keep an actual scan request in flight while opening details.
            else:
                route.fulfill(json=scan_result(3, False, [first_project, second_project]))

        context.route('http://test.local/**', respond)
        search = context.new_page()
        search.goto('http://test.local/')
        search.locator('#query').fill('Plot CP-4/2 Lucknow')
        search.locator('#searchButton').click()
        search.wait_for_function("busy && document.querySelector('a.candidate') !== null")
        search.wait_for_timeout(100)  # Allow the held continuation request to reach the route.
        assert pending and scan_bodies == [{'session_state': 'scan-v1'}]
        link = search.locator('a.candidate')
        assert link.get_attribute('target') == '_blank'
        assert 'noopener' in link.get_attribute('rel')
        assert 'Open details in a new tab' in link.inner_text()

        with search.expect_popup() as opened:
            link.click()
        detail = opened.value
        detail.wait_for_load_state('domcontentloaded')
        if outcome == 'failure':
            detail.wait_for_function("document.getElementById('status').textContent==='Details temporarily unavailable'")
        elif outcome == 'wrong_project':
            detail.wait_for_function("document.getElementById('status').textContent.includes('different project')")
            assert not detail.locator('#result').is_visible()
        else:
            detail.locator('#result').wait_for(state='visible')
            assert detail.locator('#projectName').inner_text() == 'First match'
            assert detail.locator('#exportButton').is_enabled()

        assert len(detail_queries) == 1
        assert search.evaluate('busy')
        assert search.evaluate('sessionState') == 'scan-v1'
        assert search.locator('#status').inner_text() == 'Still searching'
        pending.pop().fulfill(json=scan_result(2, True, [first_project, second_project]))
        search.wait_for_function("!busy && document.getElementById('status').textContent==='Search complete'")
        assert scan_bodies == [{'session_state': 'scan-v1'}, {'session_state': 'scan-v2'}]
        assert search.locator('a.candidate').count() == 2
        assert search.evaluate('sessionState') == 'scan-v3'
        assert detail.locator('#projectName').inner_text() == ('First match' if outcome == 'success' else '')
        browser.close()
