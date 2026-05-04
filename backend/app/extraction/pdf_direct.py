"""
Direct PDF → AI model review.

Sends raw PDF bytes straight to Amazon Bedrock (Claude) without OCR or
rule-based heuristics.  Two calls are made per submission:
  1. Extraction call   – each document separately, returns 9 structured fields
  2. Comparison call   – both documents together, returns attribute-pair
                         validations and per-citation PASS/FAIL verdicts

All prompts are fully self-contained so Claude can answer from the PDF
content alone; no intermediate OCR text is produced.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.config import get_settings


# ─────────────────────────────────────────────────────────────────────────────
# Data classes
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class DirectExtractedField:
    attribute_key: str
    value_json: Any
    raw_text_snippet: str | None
    page_hint: int | None
    confidence: float
    justification: str


@dataclass
class DirectAttributeValidation:
    attribute_key: str
    passed: bool
    reason: str | None
    details: dict[str, Any] | None = None


@dataclass
class DirectCitationValidation:
    citation_normalized: str
    on_certificate: bool
    on_test_report: bool
    clause_match: bool | None
    test_pass_fail: str | None        # "PASS" | "FAIL" | "MIXED" | None
    conformant: bool | None
    flagged_immediate_review: bool
    justification: str | None
    confidence: float


@dataclass
class DirectReviewResult:
    cert_fields: list[DirectExtractedField]
    test_fields: list[DirectExtractedField]
    attribute_validations: list[DirectAttributeValidation]
    citation_validations: list[DirectCitationValidation]
    raw_model_response: str = ""


# ─────────────────────────────────────────────────────────────────────────────
# Prompt: single-document extraction
# ─────────────────────────────────────────────────────────────────────────────

_EXTRACTION_SCHEMA = {
    "product_identification": {
        "product_name": None,
        "product_description": None,
        "identification_numbers": None,
    },
    "citations": [],
    "manufacturer_importer": {
        "company_name": None,
        "address": None,
        "phone": None,
    },
    "record_keeper_contact": {
        "name": None,
        "mailing_address": None,
        "email": None,
        "telephone": None,
    },
    "place_of_manufacture": {
        "country": None,
        "city_or_factory": None,
    },
    "date_of_manufacture": {
        "month_year_or_range": None,
        "notes": None,
    },
    "place_of_testing": {
        "laboratory_name": None,
        "full_address": None,
    },
    "date_of_testing": {
        "date_or_range": None,
    },
    "third_party_lab": {
        "laboratory_name": None,
        "full_address": None,
        "cpsc_accreditation_number": None,
    },
}

_ATTRIBUTE_DESCRIPTIONS = """
1. product_identification — Identification of the Product
   • product_name: clear, specific product name uniquely identifying the item.
   • product_description: concise description matching the test report.
   • identification_numbers: all model, style, item, SKU, or catalog numbers.

2. citations — Citations to Applicable Safety Rules
   • A JSON ARRAY of strings, each being an exact regulation or standard
     (e.g. "16 CFR 1610", "ASTM F963-17").
   • Capture every citation present; do not paraphrase.

3. manufacturer_importer — Manufacturer or Importer Information
   • company_name: legal name of the party responsible for compliance.
   • address: full address (U.S. address required for importers).
   • phone: telephone number if present (optional).

4. record_keeper_contact — Contact Information for Record Keeper
   • name: person or position responsible for maintaining records.
   • mailing_address: full postal address.
   • email: email address.
   • telephone: phone number.
   (Required on certificates; optional on test reports.)

5. place_of_manufacture — Place of Manufacture
   • country: country where the product was manufactured.
   • city_or_factory: city name or factory/plant name.

6. date_of_manufacture — Date of Manufacture
   • month_year_or_range: Month/Year or a date range (e.g. "Jan 2025", "2024-2025").
   • notes: any additional notes about the manufacturing date if present.
   (Optional field; leave null if not present.)

7. place_of_testing — Place of Testing
   • laboratory_name: full name of the testing laboratory.
   • full_address: complete city/state/country address of the lab.

8. date_of_testing — Date of Testing
   • date_or_range: exact testing date(s) (e.g. "15 Mar 2025", "2025-01-10 to 2025-02-05").

9. third_party_lab — Third-Party Laboratory Information
   • laboratory_name: name of the accredited laboratory that performed testing.
   • full_address: complete address.
   • cpsc_accreditation_number: CPSC lab accreditation / ILAC / A2LA number.
   (Required for CPC; optional but must match if present for GCC.)
