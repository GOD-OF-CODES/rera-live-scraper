from abc import ABC, abstractmethod
from typing import Any
from .models import AccessRequest, AccessResponse, AccessStatus

# Sample dataset for mock access mechanism
MOCK_DATABASE: dict[str, dict[str, Any]] = {
    "123": {
        "owner_name": "Example Person",
        "land_area": "250 sqm",
        "land_use": "Residential",
        "district": "Gautam Buddha Nagar",
        "tehsil": "Dadri",
        "khasra_number": "123",
        "encumbrance": "None",
    },
    "214/3": {
        "owner_name": "Ramesh Kumar Sharma",
        "land_area": "180 sqm",
        "land_use": "Residential Plot",
        "district": "Gautam Buddha Nagar",
        "tehsil": "Dadri",
        "khasra_number": "214/3",
        "plot_number": "B-117",
    },
    "UP_RERA_2026_001": {
        "registration_number": "UP_RERA_2026_001",
        "project_name": "Sun City Phase 1",
        "promoter_name": "Ramesh Kumar Sharma",
        "approval_status": "Approved",
        "valid_until": "2030-12-31",
    },
}


class BaseAccessMechanism(ABC):
    """Abstract interface for external access mechanisms."""

    @abstractmethod
    def execute(
        self,
        request: AccessRequest,
        source: str,
        access_method: str,
    ) -> AccessResponse:
        """
        Execute data retrieval using the target mechanism.

        Args:
            request: The structured AccessRequest object.
            source: Selected source identifier.
            access_method: Selected access method (API, PORTAL, DOCUMENT, OTHER).

        Returns:
            Standardized AccessResponse.
        """
        pass


class AccessMechanismRegistry:
    """Registry managing pluggable access mechanisms."""

    def __init__(self):
        self._mechanisms: dict[str, BaseAccessMechanism] = {}

    def register(self, name: str, mechanism: BaseAccessMechanism) -> None:
        self._mechanisms[name] = mechanism

    def get(self, name: str) -> BaseAccessMechanism:
        if name in self._mechanisms:
            return self._mechanisms[name]
        # Fallback to default mock mechanism if registered
        return self._mechanisms.get("mock", None)


class MockAccessMechanism(BaseAccessMechanism):
    """Mock implementation of the access mechanism supporting all 6 access states."""

    def execute(
        self,
        request: AccessRequest,
        source: str,
        access_method: str,
    ) -> AccessResponse:
        # 1. Check for HUMAN_ACTION_REQUIRED trigger
        if (
            request.metadata.get("simulate_status") == AccessStatus.HUMAN_ACTION_REQUIRED
            or request.metadata.get("captcha_required") is True
            or request.metadata.get("simulate_human_action") is True
            or request.property.get("khasra_number") == "NEED_CAPTCHA"
            or request.property.get("registration_number") == "NEED_CAPTCHA"
        ):
            return AccessResponse(
                status=AccessStatus.HUMAN_ACTION_REQUIRED,
                source=source,
                access_method=access_method,
                data={},
                evidence=[],
                limitations=["Automated execution paused due to CAPTCHA/OTP requirement."],
                message=f"CAPTCHA / OTP verification required for portal '{source}'. Human interaction required.",
            )

        # 2. Check for SOURCE_UNAVAILABLE trigger
        if (
            request.metadata.get("simulate_status") == AccessStatus.SOURCE_UNAVAILABLE
            or request.property.get("khasra_number") == "UNAVAILABLE"
        ):
            return AccessResponse(
                status=AccessStatus.SOURCE_UNAVAILABLE,
                source=source,
                access_method=access_method,
                data={},
                evidence=[],
                limitations=["Source website or API is currently unreachable or down for maintenance."],
                message=f"Target source '{source}' is currently unavailable.",
            )

        # 3. Check for ACCESS_FAILED trigger
        if (
            request.metadata.get("simulate_status") == AccessStatus.ACCESS_FAILED
            or request.property.get("khasra_number") == "ACCESS_FAIL"
        ):
            return AccessResponse(
                status=AccessStatus.ACCESS_FAILED,
                source=source,
                access_method=access_method,
                data={},
                evidence=[],
                limitations=["Access request encountered systemic query or formatting error."],
                message=f"Access operation failed for source '{source}'.",
            )

        # 4. Check for NOT_FOUND trigger
        if (
            request.metadata.get("simulate_status") == AccessStatus.NOT_FOUND
            or request.property.get("khasra_number") == "NOT_EXIST"
            or request.property.get("registration_number") == "NOT_EXIST"
        ):
            return AccessResponse(
                status=AccessStatus.NOT_FOUND,
                source=source,
                access_method=access_method,
                data={},
                evidence=[],
                limitations=["No public record found matching search parameters."],
                message=f"No matching record found in source '{source}'.",
            )

        # 5. Check for PARTIAL result trigger
        if request.metadata.get("simulate_status") == AccessStatus.PARTIAL:
            data = {"owner_name": "Example Person"}
            missing = [f for f in request.required_fields if f not in data]
            return AccessResponse(
                status=AccessStatus.PARTIAL,
                source=source,
                access_method=access_method,
                data=data,
                evidence=[{"type": "mock_receipt", "source": source}],
                limitations=[f"Requested field '{field}' was not present in retrieved record." for field in missing],
                message=f"Partial record retrieved from '{source}'. Some fields missing.",
            )

        # 6. Lookup in mock database
        key = (
            request.property.get("khasra_number")
            or request.property.get("registration_number")
            or request.property.get("id")
        )

        record_data = MOCK_DATABASE.get(key)
        if record_data:
            data = {k: v for k, v in record_data.items() if not request.required_fields or k in request.required_fields or k in ("owner_name", "land_area", "land_use", "project_name")}
            missing = [f for f in request.required_fields if f not in data]
            status = AccessStatus.PARTIAL if missing else AccessStatus.SUCCESS
            return AccessResponse(
                status=status,
                source=source,
                access_method=access_method,
                data=data,
                evidence=[{"type": "mock_receipt", "source": source, "query_key": key}],
                limitations=[f"Field '{f}' requested but not available." for f in missing],
                message=f"Record successfully retrieved from '{source}'.",
            )

        # Default fallback for valid search requests
        if key or request.property:
            default_data = {
                "owner_name": "Example Person",
                "land_area": "250 sqm",
                "land_use": "Residential",
            }
            if request.required_fields:
                filtered_data = {k: v for k, v in default_data.items() if k in request.required_fields}
                if not filtered_data:
                    filtered_data = default_data
            else:
                filtered_data = default_data

            missing = [f for f in request.required_fields if f not in filtered_data]
            status = AccessStatus.PARTIAL if missing else AccessStatus.SUCCESS

            return AccessResponse(
                status=status,
                source=source,
                access_method=access_method,
                data=filtered_data,
                evidence=[{"type": "mock_receipt", "source": source}],
                limitations=[f"Field '{f}' requested but not available." for f in missing],
                message=f"Data retrieved successfully from '{source}'.",
            )

        # Default NOT_FOUND if empty property params
        return AccessResponse(
            status=AccessStatus.NOT_FOUND,
            source=source,
            access_method=access_method,
            data={},
            evidence=[],
            limitations=["Empty property parameters provided."],
            message=f"No query parameters provided for source '{source}'.",
        )


# Instantiate and populate default global access mechanism registry
default_access_registry = AccessMechanismRegistry()
default_access_registry.register("mock", MockAccessMechanism())

# Lazy register web access mechanism if available
try:
    from .web_access import WebAccessMechanism
    default_access_registry.register("web", WebAccessMechanism())
except Exception:
    pass

