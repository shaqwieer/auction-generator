"""Arabic shaping and placement -- the parts that break silently.

Every assertion here corresponds to a measured failure mode on the client's real
fonts and artwork. If one of these regresses, generated booklets look wrong in a
way no unit test of the API layer would catch.
"""

from __future__ import annotations

import fitz
import pytest

from app.rendering.fonts import FontError, brand_registry
from app.rendering.shaping import Align, Fit, VAlign, calibrated_htmlbox
from tests.conftest import ARABIC, LONG_ARABIC, MIXED

PAGE = (595.28, 841.89)
PRESENTATION_FORMS = range(0xFE70, 0xFF00)


def render(text: str, rect: tuple[float, ...], **kwargs):
    """Draw onto a scratch page and hand back (placement, extracted text)."""
    doc = fitz.open()
    page = doc.new_page(width=PAGE[0], height=PAGE[1])
    placement = calibrated_htmlbox(
        page, fitz.Rect(*rect), text, registry=brand_registry(), **kwargs
    )
    reopened = fitz.open("pdf", doc.tobytes())
    extracted = reopened[0].get_text()
    reopened.close()
    doc.close()
    return placement, extracted


# --------------------------------------------------------------------------
# Shaping


def test_arabic_letters_join():
    """MuPDF must apply the font's GSUB tables, not draw isolated letters."""
    _, text = render(ARABIC, (50, 50, 500, 90), size_pt=14)
    joined = [c for c in text if ord(c) in PRESENTATION_FORMS]
    assert joined, f"no joined glyphs produced: {text!r}"


def test_no_missing_glyphs():
    """The reshaper trap: RuaqArabic has no U+FExx cmap, so a presentation-form
    pipeline emits NUL. Nothing we render may contain NUL or U+FFFD."""
    for value in (ARABIC, MIXED, LONG_ARABIC):
        _, text = render(value, (40, 40, 550, 200), size_pt=12, fit=Fit.WRAP)
        assert "\x00" not in text, f"NUL glyph in {value!r}"
        assert "�" not in text, f"replacement glyph in {value!r}"


def test_mixed_direction_keeps_digits_intact():
    """Latin digits inside an RTL line must survive as a readable run."""
    _, text = render(MIXED, (40, 40, 550, 90), size_pt=12)
    assert "542104012563" in text
    assert "308.75" in text


def test_font_is_embedded_as_vector_text():
    doc = fitz.open()
    page = doc.new_page(width=PAGE[0], height=PAGE[1])
    calibrated_htmlbox(
        page, fitz.Rect(50, 50, 500, 90), ARABIC, registry=brand_registry(), size_pt=14
    )
    reopened = fitz.open("pdf", doc.tobytes())
    fonts = reopened[0].get_fonts(full=True)
    assert fonts, "no embedded font"
    assert any("Ruaq" in f[3] for f in fonts)
    assert all(f[5] == "Identity-H" for f in fonts), "expected CID embedding"
    reopened.close()
    doc.close()


def test_unknown_font_is_reported_not_guessed():
    doc = fitz.open()
    page = doc.new_page(width=PAGE[0], height=PAGE[1])
    with pytest.raises(FontError, match="font not embedded"):
        calibrated_htmlbox(
            page,
            fitz.Rect(50, 50, 300, 80),
            ARABIC,
            registry=brand_registry(),
            family="IBMPlexSansArabic",
            weight="SemiBold",
        )
    doc.close()


# --------------------------------------------------------------------------
# Placement. A single pass is off by up to 158pt; two passes must land exactly.

TOLERANCE = 0.5


@pytest.mark.parametrize(
    "align,rect",
    [
        (Align.RIGHT, (413.1, 460.2, 482.6, 475.4)),
        (Align.LEFT, (44.7, 693.7, 176.6, 705.2)),
        (Align.CENTER, (112.8, 548.6, 194.3, 563.9)),
    ],
)
def test_calibration_lands_on_target(align, rect):
    placement, _ = render("542104012563", rect, align=align)
    target = fitz.Rect(*rect)
    got = placement.bbox
    assert got is not None
    if align is Align.RIGHT:
        assert abs(got.x1 - target.x1) < TOLERANCE
    elif align is Align.LEFT:
        assert abs(got.x0 - target.x0) < TOLERANCE
    else:
        assert abs((got.x0 + got.x1) / 2 - (target.x0 + target.x1) / 2) < TOLERANCE
    assert abs(got.y1 - target.y1) < TOLERANCE


@pytest.mark.parametrize("rotation", [90, 270])
def test_rotated_labels_land_on_target(rotation):
    """The booklet sets الحدود / الأطوال rotated inside narrow chips."""
    rect = (201.1, 466.6, 218.4, 493.4)
    placement, _ = render("الحدود", rect, rotate=rotation, size_pt=10.09)
    target = fitz.Rect(*rect)
    got = placement.bbox
    assert got is not None
    assert abs((got.x0 + got.x1) / 2 - (target.x0 + target.x1) / 2) < TOLERANCE
    assert abs((got.y0 + got.y1) / 2 - (target.y0 + target.y1) / 2) < TOLERANCE


