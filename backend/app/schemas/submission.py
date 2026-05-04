from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.db.models import CertificateKind, ProcessingStatus, TrafficLight


class SubmissionCreateResponse(BaseModel):
    id: str
    status: ProcessingStatus


class ExtractionOut(BaseModel):
    id: str
    attribute_key: str
    value_json: dict | list | str | None
    raw_text_snippet: str | None
    page_hint: int | None
    confidence: float
    justification: str | None
    user_edited: bool

    model_config = {"from_attributes": True}


class AttributeValidationOut(BaseModel):
    attribute_key: str
    passed: bool
    reason: str | None

    model_config = {"from_attributes": True}


class CitationValidationOut(BaseModel):
    citation_normalized: str
    on_certificate: bool
    on_test_report: bool
    test_pass_fail: str | None
    conformant: bool | None
    flagged_immediate_review: bool
    justification: str | None

    model_config = {"from_attributes": True}


class DocumentOut(BaseModel):
    id: str
    doc_type: str
    original_filename: str

    model_config = {"from_attributes": True}

    @field_validator("doc_type", mode="before")
    @classmethod
    def _doc_type_as_str(cls, v: object) -> str:
        return getattr(v, "value", str(v))


class SubmissionDetail(BaseModel):
    id: str
    title: str | None
    certificate_kind: CertificateKind
    status: ProcessingStatus
    traffic_light: TrafficLight | None
    traffic_light_reasons: list | None
    manual_review_required: bool
    failure_message: str | None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    documents: list[DocumentOut]
    extractions: list[ExtractionOut]
    attribute_validations: list[AttributeValidationOut]
    citation_validations: list[CitationValidationOut]


class ExtractionPatch(BaseModel):
    value_json: dict | list | str | None = None


class RatingPatch(BaseModel):
    traffic_light: TrafficLight
    reason: str = Field(..., min_length=1)
