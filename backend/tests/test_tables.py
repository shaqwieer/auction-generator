"""The summary table: derivation from artwork, and rendering with pagination."""

from __future__ import annotations

import itertools

import fitz
import pytest

from app.rendering import manifest
from app.rendering.base import FieldType, RenderPlan
from app.rendering.compose import compose
from app.rendering.overlay import PyMuPDFOverlayRenderer
from app.rendering.tables import INDEX_KEY, derive_tables

TABLE_PAGE = 4


def lots(count: int) -> list[dict]:
    return [
        {
            "deed_number": f"55500000{i:04d}",
            "property_type": "فيلا",
            "city": "حائل",
            "district": "الخطة",
            "area_sqm": str(400 + i),
            "plan_number": str(100 + i),
            "plot_number": str(200 + i),
            "entry_cheque": "10,000",
        }
        for i in range(count)
    ]


def template_fields(template_dir):
    """Column key sets for each table block, for scoping issue assertions."""
    with manifest.load(template_dir) as template:
        return [
            [c for c in f.table.columns]
            for f in template.fields
            if f.type is FieldType.TABLE and f.table is not None
        ]


def render(template, records):
    pages = compose(template.sections, records)
    plan = RenderPlan(
        background=template.background,
        fields=template.fields,
        pages=pages,
        design_page_height=template.design_page_height,
    )
    return PyMuPDFOverlayRenderer().render(plan), pages


# --------------------------------------------------------------------------
# Derivation


def test_derives_both_blocks(sample_doc):
    """The حضوري export draws the block twice: teal, then navy.

    Derivation reads both; the build makes them two pages, because the guide's
    blank specimen numbers each 01-08 and they are the same rows in two colours.
    """
    blocks = derive_tables(sample_doc, TABLE_PAGE)
    assert len(blocks) == 2, "the page draws the block in two colourways"
    for block in blocks:
        assert block.rows == 10
        assert block.row_pitch == pytest.approx(26.65, abs=0.5)
        assert len(block.columns) == 9


def test_columns_are_named_from_the_printed_headers(sample_doc):
    block = derive_tables(sample_doc, TABLE_PAGE)[0]
    keys = [c.key for c in block.columns]
    assert keys[0] == INDEX_KEY, "the row number sits at the right edge in RTL"
    assert {
        "property_type", "city", "district", "area_sqm",
        "plan_number", "plot_number", "deed_number", "entry_cheque",
    } <= set(keys)


def test_columns_span_the_cell_not_the_sample_ink(sample_doc):
    """Boundaries fall midway between header centres, so a long value still fits."""
    block = derive_tables(sample_doc, TABLE_PAGE)[0]
    columns = sorted(block.columns, key=lambda c: -c.rect_pt.x1)
    for left, right in itertools.pairwise(columns):
        assert left.rect_pt.x0 == pytest.approx(right.rect_pt.x1, abs=0.01), (
            "columns must tile without gaps or overlaps"
        )
    deed = next(c for c in block.columns if c.key == "deed_number")
    assert deed.rect_pt.width > 60, "a 12-digit deed number needs room"


def test_rows_step_down_by_the_pitch(sample_doc):
    block = derive_tables(sample_doc, TABLE_PAGE)[0]
    first, last = block.row_rect(0), block.row_rect(block.rows - 1)
    assert last.y0 - first.y0 == pytest.approx(block.row_pitch * (block.rows - 1))
    assert block.cell_rects().__len__() == block.rows * len(block.columns)


def test_table_pages_are_not_a_text_field(template_dir):
    """A table is one field per block, not one field per printed cell.

    One block, because the summary page carries one colourway of a ten-row
    table. The second block the حضوري export draws is the same ten rows in
    navy, built as its own page; counting it here as rows 11-20 printed half a
    booklet's properties into a block the design never meant to hold them.
    """
    with manifest.load(template_dir) as template:
        on_page = [
            f
            for f in template.fields
            if f.page_index == TABLE_PAGE
            # The company's name or mark, which every page carries where the
            # designer's own branding used to be baked in.
            and not f.key.startswith("company_")
        ]
        assert on_page, "the summary page must define fields"
        assert all(f.type is FieldType.TABLE for f in on_page)
        assert [f.table.row_offset for f in on_page] == [0]
        assert template.table_capacity(TABLE_PAGE) == 10


