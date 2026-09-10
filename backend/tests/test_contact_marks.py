"""معلومات التواصل: a mark that comes and goes with the number beside it.

The page draws two telephone numbers, each with a mark of its own -- a handset
for رقم التواصل, the WhatsApp bubble for واتساب -- and centres the pair. Only
the numbers were ever fields, so a seller with no WhatsApp printed a WhatsApp
mark standing over nothing, and the number that was given stayed off to one
side of a space drawn for two.

So each mark is lifted off the artwork at build time and drawn again only when
its number is. The check that makes that safe is the same one the table frame
has: with both numbers given, the page must be the page the designer drew.
"""

from __future__ import annotations

import fitz
import pytest

from app.rendering import manifest
from app.rendering.base import PageInstance, RenderPlan
from app.rendering.overlay import PyMuPDFOverlayRenderer

NUMBER = "0555405658"


def marked(template):
    """The two number fields and their page, if this build lifted the marks.

    Found by the row they are in rather than by the page's role: the row is
    what this is about, and a manifest states it on the field itself.
    """
    fields = [f for f in template.fields if f.row_group and f.ornament]
    if len(fields) != 2:
        pytest.skip("the contact marks were not lifted on this build")
    if fields[0].page_index != fields[1].page_index:
        pytest.skip("the row is not on one page")
    return fields[0].page_index, fields


def draw(template, page_index: int, values: dict) -> fitz.Document:
    plan = RenderPlan(
        background=template.background,
        fields=template.fields,
        pages=[PageInstance(page_index, values)],
        design_page_height=template.design_page_height,
    )
    return fitz.open("pdf", PyMuPDFOverlayRenderer().render(plan).pdf)


def ink(page: fitz.Page, box: fitz.Rect) -> list[fitz.Rect]:
    out = []
    for drawing in page.get_drawings():
        rect = fitz.Rect(drawing["rect"])
        rect.normalize()
        if box.contains(rect):
            out.append(rect)
    return out


def extent(page: fitz.Page, box: fitz.Rect) -> fitz.Rect | None:
    """Everything printed inside ``box`` -- marks and numbers together."""
    shapes = ink(page, box)
    words = [
        fitz.Rect(w[:4]) for w in page.get_text("words") if box.intersects(w[:4])
    ]
    boxes = shapes + words
    if not boxes:
        return None
    # By hand: a stroke's rect can be degenerate, and `Rect.__or__` ignores an
    # empty rect.
    return fitz.Rect(
        min(b.x0 for b in boxes), min(b.y0 for b in boxes),
        max(b.x1 for b in boxes), max(b.y1 for b in boxes),
    )


def row_box(template, fields, page_index: int) -> fitz.Rect:
    page_rect = template.background[page_index].rect
    boxes = [f.rect.to_points(page_rect) for f in fields]
    return fitz.Rect(
        min(b.x0 for b in boxes) - 60, min(b.y0 for b in boxes) - 12,
        max(b.x1 for b in boxes) + 60, max(b.y1 for b in boxes) + 12,
    )


def test_a_full_row_is_the_page_the_designer_drew(template_dir):
    """Both numbers given, and the marks land back exactly where they were.

    This is what makes the lifting safe to do to every booklet: the marks are
    the designer's own segments in the ink the file states them in, put back
    where they came from, so a page with nothing missing is unchanged.
    """
    with manifest.load(template_dir) as template:
        index, fields = marked(template)
        box = row_box(template, fields, index)
        want = sorted(
            (round(r.x0, 1), round(r.y0, 1), round(r.x1, 1), round(r.y1, 1))
            for f in fields
            for r in _mark_rects(f, template.background[index].rect)
        )
        with draw(
            template, index, {f.key: NUMBER for f in fields}
        ) as out:
            got = sorted(
                (round(r.x0, 1), round(r.y0, 1), round(r.x1, 1), round(r.y1, 1))
                for r in ink(out[0], box)
            )
    assert got == want, "a full row draws its marks where the artwork had them"


def _mark_rects(field, page_rect: fitz.Rect) -> list[fitz.Rect]:
    out = []
    for path in field.ornament:
        xs = [page_rect.x0 + x * page_rect.width
              for item in path.items for x in item.points[::2]]
        ys = [page_rect.y0 + y * page_rect.height
              for item in path.items for y in item.points[1::2]]
        out.append(fitz.Rect(min(xs), min(ys), max(xs), max(ys)))
    return out


def test_a_mark_goes_when_its_number_does(template_dir):
    """«if واتساب not exist … icon of واتساب disappear»."""
    with manifest.load(template_dir) as template:
        index, fields = marked(template)
        box = row_box(template, fields, index)
        both = len(_mark_rects(fields[0], template.background[index].rect)) + len(
            _mark_rects(fields[1], template.background[index].rect)
        )
        with draw(template, index, {f.key: NUMBER for f in fields}) as out:
            drawn_both = len(ink(out[0], box))
        with draw(template, index, {fields[1].key: NUMBER}) as out:
            drawn_one = len(ink(out[0], box))

    assert drawn_both == both, "both marks print when both numbers are given"
    assert drawn_one < drawn_both, "the missing number takes its mark with it"


def test_what_is_left_of_the_row_centres_on_what_was_drawn(template_dir):
    """«رقم التواصل align center».

    The remaining number keeps the centre the designer gave the pair, rather
    than sitting where it happened to be drawn when there were two of them.
    """
    with manifest.load(template_dir) as template:
        index, fields = marked(template)
        box = row_box(template, fields, index)
        with draw(template, index, {f.key: NUMBER for f in fields}) as out:
            full = extent(out[0], box)
        alone = {}
        for field in fields:
            with draw(template, index, {field.key: NUMBER}) as out:
                alone[field.key] = extent(out[0], box)

    assert full is not None
    middle = (full.x0 + full.x1) / 2
    for key, got in alone.items():
        assert got is not None, f"{key} printed nothing on its own"
        assert (got.x0 + got.x1) / 2 == pytest.approx(middle, abs=1.0), (
            f"{key} alone should sit on the row's own centre"
        )
        assert got.width < full.width, "one chip is narrower than two"
