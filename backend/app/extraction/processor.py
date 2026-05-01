"""Document extraction provider abstraction (Bedrock-first, rule fallback)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.extraction.extractors import (
    ExtractedField,
    extract_certificate_fields,
    extract_test_report_fields,
)
from app.extraction.ocr import extract_pages_ocr_first


def _rule_extract(doc_type: str, path: Path) -> list[ExtractedField]:
    if doc_type == "certificate":
        return extract_certificate_fields(path)
    return extract_test_report_fields(path)


def _bedrock_prompt(doc_type: str, raw_payload: dict[str, Any]) -> str:
    if doc_type == "certificate":
        template_fields: list[dict[str, Any]] = [
            {
                "attribute_key": "certificate.product_identification",
                "value": {
                    "product_name": None,
                    "product_description": None,
                    "identification_numbers": None,
                },
                "confidence": 0.0,
                "justification": "",
                "snippet": "",
                "page_hint": 1,
            },
            {
                "attribute_key": "certificate.citations",
                "value": [],
                "confidence": 0.0,
                "justification": "",
                "snippet": "",
                "page_hint": 1,
            },
            {
                "attribute_key": "certificate.manufacturer_importer",
                "value": {"company_name": None, "address": None, "phone": None},
                "confidence": 0.0,
                "justification": "",
                "snippet": "",
                "page_hint": 1,
            },
            {
                "attribute_key": "certificate.record_keeper_contact",
                "value": {"name": None, "mailing_address": None, "email": None, "telephone": None},
                "confidence": 0.0,
                "justification": "",
                "snippet": "",
                "page_hint": 1,
            },
            {
                "attribute_key": "certificate.place_of_manufacture",
                "value": {"country": None, "city_or_factory": None},
                "confidence": 0.0,
                "justification": "",
                "snippet": "",
                "page_hint": 1,
            },
            {
                "attribute_key": "certificate.date_of_manufacture",
                "value": {"month_year_or_range": None, "notes": None},
                "confidence": 0.0,
                "justification": "",
                "snippet": "",
                "page_hint": 1,
            },
            {
                "attribute_key": "certificate.place_of_testing",
                "value": {"laboratory_name": None, "full_address": None},
                "confidence": 0.0,
                "justification": "",
                "snippet": "",
                "page_hint": 1,
            },
            {
                "attribute_key": "certificate.date_of_testing",
                "value": {"date_or_range": None},
                "confidence": 0.0,
                "justification": "",
                "snippet": "",
                "page_hint": 1,
            },
            {
                "attribute_key": "certificate.third_party_lab",
                "value": {"laboratory_name": None, "full_address": None, "cpsc_accreditation_number": None},
                "confidence": 0.0,
                "justification": "",
                "snippet": "",
                "page_hint": 1,
            },
        ]
    else:
        template_fields = [
            {
                "attribute_key": "test_report.product_identification",
                "value": {
                    "product_name": None,
                    "product_description": None,
                    "identification_numbers": None,
                },
                "confidence": 0.0,
                "justification": "",
                "snippet": "",
                "page_hint": 1,
            },
            {
                "attribute_key": "test_report.citations",
                "value": [],
                "confidence": 0.0,
                "justification": "",
                "snippet": "",
                "page_hint": 1,
            },
            {
                "attribute_key": "test_report.manufacturer_importer",
                "value": {"company_name": None, "address": None, "phone": None},
                "confidence": 0.0,
                "justification": "",
                "snippet": "",
                "page_hint": 1,
            },
            {
                "attribute_key": "test_report.record_keeper_contact",
                "value": {"name": None, "mailing_address": None, "email": None, "telephone": None},
                "confidence": 0.0,
                "justification": "",
                "snippet": "",
                "page_hint": 1,
            },
            {
                "attribute_key": "test_report.place_of_manufacture",
                "value": {"country": None, "city_or_factory": None},
                "confidence": 0.0,
                "justification": "",
                "snippet": "",
                "page_hint": 1,
            },
            {
                "attribute_key": "test_report.date_of_manufacture",
                "value": {"month_year_or_range": None, "notes": None},
                "confidence": 0.0,
                "justification": "",
                "snippet": "",
                "page_hint": 1,
            },
            {
                "attribute_key": "test_report.place_of_testing",
                "value": {"laboratory_name": None, "full_address": None},
                "confidence": 0.0,
                "justification": "",
                "snippet": "",
                "page_hint": 1,
            },
            {
                "attribute_key": "test_report.date_of_testing",
                "value": {"date_or_range": None},
                "confidence": 0.0,
                "justification": "",
                "snippet": "",
                "page_hint": 1,
            },
            {
                "attribute_key": "test_report.third_party_lab",
                "value": {"laboratory_name": None, "full_address": None, "cpsc_accreditation_number": None},
                "confidence": 0.0,
                "justification": "",
                "snippet": "",
                "page_hint": 1,
            },
        ]
    return (
        "You are a compliance extraction agent. Extract structured fields from OCR text.\n"
        "CRITICAL OUTPUT RULES (must follow exactly):\n"
        "1) Return ONLY one JSON object. No prose, no markdown, no code fences.\n"
        "2) Output schema MUST be: {\"fields\":[...]} with EXACTLY 9 field objects.\n"
        "3) Use the EXACT attribute_key values and exact value subkeys from template.\n"
        "4) For value types:\n"
        "   - citations MUST be an array of strings ([] if none)\n"
        "   - all other attributes MUST be objects with exact keys shown in template\n"
        "5) Do not invent extra keys.\n"
        "6) If missing/uncertain: keep null or [] and set confidence <= 0.40.\n"
        "7) If found: confidence between 0.41 and 0.99.\n"
        "8) page_hint must be integer page number from OCR payload.\n"
        "9) Preserve citation text exactly as seen when possible.\n"
        "10) IMPORTANT: Use 'CFR' (not 'CRF') when expanding/normalizing obvious OCR typos.\n"
        "Strict template to fill (do not change keys):\n"
        f"{json.dumps({'fields': template_fields}, ensure_ascii=True)}\n"
        "Raw OCR extraction payload follows as JSON (with pages and text):\n\n"
        f"{json.dumps(raw_payload, ensure_ascii=True)[:120000]}"
    )


def _extract_raw_ocr_payload(path: Path) -> dict[str, Any]:
    pages = extract_pages_ocr_first(path)
    return {
        "pages": [{"page": p.page_index + 1, "text": p.text} for p in pages],
        "full_text": "\n\n".join(p.text for p in pages),
    }


def _parse_bedrock_json(s: str) -> dict[str, Any]:
    s = s.strip()
    if s.startswith("```"):
        s = s.strip("`")
        if s.lower().startswith("json"):
            s = s[4:].strip()
    return json.loads(s)


def _bedrock_extract(doc_type: str, path: Path) -> list[ExtractedField]:
    settings = get_settings()
    try:
        import boto3
    except Exception as e:
        raise RuntimeError(f"boto3 unavailable: {e}") from e

    raw_payload = _extract_raw_ocr_payload(path)
    prompt = _bedrock_prompt(doc_type, raw_payload)

    client = boto3.client("bedrock-runtime", region_name=settings.aws_region)
    response = client.converse(
        modelId=settings.bedrock_model_id,
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"maxTokens": 2500, "temperature": 0},
    )
    content = response["output"]["message"]["content"]
    out_text = "".join(c.get("text", "") for c in content if "text" in c).strip()
    payload = _parse_bedrock_json(out_text)

    fields: list[ExtractedField] = []
    for row in payload.get("fields", []):
        fields.append(
            ExtractedField(
                attribute_key=str(row.get("attribute_key")),
                value_json=row.get("value"),
                raw_text_snippet=row.get("snippet"),
                page_hint=row.get("page_hint"),
                confidence=float(row.get("confidence", 0.0)),
                justification=str(row.get("justification") or "Bedrock mapping from OCR raw payload"),
            )
        )
    if not fields:
        raise RuntimeError("Bedrock returned no fields")
    return fields


def extract_fields(doc_type: str, path: Path) -> list[ExtractedField]:
    settings = get_settings()
    if settings.document_processor.lower() != "bedrock":
        return _rule_extract(doc_type, path)
    return _bedrock_extract(doc_type, path)