# --------------------------------------------------------------------------
# Baking


def test_sample_rows_are_cleared_but_headers_survive(template_dir):
    with manifest.load(template_dir) as template:
        text = template.background[TABLE_PAGE].get_text()
    # Sample values gone.
    for value in ("542104012563", "842122003917", "10,000"):
        assert value not in text, f"sample row value {value} still printed"
    # Headers and the page title are design and must remain.
    from tests.test_pipeline import fold

    kept = {fold(line) for line in text.split("\n") if line.strip()}
    assert "نوع العقار" in kept
    assert "رقم الصك" in kept
    assert "شيك الدخول" in kept


# --------------------------------------------------------------------------
# Rendering


def test_every_lot_appears_in_the_summary(template_dir):
    records = lots(8)
    with manifest.load(template_dir) as template:
        result, _ = render(template, records)

    with fitz.open("pdf", result.pdf) as out:
        page = next(
            out[i]
            for i in range(out.page_count)
            if "بيان" in "".join(out[i].get_text().split())
            or all(r["deed_number"] in out[i].get_text() for r in records)
        )
        text = page.get_text()
    for record in records:
        assert record["deed_number"] in text
    assert "01" in text and "08" in text, "row numbers are printed"


def test_row_numbering_continues_across_pages(template_dir):
    """Row 11 opens the second summary page and must still read 11, not 01.

    A page holds ten, and the guide's answer to a longer list is «فيتم تكرار
    الصفحة» -- repeat the page. The numbering has to run on across the repeat.
    """
    with manifest.load(template_dir) as template:
        result, _ = render(template, lots(14))

    with fitz.open("pdf", result.pdf) as out:
        text = "".join(out[i].get_text() for i in range(out.page_count))
    for number in ("09", "10", "11", "14"):
        assert number in text, f"row index {number} missing"


def test_summary_paginates_beyond_one_page(template_dir):
    with manifest.load(template_dir) as template:
        capacity = template.table_capacity(TABLE_PAGE)
        result, pages = render(template, lots(capacity + 5))
        table_pages = [p for p in pages if "__rows__" in p.values]

    assert len(table_pages) == 2, "21+ rows need a second summary page"
    assert [len(p.values["__rows__"]) for p in table_pages] == [capacity, 5]
    assert [p.values["__row_offset__"] for p in table_pages] == [0, capacity]
    # Photos are absent from this fixture; only table problems are in scope here.
    table_keys = {c.key for f in template_fields(template_dir) for c in f}
    assert not [
        i
        for i in result.issues
        if i.severity == "error" and (i.field_key in table_keys or i.field_key is None)
    ]


def test_overflow_beyond_capacity_is_reported(template_dir):
    """A block that cannot hold its slice must warn rather than drop rows silently."""
    with manifest.load(template_dir) as template:
        pages = compose(template.sections, lots(4))
        table_page = next(p for p in pages if "__rows__" in p.values)
        # Force more rows onto the page than its blocks can hold.
        table_page.values["__rows__"] = lots(template.table_capacity(TABLE_PAGE) + 3)
        plan = RenderPlan(
            background=template.background,
            fields=template.fields,
            pages=[table_page],
            design_page_height=template.design_page_height,
        )
        result = PyMuPDFOverlayRenderer().render(plan)

    warnings = [i for i in result.issues if i.severity == "warning"]
    assert any("جدول" in w.cause for w in warnings)


