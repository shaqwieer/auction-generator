"""Move templates between the build artefacts, the database and the renderer.

``scripts/build_infath_templates.py`` writes a template as a background PDF plus
a manifest. :func:`import_template` loads that into the database; :func:`load`
turns database rows back into the objects the renderer expects. Keeping both
directions here means the renderer never learns about SQLAlchemy.
"""

from __future__ import annotations

import json
from pathlib import Path

import fitz
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (
    Category,
    Template,
    TemplateField,
    TemplatePage,
    TemplateSection,
    TemplateStatus,
)
from app.rendering.base import (
    FieldSpec,
    FieldType,
    NormRect,
    SectionKind,
    TableColumn,
    TableSpec,
)
from app.rendering.compose import Section
from app.rendering.shaping import Align, Fit, VAlign


class TemplateError(RuntimeError):
    pass


# ------------------------------------------------------------------ import


def import_template(
    session: Session,
    directory: Path,
    *,
    category_slug: str = "booklet",
    name: str | None = None,
) -> Template:
    """Load a built template directory into the database.

    Re-importing a revised design **updates the existing row in place** and bumps
    its version. It must not delete and recreate: projects reference the template
    with ``ondelete=RESTRICT``, so a rebuild would either fail or orphan every
    booklet already generated from it. Sections and fields are replaced wholesale,
    which is what a design revision actually means.
    """
    directory = Path(directory)
    manifest_path = directory / "template.json"
    if not manifest_path.exists():
        raise TemplateError(f"no template.json in {directory}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    slug = manifest["slug"]
    category = session.scalar(select(Category).where(Category.slug == category_slug))
    width, height = manifest["page_size"]
    fonts = sorted(
        {
            f"{f.get('font_family')}-{f.get('font_weight')}"
            for f in manifest["fields"]
            if f.get("font_family")
        }
    )

    template = session.scalar(select(Template).where(Template.slug == slug))
    if template is None:
        template = Template(slug=slug, code=slug.upper().replace("_", "-"), version=1)
        session.add(template)
    else:
        template.version += 1
        for section in list(template.sections):
            session.delete(section)
        for existing_field in list(template.fields):
            session.delete(existing_field)
        for existing_page in list(template.pages):
            session.delete(existing_page)
        session.flush()

    template.name = name or template.name or slug.replace("_", " ").title()
    # Archiving is an operator's decision about whether a template should still
    # be offered. Re-importing a revised design must not quietly undo it --
    # otherwise a superseded template comes back every time the seed runs.
    if template.status != TemplateStatus.ARCHIVED:
        template.status = TemplateStatus.PUBLISHED
    template.page_width = float(width)
    template.page_height = float(height)
    template.design_page_height = float(manifest.get("design_page_height", height))
    template.page_count = int(manifest["page_count"])
    template.source_filename = manifest.get("source")
    template.background_path = str((directory / "background.pdf").resolve())
    template.fonts = fonts
    template.category_id = category.id if category else None
    session.flush()

    for position, raw in enumerate(manifest["sections"]):
        session.add(
            TemplateSection(
                template_id=template.id,
                name=raw.get("name", ""),
                kind=raw["kind"],
                first_page=raw["first_page"],
                last_page=raw["last_page"],
                pages_per_item=raw.get("pages_per_item", 1),
                rows_per_page=raw.get("rows_per_page", 1),
                variant=raw.get("variant"),
                position=position,
            )
        )

    # What each page is, so the builder can offer covers, layouts and the
    # optional per-property pages. Older manifests predate this and simply have
    # none; a template with no page rows falls back to its section plan.
    for position, raw in enumerate(manifest.get("pages", [])):
        session.add(
            TemplatePage(
                template_id=template.id,
                page_index=int(raw["page_index"]),
                role=raw["role"],
                slot=raw.get("slot", ""),
                layout=raw.get("layout", ""),
                name=raw.get("name", ""),
                is_optional=bool(raw.get("is_optional", False)),
                default_on=bool(raw.get("default_on", True)),
                options=raw.get("options") or {},
                position=int(raw.get("position", position)),
            )
        )

    for raw in manifest["fields"]:
        rect = raw["rect"]
        session.add(
            TemplateField(
                template_id=template.id,
                key=raw["key"],
                label=raw.get("label", ""),
                page_index=raw["page_index"],
                type=raw.get("type", "text"),
                x=rect["x"],
                y=rect["y"],
                w=rect["w"],
                h=rect["h"],
                align=raw.get("align", "right"),
                valign=raw.get("valign"),
                rotation=int(raw.get("rotation", 0)),
                font_family=raw.get("font_family", "RuaqArabic"),
                font_weight=raw.get("font_weight", "Medium"),
                font_size_pt=float(raw.get("font_size_pt", 10.0)),
                color=raw.get("color", "#000000"),
                line_height=float(raw.get("line_height", 1.0)),
                fit=raw.get("fit", "shrink"),
                min_scale=float(raw.get("min_scale", 0.5)),
                calibration_dx=float(raw.get("calibration_dx", 0.0)),
                calibration_dy=float(raw.get("calibration_dy", 0.0)),
                is_required=bool(raw.get("is_required", False)),
                rtl=bool(raw.get("rtl", True)),
                preserve_aspect=bool(raw.get("preserve_aspect", False)),
                clip=raw.get("clip") or None,
                clip_holes=raw.get("clip_holes") or None,
                origin=raw.get("origin", ""),
                table_spec=raw.get("table"),
            )
        )

    session.flush()
    return template


# -------------------------------------------------------------------- load


def field_to_spec(row: TemplateField) -> FieldSpec:
    table = None
    if row.table_spec:
        table = TableSpec(
            columns=[
                TableColumn(
                    key=c["key"],
                    rect=NormRect(**c["rect"]),
                    label=c.get("label", ""),
                    align=Align(c.get("align", "center")),
                    valign=VAlign(c["valign"]) if c.get("valign") else None,
                    font_family=c.get("font_family", "RuaqArabic"),
                    font_weight=c.get("font_weight", "Medium"),
                    font_size_pt=float(c.get("font_size_pt", 8.0)),
                    color=c.get("color", "#001447"),
                    fit=Fit(c.get("fit", "shrink")),
                    rtl=bool(c.get("rtl", True)),
                    source=c.get("source", ""),
                )
                for c in row.table_spec.get("columns", [])
            ],
            rows=int(row.table_spec.get("rows", 0)),
            row_pitch=float(row.table_spec.get("row_pitch", 0.0)),
            row_offset=int(row.table_spec.get("row_offset", 0)),
        )
    return FieldSpec(
        key=row.key,
        page_index=row.page_index,
        rect=NormRect(row.x, row.y, row.w, row.h),
        type=FieldType(row.type),
        label=row.label,
        align=Align(row.align),
        valign=VAlign(row.valign) if row.valign else None,
        rotation=row.rotation,
        font_family=row.font_family,
        font_weight=row.font_weight,
        font_size_pt=row.font_size_pt,
        color=row.color,
        line_height=row.line_height,
        fit=Fit(row.fit),
        min_scale=row.min_scale,
        calibration_dx=row.calibration_dx,
        calibration_dy=row.calibration_dy,
        is_required=row.is_required,
        rtl=row.rtl,
        preserve_aspect=row.preserve_aspect,
        clip=list(row.clip or []),
        clip_holes=list(row.clip_holes or []),
        origin=row.origin,
        table=table,
    )


def section_to_spec(row: TemplateSection) -> Section:
    return Section(
        kind=SectionKind(row.kind),
        first_page=row.first_page,
        last_page=row.last_page,
        name=row.name,
        pages_per_item=row.pages_per_item,
        rows_per_page=row.rows_per_page,
        variant=row.variant,
    )


#: The two things a booklet can be. On paper a link has to be a code somebody
#: scans; on screen a code is useless and the chip should simply be clickable.
#: The pages are the same either way -- only which of the two fields sitting on
#: each chip gets drawn changes.
PRINT = "print"
ELECTRONIC = "electronic"


def for_output(fields: list[FieldSpec], flavour: str) -> list[FieldSpec]:
    """Drop the half of each link chip this output does not use."""
    unwanted = FieldType.LINK if flavour == PRINT else FieldType.QR
    return [f for f in fields if f.type is not unwanted]


def specs_for(template: Template) -> tuple[list[FieldSpec], list[Section]]:
    return (
        [field_to_spec(f) for f in template.fields],
        [section_to_spec(s) for s in template.sections],
    )


def open_background(template: Template) -> fitz.Document:
    if not template.background_path:
        raise TemplateError(f"template {template.slug} has no background artwork")
    path = Path(template.background_path)
    if not path.exists():
        # Fall back to the conventional location so a container rebuild that
        # moved the volume does not brick every template.
        path = get_settings().templates_root / template.slug / "background.pdf"
    if not path.exists():
        raise TemplateError(f"background artwork missing for {template.slug}")
    return fitz.open(str(path))


def record_keys(template: Template) -> list[str]:
    """Field keys a data row supplies, in first-appearance order."""
    per_record_pages = {
        page
        for section in template.sections
        if section.kind == SectionKind.PER_RECORD
        for page in range(section.first_page, section.last_page + 1)
    }
    table_keys: list[str] = []
    for field in template.fields:
        if field.type == FieldType.TABLE and field.table_spec:
            table_keys.extend(
                c["key"]
                for c in field.table_spec.get("columns", [])
                if not c.get("source")
            )

    seen: dict[str, None] = {}
    for field in template.fields:
        if field.page_index in per_record_pages and field.type != FieldType.TABLE:
            seen.setdefault(field.key, None)
    for key in table_keys:
        seen.setdefault(key, None)
    return list(seen)


def static_keys(template: Template) -> list[str]:
    """Keys that belong to the project rather than to any one record."""
    record = set(record_keys(template))
    seen: dict[str, None] = {}
    for field in template.fields:
        if field.type == FieldType.TABLE:
            continue
        if field.key not in record:
            seen.setdefault(field.key, None)
    return list(seen)


def required_record_keys(template: Template) -> list[str]:
    record = set(record_keys(template))
    return sorted(
        {
            f.key
            for f in template.fields
            if f.is_required and f.key in record and f.type != FieldType.IMAGE
        }
    )


def image_fields(template: Template) -> list[tuple[str, str, str, bool]]:
    """Image fields as (key, label, scope, required), de-duplicated by key.

    Scope decides where the operator sets it: a "record" photo is asked once per
    lot, a "project" photo (the cover) once for the whole booklet.
    """
    per_record = set(record_keys(template))
    seen: dict[str, tuple[str, str, str, bool]] = {}
    for field in template.fields:
        if field.type != FieldType.IMAGE:
            continue
        scope = "record" if field.key in per_record else "project"
        current = seen.get(field.key)
        required = field.is_required or bool(current and current[3])
        seen[field.key] = (field.key, field.label or field.key, scope, required)
    return list(seen.values())
