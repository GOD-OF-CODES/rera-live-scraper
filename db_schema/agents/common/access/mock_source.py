from typing import Any
from .models import AccessRequest, AccessResponse
from .source_selection import select_source
from .method_selection import select_access_method
from .mechanism import default_access_registry, MockAccessMechanism


def fetch_mock_external_record(
    source_name: str,
    query_params: dict[str, Any],
) -> AccessResponse:
    """
    Backward-compatible mock fetch helper.

    Converts raw query_params into an AccessRequest and executes via MockAccessMechanism.
    """
    req = AccessRequest(
        request_type="land_record" if "khasra_number" in query_params else "rera_record",
        property=query_params,
        source_preference=source_name,
        metadata=query_params,
    )

    source = select_source(req)
    method = select_access_method(source, req)

    mechanism = default_access_registry.get("mock") or MockAccessMechanism()
    return mechanism.execute(req, source, method)
