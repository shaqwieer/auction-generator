"""Shared fixtures. Tests run against the client's real artwork where present."""

from __future__ import annotations

import io
import os
import sys
from pathlib import Path

import fitz
import pytest
from openpyxl import Workbook

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
PROJECT = BACKEND.parent

fitz.TOOLS.mupdf_display_errors(False)


def _find_sample(pages: int) -> Path | None:
    """Locate a designer export by page count.

    The exports live under ``references/`` with Arabic filenames that no longer
    survive a round trip through the filesystem intact, so they are found by
    shape rather than by name. The project root is searched second only because
    an export once sat there; every test that skips because nothing matched is a
    test that silently stopped running, so keep both roots.
    """
    for root in (PROJECT / "references", PROJECT):
        for candidate in sorted(root.glob("*.pdf")):
            try:
                with fitz.open(candidate) as doc:
                    if doc.page_count == pages:
                        return candidate
            except Exception:
                # A stray or corrupt PDF beside the samples is not a failure.
                continue
    return None


@pytest.fixture(scope="session")
def sample_path() -> Path:
    path = _find_sample(16)
    if path is None:
        pytest.skip("in-person auction booklet export not available")
    return path


@pytest.fixture(scope="session")
def hybrid_path() -> Path:
    """The hybrid export -- the superset carrying both lot flavours."""
    path = _find_sample(21)
    if path is None:
        pytest.skip("hybrid auction booklet export not available")
    return path


@pytest.fixture(scope="session")
def covers_dir() -> Path:
    """The six alternative booklet covers from the brand guide."""
    for directory in sorted((PROJECT / "references").glob("*")):
        candidate = directory / "Ai"
        if candidate.is_dir() and len(list(candidate.glob("*.ai"))) >= 6:
            return candidate
    pytest.skip("booklet cover designs not available")


@pytest.fixture
def sample_doc(sample_path: Path):
    doc = fitz.open(sample_path)
    yield doc
    doc.close()


#: The in-person booklet, built from the designer's export by
#: ``scripts/build_infath_templates.py``. Its first seven pages line up with the
#: export's, so the artwork tests still compare like with like.
TEMPLATE_SLUG = "auction_infath_inperson"


@pytest.fixture(scope="session")
def template_dir() -> Path:
    path = BACKEND / "var" / "templates" / TEMPLATE_SLUG
    if not (path / "template.json").exists():
        pytest.skip("template not built; run scripts/build_infath_templates.py")
    return path


@pytest.fixture(scope="session")
def registry():
    from app.rendering.fonts import brand_registry

    return brand_registry()


@pytest.fixture(scope="module")
def database_url(request) -> str:
    """A throwaway Postgres database, created and dropped around each module.

    Postgres is the only supported dialect in development and production, so the
    API tests run against a real server rather than a stand-in. Tests that do not
    touch the database are unaffected and still run anywhere.

    One database *per module* rather than per session: these tests create clients,
    categories and templates, and deactivate them again. Sharing a database would
    make the suite order-dependent, where a rename in one file breaks a count in
    another.
    """
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url
    from sqlalchemy.exc import OperationalError

    from app.core.config import get_settings

    base = make_url(get_settings().test_database_url)
    suffix = request.module.__name__.rsplit(".", 1)[-1].replace("test_", "")
    url = base.set(database=f"{base.database}_{suffix}")
    name = url.database
    # A guard against ever dropping a real database: the name must be derived
    # from the configured test database, which itself ends in _test.
    assert base.database and base.database.endswith("_test"), (
        f"TEST_DATABASE_URL must name a database ending in _test, got {base.database!r}"
    )
    assert name and name.startswith(base.database), (
        f"refusing to manage {name!r}: it is not derived from {base.database!r}"
    )

    admin = create_engine(
        url.set(database="postgres"),
        isolation_level="AUTOCOMMIT",
        future=True,
        # Without a timeout an unreachable host stalls the whole run instead of
        # skipping, which is the difference between "no database" and "hung".
        connect_args={"connect_timeout": 5},
    )
    try:
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
            connection.execute(text(f'CREATE DATABASE "{name}"'))
    except OperationalError as exc:
        admin.dispose()
        pytest.skip(
            "Postgres is not reachable — start it with "
            f"`docker compose up -d db` ({exc.orig})"
        )

    yield url.render_as_string(hide_password=False)

    with admin.connect() as connection:
        connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    admin.dispose()