def test_fewer_records_than_rows_prints_only_those_rows(template_dir):
    """Three lots print three rows, and there is no fourth."""
    records = lots(3)
    with manifest.load(template_dir) as template:
        result, pages = render(template, records)
        summary_index = next(i for i, p in enumerate(pages) if "__rows__" in p.values)

    with fitz.open("pdf", result.pdf) as out:
        text = out[summary_index].get_text()

    for record in records:
        assert record["deed_number"] in text
    printed = [n for n in ("01", "02", "03", "04", "05") if n in text]
    assert printed == ["01", "02", "03"], f"unexpected row indices: {printed}"
    assert "\x00" not in text


# --------------------------------------------------------------------------
# A block as tall as the auction is long


#: «بيان عقود الإيجار» in the built template. Its own page, its own columns --
#: ten to the summary table's nine -- and nineteen rows to its ten.
LEASE_PAGE = 11


def table_field(template, page_index: int = TABLE_PAGE):
    return next(
        f
        for f in template.fields
        if f.page_index == page_index
        and f.type is FieldType.TABLE
        and f.table is not None
    )


def block_ink(page, field, height: float, width: float) -> list[fitz.Rect]:
    """Every shape drawn in the band the table's own block occupies.

    Grown from the field rect rather than stated in points, so the page's
    heading above it and the Infath mark in its footer stay out of scope
    however the artwork is revised. The margins are a row's worth either way:
    the numbered tab starts a little above the first rule and hangs a little
    below the last, and both are part of the block.
    """
    margin = field.table.row_pitch * height
    band = fitz.Rect(
        0.0,
        field.rect.y * height - margin,
        width,
        (field.rect.y + field.rect.h) * height + margin,
    )
    out = []
    for drawing in page.get_drawings():
        rect = fitz.Rect(drawing["rect"])
        rect.normalize()
        if rect.y0 >= band.y0 and rect.y1 <= band.y1:
            out.append(rect)
    return out


def rendered_summary(template, count: int):
    result, pages = render(template, lots(count))
    index = next(i for i, p in enumerate(pages) if "__rows__" in p.values)
    return result, index


def test_the_block_is_ruled_for_the_rows_there_are(template_dir):
    """No empty rows: a table of four properties is ruled four rows deep.

    The artwork ships ruled for ten because a printed page has to be drawn for
    some number. Ten rows for four properties left six ruled empties and a
    numbered tab running past all of them, which reads as a table that failed
    to fill in rather than as an auction with four lots in it.
    """
    with manifest.load(template_dir) as template:
        field = table_field(template)
        frame = field.table.frame
        assert frame is not None, "the summary table must carry its own ruling"
        page_rect = template.background[TABLE_PAGE].rect
        height, width = page_rect.height, page_rect.width
        assert len(frame.rules) == field.table.rows, (
            "one rule closes each row the block can hold"
        )

        for count in (1, 3, 7, field.table.rows):
            result, index = rendered_summary(template, count)
            with fitz.open("pdf", result.pdf) as out:
                shapes = block_ink(out[index], field, height, width)
            ruled = sorted(
                round(r.y0, 1) for r in shapes if r.height <= 1.0 and r.width > 100
            )
            expected = sorted(round(y * height, 1) for y in frame.rules[:count])
            assert ruled == expected, (
                f"{count} properties should be ruled off by {count} lines"
            )


def test_the_tab_and_the_dividers_stop_at_the_last_row(template_dir):
    """The whole block shortens, not just its rules.

    The numbered tab, the column dividers and the rules are one piece of
    artwork. Shortening the rules alone would leave the tab hanging below the
    table, which is the empty-row problem drawn a different way.
    """
    with manifest.load(template_dir) as template:
        field = table_field(template)
        frame = field.table.frame
        page_rect = template.background[TABLE_PAGE].rect
        height, width = page_rect.height, page_rect.width
        full = field.table.rows

        depths = {}
        for count in (2, 5, full):
            result, index = rendered_summary(template, count)
            with fitz.open("pdf", result.pdf) as out:
                shapes = block_ink(out[index], field, height, width)
            depths[count] = max(r.y1 for r in shapes)

        for count in (2, 5):
            lost = (frame.rules[full - 1] - frame.rules[count - 1]) * height
            assert depths[count] == pytest.approx(depths[full] - lost, abs=0.05), (
                f"the block should end {lost:.1f}pt higher with {count} rows"
            )


