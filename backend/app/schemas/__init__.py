"""Pydantic v2 request and response models for the v1 API."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ------------------------------------------------------------------- auth


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int


class CompanyOut(ORM):
    """The company a signed-in client is printing for."""

    id: uuid.UUID
    name: str
    code: str
    logo_filename: str | None = None


class CompanyUpdate(BaseModel):
    #: Required, and required to be non-blank: it is what prints on the booklet
    #: wherever no logo has been uploaded, and a booklet cannot go out unbranded.
    name: str = Field(min_length=1)


class UserOut(ORM):
    id: uuid.UUID
    email: str
    name: str
    role: str
    is_active: bool
    client_id: uuid.UUID | None = None
    #: Whose booklets these are. Carried on the user so the shell can show the
    #: company at the top of the sidebar without a second round trip, and so a
    #: client can see at a glance which company they are printing for.
    company: CompanyOut | None = None


class UserCreate(BaseModel):
    email: EmailStr
    name: str
    password: str = Field(min_length=8)
    role: Literal["admin", "operator", "client"] = "client"
    client_id: uuid.UUID | None = None


# ---------------------------------------------------------------- catalogue


class CategoryOut(ORM):
    id: uuid.UUID
    name: str
    slug: str
    description: str | None = None
    template_count: int = 0


class ClientOut(ORM):
    id: uuid.UUID
    name: str
    code: str
    contact_email: str | None = None
    contact_phone: str | None = None
    is_active: bool
    #: The company's own mark, printed on every page the booklet brands. Empty
    #: means the booklet carries the company's name set in type instead.
    logo_filename: str | None = None
    project_count: int = 0
    user_count: int = 0


class ClientUserCreate(BaseModel):
    """A sign-in for a client, created alongside it or added later."""

    name: str
    email: EmailStr
    password: str = Field(min_length=8)
    role: Literal["client", "operator"] = "client"


class ClientCreate(BaseModel):
    name: str
    code: str
    contact_email: EmailStr | None = None
    contact_phone: str | None = None
    # Optional: create the first sign-in in the same transaction, so a failed
    # user cannot leave a client behind that nobody can log in to.
    user: ClientUserCreate | None = None


class PasswordReset(BaseModel):
    password: str = Field(min_length=8)


class ClientUpdate(BaseModel):
    name: str | None = None
    logo_filename: str | None = None
    contact_email: EmailStr | None = None
    contact_phone: str | None = None
    is_active: bool | None = None


class CategoryCreate(BaseModel):
    name: str
    slug: str
    description: str | None = None
    position: int = 0


class CategoryUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    position: int | None = None


class TemplateFieldOut(ORM):
    """One field as the editor reads it back.

    Every column the editor is allowed to *write* must appear here too. Saving
    fields is a full replace, so a column the editor cannot read is a column it
    silently resets to its default on the next save -- which is how ``valign``
    and ``line_height`` used to be stripped off the booklet's wrap fields.
    """

    id: uuid.UUID
    key: str
    label: str
    page_index: int
    type: str
    x: float
    y: float
    w: float
    h: float
    align: str
    valign: str | None = None
    rotation: int
    font_family: str
    font_weight: str
    font_size_pt: float
    color: str
    line_height: float
    fit: str
    min_scale: float
    calibration_dx: float
    calibration_dy: float
    is_required: bool
    rtl: bool
    preserve_aspect: bool = False
    #: The shape the box is drawn as, where it is not a rectangle.
    clip: list[list[float]] | None = None
    clip_holes: list[list[list[float]]] | None = None
    #: The designer's mark beside this value, and the centred row it sits in.
    ornament: list[dict[str, Any]] | None = None
    row_group: str = ""
    #: Set on two lines, breaking after the first word.
    two_lines: bool = False
    #: A cutting of the artwork this field draws back when it is in play.
    part: dict[str, Any] | None = None
    #: Fixed wording printed around the value, and what prints without one.
    #: Read as well as written, per the note above: the steps page's captions
    #: are mostly prefix, and an editor save that could not see them would
    #: hand the client five numbered icons and no instructions.
    prefix: str = ""
    suffix: str = ""
    default_value: str = ""
    origin: str
    table_spec: dict[str, Any] | None = None


class TemplateSectionOut(ORM):
    id: uuid.UUID
    name: str
    kind: str
    first_page: int
    last_page: int
    pages_per_item: int
    rows_per_page: int
    variant: str | None = None


class TemplateOut(ORM):
    id: uuid.UUID
    slug: str
    name: str
    code: str
    status: str
    version: int
    page_width: float
    page_height: float
    page_count: int
    category_id: uuid.UUID | None = None
    fonts: list[str] = []
    field_count: int = 0


class TemplatePageOut(ORM):
    """What one page of the template is, so the builder can offer it.

    ``slot`` groups alternatives -- the cover designs, the two lot layouts --
    so a chooser can be rendered without knowing anything about this booklet.
    """

    id: uuid.UUID
    page_index: int
    role: str
    slot: str
    layout: str
    name: str
    is_optional: bool
    default_on: bool
    options: dict[str, Any] = {}
    position: int


class TemplateDetail(TemplateOut):
    sections: list[TemplateSectionOut] = []
    pages: list[TemplatePageOut] = []
    fields: list[TemplateFieldOut] = []
    record_keys: list[str] = []
    static_keys: list[str] = []
    required_keys: list[str] = []


class TemplateSectionUpdate(BaseModel):
    """One section as saved by the template editor."""

    name: str = ""
    kind: Literal["fixed", "per_record", "table"] = "fixed"
    first_page: int
    last_page: int
    pages_per_item: int = 1
    rows_per_page: int = 1
    variant: str | None = None


class TemplateIngestOut(BaseModel):
    template: TemplateDetail
    pages: int
    proposed_fields: int
    auto_named: int
    tables: int


class TemplateFieldUpdate(BaseModel):
    """One field as saved by the template editor.

    Every column is optional-by-omission: what the editor does not send, the
    save leaves alone. That is what stops a screen with no control for a clip
    path from clearing one. Sending an explicit null still clears it, so
    "never strip" does not become "never change".
    """

    #: Which stored row this is. A field is the row, not its name -- without
    #: this, renaming a key would replace the row and lose every column the
    #: editor does not send.
    id: uuid.UUID | None = None
    key: str
    label: str = ""
    page_index: int
    type: str = "text"
    x: float
    y: float
    w: float
    h: float
    align: str = "right"
    valign: str | None = None
    rotation: int = 0
    font_family: str = "RuaqArabic"
    font_weight: str = "Medium"
    font_size_pt: float = 10.0
    color: str = "#000000"
    line_height: float = 1.0
    fit: str = "shrink"
    min_scale: float = 0.5
    calibration_dx: float = 0.0
    calibration_dy: float = 0.0
    is_required: bool = False
    rtl: bool = True
    # Both belong to how an image is drawn rather than to where it sits, and
    # saving fields is a full replace -- a column the editor cannot write is a
    # column it silently resets on the next save.
    preserve_aspect: bool = False
    clip: list[list[float]] | None = None
    clip_holes: list[list[list[float]]] | None = None
    ornament: list[dict[str, Any]] | None = None
    row_group: str = ""
    two_lines: bool = False
    part: dict[str, Any] | None = None
    prefix: str = ""
    suffix: str = ""
    default_value: str = ""
    table_spec: dict[str, Any] | None = None


# ----------------------------------------------------------------- projects


class ProjectCreate(BaseModel):
    name: str
    template_id: uuid.UUID
    client_id: uuid.UUID | None = None
    variant: str | None = None
    # Which of the template's cover designs to start from, and how many
    # properties to lay out. Both only mean anything for a template that
    # carries page roles; without them the project starts empty.
    cover_page: int | None = None
    lot_count: int = 0


class ProjectUpdate(BaseModel):
    name: str | None = None
    #: "print" (link chips print a code) or "electronic" (they are clickable).
    output_flavour: Literal["print", "electronic"] | None = None
    #: Which colour the lease tables are printed in.
    lease_colourway: Literal["blue", "green"] | None = None
    static_values: dict[str, Any] | None = None
    output_mode: Literal["merged", "per_record"] | None = None
    add_bleed: bool | None = None
    convert_cmyk: bool | None = None
    variant: str | None = None


class ProjectOut(ORM):
    id: uuid.UUID
    name: str
    status: str
    client_id: uuid.UUID
    template_id: uuid.UUID
    variant: str | None = None
    static_values: dict[str, Any] = {}
    output_mode: str
    add_bleed: bool
    convert_cmyk: bool
    record_count: int = 0
    output_flavour: str = "print"
    lease_colourway: str = "blue"
    updated_at: datetime
    template_name: str | None = None
    category_name: str | None = None
    # Null where the project predates the builder; the wizard's escape-hatch
    # screens are still reachable for those.
    has_plan: bool = False


class PagePlanNode(BaseModel):
    """One node of a booklet plan, as the builder reads and writes it."""

    id: str
    kind: str                       # page | lot | table
    page: int | None = None
    row: int | None = None
    layout: str | None = None
    pages: list[int] = []
    options: list[str] = []
    slot: str | None = None
    rows_per_page: int | None = None
    #: Switched out of the booklet. Keeps its place and everything typed on it.
    off: bool = False
    values: dict[str, Any] = {}


class PagePlanOut(BaseModel):
    """Everything the builder needs to draw the booklet in one round trip."""

    revision: int
    nodes: list[PagePlanNode]
    pages: list[TemplatePageOut]
    fields_by_page: dict[int, list[TemplateFieldOut]]
    record_keys: list[str]
    predicted_pages: int
    #: What the booklet knows about itself -- the auction's name, the platform's
    #: -- resolved the same way the renderer resolves it. A field whose
    #: default_value names one of these prints it without being typed into,
    #: so the box beside the page shows it too rather than looking unfilled.
    booklet: dict[str, str] = {}


class NodeAdd(BaseModel):
    kind: str = "page"
    after: str | None = None
    page: int | None = None
    row: int | None = None
    layout: str | None = None
    revision: int | None = None


class NodeMove(BaseModel):
    delta: int = 1
    revision: int | None = None


class NodeLeaseRows(BaseModel):
    """A property's lease contracts, in the order they print."""

    rows: list[dict[str, str]] = []
    revision: int | None = None


