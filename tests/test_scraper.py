import base64
import json

import pytest
from playwright.sync_api import sync_playwright

from src.scraper.project_links import (project_ids_from_viewstate, project_ids_from_html,
                                      normalize_details_url)
from src.scraper.up_rera import UPRERAScraper
from src.scraper.project_details_extractor import ProjectDetailsExtractor
from src.scraper.validation import InvalidProjectDetails, is_valid_result
from src.scraper.district_dataset import (is_already_scraped, save_project_json,
    build_result, build_error_result, build_dataset_from_directory, project_json_path)
from src.scraper.detail_page import scrape_detail_page


def _encode(value):
    """Minimal ASP.NET serialization for synthetic, session-free test fixtures."""
    def length(n):
        result = b""
        while n >= 128:
            result += bytes([(n & 127) | 128])
            n >>= 7
        return result + bytes([n])
    if value is None:
        return b"\x64"
    if isinstance(value, str):
        text = value.encode()
        return b"\x05" + length(len(text)) + text
    if isinstance(value, int):
        return b"\x02" + length(value)
    if isinstance(value, tuple):
        return b"\x0f" + b"".join(_encode(x) for x in value)
    return b"\x16" + length(len(value)) + b"".join(_encode(x) for x in value)


def viewstate(rows):
    def field(value):
        return ((["Text", value], None), None)
    serialized = []
    for index, (reg, project_id) in enumerate(rows, 1):
        serialized.append((None, [0, (None, [1, field(project_id), 3, field("S")]),
                                 1, (None, [0, ([str(index)], None)]),
                                 2, (None, [1, field(reg)]),
                                 3, (None, [1, field("Test project")])]))
    return base64.b64encode(b"\xff\x01" + _encode(serialized)).decode()


@pytest.fixture(scope="module")
def page():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        yield page
        browser.close()


def test_internal_ids_are_not_registration_digits():
    rows = [("UPRERAPRJ918", "918"), ("UPRERAPRJ697894", "19021"),
            ("UPRERAPRJ248777/03/2025", "1300671")]
    assert project_ids_from_viewstate(viewstate(rows)) == dict(rows)


def test_conflicting_mapping_rejected():
    with pytest.raises(ValueError, match="Conflicting"):
        project_ids_from_viewstate(viewstate([("UPRERAPRJ918", "918"), ("UPRERAPRJ918", "999")]))


def test_split_viewstate():
    value = viewstate([("UPRERAPRJ697894", "19021")])
    html = (f'<input id="__VIEWSTATEFIELDCOUNT" value="2">'
            f'<input id="__VIEWSTATE" value="{value[:20]}">'
            f'<input id="__VIEWSTATE1" value="{value[20:]}">')
    assert project_ids_from_html(html) == {"UPRERAPRJ697894": "19021"}


@pytest.mark.parametrize("url", ["/Frm_View_Project_Details.aspx?id=19021",
    "Frm_View_Project_Details.aspx?id=19021",
    "window.open('Frm_View_Project_Details.aspx?id=19021', '_blank')"])
def test_relative_and_script_detail_links(url):
    assert normalize_details_url(url) == "https://up-rera.in/Frm_View_Project_Details.aspx?id=19021"


def test_unknown_id_is_not_guessed():
    scraper = UPRERAScraper(None)
    with pytest.raises(ValueError, match="authoritative"):
        scraper._build_row_data_from_raw({"values": ["1", "UPRERAPRJ697894", "Test"], "links": []})


def test_browser_search_uses_viewstate_and_exact_registration(page):
    state = viewstate([("UPRERAPRJ697894", "19021"), ("UPRERAPRJ6978940", "19022")])
    page.set_content(f'''<input id="__VIEWSTATE" value="{state}">
        <table id="ctl00_ContentPlaceHolder1_GridView1">
        <tr><td>1</td><td><span id="r_lblRegistrationNo">UPRERAPRJ697894</span></td><td>Test</td>
        <td>Promoter</td><td>District</td><td>Commercial</td><td>NA</td><td><a href="javascript:__doPostBack('r','')">View</a></td></tr>
        <tr><td>2</td><td><span id="s_lblRegistrationNo">UPRERAPRJ6978940</span></td><td>Another</td></tr></table>''')
    scraper = UPRERAScraper(page)
    rows = scraper.extract_all_rows_data()
    assert len(rows) == 2
    assert rows[0]["details_url"].endswith("id=19021")
    assert scraper.find_project_row("UPRERAPRJ697894").locator("td").nth(2).inner_text() == "Test"
    assert scraper.find_project_row("UPRERAPRJ697") is None


