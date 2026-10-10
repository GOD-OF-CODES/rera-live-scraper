"""Request-scoped UP-RERA scraping. No database, project index or disk cache."""

import base64
from concurrent.futures import ThreadPoolExecutor
import secrets
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup, SoupStrainer

from src.scraper.search_intent import interpret, matches, matching_parcels
from src.scraper.browser import BrowserManager
from src.scraper.detail_page import scrape_detail_page
from src.scraper.project_links import (
    BASE_URL, DETAILS_URL, REGISTRATION, normalize_registration,
    normalize_details_url, project_ids_from_html,
)

SEARCH_URL = BASE_URL + "View_projects.aspx"
PREFIX = "ctl00$ContentPlaceHolder1$"
GRID_ID = "ctl00_ContentPlaceHolder1_GridView1"


class LiveScrapeError(Exception):
    def __init__(self, message, code="source_unavailable", status_code=502):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def official_detail_url(value):
    """Validate client URLs before opening them; accept only this public endpoint."""
    try:
        parsed = urlparse(value)
        port = parsed.port
    except ValueError as exc:
        raise LiveScrapeError("Enter a valid official UP-RERA details URL.", "invalid_url", 422) from exc
    ids = parse_qs(parsed.query).get("id", [])
    if (parsed.scheme != "https" or parsed.hostname not in {"up-rera.in", "www.up-rera.in"}
            or port not in (None, 443) or parsed.username or parsed.password
            or parsed.path.lower() != "/frm_view_project_details.aspx"
            or len(ids) != 1 or not ids[0].isdigit()):
        raise LiveScrapeError("Enter an official UP-RERA project details URL.", "invalid_url", 422)
    return DETAILS_URL.format(ids[0])


def form_values(soup):
    form = soup.find("form")
    if not form:
        raise LiveScrapeError("RERA did not return its search form.")
    values = {}
    for element in form.select("input[name], select[name], textarea[name]"):
        kind = element.get("type", "text").lower()
        if element.has_attr("disabled") or kind in {"submit", "button", "image", "file"}:
            continue
        if kind in {"checkbox", "radio"} and not element.has_attr("checked"):
            continue
        if element.name == "select":
            option = element.find("option", selected=True) or element.find("option")
            value = option.get("value", option.get_text()) if option else ""
        elif element.name == "textarea":
            value = element.get_text()
        else:
            value = element.get("value", "")
        values[element["name"]] = value
    return values


def search_rows(html, query):
    """Resolve only the rows returned by this live query, never registration digits."""
    soup = BeautifulSoup(html, "html.parser")
    grid = soup.find(id=GRID_ID)
    if not grid:
        return []
    try:
        mapping = project_ids_from_html(html)
    except Exception as exc:
        raise LiveScrapeError("Could not read the internal project IDs returned by RERA.") from exc
    expected = normalize_registration(query)
    exact_registration = bool(REGISTRATION.fullmatch(expected))
    results = []
    seen = set()
    for tr in grid.find_all("tr"):
        cells = tr.find_all("td", recursive=False)
        if len(cells) < 7 or not cells[0].get_text(strip=True).isdigit():
            continue
        reg_label = cells[1].find("span")
        reg = normalize_registration(reg_label.get_text() if reg_label else cells[1].get_text())
        if not REGISTRATION.fullmatch(reg) or reg in seen or (exact_registration and reg != expected):
            continue
        project_id = mapping.get(reg)
        links = [a.get("href", "") for a in cells[7].find_all("a")] if len(cells) > 7 else []
        detail_url = DETAILS_URL.format(project_id) if project_id else next(
            (url for link in links if (url := normalize_details_url(link))), None)
        if not detail_url:
            raise LiveScrapeError(f"RERA returned {reg} without a resolvable project link.", "unresolved_project")
        name = cells[2].find("span")
        promoter = cells[3].find_all("li")
        results.append({
            "registration_number": reg,
            "project_name": name.get_text(" ", strip=True) if name else cells[2].get_text(" ", strip=True),
            "promoter_name": "; ".join(x.get_text(" ", strip=True) for x in promoter)
                             or cells[3].get_text(" ", strip=True),
            "district": cells[4].get_text(" ", strip=True),
            "project_type": cells[5].get_text(" ", strip=True),
            "approval_certificate": cells[6].get_text(" ", strip=True),
            "details_url": detail_url,
        })
        seen.add(reg)
    return results


