"""Load a built template (background artwork + field definitions) from disk.

This is the file-backed stand-in for the database. The API will read the same
shapes out of ``Template`` / ``TemplateSection`` / ``TemplateField`` rows, so the
loader returns domain objects rather than raw dicts.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from pathlib import Path

import fitz

from .base import (
    ChipPart,
    FieldSpec,
    FieldType,
    FrameItem,
    FramePath,
    NormRect,
    SectionKind,
    TableColumn,
    TableFrame,
    TableSpec,
)
from .compose import Section
from .shaping import Align, Fit, VAlign


@dataclass
class Template:
    slug: str
    background: fitz.Document
    fields: list[FieldSpec]
    sections: list[Section]
    design_page_height: float
    page_size: tuple[float, float]
    #: Which page stands in for which, per output. The lot pages are drawn
    #: twice -- once for print, once for a screen -- and a booklet points at the
    #: printed one; ``{"electronic": {5: 22}}`` says where the other drawing is.
    flavours: dict[str, dict[int, int]] = dataclass_field(default_factory=dict)

    def pages_for(self, flavour: str) -> dict[int, int]:
        """The substitutions this output asks for, empty for the default one."""
        return self.flavours.get(flavour, {})

    def close(self) -> None:
        self.background.close()

    def __enter__(self) -> Template:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @property
    def field_keys(self) -> list[str]:
        """Distinct keys, in first-appearance order -- the mapping screen's list."""
        seen: dict[str, None] = {}
        for f in self.fields:
            seen.setdefault(f.key, None)
        return list(seen)

    @property
    def required_keys(self) -> list[str]:
        return sorted({f.key for f in self.fields if f.is_required})

    def table_capacity(self, page_index: int | None = None) -> int:
        """Rows a table page can print, across every block on it.

        Per page rather than per document: the booklet carries a summary table
        of the properties and, on the property pages, a lease table. Summing
        both gives a number that describes neither.
        """
        return sum(
            f.table.rows
            for f in self.fields
            if f.type is FieldType.TABLE
            and f.table is not None
            and (page_index is None or f.page_index == page_index)
        )

    def record_keys(self) -> list[str]:
        """Keys that belong to a data record rather than the project as a whole.

        Must agree with :func:`app.services.templates.record_keys`, which reads
        the same template out of the database. A summary-table column is a
        record key even though its page is not a per-record page -- ``city``
        appears only in the auction booklet's table -- and a TABLE field's own
        key (``__table__0``) is plumbing, never a record key.
        """
        per_record_pages = {
            page
            for section in self.sections
            if section.kind is SectionKind.PER_RECORD
            for page in section.pages
        }
        table_keys: list[str] = []
        for f in self.fields:
            if f.type is FieldType.TABLE and f.table is not None:
                table_keys.extend(c.key for c in f.table.columns if not c.source)

        seen: dict[str, None] = {}
        for f in self.fields:
            if f.page_index in per_record_pages and f.type is not FieldType.TABLE:
                seen.setdefault(f.key, None)
        for key in table_keys:
            seen.setdefault(key, None)
        return list(seen)


def _column_from(raw: dict) -> TableColumn:
    rect = raw["rect"]
    return TableColumn(
        key=raw["key"],
        rect=NormRect(rect["x"], rect["y"], rect["w"], rect["h"]),
        label=raw.get("label", ""),
        align=Align(raw.get("align", "center")),
        valign=VAlign(raw["valign"]) if raw.get("valign") else None,
        font_family=raw.get("font_family", "RuaqArabic"),
        font_weight=raw.get("font_weight", "Medium"),
        font_size_pt=float(raw.get("font_size_pt", 8.0)),
        color=raw.get("color", "#001447"),
        fit=Fit(raw.get("fit", "shrink")),
        rtl=bool(raw.get("rtl", True)),
        source=raw.get("source", ""),
    )


def _ink_from(raw: object) -> list[float] | None:
    if not raw:
        return None
    return [float(v) for v in raw]  # type: ignore[union-attr]


def paths_from_json(raw: object) -> list[FramePath]:
    """Drawn shapes on their own, without a table's rules around them.

    A field's ornament is the same recording as a table frame's -- the
    designer's own segments in the ink the file states them in -- with no rows
    to close and so no ``rules`` and no ``bottom``.
    """
    return [
        FramePath(
            items=[
                FrameItem(
                    kind=str(i["kind"]),
                    points=[float(v) for v in i["points"]],
                )
                for i in p.get("items", [])
            ],
            stroke=_ink_from(p.get("stroke")),
            fill=_ink_from(p.get("fill")),
            width=float(p.get("width", 0.0)),
            closed=bool(p.get("closed", False)),
        )
        for p in (raw or [])  # type: ignore[union-attr]
    ]


