"""Turn an uploaded design file into a template, and bake it on publish.

The order matters. Baking clears the sample content out of the artwork, and it
can only clear what a field will later draw over — so it cannot run at upload
time, when nothing has been confirmed yet. Instead:

    upload   → keep the original, propose fields from its geometry
    edit     → an admin confirms, renames, adds and removes regions
    publish  → bake the original using the confirmed rects, then serve that

That also makes publishing repeatable: the original is never modified, so an
admin can re-publish after changing a field and get a correctly baked background
every time.
"""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass
from pathlib import Path

import fitz
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (
    Template,
    TemplateField,
    TemplateSection,
    TemplateStatus,
)
from app.rendering.autokey import suggest
from app.rendering.bake import bake_document
from app.rendering.base import FieldType, NormRect, SectionKind
from app.rendering.derive import DerivedField, derive_document
from app.rendering.fonts import FontError, brand_registry
from app.rendering.tables import derive_tables, to_norm

MAX_PAGES = 200
ACCEPTED_SUFFIXES = {".pdf", ".ai"}


class BuildError(RuntimeError):
    """The upload cannot be turned into a template."""


@dataclass
class IngestReport:
    template: Template
    pages: int
    proposed_fields: int
    auto_named: int
    tables: int


def _slugify(name: str, fallback: str) -> str:
    """An ASCII directory name for a template.

    Arabic names have no ASCII to keep, so rather than collapsing every one of
    them to "template", "template_2", "template_3" the fallback carries a short
    digest of the name — stable, distinct, and still obviously a slug. The
    human-readable identity lives in ``name`` and ``code``.
    """
    kept = [c if (c.isalnum() and c.isascii()) else "_" for c in name.lower()]
    slug = "_".join(part for part in "".join(kept).split("_") if part)
    if slug:
        return slug[:40]
    digest = hashlib.sha256(name.encode("utf-8")).hexdigest()[:8]
    return f"{fallback}_{digest}"


def _unique_slug(session: Session, base: str) -> str:
    slug, n = base, 2
    while session.scalar(select(Template).where(Template.slug == slug)):
        slug, n = f"{base}_{n}", n + 1
    return slug


def open_design(data: bytes, filename: str) -> fitz.Document:
    """Open an uploaded design. Illustrator files are PDF-compatible."""
    suffix = Path(filename).suffix.lower()
    if suffix not in ACCEPTED_SUFFIXES:
        raise BuildError(
            f"صيغة غير مدعومة: {suffix or '؟'} — ارفع ملف .ai أو .pdf من المصمّم."
        )
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise BuildError(f"تعذّرت قراءة ملف التصميم: {exc}") from exc
    if doc.page_count == 0:
        raise BuildError("ملف التصميم لا يحتوي على صفحات.")
    if doc.page_count > MAX_PAGES:
        doc.close()
        raise BuildError(f"عدد الصفحات {doc.page_count} يتجاوز الحدّ {MAX_PAGES}.")
    return doc


def _field_rows(
    template_id, derived: dict[int, list[DerivedField]], page_rect: fitz.Rect
) -> tuple[list[TemplateField], int]:
    """Create fields only for regions we can genuinely stand behind.

    Every text run on a page is a *candidate*, but most of them are the design's
    own labels and body copy. Turning all of them into fields buries the editor
    (340 on the auction booklet) and blocks publishing, because the artwork
    references fonts we do not ship and only need to *preserve*, not redraw.

    So: create a field when the printed label matches the vocabulary, or when the
    region is an image, link or table. Everything else stays a suggestion the
    admin can click to add — see the suggestions endpoint.
    """
    rows: list[TemplateField] = []
    auto_named = 0

    for page_index, candidates in derived.items():
        named = {id(s.field): s for s in suggest(candidates) if s.role == "value"}
        for index, candidate in enumerate(candidates):
            hit = named.get(id(candidate))
            if hit:
                auto_named += 1
            elif candidate.type is FieldType.TEXT:
                continue  # design copy, not data
            rows.append(
                TemplateField(
                    template_id=template_id,
                    key=hit.key if hit else f"p{page_index}_{candidate.type.value}_{index}",
                    label=hit.label if hit else "",
                    page_index=page_index,
                    type=candidate.type.value,
                    x=candidate.rect.x,
                    y=candidate.rect.y,
                    w=candidate.rect.w,
                    h=candidate.rect.h,
                    align=candidate.align.value,
                    rotation=candidate.rotation,
                    font_family=candidate.font_family,
                    font_weight=candidate.font_weight,
                    font_size_pt=candidate.font_size_pt,
                    color=candidate.color,
                    is_required=False,
                    origin=(
                        f"autokey:{hit.label}" if hit else "derived:unnamed"
                    ),
                )
            )
    return rows, auto_named


