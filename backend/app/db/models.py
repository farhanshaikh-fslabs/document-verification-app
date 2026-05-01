import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.sqlite import CHAR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _uuid() -> str:
    return str(uuid.uuid4())


class UserRole(str, enum.Enum):
    reviewer = "reviewer"
    admin = "admin"


class DocumentType(str, enum.Enum):
    certificate = "certificate"  # GCC/CPC
    test_report = "test_report"


class ProcessingStatus(str, enum.Enum):
    pending = "pending"
    extracting = "extracting"
    validating = "validating"
    completed = "completed"
    failed = "failed"


class TrafficLight(str, enum.Enum):
    green = "green"
    yellow = "yellow"
    red = "red"


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, values_callable=lambda x: [e.value for e in x]), default=UserRole.reviewer
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CertificateKind(str, enum.Enum):
    cpc = "cpc"
    gcc = "gcc"


class DocumentSet(Base):
    """A compliance submission: paired certificate + test report."""

    __tablename__ = "document_sets"

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=_uuid)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    certificate_kind: Mapped[CertificateKind] = mapped_column(
        Enum(CertificateKind, values_callable=lambda x: [e.value for e in x]),
        default=CertificateKind.cpc,
        index=True,
    )
    status: Mapped[ProcessingStatus] = mapped_column(
        Enum(ProcessingStatus, values_callable=lambda x: [e.value for e in x]),
        default=ProcessingStatus.pending,
        index=True,
    )
    traffic_light: Mapped[TrafficLight | None] = mapped_column(
        Enum(TrafficLight, values_callable=lambda x: [e.value for e in x]), nullable=True
    )
    traffic_light_reasons: Mapped[list | None] = mapped_column(JSON, nullable=True)
    manual_review_required: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    failure_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    documents: Mapped[list["Document"]] = relationship(back_populates="document_set", cascade="all, delete-orphan")
    extractions: Mapped[list["Extraction"]] = relationship(back_populates="document_set", cascade="all, delete-orphan")
    attribute_validations: Mapped[list["AttributeValidation"]] = relationship(
        back_populates="document_set", cascade="all, delete-orphan"
    )
    citation_validations: Mapped[list["CitationValidation"]] = relationship(
        back_populates="document_set", cascade="all, delete-orphan"
    )
    rating_decisions: Mapped[list["RatingDecision"]] = relationship(
        back_populates="document_set", cascade="all, delete-orphan"
    )
    audit_events: Mapped[list["AuditEvent"]] = relationship(back_populates="document_set", cascade="all, delete-orphan")


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=_uuid)
    document_set_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("document_sets.id", ondelete="CASCADE"))
    doc_type: Mapped[DocumentType] = mapped_column(
        Enum(DocumentType, values_callable=lambda x: [e.value for e in x]), index=True
    )
    original_filename: Mapped[str] = mapped_column(String(512))
    storage_path: Mapped[str] = mapped_column(String(1024))
    mime_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    document_set: Mapped["DocumentSet"] = relationship(back_populates="documents")


class Extraction(Base):
    """One extracted field with evidence (per document set, keyed by attribute path)."""

    __tablename__ = "extractions"

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=_uuid)
    document_set_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("document_sets.id", ondelete="CASCADE"))
    source_document_id: Mapped[str | None] = mapped_column(
        CHAR(36), ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    attribute_key: Mapped[str] = mapped_column(String(256), index=True)
    value_json: Mapped[dict | list | str | None] = mapped_column(JSON, nullable=True)
    raw_text_snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_hint: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    justification: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_edited: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    document_set: Mapped["DocumentSet"] = relationship(back_populates="extractions")


class AttributeValidation(Base):
    __tablename__ = "attribute_validations"

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=_uuid)
    document_set_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("document_sets.id", ondelete="CASCADE"))
    attribute_key: Mapped[str] = mapped_column(String(256), index=True)
    passed: Mapped[bool] = mapped_column(Boolean, default=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    details_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    document_set: Mapped["DocumentSet"] = relationship(back_populates="attribute_validations")


class CitationValidation(Base):
    __tablename__ = "citation_validations"

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=_uuid)
    document_set_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("document_sets.id", ondelete="CASCADE"))
    citation_normalized: Mapped[str] = mapped_column(String(512), index=True)
    on_certificate: Mapped[bool] = mapped_column(Boolean, default=False)
    on_test_report: Mapped[bool] = mapped_column(Boolean, default=False)
    clause_match: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    test_pass_fail: Mapped[str | None] = mapped_column(String(32), nullable=True)
    conformant: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    lab_accreditation_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    cpsc_lookup_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    justification: Mapped[str | None] = mapped_column(Text, nullable=True)
    flagged_immediate_review: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    document_set: Mapped["DocumentSet"] = relationship(back_populates="citation_validations")


class RatingDecision(Base):
    __tablename__ = "rating_decisions"

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=_uuid)
    document_set_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("document_sets.id", ondelete="CASCADE"))
    traffic_light: Mapped[TrafficLight] = mapped_column(
        Enum(TrafficLight, values_callable=lambda x: [e.value for e in x])
    )
    threshold_used: Mapped[float] = mapped_column(Float)
    reasons: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    document_set: Mapped["DocumentSet"] = relationship(back_populates="rating_decisions")


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=_uuid)
    document_set_id: Mapped[str | None] = mapped_column(
        CHAR(36), ForeignKey("document_sets.id", ondelete="SET NULL"), nullable=True, index=True
    )
    user_id: Mapped[str | None] = mapped_column(CHAR(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action: Mapped[str] = mapped_column(String(128), index=True)
    entity_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payload_before: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    payload_after: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    meta_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    document_set: Mapped["DocumentSet | None"] = relationship(back_populates="audit_events")
