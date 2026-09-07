"""Propose editable field regions by reading the designer's own file.

The sample export carries exact geometry for every text run: bbox, size, font,
colour and writing direction. Reading it turns what would be hours of manual
coordinate entry into a review step.

**Geometry only.** Illustrator bakes Arabic into presentation forms and emits the
runs out of logical order -- page 3 of the auction booklet extracts as
``07 : 00ًصباحا-ًمساء``. So ``sample_text`` is for the admin to *recognise* a
region, never to populate a label or a default value.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import fitz

from .base import FieldType, NormRect
from .shaping import Align

_SUBSET_PREFIX = re.compile(r"^[A-Z]{6}\+")


def _split_font(raw: str) -> tuple[str, str]:
    """``'NHJZGD+RuaqArabic-Medium'`` -> ``('RuaqArabic', 'Medium')``."""
    name = _SUBSET_PREFIX.sub("", raw or "")
    name = name.replace("MT", "").strip()
    family, _, weight = name.partition("-")
    return family or "RuaqArabic", (weight or "Regular")


def _rotation(direction: tuple[float, float]) -> int:
    dx, dy = round(direction[0]), round(direction[1])
    return {(1, 0): 0, (0, -1): 90, (-1, 0): 180, (0, 1): 270}.get((dx, dy), 0)


def _hex(color: int) -> str:
    return f"#{color & 0xFFFFFF:06X}"


@dataclass
class DerivedField:
    """A candidate region. The admin decides whether it is variable or static."""

    page_index: int
    rect: NormRect
    rect_pt: fitz.Rect
    type: FieldType
    sample_text: str          # for recognition ONLY -- never a label
    font_family: str = "RuaqArabic"
    font_weight: str = "Medium"
    font_size_pt: float = 10.0
    color: str = "#000000"
    rotation: int = 0
    align: Align = Align.RIGHT
    line_count: int = 1
    lines_pt: list[fitz.Rect] = field(default_factory=list)
    src_width: int = 0   # source pixels, images only
    src_height: int = 0

    @property
    def src_pixels(self) -> int:
        return self.src_width * self.src_height

    @property
    def suggested_key(self) -> str:
        """A stable placeholder key. The admin renames it in the editor."""
        return f"p{self.page_index}_{self.type.value}_{int(self.rect_pt.y0)}_{int(self.rect_pt.x1)}"


def _infer_align(rect: fitz.Rect, siblings: list[fitz.Rect], tol: float = 1.0) -> Align:
    """Right-aligned if its right edge lines up with other runs, and so on.

    Arabic layout defaults to RIGHT, so that is the tie-break.
    """
    right = sum(1 for s in siblings if abs(s.x1 - rect.x1) <= tol)
    left = sum(1 for s in siblings if abs(s.x0 - rect.x0) <= tol)
    if left > right:
        return Align.LEFT
    return Align.RIGHT


def derive_page(doc: fitz.Document, page_index: int) -> list[DerivedField]:
    """Candidate fields on one page, text blocks first then image placements."""
    page = doc[page_index]
    page_rect = page.rect
    out: list[DerivedField] = []

    data = page.get_text("dict")
    all_line_rects = [
        fitz.Rect(line["bbox"])
        for block in data["blocks"]
        if block["type"] == 0
        for line in block["lines"]
    ]

    for block in data["blocks"]:
        if block["type"] != 0:
            continue
        spans = [s for ln in block["lines"] for s in ln["spans"] if s["text"].strip()]
        if not spans:
            continue

        bbox: fitz.Rect | None = None
        for ln in block["lines"]:
            for s in ln["spans"]:
                if not s["text"].strip():
                    continue
                r = fitz.Rect(s["bbox"])
                bbox = r if bbox is None else bbox | r
        if bbox is None or bbox.is_empty:
            continue

        biggest = max(spans, key=lambda s: s["size"])
        family, weight = _split_font(biggest["font"])
        first_line = next(
            ln for ln in block["lines"] if any(s["text"].strip() for s in ln["spans"])
        )
        line_rects = [
            fitz.Rect(ln["bbox"])
            for ln in block["lines"]
            if any(s["text"].strip() for s in ln["spans"])
        ]

        out.append(
            DerivedField(
                page_index=page_index,
                rect=NormRect.from_points(bbox, page_rect),
                rect_pt=bbox,
                type=FieldType.TEXT,
                sample_text="".join(s["text"] for s in spans)[:120],
                font_family=family,
                font_weight=weight,
                font_size_pt=round(biggest["size"], 2),
                color=_hex(biggest["color"]),
                rotation=_rotation(first_line["dir"]),
                align=_infer_align(bbox, all_line_rects),
                line_count=len(line_rects),
                lines_pt=line_rects,
            )
        )

    seen_images: set[tuple[int, int, int, int]] = set()
    for info in page.get_image_info(xrefs=True):
        # xref 0 means the "image" is a flattening artifact -- a soft mask or a
        # transparency group Illustrator emitted, not a placed photo. Including
        # them yields phantom full-page candidates on every cover.
        if not info.get("xref"):
            continue
        rect = fitz.Rect(info["bbox"])
        if rect.is_empty or rect.width < 8 or rect.height < 8:
            continue
        clipped = rect & page_rect
        if clipped.is_empty or clipped.get_area() < 400:
            continue
        key = (round(clipped.x0), round(clipped.y0), round(clipped.x1), round(clipped.y1))
        if key in seen_images:
            continue
        seen_images.add(key)
        out.append(
            DerivedField(
                page_index=page_index,
                rect=NormRect.from_points(clipped, page_rect),
                rect_pt=clipped,
                type=FieldType.IMAGE,
                sample_text=f"{info['width']}x{info['height']}px",
                src_width=int(info["width"]),
                src_height=int(info["height"]),
            )
        )

    for link in page.get_links():
        if link.get("kind") != fitz.LINK_URI:
            continue
        rect = fitz.Rect(link["from"])
        out.append(
            DerivedField(
                page_index=page_index,
                rect=NormRect.from_points(rect, page_rect),
                rect_pt=rect,
                type=FieldType.LINK,
                sample_text=str(link.get("uri", ""))[:120],
            )
        )

    out.sort(key=lambda f: (round(f.rect_pt.y0, 1), -f.rect_pt.x1))
    return out


def derive_document(doc: fitz.Document) -> dict[int, list[DerivedField]]:
    return {i: derive_page(doc, i) for i in range(doc.page_count)}