def details_html(reg="UPRERAPRJ697894"):
    return f'''<div id="ctl00_ContentPlaceHolder1_content">
      Project Name: Test Project Project Id: ({reg}) Registration Date: 27-02-2019
      Promoter Name: Example Promoter Promoter Id: (UPRERAPRM123)
      <textarea id="ctl00_ContentPlaceHolder1_lblProjectName">Test Project</textarea>
      <input id="ctl00_ContentPlaceHolder1_lblTotalArea" value="10000">
      <span id="ctl00_ContentPlaceHolder1_lblProjectType">New</span>
      <span id="ctl00_ContentPlaceHolder1_lblProjectCategory">Commercial</span>
      <span id="ctl00_ContentPlaceHolder1_lblRegistrationFee">110000</span>
      <span id="ctl00_ContentPlaceHolder1_projetaddress">Test address</span>
      <table><tr><td><table><tr><th>SNo.</th><th>Document Name</th><th>Uploaded File Name</th><th>Uploaded Date</th><th>Upload Doc Type</th></tr>
      <tr><td>1</td><td>Test deed</td><td>deed.pdf</td><td></td><td>Original</td></tr></table></td></tr></table>
      <div style="display:none"><table><tr><th>Sr. No.</th><th>Type</th><th>Khasra No</th><th>Khasra Area</th></tr>
      <tr><td>1</td><td>Plot</td><td>C-01</td><td>10000</td></tr></table>
      <table><tr><th>Sr. No.</th><th>Document Name</th><th>Number</th><th>Date</th><th>Uploaded Document</th></tr>
      <tr><td>1</td><td>Lease Deed</td><td>10483</td><td>30-04-2013</td><td>lease.pdf</td></tr></table>
      <table><tr><th>Sr. No.</th><th>Floor Number</th><th>Unit Carpet Area</th><th>Number of Apartment</th></tr>
      <tr><td>1</td><td>Ground</td><td>80</td><td>2</td></tr></table></div>
      <a href="/progress.pdf">Project progress certificate</a></div>
      <footer><a href="/template.pdf">Form REG certificate</a></footer>'''


def test_real_dom_extraction_covers_labels_collapsed_sections_and_leaf_tables(page):
    page.set_content(details_html())
    data = ProjectDetailsExtractor(page).extract_structured("UPRERAPRJ697894")
    assert data["basic_details"]["project_type"] == "New"
    assert data["basic_details"]["address"] == "Test address"
    assert data["basic_details"]["registration_fee_rs"] == "110000"
    assert len(data["documents"]) == 1
    assert data["documents"][0]["document_type"] == "Original"
    assert data["land_details"]["khasra_plot_details"][0]["khasra_plot_number"] == "C-01"
    assert data["land_details"]["registry_agreement_details"][0]["registry_agreement_number"] == "10483"
    assert data["plan_and_unit_details"]["unit_records"] == [["1", "Ground", "80", "2"]]
    assert len(data["quarterly_progress"]["links"]) == 1


def test_maintenance_and_wrong_project_rejected(page):
    page.set_content("<h1>Server maintenance</h1>")
    with pytest.raises(InvalidProjectDetails):
        ProjectDetailsExtractor(page).extract_structured("UPRERAPRJ697894")
    page.set_content(details_html("UPRERAPRJ918"))
    with pytest.raises(InvalidProjectDetails, match="Wrong project"):
        ProjectDetailsExtractor(page).extract_structured("UPRERAPRJ697894")


def result():
    return build_result("UPRERAPRJ248777/03/2025", {}, "https://up-rera.in/Frm_View_Project_Details.aspx?id=1300671", {
        "identification": {"project_id": "UPRERAPRJ248777/03/2025", "project_name": "Test"},
        "basic_details": {"total_area_sq_m": "10000"}, "page": {"url": "https://up-rera.in/Frm_View_Project_Details.aspx?id=1300671"}})


