"""Aggregates for the client home screen and the admin dashboard."""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter
from sqlalchemy import func, select

from app.api.deps import DB, CurrentUser, Staff
from app.core.db import utcnow
from app.models import (
    Client,
    DataRecord,
    GenerationJob,
    JobStatus,
    Project,
    Template,
)
from app.schemas import DashboardOut, JobOut, StatOut

router = APIRouter(tags=["dashboard"])

ACTIVE = (JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.PAUSED)


def _jobs_query(user):
    query = select(GenerationJob).join(Project)
    if not user.is_staff:
        query = query.where(Project.client_id == user.client_id)
    return query


def _usage(db: DB, user, days: int = 7) -> list[dict]:
    """Pages generated per day, for the seven-day bar chart."""
    since = utcnow() - timedelta(days=days)
    rows = db.scalars(
        _jobs_query(user).where(GenerationJob.created_at >= since)
    ).all()
    buckets: dict[str, int] = {}
    for offset in range(days - 1, -1, -1):
        day = (utcnow() - timedelta(days=offset)).strftime("%Y-%m-%d")
        buckets[day] = 0
    for job in rows:
        day = job.created_at.strftime("%Y-%m-%d")
        if day in buckets:
            buckets[day] += job.page_count
    return [{"day": day, "pages": pages} for day, pages in buckets.items()]


@router.get("/dashboard", response_model=DashboardOut)
def dashboard(db: DB, user: CurrentUser) -> DashboardOut:
    month_start = utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    finished = db.scalars(
        _jobs_query(user).where(GenerationJob.status == JobStatus.SUCCEEDED)
    ).all()
    this_month = [j for j in finished if j.created_at >= month_start]
    pages = sum(j.page_count for j in this_month)

    template_query = select(func.count()).select_from(Template)
    if not user.is_staff:
        template_query = template_query.where(
            (Template.client_id.is_(None)) | (Template.client_id == user.client_id)
        )
    templates = db.scalar(template_query) or 0

    durations = [
        (j.finished_at - j.started_at).total_seconds()
        for j in finished
        if j.finished_at and j.started_at
    ]
    average = sum(durations) / len(durations) if durations else 0.0

    stats = [
        StatOut(label="ملفات وُلّدت", value=str(len(this_month))),
        StatOut(label="صفحات مطبوعة", value=f"{pages:,}"),
        StatOut(label="قوالب متاحة لك", value=str(templates)),
        StatOut(
            label="متوسّط زمن التوليد",
            value=f"{int(average // 60):02d}:{int(average % 60):02d}",
        ),
    ]

    running = db.scalars(
        _jobs_query(user)
        .where(GenerationJob.status.in_(ACTIVE))
        .order_by(GenerationJob.created_at.desc())
    ).all()
    recent = db.scalars(
        _jobs_query(user).order_by(GenerationJob.created_at.desc()).limit(8)
    ).all()

    return DashboardOut(
        stats=stats,
        running_jobs=[JobOut.model_validate(j) for j in running],
        recent_jobs=[JobOut.model_validate(j) for j in recent],
        usage=_usage(db, user),
    )


@router.get("/ops/summary")
def ops_summary(db: DB, _: Staff) -> dict:
    """Engine health and queue depth for the operations monitor."""
    from app.core.config import get_settings
    from app.services.jobs import get_runner

    settings = get_settings()
    counts = dict(
        db.execute(
            select(GenerationJob.status, func.count(GenerationJob.id)).group_by(
                GenerationJob.status
            )
        ).all()
    )
    since = utcnow() - timedelta(hours=24)
    last_day = db.scalars(
        select(GenerationJob).where(GenerationJob.created_at >= since)
    ).all()

    return {
        "engines_total": settings.worker_count,
        "engines_up": settings.worker_count if get_runner()._started else 0,
        "queued": counts.get(JobStatus.QUEUED, 0),
        "running": counts.get(JobStatus.RUNNING, 0),
        "jobs_24h": len(last_day),
        "failed_24h": sum(1 for j in last_day if j.status == JobStatus.FAILED),
        "clients": db.scalar(select(func.count()).select_from(Client)) or 0,
        "records": db.scalar(select(func.count()).select_from(DataRecord)) or 0,
    }
