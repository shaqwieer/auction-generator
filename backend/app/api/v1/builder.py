"""The step-by-step booklet builder.

One project, one plan, and the operations a client performs on it: choose a
cover, add a property, switch it between قياسي and برج, turn its optional pages
on or off, type into a page, drop a photograph onto it, and watch the page
redraw.

Every mutation carries the plan revision it was built on and gets it back. The
builder patches values on a debounce while the page rail can be reordering, so
without that check the later write silently wins and the reorder disappears.

The preview renders through the same engine and the same baked artwork as a real
job, so what the client sees is what will print.
"""

from __future__ import annotations

import io
import uuid

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile, status
from PIL import Image
from sqlalchemy import select

from app.api.deps import DB, CurrentUser, owned_or_403
from app.core.config import get_settings
from app.models import Asset, DataRecord, Project
from app.rendering.compose import booklet_facts
from app.schemas import (
    AssetOut,
    NodeAdd,
    NodeEnabled,
    NodeLayout,
    NodeLeaseRows,
    NodeMove,
    NodeValues,
    PagePlanOut,
    TemplateFieldOut,
    TemplatePageOut,
)
from app.services import generation, links, page_plan, preview
from app.services import templates as template_service
from app.services.storage import get_storage

router = APIRouter(prefix="/projects", tags=["builder"])
settings = get_settings()

ALLOWED_IMAGES = {"image/jpeg", "image/png", "image/webp", "image/tiff"}


def _project(db: DB, user, project_id: uuid.UUID) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "المشروع غير موجود.")
    owned_or_403(user, project.client_id)
    return project


def _planned(db: DB, user, project_id: uuid.UUID) -> Project:
    project = _project(db, user, project_id)
    if not project.page_plan:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "هذا المشروع أُنشئ قبل الباني — استخدم شاشات الاستيراد.",
        )
    return project


def _guard(action) -> dict:
    """Turn a plan refusal into a 409 with its Arabic message intact."""
    try:
        return action()
    except page_plan.PlanError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


def _node(project: Project, node_id: str) -> dict:
    node = next(
        (n for n in (project.page_plan or {}).get("nodes", []) if n["id"] == node_id),
        None,
    )
    if node is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "الصفحة غير موجودة.")
    return node


def _plan_out(db: DB, project: Project) -> PagePlanOut:
    template = project.template
    by_page: dict[int, list[TemplateFieldOut]] = {}
    for field in template.fields:
        by_page.setdefault(field.page_index, []).append(
            TemplateFieldOut.model_validate(field)
        )
    plan = project.page_plan or {"revision": 0, "nodes": []}
    return PagePlanOut(
        revision=int(plan.get("revision", 0)),
        nodes=plan.get("nodes", []),
        pages=[TemplatePageOut.model_validate(p) for p in template.pages],
        fields_by_page=by_page,
        record_keys=template_service.record_keys(template),
        predicted_pages=page_plan.predicted_pages(project, project.records),
        booklet=booklet_facts(
            dict(project.static_values or {}),
            plan.get("nodes", []),
            project.name,
        ),
    )


@router.get("/{project_id}/plan", response_model=PagePlanOut)
def get_plan(project_id: uuid.UUID, db: DB, user: CurrentUser) -> PagePlanOut:
    """Everything the builder needs to draw the booklet, in one round trip."""
    return _plan_out(db, _planned(db, user, project_id))


@router.post("/{project_id}/plan/nodes", response_model=PagePlanOut)
def add_node(
    project_id: uuid.UUID, payload: NodeAdd, db: DB, user: CurrentUser
) -> PagePlanOut:
    project = _planned(db, user, project_id)
    _guard(lambda: page_plan.check_revision(project, payload.revision))

    row = payload.row
    if payload.kind == "lot" and row is None:
        # A new property needs a row to hold its values.
        used = {r.row_index for r in project.records}
        row = max(used) + 1 if used else 0
        db.add(DataRecord(project_id=project.id, row_index=row, values={}))
        db.flush()
        # The relationship was loaded before the insert, and the predicted page
        # count is computed from it.
        db.expire(project, ["records"])

    _guard(
        lambda: page_plan.add_node(
            project,
            project.template,
            kind=payload.kind,
            after=payload.after,
            page=payload.page,
            row=row,
            layout=payload.layout,
        )
    )
    db.flush()
    return _plan_out(db, project)


