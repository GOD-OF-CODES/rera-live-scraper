"""Data models for document processing tools."""

from dataclasses import asdict, dataclass
from typing import Any, Optional


@dataclass
class Boundaries:
    """Represents property boundary details."""

    north: Optional[str] = None
    south: Optional[str] = None
    east: Optional[str] = None
    west: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        """Convert boundaries structure to dictionary format."""
        return asdict(self)


@dataclass
class StructuredData:
    """Represents extracted structured metadata from real estate documents."""

    document_type: Optional[str] = None
    document_number: Optional[str] = None
    registration_date: Optional[str] = None
    seller: Optional[str] = None
    buyer: Optional[str] = None
    property_type: Optional[str] = None
    plot_number: Optional[str] = None
    khasra_number: Optional[str] = None
    village: Optional[str] = None
    tehsil: Optional[str] = None
    district: Optional[str] = None
    area: Optional[str] = None
    sale_consideration: Optional[str] = None
    possession_date: Optional[str] = None
    boundaries: Optional[Boundaries] = None

    def to_dict(self) -> dict[str, Any]:
        """Convert structured data to dictionary format."""
        res = asdict(self)
        if self.boundaries is not None:
            res["boundaries"] = self.boundaries.to_dict()
        return res


@dataclass
class PageText:
    """Represents text extracted from a single page of a PDF document."""

    page_number: int
    text: str
    extraction_method: str = "text_extraction"
    ocr_failed: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert page text structure to dictionary format."""
        return asdict(self)


@dataclass
class ExtractedDocument:
    """Represents structured text extraction output for an entire PDF document."""

    filename: str
    page_count: int
    pages: list[PageText]
    structured_data: Optional[StructuredData] = None

    def to_dict(self) -> dict[str, Any]:
        """Convert document extraction structure to dictionary format."""
        return {
            "filename": self.filename,
            "page_count": self.page_count,
            "pages": [page.to_dict() for page in self.pages],
            "structured_data": self.structured_data.to_dict() if self.structured_data else None,
        }