def part_from_json(raw: dict | None) -> ChipPart | None:
    if not raw:
        return None
    rect = raw["rect"]
    return ChipPart(
        page=int(raw["page"]),
        rect=NormRect(rect["x"], rect["y"], rect["w"], rect["h"]),
    )


def frame_from_json(raw: dict | None) -> TableFrame | None:
    if not raw or not raw.get("rules"):
        return None
    rules = [float(y) for y in raw["rules"]]
    return TableFrame(
        rules=rules,
        # A block whose bottom edge is its last row's rule does not have to say
        # so, which is every table but the lease one.
        bottom=float(raw.get("bottom") or rules[-1]),
        paths=[
            FramePath(
                items=[
                    FrameItem(
                        kind=str(i["kind"]),
                        points=[float(v) for v in i["points"]],
                    )
                    for i in p.get("items", [])
                ],
                stroke=_ink_from(p.get("stroke")),
                fill=_ink_from(p.get("fill")),
                width=float(p.get("width", 0.0)),
                closed=bool(p.get("closed", False)),
                row=None if p.get("row") is None else int(p["row"]),
            )
            for p in raw.get("paths", [])
        ],
    )


def _table_from(raw: dict | None) -> TableSpec | None:
    if not raw:
        return None
    return TableSpec(
        columns=[_column_from(c) for c in raw.get("columns", [])],
        rows=int(raw.get("rows", 0)),
        row_pitch=float(raw.get("row_pitch", 0.0)),
        row_offset=int(raw.get("row_offset", 0)),
        frame=frame_from_json(raw.get("frame")),
    )


def _field_from(raw: dict) -> FieldSpec:
    rect = raw["rect"]
    return FieldSpec(
        key=raw["key"],
        page_index=raw["page_index"],
        rect=NormRect(rect["x"], rect["y"], rect["w"], rect["h"]),
        type=FieldType(raw.get("type", "text")),
        label=raw.get("label", ""),
        align=Align(raw.get("align", "right")),
        valign=VAlign(raw["valign"]) if raw.get("valign") else None,
        rotation=int(raw.get("rotation", 0)),
        font_family=raw.get("font_family", "RuaqArabic"),
        font_weight=raw.get("font_weight", "Medium"),
        font_size_pt=float(raw.get("font_size_pt", 10.0)),
        color=raw.get("color", "#000000"),
        line_height=float(raw.get("line_height", 1.0)),
        fit=Fit(raw.get("fit", "shrink")),
        min_scale=float(raw.get("min_scale", 0.5)),
        prefix=raw.get("prefix", ""),
        suffix=raw.get("suffix", ""),
        default_value=raw.get("default_value", ""),
        calibration_dx=float(raw.get("calibration_dx", 0.0)),
        calibration_dy=float(raw.get("calibration_dy", 0.0)),
        is_required=bool(raw.get("is_required", False)),
        rtl=bool(raw.get("rtl", True)),
        preserve_aspect=bool(raw.get("preserve_aspect", False)),
        clip=raw.get("clip") or [],
        clip_holes=raw.get("clip_holes") or [],
        columns=raw.get("columns") or [],
        origin=raw.get("origin", ""),
        ornament=paths_from_json(raw.get("ornament")),
        part=part_from_json(raw.get("part")),
        row_group=raw.get("row_group", ""),
        two_lines=bool(raw.get("two_lines", False)),
        table=_table_from(raw.get("table")),
    )


def _section_from(raw: dict) -> Section:
    return Section(
        kind=SectionKind(raw["kind"]),
        first_page=raw["first_page"],
        last_page=raw["last_page"],
        name=raw.get("name", ""),
        pages_per_item=raw.get("pages_per_item", 1),
        rows_per_page=raw.get("rows_per_page", 1),
        variant=raw.get("variant"),
    )


def load(directory: Path) -> Template:
    """Load the template written by ``scripts/build_infath_templates.py``."""
    directory = Path(directory)
    manifest = json.loads((directory / "template.json").read_text(encoding="utf-8"))
    background = fitz.open(str(directory / "background.pdf"))
    width, height = manifest["page_size"]
    return Template(
        slug=manifest["slug"],
        background=background,
        fields=[_field_from(f) for f in manifest["fields"]],
        sections=[_section_from(s) for s in manifest["sections"]],
        design_page_height=float(manifest.get("design_page_height", height)),
        page_size=(float(width), float(height)),
        flavours={
            name: {int(at): int(index) for at, index in swap.items()}
            for name, swap in (manifest.get("flavours") or {}).items()
        },
    )
