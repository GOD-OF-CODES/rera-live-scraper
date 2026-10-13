"""Deterministic structured information parser for real estate document processing (V3.1 enhanced)."""

import re
from typing import Optional

from .models import Boundaries, StructuredData

# Flexible delimiter pattern matching colons, dots, hyphens, equals, and horizontal spaces
DELIM = r"[ \t]*[:\.\-=]*[ \t]*"


def _clean_field(value: Optional[str]) -> Optional[str]:
    """Clean extracted string field by stripping whitespace and noise."""
    if not value:
        return None
    cleaned = value.strip(" \t\r\n:.,;-=")
    return cleaned if cleaned else None


def _extract_regex(pattern: str, text: str, flags: int = re.IGNORECASE) -> Optional[str]:
    """Search text using regex pattern and return first captured group cleaned."""
    match = re.search(pattern, text, flags=flags)
    if match:
        return _clean_field(match.group(1))
    return None


def extract_structured_data(full_text: str) -> StructuredData:
    """Parse raw document text and extract structured metadata deterministically using regex.

    Supports label variations (e.g. Vendor/First Party for Seller, Purchaser/Second Party for Buyer,
    Property Area for Area, Date of Registration/Possession) and OCR punctuation noise.

    Args:
        full_text: Combined raw text extracted from all document pages.

    Returns:
        StructuredData: Extracted structured metadata fields (missing fields default to None).
    """
    if not full_text:
        return StructuredData()

    # Document type
    document_type = _extract_regex(
        r"\b(?:Instrument[ \t]+Type|Document[ \t]+Type|Deed[ \t]+Type|Nature[ \t]+of[ \t]+Document)" + DELIM + r"([^\n\r]+)",
        full_text,
    )
    if not document_type:
        header_match = re.search(
            r"\b(Sale[ \t]+Deed|Deed[ \t]+of[ \t]+Sale|Lease[ \t]+Agreement|Warranty[ \t]+Deed)\b",
            full_text,
            re.IGNORECASE,
        )
        if header_match:
            document_type = header_match.group(1).title()

    # Document number & dates
    document_number = _extract_regex(
        r"\b(?:Document[ \t]+Number|Doc(?:ument)?[ \t]*(?:No|Num|\#)\.?)" + DELIM + r"([A-Za-z0-9\/_\-]+)",
        full_text,
    )
    registration_date = _extract_regex(
        r"\b(?:Registration[ \t]+Date|Reg(?:istration)?[ \t]+Date|Date[ \t]+of[ \t]+Registration)" + DELIM + r"([^\n\r]+)",
        full_text,
    )
    possession_date = _extract_regex(
        r"\b(?:Possession[ \t]+Date|Date[ \t]+of[ \t]+Possession)" + DELIM + r"([^\n\r]+)",
        full_text,
    )

    # Parties
    seller = _extract_regex(
        r"\b(?:Seller[ \t]*(?:/[ \t]*Transferor)?|Transferor|Vendor|First[ \t]+Party|1st[ \t]+Party)" + DELIM + r"([^\n\r]+)",
        full_text,
    )
    buyer = _extract_regex(
        r"\b(?:Buyer[ \t]*(?:/[ \t]*Transferee)?|Transferee|Purchaser|Second[ \t]+Party|2nd[ \t]+Party)" + DELIM + r"([^\n\r]+)",
        full_text,
    )

    # Property details
    property_type = _extract_regex(
        r"\bProperty[ \t]+Type" + DELIM + r"([^\n\r]+)",
        full_text,
    )
    plot_number = _extract_regex(
        r"\b(?:Plot[ \t]+Number|Plot[ \t]+No\.?|Plot)" + DELIM + r"([^\n\r,]+)",
        full_text,
    )
    khasra_number = _extract_regex(
        r"\b(?:Khasra[ \t]+Number|Khasra[ \t]+No\.?|Khasra)" + DELIM + r"([^\n\r,]+)",
        full_text,
    )
    village = _extract_regex(r"\bVillage" + DELIM + r"([^\n\r,]+)", full_text)
    tehsil = _extract_regex(r"\bTehsil" + DELIM + r"([^\n\r,]+)", full_text)
    district = _extract_regex(r"\bDistrict" + DELIM + r"([^\n\r]+)", full_text)
    area = _extract_regex(
        r"\b(?:Total[ \t]+Area|Property[ \t]+Area|Area)" + DELIM + r"([^\n\r]+)",
        full_text,
    )

    # Financial details
    sale_consideration = _extract_regex(
        r"\bSale[ \t]+Consideration" + DELIM + r"([^\n\r]+)", full_text
    )
    if not sale_consideration:
        sale_consideration = _extract_regex(
            r"\bConsideration" + DELIM + r"([^\n\r]+)", full_text
        )

    # Boundaries
    north = _extract_regex(r"\bNorth" + DELIM + r"([^\n\r]+)", full_text)
    south = _extract_regex(r"\bSouth" + DELIM + r"([^\n\r]+)", full_text)
    east = _extract_regex(r"\bEast" + DELIM + r"([^\n\r]+)", full_text)
    west = _extract_regex(r"\bWest" + DELIM + r"([^\n\r]+)", full_text)

    has_boundaries = any(b is not None for b in [north, south, east, west])
    boundaries = (
        Boundaries(north=north, south=south, east=east, west=west)
        if has_boundaries
        else None
    )

    return StructuredData(
        document_type=document_type,
        document_number=document_number,
        registration_date=registration_date,
        seller=seller,
        buyer=buyer,
        property_type=property_type,
        plot_number=plot_number,
        khasra_number=khasra_number,
        village=village,
        tehsil=tehsil,
        district=district,
        area=area,
        sale_consideration=sale_consideration,
        possession_date=possession_date,
        boundaries=boundaries,
    )
