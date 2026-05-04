import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser
from app.db.database import AsyncSessionLocal, get_db
from app.db.models import CertificateKind, Document, DocumentSet, DocumentType, ProcessingStatus
from app.schemas.submission import (
    AttributeValidationOut,
    CitationValidationOut,
    DocumentOut,
    ExtractionOut,
    SubmissionCreateResponse,
    SubmissionDetail,
)
from app.services.audit import log_audit
from app.services.pipeline import process_document_set
from app.services.storage import save_upload

router = APIRouter(prefix="/submissions", tags=["submissions"])


async def run_pipeline_job(document_set_id: str) -> None:
    async with AsyncSessionLocal() as session:
        try:
            await process_document_set(session, document_set_id)
            await session.commit()
        except Exception as e:
            await session.rollback()
            async with AsyncSessionLocal() as s2:
                r = await s2.execute(select(DocumentSet).where(DocumentSet.id == document_set_id))
                ds = r.scalar_one_or_none()
                if ds:
                    ds.status = ProcessingStatus.failed
                    ds.failure_message = str(e)[:2000]
                    await s2.commit()


@router.post("", response_model=SubmissionCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_submission(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: CurrentUser,
    certificate: UploadFile = File(...),
    test_report: UploadFile = File(...),
    title: str | None = Form(None),
    certificate_kind: CertificateKind = Form(CertificateKind.cpc),
) -> SubmissionCreateResponse:
    cert_bytes = await certificate.read()
    test_bytes = await test_report.read()
    cert_path = save_upload(certificate.filename or "certificate.pdf", cert_bytes)
    test_path = save_upload(test_report.filename or "test_report.pdf", test_bytes)

    ds = DocumentSet(title=title, certificate_kind=certificate_kind, status=ProcessingStatus.extracting)
    db.add(ds)
    await db.flush()

    db.add(
        Document(
            document_set_id=ds.id,
            doc_type=DocumentType.certificate,
            original_filename=certificate.filename or "certificate.pdf",
            storage_path=str(cert_path),
            mime_type=certificate.content_type,
        )
    )
    db.add(
        Document(
            document_set_id=ds.id,
            doc_type=DocumentType.test_report,
            original_filename=test_report.filename or "test_report.pdf",
            storage_path=str(test_path),
            mime_type=test_report.content_type,
        )
    )
    await log_audit(
        db,
        user_id=user.id,
        document_set_id=ds.id,
        action="submission_created",
        entity_type="document_set",
        entity_id=ds.id,
        payload_after={"title": title, "certificate_kind": certificate_kind.value},
    )
    await db.commit()
    await db.refresh(ds)

    asyncio.create_task(run_pipeline_job(ds.id))
    return SubmissionCreateResponse(id=ds.id, status=ds.status)


@router.get("", response_model=list[SubmissionDetail])
async def list_submissions(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: CurrentUser,
    q: str | None = None,
) -> list[SubmissionDetail]:
    stmt = (
        select(DocumentSet)
        .options(
            selectinload(DocumentSet.documents),
            selectinload(DocumentSet.extractions),
            selectinload(DocumentSet.attribute_validations),
            selectinload(DocumentSet.citation_validations),
        )
        .order_by(DocumentSet.created_at.desc())
    )
    if q:
        stmt = stmt.where(DocumentSet.title.ilike(f"%{q}%"))
    rows = (await db.execute(stmt)).scalars().all()
    return [_document_set_to_detail(ds) for ds in rows]


@router.get("/{submission_id}", response_model=SubmissionDetail)
async def get_submission(
    submission_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: CurrentUser,
) -> SubmissionDetail:
    r = await db.execute(
        select(DocumentSet)
        .options(
            selectinload(DocumentSet.documents),
            selectinload(DocumentSet.extractions),
            selectinload(DocumentSet.attribute_validations),
            selectinload(DocumentSet.citation_validations),
        )
        .where(DocumentSet.id == submission_id)
    )
    ds = r.scalar_one_or_none()
    if not ds:
        raise HTTPException(status_code=404, detail="Not found")
    return _document_set_to_detail(ds)


def _document_set_to_detail(ds: DocumentSet) -> SubmissionDetail:
    return SubmissionDetail(
        id=ds.id,
        title=ds.title,
        certificate_kind=ds.certificate_kind,
        status=ds.status,
        traffic_light=ds.traffic_light,
        traffic_light_reasons=ds.traffic_light_reasons,
        manual_review_required=ds.manual_review_required,
        failure_message=ds.failure_message,
        created_at=ds.created_at,
        updated_at=ds.updated_at,
        documents=[DocumentOut.model_validate(d) for d in ds.documents],
        extractions=[ExtractionOut.model_validate(e) for e in ds.extractions],
        attribute_validations=[AttributeValidationOut.model_validate(v) for v in ds.attribute_validations],
        citation_validations=[CitationValidationOut.model_validate(c) for c in ds.citation_validations],
    )


async def _to_detail(db: AsyncSession, ds: DocumentSet) -> SubmissionDetail:
    r = await db.execute(
        select(DocumentSet)
        .options(
            selectinload(DocumentSet.documents),
            selectinload(DocumentSet.extractions),
            selectinload(DocumentSet.attribute_validations),
            selectinload(DocumentSet.citation_validations),
        )
        .where(DocumentSet.id == ds.id)
    )
    fresh = r.scalar_one()
    return _document_set_to_detail(fresh)