"""


def build_extraction_prompt(doc_type: str) -> str:
    """
    Prompt instructing Claude to extract 9 CPSC compliance attributes
    from a single document (certificate or test report).
    """
    doc_label = (
        "GCC/CPC Certificate of Conformity"
        if doc_type == "certificate"
        else "Test Report"
    )
    prefix = "certificate" if doc_type == "certificate" else "test_report"

    schema_with_keys = {
        f"{prefix}.{k}": {
            "value": v,
            "confidence": 0.0,
            "justification": "",
            "page_hint": 1,
            "snippet": "",
        }
        for k, v in _EXTRACTION_SCHEMA.items()
    }

    return f"""You are a CPSC compliance extraction specialist. The attached PDF is a {doc_label}.

Your task is to extract exactly 9 structured compliance attributes from this document and return them as a single valid JSON object — no prose, no markdown, no code fences.

## Attribute Definitions
{_ATTRIBUTE_DESCRIPTIONS}

## Output Rules
1. Return ONLY one JSON object with the key "fields" containing an array of exactly 9 objects.
2. Each object MUST use the exact "attribute_key" shown below.
3. For each field:
   - "value": the extracted data matching the schema below (null / [] if not found).
   - "confidence": float 0.0–1.0 reflecting certainty of extraction.
     · >0.80 = found clearly stated; 0.50–0.79 = inferred/partial; <0.50 = missing/guessed.
   - "justification": one sentence explaining where in the document you found this and why.
   - "page_hint": integer page number (1-based) where the data appears (or 1 if unknown).
   - "snippet": verbatim text (≤300 chars) from the document that supports the extraction.
4. For "citations" the value MUST be a JSON array of strings (empty array [] if none found).
5. Preserve citation text exactly as it appears; expand obvious OCR typos (CRF → CFR).
6. Do NOT invent data. If a field is genuinely absent, set value to null/[] and confidence ≤0.35.

## Strict Output Schema Template
{json.dumps({"fields": list(schema_with_keys.values())}, indent=2, ensure_ascii=True)}

Replace each attribute_key with the exact key from: {list(schema_with_keys.keys())}

Now extract all 9 fields from the attached {doc_label} PDF.
"""


# ─────────────────────────────────────────────────────────────────────────────
# Prompt: combined cross-document comparison + validation
# ─────────────────────────────────────────────────────────────────────────────

_VALIDATION_RULES = """
## Validation Rules (apply to all attributes)

### Attribute 1 – Product Identification
• ALL three sub-fields (product_name, product_description, identification_numbers) must be
  present on BOTH documents and must match exactly.
• Verdict: FAIL if any field is missing from either document OR if any field does not match.

### Attribute 2 – Citations to Applicable Safety Rules
• Every citation on the certificate must appear on the test report and vice versa.
• For each matched citation pair: scan the test report for PASS/FAIL results under that
  citation.  If results are FAIL or MIXED → mark as non-conformant and flag for review.
• Verdict: FAIL if any citation appears on only one document.

### Attribute 3 – Manufacturer / Importer Information
• company_name and address must be present on BOTH documents.
• They do NOT need to match each other.
• Verdict: FAIL only if missing from either document.

### Attribute 4 – Record Keeper Contact
• name, mailing_address, email, telephone must ALL be present on the CERTIFICATE.
• If any of these fields appear on the test report, ALL fields must exactly match the
  certificate.
• Verdict: FAIL if any required field is missing from the certificate, OR if present on
  the test report with a mismatch.

### Attribute 5 – Place of Manufacture
• country and city_or_factory must be present AND match exactly on both documents.
• Verdict: FAIL if missing from either side or if they differ.

### Attribute 6 – Date of Manufacture (optional)
• If provided on EITHER document it must match the other.
• Verdict: PASS if absent from both; FAIL if present on one but not the other, or if they differ.

### Attribute 7 – Place of Testing
• laboratory_name and full_address must be present AND match on both documents.
• Verdict: FAIL if missing from either side or if they differ.

### Attribute 8 – Date of Testing
• date_or_range must be present AND match exactly on both documents.
• Verdict: FAIL if missing from either document or if they differ.

### Attribute 9 – Third-Party Laboratory (CPC strict, GCC optional)
• For CPC: laboratory_name, full_address, and cpsc_accreditation_number must ALL be
  present on both documents and must match exactly.
• For GCC: if any field is provided on either document, all provided fields must match.
• Verdict for CPC: FAIL if any field missing or mismatched.
  Verdict for GCC: PASS if both absent; FAIL if present with mismatch.

