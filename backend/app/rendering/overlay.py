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

#: The booklet's own facts, for a field whose ``default_value`` names one --
#: the auction and the platform are typed on the auction-info page and belong
#: to the whole issue, not to the page that happens to print them again. Kept
#: under a reserved key rather than merged into the values so that nothing
#: starts printing merely because the booklet knows it. See ``compose``.
DEFAULTS_KEY = "__booklet__"

_SLOT = re.compile(r"\{([a-z0-9_]+)\}")


def _resolve(template: str, booklet: dict) -> str:
    """Fill ``{key}`` from the booklet's own facts; an unknown key empties."""
    if not template:
        return ""
    return _SLOT.sub(lambda m: str(booklet.get(m.group(1)) or "").strip(), template)


def _caption(spec: FieldSpec, value: str, booklet: dict) -> str:
    """What this field actually prints: fixed wording around a typed value.

    The value falls back to ``default_value`` -- which is the point of the
    steps page: nothing typed there still prints the guide's sentence with the
    auction's own name in it, and typing replaces only the name.
    """
    inner = value or _resolve(spec.default_value, booklet)
    if not spec.prefix and not spec.suffix:
        return inner
    # The fixed halves print even with nothing between them. A caption that
    # vanished because its one variable word was blank would take the
    # designer's sentence with it, and the page was cleared to make room for it.
    return f"{spec.prefix}{inner}{spec.suffix}"


def _is_backdrop(rect: fitz.Rect, page_rect: fitz.Rect) -> bool:
    area = page_rect.get_area()
    return bool(area) and (rect & page_rect).get_area() / area >= BACKDROP_COVERAGE


class PyMuPDFOverlayRenderer:
    """Composites values onto baked background pages."""

    def __init__(self, registry: FontRegistry | None = None) -> None:
        self._registry = registry or brand_registry()

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
        for spec in specs:
            self._render_field(page, plan, instance, spec, scale, issues, jumps)

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

    def _render_field(
        self,
        page: fitz.Page,
        plan: RenderPlan,
        instance: PageInstance,
        spec: FieldSpec,
        scale: float,
        issues: list[RenderIssue],
        jumps: list[tuple[int, fitz.Rect, int]],
    ) -> None:
        row = instance.record_index
        rect = spec.rect.to_points(page.rect)

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
                    continue

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
