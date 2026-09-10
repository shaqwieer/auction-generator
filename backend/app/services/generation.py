"""Run a generation job: database rows in, print-ready PDF out.

The job owns its own session because it runs on a worker thread. Progress is
written back as it goes so the status screen can poll, and every rejection is
stored with its row index, field key and readable cause.
"""

from __future__ import annotations

import io
import uuid
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal, utcnow
from app.models import (
    Asset,
    DataRecord,
    GenerationJob,
    JobStatus,
    Project,
    ProjectStatus,
    RecordResult,
    RecordStatus,
)
from app.rendering.base import RenderPlan
from app.rendering.compose import compose, page_count
from app.rendering.overlay import PyMuPDFOverlayRenderer
from app.services import links, page_plan
from app.services import templates as template_service
from app.services.jobs import JobHandle, get_runner
from app.services.storage import get_storage


@dataclass
class Preflight:
    """What the review screen shows before the operator commits."""

    record_count: int
    predicted_pages: int
    rejected: dict[int, list[str]]
    missing_assets: list[str]

    @property
    def generatable(self) -> int:
        return self.record_count - len(self.rejected)


def _referenced_assets(project: Project, records: list[dict]) -> set[str]:
    """Filenames the image fields of this project actually point at.

    The plan's own values count too. A photograph the client dropped onto the
    cover, or onto a property's صور إضافية page, belongs to that page rather
    than to any spreadsheet row; missing it here reports the file as absent in
    preflight and then quietly drops it at render time.
    """
    image_keys = {f.key for f in project.template.fields if f.type == "image"}
    sources = [
        project.static_values,
        # The company's mark is computed from the account rather than stored on
        # the project, so nothing else in here would ever mention it — and an
        # asset nobody mentions is reported missing and then quietly dropped.
        page_plan.branding(project),
        page_plan.referenced_values(project),
        *records,
    ]
    wanted: set[str] = set()
    for values in sources:
        for key in image_keys:
            name = str((values or {}).get(key, "") or "").strip()
            if name:
                wanted.add(name)
    return wanted


def _assets_for(
    session: Session, project: Project, wanted: set[str]
) -> dict[str, bytes]:
    """Load only the photographs this run refers to.

    A client's library is phone photography -- single frames run to 20MB -- so
    reading the whole library into memory would cost hundreds of megabytes for a
    booklet that uses three of them.
    """
    if not wanted:
        return {}
    storage = get_storage()
    rows = session.scalars(
        select(Asset).where(
            Asset.client_id == project.client_id, Asset.filename.in_(wanted)
        )
    ).all()
    out: dict[str, bytes] = {}
    for asset in rows:
        try:
            out[asset.filename] = storage.read(asset.stored_path)
        except (FileNotFoundError, ValueError):
            continue
    return out


class LazyAssets(Mapping[str, bytes]):
    """The photographs a render *may* ask for, read only when it asks.

    The builder redraws one page per keystroke, and every redraw used to read
    every photograph in the booklet: a twenty-property issue is twenty phone
    frames, several hundred megabytes off disk, to draw a page carrying one of
    them. Worse, it happened before the preview cache was consulted, so even a
    page that was already rastered paid for the lot.

    The names are known up front — that is what the cache key is built from and
    what preflight reports missing — so only the bytes are deferred. A file that
    has gone from storage is absent rather than an error, which is what the
    eager loader did too: the renderer reports it as a missing image and the
    page still draws.
    """

    def __init__(self, session: Session, project: Project, names: set[str]) -> None:
        self._session = session
        self._project = project
        self._names = frozenset(names)
        self._loaded: dict[str, bytes] = {}

    def __iter__(self):
        return iter(sorted(self._names))

    def __len__(self) -> int:
        return len(self._names)

    def __getitem__(self, name: str) -> bytes:
        if name not in self._names:
            raise KeyError(name)
        if name not in self._loaded:
            found = _assets_for(self._session, self._project, {name})
            if name not in found:
                raise KeyError(name)
            self._loaded[name] = found[name]
        return self._loaded[name]


def assets_for_project(session: Session, project: Project) -> Mapping[str, bytes]:
    """Every photograph this project refers to, read when it is drawn.

    Public because the builder's preview draws through the same renderer over
    the same artwork, and so needs the same images.
    """
    records = [dict(r.values or {}) for r in project.records]
    return LazyAssets(session, project, _referenced_assets(project, records))


