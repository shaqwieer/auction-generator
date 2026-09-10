"""Types shared by the rendering pipeline, and the Renderer interface.

Field geometry is stored **normalised** (0..1 of the page box) so a template can
be re-exported at a different trim size without invalidating every mapping. Font
sizes are stored in points against the page height they were authored on, and
scaled by the same ratio at render time.
"""

from __future__ import annotations

from collections.abc import Mapping
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
class FrameItem:
    """One segment of a drawn shape: a line, or a cubic bezier."""

    #: "l" for a line (two points) or "c" for a cubic bezier (four).
    kind: str
    #: x, y pairs in 0..1 of the page, flattened.
    points: list[float]


@dataclass
class FramePath:
    """One shape of the line art a table block is ruled with.

    Kept as the designer's own segments rather than as a rectangle. The numbered
    tab down the edge of «بيان العقارات» is a notched tab with bezier corners,
    and a table that shrank by redrawing it as a box would lose the notch and
    stop being the design.
    """

    items: list[FrameItem]
    #: The ink as the PDF states it -- three components in 0..1 -- rather than
    #: the "#RRGGBB" the rest of the manifest speaks. Nothing edits these, and a
    #: round trip through eight bits a channel does not survive: the tab's teal
    #: is 0.749 green, which is 190.995 of 255, and the byte it went out as is
    #: not the byte it came back as. Redrawn a step lighter, the tab reads as a
    #: patch over the artwork rather than as the artwork.
    stroke: list[float] | None = None
    fill: list[float] | None = None
    width: float = 0.0
    closed: bool = False
    #: The row this shape rules off, for the lines drawn once per row: it is
    #: drawn only while that row exists. ``None`` marks a shape that spans the
    #: whole block -- a column divider, the tab -- which is shortened instead.
    row: int | None = None


@dataclass
class TableFrame:
    """A table block's line art, recorded so its height can follow its rows.

    The designer draws ten rows because a page has to be drawn for something,
    not because every auction sells ten properties. Printing four leaves six
    ruled empty rows and a tab running past the last of them -- «should for
    empty rows delete it like standard». The frame is therefore lifted off the
    artwork at build time and redrawn at render time for the rows there
    actually are: the shapes are the designer's, so a full table is the artwork
    it always was, and a short one is the same artwork ending sooner.

    Painting over the surplus was the alternative and is not one: a white patch
    over a coloured ground is a patch, and the guide's page is not white.
    """

    #: Normalised y of the rule closing each row, in row order. Stored as
    #: measured rather than as a pitch: the designer's rules sit 26.02pt apart
    #: except for two 28.56pt steps, and rebuilding them from an average would
    #: put every rule of a short table in the wrong place.
    rules: list[float]
    paths: list[FramePath]
    #: Normalised y of the block's drawn bottom edge -- what the column dividers
    #: run to, and what the numbered tab ends just past.
    #:
    #: Usually the last row's own rule, and left at zero to say so. Not on «بيان
    #: عقود الإيجار», where the designer ruled twenty bands and numbered
    #: nineteen: the tab there is drawn to the twentieth, so the bottom edge
    #: sits a whole band below the last row a client can fill. Shortening is
    #: measured from this line, which is what makes a full lease table end under
    #: its nineteenth row rather than under an unnumbered empty one -- the empty
    #: row being the thing this is all for.
    bottom: float = 0.0


@dataclass
class TableSpec:
    """A block of identical rows. A page may carry more than one."""

    columns: list[TableColumn]
    rows: int              # how many rows this block can hold
    row_pitch: float       # normalised vertical distance between rows
    row_offset: int = 0    # index of the first row of the page slice it draws
    #: The block's line art, where the build could lift it off the page. Absent
    #: leaves the table the fixed height the designer drew.
    frame: TableFrame | None = None

    @property
    def capacity(self) -> int:
        return self.rows


@dataclass
class ChipPart:
    """A cutting of the artwork, and where on the page it belongs.

    Kept as a page of the background PDF rather than as shapes, because what
    was cut out is a raster, some type and a piece of line art together, and
    the only faithful way to put those back is to place the page they came
    from.
    """

    page: int
    rect: NormRect


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
    #: Set this value on two lines, breaking after its first word.
    #:
    #: The brand guide's rule for the auction's name: «يكون اسم المزاد على
    #: سطرين إذا تم إستخدام الأيقونة يمين الاسم» -- the name is set on two lines
    #: wherever the mark stands to the right of it, which on this template is
    #: every cover. The designer's own two samples both break the same way,
    #: «مزاد» over «أعيان حائل» and «مـزاد» over «درة البحر»: the first word on
    #: its own line and the rest beneath it.
    #:
    #: A break, not a narrower box. Narrowing until the text wraps puts the
    #: break wherever the line happens to run out -- «مزاد أعيان» over «حائل» on
    #: one name and nothing at all on a short one -- and the box a cover gives
    #: the title is the designer's, not ours to shrink.
    #:
    #: A name the client has already broken themselves is left as typed, and a
    #: single word stays on one line: there is no second line to put it on.
    two_lines: bool = False
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
    #: The designer's own mark beside this value, lifted off the artwork so it
    #: can come and go with the value it belongs to.
    #:
    #: معلومات التواصل draws two telephone numbers, each under an icon — a
    #: handset for رقم التواصل, the WhatsApp bubble for واتساب. A booklet whose
    #: seller has no WhatsApp printed the mark with nothing beside it, because
    #: the icon is ink on the page and only the number was ever a field. So the
    #: icon is lifted at build time, erased from the bake, and drawn again here
    #: only when the field draws — which is what makes «if واتساب not exist …
    #: icon of واتساب disappear» something the page can actually do.
    #:
    #: Same shape as :class:`TableFrame`'s paths, and for the same reason: the
    #: designer's own segments, in the ink the file states, rather than a
    #: redrawing of them.
    ornament: list[FramePath] = field(default_factory=list)
    #: The designer's own drawing of this field's chip, cut off the artwork so
    #: that the chip can be absent.
    #:
    #: «معلومات الإيجار» is the case. The guide uses بيان عقود الإيجار «في حال
    #: وجود عقود إيجارية للأصل», so a property with no leases has no such page
    #: and the chip that leads to it should not be printed at all -- but a chip
    #: is a bar, a caption reversed out of it and an arrow beside it, all of it
    #: ink on the page, and only the link was ever a field.
    #:
    #: An ``ornament`` cannot hold it: the bar is a placed raster and the
    #: caption is type, on the برج drawing converted to outlines. So the region
    #: is cut whole onto a page of its own inside the background PDF and drawn
    #: back with ``show_pdf_page``, which reproduces bar, caption and arrow
    #: exactly -- measured at zero differing bytes against the artwork it
    #: replaced. ``page`` is that page, ``rect`` is where on this page it goes.
    part: ChipPart | None = None
    #: Fields the designer set as one centred row.
    #:
    #: The two numbers are a row, and the row is centred on the page: drop one
    #: and the other has to move to the middle, or the page prints a single
    #: number sitting off to one side of a space drawn for two. The renderer
    #: re-centres whatever is left on the extent of what was drawn, so a full
    #: row lands exactly where the artwork had it.
    row_group: str = ""
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
    #: Read-only, and not necessarily in memory. The builder hands over a
    #: mapping that knows every photograph the booklet refers to and fetches
    #: one only when a field actually draws it -- a page redrawn per keystroke
    #: must not read the whole issue's photography to place one frame.
    assets: Mapping[str, bytes] = field(default_factory=dict)
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
