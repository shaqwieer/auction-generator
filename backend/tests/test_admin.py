"""Template lifecycle, and the client/category admin surfaces."""

from __future__ import annotations

import uuid
from pathlib import Path

import fitz
import pytest

from tests.conftest import PNG_MAGIC, TEMPLATE_SLUG, auth

BACKEND = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def design_bytes(sample_path: Path) -> bytes:
    return sample_path.read_bytes()


@pytest.fixture(scope="module")
def uploaded(client, design_bytes) -> dict:
    response = client.post(
        "/api/v1/templates",
        headers=auth(client, "admin@matbaa.sa"),
        files={"file": ("design.ai", design_bytes, "application/pdf")},
        data={"name": "قالب مرفوع"},
    )
    assert response.status_code == 201, response.text
    return response.json()


# --------------------------------------------------------------- ingest


def test_upload_proposes_fields_from_the_design_itself(uploaded):
    assert uploaded["pages"] == 16
    assert uploaded["auto_named"] > 30, "the vocabulary should name most values"
    assert uploaded["tables"] == 2, "both summary blocks are recovered"
    assert uploaded["template"]["status"] == "draft"


def test_upload_does_not_bake_yet(uploaded):
    """Baking needs confirmed fields, so a draft still shows its sample content."""
    from app.core.db import SessionLocal
    from app.models import Template

    session = SessionLocal()
    try:
        template = session.get(Template, uuid.UUID(uploaded["template"]["id"]))
        assert template.background_path is None
    finally:
        session.close()


def test_only_nameable_regions_become_fields(uploaded):
    """340 fields would bury the editor; the rest stay click-to-add suggestions."""
    assert uploaded["proposed_fields"] < 100
    fonts = uploaded["template"]["fonts"]
    assert fonts, "text fields should record their fonts"
    assert all(
        f.startswith(("RuaqArabic", "LamaSans")) for f in fonts
    ), f"only shipped fonts may back a field: {fonts}"


def test_suggestions_exclude_regions_already_claimed(client, uploaded):
    body = client.get(
        f"/api/v1/templates/{uploaded['template']['id']}/suggestions",
        headers=auth(client, "admin@matbaa.sa"),
    ).json()
    assert len(body) > 100
    claimed = {
        (f["page_index"], round(f["x"], 4), round(f["y"], 4))
        for f in uploaded["template"]["fields"]
    }
    offered = {
        (s["page_index"], round(s["x"], 4), round(s["y"], 4)) for s in body
    }
    assert not (claimed & offered), "a region cannot be both a field and a suggestion"


def test_unsupported_upload_is_rejected(client):
    response = client.post(
        "/api/v1/templates",
        headers=auth(client, "admin@matbaa.sa"),
        files={"file": ("notes.txt", b"hello", "text/plain")},
        data={"name": "خطأ"},
    )
    assert response.status_code == 422
    assert "صيغة غير مدعومة" in response.json()["detail"]


