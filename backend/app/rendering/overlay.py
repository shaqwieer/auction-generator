"""The PDF renderer: draw variable data onto the designer's own artwork.

This is the single implementation behind :class:`~app.rendering.base.Renderer`.
See ``docs/engine-decision.md`` for why an overlay compositor beat both the
ReportLab and the headless-Chromium routes on this project's real files.

Repeated background pages are drawn with ``show_pdf_page``, which references the
source page as a form XObject. A booklet with twenty lot pages therefore carries
the artwork once, not twenty times.
"""

from __future__ import annotations

import re
from itertools import pairwise

import fitz

from . import messages
from .base import (
    FieldSpec,
    FieldType,
    PageInstance,
    RenderIssue,
    RenderPlan,
    RenderResult,
)
from .fonts import FontError, FontRegistry, brand_registry
from .images import barcode_png, prepare, qr_png
from .shaping import calibrated_htmlbox


def _label(spec: FieldSpec) -> str:
    return spec.label or spec.key


#: An image field covering this much of the page is the page's backdrop. The
#: cover photograph is stored as the whole page because that is how the designer
#: placed it; a property photograph sits in a frame and is a tenth of that.
BACKDROP_COVERAGE = 0.92


#: Where a link leads inside the document rather than out of it. The value is
#: the output page it jumps to, which only the composer knows.
GOTO_PREFIX = "__goto_"

#: How big a mark is drawn, as a percentage of the box the designer drew for it.
#:
#: Written «width×height», either half optional, and named for the page it
#: applies to — the same lockup is drawn at eighteen sizes through the booklet,
#: and a company whose mark is wider than the guide's sample wants room on the
#: cover that it does not want in a footer.
#:
#: The page is in the key because a property's values are kept on its record and
#: every page of that property reads them: without it, sizing the mark on صفحة
#: العقار would have sized the one on مميزات العقار too, which is not what «each
#: logo» means.
#:
#: Only ever the box. The mark keeps its own proportions inside it
#: (``preserve_aspect``), so this cannot stretch a logo however it is typed --
#: which is why it is offered for a mark and not for a photograph, where the
#: box is the frame the designer drew and filling it is the point.
SIZE_PREFIX = "__size_"

#: A box may be shrunk to a tenth or grown tenfold and no further. Wide enough
#: for any real mark, and narrow enough that a stray keystroke cannot draw a
#: logo across the whole booklet.
SIZE_LIMITS = (0.1, 10.0)

#: The booklet's own facts, for a field whose ``default_value`` names one --
#: the auction and the platform are typed on the auction-info page and belong
#: to the whole issue, not to the page that happens to print them again. Kept
#: under a reserved key rather than merged into the values so that nothing
#: starts printing merely because the booklet knows it. See ``compose``.
DEFAULTS_KEY = "__booklet__"

#: What a table cell prints when the property exists but the fact does not.
#: The guide's own instruction for بيان العقارات, and a hyphen rather than a
#: dash because that is the character it prints.
MISSING_CELL = "-"


_SLOT = re.compile(r"\{([a-z0-9_]+)\}")


def _resolve(template: str, booklet: dict) -> str:
    """Fill ``{key}`` from the booklet's own facts; an unknown key empties."""
    if not template:
        return ""
    return _SLOT.sub(lambda m: str(booklet.get(m.group(1)) or "").strip(), template)


def _joined(prefix: str, inner: str) -> str:
    """The fixed wording and the value, without saying one word twice.

    They are one sentence, and the join is where it can go wrong. خطوات
    المشاركة reads «إختيار مزاد …», and the booklet it is in is «مزاد أعيان
    حائل» — so the caption printed «إختيار مزاد مزاد أعيان حائل». The
    designer's own sample avoided it by writing the bare name between the
    brackets, which is a thing a person does without thinking and a fallback
    cannot: the name it falls back to is the whole title, because that is the
    fact the booklet holds.

    Whole words only, and only across the join, so a value that genuinely
    begins with the word before it keeps it wherever it is not a repetition of
    the caption's own last word.
    """
    head = prefix.split()
    tail = inner.split()
    if head and tail and head[-1] == tail[0]:
        return f"{prefix}{inner.split(maxsplit=1)[1]}" if len(tail) > 1 else prefix
    return f"{prefix}{inner}"


