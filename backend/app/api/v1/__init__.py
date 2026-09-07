"""The v1 API surface."""

from fastapi import APIRouter

from app.api.v1 import (
    assets,
    auth,
    builder,
    catalog,
    company,
    dashboard,
    jobs,
    projects,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(catalog.router)
api_router.include_router(projects.router)
api_router.include_router(builder.router)
api_router.include_router(jobs.router)
api_router.include_router(assets.router)
api_router.include_router(company.router)
api_router.include_router(dashboard.router)

__all__ = ["api_router"]
