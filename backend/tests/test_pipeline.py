"""Derivation, baking and composition, checked against the real auction booklet.

The golden test below is the one that matters most: it proves overlaying onto the
designer's artwork is non-destructive. If it fails, generated booklets are losing
design elements and nothing else in the suite will tell you.
"""

from __future__ import annotations

import unicodedata

import fitz
import pytest

from app.rendering import manifest
from app.rendering.autokey import normalise, suggest
from app.rendering.bake import bake_page
from app.rendering.base import FieldType, NormRect, RenderPlan, SectionKind
from app.rendering.compose import (
    Section,
    compose,
    compose_plan,
    page_count,
    page_count_plan,
)
from app.rendering.derive import derive_page
from app.rendering.overlay import PyMuPDFOverlayRenderer

LOT_PAGE = 5


def fold(text: str) -> str:
    """Recover base Arabic letters and drop marks, for comparing printed text."""
    folded = unicodedata.normalize("NFKC", text)
    return "".join(c for c in folded if not unicodedata.combining(c)).strip(" :")


def printed(page: fitz.Page) -> set[str]:
    return {
        fold(span["text"])
        for block in page.get_text("dict")["blocks"]
        if block["type"] == 0
        for line in block["lines"]
        for span in line["spans"]
        if span["text"].strip()
    }


# --------------------------------------------------------------------------
# Derivation


def test_derive_reads_real_geometry(sample_doc):
    fields = derive_page(sample_doc, LOT_PAGE)
    text = [f for f in fields if f.type is FieldType.TEXT]
    assert len(text) > 30, "the lot page has dozens of runs"
    assert any(f.rotation == 90 for f in text), "الحدود / الأطوال are rotated"
    assert {f.color for f in text} > {"#1A9F9F", "#0D3759"}, "labels and values differ"
    assert all(0.0 <= f.rect.x <= 1.0 and 0.0 <= f.rect.y <= 1.0 for f in fields)


def test_derive_ignores_flattening_artifacts(sample_doc):
    """Illustrator emits soft masks that look like full-page images."""
    images = [f for f in derive_page(sample_doc, 0) if f.type is FieldType.IMAGE]
    assert len(images) == 1, f"expected one cover photo, got {len(images)}"
    assert images[0].src_width >= 1000


def test_derive_finds_uri_links(sample_doc):
    links = [f for f in derive_page(sample_doc, 8) if f.type is FieldType.LINK]
    assert len(links) == 3
    assert any("maps" in f.sample_text for f in links)


# --------------------------------------------------------------------------
# Auto-keying


def test_presentation_forms_normalise_back_to_arabic():
    assert normalise("ﺍﻟﻨﻮﻉ") == "النوع"
    assert normalise("ﺭﻗﻢ ﺍﻟﺼﻚ") == "رقم الصك"


def test_autokey_pairs_labels_with_the_value_to_their_left(sample_doc):
    fields = derive_page(sample_doc, LOT_PAGE)
    values = {s.key: s for s in suggest(fields) if s.role == "value"}
    for key in ("deed_number", "property_type", "area_sqm", "district"):
        assert key in values, f"{key} not auto-keyed"
    deed = values["deed_number"].field
    assert deed.sample_text.strip() == "542104012563"
    # RTL: the value sits to the left of its printed label.
    label = next(s.field for s in suggest(fields) if s.key == "deed_number" and s.role == "label")
    assert deed.rect_pt.x1 <= label.rect_pt.x0 + 1


# --------------------------------------------------------------------------
# The golden test