def test_a_full_table_is_the_ruling_the_designer_drew(template_dir):
    """At capacity the redraw must be the artwork it was lifted from.

    This is the check that makes every shorter table trustworthy: the geometry
    is translated, never rebuilt, so if ten rows land where the designer drew
    them then four do too. It failed twice while it was being written -- once
    because the ink went through eight bits a channel and came back a step
    lighter, once because the rules had never been taken off the artwork and
    were being redrawn on top of themselves.
    """
    with manifest.load(template_dir) as template:
        field = table_field(template)
        frame = field.table.frame
        page_rect = template.background[TABLE_PAGE].rect
        height, width = page_rect.height, page_rect.width

        result, index = rendered_summary(template, field.table.rows)
        with fitz.open("pdf", result.pdf) as out:
            drawn = block_ink(out[index], field, height, width)

    def corners(path):
        xs = [v for item in path.items for v in item.points[::2]]
        ys = [v for item in path.items for v in item.points[1::2]]
        return (
            round(min(xs) * width, 1), round(min(ys) * height, 1),
            round(max(xs) * width, 1), round(max(ys) * height, 1),
        )

    want = sorted(corners(p) for p in frame.paths)
    got = sorted(
        (round(r.x0, 1), round(r.y0, 1), round(r.x1, 1), round(r.y1, 1))
        for r in drawn
    )
    assert got == want, "a full block is drawn exactly where the artwork had it"


def test_a_fact_nobody_supplied_is_a_dash_in_a_row_that_exists(template_dir):
    """«في حال تعذر وجود معلومة يمكن إضافة (-) فقط دون حذف العمود».

    A row in the block is a property that exists, so an empty cell is a fact
    not supplied rather than a row to be removed. Left blank, a row with three
    gaps in it read as a table that had failed to render.
    """
    records = lots(2)
    records[0]["district"] = ""
    del records[1]["plan_number"]

    with manifest.load(template_dir) as template:
        pages = compose(template.sections, records)
        index = next(i for i, p in enumerate(pages) if "__rows__" in p.values)
        plan = RenderPlan(
            background=template.background,
            fields=template.fields,
            pages=pages,
            design_page_height=template.design_page_height,
        )
        result = PyMuPDFOverlayRenderer().render(plan)

    with fitz.open("pdf", result.pdf) as out:
        text = out[index].get_text()
    assert text.count("-") >= 2, "each missing fact prints a hyphen of its own"
    assert "01" in text and "02" in text, "both rows are still printed"


def test_the_lease_table_shrinks_to_its_leases_too(template_dir):
    """«بيان عقود الإيجار» is the same promise on a different page.

    Different in every way that matters to the measuring: ten columns rather
    than nine, nineteen rows rather than ten, headers converted to outlines so
    the block is found from its printed row numbers instead, and a designer who
    ruled twenty bands and numbered nineteen. None of that changes what the
    client sees -- a table of three leases is ruled three rows deep.
    """
    with manifest.load(template_dir) as template:
        field = table_field(template, LEASE_PAGE)
        frame = field.table.frame
        assert frame is not None, "the lease table must carry its own ruling"
        assert len(frame.rules) == field.table.rows == 19
        page_rect = template.background[LEASE_PAGE].rect
        height = page_rect.height

        # The unnumbered twentieth band: drawn by the designer, below every row
        # a client can fill, and never redrawn.
        pitch = field.table.row_pitch
        assert frame.bottom - frame.rules[-1] == pytest.approx(pitch, rel=0.1)
        assert not any(
            p.row is not None and p.row >= field.table.rows for p in frame.paths
        )

        renderer = PyMuPDFOverlayRenderer()
        for count in (1, 3, 12, field.table.rows):
            doc = fitz.open()
            doc.insert_pdf(template.background, from_page=LEASE_PAGE, to_page=LEASE_PAGE)
            drawn_page = doc[0]
            renderer._draw_frame(drawn_page, field.table, count)
            shapes = block_ink(drawn_page, field, height, page_rect.width)
            ruled = sorted(
                round(r.y0, 1) for r in shapes if r.height <= 1.0 and r.width > 100
            )
            assert ruled == sorted(
                round(y * height, 1) for y in frame.rules[:count]
            ), f"{count} leases should be ruled off by {count} lines"
            # And the block ends there: nothing hangs below the last rule but
            # the tab's own rounded corner.
            deepest = max(r.y1 for r in shapes)
            last = frame.rules[count - 1] * height
            assert 0 <= deepest - last < pitch * height, (
                f"the lease block runs {deepest - last:.1f}pt past its last row"
            )
            doc.close()


