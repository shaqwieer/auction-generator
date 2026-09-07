"""Job status, the rejected-row table, control actions and downloads."""

from __future__ import annotations

import io
import uuid

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import select

from app.api.deps import DB, CurrentUser, Staff, owned_or_403
from app.api.http import content_disposition
from app.models import (
    GenerationJob,
    JobStatus,
    Project,
    RecordResult,
    RecordStatus,
)
from app.schemas import JobDetail, JobOut, ResultOut, RetryRequest
from app.services import generation
from app.services.jobs import get_runner
from app.services.storage import get_storage

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _get(db: DB, user, job_id: uuid.UUID) -> GenerationJob:
    job = db.get(GenerationJob, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "المهمّة غير موجودة.")
    owned_or_403(user, job.project.client_id)
    return job


@router.get("/{job_id}", response_model=JobDetail)
def get_job(job_id: uuid.UUID, db: DB, user: CurrentUser) -> JobDetail:
    job = _get(db, user, job_id)
    detail = JobDetail.model_validate(job)
    detail.project_name = job.project.name
    detail.client_name = job.project.client.name if job.project.client else None
    return detail


@router.get("/{job_id}/results", response_model=list[ResultOut])
def list_results(
    job_id: uuid.UUID,
    db: DB,
    user: CurrentUser,
    only: str | None = Query(None, description="rejected | all"),
) -> list[RecordResult]:
    job = _get(db, user, job_id)
    query = select(RecordResult).where(RecordResult.job_id == job.id)
    if only == "rejected":
        query = query.where(RecordResult.severity == "error")
    return list(db.scalars(query.order_by(RecordResult.row_index)).all())


@router.get("/{job_id}/errors.xlsx")
def export_errors(job_id: uuid.UUID, db: DB, user: CurrentUser) -> Response:
    """The status screen's 'تصدير قائمة الأخطاء XLSX'."""
    from openpyxl import Workbook

    job = _get(db, user, job_id)
    rows = db.scalars(
        select(RecordResult)
        .where(RecordResult.job_id == job.id, RecordResult.severity == "error")
        .order_by(RecordResult.row_index)
    ).all()

    book = Workbook()
    sheet = book.active
    sheet.title = "الأخطاء"
    sheet.append(["الصفّ", "الحقل", "السبب"])
    for row in rows:
        sheet.append([row.row_index + 1, row.field_key or "", row.cause or ""])
    buffer = io.BytesIO()
    book.save(buffer)

    return Response(
        content=buffer.getvalue(),
        media_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        headers={
            "Content-Disposition": content_disposition(
                f"errors-{job.id.hex[:8]}.xlsx"
            )
        },
    )


@router.get("/{job_id}/download")
def download(job_id: uuid.UUID, db: DB, user: CurrentUser) -> StreamingResponse:
    job = _get(db, user, job_id)
    if job.status != JobStatus.SUCCEEDED or not job.output_path:
        raise HTTPException(status.HTTP_409_CONFLICT, "الملف غير جاهز بعد.")

    storage = get_storage()
    if not storage.exists(job.output_path):
        raise HTTPException(status.HTTP_410_GONE, "انتهت مدة حفظ الملف.")

    name = job.output_filename or "output.pdf"
    media = "application/zip" if name.endswith(".zip") else "application/pdf"
    payload = storage.read(job.output_path)
    return StreamingResponse(
        io.BytesIO(payload),
        media_type=media,
        headers={"Content-Disposition": content_disposition(name)},
    )


@router.get("/{job_id}/pages/{page_index}.png")
def job_page(
    job_id: uuid.UUID, page_index: int, db: DB, user: CurrentUser, dpi: int = 72
) -> Response:
    """A raster of one output page, for the preview screen's thumbnails.

    Rendered on demand rather than stored: a 120-page booklet would otherwise
    need 120 extra files, and the preview is looked at once.
    """
    import fitz

    job = _get(db, user, job_id)
    if job.status != JobStatus.SUCCEEDED or not job.output_path:
        raise HTTPException(status.HTTP_409_CONFLICT, "الملف غير جاهز بعد.")
    if (job.output_filename or "").endswith(".zip"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "المعاينة متاحة للملف المجمّع فقط، لا لحزمة ZIP.",
        )

    storage = get_storage()
    if not storage.exists(job.output_path):
        raise HTTPException(status.HTTP_410_GONE, "انتهت مدة حفظ الملف.")

    with fitz.open("pdf", storage.read(job.output_path)) as doc:
        if not 0 <= page_index < doc.page_count:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "الصفحة غير موجودة.")
        png = doc[page_index].get_pixmap(dpi=min(dpi, 150)).tobytes("png")

    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "private, max-age=300"},
    )


@router.post("/{job_id}/pause", response_model=JobOut)
def pause(job_id: uuid.UUID, db: DB, user: CurrentUser) -> GenerationJob:
    job = _get(db, user, job_id)
    if get_runner().pause(job.id):
        job.status = JobStatus.PAUSED
        db.flush()
    return job


@router.post("/{job_id}/resume", response_model=JobOut)
def resume(job_id: uuid.UUID, db: DB, user: CurrentUser) -> GenerationJob:
    job = _get(db, user, job_id)
    if get_runner().resume(job.id):
        job.status = JobStatus.RUNNING
        db.flush()
    return job


@router.post("/{job_id}/cancel", response_model=JobOut)
def cancel(job_id: uuid.UUID, db: DB, user: CurrentUser) -> GenerationJob:
    job = _get(db, user, job_id)
    get_runner().cancel(job.id)
    if job.status in (JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.PAUSED):
        job.status = JobStatus.CANCELLED
        db.flush()
    return job


@router.post(
    "/{job_id}/retry", response_model=JobOut, status_code=status.HTTP_202_ACCEPTED
)
def retry(
    job_id: uuid.UUID, payload: RetryRequest, db: DB, user: CurrentUser
) -> GenerationJob:
    """Re-run only the rows that failed, as the status screen offers."""
    job = _get(db, user, job_id)
    rows = payload.rows
    if rows is None:
        rows = sorted(
            {
                r.row_index
                for r in db.scalars(
                    select(RecordResult).where(
                        RecordResult.job_id == job.id,
                        RecordResult.status == RecordStatus.REJECTED,
                    )
                ).all()
            }
        )
    if not rows:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "لا توجد صفوف مرفوضة لإعادتها.")
    return generation.queue_job(db, job.project, only_rows=rows)


# --------------------------------------------------------------- operations


@router.get("", response_model=list[JobDetail])
def list_jobs(
    db: DB,
    _: Staff,
    status_filter: str | None = Query(None, alias="status"),
    limit: int = Query(50, le=200),
) -> list[JobDetail]:
    """The admin operations monitor."""
    query = select(GenerationJob).join(Project)
    if status_filter:
        query = query.where(GenerationJob.status == status_filter)
    rows = db.scalars(
        query.order_by(GenerationJob.created_at.desc()).limit(limit)
    ).all()
    out: list[JobDetail] = []
    for row in rows:
        detail = JobDetail.model_validate(row)
        detail.project_name = row.project.name
        detail.client_name = row.project.client.name if row.project.client else None
        out.append(detail)
    return out
