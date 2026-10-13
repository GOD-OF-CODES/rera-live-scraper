"""OCR module for extracting text from scanned PDF pages using PyMuPDF, Pillow, and pytesseract."""

import io
import pymupdf
import pytesseract
from PIL import Image


class OCRError(Exception):
    """Exception raised when OCR extraction fails on a PDF page."""


def perform_ocr_on_page(page: pymupdf.Page, dpi: int = 300) -> str:
    """Render a PyMuPDF page to an image and execute OCR via pytesseract.

    Args:
        page: PyMuPDF Page object to render and analyze.
        dpi: Resolution (dots per inch) for page rendering. Defaults to 300.

    Returns:
        str: Extracted OCR text, stripped of leading/trailing whitespace.

    Raises:
        OCRError: If page rendering, image conversion, or pytesseract execution fails.
    """
    try:
        # Render page to PNG pixmap
        pix = page.get_pixmap(dpi=dpi)
        
        # Load image via Pillow
        image = Image.open(io.BytesIO(pix.tobytes("png")))

        # Perform OCR using pytesseract
        ocr_text = pytesseract.image_to_string(image)
        return ocr_text.strip() if ocr_text else ""
    except Exception as exc:
        raise OCRError(f"OCR extraction failed on page {page.number + 1}: {exc}") from exc