class NodeEnabled(BaseModel):
    on: bool = True
    revision: int | None = None


class NodeLayout(BaseModel):
    layout: str | None = None
    options: list[str] | None = None
    #: Which of a slot's alternatives to use, where the choice is a whole page
    #: rather than a layout name -- the summary table's two colourways.
    page: int | None = None
    revision: int | None = None


class NodeValues(BaseModel):
    values: dict[str, Any] = {}
    revision: int | None = None


class ColumnOut(BaseModel):
    index: int
    name: str
    letter: str
    sample: str
    kind: str
    tag: str
    non_empty: int


class DataSourceOut(ORM):
    id: uuid.UUID
    kind: str
    filename: str
    sheet: str
    row_count: int
    columns: list[dict[str, Any]] = []
    warnings: list[str] = []


class UploadResult(BaseModel):
    data_source: DataSourceOut
    preview: list[dict[str, str]]
    suggested_mapping: dict[str, str | None]


class MappingEntry(BaseModel):
    field_key: str
    column: str | None = None
    static_value: str | None = None


class MappingSave(BaseModel):
    entries: list[MappingEntry]


class MappingProblem(BaseModel):
    field_key: str
    message: str
    severity: str


class MappingOut(BaseModel):
    entries: list[MappingEntry]
    problems: list[MappingProblem]
    record_keys: list[str]
    required_keys: list[str]