def preflight(session: Session, project: Project) -> Preflight:
    template = project.template
    records = [r.values for r in project.records]
    required = template_service.required_record_keys(template)

    rejected: dict[int, list[str]] = {}
    for index, values in enumerate(records):
        missing = [k for k in required if not str(values.get(k, "")).strip()]
        if missing:
            rejected[index] = missing

    known = {a.filename for a in session.scalars(
        select(Asset).where(Asset.client_id == project.client_id)
    ).all()}
    referenced = _referenced_assets(project, records)

    if project.page_plan:
        predicted = page_plan.predicted_pages(project, project.records)
    else:
        _, sections = template_service.specs_for(template)
        predicted = page_count(sections, len(records), variant=project.variant)

    return Preflight(
        record_count=len(records),
        predicted_pages=predicted,
        rejected=rejected,
        missing_assets=sorted(referenced - known),
    )


def queue_job(session: Session, project: Project, *, only_rows: list[int] | None = None) -> GenerationJob:
    """Create a job row and hand it to the runner. Returns immediately."""
    check = preflight(session, project)
    job = GenerationJob(
        project_id=project.id,
        status=JobStatus.QUEUED,
        total_records=(
            len(only_rows) if only_rows is not None else check.record_count
        ),
    )
    session.add(job)
    project.status = ProjectStatus.QUEUED
    session.flush()
    job_id = job.id
    session.commit()

    get_runner().submit(job_id, lambda handle: run_job(job_id, handle, only_rows))
    return job


def run_job(
    job_id: uuid.UUID,
    handle: JobHandle | None = None,
    only_rows: list[int] | None = None,
) -> None:
    """Execute a queued job. Safe to call directly in tests."""
    session = SessionLocal()
    try:
        job = session.get(GenerationJob, job_id)
        if job is None:
            return
        project = job.project
        template = project.template

        job.status = JobStatus.RUNNING
        job.engine = _engine_name()
        job.started_at = utcnow()
        session.commit()

        try:
            _render(session, job, project, template, handle, only_rows)
        except Exception as exc:
            job.status = JobStatus.FAILED
            job.finished_at = utcnow()
            job.error_summary = f"{type(exc).__name__}: {exc}"
            project.status = ProjectStatus.FAILED
            _log(job, "error", str(exc))
            session.commit()
    finally:
        session.close()


def _engine_name() -> str:
    import threading

    return threading.current_thread().name.upper()


def _log(job: GenerationJob, level: str, message: str) -> None:
    entry = {
        "at": datetime.now(UTC).strftime("%H:%M:%S"),
        "level": level,
        "message": message,
    }
    job.log = [*(job.log or []), entry][-200:]


def _render(
    session: Session,
    job: GenerationJob,
    project: Project,
    template,
    handle: JobHandle | None,
    only_rows: list[int] | None,
) -> None:
    fields, sections = template_service.specs_for(template)
    fields = template_service.for_output(fields, project.output_flavour)
    required = template_service.required_record_keys(template)

    rows = session.scalars(
        select(DataRecord)
        .where(DataRecord.project_id == project.id)
        .order_by(DataRecord.row_index)
    ).all()
    if only_rows is not None:
        retry_rows = set(only_rows)
        rows = [r for r in rows if r.row_index in retry_rows]

    # Rows missing a required value never reach the renderer -- the review screen
    # already told the operator they would be excluded.
    accepted: list[DataRecord] = []
    for row in rows:
        missing = [k for k in required if not str(row.values.get(k, "")).strip()]
        if missing:
            job.rejected_records += 1
            session.add(
                RecordResult(
                    job_id=job.id,
                    row_index=row.row_index,
                    status=RecordStatus.REJECTED,
                    field_key=missing[0],
                    cause=f"قيمة «{missing[0]}» مطلوبة وفارغة — استُبعد الصفّ.",
                    severity="error",
                )
            )
        else:
            accepted.append(row)
    session.commit()

    if handle is not None:
        handle.wait_if_paused()
        if handle.cancelled.is_set():
            job.status = JobStatus.CANCELLED
            job.finished_at = utcnow()
            session.commit()
            return

    background = template_service.open_background(template)
    storage = get_storage()
    try:
        referenced = _referenced_assets(project, [r.values for r in accepted])
        assets = _assets_for(session, project, referenced)
        renderer = PyMuPDFOverlayRenderer()

        if project.output_mode == "per_record":
            payload, pages = _render_per_record(
                renderer, background, fields, sections, project,
                accepted, assets, job, session, handle,
            )
            filename = f"{project.name or 'booklet'}.zip"
        else:
            payload, pages = _render_merged(
                renderer, background, fields, sections, project,
                accepted, assets, job, session,
            )
            filename = f"{project.name or 'booklet'}.pdf"

        if handle is not None and handle.cancelled.is_set():
            job.status = JobStatus.CANCELLED
            job.finished_at = utcnow()
            session.commit()
            return

        key = storage.save(payload, folder=f"outputs/{project.id}", filename=filename)
        job.output_path = key
        job.output_filename = filename
        job.output_bytes = len(payload)
        job.page_count = pages
        job.status = JobStatus.SUCCEEDED
        job.finished_at = utcnow()
        project.status = ProjectStatus.READY
        _log(job, "info", f"job finished · {pages} pages · {len(payload)} bytes")
        session.commit()
    finally:
        background.close()


