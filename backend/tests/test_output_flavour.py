"""What changes when a booklet is read on a screen instead of printed.

Three things, and the designer drew all three rather than leaving them to be
invented:

* the lot pages are drawn twice -- «تفاصيل العقار (نسخة الطباعة)» with a code
  under every chip and the chips in a 2x2 block, and «(نسخة إلكترونية)» with no
  codes and the chips in a single column (guide pages 14, 18 and 19);
* «معلومات الإيجار» leads to a page the booklet only sometimes has, so the chip
  is cut off the artwork and put back only when that page is in the booklet;
* معلومات التواصل on an electronic auction names no venue and prints no code to
  one, because an electronic auction is held nowhere (guide page 24).
"""

from __future__ import annotations

from itertools import pairwise
from pathlib import Path

import fitz
import pytest

from app.rendering import manifest
from app.rendering.base import FieldType, PageInstance, RenderPlan
from app.rendering.overlay import GOTO_PREFIX, PyMuPDFOverlayRenderer
from app.services.templates import ELECTRONIC, PRINT, for_output
from tests.conftest import BACKEND

SLUGS = (
    "auction_infath_inperson",
    "auction_infath_hybrid",
    "auction_infath_electronic",
)
LEASE_KEY = "link_lease"


def built(slug: str) -> Path:
    path = BACKEND / "var" / "templates" / slug
    if not (path / "template.json").exists():
        pytest.skip(f"{slug} not built; run scripts/build_infath_templates.py")
    return path


@pytest.fixture(params=SLUGS)
def template(request):
    with manifest.load(built(request.param)) as loaded:
        loaded.slug = request.param
        yield loaded


def lot_pages(template) -> dict[int, int]:
    swap = template.pages_for(ELECTRONIC)
    if not swap:
        pytest.skip("this build has no screen drawings")
    return swap


def chips(template, page_index: int, kind: FieldType) -> list:
    return [
        f for f in template.fields
        if f.page_index == page_index and f.type is kind
    ]


def draw(template, page_index: int, flavour: str, values: dict) -> fitz.Document:
    plan = RenderPlan(
        background=template.background,
        fields=for_output(template.fields, flavour),
        pages=[PageInstance(page_index, values)],
        design_page_height=template.design_page_height,
    )
    return fitz.open("pdf", PyMuPDFOverlayRenderer().render(plan).pdf)


# --------------------------------------------------------------------------
# The two drawings of a lot page


def test_the_printed_lot_page_keeps_its_block_of_codes(template):
    """«نسخة الطباعة»: four chips in two rows, each with a code under it."""
    for printed in lot_pages(template):
        codes = chips(template, printed, FieldType.QR)
        links = chips(template, printed, FieldType.LINK)
        assert len(links) == 4, f"page {printed} draws four chips"
        # And a code under every one of them, which is what the designer drew.
        # «معلومات الإيجار» leads inside the booklet as well, and on screen that
        # is where it goes -- but a printed code cannot jump to a page, so on
        # paper it carries the address the client gave for the leases.
        assert len(codes) == 4, f"page {printed} prints four codes"
        rows = sorted({round(f.rect.y, 2) for f in links})
        columns = sorted({round(f.rect.x, 2) for f in links})
        assert len(rows) == 2 and len(columns) == 2, (
            f"page {printed} is a 2x2 block, got {len(columns)}x{len(rows)}"
        )


def test_the_screen_lot_page_stacks_its_chips_and_prints_no_code(template):
    """«نسخة إلكترونية»: one column, one chip a row, and nothing to scan."""
    for printed, screen in lot_pages(template).items():
        links = chips(template, screen, FieldType.LINK)
        assert not chips(template, screen, FieldType.QR), (
            f"page {screen} is read on a screen and needs no codes"
        )
        assert len(links) >= 3, f"page {screen} draws its chips"
        left = {round(f.rect.x, 3) for f in links}
        assert len(left) == 1, f"one column, got left edges {sorted(left)}"
        widths = {round(f.rect.w, 3) for f in links}
        assert len(widths) == 1, f"one width, got {sorted(widths)}"
        rows = sorted(round(f.rect.y, 4) for f in links)
        assert len(rows) == len(links), "one chip a row"
        steps = [b - a for a, b in pairwise(rows)]
        assert max(steps) - min(steps) < 0.004, (
            f"evenly spaced, got steps {[round(s, 4) for s in steps]}"
        )
        assert printed != screen


def test_the_two_drawings_agree_about_everything_else(template):
    """Only the chips move. A page swapped at render time must otherwise be
    the same page, or the boxes beside it in the builder point at nothing.

    Exactly the same, not mostly: the build refuses a twin that asks for
    anything the printed page does not, so anything short of equality here is
    a twin that got past the guard by asking for less.
    """
    for printed, screen in lot_pages(template).items():
        def named(page: int) -> set[str]:
            return {
                f.key for f in template.fields
                if f.page_index == page
                and f.type is FieldType.TEXT
                and not f.key.startswith("__")
            }
        assert named(printed) == named(screen), (
            f"pages {printed} and {screen} must ask for exactly the same "
            f"values: only the printed one asks for "
            f"{sorted(named(printed) - named(screen))}, only the screen one "
            f"for {sorted(named(screen) - named(printed))}"
        )


def test_only_the_lot_pages_are_drawn_twice(template):
    """A cover, a table or the contact page has one drawing, not two."""
    swap = lot_pages(template)
    lot = {
        f.page_index for f in template.fields
        if f.key in {"link_survey", "link_photos"}
    }
    assert set(swap) <= lot, f"non-lot pages were twinned: {set(swap) - lot}"


# --------------------------------------------------------------------------
# The chip that is not always there