def test_resume_retries_failed_empty_corrupt_and_wrong_records(tmp_path):
    reg = "UPRERAPRJ248777/03/2025"
    p = project_json_path(tmp_path, reg)
    assert p.name == "UPRERAPRJ248777_03_2025.json"
    assert not is_already_scraped(tmp_path, reg)
    for bad in ["{", "null", "[]", json.dumps(build_error_result(reg, {}, RuntimeError("failed"))),
                json.dumps({"project_found": True, "project_details_available": True, "property_data": {}})]:
        p.write_text(bad)
        assert not is_already_scraped(tmp_path, reg)
    wrong = result()
    wrong["property_data"]["identification"]["project_id"] = "UPRERAPRJ918"
    p.write_text(json.dumps(wrong))
    assert not is_already_scraped(tmp_path, reg)
    save_project_json(tmp_path, reg, result())
    assert is_already_scraped(tmp_path, reg)


def test_failed_refresh_preserves_last_good_result(tmp_path):
    reg = "UPRERAPRJ248777/03/2025"
    save_project_json(tmp_path, reg, result())
    save_project_json(tmp_path, reg, build_error_result(reg, {}, RuntimeError("HTTP 503")))
    assert is_already_scraped(tmp_path, reg)
    assert (tmp_path / "_failures" / project_json_path(tmp_path, reg).name).exists()
    save_project_json(tmp_path, reg, result())
    assert not list((tmp_path / "_failures").glob("*.json"))
    assert not list(tmp_path.glob("*.tmp"))


def test_dataset_counts_failures_separately(tmp_path):
    save_project_json(tmp_path, "UPRERAPRJ248777/03/2025", result())
    save_project_json(tmp_path, "UPRERAPRJ918", build_error_result("UPRERAPRJ918", {}, RuntimeError("failed")))
    data = json.loads(build_dataset_from_directory(tmp_path, "Test").read_text())
    assert (data["total_projects"], data["successful_projects"], data["failed_projects"]) == (2, 1, 1)


def test_live_navigation_rejects_http_failure(page):
    page.route("**/Frm_View_Project_Details.aspx*", lambda route: route.fulfill(status=503, body="Maintenance"))
    with pytest.raises(InvalidProjectDetails, match="HTTP 503"):
        scrape_detail_page(page, "https://up-rera.in/Frm_View_Project_Details.aspx?id=19021", "UPRERAPRJ697894")
    page.unroute("**/Frm_View_Project_Details.aspx*")


def test_resumable_extractor_upgrade(tmp_path):
    reg = "UPRERAPRJ248777/03/2025"
    old = result()
    old.pop("scraper_version")
    save_project_json(tmp_path, reg, old)
    assert is_already_scraped(tmp_path, reg)
    assert not is_already_scraped(tmp_path, reg, min_version=2)
    save_project_json(tmp_path, reg, result())
    assert is_already_scraped(tmp_path, reg, min_version=2)


def test_interrupted_atomic_replace_keeps_original(tmp_path, monkeypatch):
    from src.scraper import district_dataset
    reg = "UPRERAPRJ248777/03/2025"
    path = save_project_json(tmp_path, reg, result())
    original = path.read_bytes()
    def disk_error(*args):
        raise OSError("Simulated disk failure")
    monkeypatch.setattr(district_dataset.os, "replace", disk_error)
    with pytest.raises(OSError):
        save_project_json(tmp_path, reg, result())
    assert path.read_bytes() == original
    assert not list(tmp_path.glob(".scrape-*.tmp"))


def test_worker_retries_transient_failure_and_saves_verified_result(tmp_path, monkeypatch):
    import scrape_details_parallel as runner
    reg = "UPRERAPRJ248777/03/2025"
    calls = []
    class Page:
        url = "https://up-rera.in/Frm_View_Project_Details.aspx?id=1300671"
        def is_closed(self):
            return False
    class Browser:
        def __init__(self, **kwargs):
            self.browser = self
        def start(self):
            return Page()
        def is_connected(self):
            return True
        def close(self):
            pass
    def scrape(*args):
        calls.append(args)
        if len(calls) == 1:
            raise InvalidProjectDetails("Temporary maintenance")
        return result()["property_data"]
    monkeypatch.setattr(runner, "BrowserManager", Browser)
    monkeypatch.setattr(runner, "scrape_detail_page", scrape)
    monkeypatch.setattr(runner.time, "sleep", lambda _: None)
    summary = runner.scrape_chunk([{"registration_number": reg, "details_url": Page.url}],
                                  str(tmp_path), 1, 2, 0, 0)
    assert summary == {"worker_id": 1, "succeeded": 1, "failed": 0}
    assert len(calls) == 2
    assert is_already_scraped(tmp_path, reg)
