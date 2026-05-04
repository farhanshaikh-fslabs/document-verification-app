"""Server-rendered reviewer UI (Jinja2)."""

import json
import asyncio
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Request, UploadFile, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps_optional import get_current_user_optional
from app.core.security import authenticate_user, create_access_token
from app.db.database import get_db
from app.db.models import (
    CertificateKind,
    Document,
    DocumentSet,
    DocumentType,
    Extraction,
    ProcessingStatus,
    TrafficLight,
    User,
)
from app.api.routes_submissions import _document_set_to_detail, run_pipeline_job
from app.schemas.submission import SubmissionDetail
from app.services.audit import log_audit
from app.services.storage import save_upload

_templates_dir = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_templates_dir))
router = APIRouter(tags=["ui"])

# --- Attribute group definitions (9 attributes per CPSC requirements) ---
_ATTR_GROUPS: list[dict[str, Any]] = [
    {
        "num": 1,
        "name": "Product Identification",
        "description": "Product name, description, and identification/model numbers",
        "required_note": "Must match exactly on both documents and be present",
        "cert_key": "certificate.product_identification",
        "test_key": "test_report.product_identification",
        "val_key_prefix": "pair.product_identification",
        "match_required": True,
    },
    {
        "num": 2,
        "name": "Citation to Applicable Safety Rules",
        "description": "Exact regulations/standards the product is certified to (e.g. 16 CFR 1610)",
        "required_note": "Must be present and match both documents; non-compliant if any citation is missing",
        "cert_key": "certificate.citations",
        "test_key": "test_report.citations",
        "val_key_prefix": "pair.citations",
        "match_required": True,
    },
    {
        "num": 3,
        "name": "Manufacturer or Importer Information",
        "description": "Company name and full address of the party legally responsible for compliance",
        "required_note": "Must be present on both documents (not required to match)",
        "cert_key": "certificate.manufacturer_importer",
        "test_key": "test_report.manufacturer_importer",
        "val_key_prefix": "pair.manufacturer_importer",
        "match_required": False,
    },
    {
        "num": 4,
        "name": "Contact Information for Record Keeper",
        "description": "Name, full mailing address, email, and telephone of the record keeper",
        "required_note": "Required on certificate; if present on test report, all fields must match exactly",
        "cert_key": "certificate.record_keeper_contact",
        "test_key": "test_report.record_keeper_contact",
        "val_key_prefix": "pair.record_keeper",
        "match_required": None,
    },
    {
        "num": 5,
        "name": "Place of Manufacture",
        "description": "Country and city or factory name where product was manufactured",
        "required_note": "Must match both documents and be present",
        "cert_key": "certificate.place_of_manufacture",
        "test_key": "test_report.place_of_manufacture",
        "val_key_prefix": "pair.place_of_manufacture",
        "match_required": True,
    },
    {
        "num": 6,
        "name": "Date of Manufacture",
        "description": "Month/Year or date range of manufacture",
        "required_note": "Optional; if provided in either document it must match",
        "cert_key": "certificate.date_of_manufacture",
        "test_key": "test_report.date_of_manufacture",
        "val_key_prefix": "pair.date_of_manufacture",
        "match_required": None,
    },
    {
        "num": 7,
        "name": "Place of Testing",
        "description": "Laboratory name with full city/state address where testing was performed",
        "required_note": "Must match both documents and be present",
        "cert_key": "certificate.place_of_testing",
        "test_key": "test_report.place_of_testing",
        "val_key_prefix": "pair.place_of_testing",
        "match_required": True,
    },
    {
        "num": 8,
        "name": "Date of Testing",
        "description": "Day/Month/Year the product was tested (date ranges acceptable)",
        "required_note": "Must match both documents and be present",
        "cert_key": "certificate.date_of_testing",
        "test_key": "test_report.date_of_testing",
        "val_key_prefix": "pair.date_of_testing",
        "match_required": True,
    },
    {
        "num": 9,
        "name": "Third-Party Laboratory Information",
        "description": "Laboratory name, full address, and CPSC accreditation number",
        "required_note": "CPC: all fields must be exact match and present; GCC: optional but must match if provided",
        "cert_key": "certificate.third_party_lab",
        "test_key": "test_report.third_party_lab",
        "val_key_prefix": "pair.third_party_lab",
        "match_required": None,
    },
]