def fetch_project_live(details_url, registration_number=None, summary=None):
    """Always fetch the source now; return the record without writing it anywhere."""
    url = official_detail_url(details_url)
    browser = BrowserManager(headless=True)
    requested_at = datetime.now(timezone.utc).isoformat()
    try:
        page = browser.start()
        data = scrape_detail_page(page, url, registration_number)
        reg = data["identification"]["project_id"]
        return {
            "source": "UP-RERA", "fetch_mode": "live", "from_cache": False,
            "persisted": False, "registration_number": reg,
            "project_found": True, "project_details_available": True,
            "requested_at": requested_at,
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            "search_url": SEARCH_URL, "project_details_url": page.url,
            "search_result": summary or {}, "property_data": data,
        }
    except LiveScrapeError:
        raise
    except Exception as exc:
        raise LiveScrapeError(f"The live RERA fetch failed: {exc}") from exc
    finally:
        browser.close()


def fetch_project_http(details_url, registration_number=None, summary=None):
    from src.scraper.http_details import extract_html
    url = official_detail_url(details_url)
    requested_at = datetime.now(timezone.utc).isoformat()
    with requests.get(url, timeout=(10, 60)) as response:
        response.raise_for_status()
        if official_detail_url(response.url) != url:
            raise LiveScrapeError("RERA returned an unexpected project redirect.")
        try:
            data = extract_html(response.text, url, registration_number)
        except ValueError as exc:
            raise LiveScrapeError(str(exc)) from exc
    return {"source": "UP-RERA", "fetch_mode": "live", "from_cache": False,
            "persisted": False, "registration_number": data["identification"]["project_id"],
            "project_found": True, "project_details_available": True,
            "requested_at": requested_at, "scraped_at": datetime.now(timezone.utc).isoformat(),
            "search_url": SEARCH_URL, "project_details_url": url,
            "search_result": summary or {}, "property_data": data}


def fetch_search_fields(details_url, registration_number, summary=None, *, session=None):
    """Read location fields and, for parcel queries, identifier columns over HTTP."""
    url = official_detail_url(details_url)
    http = session or requests
    with http.get(url, timeout=(10, 30)) as response:
        response.raise_for_status()
        if official_detail_url(response.url) != url:
            raise LiveScrapeError("RERA redirected the address check to another project.")
        return parse_search_fields(response.text, registration_number,
                                   include_parcels=bool(summary and summary.get('_search_parcels')))


def parse_search_fields(html, registration_number, include_parcels=False):
    from lxml import html as html_parser
    root = html_parser.fromstring(html)

    def value(suffix):
        elements = root.xpath('//*[@id=$id]', id='ctl00_ContentPlaceHolder1_' + suffix)
        if not elements:
            return ''
        element = elements[0]
        if element.tag == 'select':
            options = element.xpath('./option[@selected]') or element.xpath('./option')
            return options[0].text_content().strip() if options else ''
        return element.get('value', element.text_content()).strip()

    identity = re.search(r"Project Id\s*:\s*\(([^)]+)\)", value("lblProjectNameWithID"), re.I)
    if not identity or normalize_registration(identity[1]) != normalize_registration(registration_number) or not value("lblProjectName"):
        raise LiveScrapeError("The address check returned an invalid or different project.")
    result = {"property_data": {"basic_details": {
        "address": value("projetaddress"), "village_locality_sector": value("lblVillage"),
        "district": value("ddlDistrict"),
    }}}
    if value('ddlTehsil'):
        result['property_data']['basic_details']['tehsil'] = value('ddlTehsil')
    if include_parcels:
        result['property_data']['search_parcels'] = parse_parcel_tables(html, root=root)
    return result