## Citation PASS/FAIL Scan
For each citation found on both documents:
• Search the test report for test results under or near that citation.
• Determine whether results are PASS, FAIL, or MIXED (if some pass and some fail).
• If FAIL or MIXED → set conformant=false and flag for immediate review.
• If PASS → set conformant=true.
• If results cannot be determined → set test_pass_fail=null and conformant=null.
"""


def build_comparison_prompt(cert_kind: str) -> str:
    """
    Prompt for the combined comparison call.
    cert_kind: "cpc" or "gcc"
    """
    validation_schema_example = {
        "attribute_validations": [
            {
                "attribute_key": "pair.product_identification",
                "passed": True,
                "reason": None,
                "certificate_value": {"product_name": "..."},
                "test_report_value": {"product_name": "..."},
                "confidence": 0.92,
            }
        ],
        "citation_validations": [
            {
                "citation_normalized": "16 CFR 1610",
                "on_certificate": True,
                "on_test_report": True,
                "clause_match": True,
                "test_pass_fail": "PASS",
                "conformant": True,
                "flagged_immediate_review": False,
                "justification": "Citation present in both; test results show PASS.",
                "confidence": 0.90,
            }
        ],
    }

    attribute_keys = [
        "pair.product_identification",
        "pair.citations_symmetric_presence",
        "pair.manufacturer_importer_presence",
        "pair.record_keeper",
        "pair.place_of_manufacture",
        "pair.date_of_manufacture",
        "pair.place_of_testing",
        "pair.date_of_testing",
        f"pair.third_party_lab_{cert_kind}",
    ]

    return f"""You are a CPSC compliance validation agent. You have been provided with two PDFs:
  • Document 1: GCC/CPC Certificate of Conformity  (certificate)
  • Document 2: Test Report

Certificate kind: {cert_kind.upper()}

Your task is to compare specific compliance attributes across both documents according to
CPSC regulations and return a single valid JSON object — no prose, no markdown, no code fences.

{_VALIDATION_RULES}

## Output Rules
1. Return ONLY one JSON object with keys:
   - "attribute_validations": array of {{attribute_key, passed, reason, certificate_value,
     test_report_value, confidence}} — one entry per attribute (exactly 9 entries).
   - "citation_validations": array of citation-level results (one entry per unique citation
     found across both documents).
2. attribute_key values MUST be: {json.dumps(attribute_keys)}
3. "passed": boolean — true if validation succeeds per rules above, false otherwise.
4. "reason": null if passed, otherwise a concise explanation of WHY it failed.
5. "confidence": float 0.0–1.0 for your confidence in the validation verdict.
6. For citations: include ALL unique citations from either document.
7. "flagged_immediate_review": true if:
   - Citation present on only one document, OR
   - test_pass_fail is "FAIL" or "MIXED", OR
   - conformant is false.

## Output Schema Example
{json.dumps(validation_schema_example, indent=2, ensure_ascii=True)}

