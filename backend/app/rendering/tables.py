"""Read a repeating table off the designer's artwork.

The auction booklet's summary page prints one row per lot across nine columns,
laid out as two stacked blocks of ten rows. The geometry is regular, so it can be
recovered rather than typed:

* white 6.5pt runs above the body are the column headers, and their printed text
  maps to a field key through the same vocabulary the lot pages use;
* the white two-digit runs down the right edge are the row index, and the spacing
  between them gives the row pitch;
* a data cell is centred under its header, so column boundaries fall midway
  between adjacent header centres -- which recovers the full cell width instead
  of the sample value's ink extent.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field

import fitz

from .autokey import VOCABULARY, normalise
from .base import NormRect
from .shaping import Align, Fit

INDEX_KEY = "__index__"
HEADER_MAX_SIZE = 7.5
INDEX_MIN_SIZE = 10.0


@dataclass
class DerivedColumn:
    key: str
    label: str
    rect_pt: fitz.Rect       # this column's cell on the block's first row
    align: Align = Align.CENTER
    font_family: str = "RuaqArabic"
    font_weight: str = "Medium"
    font_size_pt: float = 8.0
    color: str = "#001447"
    fit: Fit = Fit.SHRINK
    source: str = ""         # "" = record[key]; INDEX_KEY = the row number


@dataclass
class DerivedTable:
    page_index: int
    first_row_pt: fitz.Rect  # bounding box of the block's first row
    row_pitch: float         # vertical distance between consecutive rows, points
    rows: int                # how many rows this block holds
    columns: list[DerivedColumn] = field(default_factory=list)

    def row_rect(self, index: int) -> fitz.Rect:
        shift = index * self.row_pitch
        return self.first_row_pt + (0, shift, 0, shift)

    def cell_rects(self) -> list[fitz.Rect]:
        """Every cell in the block -- what baking has to clear."""
        out: list[fitz.Rect] = []
        for row in range(self.rows):
            shift = row * self.row_pitch
            for column in self.columns:
                out.append(column.rect_pt + (0, shift, 0, shift))
        return out


def _spans(page: fitz.Page) -> list[dict]:
    out: list[dict] = []
    for block in page.get_text("dict")["blocks"]:
        if block["type"] != 0:
            continue
        for line in block["lines"]:
            for span in line["spans"]:
                if span["text"].strip():
                    out.append(span)
    return out


def _band(spans: list[dict], tolerance: float = 4.0) -> list[list[dict]]:
    """Group spans into visual rows by their top edge."""
    rows: list[list[dict]] = []
    for span in sorted(spans, key=lambda s: s["bbox"][1]):
        if rows and span["bbox"][1] - rows[-1][0]["bbox"][1] <= tolerance:
            rows[-1].append(span)
        else:
            rows.append([span])
    return rows


def derive_tables(doc: fitz.Document, page_index: int) -> list[DerivedTable]:
    """Recover every table block on ``page_index``. Empty list if none look like one."""
    page = doc[page_index]
    page_rect = page.rect
    spans = _spans(page)
    if not spans:
        return []

    headers = [
        s
        for s in spans
        if f"#{s['color']:06X}" == "#FFFFFF"
        and s["size"] <= HEADER_MAX_SIZE
        and normalise(s["text"]) in VOCABULARY
    ]
    indices = [
        s
        for s in spans
        if f"#{s['color']:06X}" == "#FFFFFF"
        and s["size"] >= INDEX_MIN_SIZE
        and s["text"].strip().isdigit()
    ]
    if len(headers) < 3 or len(indices) < 4:
        return []

    header_rows = [r for r in _band(headers) if len(r) >= 3]
    index_rows = _band(indices)
    if not header_rows:
        return []

    tables: list[DerivedTable] = []
    for block_no, header_row in enumerate(header_rows):
        header_bottom = max(s["bbox"][3] for s in header_row)
        next_header = (
            min(s["bbox"][1] for s in header_rows[block_no + 1])
            if block_no + 1 < len(header_rows)
            else page_rect.y1
        )
        block_indices = [
            r
            for r in index_rows
            if header_bottom < r[0]["bbox"][1] < next_header
        ]
        if len(block_indices) < 2:
            continue

        tops = [r[0]["bbox"][1] for r in block_indices]
        pitch = statistics.median(
            tops[i + 1] - tops[i] for i in range(len(tops) - 1)
        )
        first_top = tops[0]
        index_span = block_indices[0][0]

        # Data cells on the block's first row, excluding the index itself.
        row_bottom = first_top + pitch * 0.9
        data = [
            s
            for s in spans
            if first_top - 3 <= s["bbox"][1] <= row_bottom
            and f"#{s['color']:06X}" != "#FFFFFF"
        ]
        if not data:
            continue

        columns = _build_columns(header_row, data, index_span, page_rect)
        if len(columns) < 3:
            continue

        first_row = fitz.Rect(columns[0].rect_pt)
        for column in columns[1:]:
            first_row |= column.rect_pt

        tables.append(
            DerivedTable(
                page_index=page_index,
                first_row_pt=first_row,
                row_pitch=round(pitch, 3),
                rows=len(block_indices),
                columns=columns,
            )
        )
    return tables


def _build_columns(
    header_row: list[dict],
    data: list[dict],
    index_span: dict,
    page_rect: fitz.Rect,
) -> list[DerivedColumn]:
    """Turn headers plus one sample row into full-width column definitions.

    Cells are centred under their headers, so the boundary between two columns is
    the midpoint of their centres. That recovers the cell, where using the sample
    value's bbox would give a box only as wide as whatever the designer typed.
    """
    entries: list[tuple[float, str, str, dict | None]] = []
    for span in header_row:
        label = normalise(span["text"])
        key = VOCABULARY.get(label)
        if not key:
            continue
        centre = (span["bbox"][0] + span["bbox"][2]) / 2
        entries.append((centre, key, label, None))

    index_centre = (index_span["bbox"][0] + index_span["bbox"][2]) / 2
    entries.append((index_centre, INDEX_KEY, "#", index_span))

    # Right to left: the index sits at the right edge in an RTL table.
    entries.sort(key=lambda e: -e[0])

    columns: list[DerivedColumn] = []
    for position, (centre, key, label, source_span) in enumerate(entries):
        right = (
            (centre + entries[position - 1][0]) / 2
            if position > 0
            else min(page_rect.x1, centre + 24)
        )
        left = (
            (centre + entries[position + 1][0]) / 2
            if position + 1 < len(entries)
            else max(page_rect.x0, centre - 40)
        )

        sample = source_span
        if sample is None:
            candidates = [
                s
                for s in data
                if left <= (s["bbox"][0] + s["bbox"][2]) / 2 <= right
            ]
            if not candidates:
                continue
            sample = min(
                candidates,
                key=lambda s: abs((s["bbox"][0] + s["bbox"][2]) / 2 - centre),
            )

        family, _, weight = sample["font"].split("+")[-1].partition("-")
        columns.append(
            DerivedColumn(
                key=key,
                label=label,
                rect_pt=fitz.Rect(left, sample["bbox"][1], right, sample["bbox"][3]),
                font_family=family or "RuaqArabic",
                font_weight=weight or "Regular",
                font_size_pt=round(sample["size"], 2),
                color=f"#{sample['color']:06X}",
                source=INDEX_KEY if key == INDEX_KEY else "",
            )
        )
    return columns


def to_norm(table: DerivedTable, page_rect: fitz.Rect) -> dict:
    """Serialise a derived block into the template manifest's shape."""
    return {
        "row_pitch": table.row_pitch / page_rect.height,
        "rows": table.rows,
        "columns": [
            {
                "key": c.key,
                "label": c.label,
                "rect": {
                    "x": (c.rect_pt.x0 - page_rect.x0) / page_rect.width,
                    "y": (c.rect_pt.y0 - page_rect.y0) / page_rect.height,
                    "w": c.rect_pt.width / page_rect.width,
                    "h": c.rect_pt.height / page_rect.height,
                },
                "align": c.align.value,
                "font_family": c.font_family,
                "font_weight": c.font_weight,
                "font_size_pt": c.font_size_pt,
                "color": c.color,
                "fit": c.fit.value,
                "source": c.source,
            }
            for c in table.columns
        ],
    }


def norm_rect(column: dict) -> NormRect:
    r = column["rect"]
    return NormRect(r["x"], r["y"], r["w"], r["h"])
