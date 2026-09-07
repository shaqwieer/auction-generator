"""Projects: the wizard from template choice through to queuing a job."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, File, HTTPException, Query, UploadFile, status
from sqlalchemy import func, select

from app.api.deps import DB, CurrentUser, owned_or_403, scope_client_id
from app.core.config import get_settings
from app.models import (
    DataRecord,
    DataSource,
    DataSourceKind,
    FieldMapping,
    GenerationJob,
    JobStatus,
    Project,
    ProjectStatus,
    Template,
    TemplateStatus,
)
from app.schemas import (
    DataSourceOut,
    ImageFieldOut,
    JobOut,
    MappingEntry,
    MappingOut,
    MappingProblem,
    MappingSave,
    PreflightOut,
    ProjectCreate,
    ProjectOut,
    ProjectUpdate,
    RecordOut,
    RecordPatch,
    RecordPhotosOut,
    RecordsSave,
    UploadResult,
)
from app.services import generation, page_plan
from app.services import mapping as mapping_service
from app.services import templates as template_service
from app.services.ingest import excel
from app.services.ingest.excel import IngestError
from app.services.storage import get_storage

router = APIRouter(prefix="/projects", tags=["projects"])
settings = get_settings()


def template_variant(template: Template) -> str | None:
    """The variant a template implies, for display.

    With حضوري, إلكتروني and هجين as three separate templates the field is no
    longer a switch -- ``compose`` filters on it and there is nothing left to
    filter -- but the review screen still names it, so it is set from the slug.
    """
    for name in ("inperson", "electronic", "hybrid"):
        if template.slug.endswith(name):
            return name
    return None


def _get(db: DB, user, project_id: uuid.UUID) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "المشروع غير موجود.")
    owned_or_403(user, project.client_id)
    return project


def _out(project: Project, record_count: int | None = None) -> ProjectOut:
    return ProjectOut.model_validate(project).model_copy(
        update={
            "record_count": (
                len(project.records) if record_count is None else record_count
            ),
            "template_name": project.template.name if project.template else None,
            "category_name": (
                project.template.category.name
                if project.template and project.template.category
                else None
            ),
        }
    )


# ----------------------------------------------------------------- CRUD


@router.get("", response_model=list[ProjectOut])
def list_projects(
    db: DB,
    user: CurrentUser,
    client_id: uuid.UUID | None = None,
    status_filter: str | None = Query(None, alias="status"),
    category_id: uuid.UUID | None = None,
    limit: int = Query(50, le=200),
    offset: int = 0,
) -> list[ProjectOut]:
    query = select(Project)
    if user.is_staff:
        if client_id is not None:
            query = query.where(Project.client_id == client_id)
    else:
        query = query.where(Project.client_id == user.client_id)
    if status_filter:
        query = query.where(Project.status == status_filter)
    if category_id is not None:
        query = query.join(Template).where(Template.category_id == category_id)

    rows = db.scalars(
        query.order_by(Project.updated_at.desc()).limit(limit).offset(offset)
    ).all()
    counts = dict(
        db.execute(
            select(DataRecord.project_id, func.count(DataRecord.id)).group_by(
                DataRecord.project_id
            )
        ).all()
    )
    return [_out(row, counts.get(row.id, 0)) for row in rows]


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
def create_project(payload: ProjectCreate, db: DB, user: CurrentUser) -> ProjectOut:
    template = db.get(Template, payload.template_id)
    if template is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "القالب غير موجود.")
    if template.status != TemplateStatus.PUBLISHED and not user.is_staff:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "القالب غير منشور.")

    project = Project(
        name=payload.name,
        template_id=template.id,
        client_id=scope_client_id(user, payload.client_id),
        created_by_id=user.id,
        variant=payload.variant or template_variant(template),
        status=ProjectStatus.DRAFT,
    )
    db.add(project)
    db.flush()

    # A template that knows what its pages are goes straight into the builder.
    # One without them is an older template, and its projects keep the
    # spreadsheet flow.
    if page_plan.supports_plan(template):
        rows = list(range(max(0, payload.lot_count)))
        for row in rows:
            db.add(DataRecord(project_id=project.id, row_index=row, values={}))
        db.flush()
        project.page_plan = page_plan.default_plan(
            template, rows=rows, cover_page=payload.cover_page
        )
        db.flush()

    return _out(project, len(project.records))


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(project_id: uuid.UUID, db: DB, user: CurrentUser) -> ProjectOut:
    return _out(_get(db, user, project_id))


# PATCH is the correct verb and works for API clients, but some browser setups
# refuse to send it after a successful preflight — the request never leaves and
# surfaces as "Failed to fetch". POST is accepted on the same handler so the web
# client has a path that always works.
@router.api_route(
    "/{project_id}", methods=["PATCH", "POST"], response_model=ProjectOut
)
def update_project(
    project_id: uuid.UUID, payload: ProjectUpdate, db: DB, user: CurrentUser
) -> ProjectOut:
    project = _get(db, user, project_id)
    changes = payload.model_dump(exclude_unset=True)
    colourway = changes.pop("lease_colourway", None)
    for name, value in changes.items():
        setattr(project, name, value)
    if colourway is not None and project.page_plan:
        # Not a plain attribute: the pages a property occupies are frozen on its
        # node, so every one of them has to be re-resolved or the booklet keeps
        # printing the colour it was created with.
        try:
            page_plan.set_lease_colourway(project, project.template, colourway)
        except page_plan.PlanError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    elif colourway is not None:
        project.lease_colourway = colourway
    db.flush()
    return _out(project)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(project_id: uuid.UUID, db: DB, user: CurrentUser) -> None:
    db.delete(_get(db, user, project_id))


# ------------------------------------------------------------ data source


@router.post("/{project_id}/datasource", response_model=UploadResult)
async def upload_datasource(
    project_id: uuid.UUID,
    db: DB,
    user: CurrentUser,
    file: UploadFile = File(...),
) -> UploadResult:
    """Parse an uploaded workbook and propose a mapping. Nothing is generated yet."""
    project = _get(db, user, project_id)
    payload = await file.read()
    if len(payload) > settings.max_upload_bytes:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"حجم الملف يتجاوز {settings.max_upload_bytes // (1024 * 1024)} ميجابايت.",
        )
    try:
        dataset = excel.read(payload, file.filename or "upload.xlsx")
    except IngestError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    key = get_storage().save(
        payload, folder=f"uploads/{project.id}", filename=file.filename or "upload.xlsx"
    )

    for existing in list(project.data_sources):
        db.delete(existing)
    for record in list(project.records):
        db.delete(record)
    db.flush()

    source = DataSource(
        project_id=project.id,
        kind=DataSourceKind.EXCEL,
        filename=file.filename or "upload.xlsx",
        stored_path=key,
        sheet=dataset.sheet,
        columns=[
            {
                "index": c.index, "name": c.name, "letter": c.letter,
                "sample": c.sample, "kind": c.kind, "tag": c.tag,
                "non_empty": c.non_empty,
            }
            for c in dataset.columns
        ],
        row_count=dataset.row_count,
        warnings=dataset.warnings,
    )
    db.add(source)

    for index, row in enumerate(dataset.rows):
        db.add(
            DataRecord(
                project_id=project.id,
                row_index=index,
                values=row,
                source=DataSourceKind.EXCEL,
            )
        )

    db.flush()
    # An import is an action inside the builder, so the rows have to land as
    # pages. Properties already in the booklet keep their layout and anything
    # typed onto them.
    page_plan.sync_lots(project, project.template, list(range(len(dataset.rows))))

    keys = template_service.record_keys(project.template)
    report = mapping_service.suggest(dataset.columns, keys)

    for entry in report.suggestions:
        db.add(
            FieldMapping(
                project_id=project.id,
                field_key=entry.field_key,
                column_name=entry.column,
            )
        )

    project.status = ProjectStatus.MAPPING
    db.flush()

    return UploadResult(
        data_source=DataSourceOut.model_validate(source),
        preview=dataset.preview,
        suggested_mapping={s.field_key: s.column for s in report.suggestions},
    )


# ---------------------------------------------------------------- mapping


def _mapping_out(db: DB, project: Project) -> MappingOut:
    keys = template_service.record_keys(project.template)
    required = template_service.required_record_keys(project.template)
    by_key = {m.field_key: m for m in project.mappings}
    entries = [
        MappingEntry(
            field_key=key,
            column=by_key[key].column_name if key in by_key else None,
            static_value=by_key[key].static_value if key in by_key else None,
        )
        for key in keys
    ]
    source = project.data_sources[0] if project.data_sources else None
    columns = (
        [excel.Column(**{k: c[k] for k in ("index", "name", "letter")},
                      sample=c.get("sample", ""), non_empty=c.get("non_empty", 0))
         for c in source.columns]
        if source
        else []
    )
    lookup = {e.field_key: (f"={e.static_value}" if e.static_value else e.column)
              for e in entries}
    problems = mapping_service.validate(lookup, columns, required)
    return MappingOut(
        entries=entries,
        problems=[
            MappingProblem(field_key=p.field_key, message=p.message, severity=p.severity)
            for p in problems
        ],
        record_keys=keys,
        required_keys=required,
    )


@router.get("/{project_id}/datasource", response_model=DataSourceOut | None)
def get_datasource(
    project_id: uuid.UUID, db: DB, user: CurrentUser
) -> DataSource | None:
    """The parsed upload, including its real column letters and order.

    The mapping screen needs these; reconstructing them from a record's values
    would lose both the spreadsheet's column order and its letters.
    """
    project = _get(db, user, project_id)
    return project.data_sources[0] if project.data_sources else None


@router.get("/{project_id}/mapping", response_model=MappingOut)
def get_mapping(project_id: uuid.UUID, db: DB, user: CurrentUser) -> MappingOut:
    return _mapping_out(db, _get(db, user, project_id))


@router.put("/{project_id}/mapping", response_model=MappingOut)
def save_mapping(
    project_id: uuid.UUID, payload: MappingSave, db: DB, user: CurrentUser
) -> MappingOut:
    project = _get(db, user, project_id)
    for existing in list(project.mappings):
        db.delete(existing)
    db.flush()
    for entry in payload.entries:
        db.add(
            FieldMapping(
                project_id=project.id,
                field_key=entry.field_key,
                column_name=entry.column,
                static_value=entry.static_value,
            )
        )
    db.flush()
    db.refresh(project)

    # Re-key the stored records so the renderer sees template keys, not headers.
    source = project.data_sources[0] if project.data_sources else None
    if source and source.kind == DataSourceKind.EXCEL:
        lookup = {
            e.field_key: (f"={e.static_value}" if e.static_value else e.column)
            for e in payload.entries
        }
        stored = db.scalars(
            select(DataRecord)
            .where(DataRecord.project_id == project.id)
            .order_by(DataRecord.row_index)
        ).all()
        raw_key = "__raw__"
        for record in stored:
            raw = record.values.get(raw_key) or record.values
            mapped = mapping_service.apply(lookup, [raw])[0]
            record.values = {**mapped, raw_key: raw}
        db.flush()

    return _mapping_out(db, project)


# ---------------------------------------------------------------- records


@router.get("/{project_id}/records", response_model=list[RecordOut])
def list_records(project_id: uuid.UUID, db: DB, user: CurrentUser) -> list[DataRecord]:
    project = _get(db, user, project_id)
    return list(project.records)


@router.put("/{project_id}/records", response_model=list[RecordOut])
def save_records(
    project_id: uuid.UUID, payload: RecordsSave, db: DB, user: CurrentUser
) -> list[DataRecord]:
    """Manual entry. Each item becomes one lot, in the order supplied."""
    project = _get(db, user, project_id)
    for existing in list(project.records):
        db.delete(existing)
    db.flush()
    for index, item in enumerate(payload.records):
        db.add(
            DataRecord(
                project_id=project.id,
                row_index=index,
                values=item.values,
                source=DataSourceKind.MANUAL,
            )
        )
    if project.status == ProjectStatus.DRAFT:
        project.status = ProjectStatus.MAPPING
    db.flush()
    page_plan.sync_lots(
        project, project.template, list(range(len(payload.records)))
    )
    db.flush()
    db.refresh(project)
    return list(project.records)


@router.api_route(
    "/{project_id}/records/{row_index}",
    methods=["PATCH", "POST"],
    response_model=RecordOut,
)
def patch_record(
    project_id: uuid.UUID,
    row_index: int,
    payload: RecordPatch,
    db: DB,
    user: CurrentUser,
) -> DataRecord:
    """Merge values into one record.

    The photo step sets a single field on a single row, so a full replace would
    be both wasteful and racy when two rows are edited in quick succession.
    """
    project = _get(db, user, project_id)
    record = db.scalar(
        select(DataRecord).where(
            DataRecord.project_id == project.id, DataRecord.row_index == row_index
        )
    )
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "السجلّ غير موجود.")
    # Reassign rather than mutate: SQLAlchemy does not track in-place JSONB edits.
    record.values = {**record.values, **payload.values}
    db.flush()
    return record


@router.get("/{project_id}/photos", response_model=RecordPhotosOut)
def get_photos(
    project_id: uuid.UUID, db: DB, user: CurrentUser
) -> RecordPhotosOut:
    """The image fields this template needs, and what each row has so far."""
    project = _get(db, user, project_id)
    return RecordPhotosOut(
        fields=[
            ImageFieldOut(key=key, label=label, scope=scope, is_required=required)
            for key, label, scope, required in template_service.image_fields(
                project.template
            )
        ],
        records=[RecordOut.model_validate(r) for r in project.records],
        static_values=project.static_values,
    )


# ------------------------------------------------------- review & generate


@router.get("/{project_id}/preflight", response_model=PreflightOut)
def get_preflight(project_id: uuid.UUID, db: DB, user: CurrentUser) -> PreflightOut:
    project = _get(db, user, project_id)
    check = generation.preflight(db, project)
    return PreflightOut(
        record_count=check.record_count,
        generatable=check.generatable,
        predicted_pages=check.predicted_pages,
        rejected=check.rejected,
        missing_assets=check.missing_assets,
    )


@router.post(
    "/{project_id}/generate", response_model=JobOut, status_code=status.HTTP_202_ACCEPTED
)
def generate(project_id: uuid.UUID, db: DB, user: CurrentUser) -> JobOut:
    """Queue a job and return immediately. The status screen polls for progress."""
    project = _get(db, user, project_id)
    if not project.records:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "لا توجد بيانات للتوليد.")

    # The admin settings screen advertises a per-client concurrency limit, so
    # enforce it here rather than letting a client fill every engine.
    active = db.scalar(
        select(func.count(GenerationJob.id))
        .join(Project, GenerationJob.project_id == Project.id)
        .where(
            Project.client_id == project.client_id,
            GenerationJob.status.in_(
                [JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.PAUSED]
            ),
        )
    )
    if (active or 0) >= settings.concurrent_jobs_per_client:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"لديك {active} عملية توليد جارية — الحدّ الأقصى "
            f"{settings.concurrent_jobs_per_client}. انتظر انتهاءها ثم أعد المحاولة.",
        )

    job = generation.queue_job(db, project)
    return JobOut.model_validate(job)
