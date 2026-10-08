"""Shared acceptance checks for new scrapes and existing resume checkpoints."""

from urllib.parse import urlparse
from src.scraper.project_links import normalize_registration


class InvalidProjectDetails(ValueError):
    pass


def validate_property_data(data, expected_registration=None):
    if not isinstance(data, dict):
        raise InvalidProjectDetails("Missing structured project data")
    page_url = (data.get("page") or {}).get("url", "")
    if any(word in urlparse(page_url).path.lower() for word in ("maintenance", "error", "login")):
        raise InvalidProjectDetails(f"RERA returned an error/maintenance page: {page_url}")
    identity = data.get("identification") or {}
    actual = normalize_registration(identity.get("project_id"))
    if not actual or not identity.get("project_name"):
        raise InvalidProjectDetails("Details page has no project name/registration identity")
    if expected_registration and actual != normalize_registration(expected_registration):
        raise InvalidProjectDetails(f"Wrong project returned: expected {expected_registration}, got {actual}")
    basic = data.get("basic_details") or {}
    if not any(basic.get(k) for k in ("total_area_sq_m", "district", "address", "proposed_start_date")):
        raise InvalidProjectDetails("Details page has an identity but no basic project details")


def is_valid_result(result, expected_registration=None):
    if not isinstance(result, dict) or result.get("project_details_available") is not True:
        return False
    if result.get("project_found") is not True or result.get("error"):
        return False
    try:
        validate_property_data(result.get("property_data"), expected_registration or result.get("registration_number"))
    except (ValueError, TypeError, AttributeError):
        return False
    return True
