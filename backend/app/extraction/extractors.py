"""
Rule-based field extraction from certificate / test report plain text.

Heuristics match common GCC/CPC phrasing; POC tuning expected per real layouts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.extraction.fields import (
    ATTR_CERT_CITATIONS,
    ATTR_CERT_DATE_MANUFACTURE,
    ATTR_CERT_DATE_TESTING,
    ATTR_CERT_MANUFACTURER,
    ATTR_CERT_PLACE_MANUFACTURE,
    ATTR_CERT_PLACE_TESTING,
    ATTR_CERT_PRODUCT,
    ATTR_CERT_RECORD_KEEPER,
    ATTR_CERT_THIRD_PARTY_LAB,
    ATTR_TEST_CITATIONS,
    ATTR_TEST_DATE_MANUFACTURE,
    ATTR_TEST_DATE_TESTING,
    ATTR_TEST_MANUFACTURER,
    ATTR_TEST_PLACE_MANUFACTURE,
    ATTR_TEST_PLACE_TESTING,
    ATTR_TEST_PRODUCT,
    ATTR_TEST_RECORD_KEEPER,
    ATTR_TEST_THIRD_PARTY_LAB,
)
from app.extraction.ocr import extract_pages_with_ocr_fallback


@dataclass
class ExtractedField:
    attribute_key: str
    value_json: Any
    raw_text_snippet: str | None
    page_hint: int | None
    confidence: float
    justification: str


CITATION_PATTERNS = [
    re.compile(r"\b\d+\s*CFR\s*§?\s*\d+[\w.\-]*\b", re.IGNORECASE),
    re.compile(r"\b\d+\s*CFR\s+\d+[\w.\-]*\b", re.IGNORECASE),
    re.compile(r"\bASTM\s+[A-Z]\d+[\w.\-]*\b", re.IGNORECASE),
    re.compile(r"\b16\s*CFR\s*Part\s*\d+[\w.\-]*\b", re.IGNORECASE),
]


def normalize_citation(s: str) -> str:
    s = re.sub(r"\s+", " ", s.strip())
    s = re.sub(r"§\s*", "§", s, flags=re.IGNORECASE)
    return s


def find_citations(text: str) -> list[str]:
    found: set[str] = set()
    for pat in CITATION_PATTERNS:
        for m in pat.finditer(text):
            found.add(normalize_citation(m.group(0)))
    return sorted(found)


def _block_after_label(text: str, labels: list[str], max_len: int = 500) -> tuple[str | None, str | None]:
    lower = text.lower()
    for lab in labels:
        idx = lower.find(lab.lower())
        if idx >= 0:
            chunk = text[idx : idx + max_len]
            line_end = chunk.find("\n\n")
            if line_end > 0:
                chunk = chunk[: line_end + 2]
            return chunk.strip(), lab
    return None, None


def _confidence_from_match(snippet: str | None, required_terms: int = 1) -> float:
    if not snippet:
        return 0.35
    base = 0.55 + min(0.35, len(snippet) / 800)
    return min(0.98, base)


def extract_certificate_fields(path: Path) -> list[ExtractedField]:
    pages = extract_pages_with_ocr_fallback(path)
    full = "\n\n".join(p.text for p in pages)
    best_page = 0

    fields: list[ExtractedField] = []

    # Product — look for Identification of product / product identification
    prod_snip, _ = _block_after_label(
        full,
        [
            "identification of the product",
            "identification of product",
            "product identification",
            "description of product",
        ],
    )
    product = {
        "product_name": None,
        "product_description": None,
        "identification_numbers": None,
    }
    if prod_snip:
        # naive line splits
        lines = [ln.strip() for ln in prod_snip.splitlines() if ln.strip()][1:6]
        if lines:
            product["product_name"] = lines[0] if lines else None
        if len(lines) > 1:
            product["product_description"] = " ".join(lines[1:4])
        idm = re.search(
            r"(?:model|style|item|sku|catalog)\s*(?:#|number|no\.?)?\s*[:\s]+([^\n]+)",
            prod_snip,
            re.IGNORECASE,
        )
        if idm:
            product["identification_numbers"] = idm.group(1).strip()

    fields.append(
        ExtractedField(
            ATTR_CERT_PRODUCT,
            product,
            prod_snip[:400] if prod_snip else None,
            best_page,
            _confidence_from_match(prod_snip),
            "Heuristic block after product identification heading",
        )
    )

    cites = find_citations(full)
    fields.append(
        ExtractedField(
            ATTR_CERT_CITATIONS,
            cites,
            ", ".join(cites)[:400] if cites else None,
            best_page,
            0.85 if cites else 0.4,
            "Regex extraction of CFR/ASTM style citations",
        )
    )

    mfg_snip, _ = _block_after_label(
        full,
        [
            "manufacturer",
            "importer",
            "manufacturer or importer",
            "party responsible",
        ],
    )
    mfg = {"company_name": None, "address": None, "phone": None}
    if mfg_snip:
        lines = [ln.strip() for ln in mfg_snip.splitlines() if ln.strip()][1:5]
        if lines:
            mfg["company_name"] = lines[0]
        if len(lines) > 1:
            mfg["address"] = " ".join(lines[1:3])
        ph = re.search(r"(?:tel|phone)[.:]?\s*([\d\-\(\)\s+]+)", mfg_snip, re.IGNORECASE)
        if ph:
            mfg["phone"] = ph.group(1).strip()
    fields.append(
        ExtractedField(
            ATTR_CERT_MANUFACTURER,
            mfg,
            mfg_snip[:400] if mfg_snip else None,
            best_page,
            _confidence_from_match(mfg_snip),
            "Block after manufacturer/importer labels",
        )
    )

    rk_snip, _ = _block_after_label(
        full,
        [
            "record keeper",
            "contact for documentation",
            "contact information",
            "person maintaining records",
        ],
    )
    rk = {"name": None, "mailing_address": None, "email": None, "telephone": None}
    if rk_snip:
        em = re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", rk_snip)
        if em:
            rk["email"] = em.group(0)
        tel = re.search(r"(?:tel|phone)[.:]?\s*([\d\-\(\)\s+ext.]+)", rk_snip, re.IGNORECASE)
        if tel:
            rk["telephone"] = tel.group(1).strip()
        lines = [ln.strip() for ln in rk_snip.splitlines() if ln.strip()][1:4]
        if lines:
            rk["name"] = lines[0]
        if len(lines) > 1:
            rk["mailing_address"] = " ".join(lines[1:])
    fields.append(
        ExtractedField(
            ATTR_CERT_RECORD_KEEPER,
            rk,
            rk_snip[:400] if rk_snip else None,
            best_page,
            _confidence_from_match(rk_snip),
            "Record keeper contact heuristics",
        )
    )

    pom_snip, _ = _block_after_label(
        full,
        ["place of manufacture", "country of manufacture", "manufactured in"],
    )
    pom = {"country": None, "city_or_factory": None}
    if pom_snip:
        c = re.search(
            r"(?:country|nation)\s*[:\s]+([A-Za-z\s]+)",
            pom_snip,
            re.IGNORECASE,
        )
        if c:
            pom["country"] = c.group(1).strip()[:80]
        city = re.search(r"(?:city|factory|plant)\s*[:\s]+([^\n]+)", pom_snip, re.IGNORECASE)
        if city:
            pom["city_or_factory"] = city.group(1).strip()[:120]
    fields.append(
        ExtractedField(
            ATTR_CERT_PLACE_MANUFACTURE,
            pom,
            pom_snip[:300] if pom_snip else None,
            best_page,
            _confidence_from_match(pom_snip),
            "Place of manufacture block",
        )
    )

    dom_snip, _ = _block_after_label(
        full,
        ["date of manufacture", "manufacturing date", "production date"],
    )
    dom = {"month_year_or_range": None, "notes": None}
    if dom_snip:
        dm = re.search(
            r"(\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4}\b|\d{1,2}/\d{4}|\d{4}-\d{4})",
            dom_snip,
            re.IGNORECASE,
        )
        if dm:
            dom["month_year_or_range"] = dm.group(1)
    fields.append(
        ExtractedField(
            ATTR_CERT_DATE_MANUFACTURE,
            dom,
            dom_snip[:300] if dom_snip else None,
            best_page,
            0.5 if dom.get("month_year_or_range") else 0.45,
            "Optional manufacture date pattern",
        )
    )

    pot_snip, _ = _block_after_label(
        full,
        ["place of testing", "testing laboratory", "laboratory name"],
    )
    pot = {"laboratory_name": None, "full_address": None}
    if pot_snip:
        lines = [ln.strip() for ln in pot_snip.splitlines() if ln.strip()][1:5]
        if lines:
            pot["laboratory_name"] = lines[0]
        if len(lines) > 1:
            pot["full_address"] = " ".join(lines[1:4])
    fields.append(
        ExtractedField(
            ATTR_CERT_PLACE_TESTING,
            pot,
            pot_snip[:400] if pot_snip else None,
            best_page,
            _confidence_from_match(pot_snip),
            "Place of testing block",
        )
    )

    dot_snip, _ = _block_after_label(
        full,
        ["date of testing", "test date", "testing date"],
    )
    dot = {"date_or_range": None}
    if dot_snip:
        d = re.search(
            r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b|\b\d{4}[/-]\d{1,2}[/-]\d{1,2}\b",
            dot_snip,
        )
        if d:
            dot["date_or_range"] = d.group(0)
    fields.append(
        ExtractedField(
            ATTR_CERT_DATE_TESTING,
            dot,
            dot_snip[:300] if dot_snip else None,
            best_page,
            _confidence_from_match(dot_snip),
            "Date of testing pattern",
        )
    )

    lab_snip, _ = _block_after_label(
        full,
        ["third party", "accredited laboratory", "cpsc accreditation", "lab accreditation"],
    )
    lab = {"laboratory_name": None, "full_address": None, "cpsc_accreditation_number": None}
    if lab_snip:
        lines = [ln.strip() for ln in lab_snip.splitlines() if ln.strip()][1:5]
        if lines:
            lab["laboratory_name"] = lines[0]
        if len(lines) > 1:
            lab["full_address"] = " ".join(lines[1:4])
        acc = re.search(
            r"(?:accreditation|lab\s*(?:#|no\.?))\s*[:\s]*([A-Z0-9\-]+)",
            lab_snip,
            re.IGNORECASE,
        )
        if acc:
            lab["cpsc_accreditation_number"] = acc.group(1).strip()
    fields.append(
        ExtractedField(
            ATTR_CERT_THIRD_PARTY_LAB,
            lab,
            lab_snip[:400] if lab_snip else None,
            best_page,
            _confidence_from_match(lab_snip),
            "Third party lab block",
        )
    )

    return fields


def extract_test_report_fields(path: Path) -> list[ExtractedField]:
    pages = extract_pages_with_ocr_fallback(path)
    full = "\n\n".join(p.text for p in pages)
    best_page = 0
    fields: list[ExtractedField] = []

    prod_snip, _ = _block_after_label(
        full,
        [
            "product description",
            "sample description",
            "test sample",
            "item tested",
            "identification",
        ],
    )
    product = {"product_name": None, "product_description": None, "identification_numbers": None}
    if prod_snip:
        lines = [ln.strip() for ln in prod_snip.splitlines() if ln.strip()][1:6]
        if lines:
            product["product_name"] = lines[0]
        if len(lines) > 1:
            product["product_description"] = " ".join(lines[1:4])
        idm = re.search(
            r"(?:model|style|item|sku)\s*(?:#|number|no\.?)?\s*[:\s]+([^\n]+)",
            prod_snip,
            re.IGNORECASE,
        )
        if idm:
            product["identification_numbers"] = idm.group(1).strip()
    fields.append(
        ExtractedField(
            ATTR_TEST_PRODUCT,
            product,
            prod_snip[:400] if prod_snip else None,
            best_page,
            _confidence_from_match(prod_snip),
            "Test report product block",
        )
    )

    cites = find_citations(full)
    fields.append(
        ExtractedField(
            ATTR_TEST_CITATIONS,
            cites,
            ", ".join(cites)[:400] if cites else None,
            best_page,
            0.85 if cites else 0.4,
            "Regex citations from test report",
        )
    )

    mfg_snip, _ = _block_after_label(
        full,
        ["client", "submitter", "manufacturer", "applicant"],
    )
    mfg = {"company_name": None, "address": None, "phone": None}
    if mfg_snip:
        lines = [ln.strip() for ln in mfg_snip.splitlines() if ln.strip()][1:5]
        if lines:
            mfg["company_name"] = lines[0]
        if len(lines) > 1:
            mfg["address"] = " ".join(lines[1:3])
    fields.append(
        ExtractedField(
            ATTR_TEST_MANUFACTURER,
            mfg,
            mfg_snip[:400] if mfg_snip else None,
            best_page,
            _confidence_from_match(mfg_snip),
            "Test report manufacturer/client block",
        )
    )

    rk_snip, _ = _block_after_label(full, ["record keeper", "contact"])
    rk = {"name": None, "mailing_address": None, "email": None, "telephone": None}
    if rk_snip:
        em = re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", rk_snip)
        if em:
            rk["email"] = em.group(0)
        tel = re.search(r"(?:tel|phone)[.:]?\s*([\d\-\(\)\s+]+)", rk_snip, re.IGNORECASE)
        if tel:
            rk["telephone"] = tel.group(1).strip()
        lines = [ln.strip() for ln in rk_snip.splitlines() if ln.strip()][1:4]
        if lines:
            rk["name"] = lines[0]
        if len(lines) > 1:
            rk["mailing_address"] = " ".join(lines[1:])
    fields.append(
        ExtractedField(
            ATTR_TEST_RECORD_KEEPER,
            rk,
            rk_snip[:400] if rk_snip else None,
            best_page,
            0.5 if any(rk.values()) else 0.35,
            "Optional record keeper on test report",
        )
    )

    pom_snip, _ = _block_after_label(
        full,
        ["place of manufacture", "manufactured", "origin", "country of origin"],
    )
    pom = {"country": None, "city_or_factory": None}
    if pom_snip:
        c = re.search(r"(?:country)\s*[:\s]+([A-Za-z\s]+)", pom_snip, re.IGNORECASE)
        if c:
            pom["country"] = c.group(1).strip()[:80]
        city = re.search(r"(?:city|factory)\s*[:\s]+([^\n]+)", pom_snip, re.IGNORECASE)
        if city:
            pom["city_or_factory"] = city.group(1).strip()[:120]
    fields.append(
        ExtractedField(
            ATTR_TEST_PLACE_MANUFACTURE,
            pom,
            pom_snip[:300] if pom_snip else None,
            best_page,
            _confidence_from_match(pom_snip),
            "Test report place of manufacture",
        )
    )

    dom_snip, _ = _block_after_label(full, ["date of manufacture", "production date"])
    dom = {"month_year_or_range": None, "notes": None}
    if dom_snip:
        dm = re.search(
            r"(\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4}\b|\d{1,2}/\d{4})",
            dom_snip,
            re.IGNORECASE,
        )
        if dm:
            dom["month_year_or_range"] = dm.group(1)
    fields.append(
        ExtractedField(
            ATTR_TEST_DATE_MANUFACTURE,
            dom,
            dom_snip[:300] if dom_snip else None,
            best_page,
            0.5 if dom.get("month_year_or_range") else 0.45,
            "Optional manufacture date on test report",
        )
    )

    pot_snip, _ = _block_after_label(
        full,
        ["testing laboratory", "laboratory", "test location", "place of test"],
    )
    pot = {"laboratory_name": None, "full_address": None}
    if pot_snip:
        lines = [ln.strip() for ln in pot_snip.splitlines() if ln.strip()][1:5]
        if lines:
            pot["laboratory_name"] = lines[0]
        if len(lines) > 1:
            pot["full_address"] = " ".join(lines[1:4])
    fields.append(
        ExtractedField(
            ATTR_TEST_PLACE_TESTING,
            pot,
            pot_snip[:400] if pot_snip else None,
            best_page,
            _confidence_from_match(pot_snip),
            "Test report testing location",
        )
    )

    dot_snip, _ = _block_after_label(full, ["date of test", "test date", "testing date"])
    dot = {"date_or_range": None}
    if dot_snip:
        d = re.search(
            r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b|\b\d{4}[/-]\d{1,2}[/-]\d{1,2}\b",
            dot_snip,
        )
        if d:
            dot["date_or_range"] = d.group(0)
    fields.append(
        ExtractedField(
            ATTR_TEST_DATE_TESTING,
            dot,
            dot_snip[:300] if dot_snip else None,
            best_page,
            _confidence_from_match(dot_snip),
            "Test date on report",
        )
    )

    lab_snip = pot_snip or full[:2000]
    lab = {"laboratory_name": None, "full_address": None, "cpsc_accreditation_number": None}
    if lab_snip:
        lines = [ln.strip() for ln in lab_snip.splitlines() if ln.strip()][:5]
        if lines:
            lab["laboratory_name"] = lines[0]
        if len(lines) > 1:
            lab["full_address"] = " ".join(lines[1:4])
        acc = re.search(
            r"(?:accreditation|cpsc)\s*(?:#|no\.?)?\s*[:\s]*([A-Z0-9\-]+)",
            full,
            re.IGNORECASE,
        )
        if acc:
            lab["cpsc_accreditation_number"] = acc.group(1).strip()
    fields.append(
        ExtractedField(
            ATTR_TEST_THIRD_PARTY_LAB,
            lab,
            lab_snip[:400] if lab_snip else None,
            best_page,
            _confidence_from_match(lab_snip),
            "Third party lab from test report",
        )
    )

    return fields