def _stacked(text: str) -> str:
    """The first word on its own line and the rest beneath it.

    «يكون اسم المزاد على سطرين إذا تم إستخدام الأيقونة يمين الاسم» -- the
    guide's rule for the name that stands beside the mark, and both of its own
    samples break it the same way: «مزاد» over «أعيان حائل», «مـزاد» over «درة
    البحر». The newline is what the engine turns into a <br>, so this is the
    same kind of break the designer typed.

    A name already broken by hand is left alone rather than broken again -- two
    breaks would make three lines -- and a single word is returned untouched,
    because there is no second line to put anything on.
    """
    if "\n" in text:
        return text
    head, sep, tail = text.strip().partition(" ")
    return f"{head}\n{tail.strip()}" if sep and tail.strip() else text


def _caption(spec: FieldSpec, value: str, booklet: dict) -> str:
    """What this field actually prints: fixed wording around a typed value.

    The value falls back to ``default_value`` -- which is the point of the
    steps page: nothing typed there still prints the guide's sentence with the
    auction's own name in it, and typing replaces only the name.
    """
    inner = value or _resolve(spec.default_value, booklet)
    if spec.two_lines:
        inner = _stacked(inner)
    if not spec.prefix and not spec.suffix:
        return inner
    if spec.prefix:
        return f"{_joined(spec.prefix, inner)}{spec.suffix}"
    # The fixed halves print even with nothing between them. A caption that
    # vanished because its one variable word was blank would take the
    # designer's sentence with it, and the page was cleared to make room for it.
    return f"{spec.prefix}{inner}{spec.suffix}"


def _is_backdrop(rect: fitz.Rect, page_rect: fitz.Rect) -> bool:
    area = page_rect.get_area()
    return bool(area) and (rect & page_rect).get_area() / area >= BACKDROP_COVERAGE


def _resized(rect: fitz.Rect, setting: str) -> fitz.Rect:
    """The box grown or shrunk about its own centre, per «width×height».

    Either half may be left out — «120» is 120% of the width and the height
    untouched, «×80» the other way about. Anything that is not a number is
    ignored rather than refused: this is a value typed into a box on a page,
    and a half-typed number must not blank the mark being sized.
    """
    width, _, height = str(setting).partition("x")
    factors: list[float] = []
    for raw in (width, height):
        try:
            factor = float(raw.strip().rstrip("%")) / 100.0
        except ValueError:
            factor = 1.0
        low, high = SIZE_LIMITS
        factors.append(min(max(factor, low), high))
    grow_x = rect.width * (factors[0] - 1.0) / 2
    grow_y = rect.height * (factors[1] - 1.0) / 2
    return rect + (-grow_x, -grow_y, grow_x, grow_y)


