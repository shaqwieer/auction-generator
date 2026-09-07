"""Photographs take the shape of the frame the designer drew.

A frame here is not a rectangle. The قياسي page cuts a corner out of it for the
property number; the برج page cuts two; the صور إضافية page cuts one on each of
its three. A photograph placed in the bounding box printed a square corner
straight over the badge.
"""

from __future__ import annotations

import io

import fitz
import pytest
from PIL import Image

from app.rendering import manifest
from app.rendering.base import PageInstance, RenderPlan
from app.rendering.images import prepare
from app.rendering.overlay import PyMuPDFOverlayRenderer

SHAPED_KEYS = {"main_photo", "extra_photo_1", "extra_photo_2", "extra_photo_3"}


def photo(size: tuple[int, int] = (1600, 1000)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, (210, 70, 40)).save(buf, format="JPEG", quality=90)
    return buf.getvalue()


@pytest.fixture(scope="module")
def template(template_dir):
    with manifest.load(template_dir) as loaded:
        yield loaded


def test_every_photo_frame_carries_its_shape(template):
    shaped = [
        f
        for f in template.fields
        if f.key in SHAPED_KEYS and f.type.value == "image"
    ]
    assert shaped, "the booklet has photo frames"
    for field in shaped:
        assert len(field.clip) >= 3, f"{field.key} on page {field.page_index}"
        # In its own box, so it moves and scales with the box.
        assert all(0.0 <= x <= 1.0 and 0.0 <= y <= 1.0 for x, y in field.clip)


def test_the_shape_is_the_frame_and_not_what_is_drawn_inside_it(template):
    """The قياسي frame's fill also traces the sample property, floating in it.

    Threading that onto the same polygon punched a hole through every
    photograph, and taking the first piece instead of the largest kept the
    tracing and threw the frame away.
    """
    field = next(
        f for f in template.fields if f.key == "main_photo" and f.clip
    )
    xs = [x for x, _ in field.clip]
    ys = [y for _, y in field.clip]
    assert min(xs) < 0.02 and max(xs) > 0.98, "the shape spans its box"
    assert min(ys) < 0.02 and max(ys) > 0.98


def test_a_masked_photo_stays_a_jpeg_with_a_stencil_beside_it():
    """Not an RGBA PNG.

    The source material is phone photography — 4032x2268 — and a masked RGBA
    page is megabytes where the same page as JPEG plus a one-channel stencil is
    a few hundred kilobytes.
    """
    box = fitz.Rect(0, 0, 400, 200)
    square = prepare(photo(), box)
    assert square.mask is None
    assert square.data[:2] == b"\xff\xd8", "a plain frame stays a plain JPEG"

    cut = prepare(photo(), box, clip=[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0]])
    assert cut.data[:2] == b"\xff\xd8"
    assert cut.mask and cut.mask[:4] == b"\x89PNG"
    with Image.open(io.BytesIO(cut.mask)) as stencil:
        assert stencil.mode == "L"
        assert stencil.size == (cut.width, cut.height)
        # The cut-away half is off, the kept half is on.
        assert stencil.getpixel((5, cut.height - 5)) == 0
        assert stencil.getpixel((cut.width - 5, cut.height - 5)) == 255


def test_the_corner_the_frame_cuts_shows_the_page_not_the_photograph(template):
    """The whole point, measured on the page rather than on the mask."""
    field = next(f for f in template.fields if f.key == "main_photo" and f.clip)
    plan = RenderPlan(
        background=template.background,
        fields=template.fields,
        pages=[
            PageInstance(
                template_page_index=field.page_index,
                values={"main_photo": "p.jpg"},
            )
        ],
        assets={"p.jpg": photo()},
        design_page_height=template.design_page_height,
    )
    result = PyMuPDFOverlayRenderer().render(plan)

    page_box = fitz.Rect(0, 0, *template.page_size)
    box = field.rect.to_points(page_box)

    # Which corner is cut is the shape's own business, so ask it: the corner of
    # the box that the outline comes least close to.
    def gap(corner: tuple[float, float]) -> float:
        return min(
            abs(x - corner[0]) + abs(y - corner[1]) for x, y in field.clip
        )

    corners = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    cut = max(corners, key=gap)
    assert gap(cut) > 0.02, "this frame cuts no corner"

    inset = 3.0
    x = box.x0 + inset if cut[0] < 0.5 else box.x1 - inset
    y = box.y0 + inset if cut[1] < 0.5 else box.y1 - inset
    with fitz.open("pdf", result.pdf) as pdf:
        pixels = pdf[0].get_pixmap(
            clip=fitz.Rect(x - 1, y - 1, x + 1, y + 1), dpi=150
        )
    assert pixels.pixel(1, 1) != (210, 70, 40), (
        "the photograph still overhangs the cut corner"
    )
