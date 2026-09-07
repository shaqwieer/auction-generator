"""Arabic-correct text placement onto a PDF page.

Everything here exists because of two measured facts:

* Shaping must come from OpenType GSUB. ``arabic-reshaper`` produces presentation
  forms (U+FExx) that the client's brand fonts do not map, yielding NUL glyphs.
  MuPDF's Story engine (HarfBuzz + FriBidi), reached through ``insert_htmlbox``,
  shapes and reorders correctly.
* ``insert_htmlbox`` does not honour the box origin. Measured errors on the real
  artwork were -14.3pt for a number and -157.9pt for a sentence. Rendering once
  to measure, then shifting the box by the observed delta, lands on target to
  +/-0.00pt -- and stays exact even when the text has been shrunk to fit.

Callers should always use :func:`calibrated_htmlbox`, never ``insert_htmlbox``.
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from enum import StrEnum

import fitz

from .fonts import FontError, FontRegistry


class Align(StrEnum):
    RIGHT = "right"
    LEFT = "left"
    CENTER = "center"


class Fit(StrEnum):
    SHRINK = "shrink"  # scale the text down until it fits
    CLIP = "clip"      # keep the size, drop what does not fit
    WRAP = "wrap"      # keep the size, let the box grow downward


class VAlign(StrEnum):
    """Which vertical edge of the target rect the glyphs are pinned to.

    ``BOTTOM`` is the default because the common case is replacing a single-line
    value whose target rect *is* the original span's bbox -- pinning the bottom
    keeps the new text on the old baseline. Wrapping text pins ``TOP`` instead,
    so extra lines grow downward rather than pushing the first line up.
    """

    TOP = "top"
    BOTTOM = "bottom"
    CENTER = "center"


@dataclass(frozen=True)
class Placement:
    """What actually happened when a field was drawn."""

    box: fitz.Rect        # the box used after calibration
    bbox: fitz.Rect | None  # bounding box of the rendered glyphs
    scale: float          # < 1.0 means the text was shrunk to fit
    overflowed: bool      # True if it still did not fit
    empty: bool           # True if there was nothing to draw
    clipped_chars: int = 0  # characters dropped when fit=CLIP

    @property
    def shrunk(self) -> bool:
        return self.scale < 0.999


#: A line no longer than this that ends in a colon is a heading, not a sentence
#: that happens to end in one. The guide's own معلومات إضافية page is written
#: this way -- «مميزات العقار:» over its points, «الملاحظات:» over theirs.
HEADING_MAX = 48


def _as_html(value: str, bold_family: str | None = None) -> str:
    """One field's value as the markup that prints it.

    Two things HTML would not do on its own. A newline is whitespace to an HTML
    engine, so a value typed as several lines came out as one paragraph; and a
    heading is a heading -- the page is a list of points under titles, and the
    titles have to look like titles.

    ``<b>`` is not enough for that: each weight of the brand font is registered
    as its own family, so there is nothing for a browser's idea of bold to
    switch *to*. The heading names the bold face instead.
    """
    out: list[str] = []
    for line in value.splitlines():
        stripped = line.strip()
        escaped = html.escape(line)
        if bold_family and stripped.endswith(":") and len(stripped) <= HEADING_MAX:
            out.append(f'<span style="font-family:{bold_family}">{escaped}</span>')
        else:
            out.append(escaped)
    return "<br>".join(out)


def _css_block(
    *,
    registry: FontRegistry,
    family: str,
    weight: str,
    size_pt: float,
    color: str,
    align: Align,
    line_height: float,
) -> tuple[str, str]:
    """Return (css, inline_style) for one text field."""
    face = registry.face(family, weight)
    style = (
        f"text-align:{align.value};"
        f"font-family:{face.css_family};"
        f"font-size:{size_pt}px;"
        f"color:{color};"
        f"line-height:{line_height};"
    )
    return registry.css(), style


def _measure(
    page_rect: fitz.Rect,
    box: fitz.Rect,
    markup: str,
    css: str,
    archive: fitz.Archive,
    *,
    scale_low: float,
    rotate: int,
) -> tuple[fitz.Rect | None, float, float]:
    """Render into a scratch page and report (glyph bbox, scale, spare height)."""
    doc = fitz.open()
    try:
        page = doc.new_page(width=page_rect.width, height=page_rect.height)
        spare, scale = page.insert_htmlbox(
            box, markup, css=css, archive=archive, scale_low=scale_low, rotate=rotate
        )
        bbox: fitz.Rect | None = None
        for block in page.get_text("dict")["blocks"]:
            if block["type"] != 0:
                continue
            for line in block["lines"]:
                for span in line["spans"]:
                    if not span["text"].strip():
                        continue
                    r = fitz.Rect(span["bbox"])
                    bbox = r if bbox is None else bbox | r
        return bbox, scale, spare
    finally:
        doc.close()


def _delta(
    target: fitz.Rect, got: fitz.Rect, align: Align, valign: VAlign, rotate: int
) -> tuple[float, float]:
    """Offset that moves the rendered glyphs onto the target rect.

    For upright text we anchor on the edge the alignment implies and on the
    bottom of the glyph box. Rotated text (the ``الحدود`` / ``الأطوال`` labels in
    the auction booklet) is short and centred in its cell, so matching centres is
    both simpler and visually correct there.
    """
    if rotate % 360 != 0:
        return (
            (target.x0 + target.x1) / 2 - (got.x0 + got.x1) / 2,
            (target.y0 + target.y1) / 2 - (got.y0 + got.y1) / 2,
        )
    if align is Align.RIGHT:
        dx = target.x1 - got.x1
    elif align is Align.LEFT:
        dx = target.x0 - got.x0
    else:
        dx = (target.x0 + target.x1) / 2 - (got.x0 + got.x1) / 2

    if valign is VAlign.TOP:
        dy = target.y0 - got.y0
    elif valign is VAlign.CENTER:
        dy = (target.y0 + target.y1) / 2 - (got.y0 + got.y1) / 2
    else:
        dy = target.y1 - got.y1
    return dx, dy


def _longest_fitting(
    probe, text: str, *, max_len: int
) -> tuple[str, int]:
    """Largest prefix of ``text`` that ``probe`` can render, and chars dropped.

    ``insert_htmlbox`` draws *nothing* when the story does not fit and scaling is
    disallowed, so ``fit=CLIP`` has to find the cut point itself.
    """
    if probe(text) is not None:
        return text, 0
    lo, hi = 0, max_len
    best = ""
    while lo <= hi:
        mid = (lo + hi) // 2
        candidate = text[:mid].rstrip()
        if candidate and probe(candidate) is not None:
            best = candidate
            lo = mid + 1
        else:
            hi = mid - 1
    return best, len(text) - len(best)


def calibrated_htmlbox(
    page: fitz.Page,
    rect: fitz.Rect,
    text: str,
    *,
    registry: FontRegistry,
    family: str = "RuaqArabic",
    weight: str = "Medium",
    size_pt: float = 10.0,
    color: str = "#000000",
    align: Align = Align.RIGHT,
    valign: VAlign | None = None,
    line_height: float = 1.0,
    fit: Fit = Fit.SHRINK,
    min_scale: float = 0.5,
    rotate: int = 0,
    dx: float = 0.0,
    dy: float = 0.0,
    rtl: bool = True,
) -> Placement:
    """Draw ``text`` so its glyphs land on ``rect``.

    ``dx``/``dy`` are an optional manual nudge applied on top of the automatic
    calibration, for the rare field a designer wants to tweak by hand.
    """
    if not text or not text.strip():
        return Placement(box=rect, bbox=None, scale=1.0, overflowed=False, empty=True)

    if valign is None:
        valign = VAlign.TOP if fit is Fit.WRAP else VAlign.BOTTOM

    css, style = _css_block(
        registry=registry,
        family=family,
        weight=weight,
        size_pt=size_pt,
        color=color,
        align=align,
        line_height=line_height,
    )
    archive = registry.archive()
    direction = "rtl" if rtl else "ltr"

    try:
        bold_family = registry.face(family, "Bold").css_family
    except FontError:
        bold_family = None

    def markup_for(value: str) -> str:
        return (
            f'<div dir="{direction}" style="{style}">'
            f"{_as_html(value, bold_family)}</div>"
        )

    scale_low = min_scale if fit is Fit.SHRINK else 1.0
    box = fitz.Rect(rect)
    drawn = text
    clipped = 0

    if fit is Fit.WRAP:
        # Let the box grow downward to whatever the text needs.
        probe_box = fitz.Rect(box.x0, box.y0, box.x1, page.rect.height)
        got, _, _ = _measure(
            page.rect, probe_box, markup_for(text), css, archive,
            scale_low=1.0, rotate=rotate,
        )
        if got is not None and got.height > box.height:
            box = fitz.Rect(box.x0, box.y0, box.x1, box.y0 + got.height)

    def probe(value: str):
        got, _, _ = _measure(
            page.rect, box, markup_for(value), css, archive,
            scale_low=scale_low, rotate=rotate,
        )
        return got

    if fit is Fit.CLIP:
        drawn, clipped = _longest_fitting(probe, text, max_len=len(text))
        if not drawn:
            return Placement(
                box=box, bbox=None, scale=1.0, overflowed=True, empty=True,
                clipped_chars=len(text),
            )

    # Pass 1 -- measure where MuPDF actually puts the glyphs.
    got, scale, spare = _measure(
        page.rect, box, markup_for(drawn), css, archive,
        scale_low=scale_low, rotate=rotate,
    )
    if got is None:
        # Even the smallest allowed scale could not fit it. Fall back to clipping
        # so the page shows *something* and the caller can warn.
        scale_low = min_scale
        drawn, clipped = _longest_fitting(probe, text, max_len=len(text))
        if not drawn:
            return Placement(
                box=box, bbox=None, scale=1.0, overflowed=True, empty=True,
                clipped_chars=len(text),
            )
        got, scale, spare = _measure(
            page.rect, box, markup_for(drawn), css, archive,
            scale_low=scale_low, rotate=rotate,
        )
        if got is None:
            return Placement(
                box=box, bbox=None, scale=1.0, overflowed=True, empty=True,
                clipped_chars=len(text),
            )

    # Pass 2 -- shift the box by the observed error and draw for real.
    ddx, ddy = _delta(box, got, align, valign, rotate)
    final_box = box + (ddx + dx, ddy + dy, ddx + dx, ddy + dy)
    spare, scale = page.insert_htmlbox(
        final_box, markup_for(drawn), css=css, archive=archive,
        scale_low=scale_low, rotate=rotate,
    )

    bbox: fitz.Rect | None = None
    for block in page.get_text("dict")["blocks"]:
        if block["type"] != 0:
            continue
        for line in block["lines"]:
            for span in line["spans"]:
                if not span["text"].strip():
                    continue
                r = fitz.Rect(span["bbox"])
                if r.intersects(final_box + (-4, -4, 4, 4)):
                    bbox = r if bbox is None else bbox | r

    return Placement(
        box=final_box,
        bbox=bbox,
        scale=scale,
        overflowed=spare < 0 or clipped > 0,
        empty=False,
        clipped_chars=clipped,
    )