def ruled_rows(page, field, height: float, width: float) -> int:
    """How many row rules the renderer actually drew on this page."""
    shapes = block_ink(page, field, height, width)
    return len([r for r in shapes if r.height <= 1.0 and r.width > 100])


def test_the_summary_overflow_page_is_ruled_for_its_remainder(template_dir):
    """Thirteen properties: ten on one page, three on the next -- and three
    ruled rows on the next, not ten with seven empties under them.

    Repeating the artwork is only half the answer. Repeated at full height, an
    overflow page is a page of empty ruled rows, which is the original problem
    moved one page along.
    """
    with manifest.load(template_dir) as template:
        field = table_field(template)
        rect = template.background[TABLE_PAGE].rect
        result, pages = render(template, lots(13))
        table_pages = [i for i, p in enumerate(pages) if "__rows__" in p.values]
        assert len(table_pages) == 2, "thirteen properties need two summary pages"
        assert [len(pages[i].values["__rows__"]) for i in table_pages] == [10, 3]

        with fitz.open("pdf", result.pdf) as out:
            first = ruled_rows(out[table_pages[0]], field, rect.height, rect.width)
            second = ruled_rows(out[table_pages[1]], field, rect.height, rect.width)
            tail = out[table_pages[1]].get_text()
    assert (first, second) == (10, 3)
    for number in ("11", "12", "13"):
        assert number in tail, f"the overflow page carries on at {number}"
    assert "14" not in tail


def test_the_lease_overflow_page_is_ruled_for_its_remainder(template_dir):
    """And the same for contracts: nineteen, then six ruled rows numbered 20-25."""
    from app.rendering.compose import compose_plan_indexed

    nodes = [{
        "id": "lot0", "kind": "lot", "row": 0, "pages": [LEASE_PAGE],
        "layout": "standard", "options": ["rent_table"],
        "values": {"__lease__": [
            {"lease_unit_number": str(i + 1), "lease_status": "جاري"}
            for i in range(25)
        ]},
    }]
    with manifest.load(template_dir) as template:
        field = table_field(template, LEASE_PAGE)
        rect = template.background[LEASE_PAGE].rect
        pages = [
            p
            for _, p in compose_plan_indexed(
                nodes, {0: lots(1)[0]}, lease_pages={LEASE_PAGE: field.table.rows}
            )
            if p.template_page_index == LEASE_PAGE
        ]
        assert [len(p.values["__rows__"]) for p in pages] == [19, 6]

        plan = RenderPlan(
            background=template.background,
            fields=[f for f in template.fields if f.page_index == LEASE_PAGE],
            pages=pages,
            design_page_height=template.design_page_height,
        )
        result = PyMuPDFOverlayRenderer().render(plan)
        with fitz.open("pdf", result.pdf) as out:
            first = ruled_rows(out[0], field, rect.height, rect.width)
            second = ruled_rows(out[1], field, rect.height, rect.width)
            tail = out[1].get_text()
    assert (first, second) == (19, 6)
    for number in ("20", "25"):
        assert number in tail, f"the second lease page carries on at {number}"
    assert "26" not in tail