@pytest.mark.parametrize("valign", list(VAlign))
def test_valign_pins_the_requested_edge(valign):
    rect = (413.1, 460.2, 482.6, 475.4)
    placement, _ = render("542104012563", rect, valign=valign)
    target, got = fitz.Rect(*rect), placement.bbox
    expected = {
        VAlign.TOP: abs(got.y0 - target.y0),
        VAlign.BOTTOM: abs(got.y1 - target.y1),
        VAlign.CENTER: abs((got.y0 + got.y1) / 2 - (target.y0 + target.y1) / 2),
    }[valign]
    assert expected < TOLERANCE


def test_colour_round_trips():
    """White-on-photograph cover text depends on this."""
    for wanted in ("#0E2A3A", "#D6006F", "#FFFFFF"):
        doc = fitz.open()
        page = doc.new_page(width=PAGE[0], height=PAGE[1])
        calibrated_htmlbox(
            page,
            fitz.Rect(50, 50, 300, 80),
            ARABIC,
            registry=brand_registry(),
            color=wanted,
            size_pt=12,
        )
        reopened = fitz.open("pdf", doc.tobytes())
        spans = [
            s
            for b in reopened[0].get_text("dict")["blocks"]
            for line in b.get("lines", [])
            for s in line["spans"]
        ]
        assert f"#{spans[0]['color']:06X}" == wanted
        reopened.close()
        doc.close()


# --------------------------------------------------------------------------
# Overflow behaviour -- the editor exposes all three modes.

TIGHT = (300, 400, 545, 432)


def test_shrink_scales_down_and_fits():
    placement, _ = render(
        LONG_ARABIC * 3, TIGHT, fit=Fit.SHRINK, min_scale=0.3, line_height=1.2
    )
    assert placement.scale < 1.0, "text should have been scaled down"
    assert placement.bbox.y1 <= TIGHT[3] + TOLERANCE


def test_clip_truncates_and_reports_the_character_count():
    """The preview screen shows 'أطول من الحقل بـ N أحرف'."""
    placement, _ = render(
        LONG_ARABIC * 3, TIGHT, fit=Fit.CLIP, line_height=1.2
    )
    assert placement.clipped_chars > 0
    assert placement.overflowed
    assert placement.scale == pytest.approx(1.0)
    assert placement.bbox.y1 <= TIGHT[3] + TOLERANCE


def test_wrap_keeps_size_and_grows_downward():
    placement, _ = render(
        LONG_ARABIC * 3, TIGHT, fit=Fit.WRAP, line_height=1.2
    )
    assert placement.scale == pytest.approx(1.0)
    assert placement.clipped_chars == 0
    assert placement.bbox.y1 > TIGHT[3], "wrap should overflow the original box"
    assert abs(placement.bbox.y0 - TIGHT[1]) < TOLERANCE, "top edge must stay pinned"


def test_calibration_still_exact_after_shrinking():
    """Shrinking and calibrating interact; the second pass must still land."""
    placement, _ = render(
        LONG_ARABIC * 3, TIGHT, fit=Fit.SHRINK, min_scale=0.3, line_height=1.2
    )
    assert placement.scale < 1.0
    assert abs(placement.bbox.x1 - TIGHT[2]) < TOLERANCE
    assert abs(placement.bbox.y1 - TIGHT[3]) < TOLERANCE


def test_empty_value_draws_nothing():
    placement, text = render("   ", (50, 50, 300, 80))
    assert placement.empty
    assert not text.strip()


# --------------------------------------------------------------------------
# Sections: a bold title over its points


SECTIONS = "مميزات العقار:\nبالقرب من طريق الملك فهد\n\nالملاحظات:\nيوجد اختلاف"


def test_a_title_is_set_in_the_brand_bold_face():
    """«مميزات العقار:» prints heavier than the points beneath it.

    `<b>` does nothing here: every weight of RuaqArabic is registered as its own
    CSS family, so bold has to be asked for by name. Checked on the font each
    line is actually drawn with, because a fallback face would satisfy any
    assertion about weight while looking nothing like the guide.
    """
    doc = fitz.open()
    page = doc.new_page(width=PAGE[0], height=PAGE[1])
    calibrated_htmlbox(
        page, fitz.Rect(60, 60, 500, 300), SECTIONS,
        registry=brand_registry(), fit=Fit.WRAP, align=Align.RIGHT,
    )
    reopened = fitz.open("pdf", doc.tobytes())
    faces: dict[str, set[str]] = {}
    for block in reopened[0].get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                if span["text"].strip():
                    faces.setdefault(span["font"], set()).add(span["text"].strip())
    reopened.close()
    doc.close()

    assert len(faces) == 2, f"a title face and a body face, got {list(faces)}"
    bold = [name for name in faces if "bold" in name.lower()]
    assert len(bold) == 1, f"one of them is the bold face: {list(faces)}"
    titled = " ".join(faces[bold[0]])
    assert ":" in titled, "the titles are what is set bold"
    body = " ".join(faces[next(n for n in faces if n != bold[0])])
    assert ":" not in body, "the points are not"