def _record_issues(
    session: Session, job: GenerationJob, issues, row_lookup: dict[int, int]
) -> None:
    for issue in issues:
        row = issue.row_index
        session.add(
            RecordResult(
                job_id=job.id,
                row_index=row_lookup.get(row, row if row is not None else -1),
                status=(
                    RecordStatus.REJECTED
                    if issue.severity == "error"
                    else RecordStatus.OK
                ),
                field_key=issue.field_key,
                cause=issue.cause,
                severity=issue.severity,
            )
        )


def _render_merged(
    renderer, background, fields, sections, project, accepted, assets, job, session
):
    if project.page_plan:
        pages = page_plan.to_instances(project, accepted)
    else:
        pages = compose(
            sections,
            [r.values for r in accepted],
            static_values=project.static_values,
            variant=project.variant,
        )
    links.apply_codes(session, project, pages)
    plan = RenderPlan(
        background=background,
        fields=fields,
        pages=template_service.drawn_as(
            pages,
            template_service.pages_for_output(
                project.template, project.output_flavour
            ),
        ),
        assets=assets,
        design_page_height=project.template.design_page_height,
    )
    result = renderer.render(plan)

    lookup = {i: row.row_index for i, row in enumerate(accepted)}
    _record_issues(session, job, result.issues, lookup)
    job.completed_records = len(accepted)
    _log(job, "info", f"rendered {result.page_count} pages")
    session.commit()
    return result.pdf, result.page_count


def _render_per_record(
    renderer, background, fields, sections, project, accepted, assets,
    job, session, handle,
):
    buffer = io.BytesIO()
    total_pages = 0
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for position, row in enumerate(accepted):
            if handle is not None:
                handle.wait_if_paused()
                if handle.cancelled.is_set():
                    break
            if project.page_plan:
                # One property's own pages only: the covers, the summary table
                # and the closing pages belong to the booklet, not to a lot.
                pages = [
                    page
                    for page in page_plan.to_instances(project, [row])
                    if page.record_index == row.row_index
                ]
            else:
                pages = compose(
                    sections,
                    [row.values],
                    static_values=project.static_values,
                    variant=project.variant,
                )
            links.apply_codes(session, project, pages)
            plan = RenderPlan(
                background=background,
                fields=fields,
                pages=template_service.drawn_as(
                    pages,
                    template_service.pages_for_output(
                        project.template, project.output_flavour
                    ),
                ),
                assets=assets,
                design_page_height=project.template.design_page_height,
            )
            result = renderer.render(plan)
            _record_issues(session, job, result.issues, {0: row.row_index})

            name = str(row.values.get("deed_number") or row.row_index + 1)
            archive.writestr(f"{position + 1:03d}_{name}.pdf", result.pdf)
            total_pages += result.page_count

            job.completed_records = position + 1
            job.page_count = total_pages
            if position % 5 == 0 or position == len(accepted) - 1:
                session.commit()
    session.commit()
    return buffer.getvalue(), total_pages