def _build_attribute_groups(detail: SubmissionDetail) -> list[dict[str, Any]]:
    ext_map = {e.attribute_key: e for e in detail.extractions}
    val_map = {v.attribute_key: v for v in detail.attribute_validations}

    groups: list[dict[str, Any]] = []
    for ag in _ATTR_GROUPS:
        cert_ext = ext_map.get(ag["cert_key"])
        test_ext = ext_map.get(ag["test_key"])
        val = next(
            (v for k, v in val_map.items() if k.startswith(ag["val_key_prefix"])),
            None,
        )
        groups.append({**ag, "cert": cert_ext, "test": test_ext, "validation": val})
    return groups


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "login.html", {"request": request, "error": None})


@router.post("/login", response_class=HTMLResponse, response_model=None)
async def login_submit(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    email: str = Form(...),
    password: str = Form(...),
) -> RedirectResponse | HTMLResponse:
    user = await authenticate_user(db, email, password)
    if not user:
        return templates.TemplateResponse(
            request,
            "login.html",
            {"request": request, "error": "Invalid credentials"},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    token = create_access_token(user.id)
    await log_audit(
        db,
        user_id=user.id,
        document_set_id=None,
        action="login_success",
        entity_type="user",
        entity_id=user.id,
    )
    resp = RedirectResponse("/review", status_code=status.HTTP_303_SEE_OTHER)
    resp.set_cookie(
        "access_token",
        token,
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24,
        path="/",
    )
    return resp


@router.get("/logout", response_model=None)
async def logout() -> RedirectResponse:
    resp = RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    resp.delete_cookie("access_token", path="/")
    return resp


def _require(user: User | None) -> User | RedirectResponse:
    if not user:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    return user


@router.get("/review", response_class=HTMLResponse, response_model=None)
async def review_list(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User | None, Depends(get_current_user_optional)],
    q: str | None = None,
) -> HTMLResponse | RedirectResponse:
    u = _require(user)
    if isinstance(u, RedirectResponse):
        return u
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
    items = [_document_set_to_detail(ds) for ds in rows]
    await log_audit(
        db,
        user_id=u.id,
        document_set_id=None,
        action="page_view_submissions",
        meta_json={"q": q},
    )
    return templates.TemplateResponse(
        request,
        "list.html",
        {"request": request, "user": u, "items": items, "q": q or ""},
    )


@router.get("/review/new", response_class=HTMLResponse, response_model=None)
async def review_new(
    request: Request,
    user: Annotated[User | None, Depends(get_current_user_optional)],
) -> HTMLResponse | RedirectResponse:
    u = _require(user)
    if isinstance(u, RedirectResponse):
        return u
    return templates.TemplateResponse(request, "upload.html", {"request": request, "user": u})


@router.post("/review/new", response_class=HTMLResponse, response_model=None)
async def review_new_post(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User | None, Depends(get_current_user_optional)],
    certificate: UploadFile = File(...),
    test_report: UploadFile = File(...),
    title: str | None = Form(None),
    certificate_kind: str = Form("cpc"),
) -> RedirectResponse | HTMLResponse:
    u = _require(user)
    if isinstance(u, RedirectResponse):
        return u
    kind = CertificateKind.gcc if certificate_kind.lower() == "gcc" else CertificateKind.cpc
    cert_bytes = await certificate.read()
    test_bytes = await test_report.read()
    cert_path = save_upload(certificate.filename or "certificate.pdf", cert_bytes)
    test_path = save_upload(test_report.filename or "test_report.pdf", test_bytes)

    ds = DocumentSet(title=title, certificate_kind=kind, status=ProcessingStatus.extracting)
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
        user_id=u.id,
        document_set_id=ds.id,
        action="submission_created",
        entity_type="document_set",
        entity_id=ds.id,
        payload_after={"title": title, "certificate_kind": kind.value},
    )
    await db.commit()
    asyncio.create_task(run_pipeline_job(ds.id))
    return RedirectResponse(f"/review/{ds.id}?started=1", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/review/{submission_id}", response_class=HTMLResponse, response_model=None)
async def review_detail(
    request: Request,
    submission_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User | None, Depends(get_current_user_optional)],
    started: int = 0,
) -> HTMLResponse | RedirectResponse:
    u = _require(user)
    if isinstance(u, RedirectResponse):
        return u
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
        return templates.TemplateResponse(request, "404.html", {"request": request, "user": u}, status_code=404)
    detail = _document_set_to_detail(ds)
    attribute_groups = _build_attribute_groups(detail)
    await log_audit(
        db,
        user_id=u.id,
        document_set_id=submission_id,
        action="page_view_submission_detail",
        entity_type="document_set",
        entity_id=submission_id,
    )
    return templates.TemplateResponse(
        request,
        "detail.html",
        {
            "request": request,
            "user": u,
            "detail": detail,
            "started": bool(started),
            "attribute_groups": attribute_groups,
        },
    )


