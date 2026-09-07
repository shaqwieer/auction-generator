"""Types shared by the rendering pipeline, and the Renderer interface.

Field geometry is stored **normalised** (0..1 of the page box) so a template can
be re-exported at a different trim size without invalidating every mapping. Font
sizes are stored in points against the page height they were authored on, and
scaled by the same ratio at render time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

import fitz

from .shaping import Align, Fit, VAlign


class FieldType(StrEnum):
    TEXT = "text"
    IMAGE = "image"
    QR = "qr"
    BARCODE = "barcode"
    LINK = "link"
    TABLE = "table"


class SectionKind(StrEnum):
    FIXED = "fixed"            # rendered once
    PER_RECORD = "per_record"  # repeated, pages_per_item pages per data record
    TABLE = "table"            # a paginating summary table


@dataclass(frozen=True)
class NormRect:
    """A rectangle in normalised page coordinates (0..1, origin top-left)."""

    x: float
    y: float
    w: float
    h: float

    def to_points(self, page: fitz.Rect) -> fitz.Rect:
        return fitz.Rect(
            page.x0 + self.x * page.width,
            page.y0 + self.y * page.height,
            page.x0 + (self.x + self.w) * page.width,
            page.y0 + (self.y + self.h) * page.height,
        )

    @classmethod
    def from_points(cls, rect: fitz.Rect, page: fitz.Rect) -> NormRect:
        return cls(
            x=(rect.x0 - page.x0) / page.width,
            y=(rect.y0 - page.y0) / page.height,
            w=rect.width / page.width,
            h=rect.height / page.height,
        )


@dataclass
class TableColumn:
    """One column of a repeating table, positioned on the block's first row."""

    key: str
    rect: NormRect
    label: str = ""
    align: Align = Align.CENTER
    valign: VAlign | None = None
    font_family: str = "RuaqArabic"
    font_weight: str = "Medium"
    font_size_pt: float = 8.0
    color: str = "#001447"
    fit: Fit = Fit.SHRINK
    rtl: bool = True
    # "" takes the value from record[key]; "__index__" prints the row number.
    source: str = ""


@dataclass
class TableSpec:
    """A block of identical rows. A page may carry more than one."""

    columns: list[TableColumn]
    rows: int              # how many rows this block can hold
    row_pitch: float       # normalised vertical distance between rows
    row_offset: int = 0    # index of the first row of the page slice it draws

    @property
    def capacity(self) -> int:
        return self.rows


@dataclass
class FieldSpec:
    """One editable region on one template page."""

    key: str
    page_index: int
    rect: NormRect
    type: FieldType = FieldType.TEXT
    label: str = ""
    align: Align = Align.RIGHT
    valign: VAlign | None = None
    rotation: int = 0
    font_family: str = "RuaqArabic"
    font_weight: str = "Medium"
    font_size_pt: float = 10.0
    color: str = "#000000"
    line_height: float = 1.0
    fit: Fit = Fit.SHRINK
    min_scale: float = 0.5
    calibration_dx: float = 0.0
    calibration_dy: float = 0.0
    is_required: bool = False
    rtl: bool = True
    #: Fixed wording printed around the value, so a caption can be part design
    #: and part data. The steps page is the case: «سداد قيمة المشاركة في المزاد
    #: (…)» is the guide's sentence and only the bracketed words change, so the
    #: client is asked for those words and cannot mistype the rest. The whole
    #: caption is drawn as one box, which is why it still wraps and centres the
    #: way the designer drew it — carving out only the middle would leave the
    #: fixed halves stranded when the value changes length.
    #: A newline is a deliberate line break (the engine turns it into <br>), so
    #: the caption breaks where the artwork breaks rather than where it measures.
    prefix: str = ""
    suffix: str = ""
    #: What prints when nothing has been typed. {other_key} takes the value
    #: from elsewhere in the booklet — the platform and the auction are named on
    #: the auction-info page, and naming them again on this one would be asking
    #: twice for one fact. Resolved at draw time, never copied, so a title
    #: corrected on the cover corrects the steps page too.
    default_value: str = ""
    #: Fit the image inside the box instead of filling it. A photograph is
    #: cropped to its frame, which is what a frame is for; a logo cropped to a
    #: frame is a broken logo, and one stretched to it is worse.
    preserve_aspect: bool = False
    #: The shape the frame is actually drawn as, as ``[x, y]`` pairs in 0..1 of
    #: this field's own box — so it moves and scales with the box. Empty means a
    #: plain rectangle. The lot page cuts a corner out of its photo frame for the
    #: property number, and a photograph filling the bounding box covers it.
    # How this field was proposed ("autokey:deed_number", "rule:lot_number").
    # Recorded so that re-ingesting a revised design shows which rule moved.
    origin: str = ""
    # Only for FieldType.TABLE.
    table: TableSpec | None = None
    clip: list[list[float]] = field(default_factory=list)
    #: Shapes the designer draws *over* the image — the property number's badge,
    #: the closing-time chip — as rings in the same coordinates as ``clip``. The
    #: photograph is masked out of them, because it is placed on top of the
    #: baked artwork and would otherwise cover the very things printed over it.
    clip_holes: list[list[list[float]]] = field(default_factory=list)
    # table fields carry per-column alignment; see the summary table in the
    # auction booklet, which mixes Arabic labels with Latin numerals per row.
    columns: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class PageInstance:
    """One page of output: a background page plus the values to draw on it."""

    template_page_index: int
    values: dict[str, Any] = field(default_factory=dict)
    record_index: int | None = None


@dataclass
class RenderIssue:
    """A problem worth showing the user. Always names row, field and cause."""

    row_index: int | None
    field_key: str | None
    cause: str
    severity: str = "warning"  # "warning" | "error"

    def as_dict(self) -> dict[str, Any]:
        return {
            "row": self.row_index,
            "field": self.field_key,
            "cause": self.cause,
            "severity": self.severity,
        }


@dataclass
class RenderPlan:
    """Everything the renderer needs to produce one document."""

    background: fitz.Document
    fields: list[FieldSpec]
    pages: list[PageInstance]
    assets: dict[str, bytes] = field(default_factory=dict)
    design_page_height: float = 841.89

    def fields_for(self, template_page_index: int) -> list[FieldSpec]:
        return [f for f in self.fields if f.page_index == template_page_index]


@dataclass
class RenderResult:
    pdf: bytes
    page_count: int
    issues: list[RenderIssue] = field(default_factory=list)


class Renderer(Protocol):
    """The seam we would swap if the engine ever changed. Call this, not fitz."""

    def render(self, plan: RenderPlan) -> RenderResult: ...