def test_template_page_renders_as_png(client, uploaded):
    response = client.get(
        f"/api/v1/templates/{uploaded['template']['id']}/pages/5.png",
        headers=auth(client, "admin@matbaa.sa"),
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content.startswith(PNG_MAGIC)


def test_page_out_of_range_is_a_404(client, uploaded):
    assert (
        client.get(
            f"/api/v1/templates/{uploaded['template']['id']}/pages/99.png",
            headers=auth(client, "admin@matbaa.sa"),
        ).status_code
        == 404
    )


# --------------------------------------------------------------- sections


SECTIONS = [
    {"name": "المقدمة", "kind": "fixed", "first_page": 0, "last_page": 3},
    {"name": "جدول", "kind": "table", "first_page": 4, "last_page": 4,
     "rows_per_page": 20},
    {"name": "العقار", "kind": "per_record", "first_page": 5, "last_page": 6,
     "pages_per_item": 2},
    {"name": "الخاتمة", "kind": "fixed", "first_page": 7, "last_page": 15},
]


def test_sections_define_the_repeating_block(client, uploaded):
    response = client.put(
        f"/api/v1/templates/{uploaded['template']['id']}/sections",
        headers=auth(client, "admin@matbaa.sa"),
        json=SECTIONS,
    )
    assert response.status_code == 200
    kinds = [s["kind"] for s in response.json()["sections"]]
    assert kinds == ["fixed", "table", "per_record", "fixed"]


@pytest.mark.parametrize(
    "broken,message",
    [
        ({"pages_per_item": 3}, "صفحة"),
        ({"last_page": 2, "first_page": 5}, "نهاية القسم"),
        ({"last_page": 99}, "خارج القالب"),
    ],
)
def test_impossible_sections_are_refused(client, uploaded, broken, message):
    payload = [{**SECTIONS[2], **broken}]
    response = client.put(
        f"/api/v1/templates/{uploaded['template']['id']}/sections",
        headers=auth(client, "admin@matbaa.sa"),
        json=payload,
    )
    assert response.status_code == 400
    assert message in response.json()["detail"]


# --------------------------------------------------------------- publish


def test_publishing_bakes_the_artwork(client, uploaded):
    """Values are cleared from the design; the printed labels survive."""
    from app.core.db import SessionLocal
    from app.models import Template

    headers = auth(client, "admin@matbaa.sa")
    client.put(
        f"/api/v1/templates/{uploaded['template']['id']}/sections",
        headers=headers,
        json=SECTIONS,
    )
    response = client.post(
        f"/api/v1/templates/{uploaded['template']['id']}/publish", headers=headers
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "published"

    session = SessionLocal()
    try:
        template = session.get(Template, uuid.UUID(uploaded["template"]["id"]))
        assert template.background_path
        with fitz.open(template.background_path) as baked:
            assert baked.page_count == 16
            text = baked[5].get_text()
        # The design's own labels stay; the sample values go.
        assert "542104012563" not in text
        assert len(text.strip()) > 200, "static design copy must survive baking"
    finally:
        session.close()


def test_publishing_an_empty_template_is_refused(client):
    """A template with no fields would generate a stack of identical pages."""
    from app.core.db import SessionLocal
    from app.models import Template, TemplateStatus

    session = SessionLocal()
    try:
        bare = Template(
            slug=f"bare_{uuid.uuid4().hex[:6]}",
            name="فارغ",
            code="BARE",
            status=TemplateStatus.DRAFT,
        )
        session.add(bare)
        session.commit()
        bare_id = str(bare.id)
    finally:
        session.close()

    response = client.post(
        f"/api/v1/templates/{bare_id}/publish", headers=auth(client, "admin@matbaa.sa")
    )
    assert response.status_code == 400
    assert "بلا حقول" in response.json()["detail"]


def test_only_an_admin_may_publish(client, uploaded):
    """Publishing is the admin's signature on somebody else's preparation.

    It bakes the artwork and is what puts a template in front of clients, so it
    sits with the admin alone -- which is what the permission matrix on
    /admin/settings has always said. The guard said ``Staff`` and let an
    operator publish.
    """
    url = f"/api/v1/templates/{uploaded['template']['id']}/publish"

    refused = client.post(url, headers=auth(client, "sara@matbaa.sa"))
    assert refused.status_code == 403, refused.text
    assert "مدير النظام" in refused.json()["detail"]

    assert client.post(url, headers=auth(client)).status_code == 403

    allowed = client.post(url, headers=auth(client, "admin@matbaa.sa"))
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["status"] == "published"


def test_an_operator_still_prepares_the_template_they_cannot_publish(client, uploaded):
    """The split is publishing only -- everything up to it stays staff-level."""
    headers = auth(client, "sara@matbaa.sa")
    template_id = uploaded["template"]["id"]

    assert (
        client.get(f"/api/v1/templates/{template_id}", headers=headers).status_code
        == 200
    )
    assert (
        client.get(
            f"/api/v1/templates/{template_id}/suggestions", headers=headers
        ).status_code
        == 200
    )
    assert (
        client.put(
            f"/api/v1/templates/{template_id}/sections",
            headers=headers,
            json=SECTIONS,
        ).status_code
        == 200
    )


def test_only_an_admin_may_unpublish(client, uploaded):
    """Withdrawing a template is the same decision as publishing it, reversed."""
    template_id = uploaded["template"]["id"]
    url = f"/api/v1/templates/{template_id}/unpublish"
    admin = auth(client, "admin@matbaa.sa")

    published = client.post(
        f"/api/v1/templates/{template_id}/publish", headers=admin
    )
    assert published.status_code == 200, published.text

    refused = client.post(url, headers=auth(client, "sara@matbaa.sa"))
    assert refused.status_code == 403, refused.text
    assert "مدير النظام" in refused.json()["detail"]

    assert client.post(url, headers=auth(client)).status_code == 403

    allowed = client.post(url, headers=admin)
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["status"] == "draft"

    # Publishing again is the way back, and it re-bakes from the original.
    again = client.post(f"/api/v1/templates/{template_id}/publish", headers=admin)
    assert again.status_code == 200, again.text
    assert again.json()["status"] == "published"


def test_unpublishing_twice_says_so_rather_than_pretending(client, uploaded):
    """A no-op that reports success hides a mis-click on the wrong template."""
    template_id = uploaded["template"]["id"]
    admin = auth(client, "admin@matbaa.sa")

    client.post(f"/api/v1/templates/{template_id}/unpublish", headers=admin)
    again = client.post(f"/api/v1/templates/{template_id}/unpublish", headers=admin)
    assert again.status_code == 400
    assert "ليس منشورًا" in again.json()["detail"]

    assert (
        client.post(
            f"/api/v1/templates/{template_id}/publish", headers=admin
        ).status_code
        == 200
    )


def test_unpublishing_takes_a_template_out_of_the_client_catalogue(client, uploaded):
    """What unpublishing is for: it stops being offered, staff keep working on it."""
    template_id = uploaded["template"]["id"]
    admin = auth(client, "admin@matbaa.sa")
    as_client = auth(client)

    client.post(f"/api/v1/templates/{template_id}/publish", headers=admin)
    listed = client.get("/api/v1/templates", headers=as_client).json()
    assert any(t["id"] == template_id for t in listed), "published: the client sees it"

    assert (
        client.post(
            f"/api/v1/templates/{template_id}/unpublish", headers=admin
        ).status_code
        == 200
    )

    listed = client.get("/api/v1/templates", headers=as_client).json()
    assert not any(t["id"] == template_id for t in listed), "withdrawn from the catalogue"

    started = client.post(
        "/api/v1/projects",
        headers=as_client,
        json={"name": "مزاد", "template_id": template_id},
    )
    assert started.status_code == 400
    assert "غير منشور" in started.json()["detail"]

    # Staff still reach it -- that is the point: it is withdrawn to be corrected.
    assert (
        client.get(
            f"/api/v1/templates/{template_id}",
            headers=auth(client, "sara@matbaa.sa"),
        ).status_code
        == 200
    )

    assert (
        client.post(
            f"/api/v1/templates/{template_id}/publish", headers=admin
        ).status_code
        == 200
    )


def test_unpublishing_leaves_the_baked_artwork_alone(client, uploaded):
    """Existing projects render from the baked background; it must survive.

    ``open_background`` raises when the file is gone rather than falling back to
    the designer's export, so clearing it here would break every project already
    built from this template instead of merely withdrawing it.
    """
    import uuid as _uuid

    from app.core.db import SessionLocal
    from app.models import Template

    template_id = uploaded["template"]["id"]
    admin = auth(client, "admin@matbaa.sa")
    client.post(f"/api/v1/templates/{template_id}/publish", headers=admin)

    session = SessionLocal()
    try:
        baked = session.get(Template, _uuid.UUID(template_id)).background_path
        assert baked
    finally:
        session.close()

    assert (
        client.post(
            f"/api/v1/templates/{template_id}/unpublish", headers=admin
        ).status_code
        == 200
    )

    session = SessionLocal()
    try:
        template = session.get(Template, _uuid.UUID(template_id))
        assert template.status == "draft"
        assert template.background_path == baked, "the bake is not undone"
        assert Path(template.background_path).exists()
    finally:
        session.close()

    assert (
        client.post(
            f"/api/v1/templates/{template_id}/publish", headers=admin
        ).status_code
        == 200
    )


def test_a_template_in_use_cannot_be_deleted(client, project):
    from app.core.db import SessionLocal
    from app.models import Project

    session = SessionLocal()
    try:
        template_id = str(
            session.get(Project, uuid.UUID(project["id"])).template_id
        )
    finally:
        session.close()

    response = client.delete(
        f"/api/v1/templates/{template_id}", headers=auth(client, "admin@matbaa.sa")
    )
    assert response.status_code == 409
    assert "مستخدم" in response.json()["detail"]


# ------------------------------------------------------------- categories


def test_category_crud(client):
    headers = auth(client, "admin@matbaa.sa")

    created = client.post(
        "/api/v1/categories",
        headers=headers,
        json={"name": "أكياس", "slug": "bags", "description": "أكياس ورقية"},
    )
    assert created.status_code == 201
    category_id = created.json()["id"]

    assert (
        client.post(
            "/api/v1/categories",
            headers=headers,
            json={"name": "مكرر", "slug": "bags"},
        ).status_code
        == 409
    )

    renamed = client.post(
        f"/api/v1/categories/{category_id}",
        headers=headers,
        json={"name": "أكياس وتغليف"},
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "أكياس وتغليف"
    assert renamed.json()["slug"] == "bags", "the slug is an identity, not a label"

    assert (
        client.delete(
            f"/api/v1/categories/{category_id}", headers=headers
        ).status_code
        == 204
    )


def test_a_category_holding_templates_cannot_be_deleted(client):
    headers = auth(client, "admin@matbaa.sa")
    categories = client.get("/api/v1/categories", headers=headers).json()
    used = next((c for c in categories if c["template_count"] > 0), None)
    if used is None:
        pytest.skip("no category currently holds a template")
    response = client.delete(f"/api/v1/categories/{used['id']}", headers=headers)
    assert response.status_code == 409
    assert "مستخدم" in response.json()["detail"]


def test_categories_are_staff_only_to_change(client):
    response = client.post(
        "/api/v1/categories",
        headers=auth(client),
        json={"name": "عميل", "slug": "client-made"},
    )
    assert response.status_code == 403


# ---------------------------------------------------------------- clients


def test_client_crud_and_soft_delete(client):
    headers = auth(client, "admin@matbaa.sa")

    created = client.post(
        "/api/v1/clients",
        headers=headers,
        json={"name": "عميل تجريبي", "code": "TRIAL"},
    )
    assert created.status_code == 201
    client_id = created.json()["id"]

    updated = client.post(
        f"/api/v1/clients/{client_id}",
        headers=headers,
        json={"contact_email": "ops@trial.sa", "name": "عميل تجريبي محدّث"},
    )
    assert updated.status_code == 200
    assert updated.json()["contact_email"] == "ops@trial.sa"

    # No work attached yet, so it really goes.
    assert (
        client.delete(f"/api/v1/clients/{client_id}", headers=headers).status_code
        == 204
    )


def test_a_client_with_projects_is_deactivated_not_deleted(client, project):
    """Deleting would cascade away every generated booklet."""
    headers = auth(client, "admin@matbaa.sa")
    owner_id = project["client_id"]

    assert client.delete(f"/api/v1/clients/{owner_id}", headers=headers).status_code == 204

    remaining = client.get("/api/v1/clients", headers=headers).json()
    kept = next(c for c in remaining if c["id"] == owner_id)
    assert kept["is_active"] is False, "the client is deactivated, not removed"
    assert kept["project_count"] > 0

    # Restore so later tests still see an active client.
    client.post(f"/api/v1/clients/{owner_id}", headers=headers, json={"is_active": True})


# ------------------------------------------------------------ client sign-ins


def test_creating_a_client_can_create_its_first_login(client):
    """A client with no user is one nobody can log in to."""
    headers = auth(client, "admin@matbaa.sa")
    created = client.post(
        "/api/v1/clients",
        headers=headers,
        json={
            "name": "مطابع الرياض",
            "code": "RIYADH",
            "user": {
                "name": "سلمان",
                "email": "salman@riyadh-print.sa",
                "password": "riyadh1234",
            },
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["user_count"] == 1

    # The new sign-in works, and lands on its own client.
    session = client.post(
        "/api/v1/auth/login",
        json={"email": "salman@riyadh-print.sa", "password": "riyadh1234"},
    )
    assert session.status_code == 200
    me = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {session.json()['access_token']}"},
    ).json()
    assert me["role"] == "client"
    assert me["client_id"] == created.json()["id"]


def test_a_duplicate_email_leaves_no_orphan_client(client):
    """The client and its user are created together or not at all."""
    headers = auth(client, "admin@matbaa.sa")
    before = len(client.get("/api/v1/clients", headers=headers).json())

    response = client.post(
        "/api/v1/clients",
        headers=headers,
        json={
            "name": "عميل مكرر",
            "code": "DUPE",
            "user": {
                "name": "مكرر",
                "email": "salman@riyadh-print.sa",
                "password": "another1234",
            },
        },
    )
    assert response.status_code == 409
    assert "مستخدم بالفعل" in response.json()["detail"]

    after = client.get("/api/v1/clients", headers=headers).json()
    assert len(after) == before, "the client must not survive a failed user"
    assert not any(c["code"] == "DUPE" for c in after)


def test_client_without_a_user_is_still_allowed(client):
    """Some clients are set up before anyone is given access."""
    headers = auth(client, "admin@matbaa.sa")
    created = client.post(
        "/api/v1/clients", headers=headers, json={"name": "لاحقًا", "code": "LATER"}
    )
    assert created.status_code == 201
    assert created.json()["user_count"] == 0

    added = client.post(
        f"/api/v1/clients/{created.json()['id']}/users",
        headers=headers,
        json={"name": "مشغّل", "email": "later@later.sa", "password": "later12345"},
    )
    assert added.status_code == 201
    listed = client.get(
        f"/api/v1/clients/{created.json()['id']}/users", headers=headers
    ).json()
    assert [u["email"] for u in listed] == ["later@later.sa"]


def test_password_can_be_reset_and_the_old_one_stops_working(client):
    headers = auth(client, "admin@matbaa.sa")
    users = client.get("/api/v1/auth/users", headers=headers).json()
    target = next(u for u in users if u["email"] == "later@later.sa")

    assert (
        client.post(
            f"/api/v1/users/{target['id']}/password",
            headers=headers,
            json={"password": "brandnew1234"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"email": "later@later.sa", "password": "later12345"},
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"email": "later@later.sa", "password": "brandnew1234"},
        ).status_code
        == 200
    )


def test_a_short_password_is_refused(client):
    response = client.post(
        "/api/v1/clients",
        headers=auth(client, "admin@matbaa.sa"),
        json={
            "name": "ضعيف",
            "code": "WEAK",
            "user": {"name": "x", "email": "weak@weak.sa", "password": "12345"},
        },
    )
    assert response.status_code == 422


def test_an_admin_cannot_delete_their_own_account(client):
    headers = auth(client, "admin@matbaa.sa")
    me = client.get("/api/v1/auth/me", headers=headers).json()
    response = client.delete(f"/api/v1/users/{me['id']}", headers=headers)
    assert response.status_code == 400
    assert "حسابك الحالي" in response.json()["detail"]


def test_client_users_are_staff_only_to_list(client):
    clients = client.get("/api/v1/clients", headers=auth(client, "admin@matbaa.sa")).json()
    response = client.get(
        f"/api/v1/clients/{clients[0]['id']}/users", headers=auth(client)
    )
    assert response.status_code == 403


def test_deleting_a_client_removes_its_logins(client):
    """A client-role account with no client can log in and then do nothing."""
    from sqlalchemy import select

    from app.core.db import SessionLocal
    from app.models import User

    headers = auth(client, "admin@matbaa.sa")
    created = client.post(
        "/api/v1/clients",
        headers=headers,
        json={
            "name": "مؤقّت",
            "code": "TEMP",
            "user": {
                "name": "مؤقّت",
                "email": "temp@temp.sa",
                "password": "temp123456",
            },
        },
    ).json()

    assert (
        client.post(
            "/api/v1/auth/login",
            json={"email": "temp@temp.sa", "password": "temp123456"},
        ).status_code
        == 200
    )

    assert (
        client.delete(f"/api/v1/clients/{created['id']}", headers=headers).status_code
        == 204
    )

    session = SessionLocal()
    try:
        orphan = session.scalar(select(User).where(User.email == "temp@temp.sa"))
        assert orphan is None, "the client's sign-in must go with it"
    finally:
        session.close()

    assert (
        client.post(
            "/api/v1/auth/login",
            json={"email": "temp@temp.sa", "password": "temp123456"},
        ).status_code
        == 401
    )


# ------------------------------------------------- field save round trip


def _as_update(field: dict) -> dict:
    """The payload the editor sends back, built the way the editor builds it.

    It reads a field, drops the server-owned keys, and PUTs the rest. Anything
    the read shape does not carry is therefore a value the editor has to invent
    -- and since saving replaces every field, inventing it discards what the
    build measured.
    """
    return {k: v for k, v in field.items() if k not in {"id", "origin"}}


def test_field_roundtrip_preserves_valign_and_calibration(client):
    """Saving an untouched template must not change a single field.

    The booklet's وصف العقار and ملاحظات blocks are wrapped body copy: they
    carry valign="top" and a 1.4 line height that the build measured off the
    artwork. When the read shape omitted those columns the first save from the
    editor reset them, and the lot pages silently reflowed.
    """
    headers = auth(client, "admin@matbaa.sa")
    listed = client.get("/api/v1/templates", headers=headers).json()
    # This module also uploads a draft; the built booklet is the one with the
    # measured typography to protect.
    built = next(t for t in listed if t["slug"] == TEMPLATE_SLUG)
    before = client.get(f"/api/v1/templates/{built['id']}", headers=headers).json()
    template_id = built["id"]

    wrapped = [f for f in before["fields"] if f["fit"] == "wrap"]
    assert wrapped, "the booklet has wrapped body copy to protect"
    assert any(f["valign"] == "top" for f in wrapped)
    assert any(f["line_height"] > 1.0 for f in wrapped)

    saved = client.put(
        f"/api/v1/templates/{template_id}/fields",
        headers=headers,
        json=[_as_update(f) for f in before["fields"]],
    )
    assert saved.status_code == 200, saved.text

    after = client.get(f"/api/v1/templates/{template_id}", headers=headers).json()
    keep = (
        "key", "page_index", "type", "align", "valign", "rotation",
        "font_family", "font_weight", "font_size_pt", "color", "line_height",
        "fit", "min_scale", "calibration_dx", "calibration_dy",
        "is_required", "rtl",
    )
    def shape(fields: list[dict]) -> list[tuple]:
        return sorted(tuple(f[k] for k in keep) for f in fields)

    assert shape(after["fields"]) == shape(before["fields"])


def test_reimporting_does_not_unarchive_a_retired_template(client, template_dir):
    """Archiving is a decision; a design revision must not undo it.

    The two first-generation booklets are superseded but still referenced by
    booklets already generated from them, so they are archived rather than
    deleted -- and the seed runs often enough that a re-import resurrecting
    them would put them back in front of every client.
    """
    from sqlalchemy import select

    from app.core.db import SessionLocal
    from app.models import Template, TemplateStatus
    from app.services.templates import import_template

    session = SessionLocal()
    try:
        template = session.scalar(
            select(Template).where(Template.slug == TEMPLATE_SLUG)
        )
        template.status = TemplateStatus.ARCHIVED
        session.commit()

        again = import_template(session, template_dir, name=template.name)
        session.commit()
        assert again.status == TemplateStatus.ARCHIVED

        again.status = TemplateStatus.PUBLISHED
        session.commit()
    finally:
        session.close()
