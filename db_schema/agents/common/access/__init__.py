"""
Vendored (trimmed) from app/tools/access in the uploaded toolkit.

Deliberately NOT included here: web_access/ (Playwright-based live
browser automation) and sources/ (up_land_record.py, e_courts.py -
642+376 lines of real portal-scraping logic). Those belong to OTHER
subagents (Land Records & Land Use, Litigation) that don't exist yet
in this codebase - pulling them in now would add a Playwright
dependency for a capability Property Identification doesn't need.

What's here is only the MOCK access mechanism: a request/response
contract (AccessRequest/AccessResponse/AccessStatus) plus source and
method selection logic, backed by a small hardcoded sample dataset in
mechanism.py (MOCK_DATABASE). See the external_land_record_lookup
tool in property_identification/tools.py for why this matters and how
it's labeled to the model.
"""

from .mechanism import (
    AccessMechanismRegistry,
    BaseAccessMechanism,
    MockAccessMechanism,
    default_access_registry,
)
from .method_selection import select_access_method
from .mock_source import fetch_mock_external_record
from .models import AccessRequest, AccessResponse, AccessStatus
from .source_selection import select_source

__all__ = [
    "AccessRequest",
    "AccessResponse",
    "AccessStatus",
    "select_source",
    "select_access_method",
    "BaseAccessMechanism",
    "AccessMechanismRegistry",
    "MockAccessMechanism",
    "default_access_registry",
    "fetch_mock_external_record",
]