@router.post("/{project_id}/plan/nodes/{node_id}/duplicate", response_model=PagePlanOut)
def duplicate_node(
    project_id: uuid.UUID, node_id: str, payload: NodeMove, db: DB, user: CurrentUser
) -> PagePlanOut:
    project = _planned(db, user, project_id)
    _guard(lambda: page_plan.check_revision(project, payload.revision))

    node = _node(project, node_id)
    new_row: int | None = None
    if node.get("kind") == "lot":
        # A copy is a second property, not a second view of the first. Sharing
        # the record would print it twice in the summary table.
        source = db.scalar(
            select(DataRecord).where(
                DataRecord.project_id == project.id,
                DataRecord.row_index == node["row"],
            )
        )
        used = {r.row_index for r in project.records}
        new_row = (max(used) + 1) if used else 0
        db.add(
            DataRecord(
                project_id=project.id,
                row_index=new_row,
                values=dict(source.values or {}) if source else {},
            )
        )
        db.flush()
        db.expire(project, ["records"])

    _guard(lambda: page_plan.duplicate_node(project, node_id, new_row=new_row))
    db.flush()
    return _plan_out(db, project)


@router.post("/{project_id}/plan/nodes/{node_id}/move", response_model=PagePlanOut)
def move_node(
    project_id: uuid.UUID, node_id: str, payload: NodeMove, db: DB, user: CurrentUser
) -> PagePlanOut:
    project = _planned(db, user, project_id)
    _guard(lambda: page_plan.check_revision(project, payload.revision))
    _guard(lambda: page_plan.move_node(project, node_id, payload.delta))
    db.flush()
    return _plan_out(db, project)


@router.delete("/{project_id}/plan/nodes/{node_id}", response_model=PagePlanOut)
def delete_node(
    project_id: uuid.UUID, node_id: str, db: DB, user: CurrentUser
) -> PagePlanOut:
    project = _planned(db, user, project_id)
    _guard(lambda: page_plan.delete_node(project, node_id))
    db.flush()
    return _plan_out(db, project)


@router.api_route(
    "/{project_id}/plan/nodes/{node_id}/leases",
    methods=["PATCH", "POST"],
    response_model=PagePlanOut,
)
def set_lease_rows(
    project_id: uuid.UUID,
    node_id: str,
    payload: NodeLeaseRows,
    db: DB,
    user: CurrentUser,
) -> PagePlanOut:
    """The lease contracts this property carries.

    Typed rather than derived: بيان العقارات builds itself from the booklet's
    properties, but nothing in the system knows what leases an asset has.
    """
    project = _planned(db, user, project_id)
    _guard(lambda: page_plan.check_revision(project, payload.revision))
    _guard(lambda: page_plan.set_lease_rows(project, node_id, payload.rows))
    db.flush()
    return _plan_out(db, project)


@router.post("/{project_id}/plan/nodes/{node_id}/enabled", response_model=PagePlanOut)
def set_enabled(
    project_id: uuid.UUID,
    node_id: str,
    payload: NodeEnabled,
    db: DB,
    user: CurrentUser,
) -> PagePlanOut:
    """Take a page out of this issue of the booklet, or put it back.

    Not a delete. A client who says "not this one" means it should not print,
    not that the half hour they spent filling it in should go.
    """
    project = _planned(db, user, project_id)
    _guard(lambda: page_plan.check_revision(project, payload.revision))
    _guard(lambda: page_plan.set_enabled(project, node_id, on=payload.on))
    db.flush()
    return _plan_out(db, project)


@router.post("/{project_id}/plan/nodes/{node_id}/layout", response_model=PagePlanOut)
def set_layout(
    project_id: uuid.UUID,
    node_id: str,
    payload: NodeLayout,
    db: DB,
    user: CurrentUser,
) -> PagePlanOut:
    """Switch a property between قياسي and برج, toggle its optional pages, or
    change the summary table's colour."""
    project = _planned(db, user, project_id)
    _guard(lambda: page_plan.check_revision(project, payload.revision))
    _guard(
        lambda: page_plan.set_layout(
            project,
            project.template,
            node_id,
            layout=payload.layout,
            options=payload.options,
            page=payload.page,
        )
    )
    db.flush()
    return _plan_out(db, project)


@router.api_route(
    "/{project_id}/plan/nodes/{node_id}/values",
    methods=["PATCH", "POST"],
    response_model=PagePlanOut,
)
def set_values(
    project_id: uuid.UUID,
    node_id: str,
    payload: NodeValues,
    db: DB,
    user: CurrentUser,
) -> PagePlanOut:
    """Merge values into one page.

    A property's own values go to its record, so that a later spreadsheet
    import and the summary table both see them; everything else belongs to the
    page it was typed on.
    """
    project = _planned(db, user, project_id)
    _guard(lambda: page_plan.check_revision(project, payload.revision))

    node = _node(project, node_id)

    if node.get("kind") == "lot":
        record = db.scalar(
            select(DataRecord).where(
                DataRecord.project_id == project.id,
                DataRecord.row_index == node["row"],
            )
        )
        if record is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "سجلّ العقار غير موجود.")
        # Reassigned, not mutated: SQLAlchemy does not track in-place JSONB edits.
        record.values = {**(record.values or {}), **payload.values}
        # Bump the revision anyway, so a concurrent reorder still conflicts.
        _guard(lambda: page_plan.set_values(project, node_id, {}))
    else:
        _guard(lambda: page_plan.set_values(project, node_id, payload.values))

    db.flush()
    return _plan_out(db, project)


