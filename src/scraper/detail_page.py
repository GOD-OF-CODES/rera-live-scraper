"""Open a details page and reject redirects, HTTP failures and wrong identities."""

from src.scraper.project_details_extractor import ProjectDetailsExtractor
from src.scraper.project_links import normalize_details_url
from src.scraper.validation import InvalidProjectDetails


def _skip_assets(route):
    # ASP.NET details are server-rendered. No layout or page scripts are needed
    # to read their controls and tables, including collapsed sections.
    if route.request.resource_type in {"image", "font", "media", "stylesheet", "script"}:
        route.abort()
    else:
        route.fallback()


def scrape_detail_page(page, details_url, registration_number):
    url = normalize_details_url(details_url)
    if not url:
        raise InvalidProjectDetails("Missing or invalid authoritative project details URL")
    page.route("**/*", _skip_assets)
    try:
        response = page.goto(url, wait_until="domcontentloaded", timeout=60000)
        if response is not None and response.status >= 400:
            raise InvalidProjectDetails(f"RERA returned HTTP {response.status} for {url}")
        if not normalize_details_url(page.url):
            raise InvalidProjectDetails(f"RERA redirected the details request to {page.url}")
        page.locator('[id$="_lblProjectName"]').wait_for(state="attached", timeout=15000)
        return ProjectDetailsExtractor(page).extract_structured(registration_number)
    finally:
        page.unroute("**/*", _skip_assets)
