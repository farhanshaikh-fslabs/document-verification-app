from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser
from app.db.database import get_db
from app.db.models import DocumentSet, Extraction
from app.schemas.submission import ExtractionPatch, RatingPatch, SubmissionDetail
from app.services.audit import log_audit
from app.api.routes_submissions import _to_detail, run_pipeline_job

router = APIRouter(prefix="/submissions", tags=["review"])


async def _get_ds(db: AsyncSession, submission_id: str) -> DocumentSet | None:
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
    return r.scalar_one_or_none()


@router.patch("/{submission_id}/extractions/{extraction_id}", response_model=SubmissionDetail)
async def patch_extraction(
    submission_id: str,
    extraction_id: str,
    body: ExtractionPatch,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: CurrentUser,
) -> SubmissionDetail:
    ds = await _get_ds(db, submission_id)
    if not ds:
        raise HTTPException(status_code=404, detail="Submission not found")
    r = await db.execute(
        select(Extraction).where(Extraction.id == extraction_id, Extraction.document_set_id == submission_id)
    )
    ex = r.scalar_one_or_none()
    if not ex:
        raise HTTPException(status_code=404, detail="Extraction not found")
    before: dict[str, Any] = {"value_json": ex.value_json}
    if body.value_json is not None:
        ex.value_json = body.value_json
    ex.user_edited = True
    await log_audit(
        db,
        user_id=user.id,
        document_set_id=submission_id,
        action="extraction_edited",
        entity_type="extraction",
        entity_id=extraction_id,
        payload_before=before,
        payload_after={"value_json": ex.value_json},
    )
    await db.commit()
    ds2 = await _get_ds(db, submission_id)
    assert ds2
    return await _to_detail(db, ds2)


@router.patch("/{submission_id}/rating", response_model=SubmissionDetail)
async def patch_rating(
    submission_id: str,
    body: RatingPatch,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: CurrentUser,
) -> SubmissionDetail:
    ds = await _get_ds(db, submission_id)
    if not ds:
        raise HTTPException(status_code=404, detail="Submission not found")
    before = {"traffic_light": ds.traffic_light.value if ds.traffic_light else None}
    ds.traffic_light = body.traffic_light
    ds.traffic_light_reasons = (ds.traffic_light_reasons or []) + [f"Manual override: {body.reason}"]
    await log_audit(
        db,
        user_id=user.id,
        document_set_id=submission_id,
        action="rating_manual_override",
        entity_type="document_set",
        entity_id=submission_id,
        payload_before=before,
        payload_after={"traffic_light": body.traffic_light.value, "reason": body.reason},
    )
    await db.commit()
    ds2 = await _get_ds(db, submission_id)
    assert ds2
    return await _to_detail(db, ds2)


@router.post("/{submission_id}/reprocess", response_model=SubmissionDetail)
async def reprocess_submission(
    submission_id: str,
    background_tasks: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: CurrentUser,
) -> SubmissionDetail:
    ds = await _get_ds(db, submission_id)
    if not ds:
        raise HTTPException(status_code=404, detail="Submission not found")
    await log_audit(
        db,
        user_id=user.id,
        document_set_id=submission_id,
        action="reprocess_requested",
        entity_type="document_set",
        entity_id=submission_id,
    )
    await db.commit()
    background_tasks.add_task(run_pipeline_job, submission_id)
    return await _to_detail(db, ds)