@router.post(
    "/{project_id}/plan/nodes/{node_id}/photo",
    response_model=AssetOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_node_photo(
    project_id: uuid.UUID,
    node_id: str,
    db: DB,
    user: CurrentUser,
    field_key: str = Form(...),
    file: UploadFile = File(...),
) -> Asset:
    """Store a photograph and point one field on one page at it.

    Uploading and assigning are one action here. The library screen is gone;
    a photograph arrives because somebody dropped it onto a page, and leaving
    it stored but unassigned would just be a file nobody can find.
    """
    project = _planned(db, user, project_id)

    payload = await file.read()
    if not payload:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "الملف فارغ.")
    if len(payload) > settings.max_upload_bytes:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"حجم الصورة يتجاوز "
            f"{settings.max_upload_bytes // (1024 * 1024)} ميجابايت.",
        )
    try:
        with Image.open(io.BytesIO(payload)) as image:
            width, height = image.size
            content_type = Image.MIME.get(image.format or "", "")
    except Exception as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "تعذّرت قراءة الصورة."
        ) from exc
    if content_type not in ALLOWED_IMAGES:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "صيغة غير مدعومة — استخدم JPEG أو PNG أو WebP أو TIFF.",
        )

    name = file.filename or "image"
    asset = db.scalar(
        select(Asset).where(
            Asset.client_id == project.client_id, Asset.filename == name
        )
    )
    if asset is None:
        stored = get_storage().save(
            payload, folder=f"assets/{project.client_id}", filename=name
        )
        asset = Asset(
            client_id=project.client_id,
            filename=name,
            stored_path=stored,
            content_type=content_type,
            width=width,
            height=height,
            size_bytes=len(payload),
            role="lot",
            uploaded_by_id=user.id,
        )
        db.add(asset)
        db.flush()

    # A record refers to its photograph by filename, so that is what is stored.
    node = _node(project, node_id)
    if node.get("kind") == "lot":
        record = db.scalar(
            select(DataRecord).where(
                DataRecord.project_id == project.id,
                DataRecord.row_index == node["row"],
            )
        )
        if record is not None:
            record.values = {**(record.values or {}), field_key: asset.filename}
        # Bumped even though nothing on the plan changed: the preview is
        # addressed by revision, so without this the page keeps the raster it
        # had and the photograph appears only when something else is typed.
        _guard(lambda: page_plan.set_values(project, node_id, {}))
    else:
        _guard(
            lambda: page_plan.set_values(project, node_id, {field_key: asset.filename})
        )
    db.flush()
    return asset


@router.get("/{project_id}/plan/nodes/{node_id}/preview.png")
def node_preview(
    project_id: uuid.UUID,
    node_id: str,
    db: DB,
    user: CurrentUser,
    dpi: int = 96,
    page: int | None = None,
    omit: str | None = None,
) -> Response:
    """One page of the booklet as it will print.

    ``page`` picks which of a property's pages to draw when it has more than
    one; without it the first is drawn.

    ``omit`` leaves one field off. The builder asks for that while somebody is
    typing into the field on the page: the page underneath is the authoritative
    render, so drawing the value there *and* in the input over it printed it
    twice, in two different fonts, a few points apart. Leaving the hole means
    what the client sees while typing is their own text, in the place it will
    print, over the page it will print on. The cache key is the values being
    drawn, so the variant is an ordinary entry rather than a special case.
    """
    project = _planned(db, user, project_id)
    pages = _guard(
        lambda: page_plan.instances_for_node(project, project.records, node_id)
    )
    instance = next(
        (p for p in pages if page is None or p.template_page_index == page),
        pages[0],
    )
    if omit and omit in instance.values:
        instance.values = {
            key: value for key, value in instance.values.items() if key != omit
        }
    # Mints the permanent address behind any link this page carries, so the
    # builder shows the code that will actually be printed rather than a
    # stand-in. A read that writes, but what it writes is an identifier that has
    # to be the same one for ever, so it may as well exist from first sight.
    links.apply_codes(db, project, [instance])
    assets = generation.assets_for_project(db, project)

    try:
        png, key, _ = preview.render_page(project, instance, dpi=dpi, assets=assets)
    except preview.PreviewError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc

    return Response(
        content=png,
        media_type="image/png",
        headers={
            "ETag": f'"{key}"',
            "Cache-Control": "private, max-age=0, must-revalidate",
        },
    )
