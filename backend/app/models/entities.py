"""Database tables.

Naming note: ``Project`` is one generation run -- a booklet issue. The client's
Arabic "مشروع" means a *lot*, which is a :class:`DataRecord`. Never conflate them.

Enumerated columns are stored as short strings rather than database enums, so
adding a status later is a data change instead of a migration.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


class Role(StrEnum):
    ADMIN = "admin"
    OPERATOR = "operator"
    CLIENT = "client"


class TemplateStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class ProjectStatus(StrEnum):
    DRAFT = "draft"
    MAPPING = "mapping"
    QUEUED = "queued"
    GENERATING = "generating"
    READY = "ready"
    FAILED = "failed"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RecordStatus(StrEnum):
    PENDING = "pending"
    OK = "ok"
    REJECTED = "rejected"


class DataSourceKind(StrEnum):
    EXCEL = "excel"
    MANUAL = "manual"


# ---------------------------------------------------------------- accounts


class Client(Base):
    __tablename__ = "clients"

    id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    contact_email: Mapped[str | None] = mapped_column(String(255))
    contact_phone: Mapped[str | None] = mapped_column(String(40))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # The company's own mark, printed where the booklet's branding goes. An
    # ``Asset.filename`` belonging to this client; empty means the booklet
    # carries the company's name set in type instead.
    logo_filename: Mapped[str | None] = mapped_column(String(255))

    users: Mapped[list[User]] = relationship(back_populates="client")
    projects: Mapped[list[Project]] = relationship(back_populates="client")
    assets: Mapped[list[Asset]] = relationship(back_populates="client")


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _pk()
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), default=Role.CLIENT, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    client_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("clients.id", ondelete="SET NULL")
    )
    client: Mapped[Client | None] = relationship(back_populates="users")

    @property
    def company(self) -> Client | None:
        """The same row, under the name the client-facing API calls it.

        Inside, a ``Client`` is who Matbaa invoices. To the person signing in it
        is their own company — the one whose name and mark go on the booklet —
        and the API says so.
        """
        return self.client

    @property
    def is_staff(self) -> bool:
        return self.role in (Role.ADMIN, Role.OPERATOR)


# ---------------------------------------------------------------- templates


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(60), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    templates: Mapped[list[Template]] = relationship(back_populates="category")


class Template(Base):
    __tablename__ = "templates"

    id: Mapped[uuid.UUID] = _pk()
    slug: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default=TemplateStatus.DRAFT, nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    page_width: Mapped[float] = mapped_column(Float, default=595.28, nullable=False)
    page_height: Mapped[float] = mapped_column(Float, default=841.89, nullable=False)
    design_page_height: Mapped[float] = mapped_column(
        Float, default=841.89, nullable=False
    )
    page_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    source_filename: Mapped[str | None] = mapped_column(String(255))
    background_path: Mapped[str | None] = mapped_column(String(500))
    fonts: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)

    category_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL")
    )
    category: Mapped[Category | None] = relationship(back_populates="templates")

    # Null means the template is available to every client.
    client_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE")
    )

    sections: Mapped[list[TemplateSection]] = relationship(
        back_populates="template", cascade="all, delete-orphan",
        order_by="TemplateSection.position",
    )
    fields: Mapped[list[TemplateField]] = relationship(
        back_populates="template", cascade="all, delete-orphan",
        order_by="TemplateField.page_index",
    )
    pages: Mapped[list[TemplatePage]] = relationship(
        back_populates="template", cascade="all, delete-orphan",
        order_by="TemplatePage.position",
    )


class TemplateSection(Base):
    __tablename__ = "template_sections"
    __table_args__ = (Index("ix_sections_template", "template_id", "position"),)

    id: Mapped[uuid.UUID] = _pk()
    template_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("templates.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    first_page: Mapped[int] = mapped_column(Integer, nullable=False)
    last_page: Mapped[int] = mapped_column(Integer, nullable=False)
    pages_per_item: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    rows_per_page: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    variant: Mapped[str | None] = mapped_column(String(40))
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    template: Mapped[Template] = relationship(back_populates="sections")


class TemplatePage(Base):
    """What one page of a template is, so the builder can offer it.

    Deliberately not columns on :class:`TemplateSection`. A section is a *range*
    that ``compose`` walks and the section editor edits; giving it a role and an
    optional flag would mean either overloading ``kind`` or making every page
    its own one-page section, which breaks composition and record-key discovery
    both.

    ``slot`` groups pages that are alternatives to each other -- the eight
    covers, the two lot layouts -- so the builder can present a choice without
    knowing anything about this particular booklet.
    """

    __tablename__ = "template_pages"
    __table_args__ = (
        UniqueConstraint("template_id", "page_index", name="uq_template_page"),
        Index("ix_template_pages", "template_id", "position"),
    )

    id: Mapped[uuid.UUID] = _pk()
    template_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("templates.id", ondelete="CASCADE"), nullable=False
    )
    page_index: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(30), nullable=False)
    # Pages sharing a slot are alternatives: "cover", "lot".
    slot: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    # For a lot page: "standard" (قياسي) or "tower" (برج/عمارة).
    layout: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    name: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    is_optional: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    default_on: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Anything the builder should know that the columns do not cover -- notably
    # ``needs_artwork``, set where a page is built from artwork that is not
    # really its own and so should not be offered yet.
    options: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    template: Mapped[Template] = relationship(back_populates="pages")


class TemplateField(Base):
    __tablename__ = "template_fields"
    __table_args__ = (
        Index("ix_fields_template_page", "template_id", "page_index"),
    )

    id: Mapped[uuid.UUID] = _pk()
    template_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("templates.id", ondelete="CASCADE"), nullable=False
    )
    key: Mapped[str] = mapped_column(String(80), nullable=False)
    label: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    page_index: Mapped[int] = mapped_column(Integer, nullable=False)
    type: Mapped[str] = mapped_column(String(20), default="text", nullable=False)

    # Normalised geometry: 0..1 of the page box, so a re-export at another trim
    # size does not invalidate the mapping.
    x: Mapped[float] = mapped_column(Float, nullable=False)
    y: Mapped[float] = mapped_column(Float, nullable=False)
    w: Mapped[float] = mapped_column(Float, nullable=False)
    h: Mapped[float] = mapped_column(Float, nullable=False)

    align: Mapped[str] = mapped_column(String(10), default="right", nullable=False)
    valign: Mapped[str | None] = mapped_column(String(10))
    rotation: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    font_family: Mapped[str] = mapped_column(
        String(60), default="RuaqArabic", nullable=False
    )
    font_weight: Mapped[str] = mapped_column(
        String(30), default="Medium", nullable=False
    )
    font_size_pt: Mapped[float] = mapped_column(Float, default=10.0, nullable=False)
    color: Mapped[str] = mapped_column(String(9), default="#000000", nullable=False)
    line_height: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    fit: Mapped[str] = mapped_column(String(10), default="shrink", nullable=False)
    min_scale: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    calibration_dx: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    calibration_dy: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    is_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    rtl: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Images only: fit inside the box rather than fill it. See FieldSpec.
    preserve_aspect: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="false"
    )
    # The shape the field's box is drawn as, if it is not a rectangle, and the
    # shapes drawn over it. See FieldSpec.clip and FieldSpec.clip_holes.
    clip: Mapped[list | None] = mapped_column(JSONB)
    clip_holes: Mapped[list | None] = mapped_column(JSONB)
    origin: Mapped[str] = mapped_column(String(200), default="", nullable=False)

    # Fixed wording printed around the value, and what prints when nothing has
    # been typed. See FieldSpec.prefix / FieldSpec.default_value: a caption that
    # is mostly the guide's sentence asks only for the words that change.
    prefix: Mapped[str] = mapped_column(
        Text, default="", nullable=False, server_default=""
    )
    suffix: Mapped[str] = mapped_column(
        Text, default="", nullable=False, server_default=""
    )
    default_value: Mapped[str] = mapped_column(
        Text, default="", nullable=False, server_default=""
    )

    # Only populated for type == "table".
    table_spec: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    template: Mapped[Template] = relationship(back_populates="fields")


# ---------------------------------------------------------------- projects


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (Index("ix_projects_client_status", "client_id", "status"),)

    id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default=ProjectStatus.DRAFT, nullable=False
    )

    client_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
    template_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("templates.id", ondelete="RESTRICT"), nullable=False
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )

    # Project-level values -- the manual screen's "بيانات ثابتة تظهر على كل صفحة".
    static_values: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, nullable=False
    )
    variant: Mapped[str | None] = mapped_column(String(40))
    #: "print" or "electronic". On paper a link has to be a code somebody scans;
    #: on screen a code is useless and the chip should simply be clickable. The
    #: pages are the same either way — only which half of each link chip is
    #: drawn changes. Kept on the project so a regenerate repeats the choice.
    output_flavour: Mapped[str] = mapped_column(
        String(20), default="print", server_default="print", nullable=False
    )
    #: "blue" or "green". The lease table is drawn in the brand's navy; the
    #: summary page proves both colours are the brand's, so the other is offered
    #: by rewriting the colour the page asks for. One choice for the booklet, so
    #: its lease pages do not disagree with each other.
    lease_colourway: Mapped[str] = mapped_column(
        String(20), default="blue", server_default="blue", nullable=False
    )

    # The booklet the client assembled: an ordered list of nodes, each one an
    # output page, one lot's pages, or the summary table. Null means the project
    # predates the builder -- or its template carries no page rows -- and
    # generation falls back to the template's section plan unchanged.
    page_plan: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    # Output settings from the review step. Both default off: the client's own
    # approved artwork is RGB with no bleed.
    output_mode: Mapped[str] = mapped_column(
        String(20), default="merged", nullable=False
    )  # merged | per_record
    add_bleed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    convert_cmyk: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    @property
    def has_plan(self) -> bool:
        """Whether this project was assembled in the builder.

        Read by the API rather than the plan itself, which is large and only
        the builder screen needs it.
        """
        return bool(self.page_plan)

    client: Mapped[Client] = relationship(back_populates="projects")
    template: Mapped[Template] = relationship()
    data_sources: Mapped[list[DataSource]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    records: Mapped[list[DataRecord]] = relationship(
        back_populates="project", cascade="all, delete-orphan",
        order_by="DataRecord.row_index",
    )
    mappings: Mapped[list[FieldMapping]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    jobs: Mapped[list[GenerationJob]] = relationship(
        back_populates="project", cascade="all, delete-orphan",
        order_by="GenerationJob.created_at.desc()",
    )


class DataSource(Base):
    __tablename__ = "data_sources"

    id: Mapped[uuid.UUID] = _pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(
        String(20), default=DataSourceKind.EXCEL, nullable=False
    )
    filename: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    stored_path: Mapped[str | None] = mapped_column(String(500))
    sheet: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    columns: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, nullable=False
    )
    row_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    warnings: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)

    project: Mapped[Project] = relationship(back_populates="data_sources")


class DataRecord(Base):
    """One lot. The Arabic "مشروع" in the client's vocabulary."""

    __tablename__ = "data_records"
    __table_args__ = (
        UniqueConstraint("project_id", "row_index", name="uq_record_row"),
    )

    id: Mapped[uuid.UUID] = _pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    row_index: Mapped[int] = mapped_column(Integer, nullable=False)
    values: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    source: Mapped[str] = mapped_column(
        String(20), default=DataSourceKind.EXCEL, nullable=False
    )

    project: Mapped[Project] = relationship(back_populates="records")