# A mixed Arabic/English/numeral line -- the shape every renderer change must
# still get right.
ARABIC = "مزاد أعيان حائل"
MIXED = "رقم الصك 542104012563 - المساحة 308.75 م"
LONG_ARABIC = (
    "العقار عبارة عن فيلا سكنية مكونة من دورين وملحق وصالة وأربع غرف "
    "ومطبخ ومستودع ودورتي مياه ومجلس بسقف هنقر في الارتداد الجنوبي"
)


PNG_MAGIC = bytes([0x89, 0x50, 0x4E, 0x47])


HEADERS = [
    "رقم الصك", "نوع العقار", "المدينة", "الحي",
    "المساحة م٢", "شيك الدخول", "رقم المخطط", "رقم القطعة", "وصف العقار",
]

ROWS = [
    ["442108021305", "فيلا", "حائل", "الملك عبدالله", 875, "10,000", 553, 110,
     "فيلا سكنية مكونة من دورين وملحق."],
    ["542104012563", "أرض سكنية", "حائل", "الخطة", 308.75, "3,000", 389, 711,
     "أرض سكنية على شارعين."],
    ["660675003193", "أرض مسورة", "حائل", "الحائط", 1130.451, "20,000", 2020, 6111,
     "أرض مسورة بمخطط معتمد."],
]


def workbook_bytes() -> bytes:
    book = Workbook()
    sheet = book.active
    sheet.title = "العقارات"
    sheet.append(HEADERS)
    for row in ROWS:
        sheet.append(row)
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


@pytest.fixture(scope="module")
def client(tmp_path_factory, database_url):
    """A live app against this module's own database and storage root."""
    root = tmp_path_factory.mktemp("api")
    os.environ["DATABASE_URL"] = database_url
    # One variable moves everything the app writes into this module's own
    # throwaway directory. Redirecting only STORAGE_ROOT left the template
    # ingest writing into the developer's real backend/var/templates -- a
    # 127MB source.pdf per run, which is where the stray `template_<hash>`
    # directories came from.
    os.environ["VAR_ROOT"] = str(root)

    import app.core.config as config_module

    config_module.get_settings.cache_clear()

    from app.core.db import Base, get_engine, reset_engine

    reset_engine()
    import app.models

    Base.metadata.create_all(get_engine())

    import app.services.storage as storage_module

    storage_module._default = None

    template_dir = BACKEND / "var" / "templates" / TEMPLATE_SLUG
    if not (template_dir / "template.json").exists():
        pytest.skip("template not built; run scripts/build_infath_templates.py")

    from sqlalchemy import select

    from app.core.db import SessionLocal
    from app.core.security import hash_password
    from app.models import Category, Client, Role, User
    from app.services.templates import import_template

    session = SessionLocal()
    try:
        session.add(Category(slug="booklet", name="كتيّبات"))
        owner = Client(name="أعيان", code="AAYAN")
        session.add(owner)
        session.flush()
        session.add_all(
            [
                User(
                    email="admin@matbaa.sa", name="مشرف",
                    password_hash=hash_password("secret12"), role=Role.ADMIN,
                ),
                # Staff, but not an admin: the role that separates "may prepare
                # a template" from "may publish one".
                User(
                    email="sara@matbaa.sa", name="سارة",
                    password_hash=hash_password("secret12"), role=Role.OPERATOR,
                ),
                User(
                    email="noura@aayan.sa", name="نورة",
                    password_hash=hash_password("secret12"), role=Role.CLIENT,
                    client_id=owner.id,
                ),
            ]
        )
        import_template(session, template_dir, name="كتيّب المزاد")
        session.commit()
        del select
    finally:
        session.close()

    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client

    config_module.get_settings.cache_clear()
    reset_engine()
    os.environ.pop("DATABASE_URL", None)
    os.environ.pop("VAR_ROOT", None)


def auth(client, email="noura@aayan.sa", password="secret12") -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture(scope="module")
def project(client):
    headers = auth(client)
    template_id = client.get("/api/v1/templates", headers=headers).json()[0]["id"]
    response = client.post(
        "/api/v1/projects",
        headers=headers,
        json={"name": "مزاد أعيان حائل", "template_id": template_id},
    )
    assert response.status_code == 201, response.text
    return response.json()
