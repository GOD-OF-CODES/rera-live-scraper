"""
Real implementation of process_document(), built on the PDF/OCR
pipeline vendored into agents/document_processing/pdf/ (originally
app/tools/document_processing from the uploaded toolkit - logic
unchanged, only the import paths were made relative).

Pipeline per document:
  1. Download the PDF from document_url to a temp file.
  2. extract_text_from_pdf(): page-by-page text extraction via
     PyMuPDF, falling back to Tesseract OCR per-page when a page has
     too little extractable text (i.e. it's a scan, not a text PDF -
     confirmed this is common for UP-RERA registry documents).
  3. Deterministic regex-based structured field extraction
     (khasra number, seller/buyer, dates, area, boundaries, ...).
  4. Classify document_category from the extracted document_type
     field, falling back to filename keywords.
  5. Map fields into OUR contract (khasra_number, seller_name,
     buyer_name, deed_date, plot_area_sq_m - the names Property
     Identification's get_project_land_details() already reads) while
     keeping every other extracted field too, under its own name.
  6. Save via storage.save_extraction_result().

Requires:
  - System dependency: Tesseract OCR must be installed and on PATH.
      Windows: https://github.com/UB-Mannheim/tesseract/wiki (installer)
      Mac:     brew install tesseract
      Linux:   apt install tesseract-ocr
    Verify with `tesseract --version` in your terminal.
  - Python: pymupdf, pytesseract, pillow, requests (see
    requirements-agents.txt)

Run the whole pending queue with:
    cd db_schema
    python -m agents.document_processing.extractor
"""

import tempfile
from pathlib import Path
from typing import Optional

import requests

from agents.document_processing import storage
from agents.document_processing.pdf.pdf_extractor import extract_text_from_pdf

DOWNLOAD_TIMEOUT_SECONDS = 60

# document_type (as extracted from the PDF text) or filename keyword
# -> our document_category enum. Checked in order, first match wins.
CATEGORY_KEYWORDS = [
    ("registry", "registry_deed"),
    ("sale deed", "registry_deed"),
    ("sale_deed", "registry_deed"),
    ("agreement", "sale_agreement"),
    ("ca certificate", "ca_certificate"),
    ("chartered accountant", "ca_certificate"),
    ("architect", "architect_certificate"),
    ("engineer", "engineer_certificate"),
    ("affidavit", "other"),
]


def _classify_category(document_type: Optional[str], document_name: Optional[str]) -> str:
    haystack = f"{document_type or ''} {document_name or ''}".lower()

    for keyword, category in CATEGORY_KEYWORDS:
        if keyword in haystack:
            return category

    return "other"


def _download_to_temp(url: str) -> Path:
    response = requests.get(url, timeout=DOWNLOAD_TIMEOUT_SECONDS)
    response.raise_for_status()

    suffix = ".pdf" if url.lower().endswith(".pdf") else ""
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp.write(response.content)
    tmp.close()

    return Path(tmp.name)


def _map_to_contract_fields(structured: dict) -> dict:
    """
    structured is StructuredData.to_dict() - map its names to the
    field names Property Identification's tools.py already expects
    (khasra_number, seller_name, buyer_name, deed_date,
    plot_area_sq_m), while keeping every field under its own name too
    so nothing is lost for future subagents (Ownership & Title,
    Registration & Encumbrance) that will want the rest.
    """

    fields = dict(structured)  # keep everything as-is first

    fields["khasra_number"] = structured.get("khasra_number")
    fields["seller_name"] = structured.get("seller")
    fields["buyer_name"] = structured.get("buyer")
    fields["deed_date"] = structured.get("registration_date")
    fields["plot_area_sq_m"] = structured.get("area")

    return fields


def process_document(document: dict) -> None:
    """document is one row from storage.list_pending_documents()."""

    project_document_id = document["project_document_id"]
    project_id = document["project_id"]
    document_url = document["document_url"]
    document_name = document.get("document_name")

    if not document_url or not document_url.lower().endswith(".pdf"):
        storage.save_extraction_result(
            project_document_id=project_document_id,
            project_id=project_id,
            extraction_status="failed",
            extracted_fields={},
            source_document_url=document_url,
        )
        return

    tmp_path: Optional[Path] = None

    try:
        tmp_path = _download_to_temp(document_url)
        extracted = extract_text_from_pdf(tmp_path)

        structured = extracted.structured_data.to_dict() if extracted.structured_data else {}
        any_ocr_failed = any(p.ocr_failed for p in extracted.pages)
        # simple, transparent confidence heuristic - not a calibrated
        # probability, just "did OCR fail on any page + were any
        # structured fields actually found"
        fields_found = sum(1 for v in structured.values() if v not in (None, "", {}))
        confidence = 0.0 if any_ocr_failed else min(1.0, 0.3 + 0.07 * fields_found)

        storage.save_extraction_result(
            project_document_id=project_document_id,
            project_id=project_id,
            extraction_status="unreadable_scan" if any_ocr_failed else "ok",
            document_category=_classify_category(structured.get("document_type"), document_name),
            extracted_fields=_map_to_contract_fields(structured),
            raw_text="\n".join(p.text for p in extracted.pages if p.text),
            confidence=round(confidence, 3),
            source_document_url=document_url,
        )

    except Exception as exc:  # noqa: BLE001 - always record SOMETHING, never crash the queue
        storage.save_extraction_result(
            project_document_id=project_document_id,
            project_id=project_id,
            extraction_status="failed",
            extracted_fields={"error": str(exc)},
            source_document_url=document_url,
        )

    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)


def run_pending_queue(limit: int = 50) -> int:
    pending = storage.list_pending_documents(limit=limit)

    for document in pending:
        process_document(document)

    return len(pending)


if __name__ == "__main__":
    processed = run_pending_queue()
    print(f"Processed {processed} pending document(s).")
