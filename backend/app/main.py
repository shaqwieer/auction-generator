"""FastAPI application entrypoint."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse

from app.api.deps import DB
from app.api.v1 import api_router
from app.core.config import get_settings
from app.services import links
from app.services.ingest.excel import IngestError
from app.services.jobs import get_runner

settings = get_settings()
logging.basicConfig(level=logging.INFO if settings.debug else logging.WARNING)
log = logging.getLogger("matbaa")


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_runner().start()
    log.info("started %s engines", settings.worker_count)
    yield


app = FastAPI(
    title="Matbaa API",
    version="1.0.0",
    description="Fills fixed Arabic print templates from Excel or manual entry.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(IngestError)
async def ingest_error(request: Request, exc: IngestError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok", "environment": settings.environment}


@app.get("/r/{code}", tags=["links"])
def follow(code: str, db: DB) -> RedirectResponse:
    """Where a printed code leads.

    Deliberately outside the API and deliberately unauthenticated: this is the
    address on the paper, scanned by whoever picks the booklet up. It is also
    the reason the paper never needs reprinting when a destination moves — the
    code stays, the row it resolves through changes.

    A temporary redirect, not a permanent one: a browser that cached a 301 would
    keep going to yesterday's destination for ever, which is exactly the thing
    this exists to prevent.
    """
    target = links.resolve(db, code)
    if not target:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "الرابط غير موجود.")
    return RedirectResponse(target, status_code=status.HTTP_307_TEMPORARY_REDIRECT)


app.include_router(api_router)
