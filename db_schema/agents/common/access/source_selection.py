from .models import AccessRequest

# Mapping from request types to default conceptual source identifiers
REQUEST_TYPE_TO_SOURCE = {
    "land_record": "official_land_record",
    "ownership_record": "official_land_record",
    "registration_record": "sub_registrar_portal",
    "litigation_record": "e_courts_portal",
    "litigation": "e_courts_portal",
    "case_record": "e_courts_portal",
    "rera_record": "official_rera",
    "municipal_record": "municipal_portal",
    "document": "document_repository",
    "other": "general_access_source",
}


def select_source(request: AccessRequest) -> str:
    """
    Select the appropriate target data source based on request type and preferences.

    Args:
        request: The structured AccessRequest.

    Returns:
        Conceptual source string identifier.
    """
    # 1. If explicit recognized source preference is provided, honor it
    if request.source_preference and request.source_preference not in ("official", "any", "default"):
        return request.source_preference

    # 2. Otherwise map from request_type
    req_type = request.request_type.lower() if request.request_type else "other"
    return REQUEST_TYPE_TO_SOURCE.get(req_type, "general_access_source")
