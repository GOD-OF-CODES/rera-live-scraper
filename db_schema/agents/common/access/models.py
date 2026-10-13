from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AccessStatus(str, Enum):
    """Standard status codes for external access operations."""

    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    NOT_FOUND = "NOT_FOUND"
    HUMAN_ACTION_REQUIRED = "HUMAN_ACTION_REQUIRED"
    ACCESS_FAILED = "ACCESS_FAILED"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"


@dataclass
class AccessRequest:
    """Represents a data-access request made by a subagent."""

    request_type: str
    property: dict[str, Any] = field(default_factory=dict)
    required_fields: list[str] = field(default_factory=list)
    source_preference: str = "official"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_type": self.request_type,
            "property": self.property,
            "required_fields": self.required_fields,
            "source_preference": self.source_preference,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AccessRequest":
        return cls(
            request_type=data.get("request_type", "other"),
            property=data.get("property", {}),
            required_fields=data.get("required_fields", []),
            source_preference=data.get("source_preference", "official"),
            metadata=data.get("metadata", {}),
        )


@dataclass
class AccessResponse:
    """Standardized response produced by external access mechanisms."""

    status: str
    source: str
    access_method: str
    data: dict[str, Any] = field(default_factory=dict)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    message: str = ""

    # Legacy fields mapping for backward compatibility
    @property
    def source_name(self) -> str:
        return self.source

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "source": self.source,
            "access_method": self.access_method,
            "data": self.data,
            "evidence": self.evidence,
            "limitations": self.limitations,
            "message": self.message,
            "source_name": self.source,
        }