def test_baking_preserves_the_artwork(sample_doc, template_dir):
    """Bake every field region on the real lot page and prove the design survives.

    Checks the two things that can silently go wrong: pixels changing outside the
    cleared regions, and vector line art being punched out.
    """
    template = manifest.load(template_dir)
    try:
        regions = [
            (f.rect.to_points(sample_doc[LOT_PAGE].rect), f.type)
            for f in template.fields
            if f.page_index == LOT_PAGE
        ]
    finally:
        template.close()
    assert regions, "the lot page must define fields"

    page = sample_doc[LOT_PAGE]
    # Guard against a future fixture change handing us an already-baked page:
    # baking twice would trivially report zero pixels changed.
    assert "542104012563" in page.get_text(), "sample page 5 is not pristine"

    before_pix = page.get_pixmap(dpi=150)
    before_drawings = len(page.get_drawings())

    bake_page(page, regions)

    after_pix = page.get_pixmap(dpi=150)
    after_drawings = len(page.get_drawings())

    scale = 150 / 72.0
    padded = [r + (-2, -2, 2, 2) for r, _ in regions]

    outside = 0
    width, height, n = before_pix.width, before_pix.height, before_pix.n
    a, b = before_pix.samples, after_pix.samples
    for y in range(0, height, 2):
        for x in range(0, width, 2):
            i = (y * width + x) * n
            if a[i : i + n] == b[i : i + n]:
                continue
            px, py = x / scale, y / scale
            if not any(r.x0 <= px <= r.x1 and r.y0 <= py <= r.y1 for r in padded):
                outside += 1

    assert outside == 0, f"{outside} pixels changed outside the field regions"
    assert before_drawings - after_drawings <= 2, "vector line art was removed"


def test_baking_keeps_the_printed_labels(sample_path, template_dir):
    """Values go, labels stay. Clearing a label leaves an orphaned value."""
    with fitz.open(sample_path) as original:
        before = printed(original[LOT_PAGE])
    with manifest.load(template_dir) as template:
        after = printed(template.background[LOT_PAGE])

    labels = {
        "النوع", "رقم الصك", "رقم المخطط", "رقم القطعة", "المساحة",
        "الاستخدام", "الحي", "شيك الدخول", "رقم طلب التنفيذ",
        # «معلومات اضافية» is the chip above the box and is design. «ملاحظات»
        # is *inside* it, where the guide has the client write their own
        # section titles — so it is sample content, and a page that kept it
        # opened with a heading already written in it that no field could
        # reach.
        "وصف العقار", "معلومات اضافية",
        "شمالا", "جنوبا", "شرقا", "غربا",
    }
    expected = labels & before
    assert expected, "sanity: the sample should print these labels"
    assert expected <= after, f"labels lost in bake: {sorted(expected - after)}"

    # And the sample's own values must be gone.
    assert "542104012563" not in after
    assert "875" not in after


# --------------------------------------------------------------------------
# Composition


def sections() -> list[Section]:
    return [
        Section(SectionKind.FIXED, 0, 3, name="front"),
        Section(SectionKind.TABLE, 4, 4, name="summary", rows_per_page=8),
        Section(SectionKind.PER_RECORD, 5, 6, name="lots", pages_per_item=2),
        Section(SectionKind.FIXED, 7, 13, name="back"),
    ]


def test_two_pages_per_lot():
    records = [{"deed_number": str(i)} for i in range(8)]
    pages = compose(sections(), records)
    lot_pages = [p for p in pages if p.record_index is not None]
    assert len(lot_pages) == 16
    for index in range(8):
        owned = [p for p in lot_pages if p.record_index == index]
        assert len(owned) == 2
        assert [p.template_page_index for p in owned] == [5, 6]


def test_predicted_page_count_matches_reality():
    for count in (1, 3, 8, 20):
        records = [{"deed_number": str(i)} for i in range(count)]
        assert len(compose(sections(), records)) == page_count(sections(), count)


def test_summary_table_paginates():
    records = [{"deed_number": str(i)} for i in range(20)]
    pages = compose(sections(), records)
    table_pages = [p for p in pages if "__rows__" in p.values]
    assert len(table_pages) == 3  # ceil(20 / 8)
    assert [len(p.values["__rows__"]) for p in table_pages] == [8, 8, 4]
    assert [p.values["__row_offset__"] for p in table_pages] == [0, 8, 16]