@router.get("/", response_class=HTMLResponse, response_model=None)
async def home() -> RedirectResponse:
    return RedirectResponse("/review")


@router.post("/review/{submission_id}/extractions/{extraction_id}", response_model=None)
async def review_save_extraction(
    submission_id: str,
    extraction_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User | None, Depends(get_current_user_optional)],
    value_json: str = Form(...),
) -> RedirectResponse:
    u = _require(user)
    if isinstance(u, RedirectResponse):
        return u
    r = await db.execute(
        select(Extraction).where(
            Extraction.id == extraction_id,
            Extraction.document_set_id == submission_id,
        )
    )
    ex = r.scalar_one_or_none()
    if not ex:
        return RedirectResponse("/review", status_code=status.HTTP_303_SEE_OTHER)
    before = {"value_json": ex.value_json}
    try:
        parsed: object = json.loads(value_json)
    except json.JSONDecodeError:
        parsed = value_json.strip()
    ex.value_json = parsed  # type: ignore[assignment]
    ex.user_edited = True
    await log_audit(
        db,
        user_id=u.id,
        document_set_id=submission_id,
        action="extraction_edited",
        entity_type="extraction",
        entity_id=extraction_id,
        payload_before=before,
        payload_after={"value_json": parsed},
    )
    await db.commit()
    return RedirectResponse(f"/review/{submission_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/review/{submission_id}/rating", response_model=None)
async def review_save_rating(
    submission_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User | None, Depends(get_current_user_optional)],
    traffic_light: str = Form(...),
    reason: str = Form(...),
) -> RedirectResponse:
    u = _require(user)
    if isinstance(u, RedirectResponse):
        return u
    r = await db.execute(select(DocumentSet).where(DocumentSet.id == submission_id))
    ds = r.scalar_one_or_none()
    if not ds:
        return RedirectResponse("/review", status_code=status.HTTP_303_SEE_OTHER)
    try:
        tl = TrafficLight(traffic_light.lower())
    except ValueError:
        tl = TrafficLight.yellow
    before = {"traffic_light": ds.traffic_light.value if ds.traffic_light else None}
    ds.traffic_light = tl
    ds.traffic_light_reasons = list(ds.traffic_light_reasons or []) + [f"Manual override: {reason}"]
    await log_audit(
        db,
        user_id=u.id,
        document_set_id=submission_id,
        action="rating_manual_override",
        entity_type="document_set",
        entity_id=submission_id,
        payload_before=before,
        payload_after={"traffic_light": tl.value, "reason": reason},
    )
    await db.commit()
    return RedirectResponse(f"/review/{submission_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/review/{submission_id}/reprocess", response_model=None)
async def review_reprocess(
    submission_id: str,
    background_tasks: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User | None, Depends(get_current_user_optional)],
) -> RedirectResponse:
    u = _require(user)
    if isinstance(u, RedirectResponse):
        return u
    r = await db.execute(select(DocumentSet).where(DocumentSet.id == submission_id))
    ds = r.scalar_one_or_none()
    if not ds:
        return RedirectResponse("/review", status_code=status.HTTP_303_SEE_OTHER)
    await log_audit(
        db,
        user_id=u.id,
        document_set_id=submission_id,
        action="reprocess_requested",
        entity_type="document_set",
        entity_id=submission_id,
    )
    await db.commit()
    asyncio.create_task(run_pipeline_job(submission_id))
    return RedirectResponse(f"/review/{submission_id}", status_code=status.HTTP_303_SEE_OTHER)