def test_the_lines_of_a_section_stay_separate_lines():
    """A newline is whitespace to an HTML engine.

    Written straight in, the whole box came out as one running paragraph and
    every title ran into the point beneath it.
    """
    _, extracted = render(
        SECTIONS, (60, 60, 500, 300), fit=Fit.WRAP, align=Align.RIGHT
    )
    lines = [line.strip() for line in extracted.splitlines() if line.strip()]
    assert len(lines) >= 4, f"four lines were written, got {lines}"


def test_a_long_line_is_not_mistaken_for_a_title():
    """The rule is a short line ending in a colon; a sentence is not one."""
    sentence = "يوجد إختلاف في الحد الشرقي بين الصك و المستكشف حيث ان الصك:"
    assert len(sentence) > 48
    doc = fitz.open()
    page = doc.new_page(width=PAGE[0], height=PAGE[1])
    calibrated_htmlbox(
        page, fitz.Rect(60, 60, 520, 300), sentence,
        registry=brand_registry(), fit=Fit.WRAP, align=Align.RIGHT,
    )
    reopened = fitz.open("pdf", doc.tobytes())
    fonts = {
        span["font"]
        for block in reopened[0].get_text("dict")["blocks"]
        for line in block.get("lines", [])
        for span in line["spans"]
        if span["text"].strip()
    }
    reopened.close()
    doc.close()
    assert not any("bold" in name.lower() for name in fonts), fonts


# --------------------------------------------------------------------------
# Which edge a wrapped paragraph starts on.


def _line_edges(text: str, rect: tuple[float, ...], **kwargs) -> list[fitz.Rect]:
    """Every drawn line's box, so an assertion can look at the short one."""
    doc = fitz.open()
    page = doc.new_page(width=PAGE[0], height=PAGE[1])
    calibrated_htmlbox(
        page, fitz.Rect(*rect), text, registry=brand_registry(), **kwargs
    )
    lines = [
        fitz.Rect(line["bbox"])
        for block in page.get_text("dict")["blocks"]
        if block["type"] == 0
        for line in block["lines"]
        if any(span["text"].strip() for span in line["spans"])
    ]
    doc.close()
    return lines


#: Long enough to wrap and to end on a line far short of the box's width.
PARAGRAPH = "نبذة عن وكيل البيع " * 9


def test_an_arabic_paragraph_starts_on_the_right():
    """نبذة عن وكيل البيع and نص الإعلان begin at the right of their box.

    Asserted on the *rendered* lines rather than on the CSS, because the
    keyword and the result do not agree: ``text-align`` is logical to MuPDF's
    story engine, so under ``dir="rtl"`` asking for ``right`` laid every line
    against the left edge and the paragraph's short last line hung off the
    wrong side. ``_RTL_ALIGN`` swaps the two names; if a MuPDF release ever
    stops needing that, this is what says so.

    A one-line value never showed it — calibration pins its right edge onto the
    target — so nothing but a wrapping box can catch this.
    """
    box = (100.0, 100.0, 450.0, 160.0)
    lines = _line_edges(PARAGRAPH, box, size_pt=10, align=Align.RIGHT, fit=Fit.WRAP)
    assert len(lines) >= 3, f"the sample has to wrap: {len(lines)} line(s)"
    for line in lines:
        assert abs(line.x1 - box[2]) < 1.0, "every line ends at the box's right edge"
    short = min(lines, key=lambda r: r.width)
    assert short.x0 > (box[0] + box[2]) / 2, (
        "the last line hangs off the right, not the left"
    )


def test_a_latin_run_still_aligns_the_way_css_says():
    """The three chips on تعريف وكيل البيع are set ``rtl=False``.

    A website, a telephone and an @handle are Latin and are laid out
    left-to-right, so the swap must not reach them: right means right.
    """
    box = (100.0, 100.0, 450.0, 160.0)
    lines = _line_edges(
        "www.example.com @aayan_realestate +966 55 000 0000 "
        "and a second line of the very same sort", box,
        size_pt=10, align=Align.RIGHT, fit=Fit.WRAP, rtl=False,
    )
    assert len(lines) >= 2, "the sample has to wrap"
    for line in lines:
        assert abs(line.x1 - box[2]) < 1.0, "every line ends at the box's right edge"