def parse_parcel_tables(html, root=None):
    """Read only published identifier columns, preserving type and compound IDs."""
    from lxml import html as html_parser
    root = root if root is not None else html_parser.fromstring(html)
    records = []
    for table in root.iter('table'):
        if table.xpath('.//table'):
            continue
        # Large unit inventories are irrelevant to a parcel lookup. Inspect
        # their headings before walking thousands of apartment rows.
        heading_cells = table.xpath('./tr[1]/* | ./thead/tr[1]/* | ./tbody/tr[1]/*')
        if not any(re.search(r'\b(?:khasra|plot)\b', cell.text_content(), re.I)
                   for cell in heading_cells):
            continue
        columns, width, type_column = {}, 0, None
        for row in table.iter('tr'):
            cells = [cell for cell in row if cell.tag in {'td', 'th'}]
            values = [' '.join(cell.text_content().split()) for cell in cells]
            headers = {}
            for index, value in enumerate(values):
                label = re.sub(r'[^a-z]+', ' ', value.lower()).strip()
                if re.fullmatch(r'(?:khasra(?: plot)?|plot|villa plot) (?:no|number|nos|numbers)', label):
                    headers[index] = ([kind for kind in ('khasra', 'plot') if kind in label], value)
            if headers:
                columns, width = headers, len(values)
                type_column = next((i for i, v in enumerate(values) if v.lower() == 'type'), None)
                continue
            if len(values) != width or any(cell.get('colspan', '1') != '1' for cell in cells):
                continue
            for index, (kinds, label) in columns.items():
                if index < len(values) and values[index]:
                    record_type = values[type_column].lower() if type_column is not None else ''
                    record_kinds = [record_type] if record_type in ('plot', 'khasra') else kinds
                    records.append({'number': values[index], 'kinds': record_kinds,
                                    'source': f'Published RERA table: {label}'})
    return records


@dataclass
class SearchSession:
    query: str
    http: requests.Session
    expires_at: float
    fields: dict = field(default_factory=dict)
    rows: list = field(default_factory=list)
    intent: dict = field(default_factory=dict)
    candidates: list = field(default_factory=list)
    scan_offset: int = 0
    scan_attempts: dict = field(default_factory=dict)
    scan_failures: set = field(default_factory=set)
    lock: threading.Lock = field(default_factory=threading.Lock)


