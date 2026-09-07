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


def test_fewer_records_than_rows_leaves_the_rest_blank(template_dir):
    """Three lots print three rows; the rest of the block stays empty."""
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
