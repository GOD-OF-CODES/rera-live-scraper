"""PDF text extraction module using PyMuPDF (fitz) with OCR fallback and V3 structured information extraction.

Provides functionality for page-by-page text extraction from PDF documents,
automatically falling back to Tesseract OCR when a page contains insufficient
or no extractable text, and deterministically parsing structured metadata.
"""

from pathlib import Path
import pymupdf

from .models import ExtractedDocument, PageText
from .ocr_handler import OCRError, perform_ocr_on_page
from .structured_parser import extract_structured_data

DEFAULT_MIN_TEXT_LENGTH = 10


def is_sufficient_text(text: str, min_text_length: int = DEFAULT_MIN_TEXT_LENGTH) -> bool:
    """Determine whether extracted text is sufficient to be considered usable.

    Evaluates text based on the count of non-whitespace characters.

    Args:
        text: Extracted page text string.
        min_text_length: Minimum number of non-whitespace characters required.

    Returns:
        bool: True if non-whitespace character count >= min_text_length, else False.
    """
    if not text:
        return False
    non_whitespace_count = len("".join(text.split()))
    return non_whitespace_count >= min_text_length


def extract_text_from_pdf(
    file_path: str | Path,
    min_text_length: int = DEFAULT_MIN_TEXT_LENGTH,
    dpi: int = 300,
) -> ExtractedDocument:
    """Extract text from a PDF document page by page, with OCR fallback and V3 structured data extraction.

    Pipeline:
    1. Page-by-page text extraction via PyMuPDF (V1).
    2. If page text is insufficient (< min_text_length non-whitespace chars), fall back to OCR via Tesseract (V2).
    3. Deterministically extract structured fields from full raw document text (V3).

    Args:
        file_path: Path to the target PDF file (str or Path object).
        min_text_length: Threshold of non-whitespace characters to consider PyMuPDF text sufficient.
        dpi: Resolution used for rendering PDF pages during OCR fallback.

    Returns:
        ExtractedDocument: Structured output containing filename, page count,
        page text objects with extraction metadata, and parsed structured_data.

    Raises:
        FileNotFoundError: If the file does not exist at the specified path.
        ValueError: If the file is not a PDF, is corrupt, or cannot be opened.
    """
    path = Path(file_path).resolve()

    # Validate file existence
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"PDF file not found at path: '{file_path}'")

    # Validate file extension
    if path.suffix.lower() != ".pdf":
        raise ValueError(f"File at path '{file_path}' is not a PDF document (expected '.pdf' extension).")

    # Open PDF document with PyMuPDF
    try:
        doc = pymupdf.open(path)
    except Exception as exc:
        raise ValueError(f"Failed to open or parse PDF file '{path.name}': {exc}") from exc

    pages: list[PageText] = []

    try:
        # Iterate page by page (1-indexed page numbering)
        for page_index in range(len(doc)):
            page = doc.load_page(page_index)
            extracted_text = page.get_text()
            clean_text = extracted_text.strip() if extracted_text else ""

            # Check if PyMuPDF text is sufficient
            if is_sufficient_text(clean_text, min_text_length=min_text_length):
                pages.append(
                    PageText(
                        page_number=page_index + 1,
                        text=clean_text,
                        extraction_method="text_extraction",
                        ocr_failed=False,
                    )
                )
            else:
                # Fallback to OCR
                try:
                    ocr_text = perform_ocr_on_page(page, dpi=dpi)
                    pages.append(
                        PageText(
                            page_number=page_index + 1,
                            text=ocr_text,
                            extraction_method="ocr",
                            ocr_failed=False,
                        )
                    )
                except (OCRError, Exception):
                    # Handle OCR failure gracefully
                    pages.append(
                        PageText(
                            page_number=page_index + 1,
                            text=clean_text,
                            extraction_method="ocr",
                            ocr_failed=True,
                        )
                    )

        # Concatenate raw text from all pages for V3 structured extraction
        full_document_text = "\n".join(p.text for p in pages if p.text)
        structured_data = extract_structured_data(full_document_text)

        return ExtractedDocument(
            filename=path.name,
            page_count=len(doc),
            pages=pages,
            structured_data=structured_data,
        )
    finally:
        doc.close()