def _table_rows(
    template_id, doc: fitz.Document, page_rect: fitz.Rect
) -> list[TemplateField]:
    """Recover any repeating table blocks as single table fields."""
    rows: list[TemplateField] = []
    for page_index in range(doc.page_count):
        offset = 0
        for block_no, block in enumerate(derive_tables(doc, page_index)):
            payload = to_norm(block, page_rect)
            body = block.first_row_pt | block.row_rect(block.rows - 1)
            norm = NormRect.from_points(body, page_rect)
            rows.append(
                TemplateField(
                    template_id=template_id,
                    key=f"__table__{page_index}_{block_no}",
                    label="جدول",
                    page_index=page_index,
                    type=FieldType.TABLE.value,
                    x=norm.x,
                    y=norm.y,
                    w=norm.w,
                    h=norm.h,
                    origin=f"table:block={block_no}/rows={block.rows}",
                    table_spec={
                        "rows": payload["rows"],
                        "row_pitch": payload["row_pitch"],
                        "row_offset": offset,
                        "columns": payload["columns"],
                    },
                )
            )
            offset += block.rows
    return rows


def ingest(
    session: Session,
    data: bytes,
    filename: str,
    *,
    name: str,
    category_id=None,
    client_id=None,
) -> IngestReport:
    """Store an uploaded design and propose fields from its own geometry."""
    settings = get_settings()
    doc = open_design(data, filename)
    try:
        page_rect = doc[0].rect
        slug = _unique_slug(session, _slugify(name, "template"))

        directory = settings.templates_root / slug
        directory.mkdir(parents=True, exist_ok=True)
        source_path = directory / "source.pdf"
        source_path.write_bytes(data)

        template = Template(
            slug=slug,
            name=name,
            code=slug.upper().replace("_", "-")[:40],
            status=TemplateStatus.DRAFT,
            version=1,
            page_width=round(page_rect.width, 2),
            page_height=round(page_rect.height, 2),
            design_page_height=round(page_rect.height, 2),
            page_count=doc.page_count,
            source_filename=filename,
            background_path=None,  # set when published
            category_id=category_id,
            client_id=client_id,
            fonts=[],
        )
        session.add(template)
        session.flush()

        # One fixed section over everything; the admin marks the repeating block.
        session.add(
            TemplateSection(
                template_id=template.id,
                name="كل الصفحات",
                kind=SectionKind.FIXED.value,
                first_page=0,
                last_page=doc.page_count - 1,
                position=0,
            )
        )

        derived = derive_document(doc)
        rows, auto_named = _field_rows(template.id, derived, page_rect)
        tables = _table_rows(template.id, doc, page_rect)
        for row in [*rows, *tables]:
            session.add(row)

        template.fonts = sorted(
            {f"{r.font_family}-{r.font_weight}" for r in rows if r.font_family}
        )
        session.flush()

        return IngestReport(
            template=template,
            pages=doc.page_count,
            proposed_fields=len(rows) + len(tables),
            auto_named=auto_named,
            tables=len(tables),
        )
    finally:
        doc.close()


def suggestions(template: Template) -> list[dict]:
    """Regions on the design that are not yet fields, for click-to-add.

    Re-derived from the original each time rather than stored, so it always
    reflects the file on disk and needs no extra column.
    """
    source = source_path_for(template)
    if not source.exists():
        return []
    claimed = {
        (f.page_index, round(f.x, 4), round(f.y, 4)) for f in template.fields
    }
    out: list[dict] = []
    doc = fitz.open(str(source))
    try:
        for page_index, candidates in derive_document(doc).items():
            for candidate in candidates:
                key = (page_index, round(candidate.rect.x, 4), round(candidate.rect.y, 4))
                if key in claimed:
                    continue
                out.append(
                    {
                        "page_index": page_index,
                        "type": candidate.type.value,
                        "x": candidate.rect.x,
                        "y": candidate.rect.y,
                        "w": candidate.rect.w,
                        "h": candidate.rect.h,
                        "align": candidate.align.value,
                        "rotation": candidate.rotation,
                        "font_family": candidate.font_family,
                        "font_weight": candidate.font_weight,
                        "font_size_pt": candidate.font_size_pt,
                        "color": candidate.color,
                        "sample_text": candidate.sample_text[:60],
                    }
                )
    finally:
        doc.close()
    return out


