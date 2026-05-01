"""
Validation rules: GCC/CPC certificate vs test report per POC requirements.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.db.models import CertificateKind
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
from app.extraction.extractors import extract_pages_with_ocr_fallback, normalize_citation
from app.validation.lab_lookup import cpsc_has_requirement, find_lab, lab_supports_citation


def _norm(s: Any) -> str:
    if s is None:
        return ""
    t = str(s).strip().lower()
    t = re.sub(r"\s+", " ", t)
    return t


def _normalize_citation_for_compare(s: str) -> str:
    t = normalize_citation(s)
    # Common OCR/model typo: CRF vs CFR.
    t = re.sub(r"\bcrf\b", "cfr", t, flags=re.IGNORECASE)
    return _norm(t)


def _get(attrs: dict[str, Any], key: str) -> Any:
    return attrs.get(key)


def _product_dict(v: Any) -> dict[str, Any]:
    if isinstance(v, dict):
        return {
            "product_name": v.get("product_name") or v.get("name") or v.get("product"),
            "product_description": v.get("product_description") or v.get("description"),
            "identification_numbers": v.get("identification_numbers")
            or v.get("model")
            or v.get("item")
            or v.get("sku"),
        }
    if isinstance(v, str):
        return {"product_name": v, "product_description": None, "identification_numbers": None}
    return {"product_name": None, "product_description": None, "identification_numbers": None}


def _dict(v: Any) -> dict[str, Any]:
    return v if isinstance(v, dict) else {}


def _list_str(v: Any) -> list[str]:
    if isinstance(v, list):
        return [str(x) for x in v]
    if isinstance(v, dict):
        if isinstance(v.get("citations"), list):
            return [str(x) for x in v.get("citations", [])]
        for k in ("regulation", "citation", "value"):
            if v.get(k):
                return [str(v[k]).strip()]
        return []
    if isinstance(v, str) and v.strip():
        return [v.strip()]
    return []


def _manufacturer_dict(v: Any) -> dict[str, Any]:
    if isinstance(v, dict):
        return {
            "company_name": v.get("company_name") or v.get("name") or v.get("organization"),
            "address": v.get("address") or v.get("full_address") or v.get("mailing_address"),
            "phone": v.get("phone") or v.get("telephone") or v.get("tel"),
        }
    if isinstance(v, str):
        return {"company_name": v, "address": v, "phone": None}
    return {"company_name": None, "address": None, "phone": None}


def _record_keeper_dict(v: Any) -> dict[str, Any]:
    if isinstance(v, dict):
        return {
            "name": v.get("name") or v.get("contact_person"),
            "mailing_address": v.get("mailing_address") or v.get("address") or v.get("full_address"),
            "email": v.get("email"),
            "telephone": v.get("telephone") or v.get("phone") or v.get("tel"),
        }
    if isinstance(v, str):
        return {"name": v, "mailing_address": v, "email": None, "telephone": None}
    return {"name": None, "mailing_address": None, "email": None, "telephone": None}


def _place_manufacture_dict(v: Any) -> dict[str, Any]:
    if isinstance(v, dict):
        location = v.get("location")
        country = v.get("country")
        city = v.get("city_or_factory")
        if location and (not country or not city) and "," in str(location):
            parts = [p.strip() for p in str(location).split(",") if p.strip()]
            if parts:
                city = city or parts[0]
                country = country or parts[-1]
        return {"country": country, "city_or_factory": city}
    if isinstance(v, str) and "," in v:
        parts = [p.strip() for p in v.split(",") if p.strip()]
        return {"country": (parts[-1] if parts else None), "city_or_factory": (parts[0] if parts else None)}
    return {"country": None, "city_or_factory": None}


def _date_manufacture_dict(v: Any) -> dict[str, Any]:
    if isinstance(v, dict):
        return {"month_year_or_range": v.get("month_year_or_range") or v.get("date"), "notes": v.get("notes")}
    if isinstance(v, str):
        return {"month_year_or_range": v, "notes": None}
    return {"month_year_or_range": None, "notes": None}


def _place_testing_dict(v: Any) -> dict[str, Any]:
    if isinstance(v, dict):
        return {
            "laboratory_name": v.get("laboratory_name") or v.get("name"),
            "full_address": v.get("full_address") or v.get("address") or v.get("location"),
        }
    if isinstance(v, str):
        return {"laboratory_name": v, "full_address": v}
    return {"laboratory_name": None, "full_address": None}


def _date_testing_dict(v: Any) -> dict[str, Any]:
    if isinstance(v, dict):
        return {"date_or_range": v.get("date_or_range") or v.get("date")}
    if isinstance(v, str):
        return {"date_or_range": v}
    return {"date_or_range": None}


def _third_party_lab_dict(v: Any) -> dict[str, Any]:
    if isinstance(v, dict):
        return {
            "laboratory_name": v.get("laboratory_name") or v.get("name"),
            "full_address": v.get("full_address") or v.get("address") or v.get("location"),
            "cpsc_accreditation_number": v.get("cpsc_accreditation_number")
            or v.get("accreditation_number")
            or v.get("lab_accreditation_number"),
        }
    if isinstance(v, str):
        return {"laboratory_name": v, "full_address": v, "cpsc_accreditation_number": None}
    return {"laboratory_name": None, "full_address": None, "cpsc_accreditation_number": None}


@dataclass
class AttributeValidationResult:
    attribute_key: str
    passed: bool
    reason: str | None
    details: dict[str, Any] | None = None


@dataclass
class CitationValidationResult:
    citation_normalized: str
    on_certificate: bool
    on_test_report: bool
    clause_match: bool | None
    test_pass_fail: str | None
    conformant: bool | None
    lab_accreditation_ok: bool | None
    cpsc_lookup_ok: bool | None
    confidence: float
    justification: str | None
    flagged_immediate_review: bool


def validate_product_identification(cert: dict, test: dict) -> AttributeValidationResult:
    c = _product_dict(cert)
    t = _product_dict(test)
    keys = ["product_name", "product_description", "identification_numbers"]
    failed = []
    for k in keys:
        if _norm(c.get(k)) != _norm(t.get(k)):
            failed.append(k)
    ok = len(failed) == 0 and all(_norm(c.get(k)) for k in keys) and all(_norm(t.get(k)) for k in keys)
    return AttributeValidationResult(
        "pair.product_identification",
        ok,
        None if ok else f"Product fields must match exactly and be present: mismatch or missing in {failed}",
        {"certificate": c, "test_report": t, "mismatched_keys": failed},
    )


def validate_citation_presence(cert_cites: list[str], test_cites: list[str]) -> list[AttributeValidationResult]:
    """Symmetric presence: any citation only on one side => non-compliant for that pair logic."""
    results: list[AttributeValidationResult] = []
    cn = {_normalize_citation_for_compare(x) for x in cert_cites}
    tn = {_normalize_citation_for_compare(x) for x in test_cites}
    only_cert = cn - tn
    only_test = tn - cn
    ok = len(only_cert) == 0 and len(only_test) == 0 and len(cn) > 0
    reason = None
    if only_cert:
        reason = f"Citations on certificate missing from test report: {sorted(only_cert)}"
    elif only_test:
        reason = f"Citations on test report missing from certificate: {sorted(only_test)}"
    elif not cn:
        reason = "No citations extracted from certificate"
    results.append(
        AttributeValidationResult(
            "pair.citations_symmetric_presence",
            ok,
            reason,
            {"certificate_citations": sorted(cn), "test_report_citations": sorted(tn)},
        )
    )
    return results


def validate_manufacturer_presence(cert: dict, test: dict) -> AttributeValidationResult:
    c, t = _manufacturer_dict(cert), _manufacturer_dict(test)
    c_ok = bool(_norm(c.get("company_name")) and _norm(c.get("address")))
    t_ok = bool(_norm(t.get("company_name")) and _norm(t.get("address")))
    ok = c_ok and t_ok
    return AttributeValidationResult(
        "pair.manufacturer_importer_presence",
        ok,
        None if ok else "Manufacturer/importer company name and full address required on both documents",
        {"certificate": c, "test_report": t},
    )


def validate_record_keeper(cert: dict, test: dict) -> AttributeValidationResult:
    c, t = _record_keeper_dict(cert), _record_keeper_dict(test)
    req = ["name", "mailing_address", "email", "telephone"]
    cert_ok = all(_norm(c.get(k)) for k in req)
    test_present = any(_norm(t.get(k)) for k in req)
    if not cert_ok:
        return AttributeValidationResult(
            "pair.record_keeper",
            False,
            "Record keeper name, mailing address, email, and telephone required on certificate",
            {"certificate": c, "test_report": t},
        )
    if not test_present:
        return AttributeValidationResult(
            "pair.record_keeper",
            True,
            None,
            {"note": "Not required on test report; absent OK"},
        )
    mism = [k for k in req if _norm(c.get(k)) != _norm(t.get(k))]
    ok = len(mism) == 0
    return AttributeValidationResult(
        "pair.record_keeper",
        ok,
        None if ok else f"Test report record keeper fields must exactly match certificate: {mism}",
        {"certificate": c, "test_report": t},
    )


def validate_place_manufacture(cert: dict, test: dict) -> AttributeValidationResult:
    c, t = _place_manufacture_dict(cert), _place_manufacture_dict(test)
    keys = ["country", "city_or_factory"]
    ok = all(_norm(c.get(k)) == _norm(t.get(k)) for k in keys) and all(_norm(c.get(k)) for k in keys) and all(
        _norm(t.get(k)) for k in keys
    )
    return AttributeValidationResult(
        "pair.place_of_manufacture",
        ok,
        None if ok else "Country and city/factory must match and be present on both",
        {"certificate": c, "test_report": t},
    )


def validate_date_manufacture(cert: dict, test: dict) -> AttributeValidationResult:
    c, t = _date_manufacture_dict(cert), _date_manufacture_dict(test)
    cv, tv = _norm(c.get("month_year_or_range")), _norm(t.get("month_year_or_range"))
    if not cv and not tv:
        return AttributeValidationResult(
            "pair.date_of_manufacture",
            True,
            None,
            {"note": "Optional; neither provided"},
        )
    if bool(cv) != bool(tv) or cv != tv:
        return AttributeValidationResult(
            "pair.date_of_manufacture",
            False,
            "If manufacture date provided on either document it must match both",
            {"certificate": c, "test_report": t},
        )
    return AttributeValidationResult("pair.date_of_manufacture", True, None, {})


def validate_place_testing(cert: dict, test: dict) -> AttributeValidationResult:
    c, t = _place_testing_dict(cert), _place_testing_dict(test)
    keys = ["laboratory_name", "full_address"]
    ok = all(_norm(c.get(k)) == _norm(t.get(k)) for k in keys) and all(_norm(c.get(k)) for k in keys) and all(
        _norm(t.get(k)) for k in keys
    )
    return AttributeValidationResult(
        "pair.place_of_testing",
        ok,
        None if ok else "Place of testing (lab name + full address) must match and be present",
        {"certificate": c, "test_report": t},
    )


def validate_date_testing(cert: dict, test: dict) -> AttributeValidationResult:
    c, t = _date_testing_dict(cert), _date_testing_dict(test)
    cv, tv = _norm(c.get("date_or_range")), _norm(t.get("date_or_range"))
    ok = bool(cv and tv and cv == tv)
    return AttributeValidationResult(
        "pair.date_of_testing",
        ok,
        None if ok else "Date of testing must match and be present on both",
        {"certificate": c, "test_report": t},
    )


def validate_third_party_lab(cert: dict, test: dict, kind: CertificateKind) -> AttributeValidationResult:
    c, t = _third_party_lab_dict(cert), _third_party_lab_dict(test)
    keys = ["laboratory_name", "full_address", "cpsc_accreditation_number"]
    if kind == CertificateKind.cpc:
        ok = all(_norm(c.get(k)) == _norm(t.get(k)) for k in keys) and all(_norm(c.get(k)) for k in keys) and all(
            _norm(t.get(k)) for k in keys
        )
        return AttributeValidationResult(
            "pair.third_party_lab_cpc",
            ok,
            None
            if ok
            else "CPC: third party lab name, address, and CPSC accreditation must be present and exact match",
            {"certificate": c, "test_report": t},
        )
    # GCC: optional; if any field present on either, all provided fields must match pairwise when both sides have value
    mism = []
    for k in keys:
        cv, tv = _norm(c.get(k)), _norm(t.get(k))
        if cv and tv and cv != tv:
            mism.append(k)
        if (cv and not tv) or (tv and not cv):
            if cv and tv:
                continue
            if cv or tv:
                mism.append(f"{k}_partial")
    ok = len(mism) == 0
    return AttributeValidationResult(
        "pair.third_party_lab_gcc",
        ok,
        None if ok else f"GCC: if lab info provided it must match: issues {mism}",
        {"certificate": c, "test_report": t},
    )


def scan_test_report_pass_fail(test_report_path: Path, citation: str) -> tuple[str | None, bool | None]:
    """
    Heuristic: find citation in test report text, scan nearby lines for PASS/FAIL.
    Returns (pass_fail_upper, conformant guess).
    """
    pages = extract_pages_with_ocr_fallback(test_report_path)
    full_lines: list[str] = []
    for p in pages:
        for line in p.text.splitlines():
            full_lines.append(line)
    text_block = "\n".join(full_lines)
    cit = citation.strip()
    idx = text_block.lower().find(cit.lower())
    if idx < 0:
        return None, None
    window = text_block[idx : idx + 2500]
    fail_hits = len(re.findall(r"\bFAIL\b|\bFAILED\b|\bNON[\s-]?CONFORM", window, re.IGNORECASE))
    pass_hits = len(re.findall(r"\bPASS\b|\bPASSED\b|\bCONFORM", window, re.IGNORECASE))
    if fail_hits and not pass_hits:
        return "FAIL", False
    if pass_hits and not fail_hits:
        return "PASS", True
    if fail_hits and pass_hits:
        return "MIXED", False
    return None, None


def build_citation_validations(
    cert_cites: list[str],
    test_cites: list[str],
    test_report_path: Path,
    lab_cert: dict,
    lab_test: dict,
) -> list[CitationValidationResult]:
    cn = {normalize_citation(x) for x in cert_cites}
    tn = {normalize_citation(x) for x in test_cites}
    union = sorted(cn | tn)
    lab = find_lab(lab_test.get("laboratory_name"), lab_test.get("cpsc_accreditation_number"))
    out: list[CitationValidationResult] = []
    for u in union:
        on_c = u in cn
        on_t = u in tn
        clause_match = on_c and on_t
        pf, conf = (None, None)
        flagged = False
        justification_parts = []
        if on_c and on_t:
            pf, conf = scan_test_report_pass_fail(test_report_path, u)
            if pf == "FAIL" or conf is False:
                flagged = True
            if pf == "MIXED":
                flagged = True
            justification_parts.append(f"Test clause window scan: pass_fail={pf}, conformant_guess={conf}")
        elif on_c != on_t:
            flagged = True
            justification_parts.append("Citation missing on one document — non-compliant")
        cpsc_ok = cpsc_has_requirement(u)
        lab_ok = lab_supports_citation(lab, u) if lab else False
        if on_c and on_t:
            if not cpsc_ok:
                flagged = True
            if not lab_ok:
                flagged = True
        justification_parts.append(f"CPSC index match: {cpsc_ok}; lab can perform test: {lab_ok}")
        confidence = 0.75 if on_c and on_t else 0.55
        out.append(
            CitationValidationResult(
                citation_normalized=u,
                on_certificate=on_c,
                on_test_report=on_t,
                clause_match=clause_match if (on_c or on_t) else None,
                test_pass_fail=pf,
                conformant=conf,
                lab_accreditation_ok=lab_ok,
                cpsc_lookup_ok=cpsc_ok,
                confidence=confidence,
                justification="; ".join(justification_parts),
                flagged_immediate_review=flagged,
            )
        )
    return out


def run_full_validation(
    extractions: dict[str, Any],
    certificate_kind: CertificateKind,
    test_report_path: Path,
) -> tuple[list[AttributeValidationResult], list[CitationValidationResult]]:
    cert_p = _product_dict(_get(extractions, ATTR_CERT_PRODUCT))
    test_p = _product_dict(_get(extractions, ATTR_TEST_PRODUCT))
    attr_results: list[AttributeValidationResult] = []
    attr_results.append(validate_product_identification(cert_p, test_p))
    cc = _list_str(_get(extractions, ATTR_CERT_CITATIONS))
    tc = _list_str(_get(extractions, ATTR_TEST_CITATIONS))
    attr_results.extend(validate_citation_presence(cc, tc))
    attr_results.append(
        validate_manufacturer_presence(
            _get(extractions, ATTR_CERT_MANUFACTURER), _get(extractions, ATTR_TEST_MANUFACTURER)
        )
    )
    attr_results.append(
        validate_record_keeper(
            _get(extractions, ATTR_CERT_RECORD_KEEPER), _get(extractions, ATTR_TEST_RECORD_KEEPER)
        )
    )
    attr_results.append(
        validate_place_manufacture(
            _get(extractions, ATTR_CERT_PLACE_MANUFACTURE), _get(extractions, ATTR_TEST_PLACE_MANUFACTURE)
        )
    )
    attr_results.append(
        validate_date_manufacture(
            _get(extractions, ATTR_CERT_DATE_MANUFACTURE), _get(extractions, ATTR_TEST_DATE_MANUFACTURE)
        )
    )
    attr_results.append(
        validate_place_testing(
            _get(extractions, ATTR_CERT_PLACE_TESTING), _get(extractions, ATTR_TEST_PLACE_TESTING)
        )
    )
    attr_results.append(
        validate_date_testing(_get(extractions, ATTR_CERT_DATE_TESTING), _get(extractions, ATTR_TEST_DATE_TESTING))
    )
    attr_results.append(
        validate_third_party_lab(
            _get(extractions, ATTR_CERT_THIRD_PARTY_LAB),
            _get(extractions, ATTR_TEST_THIRD_PARTY_LAB),
            certificate_kind,
        )
    )

    cite_results = build_citation_validations(
        cc,
        tc,
        test_report_path,
        _third_party_lab_dict(_get(extractions, ATTR_CERT_THIRD_PARTY_LAB)),
        _third_party_lab_dict(_get(extractions, ATTR_TEST_THIRD_PARTY_LAB)),
    )
    return attr_results, cite_results
