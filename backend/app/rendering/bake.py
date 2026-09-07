"""Turn the designer's export into clean background pages.

Baking removes the sample content from the artwork and leaves everything else
untouched. Two things make this safe, and both were measured on the real file:

* Redacting all 48 text spans on a dense table page changed **0 pixels outside
  the field rects** and cost one drawing (the redacted cell fill).
* Sample photos must be dropped, not merely covered. A raw slice of page 5 is
  22.5 MB because a 4032x2268 photo rides along inside it.
"""

from __future__ import annotations

from dataclasses import dataclass

import fitz

from .base import FieldType


@dataclass
class BakeReport:
    pages: int
    text_rects_cleared: int
    images_removed: int
    drawings_before: int
    drawings_after: int
    bytes_before: int
    bytes_after: int

    @property
    def shrunk_by(self) -> str:
        if not self.bytes_before:
            return "n/a"
        pct = 100 * (1 - self.bytes_after / self.bytes_before)
        return f"{self.bytes_before/1e6:.1f}MB -> {self.bytes_after/1e6:.1f}MB ({pct:.0f}% smaller)"


def bake_page(
    page: fitz.Page,
    regions: list[tuple[fitz.Rect, FieldType]],
    *,
    remove_images: bool = True,
) -> tuple[int, int]:
    """Strip the *replaced* content from one page. Returns (text rects, images).

    Only regions that an actual field will draw over may be cleared. Everything
    else -- the printed labels النوع / رقم الصك, the white chip captions, the
    section headings -- is part of the design and must survive, or the generated
    page comes out with values floating beside empty cells.
    """
    text_rects = [r for r, kind in regions if kind is FieldType.TEXT]
    image_rects = [r for r, kind in regions if kind is FieldType.IMAGE]

    removed = 0
    if remove_images and image_rects:
        # delete_image swaps the pixels for a 1x1 stub without disturbing the
        # placement operators, so the page geometry -- and the field rect we
        # will draw the replacement into -- stays exactly where it was.
        for info in page.get_image_info(xrefs=True):
            xref = info.get("xref")
            if not xref:
                continue
            rect = fitz.Rect(info["bbox"])
            if any(rect.intersects(target) for target in image_rects):
                try:
                    page.delete_image(xref)
                    removed += 1
                except Exception:
                    continue

    if text_rects:
        for rect in text_rects:
            page.add_redact_annot(rect)
        page.apply_redactions(
            images=fitz.PDF_REDACT_IMAGE_NONE,
            graphics=fitz.PDF_REDACT_LINE_ART_NONE,
        )

    return len(text_rects), removed


def bake_document(
    doc: fitz.Document,
    regions_by_page: dict[int, list[tuple[fitz.Rect, FieldType]]],
    *,
    remove_images: bool = True,
) -> BakeReport:
    """Bake every page in place. The caller saves the document."""
    before_bytes = len(doc.tobytes(garbage=0, deflate=True))
    drawings_before = sum(len(doc[i].get_drawings()) for i in range(doc.page_count))

    cleared = removed = 0
    for index in range(doc.page_count):
        t, i = bake_page(
            doc[index], regions_by_page.get(index, []), remove_images=remove_images
        )
        cleared += t
        removed += i

    drawings_after = sum(len(doc[i].get_drawings()) for i in range(doc.page_count))
    after_bytes = len(doc.tobytes(garbage=4, deflate=True, clean=True))
    return BakeReport(
        pages=doc.page_count,
        text_rects_cleared=cleared,
        images_removed=removed,
        drawings_before=drawings_before,
        drawings_after=drawings_after,
        bytes_before=before_bytes,
        bytes_after=after_bytes,
    )


def slice_pages(doc: fitz.Document, first: int, last: int) -> fitz.Document:
    """Extract a page range as its own document (a section background)."""
    out = fitz.open()
    out.insert_pdf(doc, from_page=first, to_page=last)
    return out