class RecordIn(BaseModel):
    values: dict[str, Any]


class RecordsSave(BaseModel):
    records: list[RecordIn]


class RecordPatch(BaseModel):
    """Merge these values into one record, leaving the rest untouched."""

    values: dict[str, Any]


class ImageFieldOut(BaseModel):
    key: str
    label: str
    scope: Literal["record", "project"]
    is_required: bool


class RecordOut(ORM):
    id: uuid.UUID
    row_index: int
    values: dict[str, Any]
    source: str


class RecordPhotosOut(BaseModel):
    """Everything the photo step needs: which fields, and what each row has."""

    fields: list[ImageFieldOut]
    records: list[RecordOut]
    static_values: dict[str, Any] = {}


class PreflightOut(BaseModel):
    record_count: int
    generatable: int
    predicted_pages: int
    rejected: dict[int, list[str]]
    missing_assets: list[str]


# --------------------------------------------------------------------- jobs


class JobOut(ORM):
    id: uuid.UUID
    project_id: uuid.UUID
    status: str
    engine: str
    total_records: int
    completed_records: int
    rejected_records: int
    page_count: int
    progress: float
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_summary: str | None = None
    output_filename: str | None = None
    output_bytes: int
    created_at: datetime


class JobDetail(JobOut):
    log: list[dict[str, Any]] = []
    project_name: str | None = None
    client_name: str | None = None


class ResultOut(ORM):
    row_index: int
    status: str
    field_key: str | None = None
    cause: str | None = None
    severity: str


class RetryRequest(BaseModel):
    rows: list[int] | None = None


# ------------------------------------------------------------------- assets


class AssetOut(ORM):
    id: uuid.UUID
    filename: str
    content_type: str
    width: int
    height: int
    size_bytes: int
    role: str
    created_at: datetime


class AssetWithDpi(AssetOut):
    print_dpi_a4: float = 0.0
    below_min_dpi: bool = False


# ---------------------------------------------------------------- dashboard


class StatOut(BaseModel):
    label: str
    value: str
    delta: str | None = None


class DashboardOut(BaseModel):
    stats: list[StatOut]
    running_jobs: list[JobOut]
    recent_jobs: list[JobOut]
    usage: list[dict[str, Any]]
