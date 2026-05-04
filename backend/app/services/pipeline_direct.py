"""
Direct-PDF processing pipeline.

Replaces OCR + rule-based extraction with three Bedrock Claude calls
that receive the raw PDF bytes directly:
  Call 1 – extract certificate fields
  Call 2 – extract test report fields
  Call 3 – compare both documents and validate all attribute pairs + citations

Results are persisted into the same DB models as the standard pipeline so
the detail UI renders identically.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AttributeValidation,
    CitationValidation,
    Document,
    DocumentSet,
    DocumentType,
    Extraction,
    ProcessingStatus,
    RatingDecision,
)
from app.extraction.pdf_direct import run_direct_review
from app.config import get_settings
from app.rating.traffic_light import compute_rating


async def process_document_set_direct(session: AsyncSession, document_set_id: str) -> None:
    """Background task: run direct-PDF review for a submitted document set."""

    # ── load document set ─────────────────────────────────────────────────────
    result = await session.execute(
        select(DocumentSet).where(DocumentSet.id == document_set_id)
    )
    ds = result.scalar_one_or_none()
    if not ds:
        return

    # ── wipe any previous results ─────────────────────────────────────────────
    await session.execute(delete(Extraction).where(Extraction.document_set_id == document_set_id))
    await session.execute(
        delete(AttributeValidation).where(AttributeValidation.document_set_id == document_set_id)
    )
    await session.execute(
        delete(CitationValidation).where(CitationValidation.document_set_id == document_set_id)
    )
    await session.execute(
        delete(RatingDecision).where(RatingDecision.document_set_id == document_set_id)
    )

    ds.status = ProcessingStatus.extracting
    await session.flush()

    # ── locate the two documents ──────────────────────────────────────────────
    docs = (
        await session.execute(
            select(Document).where(Document.document_set_id == document_set_id)
        )
    ).scalars().all()

    cert_doc = next((d for d in docs if d.doc_type == DocumentType.certificate), None)
    test_doc = next((d for d in docs if d.doc_type == DocumentType.test_report), None)

    if not cert_doc or not test_doc:
        ds.status = ProcessingStatus.failed
        ds.failure_message = "Both certificate and test report are required"
        return

    cert_path = Path(cert_doc.storage_path)
    test_path = Path(test_doc.storage_path)

    # ── run direct PDF review ─────────────────────────────────────────────────
    review = run_direct_review(cert_path, test_path, ds.certificate_kind.value)

    confidences: list[float] = []

    # ── persist certificate extractions ──────────────────────────────────────
    for f in review.cert_fields:
        confidences.append(f.confidence)
        session.add(
            Extraction(
                document_set_id=ds.id,
                source_document_id=cert_doc.id,
                attribute_key=f.attribute_key,
                value_json=f.value_json,
                raw_text_snippet=f.raw_text_snippet,
                page_hint=f.page_hint,
                confidence=f.confidence,
                justification=f.justification,
            )
        )

    # ── persist test report extractions ──────────────────────────────────────
    for f in review.test_fields:
        confidences.append(f.confidence)
        session.add(
            Extraction(
                document_set_id=ds.id,
                source_document_id=test_doc.id,
                attribute_key=f.attribute_key,
                value_json=f.value_json,
                raw_text_snippet=f.raw_text_snippet,
                page_hint=f.page_hint,
                confidence=f.confidence,
                justification=f.justification,
            )
        )

    ds.status = ProcessingStatus.validating
    await session.flush()

    # ── persist attribute validations ─────────────────────────────────────────
    attr_passed: list[bool] = []
    for av in review.attribute_validations:
        attr_passed.append(av.passed)
        session.add(
            AttributeValidation(
                document_set_id=ds.id,
                attribute_key=av.attribute_key,
                passed=av.passed,
                reason=av.reason,
                details_json=av.details,
            )
        )

    # ── persist citation validations ──────────────────────────────────────────
    cite_flagged: list[bool] = []
    for cv in review.citation_validations:
        cite_flagged.append(cv.flagged_immediate_review)
        session.add(
            CitationValidation(
                document_set_id=ds.id,
                citation_normalized=cv.citation_normalized,
                on_certificate=cv.on_certificate,
                on_test_report=cv.on_test_report,
                clause_match=cv.clause_match,
                test_pass_fail=cv.test_pass_fail,
                conformant=cv.conformant,
                lab_accreditation_ok=None,   # not checked in direct mode
                cpsc_lookup_ok=None,          # not checked in direct mode
                confidence=cv.confidence,
                justification=cv.justification,
                flagged_immediate_review=cv.flagged_immediate_review,
            )
        )

    # ── compute traffic-light rating ──────────────────────────────────────────
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