class PyMuPDFOverlayRenderer:
    """Composites values onto baked background pages.

    ``image_dpi`` is the resolution photographs are resampled *for*. It is the
    print resolution unless a caller says otherwise, and the builder does: its
    page is rastered at about 110dpi, so resampling a phone frame to 300 for it
    is work thrown away a moment later. What the resolution is *judged* against
    does not move with it — a photograph too coarse to print says so in the
    preview, which is where it is worth hearing.
    """

    def __init__(
        self,
        registry: FontRegistry | None = None,
        *,
        image_dpi: int | None = None,
    ) -> None:
        self._registry = registry or brand_registry()
        self._image_dpi = image_dpi

    # -- public API ----------------------------------------------------------

    def render(self, plan: RenderPlan) -> RenderResult:
        out = fitz.open()
        issues: list[RenderIssue] = []
        # Jumps are held back until every page exists. MuPDF refuses a link to a
        # page that has not been made yet, and a lease chip on the first property
        # page points several pages ahead of itself.
        jumps: list[tuple[int, fitz.Rect, int]] = []
        try:
            for instance in plan.pages:
                self._render_page(out, plan, instance, issues, jumps)
            for number, box, destination in jumps:
                if 0 <= destination < out.page_count:
                    out[number].insert_link({
                        "kind": fitz.LINK_GOTO,
                        "from": box,
                        "page": destination,
                        "to": fitz.Point(0, 0),
                    })
            pdf = out.tobytes(garbage=4, deflate=True, clean=True)
            return RenderResult(pdf=pdf, page_count=out.page_count, issues=issues)
        finally:
            out.close()

    # -- internals -----------------------------------------------------------

    def _render_page(
        self,
        out: fitz.Document,
        plan: RenderPlan,
        instance: PageInstance,
        issues: list[RenderIssue],
        jumps: list[tuple[int, fitz.Rect, int]],
    ) -> None:
        src = plan.background[instance.template_page_index]
        page = out.new_page(width=src.rect.width, height=src.rect.height)
        page.show_pdf_page(page.rect, plan.background, instance.template_page_index)

        scale = (
            page.rect.height / plan.design_page_height
            if plan.design_page_height
            else 1.0
        )
        specs = plan.fields_for(instance.template_page_index)
        shifts = self._row_shifts(page, specs, instance)
        for spec in specs:
            self._render_field(
                page, plan, instance, spec, scale, issues, jumps,
                shift=shifts.get(spec.key, 0.0),
            )

        # A composed table page carries its rows in ``__rows__``. If the template
        # defines no table field to draw them, the page comes out as bare artwork
        # -- correct-looking but empty. That must not pass silently.
        rows = instance.values.get("__rows__")
        if rows:
            capacity = sum(
                s.table.rows
                for s in specs
                if s.type is FieldType.TABLE and s.table is not None
            )
            if capacity < len(rows):
                issues.append(
                    RenderIssue(
                        None,
                        None,
                        messages.TABLE_NOT_RENDERED.format(
                            rows=len(rows) - capacity
                        ),
                        "warning",
                    )
                )

    def _will_draw(self, instance: PageInstance, spec: FieldSpec) -> bool:
        """Whether this field puts anything on the page at all.

        A value, or the wording a caption prints around one, or the fact it
        falls back to. Asked before anything is drawn, because a row cannot
        know where to centre until it knows which of its members are in it.

        Kept in step with ``_render_field`` case by case, deliberately: this
        decides whether a field's own mark is drawn, so the two answering
        differently would print a mark over nothing, or leave one off a value
        that is there. Only text takes the caption path there, so only text
        takes it here.
        """
        raw = instance.values.get(spec.key)
        if spec.type is FieldType.LINK and spec.part is not None:
            # A chip cut off the artwork is drawn where the booklet puts it,
            # and nowhere else. «معلومات الإيجار» leads to that property's بيان
            # عقود الإيجار — «يتم استخدام الصفحة في حال وجود عقود إيجارية
            # للأصل» — so the booklet placing that page is the whole of what
            # decides it. The address is a value on the property and outlives
            # the page being switched off: honoured as a value, it would print
            # the chip back onto a booklet the build had cut it out of.
            return instance.values.get(f"{GOTO_PREFIX}{spec.key}") is not None
        value = "" if raw is None else str(raw).strip()
        if value:
            return True
        if spec.type is FieldType.LINK:
            return instance.values.get(f"{GOTO_PREFIX}{spec.key}") is not None
        if spec.type is not FieldType.TEXT:
            return False
        booklet = instance.values.get(DEFAULTS_KEY) or {}
        return bool(_caption(spec, "", booklet).strip())

    def _extent(self, page: fitz.Page, spec: FieldSpec) -> fitz.Rect:
        """The room this field takes on the page: its box and its own mark."""
        box = spec.rect.to_points(page.rect)
        for path in spec.ornament:
            xs = [
                page.rect.x0 + x * page.rect.width
                for item in path.items
                for x in item.points[::2]
            ]
            ys = [
                page.rect.y0 + y * page.rect.height
                for item in path.items
                for y in item.points[1::2]
            ]
            if xs and ys:
                # By hand, not by unioning point-rects: a rect with no width is
                # empty, and ``Rect.__or__`` ignores an empty rect.
                box = fitz.Rect(
                    min(box.x0, *xs), min(box.y0, *ys),
                    max(box.x1, *xs), max(box.y1, *ys),
                )
        return box

    def _row_shifts(
        self,
        page: fitz.Page,
        specs: list[FieldSpec],
        instance: PageInstance,
    ) -> dict[str, float]:
        """How far each member of a centred row moves to close the gaps.

        معلومات التواصل draws two telephone numbers side by side and centres
        the pair on the page. A seller with no WhatsApp leaves one of them
        empty, and the other stayed where it was — off to one side of a space
        drawn for two, which is «رقم التواصل align center» not happening.

        The row keeps the centre the designer gave it: the shift is measured
        between the middle of everything the row was drawn with and the middle
        of what is left. A full row therefore moves not at all, which is what
        makes this safe to apply to every booklet.
        """
        groups: dict[str, list[FieldSpec]] = {}
        for spec in specs:
            if spec.row_group:
                groups.setdefault(spec.row_group, []).append(spec)

        shifts: dict[str, float] = {}
        for members in groups.values():
            drawing = [s for s in members if self._will_draw(instance, s)]
            if not drawing or len(drawing) == len(members):
                continue
            whole = [self._extent(page, s) for s in members]
            live = [self._extent(page, s) for s in drawing]
            drawn_centre = (
                min(b.x0 for b in whole) + max(b.x1 for b in whole)
            ) / 2
            live_centre = (
                min(b.x0 for b in live) + max(b.x1 for b in live)
            ) / 2
            for spec in drawing:
                shifts[spec.key] = drawn_centre - live_centre
        return shifts

    def _draw_ornament(self, page: fitz.Page, spec: FieldSpec, shift: float) -> None:
        """Put the designer's own mark back beside the value it belongs to.

        Lifted off the artwork at build time so that it can be absent; drawn
        here from the segments and the ink the file stated, so a booklet that
        has both numbers is the page the designer drew.
        """
        if not spec.ornament:
            return
        shape = page.new_shape()
        for path in spec.ornament:
            for item in path.items:
                run = [
                    fitz.Point(
                        page.rect.x0 + x * page.rect.width + shift,
                        page.rect.y0 + y * page.rect.height,
                    )
                    for x, y in zip(
                        item.points[::2], item.points[1::2], strict=True
                    )
                ]
                if item.kind == "c" and len(run) == 4:
                    shape.draw_bezier(*run)
                else:
                    for start, end in pairwise(run):
                        shape.draw_line(start, end)
            # ``None`` is not black: it is how a shape says it is filled but
            # not stroked, or stroked but not filled.
            shape.finish(
                color=tuple(path.stroke) if path.stroke else None,
                fill=tuple(path.fill) if path.fill else None,
                width=path.width,
                closePath=path.closed,
            )
        shape.commit()

    def _render_field(
        self,
        page: fitz.Page,
        plan: RenderPlan,
        instance: PageInstance,
        spec: FieldSpec,
        scale: float,
        issues: list[RenderIssue],
        jumps: list[tuple[int, fitz.Rect, int]],
        shift: float = 0.0,
    ) -> None:
        row = instance.record_index
        rect = spec.rect.to_points(page.rect) + (shift, 0, shift, 0)
        drawing = self._will_draw(instance, spec)
        if spec.ornament and drawing:
            self._draw_ornament(page, spec, shift)
        # The chip this field is printed as, where the build cut it off the
        # artwork so that it could be absent. «معلومات الإيجار» leads to a page
        # the booklet only sometimes contains, and a chip leading to a page
        # that is not there is worse than no chip.
        if spec.part is not None:
            if not drawing:
                # Nothing at all, not merely no cutting. The address behind
                # «معلومات الإيجار» is a value on the property and outlives its
                # lease page being switched off, so a booklet the build cut the
                # chip out of would otherwise carry a click target over the
                # blank the cutting left. ``_will_draw`` is the whole of the
                # decision, on both sides of it.
                return
            page.show_pdf_page(
                spec.part.rect.to_points(page.rect) + (shift, 0, shift, 0),
                plan.background,
                spec.part.page,
            )

        # A mark drawn at whatever size this page wants it. Only a mark: a
        # photograph fills the frame the designer drew, and the frame is not
        # the client's to resize.
        if spec.type is FieldType.IMAGE and spec.preserve_aspect:
            setting = instance.values.get(
                f"{SIZE_PREFIX}{spec.page_index}_{spec.key}"
            )
            if setting:
                rect = _resized(rect, str(setting))

        if spec.type is FieldType.TABLE:
            self._draw_table(page, plan, instance, spec, scale, issues)
            return

        raw = instance.values.get(spec.key)
        value = "" if raw is None else str(raw).strip()

        if spec.type is FieldType.TEXT and (
            spec.prefix or spec.suffix or spec.default_value
        ):
            booklet = instance.values.get(DEFAULTS_KEY) or {}
            text = _caption(spec, value, booklet)
            if text.strip():
                self._draw_text(page, spec, rect, text, scale, row, issues)
            return

        if not value:
            # A link that leads inside the document needs no address to lead to.
            if (
                spec.type is FieldType.LINK
                and instance.values.get(f"{GOTO_PREFIX}{spec.key}") is not None
            ):
                self._draw_link(
                    page, instance, spec, rect, value, row, issues, jumps
                )
                return
            if spec.is_required:
                template = (
                    messages.IMAGE_MISSING
                    if spec.type is FieldType.IMAGE
                    else messages.REQUIRED_EMPTY
                )
                issues.append(
                    RenderIssue(
                        row, spec.key, template.format(label=_label(spec)), "error"
                    )
                )
            return

        if spec.type is FieldType.TEXT:
            self._draw_text(page, spec, rect, value, scale, row, issues)
        elif spec.type is FieldType.IMAGE:
            self._draw_image(page, plan, spec, rect, value, row, issues)
        elif spec.type in (FieldType.QR, FieldType.BARCODE):
            self._draw_code(page, spec, rect, value, row, issues)
        elif spec.type is FieldType.LINK:
            self._draw_link(page, instance, spec, rect, value, row, issues, jumps)

    def _draw_text(self, page, spec, rect, value, scale, row, issues) -> None:
        try:
            placement = calibrated_htmlbox(
                page,
                rect,
                value,
                registry=self._registry,
                family=spec.font_family,
                weight=spec.font_weight,
                size_pt=spec.font_size_pt * scale,
                color=spec.color,
                align=spec.align,
                valign=spec.valign,
                line_height=spec.line_height,
                fit=spec.fit,
                min_scale=spec.min_scale,
                rotate=spec.rotation,
                dx=spec.calibration_dx * scale,
                dy=spec.calibration_dy * scale,
                rtl=spec.rtl,
            )
        except FontError as exc:
            issues.append(
                RenderIssue(
                    row,
                    spec.key,
                    messages.FONT_MISSING.format(label=_label(spec), detail=exc),
                    "error",
                )
            )
            return

        if placement.clipped_chars:
            issues.append(
                RenderIssue(
                    row,
                    spec.key,
                    messages.TEXT_CLIPPED.format(
                        label=_label(spec), chars=placement.clipped_chars
                    ),
                )
            )
        elif placement.shrunk:
            issues.append(
                RenderIssue(
                    row,
                    spec.key,
                    messages.TEXT_SHRUNK.format(
                        label=_label(spec), pct=round(placement.scale * 100)
                    ),
                )
            )
        elif placement.overflowed:
            issues.append(
                RenderIssue(
                    row, spec.key, messages.TEXT_OVERFLOW.format(label=_label(spec))
                )
            )

    def _draw_image(self, page, plan, spec, rect, value, row, issues) -> None:
        blob = plan.assets.get(value)
        if blob is None:
            issues.append(
                RenderIssue(
                    row, spec.key, messages.IMAGE_MISSING.format(label=_label(spec))
                )
            )
            return
        try:
            image = prepare(
                blob,
                rect,
                output_dpi=self._image_dpi,
                cover=not spec.preserve_aspect,
                clip=spec.clip,
                holes=spec.clip_holes,
            )
        except Exception as exc:
            issues.append(
                RenderIssue(
                    row,
                    spec.key,
                    messages.IMAGE_UNREADABLE.format(label=_label(spec), detail=exc),
                    "error",
                )
            )
            return

        # A full-bleed photograph is the page's background, not something laid
        # over it. The designer draws the logos, the scrim and the title on top
        # of it, and the bake kept all of that -- so inserting it as an overlay
        # covered the entire design and the cover came out as a bare photograph.
        # A masked backdrop would show the page's own white through the cut
        # rather than the artwork beneath it, so a shaped image is always an
        # overlay. Only the lot frames are shaped, and none of them is one.
        backdrop = _is_backdrop(rect, page.rect) and not image.mask
        page.insert_image(
            rect,
            stream=image.data,
            mask=image.mask,
            keep_proportion=spec.preserve_aspect,
            overlay=not backdrop,
        )
        if image.below_min_dpi:
            issues.append(
                RenderIssue(
                    row,
                    spec.key,
                    messages.IMAGE_LOW_DPI.format(
                        label=_label(spec), dpi=int(image.effective_dpi)
                    ),
                )
            )

    def _draw_code(self, page, spec, rect, value, row, issues) -> None:
        kind = "QR" if spec.type is FieldType.QR else "الباركود"
        try:
            png = (
                qr_png(value, colour=spec.color)
                if spec.type is FieldType.QR
                else barcode_png(value)
            )
        except Exception as exc:
            issues.append(
                RenderIssue(
                    row,
                    spec.key,
                    messages.CODE_FAILED.format(
                        kind=kind, label=_label(spec), detail=exc
                    ),
                    "error",
                )
            )
            return
        page.insert_image(rect, stream=png, keep_proportion=True)

    def _draw_frame(self, page, table, count: int) -> None:
        """Rule the block for the rows it actually has.

        The artwork ships the table ruled for ten because a printed page has to
        be drawn for some number, and the build lifts that ruling off it. Here
        it goes back on, ending at the last row there is: the shapes are the
        designer's own points, so ten rows come out as the artwork always was
        and four come out as the same artwork stopping four rows down.

        Shortening is a translation, never a rebuild. Every point below a
        shape's own middle moves up by the distance between the rule the block
        was drawn to and the rule it now ends on, which keeps the notch and the
        bezier corners of the numbered tab intact -- they are the bottom of the
        shape, not a radius to be inferred.
        """
        frame = table.frame
        if frame is None or not frame.rules:
            return
        if count <= 0:
            # No properties, so no table: a block ruled for a single empty row
            # is still a table that failed to be filled in. The header bar above
            # it is the designer's and stays.
            return

        height = page.rect.height
        last = min(count, len(frame.rules)) - 1
        # Measured from the block's drawn bottom edge rather than from its last
        # rule, because on the lease page those are not the same line: the
        # artwork rules a band below the last row anyone can fill, and a table
        # that stopped shortening at the last rule would keep that band.
        delta = (frame.bottom - frame.rules[last]) * height

        # One shape for the whole frame: every ``commit`` appends a content
        # stream of its own, and eighteen of them for eighteen hairlines is
        # eighteen times the bookkeeping for one drawing.
        shape = page.new_shape()
        for path in frame.paths:
            if path.row is not None and path.row > last:
                continue
            points = [
                (page.rect.x0 + x * page.rect.width, page.rect.y0 + y * height)
                for item in path.items
                for x, y in zip(item.points[::2], item.points[1::2], strict=True)
            ]
            if not points:
                continue
            # Measured on the shape's own extent, so a rule -- whose points all
            # sit at one y -- moves not at all, and only what hangs below the
            # middle of a divider or the tab is drawn up.
            middle = (min(y for _, y in points) + max(y for _, y in points)) / 2
            cursor = 0
            for item in path.items:
                taken = len(item.points) // 2
                run = [
                    fitz.Point(x, y - delta if y > middle else y)
                    for x, y in points[cursor : cursor + taken]
                ]
                cursor += taken
                if item.kind == "c" and len(run) == 4:
                    shape.draw_bezier(*run)
                else:
                    for start, end in pairwise(run):
                        shape.draw_line(start, end)
            # ``None`` is not black: it is how a shape says it is filled but
            # not stroked, or stroked but not filled.
            shape.finish(
                color=tuple(path.stroke) if path.stroke else None,
                fill=tuple(path.fill) if path.fill else None,
                width=path.width,
                closePath=path.closed,
            )
        shape.commit()

    def _draw_table(self, page, plan, instance, spec, scale, issues) -> None:
        """Draw one block of a repeating table.

        The block takes its slice of the page's rows via ``table.row_offset``, so
        a page holding two ten-row blocks fills the first before the second.
        """
        table = spec.table
        if table is None:
            return
        rows = instance.values.get("__rows__") or []
        page_offset = int(instance.values.get("__row_offset__", 0))
        slice_ = rows[table.row_offset : table.row_offset + table.rows]

        # The rules and the tab before the values, so a cell's text sits on top
        # of the line that closes its row, exactly as the designer stacked them.
        self._draw_frame(page, table, len(slice_))

        pitch = table.row_pitch * page.rect.height
        for position, record in enumerate(slice_):
            absolute_row = page_offset + table.row_offset + position
            shift = position * pitch
            for column in table.columns:
                if column.source == "__index__":
                    raw = f"{absolute_row + 1:02d}"
                else:
                    raw = record.get(column.key)
                value = "" if raw is None else str(raw).strip()
                if not value:
                    # A row in this slice is a property that exists, so a cell
                    # with nothing in it is a fact not supplied — and the guide
                    # says what to print: «في حال تعذر وجود معلومة يمكن إضافة
                    # (-) فقط دون حذف العمود». Left blank, a row with three
                    # gaps in it reads as a table that failed to render rather
                    # than as an asset whose deed number nobody has yet. The
                    # column stays either way; it is the cell that says so.
                    value = MISSING_CELL

                cell = column.rect.to_points(page.rect) + (0, shift, 0, shift)
                try:
                    placement = calibrated_htmlbox(
                        page,
                        cell,
                        value,
                        registry=self._registry,
                        family=column.font_family,
                        weight=column.font_weight,
                        size_pt=column.font_size_pt * scale,
                        color=column.color,
                        align=column.align,
                        valign=column.valign,
                        fit=column.fit,
                        rotate=0,
                        rtl=column.rtl,
                    )
                except FontError as exc:
                    issues.append(
                        RenderIssue(
                            absolute_row,
                            column.key,
                            messages.FONT_MISSING.format(
                                label=column.label or column.key, detail=exc
                            ),
                            "error",
                        )
                    )
                    continue
                if placement.clipped_chars:
                    issues.append(
                        RenderIssue(
                            absolute_row,
                            column.key,
                            messages.TEXT_CLIPPED.format(
                                label=column.label or column.key,
                                chars=placement.clipped_chars,
                            ),
                        )
                    )

    def _draw_link(
        self, page, instance, spec, rect, value, row, issues, jumps
    ) -> None:
        """A click target: to a page of this document, or out to an address.

        The lease chip leads to the property's own بيان عقود الإيجار, which is a
        page of the booklet rather than a place on the web. On screen that is a
        jump; on paper it cannot be one, so the printed code keeps carrying the
        permanent address instead. Both come from the same chip.
        """
        inside = instance.values.get(f"{GOTO_PREFIX}{spec.key}")
        if inside is not None:
            jumps.append((page.number, fitz.Rect(rect), int(inside)))
            return
        if not value.lower().startswith(("http://", "https://", "mailto:", "tel:")):
            issues.append(
                RenderIssue(
                    row,
                    spec.key,
                    messages.LINK_INVALID.format(label=_label(spec), value=value[:60]),
                )
            )
            return
        page.insert_link({"kind": fitz.LINK_URI, "from": rect, "uri": value})
