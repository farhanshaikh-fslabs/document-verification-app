"""Extract plain text from PDFs (native text first)."""

from dataclasses import dataclass
from pathlib import Path

import pdfplumber
from pypdf import PdfReader


@dataclass
class PageText:
    page_index: int  # 0-based
    text: str


def extract_pages_pdfplumber(path: Path) -> list[PageText]:
    pages: list[PageText] = []
    with pdfplumber.open(path) as pdf:
        for i, page in enumerate(pdf.pages):
            t = page.extract_text() or ""
            pages.append(PageText(page_index=i, text=t))
    return pages


def extract_pages_pypdf(path: Path) -> list[PageText]:
    reader = PdfReader(str(path))
    pages: list[PageText] = []
    for i, page in enumerate(reader.pages):
        t = page.extract_text() or ""
        pages.append(PageText(page_index=i, text=t))
    return pages


def extract_pages(path: Path) -> list[PageText]:
    try:
        return extract_pages_pdfplumber(path)
    except Exception:
        return extract_pages_pypdf(path)


def full_text(path: Path) -> str:
    return "\n\n".join(p.text for p in extract_pages(path))