class LiveScraper:
    """Short-lived CAPTCHA sessions, not a property database or results cache.

    Sessions contain only cookies, search form state and candidate rows. They are
    removed after a completed request, cancellation or ten minutes of inactivity.
    """

    def __init__(self, session_factory=requests.Session, fetcher=fetch_project_live,
                 ttl=600, max_sessions=8, clock=time.monotonic, scanner=fetch_search_fields):
        self.session_factory = session_factory
        self.fetcher = fetcher
        self.scanner = scanner
        self.scan_slots = threading.BoundedSemaphore(6)
        self.ttl = ttl
        self.max_sessions = max_sessions
        self.clock = clock
        self.sessions = {}
        self.lock = threading.Lock()
        self.fetch_slots = threading.BoundedSemaphore(4)

    def prune(self):
        with self.lock:
            for token, state in list(self.sessions.items()):
                if state.expires_at <= self.clock() and state.lock.acquire(blocking=False):
                    try:
                        self.sessions.pop(token)
                        state.http.close()
                    finally:
                        state.lock.release()

    def close(self):
        with self.lock:
            for state in self.sessions.values():
                state.http.close()
            self.sessions.clear()

    def _remove(self, token):
        with self.lock:
            state = self.sessions.pop(token, None)
        if state:
            state.http.close()

    def _acquire(self, token):
        self.prune()
        with self.lock:
            state = self.sessions.get(token)
            if state is None:
                raise LiveScrapeError("This search has expired. Start a new live search.", "session_expired", 410)
            if not state.lock.acquire(blocking=False):
                raise LiveScrapeError("This search is already running.", "search_busy", 409)
            state.expires_at = self.clock() + self.ttl
        return state

    def cancel(self, token):
        state = self._acquire(token)
        try:
            self._remove(token)
        finally:
            state.lock.release()

    @staticmethod
    def _check_response(response):
        response.raise_for_status()
        parsed = urlparse(response.url)
        if (parsed.hostname not in {"up-rera.in", "www.up-rera.in"}
                or any(word in parsed.path.lower() for word in ("maintenance", "error", "login"))):
            raise LiveScrapeError("RERA redirected the request to an unavailable or error page.")

    def _challenge(self, token, state, html, message=None):
        soup = BeautifulSoup(html, "html.parser")
        state.fields = form_values(soup)
        state.intent = interpret(state.query, soup, PREFIX)
        if state.intent.get('parcels') and not state.intent['district']:
            raise LiveScrapeError('Include a city or district with the plot/khasra number, '
                                 'for example "Khasra 123/4 Lucknow" or "Plot GH-03 Noida".',
                                 'refine_query', 422)
        captcha = soup.select_one('img[src*="CaptchaImage"]')
        if not captcha:
            raise LiveScrapeError("RERA's CAPTCHA image is unavailable. Try a new search.")
        image_url = urljoin(SEARCH_URL, captcha["src"])
        parsed = urlparse(image_url)
        if parsed.hostname not in {"up-rera.in", "www.up-rera.in"} or parsed.scheme != "https":
            raise LiveScrapeError("RERA returned an unexpected CAPTCHA address.")
        response = state.http.get(image_url, timeout=30)
        self._check_response(response)
        content_type = response.headers.get("Content-Type", "").split(";")[0]
        if content_type not in {"image/png", "image/jpeg", "image/gif"} or len(response.content) > 1_000_000:
            raise LiveScrapeError("RERA did not return a valid CAPTCHA image.")
        return {
            "status": "captcha_required", "session_id": token, "query": state.query,
            "expires_in_seconds": self.ttl,
            "captcha_image": f"data:{content_type};base64," + base64.b64encode(response.content).decode(),
            "message": message or "Enter the CAPTCHA shown by UP-RERA to search this project live.",
        }

    def _fetch(self, url, reg=None, summary=None):
        if not self.fetch_slots.acquire(blocking=False):
            raise LiveScrapeError("Other live fetches are running. Please try again shortly.", "capacity", 429)
        try:
            return {"status": "complete", "result": self.fetcher(url, reg, summary)}
        finally:
            self.fetch_slots.release()

    def start(self, query):
        query = query.strip()
        if len(query) < 3 or len(query) > 300:
            raise LiveScrapeError("Enter a project name, builder, address with city, registration number or official details URL.", "invalid_query", 422)
        if query.lower().startswith(("http:", "https:")):
            return self._fetch(official_detail_url(query))
        if query.upper().startswith("UPRERAPRJ") and not REGISTRATION.fullmatch(normalize_registration(query)):
            raise LiveScrapeError("Enter the complete UP-RERA registration number.", "invalid_query", 422)
        self.prune()
        with self.lock:
            if len(self.sessions) >= self.max_sessions:
                raise LiveScrapeError("Too many active searches. Try again shortly.", "capacity", 429)
            token = secrets.token_urlsafe(24)
            state = SearchSession(query, self.session_factory(), self.clock() + self.ttl)
            state.lock.acquire()
            self.sessions[token] = state
        try:
            response = state.http.get(SEARCH_URL, timeout=45)
            self._check_response(response)
            return self._challenge(token, state, response.text)
        except Exception:
            self._remove(token)
            raise
        finally:
            state.lock.release()

    def submit_captcha(self, token, captcha):
        captcha = captcha.strip()
        if not captcha or len(captcha) > 20 or not captcha.isalnum():
            raise LiveScrapeError("Enter the letters and numbers in the CAPTCHA.", "invalid_captcha", 422)
        state = self._acquire(token)
        try:
            if state.rows or state.candidates:
                raise LiveScrapeError("Select a project from the search results.", "select_project", 409)
            if not REGISTRATION.fullmatch(normalize_registration(state.query)) and not any(
                    state.intent[k] for k in ("district", "promoter", "project_name")):
                raise LiveScrapeError("Add a project name, builder, or city to narrow the search.", "refine_query", 422)
            payload = dict(state.fields)
            reg = normalize_registration(state.query)
            exact = bool(REGISTRATION.fullmatch(reg))
            payload.update({
                "__EVENTTARGET": "", "__EVENTARGUMENT": "",
                PREFIX + "txt_regid1": reg if exact else "",
                PREFIX + "txtProject1": "" if exact else state.intent["project_name"],
                PREFIX + "DdlprojectDistrict": "0" if exact else state.intent["district"] or "0",
                PREFIX + "ddl_prm": "0" if exact else state.intent["promoter"] or "0",
                PREFIX + "txtcap": captcha,
                PREFIX + "btnSearch": "Search",
            })
            response = state.http.post(SEARCH_URL, data=payload, timeout=60)
            self._check_response(response)
            state.rows = search_rows(response.text, state.query)
            if not state.rows:
                soup = BeautifulSoup(response.text, "html.parser")
                text = soup.get_text(" ", strip=True).lower()
                if soup.find(id=GRID_ID) or any(word in text for word in ("no record found", "no records found", "no records to display", "no project found")):
                    self._remove(token)
                    return {"status": "not_found", "message": "RERA returned no projects matching this query. Try a shorter name, builder name, or add the city to an address."}
                return self._challenge(token, state, response.text,
                                       "RERA did not complete the search. Enter the new CAPTCHA and try again.")
            if not exact and state.intent.get("inspect_details"):
                state.candidates, state.rows = state.rows, []
                terms = state.intent["terms"]
                state.candidates.sort(key=lambda row: sum(
                    matches([term], row["project_name"] + " " + row["promoter_name"])
                    for term in terms), reverse=True)
                return self._scan(token, state)
            if len(state.rows) == 1 and exact:
                row = state.rows[0]
                result = self._fetch(row["details_url"], row["registration_number"], row)
                self._remove(token)
                return result
            return {"status": "select_project", "session_id": token,
                    "projects": state.rows, "message": "Select the project to fetch its current details."}
        finally:
            state.lock.release()

    def _scan(self, token, state):
        """Bounded live address discovery; never download or retain a district dataset."""
        batch = state.candidates[state.scan_offset:state.scan_offset + 12]
        terms = state.intent["terms"]
        parcels = state.intent.get('parcels', [])

        def check(row):
            try:
                with self.scan_slots:
                    scan_row = dict(row, _search_parcels=True) if parcels else row
                    data = self.scanner(row["details_url"], row["registration_number"], scan_row)
                prop = data.get("property_data", {})
                address = prop.get("basic_details", {}).get("address", "") or ""
                locality = prop.get("basic_details", {}).get("village_locality_sector", "") or ""
                text = " ".join([row["project_name"], row["promoter_name"], row["district"], address, locality])
                evidence = matching_parcels(parcels, prop.get('search_parcels', []), address) if parcels else []
                if not matches(terms, text) or (parcels and not evidence):
                    return None, False
                match = dict(row, address=address or locality,
                             match_reason="Published parcel identifier matched" if parcels else
                             "Clues matched on the live RERA page")
                if evidence:
                    match['matched_parcels'] = evidence
                return match, False
            except (LiveScrapeError, requests.RequestException):
                return None, True

        with ThreadPoolExecutor(max_workers=6) as pool:
            checked = list(pool.map(check, batch))
        state.scan_offset += len(batch)
        for row, (_, error) in zip(batch, checked):
            reg = row["registration_number"]
            state.scan_attempts[reg] = state.scan_attempts.get(reg, 0) + 1
            if error:
                if state.scan_attempts[reg] < 3:
                    state.candidates.append(row)
                else:
                    state.scan_failures.add(reg)
            else:
                state.scan_failures.discard(reg)
        seen = {row["registration_number"] for row in state.rows}
        state.rows.extend(row for row, _ in checked if row and row["registration_number"] not in seen)
        more = state.scan_offset < len(state.candidates)
        total = len({row["registration_number"] for row in state.candidates})
        checked_count = len(state.scan_attempts)
        failed = len(state.scan_failures)
        if more:
            message = (f"Searching live RERA pages: {checked_count} of {total} projects checked; "
                       f"{len(state.rows)} matches found so far. Search is still running; "
                       "temporary failures are queued to retry automatically.")
        elif failed:
            message = (f"Search incomplete: {len(state.rows)} matches found, but {failed} project pages "
                       "could not be checked after 3 attempts. These results may be missing projects.")
        else:
            message = (f"Search complete: checked all {total} projects returned by RERA for this district. "
                       f"{len(state.rows)} projects matched your clues in the published information.")
        return {"status": "select_project", "session_id": token, "projects": state.rows,
                "has_more": more, "checked": checked_count, "total": total,
                "failed": failed, "search_complete": not more and not failed,
                "message": message}

    def next_matches(self, token):
        state = self._acquire(token)
        try:
            if not state.candidates:
                raise LiveScrapeError("Start an address search first.", "invalid_search", 422)
            return self._scan(token, state)
        finally:
            state.lock.release()

    def select(self, token, registration_number):
        state = self._acquire(token)
        try:
            reg = normalize_registration(registration_number)
            row = next((row for row in state.rows if row["registration_number"] == reg), None)
            if row is None:
                raise LiveScrapeError("Select a project returned by this live search.", "invalid_selection", 422)
            result = self._fetch(row["details_url"], reg, row)
            self._remove(token)
            return result
        finally:
            state.lock.release()

    def refresh_captcha(self, token):
        state = self._acquire(token)
        try:
            state.rows = []
            state.candidates = []
            state.scan_offset = 0
            state.scan_attempts.clear()
            state.scan_failures.clear()
            response = state.http.get(SEARCH_URL, timeout=45)
            self._check_response(response)
            return self._challenge(token, state, response.text)
        finally:
            state.lock.release()
