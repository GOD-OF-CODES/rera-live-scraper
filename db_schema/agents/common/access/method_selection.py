from .models import AccessRequest

# Mapping from source identifiers / request types to access methods
SOURCE_TO_METHOD = {
    "official_land_record": "PORTAL",
    "official_rera": "PORTAL",
    "sub_registrar_portal": "PORTAL",
    "e_courts_portal": "PORTAL",
    "municipal_portal": "PORTAL",
    "document_repository": "DOCUMENT",
    "general_access_source": "OTHER",
}


def select_access_method(source: str, request: AccessRequest) -> str:
    """
    Determine the conceptual access method (API, PORTAL, DOCUMENT, OTHER).

    Args:
        source: Selected target source identifier.
        request: The structured AccessRequest.

    Returns:
        Access method string ("API", "PORTAL", "DOCUMENT", "OTHER").
    """
    # 1. Check if metadata specifies access method directly
    if request.metadata and "access_method" in request.metadata:
        return request.metadata["access_method"].upper()

    # 2. Check if request_type is document
    if request.request_type == "document":
        return "DOCUMENT"

    # 3. Lookup source default
    return SOURCE_TO_METHOD.get(source, "PORTAL")