Now compare the attached Certificate (Document 1) against the Test Report (Document 2) and
return validation results for all 9 attributes plus all citation-level verdicts.
"""


# ─────────────────────────────────────────────────────────────────────────────
# Bedrock helpers
# ─────────────────────────────────────────────────────────────────────────────

def _bedrock_client():
    try:
        import boto3
    except ImportError as e:
        raise RuntimeError("boto3 is required for direct PDF review") from e
    settings = get_settings()
    return boto3.client("bedrock-runtime", region_name=settings.aws_region)


def _converse_safe_document_name(name: str) -> str:
    """
    Bedrock Converse requires document names to use only alphanumeric characters,
    whitespace, hyphens, parentheses, and square brackets, with no run of
    multiple spaces. Other characters (e.g. . _ /) must be removed or replaced.
    """
    if not name or not str(name).strip():
        return "document"
    parts: list[str] = []
    for ch in name:
        if ch.isalnum():
            parts.append(ch)
        elif ch.isspace():
            parts.append(" ")
        elif ch in "-()[]":
            parts.append(ch)
        else:
            parts.append("-")
    s = "".join(parts)
    s = re.sub(r" +", " ", s)
    s = re.sub(r"-+", "-", s)
    s = s.strip(" -")
    return s or "document"


def _doc_block(name: str, pdf_bytes: bytes) -> dict[str, Any]:
    """Bedrock Converse document content block for a PDF."""
    safe = _converse_safe_document_name(name)
    return {
        "document": {
            "format": "pdf",
            "name": safe,
            "source": {"bytes": pdf_bytes},
        }
    }


def _converse(client: Any, messages: list[dict], max_tokens: int = 8000) -> str:
    settings = get_settings()
    response = client.converse(
        modelId=settings.bedrock_model_id,
        messages=messages,
        inferenceConfig={"maxTokens": max_tokens, "temperature": 0},
    )
    content = response["output"]["message"]["content"]
    return "".join(c.get("text", "") for c in content if "text" in c).strip()


def _parse_json(raw: str) -> dict[str, Any]:
    """Strip markdown fences and parse JSON."""
    text = raw.strip()
    # Remove ```json ... ``` or ``` ... ``` wrappers
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


# ─────────────────────────────────────────────────────────────────────────────
# Extraction: single document
# ─────────────────────────────────────────────────────────────────────────────

def _extract_document_direct(
    client: Any,
    doc_type: str,
    pdf_bytes: bytes,
    filename: str,
) -> list[DirectExtractedField]:
    """Send one PDF to Claude and extract 9 fields."""
    prompt = build_extraction_prompt(doc_type)
    messages = [
        {
            "role": "user",
            "content": [
                _doc_block(filename, pdf_bytes),
                {"text": prompt},
            ],
        }
    ]
    raw = _converse(client, messages, max_tokens=6000)
    payload = _parse_json(raw)

    fields: list[DirectExtractedField] = []
    for row in payload.get("fields", []):
        fields.append(
            DirectExtractedField(
                attribute_key=str(row.get("attribute_key", "")),
                value_json=row.get("value"),
                raw_text_snippet=str(row.get("snippet", ""))[:500] or None,
                page_hint=int(row["page_hint"]) - 1 if row.get("page_hint") else 0,
                confidence=float(row.get("confidence", 0.5)),
                justification=str(row.get("justification", "Direct PDF extraction by AI model")),
            )
        )
    return fields


# ─────────────────────────────────────────────────────────────────────────────
# Validation: both documents in one call
# ─────────────────────────────────────────────────────────────────────────────

def _validate_documents_direct(
    client: Any,
    cert_bytes: bytes,
    cert_filename: str,
    test_bytes: bytes,
    test_filename: str,
    cert_kind: str,
) -> tuple[list[DirectAttributeValidation], list[DirectCitationValidation]]:
    """Send both PDFs to Claude and get cross-document validation results."""
    prompt = build_comparison_prompt(cert_kind)
    messages = [
        {
            "role": "user",
            "content": [
                _doc_block(f"Document-1-Certificate-{cert_filename}", cert_bytes),
                _doc_block(f"Document-2-TestReport-{test_filename}", test_bytes),
                {"text": prompt},
            ],
        }
    ]
    raw = _converse(client, messages, max_tokens=8000)
    payload = _parse_json(raw)

    attr_validations: list[DirectAttributeValidation] = []
    for row in payload.get("attribute_validations", []):
        attr_validations.append(
            DirectAttributeValidation(
                attribute_key=str(row.get("attribute_key", "")),
                passed=bool(row.get("passed", False)),
                reason=row.get("reason"),
                details={
                    "certificate_value": row.get("certificate_value"),
                    "test_report_value": row.get("test_report_value"),
                    "confidence": row.get("confidence"),
                },
            )
        )

    cite_validations: list[DirectCitationValidation] = []
    for row in payload.get("citation_validations", []):
        pf = row.get("test_pass_fail")
        if pf:
            pf = pf.upper()
        cite_validations.append(
            DirectCitationValidation(
                citation_normalized=str(row.get("citation_normalized", "")),
                on_certificate=bool(row.get("on_certificate", False)),
                on_test_report=bool(row.get("on_test_report", False)),
                clause_match=row.get("clause_match"),
                test_pass_fail=pf,
                conformant=row.get("conformant"),
                flagged_immediate_review=bool(row.get("flagged_immediate_review", False)),
                justification=row.get("justification"),
                confidence=float(row.get("confidence", 0.75)),
            )
        )

    return attr_validations, cite_validations


# ─────────────────────────────────────────────────────────────────────────────
# Public entry-point
# ─────────────────────────────────────────────────────────────────────────────

def run_direct_review(
    cert_path: Path,
    test_path: Path,
    cert_kind: str = "cpc",
) -> DirectReviewResult:
    """
    Full direct-PDF review pipeline:
      1. Extract certificate fields
      2. Extract test report fields
      3. Validate both documents against each other

    All three calls send raw PDF bytes to Bedrock Claude — no OCR, no text heuristics.
    """
    client = _bedrock_client()

    cert_bytes = cert_path.read_bytes()
    test_bytes = test_path.read_bytes()

    cert_fields = _extract_document_direct(
        client, "certificate", cert_bytes, cert_path.name
    )
    test_fields = _extract_document_direct(
        client, "test_report", test_bytes, test_path.name
    )
    attr_vals, cite_vals = _validate_documents_direct(
        client,
        cert_bytes, cert_path.name,
        test_bytes, test_path.name,
        cert_kind,
    )

    return DirectReviewResult(
        cert_fields=cert_fields,
        test_fields=test_fields,
        attribute_validations=attr_vals,
        citation_validations=cite_vals,
    )
