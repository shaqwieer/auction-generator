"""The full client journey over HTTP: sign in, upload, map, generate, download."""

from __future__ import annotations

import time
import uuid

from tests.conftest import (
    BACKEND,
    HEADERS,
    PNG_MAGIC,
    ROWS,
    TEMPLATE_SLUG,
    auth,
    workbook_bytes,
)

# --------------------------------------------------------------------- auth


def test_health_needs_no_token(client):
    assert client.get("/health").json()["status"] == "ok"


def test_bad_credentials_do_not_say_which_half_was_wrong(client):
    wrong_password = client.post(
        "/api/v1/auth/login", json={"email": "noura@aayan.sa", "password": "nope1234"}
    )
    unknown_user = client.post(
        "/api/v1/auth/login", json={"email": "ghost@aayan.sa", "password": "secret12"}
    )
    assert wrong_password.status_code == unknown_user.status_code == 401
    assert wrong_password.json()["detail"] == unknown_user.json()["detail"]


def test_protected_routes_reject_anonymous_callers(client):
    assert client.get("/api/v1/projects").status_code == 401
    assert client.get("/api/v1/dashboard").status_code == 401


def test_me_returns_the_signed_in_user(client):
    body = client.get("/api/v1/auth/me", headers=auth(client)).json()
    assert body["email"] == "noura@aayan.sa"
    assert body["role"] == "client"
    assert body["client_id"]


def test_clients_list_is_staff_only(client):
    assert client.get("/api/v1/clients", headers=auth(client)).status_code == 403
    staff = auth(client, "admin@matbaa.sa")
    assert client.get("/api/v1/clients", headers=staff).status_code == 200


def test_refresh_token_cannot_be_used_as_an_access_token(client):
    tokens = client.post(
        "/api/v1/auth/login", json={"email": "noura@aayan.sa", "password": "secret12"}
    ).json()
    bad = {"Authorization": f"Bearer {tokens['refresh_token']}"}
    assert client.get("/api/v1/auth/me", headers=bad).status_code == 401

    refreshed = client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert refreshed.status_code == 200
    good = {"Authorization": f"Bearer {refreshed.json()['access_token']}"}
    assert client.get("/api/v1/auth/me", headers=good).status_code == 200


# ---------------------------------------------------------------- catalogue


def test_template_detail_exposes_the_keys_the_wizard_needs(client):
    headers = auth(client)
    templates = client.get("/api/v1/templates", headers=headers).json()
    assert templates, "the seeded template should be visible to the client"

    detail = client.get(
        f"/api/v1/templates/{templates[0]['id']}", headers=headers
    ).json()
    assert "deed_number" in detail["record_keys"]
    assert "deed_number" in detail["required_keys"]
    assert detail["field_count"] > 20
    assert any(f["type"] == "table" for f in detail["fields"])


# ------------------------------------------------------------ the full flow


def test_project_starts_as_a_draft(project):
    assert project["status"] == "draft"
    assert project["record_count"] == 0


