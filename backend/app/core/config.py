"""Application settings, read from the environment."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Matbaa"
    environment: str = "development"
    debug: bool = True

    # Postgres in development and in production. The default points at the
    # compose stack's published port so `uvicorn` works without extra setup.
    database_url: str = Field(
        default="postgresql+psycopg://matbaa:matbaa@localhost:55432/matbaa"
    )
    # The API test suite creates and drops this database on the same server.
    test_database_url: str = Field(
        default="postgresql+psycopg://matbaa:matbaa@localhost:55432/matbaa_test"
    )

    #: What a printed QR code points at, before the path. A code outlives the
    #: booklet it is printed in -- that is the whole reason it redirects rather
    #: than carrying a destination -- so this is a deployment setting and never
    #: a request's own host: the address on the paper has to keep working when
    #: the API is reached some other way. Set it before the first real print run.
    public_base_url: str = Field(default="http://localhost:8000")

    secret_key: str = Field(default="change-me-in-production")
    algorithm: str = "HS256"
    access_token_minutes: int = 60
    refresh_token_days: int = 14

    # Everything the application writes lives under one directory: the template
    # artwork, the spreadsheets that were uploaded, the client's photographs and
    # the generated booklets. Nothing but paths goes in the database.
    #
    # In development that is ``backend/var`` -- the same directory the dev
    # server, the build script and the compose stack all use, so a template
    # built on the host is immediately visible to the container.
    #
    # In production it is a bind-mounted host directory (``/srv/matbaa/var``),
    # never a Docker named volume: a bind mount survives ``docker compose
    # down``, can be backed up with ordinary tools, and needs no `docker cp` to
    # get files in or out.
    #
    # Set VAR_ROOT to move all of it. STORAGE_ROOT and TEMPLATES_ROOT override
    # one half each, for the rare case where the artwork and the output belong
    # on different disks.
    var_root: Path = BACKEND_ROOT / "var"
    storage_root: Path = BACKEND_ROOT / "var" / "storage"
    templates_root: Path = BACKEND_ROOT / "var" / "templates"

    @model_validator(mode="after")
    def _derive_roots(self) -> Settings:
        """Hang the two roots off ``var_root`` unless they were set explicitly."""
        if "storage_root" not in self.model_fields_set:
            self.storage_root = self.var_root / "storage"
        if "templates_root" not in self.model_fields_set:
            self.templates_root = self.var_root / "templates"
        return self

    # Mirrors the admin settings screen.
    max_upload_bytes: int = 25 * 1024 * 1024
    max_rows_per_file: int = 5_000
    min_image_dpi: int = 300
    output_retention_days: int = 180
    concurrent_jobs_per_client: int = 2
    worker_count: int = 3

    # localhost and 127.0.0.1 are distinct origins to the browser, and a
    # developer may reach the dev server by either name.
    cors_origins: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

    @property
    def sync_database_url(self) -> str:
        return self.database_url


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.storage_root.mkdir(parents=True, exist_ok=True)
    settings.templates_root.mkdir(parents=True, exist_ok=True)
    return settings