class FieldMapping(Base):
    __tablename__ = "field_mappings"
    __table_args__ = (
        UniqueConstraint("project_id", "field_key", name="uq_mapping_field"),
    )

    id: Mapped[uuid.UUID] = _pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    field_key: Mapped[str] = mapped_column(String(80), nullable=False)
    column_name: Mapped[str | None] = mapped_column(String(255))
    static_value: Mapped[str | None] = mapped_column(Text)

    project: Mapped[Project] = relationship(back_populates="mappings")

    @property
    def target(self) -> str | None:
        if self.static_value is not None:
            return f"={self.static_value}"
        return self.column_name


class GenerationJob(Base):
    __tablename__ = "generation_jobs"
    __table_args__ = (Index("ix_jobs_status", "status", "created_at"),)

    id: Mapped[uuid.UUID] = _pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(20), default=JobStatus.QUEUED, nullable=False
    )
    engine: Mapped[str] = mapped_column(String(40), default="", nullable=False)

    total_records: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completed_records: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rejected_records: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    page_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_summary: Mapped[str | None] = mapped_column(Text)
    log: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, nullable=False
    )

    output_path: Mapped[str | None] = mapped_column(String(500))
    output_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_filename: Mapped[str | None] = mapped_column(String(255))

    project: Mapped[Project] = relationship(back_populates="jobs")
    results: Mapped[list[RecordResult]] = relationship(
        back_populates="job", cascade="all, delete-orphan",
        order_by="RecordResult.row_index",
    )

    @property
    def progress(self) -> float:
        if not self.total_records:
            return 0.0
        return round(
            (self.completed_records + self.rejected_records) / self.total_records, 4
        )