def lease_fields(template) -> list:
    found = [f for f in template.fields if f.key == LEASE_KEY and f.part]
    if not found:
        pytest.skip("this build cut out no lease chip")
    return found


def ink(page: fitz.Page, box: fitz.Rect) -> int:
    """How many pixels inside ``box`` are not the page's ground."""
    pix = page.get_pixmap(dpi=150, clip=box)
    corner = pix.pixel(0, 0)
    return sum(
        1
        for y in range(pix.height)
        for x in range(pix.width)
        if pix.pixel(x, y) != corner
    )


def test_the_lease_chip_leaves_nothing_behind_when_its_page_is_off(template):
    """«box, icon, caption, and link. No visual residue.»"""
    for field in lease_fields(template):
        box = field.part.rect.to_points(template.background[0].rect)
        with draw(template, field.page_index, PRINT, {}) as out:
            gone = ink(out[0], box)
        with draw(
            template, field.page_index, PRINT, {f"{GOTO_PREFIX}{LEASE_KEY}": 1}
        ) as out:
            shown = ink(out[0], box)
        assert gone == 0, (
            f"page {field.page_index}: {gone} pixels of the lease chip are "
            f"still printed with its page switched off"
        )
        assert shown > 0, "and the chip is there when its page is"


def test_a_lease_chip_that_is_drawn_is_the_designers_own(template):
    """Put back, it has to be the artwork it was cut out of.

    The chip is a bar, a caption reversed out of it and an arrow beside it --
    a raster, some type and a piece of line art. Nothing redraws those; the
    cutting is placed back whole, and this is what says so.
    """
    source = fitz.open(built(template.slug) / "source.pdf")
    try:
        for field in lease_fields(template):
            box = field.part.rect.to_points(template.background[0].rect)
            want = source[field.page_index].get_pixmap(dpi=200, clip=box)
            with draw(
                template, field.page_index, PRINT,
                {f"{GOTO_PREFIX}{LEASE_KEY}": 1},
            ) as out:
                got = out[0].get_pixmap(dpi=200, clip=box)
            assert len(want.samples) == len(got.samples)
            worst = max(
                abs(a - b) for a, b in zip(want.samples, got.samples, strict=True)
            )
            assert worst <= 2, (
                f"page {field.page_index}: the chip came back {worst}/255 off "
                f"the artwork it replaced"
            )
    finally:
        source.close()


def test_a_booklet_with_no_lease_page_prints_no_chip_to_one(template):
    """The chip goes where its page goes, including all the way away.

    A project built without a page plan is composed from the template's
    sections, and no section holds بيان عقود الإيجار -- there is nowhere for
    the chip to lead and no way to switch one on. It is drawn on none of
    those booklets, which is «معلومات الايجار exist if fill it page» read the
    only way it can be read when the page can never be filled: a bar captioned
    «معلومات الإيجار» with an arrow beside it, in a booklet that does not
    contain the page, is a promise the paper cannot keep.

    Pinned because the chip used to be baked into the artwork and printed on
    every property whatever the booklet held. Cutting it out is what made this
    a decision rather than a fact about the file.
    """
    from app.rendering.compose import GOTO_PREFIX as COMPOSE_GOTO
    from app.rendering.compose import RENT_LINK_KEY, compose

    lease_at = {f.page_index for f in lease_fields(template)}
    pages = compose(template.sections, [{"deed_number": "1"}])
    assert pages, "the sections compose something"
    assert not any(
        page.template_page_index in lease_at for page in pages
        if f"{COMPOSE_GOTO}{RENT_LINK_KEY}" in page.values
    ), "nothing on this path knows where a lease page would be"
    for page in pages:
        if page.template_page_index not in lease_at:
            continue
        with draw(template, page.template_page_index, PRINT, page.values) as out:
            field = next(
                f for f in lease_fields(template)
                if f.page_index == page.template_page_index
            )
            box = field.part.rect.to_points(template.background[0].rect)
            assert ink(out[0], box) == 0, (
                f"page {page.template_page_index}: a chip leading to a page "
                f"this booklet does not contain"
            )


def test_the_lease_chip_survives_being_printed(template):
    """It is a LINK with no code, and paper drops LINKs -- except this one.

    Dropped, nothing would know the chip existed, and a printed booklet would
    carry the gap where the build cut it out.
    """
    for field in lease_fields(template):
        kept = {
            f.key for f in for_output(template.fields, PRINT)
            if f.page_index == field.page_index
        }
        assert LEASE_KEY in kept
        assert "link_survey" not in kept, "a chip with a code still drops its link"


# --------------------------------------------------------------------------
# معلومات التواصل on an auction held nowhere


def contact_page(template) -> int | None:
    pages = {
        f.page_index for f in template.fields if f.key == "contact_whatsapp"
    }
    return min(pages) if pages else None


def test_an_electronic_auction_names_no_venue(template):
    """Guide page 24: التاريخ، اسم المنصة، الوقت, two numbers, no قاعة المزاد."""
    page = contact_page(template)
    if page is None:
        pytest.skip("no contact page")
    keys = {f.key for f in template.fields if f.page_index == page}
    if template.slug != "auction_infath_electronic":
        assert "location" in keys, "a hybrid or in-person auction is held somewhere"
        assert "venue_link" in keys, "and prints a code to it"
        return
    assert "location" not in keys, "an electronic auction is held nowhere"
    assert "venue_link" not in keys and "__qr_venue_link" not in keys, (
        "and has no قاعة المزاد block"
    )
    assert {"platform_name", "auction_date", "auction_time"} <= keys, (
        "the guide's electronic card names the platform, the date and the time"
    )
    assert {"contact_phone", "contact_whatsapp"} <= keys, "and two numbers"