def test_a_property_with_more_leases_than_one_page_gets_another():
    """«فيتم تكرار الصفحة», for contracts as much as for properties.

    A lease page holds nineteen. The twentieth contract does not vanish and is
    not squeezed in: the page repeats, the same artwork again, and the numbering
    carries on across it. Before this the render stopped at nineteen and warned,
    so an asset with more leases than that could not be printed at all.
    """
    from app.rendering.compose import compose_plan_indexed, page_count_plan

    nodes = [{
        "id": "lot0", "kind": "lot", "row": 0, "pages": [5, 11],
        "layout": "standard", "options": ["rent_table"],
        "values": {"__lease__": [{"lease_unit_number": str(i + 1)} for i in range(25)]},
    }]
    caps = {11: 19}
    pages = [p for _, p in compose_plan_indexed(nodes, {0: {"deed_number": "X"}},
                                                lease_pages=caps)]
    leases = [p for p in pages if p.template_page_index == 11]
    assert len(leases) == 2, "twenty-five contracts need two pages"
    assert [len(p.values["__rows__"]) for p in leases] == [19, 6]
    assert [p.values["__row_offset__"] for p in leases] == [0, 19]
    # The property's own page is still drawn once.
    assert sum(1 for p in pages if p.template_page_index == 5) == 1
    # And the review step counts what the booklet actually prints.
    assert page_count_plan(nodes, {0}, caps) == len(pages)


def test_a_lease_page_is_drawn_even_with_no_contracts_on_it():
    """Switching the page on is how the operator gets somewhere to type."""
    from app.rendering.compose import compose_plan_indexed

    nodes = [{
        "id": "lot0", "kind": "lot", "row": 0, "pages": [11],
        "layout": "standard", "options": ["rent_table"], "values": {},
    }]
    pages = [p for _, p in compose_plan_indexed(nodes, {0: {"deed_number": "X"}},
                                                lease_pages={11: 19})]
    assert len(pages) == 1
    assert pages[0].values["__rows__"] == []


def test_static_values_reach_every_page_and_records_win():
    records = [{"deed_number": "X", "auction_title": "من السجل"}]
    pages = compose(
        sections(), records, static_values={"auction_title": "عام", "city": "حائل"}
    )
    assert all(p.values.get("city") == "حائل" for p in pages)
    lot = next(p for p in pages if p.record_index == 0)
    assert lot.values["auction_title"] == "من السجل"


def test_variant_sections_are_skipped():
    plan = [*sections(), Section(SectionKind.FIXED, 13, 13, name="e-auction", variant="hybrid")]
    assert page_count(plan, 1, variant=None) + 1 == page_count(plan, 1, variant="hybrid")


def test_per_record_section_rejects_inconsistent_page_span():
    with pytest.raises(ValueError, match="pages_per_item"):
        Section(SectionKind.PER_RECORD, 5, 6, name="bad", pages_per_item=3)


# --------------------------------------------------------------------------
# End to end


def a_photo(width: int = 1600, height: int = 1200) -> bytes:
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (width, height), (120, 140, 160)).save(buf, format="JPEG")
    return buf.getvalue()