def test_upload_parses_columns_and_proposes_a_mapping(client, project):
    headers = auth(client)
    response = client.post(
        f"/api/v1/projects/{project['id']}/datasource",
        headers=headers,
        files={
            "file": (
                "lots.xlsx",
                workbook_bytes(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["data_source"]["row_count"] == 3
    assert body["data_source"]["sheet"] == "العقارات"
    assert [c["letter"] for c in body["data_source"]["columns"][:3]] == ["A", "B", "C"]
    assert len(body["preview"]) == 3

    suggested = body["suggested_mapping"]
    assert suggested["deed_number"] == "رقم الصك"
    assert suggested["property_type"] == "نوع العقار"
    assert suggested["city"] == "المدينة"


def test_rejects_a_file_that_is_not_a_spreadsheet(client, project):
    response = client.post(
        f"/api/v1/projects/{project['id']}/datasource",
        headers=auth(client),
        files={"file": ("notes.pdf", b"%PDF-1.4", "application/pdf")},
    )
    assert response.status_code == 422
    assert "صيغة غير مدعومة" in response.json()["detail"]


def test_saving_the_mapping_rekeys_the_records(client, project):
    headers = auth(client)
    current = client.get(
        f"/api/v1/projects/{project['id']}/mapping", headers=headers
    ).json()
    assert "deed_number" in current["required_keys"]

    response = client.put(
        f"/api/v1/projects/{project['id']}/mapping",
        headers=headers,
        json={"entries": current["entries"]},
    )
    assert response.status_code == 200
    assert not [p for p in response.json()["problems"] if p["severity"] == "error"]

    records = client.get(
        f"/api/v1/projects/{project['id']}/records", headers=headers
    ).json()
    assert len(records) == 3
    assert records[0]["values"]["deed_number"] == "442108021305"
    assert records[0]["values"]["area_sqm"] == "875", "875.0 would print wrongly"


def test_unmapped_required_field_is_reported_as_an_error(client, project):
    headers = auth(client)
    current = client.get(
        f"/api/v1/projects/{project['id']}/mapping", headers=headers
    ).json()
    broken = [
        {**e, "column": None} if e["field_key"] == "deed_number" else e
        for e in current["entries"]
    ]
    problems = client.put(
        f"/api/v1/projects/{project['id']}/mapping",
        headers=headers,
        json={"entries": broken},
    ).json()["problems"]
    assert any(
        p["field_key"] == "deed_number" and p["severity"] == "error" for p in problems
    )

    # Put it back so the generation tests below have a valid mapping.
    client.put(
        f"/api/v1/projects/{project['id']}/mapping",
        headers=headers,
        json={"entries": current["entries"]},
    )


def test_preflight_predicts_the_page_count(client, project):
    body = client.get(
        f"/api/v1/projects/{project['id']}/preflight", headers=auth(client)
    ).json()
    assert body["record_count"] == 3
    assert body["generatable"] == 3
    assert body["rejected"] == {}
    # 4 opening + 1 summary + 1 page per property + 2 closing. The alternative
    # layouts and the optional per-property pages are the page plan's business,
    # so they are not in the section plan and not in this count.
    assert body["predicted_pages"] == 4 + 1 + (1 * 3) + 2


def test_generate_returns_a_job_immediately_then_produces_a_pdf(client, project):
    headers = auth(client)
    response = client.post(
        f"/api/v1/projects/{project['id']}/generate", headers=headers
    )
    assert response.status_code == 202, response.text
    job_id = response.json()["id"]
    assert response.json()["status"] in ("queued", "running")

    deadline = time.time() + 120
    body = {}
    while time.time() < deadline:
        body = client.get(f"/api/v1/jobs/{job_id}", headers=headers).json()
        if body["status"] in ("succeeded", "failed", "cancelled"):
            break
        time.sleep(0.5)

    assert body["status"] == "succeeded", body.get("error_summary")
    assert body["completed_records"] == 3
    assert body["page_count"] == 10
    assert body["output_filename"].endswith(".pdf")
    assert body["progress"] == 1.0
    assert body["engine"].startswith("ENGINE")

    download = client.get(f"/api/v1/jobs/{job_id}/download", headers=headers)
    assert download.status_code == 200
    assert download.headers["content-type"] == "application/pdf"
    assert download.content.startswith(b"%PDF")

    import fitz

    with fitz.open("pdf", download.content) as pdf:
        assert pdf.page_count == 10
        text = "".join(pdf[i].get_text() for i in range(pdf.page_count))
    for row in ROWS:
        assert row[0] in text, f"deed {row[0]} missing from the output"
    assert "\x00" not in text and "�" not in text


def test_errors_export_is_a_workbook(client, project):
    headers = auth(client)
    jobs = client.get("/api/v1/jobs", headers=auth(client, "admin@matbaa.sa")).json()
    job_id = jobs[0]["id"]
    response = client.get(f"/api/v1/jobs/{job_id}/errors.xlsx", headers=headers)
    assert response.status_code == 200
    assert response.content[:2] == b"PK", "xlsx is a zip container"


def test_dashboard_counts_the_finished_job(client):
    body = client.get("/api/v1/dashboard", headers=auth(client)).json()
    labels = {s["label"]: s["value"] for s in body["stats"]}
    assert labels["ملفات وُلّدت"] == "1"
    assert int(labels["صفحات مطبوعة"].replace(",", "")) == 10
    assert len(body["usage"]) == 7


def test_a_client_cannot_read_another_clients_project(client, project):
    from app.core.db import SessionLocal
    from app.core.security import hash_password
    from app.models import Client, Role, User

    session = SessionLocal()
    try:
        other = Client(name="آخر", code="OTHER")
        session.add(other)
        session.flush()
        session.add(
            User(
                email="rival@other.sa", name="منافس",
                password_hash=hash_password("secret12"), role=Role.CLIENT,
                client_id=other.id,
            )
        )
        session.commit()
    finally:
        session.close()

    headers = auth(client, "rival@other.sa")
    assert client.get(f"/api/v1/projects/{project['id']}", headers=headers).status_code == 404
    assert client.get("/api/v1/projects", headers=headers).json() == []


def test_generating_without_data_is_rejected(client):
    headers = auth(client)
    template_id = client.get("/api/v1/templates", headers=headers).json()[0]["id"]
    empty = client.post(
        "/api/v1/projects",
        headers=headers,
        json={"name": "بلا بيانات", "template_id": template_id},
    ).json()
    response = client.post(
        f"/api/v1/projects/{empty['id']}/generate", headers=headers
    )
    assert response.status_code == 400
    assert "لا توجد بيانات" in response.json()["detail"]


def test_unknown_project_is_a_404(client):
    response = client.get(f"/api/v1/projects/{uuid.uuid4()}", headers=auth(client))
    assert response.status_code == 404


def test_datasource_endpoint_returns_the_real_columns(client, project):
    """The mapping screen needs the spreadsheet's own letters and order."""
    body = client.get(
        f"/api/v1/projects/{project['id']}/datasource", headers=auth(client)
    ).json()
    assert body["filename"] == "lots.xlsx"
    assert body["row_count"] == 3
    assert [c["letter"] for c in body["columns"]] == [
        "A", "B", "C", "D", "E", "F", "G", "H", "I"
    ]
    assert [c["name"] for c in body["columns"]] == HEADERS


def test_datasource_is_null_for_a_manual_project(client):
    headers = auth(client)
    template_id = client.get("/api/v1/templates", headers=headers).json()[0]["id"]
    manual = client.post(
        "/api/v1/projects",
        headers=headers,
        json={"name": "يدوي", "template_id": template_id},
    ).json()
    response = client.get(
        f"/api/v1/projects/{manual['id']}/datasource", headers=headers
    )
    assert response.status_code == 200
    assert response.json() is None


def test_concurrency_limit_is_enforced_per_client(client, project, monkeypatch):
    """The admin screen advertises the cap, so generate must actually apply it."""
    import app.api.v1.projects as projects_module

    headers = auth(client)
    original = projects_module.settings.concurrent_jobs_per_client
    projects_module.settings.concurrent_jobs_per_client = 0
    try:
        response = client.post(
            f"/api/v1/projects/{project['id']}/generate", headers=headers
        )
        assert response.status_code == 429
        assert "الحدّ الأقصى" in response.json()["detail"]
    finally:
        projects_module.settings.concurrent_jobs_per_client = original


def test_reimporting_a_template_keeps_existing_projects(client, project):
    """A design revision bumps the version; it must not orphan past booklets."""
    from sqlalchemy import select

    from app.core.db import SessionLocal
    from app.models import Project, Template
    from app.services.templates import import_template

    template_dir = BACKEND / "var" / "templates" / TEMPLATE_SLUG
    session = SessionLocal()
    try:
        before = session.scalar(
            select(Template).where(Template.slug == TEMPLATE_SLUG)
        )
        template_id, version = before.id, before.version

        reimported = import_template(session, template_dir, name="كتيّب المزاد")
        session.commit()

        assert reimported.id == template_id, "the row must be reused, not replaced"
        assert reimported.version == version + 1
        assert len(reimported.fields) > 20, "fields are replaced, not dropped"

        survivor = session.get(Project, __import__("uuid").UUID(project["id"]))
        assert survivor is not None, "the existing project must survive"
        assert survivor.template_id == template_id
    finally:
        session.close()


def test_staff_must_name_the_client_when_creating_a_project(client):
    """Staff act for any client, so the wizard has to say which one."""
    from sqlalchemy import select

    from app.core.db import SessionLocal
    from app.models import Client

    staff = auth(client, "admin@matbaa.sa")
    template_id = client.get("/api/v1/templates", headers=staff).json()[0]["id"]

    without = client.post(
        "/api/v1/projects",
        headers=staff,
        json={"name": "بلا عميل", "template_id": template_id},
    )
    assert without.status_code == 400
    assert "العميل" in without.json()["detail"]

    session = SessionLocal()
    try:
        owner_id = str(session.scalar(select(Client).where(Client.code == "AAYAN")).id)
    finally:
        session.close()

    created = client.post(
        "/api/v1/projects",
        headers=staff,
        json={"name": "مع عميل", "template_id": template_id, "client_id": owner_id},
    )
    assert created.status_code == 201, created.text
    assert created.json()["client_id"] == owner_id


def test_a_client_user_never_needs_to_pick_a_client(client):
    """Their own organisation is implied, and another client's id is refused."""
    headers = auth(client)
    template_id = client.get("/api/v1/templates", headers=headers).json()[0]["id"]

    mine = client.post(
        "/api/v1/projects",
        headers=headers,
        json={"name": "بلا تحديد عميل", "template_id": template_id},
    )
    assert mine.status_code == 201
    own_client_id = mine.json()["client_id"]

    someone_else = client.post(
        "/api/v1/projects",
        headers=headers,
        json={
            "name": "عميل آخر",
            "template_id": template_id,
            "client_id": str(uuid.uuid4()),
        },
    )
    assert someone_else.status_code == 403
    assert own_client_id != str(uuid.uuid4())


def test_photos_endpoint_lists_image_fields_by_scope(client, project):
    """The photo step needs to know which images are per-lot and which are per-booklet."""
    body = client.get(
        f"/api/v1/projects/{project['id']}/photos", headers=auth(client)
    ).json()
    scopes = {f["key"]: f["scope"] for f in body["fields"]}
    assert scopes["main_photo"] == "record", "the lot photo is asked once per lot"
    assert scopes["cover_photo"] == "project", "the cover is asked once per booklet"
    assert len(body["records"]) == 3


def test_patching_a_record_merges_rather_than_replaces(client, project):
    """Setting a photo must not wipe the deed number beside it."""
    headers = auth(client)
    before = client.get(
        f"/api/v1/projects/{project['id']}/records", headers=headers
    ).json()[0]
    assert before["values"]["deed_number"]

    patched = client.patch(
        f"/api/v1/projects/{project['id']}/records/{before['row_index']}",
        headers=headers,
        json={"values": {"main_photo": "lot-photo.jpg"}},
    )
    assert patched.status_code == 200, patched.text
    values = patched.json()["values"]
    assert values["main_photo"] == "lot-photo.jpg"
    assert values["deed_number"] == before["values"]["deed_number"]
    assert values["district"] == before["values"]["district"]


def test_patching_an_unknown_row_is_a_404(client, project):
    response = client.patch(
        f"/api/v1/projects/{project['id']}/records/999",
        headers=auth(client),
        json={"values": {"main_photo": "x.jpg"}},
    )
    assert response.status_code == 404


def test_preflight_reports_a_photo_that_is_not_in_the_library(client, project):
    """A referenced-but-missing photo is surfaced before generation, not after."""
    headers = auth(client)
    client.patch(
        f"/api/v1/projects/{project['id']}/records/0",
        headers=headers,
        json={"values": {"main_photo": "does-not-exist.jpg"}},
    )
    body = client.get(
        f"/api/v1/projects/{project['id']}/preflight", headers=headers
    ).json()
    assert "does-not-exist.jpg" in body["missing_assets"]

    # Put it back so later tests see a clean project.
    client.patch(
        f"/api/v1/projects/{project['id']}/records/0",
        headers=headers,
        json={"values": {"main_photo": ""}},
    )


def test_output_pages_render_as_thumbnails(client, project):
    """The preview screen needs a raster per page; they are rendered on demand."""
    headers = auth(client)
    jobs = client.get("/api/v1/dashboard", headers=headers).json()["recent_jobs"]
    done = next((j for j in jobs if j["status"] == "succeeded"), None)
    assert done is not None, "the generate test should have left a finished job"

    response = client.get(f"/api/v1/jobs/{done['id']}/pages/0.png", headers=headers)
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content.startswith(PNG_MAGIC)

    missing = client.get(
        f"/api/v1/jobs/{done['id']}/pages/9999.png", headers=headers
    )
    assert missing.status_code == 404


def test_record_keys_agree_between_disk_and_db(client, template_dir):
    """The same template must not describe its record keys two different ways.

    ``manifest.load`` reads a built template off disk; the API reads the same
    template out of the database. Both answer "which keys does one lot supply?"
    -- the mapping screen asks over HTTP, the CLI renderer asks on disk. When
    they disagreed, ``city`` (a summary-table column, on no per-record page) was
    a record key through one path and not the other.
    """
    from app.rendering import manifest

    headers = auth(client, "admin@matbaa.sa")
    template_id = client.get("/api/v1/templates", headers=headers).json()[0]["id"]
    over_http = client.get(
        f"/api/v1/templates/{template_id}", headers=headers
    ).json()["record_keys"]

    with manifest.load(template_dir) as template:
        on_disk = template.record_keys()

    assert set(on_disk) == set(over_http)
    assert "city" in on_disk, "a summary-table column is still a record key"
    assert not any(k.startswith("__table__") for k in on_disk), (
        "a table field's own key is plumbing, not a record key"
    )
