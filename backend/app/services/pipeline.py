"""Background processing: extract, validate, rate."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AttributeValidation,
    CertificateKind,
    CitationValidation,
    Document,
    DocumentSet,
    DocumentType,
    Extraction,
    ProcessingStatus,
    RatingDecision,
    TrafficLight,
)
from app.extraction.processor import extract_fields
from app.config import get_settings
from app.rating.traffic_light import compute_rating
from app.validation.engine import run_full_validation


async def process_document_set(session: AsyncSession, document_set_id: str) -> None:
    result = await session.execute(select(DocumentSet).where(DocumentSet.id == document_set_id))
    ds = result.scalar_one_or_none()
    if not ds:
        return

    await session.execute(delete(Extraction).where(Extraction.document_set_id == document_set_id))
    await session.execute(delete(AttributeValidation).where(AttributeValidation.document_set_id == document_set_id))
    await session.execute(delete(CitationValidation).where(CitationValidation.document_set_id == document_set_id))
    await session.execute(delete(RatingDecision).where(RatingDecision.document_set_id == document_set_id))

    ds.status = ProcessingStatus.extracting
    await session.flush()

    docs = (await session.execute(select(Document).where(Document.document_set_id == document_set_id))).scalars().all()
    cert_doc = next((d for d in docs if d.doc_type == DocumentType.certificate), None)
    test_doc = next((d for d in docs if d.doc_type == DocumentType.test_report), None)
    if not cert_doc or not test_doc:
        ds.status = ProcessingStatus.failed
        ds.failure_message = "Both certificate and test report files are required"
        return

    cert_path = Path(cert_doc.storage_path)
    test_path = Path(test_doc.storage_path)

    extractions_map: dict[str, Any] = {}
    confidences: list[float] = []

    for field in extract_fields("certificate", cert_path):
        extractions_map[field.attribute_key] = field.value_json
        confidences.append(field.confidence)
        session.add(
            Extraction(
                document_set_id=ds.id,
                source_document_id=cert_doc.id,
                attribute_key=field.attribute_key,
                value_json=field.value_json,
                raw_text_snippet=field.raw_text_snippet,
                page_hint=field.page_hint,
                confidence=field.confidence,
                justification=field.justification,
            )
        )

    for field in extract_fields("test_report", test_path):
        extractions_map[field.attribute_key] = field.value_json
        confidences.append(field.confidence)
        session.add(
            Extraction(
                document_set_id=ds.id,
                source_document_id=test_doc.id,
                attribute_key=field.attribute_key,
                value_json=field.value_json,
                raw_text_snippet=field.raw_text_snippet,
                page_hint=field.page_hint,
                confidence=field.confidence,
                justification=field.justification,
            )
        )

    ds.status = ProcessingStatus.validating
    await session.flush()

    attr_results, cite_results = run_full_validation(
        extractions_map,
        ds.certificate_kind,
        test_path,
    )

    for ar in attr_results:
        session.add(
            AttributeValidation(
                document_set_id=ds.id,
                attribute_key=ar.attribute_key,
                passed=ar.passed,
                reason=ar.reason,
                details_json=ar.details,
            )
        )

    cite_flagged: list[bool] = []
    for cr in cite_results:
        cite_flagged.append(cr.flagged_immediate_review)
        session.add(
            CitationValidation(
                document_set_id=ds.id,
                citation_normalized=cr.citation_normalized,
                on_certificate=cr.on_certificate,
                on_test_report=cr.on_test_report,
                clause_match=cr.clause_match,
                test_pass_fail=cr.test_pass_fail,
                conformant=cr.conformant,
                lab_accreditation_ok=cr.lab_accreditation_ok,
                cpsc_lookup_ok=cr.cpsc_lookup_ok,
                confidence=cr.confidence,
                justification=cr.justification,
                flagged_immediate_review=cr.flagged_immediate_review,
            )
        )

    attr_passed = [ar.passed for ar in attr_results]
    rating = compute_rating(confidences, attr_passed, cite_flagged)

    ds.traffic_light = rating.traffic_light
    ds.traffic_light_reasons = rating.reasons
    ds.manual_review_required = rating.manual_review_required
    ds.status = ProcessingStatus.completed
    ds.failure_message = None

    session.add(
        RatingDecision(
            document_set_id=ds.id,
            traffic_light=rating.traffic_light,
            threshold_used=get_settings().confidence_threshold,
            reasons=rating.reasons,
        )
    )