def test_generated_booklet_places_every_lot(template_dir):
    records = [
        {
            "deed_number": f"9999000{i:05d}",
            "property_type": "فيلا",
            "district": "الملك عبدالله",
            "area_sqm": "875",
            "main_photo": "lot.jpg",
        }
        for i in range(4)
    ]
    with manifest.load(template_dir) as template:
        pages = compose(
            template.sections, records, static_values={"cover_photo": "cover.jpg"}
        )
        plan = RenderPlan(
            background=template.background,
            fields=template.fields,
            pages=pages,
            assets={"lot.jpg": a_photo(), "cover.jpg": a_photo(2400, 3400)},
            design_page_height=template.design_page_height,
        )
        result = PyMuPDFOverlayRenderer().render(plan)

    assert result.page_count == len(pages)
    assert not [i for i in result.issues if i.severity == "error"]

    # A property appears once in the summary table and once on its page. The
    # section plan carries only the default قياسي layout -- which of the two a
    # property actually uses is the project's page plan to decide, not the
    # template's.
    summary = {i for i, p in enumerate(pages) if "__rows__" in p.values}
    lot_pages = {i for i, p in enumerate(pages) if p.record_index is not None}

    with fitz.open("pdf", result.pdf) as out:
        text_by_page = [out[i].get_text() for i in range(out.page_count)]
        for i, record in enumerate(records):
            hits = {n for n, t in enumerate(text_by_page) if record["deed_number"] in t}
            assert len(hits & lot_pages) == 1, (
                f"lot {i} should occupy exactly one lot page, "
                f"got {sorted(hits & lot_pages)}"
            )
            assert hits & summary, f"lot {i} missing from the summary table"
        joined = "".join(text_by_page)
        assert "\x00" not in joined and "�" not in joined


def test_missing_required_value_is_reported_with_row_and_field(template_dir):
    """Every generation error must name the row, the field and a readable cause."""
    with manifest.load(template_dir) as template:
        required_text = {
            f.key
            for f in template.fields
            if f.is_required and f.type is FieldType.TEXT
        }
        assert required_text, "the template should mark some text fields required"
        # Supply nothing: every required field should be reported.
        pages = compose(template.sections, [{}])
        plan = RenderPlan(
            background=template.background,
            fields=template.fields,
            pages=pages,
            design_page_height=template.design_page_height,
        )
        result = PyMuPDFOverlayRenderer().render(plan)

    errors = [i for i in result.issues if i.severity == "error"]
    assert errors, "an empty required field must be an error"

    row_errors = [e for e in errors if e.row_index is not None]
    assert row_errors, "a per-record failure must carry its row index"
    assert row_errors[0].row_index == 0
    assert required_text <= {e.field_key for e in row_errors}, (
        "every required text field left empty must be reported for that row"
    )
    assert all(e.field_key for e in errors)
    assert all("«" in e.cause for e in errors), "the cause must name the field"

    # Project-level fields have no row, and must say so rather than claim row 0.
    assert any(e.row_index is None for e in errors)


def test_normalised_rect_survives_a_different_page_size():
    rect = NormRect(0.25, 0.5, 0.5, 0.1)
    a4 = fitz.Rect(0, 0, 595.28, 841.89)
    a3 = fitz.Rect(0, 0, 841.89, 1190.55)
    assert rect.to_points(a4).width == pytest.approx(297.64)
    assert rect.to_points(a3).width == pytest.approx(420.945)
    round_tripped = NormRect.from_points(rect.to_points(a3), a3)
    assert round_tripped.x == pytest.approx(rect.x)
    assert round_tripped.w == pytest.approx(rect.w)


# ------------------------------------------------------- the project's plan


def _plan_nodes():
    """A small booklet: cover, table, three properties, closing page."""
    return [
        {"id": "n1", "kind": "page", "page": 0, "slot": "cover"},
        {"id": "n2", "kind": "table", "page": 4, "rows_per_page": 2},
        {"id": "n3", "kind": "lot", "row": 0, "layout": "standard", "pages": [5, 9]},
        {"id": "n4", "kind": "lot", "row": 1, "layout": "tower", "pages": [6]},
        {"id": "n5", "kind": "lot", "row": 2, "layout": "standard", "pages": [5]},
        {"id": "n6", "kind": "page", "page": 14, "values": {"contact_phone": "0500"}},
    ]


def _records():
    return {
        0: {"deed_number": "A", "property_type": "فيلا"},
        1: {"deed_number": "B", "property_type": "أرض"},
        2: {"deed_number": "C", "property_type": "شقة"},
    }


def test_compose_plan_predicts_exactly_what_it_produces():
    nodes, records = _plan_nodes(), _records()
    pages = compose_plan(nodes, records)
    assert len(pages) == page_count_plan(nodes, set(records))