class RecordResult(Base):
    """One row's outcome. Always names the row, the field and a readable cause."""

    __tablename__ = "record_results"
    __table_args__ = (Index("ix_results_job_status", "job_id", "status"),)

    id: Mapped[uuid.UUID] = _pk()
    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("generation_jobs.id", ondelete="CASCADE"), nullable=False
    )
    row_index: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default=RecordStatus.PENDING, nullable=False
    )
    field_key: Mapped[str | None] = mapped_column(String(80))
    cause: Mapped[str | None] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(10), default="error", nullable=False)
    output_path: Mapped[str | None] = mapped_column(String(500))

    job: Mapped[GenerationJob] = relationship(back_populates="results")


class ShortLink(Base):
    """A printed code, and where it currently leads.

    The indirection is the point. A code printed in a booklet cannot be edited,
    so it never carries a destination: it carries its own permanent address, and
    this row says what that address redirects to today. A client who moves a
    survey file changes the row; the paper keeps working.

    One row per slot per property, so regenerating a booklet reprints the same
    codes rather than minting new ones and orphaning the paper already out.
    """

    __tablename__ = "short_links"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "row_index", "field_key", name="uq_short_link_slot"
        ),
    )

    id: Mapped[uuid.UUID] = _pk()
    code: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    #: Which property, or null for a link belonging to the booklet as a whole.
    row_index: Mapped[int | None] = mapped_column(Integer)
    field_key: Mapped[str] = mapped_column(String(80), nullable=False)
    target: Mapped[str] = mapped_column(String(2000), default="", nullable=False)


class Asset(Base):
    """An uploaded image, stored once and reusable across booklets."""

    __tablename__ = "assets"
    __table_args__ = (Index("ix_assets_client", "client_id", "role"),)

    id: Mapped[uuid.UUID] = _pk()
    client_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_path: Mapped[str] = mapped_column(String(500), nullable=False)
    content_type: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    width: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    height: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    role: Mapped[str] = mapped_column(String(30), default="extra", nullable=False)
    uploaded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )

    client: Mapped[Client] = relationship(back_populates="assets")

    def dpi_at(self, width_pt: float) -> float:
        """Effective print resolution if placed in a box this wide."""
        if width_pt <= 0:
            return 0.0
        return round(self.width / (width_pt / 72.0), 1)