def source_path_for(template: Template) -> Path:
    return get_settings().templates_root / template.slug / "source.pdf"


def publish(session: Session, template: Template) -> Template:
    """Validate the fonts, bake the artwork, and mark the template published.

    Baking happens here rather than at upload because only now do we know which
    regions are fields. The original is left untouched so this can be repeated.
    """
    if not template.fields:
        raise BuildError("لا يمكن نشر قالب بلا حقول.")

    registry = brand_registry()
    problems: list[str] = []
    for field in template.fields:
        if field.type != FieldType.TEXT.value:
            continue
        try:
            face = registry.face(field.font_family, field.font_weight)
        except FontError as exc:
            problems.append(str(exc))
            continue
        problems.extend(registry.validate(face))
    if problems:
        raise BuildError(" · ".join(sorted(set(problems))))

    source = source_path_for(template)
    if not source.exists():
        raise BuildError("ملف التصميم الأصلي غير موجود — أعِد رفعه.")

    doc = fitz.open(str(source))
    try:
        page_rect = doc[0].rect
        regions: dict[int, list[tuple[fitz.Rect, FieldType]]] = {}
        for field in template.fields:
            kind = FieldType(field.type)
            if kind is FieldType.TABLE:
                for cell in _table_cells(field, page_rect):
                    regions.setdefault(field.page_index, []).append(
                        (cell, FieldType.TEXT)
                    )
                continue
            rect = NormRect(field.x, field.y, field.w, field.h).to_points(page_rect)
            regions.setdefault(field.page_index, []).append((rect, kind))

        report = bake_document(doc, regions)
        directory = source.parent
        background = directory / "background.pdf"
        doc.save(str(background), garbage=4, deflate=True, clean=True)
    finally:
        doc.close()

    template.background_path = str(background.resolve())
    template.status = TemplateStatus.PUBLISHED
    template.version += 1
    session.flush()
    del report
    return template


def unpublish(session: Session, template: Template) -> Template:
    """Withdraw a published template from the catalogue, without unbaking it.

    The baked background stays, on disk and on the row. Projects already built
    from this template render from that file, and ``open_background`` raises
    rather than falling back to the designer's export, so dropping it here would
    break every existing project instead of merely taking the template out of
    circulation. Nor is the version bumped: nothing about the artwork changed.

    Publishing again re-bakes from the untouched original, so this is reversible
    -- and it is currently the only withdrawal the product has: the status enum
    carries an ``archived`` state that a re-import leaves alone, but nothing sets
    it. Note that a re-import *does* republish a draft, so a rebuild or a seed run
    undoes this.
    """
    if template.status != TemplateStatus.PUBLISHED:
        raise BuildError("القالب ليس منشورًا.")
    template.status = TemplateStatus.DRAFT
    session.flush()
    return template


def _table_cells(field: TemplateField, page_rect: fitz.Rect) -> list[fitz.Rect]:
    spec = field.table_spec or {}
    pitch = float(spec.get("row_pitch", 0.0)) * page_rect.height
    out: list[fitz.Rect] = []
    for row in range(int(spec.get("rows", 0))):
        shift = row * pitch
        for column in spec.get("columns", []):
            rect = NormRect(**column["rect"]).to_points(page_rect)
            out.append(rect + (0, shift, 0, shift))
    return out


def render_page(template: Template, page_index: int, dpi: int = 96) -> bytes:
    """A PNG of one template page, for the editor canvas.

    Draws the published background when there is one, otherwise the original —
    a draft still shows its sample content, which is what an admin needs while
    deciding which regions are variable.
    """
    path = (
        Path(template.background_path)
        if template.background_path and Path(template.background_path).exists()
        else source_path_for(template)
    )
    if not path.exists():
        raise BuildError("ملف التصميم غير موجود.")
    doc = fitz.open(str(path))
    try:
        if not 0 <= page_index < doc.page_count:
            raise BuildError(f"الصفحة {page_index + 1} غير موجودة.")
        buffer = io.BytesIO(doc[page_index].get_pixmap(dpi=dpi).tobytes("png"))
        return buffer.getvalue()
    finally:
        doc.close()
