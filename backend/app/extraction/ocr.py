"""OCR utilities for PDF text extraction."""

from pathlib import Path

from app.config import get_settings
from app.extraction.pdf_text import PageText, extract_pages


def _needs_ocr(pages: list[PageText], min_chars: int = 200) -> bool:
    total = sum(len(p.text.strip()) for p in pages)
    return total < min_chars


def extract_pages_with_ocr_fallback(path: Path) -> list[PageText]:
    settings = get_settings()
    pages = extract_pages(path)
    if not settings.ocr_enabled or not _needs_ocr(pages):
        return pages
    try:
        from pdf2image import convert_from_path
        import pytesseract
    except Exception:
        return pages
    try:
        images = convert_from_path(str(path), dpi=150)
    except Exception:
        return pages
    out: list[PageText] = []
    for i, img in enumerate(images):
        try:
            text = pytesseract.image_to_string(img) or ""
        except Exception:
            text = pages[i].text if i < len(pages) else ""
        out.append(PageText(page_index=i, text=text))
    return out


def extract_pages_ocr_first(path: Path) -> list[PageText]:
    """
    OCR-first extraction for all pages.

    If OCR is unavailable/fails, fallback to native text extraction.
    """
    settings = get_settings()
    native_pages = extract_pages(path)
    if not settings.ocr_enabled:
        return native_pages
    try:
        from pdf2image import convert_from_path
        import pytesseract
    except Exception:
        return native_pages
    try:
        images = convert_from_path(str(path), dpi=200)
    except Exception:
        return native_pages

    out: list[PageText] = []
    for i, img in enumerate(images):
        try:
            text = (pytesseract.image_to_string(img) or "").strip()
        except Exception:
            text = ""
        if not text:
            text = native_pages[i].text if i < len(native_pages) else ""
        out.append(PageText(page_index=i, text=text))
    return out