def test_compose_plan_lets_each_property_choose_its_own_layout():
    """The whole point of the builder: one برج among the قياسي."""
    pages = compose_plan(_plan_nodes(), _records())
    by_row = {}
    for page in pages:
        if page.record_index is not None:
            by_row.setdefault(page.record_index, []).append(page.template_page_index)
    assert by_row == {0: [5, 9], 1: [6], 2: [5]}


def test_compose_plan_table_rows_follow_the_booklet_order():
    """Reordering the properties must reorder the summary table with them."""
    nodes = _plan_nodes()
    nodes[2], nodes[4] = nodes[4], nodes[2]        # move the third lot first
    pages = compose_plan(nodes, _records())
    rows = [
        deed
        for page in pages
        if "__rows__" in page.values
        for deed in (r["deed_number"] for r in page.values["__rows__"])
    ]
    assert rows == ["C", "B", "A"]


def test_compose_plan_table_offsets_are_contiguous():
    """Row numbering runs across pages, so the offsets cannot have gaps."""
    pages = [p for p in compose_plan(_plan_nodes(), _records()) if "__rows__" in p.values]
    offsets = [p.values["__row_offset__"] for p in pages]
    assert offsets == [0, 2]
    assert sum(len(p.values["__rows__"]) for p in pages) == 3


def test_compose_plan_value_precedence_is_project_then_page_then_record():
    """A page's own values fill the optional pages; a record still wins."""
    nodes = [
        {"id": "a", "kind": "page", "page": 14,
         "values": {"location": "قاعة جدة", "auction_title": "من الصفحة"}},
        {"id": "b", "kind": "lot", "row": 0, "pages": [5],
         "values": {"deed_number": "من الصفحة"}},
    ]
    pages = compose_plan(
        nodes, {0: {"deed_number": "من السجل"}},
        static_values={"auction_title": "من المشروع", "location": "من المشروع"},
    )
    assert pages[0].values["location"] == "قاعة جدة"
    assert pages[0].values["auction_title"] == "من الصفحة"
    assert pages[1].values["deed_number"] == "من السجل"


def test_compose_plan_skips_a_lot_whose_row_is_gone():
    """Deleting a spreadsheet row must not print an empty property."""
    pages = compose_plan(_plan_nodes(), {0: {"deed_number": "A"}})
    assert {p.record_index for p in pages if p.record_index is not None} == {0}


def test_default_plan_composes_the_same_booklet_as_the_section_plan(template_dir):
    """The regression net: a project that changes nothing gets what it always got.

    A default plan is the template's own order with one node per property, so
    the pages it produces must match what the section plan produced before the
    builder existed -- otherwise every existing booklet quietly changes shape.
    """
    from app.services.page_plan import PAGE, TABLE

    with manifest.load(template_dir) as template:
        records = [{"deed_number": str(i)} for i in range(3)]
        old = compose(template.sections, records)

        # The same booklet expressed as a plan, built the way default_plan does.
        nodes: list[dict] = []
        placed = False
        for section in template.sections:
            if section.kind is SectionKind.TABLE:
                nodes.append({
                    "id": f"t{section.first_page}", "kind": TABLE,
                    "page": section.first_page,
                    "rows_per_page": section.rows_per_page,
                })
            elif section.kind is SectionKind.PER_RECORD:
                if not placed:
                    nodes.extend(
                        {"id": f"l{i}", "kind": "lot", "row": i,
                         "pages": list(section.pages)}
                        for i in range(len(records))
                    )
                    placed = True
            else:
                nodes.extend(
                    {"id": f"p{p}", "kind": PAGE, "page": p} for p in section.pages
                )

        new = compose_plan(nodes, dict(enumerate(records)))

    assert [p.template_page_index for p in new] == [
        p.template_page_index for p in old
    ]
    assert [p.record_index for p in new] == [p.record_index for p in old]
