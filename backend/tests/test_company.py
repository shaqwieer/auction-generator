"""The company a booklet is printed for, and the mark it prints with.

The designer's export carried one selling agent's lockup baked into the artwork
on seventeen pages of every variant. A booklet is printed for whoever is
selling, so that mark is out of the artwork and its place is a field.

Two places, not one, and that distinction is what most of these check. The mark
goes where the lockup was, and *only* a mark goes there: the guide prints a logo
in that spot and never a name set in type, so a company with no logo leaves it
empty. The name has its own place in the design -- the title on تعريف وكيل
البيع, which is exactly where the guide's own example prints it.
"""

from __future__ import annotations

import io

import fitz
import pytest
from PIL import Image

from app.rendering import manifest
from tests.conftest import auth
from tests.test_pipeline import fold


def ink_fraction(page, box, width: int = 96, height: int = 28) -> float:
    """How much of a box is drawn on, against whatever its background is."""
    matrix = fitz.Matrix(width / box.width, height / box.height)
    pixels = page.get_pixmap(clip=box, matrix=matrix)
    depth = pixels.n
    dots = [
        bytes(pixels.samples[i : i + depth])
        for i in range(0, len(pixels.samples), depth)
    ]
    background = max(set(dots), key=dots.count)
    return sum(
        1
        for dot in dots
        if sum(abs(dot[c] - background[c]) for c in range(3)) > 90
    ) / len(dots)


def png(size: tuple[int, int] = (400, 120), colour=(220, 40, 90, 255)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", size, colour).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture(scope="module")
def template(client) -> dict:
    body = client.get("/api/v1/templates", headers=auth(client)).json()
    return client.get(
        f"/api/v1/templates/{body[0]['id']}", headers=auth(client)
    ).json()


@pytest.fixture
def booklet(client, template) -> dict:
    created = client.post(
        "/api/v1/projects",
        headers=auth(client),
        json={"name": "كتيّب العلامة", "template_id": template["id"], "lot_count": 1},
    )
    assert created.status_code == 201, created.text
    return created.json()


@pytest.fixture
def company(client) -> dict:
    return client.get("/api/v1/company", headers=auth(client)).json()


@pytest.fixture(autouse=True)
def _restore_company(client):
    """Each test leaves the account as it found it."""
    before = client.get("/api/v1/company", headers=auth(client)).json()
    yield
    client.patch("/api/v1/company", headers=auth(client), json={"name": before["name"]})
    if not before["logo_filename"]:
        client.delete("/api/v1/company/logo", headers=auth(client))


def title_field(template: dict) -> dict:
    return next(f for f in template["fields"] if f["key"] == "company_name")


def preview_url(project_id: str, node_id: str, dpi: int = 80) -> str:
    return (
        f"/api/v1/projects/{project_id}/plan/nodes/{node_id}/preview.png?dpi={dpi}"
    )


def node_for_page(client, project_id: str, page_index: int) -> dict:
    plan = client.get(
        f"/api/v1/projects/{project_id}/plan", headers=auth(client)
    ).json()
    return next(n for n in plan["nodes"] if n.get("page") == page_index)


# ------------------------------------------------------------- the account


def test_the_signed_in_user_carries_their_company(client):
    """The sidebar shows it, so it rides on the session rather than a fetch."""
    me = client.get("/api/v1/auth/me", headers=auth(client)).json()
    assert me["company"], "a client account belongs to a company"
    assert me["company"]["name"]


def test_the_name_is_required_and_cannot_be_blanked(client, company):
    assert company["name"]
    refused = client.patch(
        "/api/v1/company", headers=auth(client), json={"name": "   "}
    )
    assert refused.status_code in (400, 422), refused.text
    still = client.get("/api/v1/company", headers=auth(client)).json()
    assert still["name"] == company["name"]


def test_a_client_account_cannot_be_made_without_a_company(client):
    """Its booklets would print no name and no mark at all."""
    response = client.post(
        "/api/v1/auth/users",
        headers=auth(client, "admin@matbaa.sa"),
        json={
            "email": "orphan@example.com",
            "name": "بلا شركة",
            "password": "secret12",
            "role": "client",
        },
    )
    assert response.status_code == 422, response.text
    assert "شركة" in response.json()["detail"]


# ------------------------------------------------------------- the template


def test_the_mark_is_a_field_on_every_page_that_carried_the_lockup(template):
    logos = [f for f in template["fields"] if f["key"] == "company_logo"]
    assert len(logos) > 10, "the lockup was on most pages of the booklet"
    assert all(f["type"] == "image" for f in logos)
    assert all(f["preserve_aspect"] for f in logos), (
        "a logo is fitted to its box, never cropped or stretched to it"
    )


def test_nothing_of_the_old_mark_survives(template_dir):
    """Not a fragment.

    Redaction judges "covered" strictly, and the hamza of the wordmark begins on
    the mark's own top edge — so the first attempt left a speck floating in the
    middle of an otherwise empty footer, on every page, in every variant.

    Measured the way the build finds the mark in the first place: ink against
    the local background. A lockup reads about 0.40 and a cleared box 0.00 —
    including the gradient covers, because a gradient has no edges.
    """
    with manifest.load(template_dir) as loaded:
        page_box = fitz.Rect(0, 0, *loaded.page_size)
        boxes = [
            (f.page_index, f.rect.to_points(page_box))
            for f in loaded.fields
            if f.key == "company_logo"
        ]
        assert boxes, "the mark should be a field"
        for page_index, box in boxes:
            assert ink_fraction(loaded.background[page_index], box) < 0.02, (
                f"page {page_index} still carries part of the old mark"
            )


def test_the_mark_is_never_confused_with_a_qr_code(template):
    """The lot pages draw four QR codes, and each is twenty-three paths.

    So is the lockup. The only thing separating them is proportion — 3.37
    against 1.00 — and an export that scaled the mark slightly could brand four
    property QR codes with the company's logo before anyone noticed.
    """
    for field in template["fields"]:
        if field["key"] != "company_logo":
            continue
        shape = (field["w"] * 595.28) / (field["h"] * 841.89)
        assert shape > 2.0, (
            f"page {field['page_index']}: a square mark is not the lockup"
        )


def test_the_name_has_one_place_and_it_is_not_the_marks(template):
    names = [f for f in template["fields"] if f["key"] == "company_name"]
    assert len(names) == 1, "the company's name belongs in one place"
    title = names[0]
    assert title["type"] == "text"

    on_that_page = [
        f
        for f in template["fields"]
        if f["key"] == "company_logo" and f["page_index"] == title["page_index"]
    ]
    assert on_that_page, "the title's page carries the mark above it"
    mark = on_that_page[0]
    assert title["y"] > mark["y"] + mark["h"], (
        "the name is a title under the mark, not something drawn inside it"
    )


def test_the_agent_page_offers_its_three_contacts_separately(template):
    """A website, a telephone and an X handle, each under its own icon.

    One field spanning all three could only ever hold one of them.
    """
    keys = {f["key"] for f in template["fields"]}
    assert {"agent_website", "agent_phone", "agent_x"} <= keys
    contacts = sorted(
        (f for f in template["fields"] if f["key"].startswith("agent_")),
        key=lambda f: -f["x"],
    )
    row = [f for f in contacts if f["key"] != "agent_about"]
    assert [f["key"] for f in row] == ["agent_x", "agent_phone", "agent_website"], (
        "right to left, the order the page reads in"
    )
    assert len({f["page_index"] for f in row}) == 1
    assert all(f["align"] == "right" for f in row), (
        "each value is printed hard against its own icon"
    )
    assert not any(f["rtl"] for f in row), (
        "an address, a number and a handle are Latin — laid out right to left "
        "the «@» ends up on the wrong end of the name"
    )


def test_the_cover_date_is_centred_under_its_caption(template):
    """«تاريخ المزاد» is printed above it; the date sits centred beneath."""
    dates = [f for f in template["fields"] if f["key"] == "auction_date_block"]
    assert dates, "every cover carries a date"
    assert all(f["align"] == "center" for f in dates)
    assert all(f["fit"] == "wrap" for f in dates), "a date may take two lines"


# -------------------------------------------------------------- the booklet


def test_renaming_the_company_renames_it_on_the_booklet(client, booklet, template):
    """Computed at compose time, so an open project follows the account."""
    headers = auth(client)
    title = title_field(template)
    node = node_for_page(client, booklet["id"], title["page_index"])
    url = preview_url(booklet["id"], node["id"])
    before = client.get(url, headers=headers).content

    renamed = client.patch(
        "/api/v1/company", headers=headers, json={"name": "شركة الرياض للتطوير"}
    )
    assert renamed.status_code == 200, renamed.text
    assert client.get(url, headers=headers).content != before


def test_a_page_that_carries_only_the_mark_ignores_the_name(client, booklet):
    """Renaming must not change a page the design gives no name a place on."""
    headers = auth(client)
    plan = client.get(
        f"/api/v1/projects/{booklet['id']}/plan", headers=headers
    ).json()
    cover = plan["nodes"][0]
    url = preview_url(booklet["id"], cover["id"])
    before = client.get(url, headers=headers).content

    client.patch("/api/v1/company", headers=headers, json={"name": "اسم آخر تمامًا"})
    assert client.get(url, headers=headers).content == before


def test_the_mark_goes_on_and_comes_off_the_page(client, booklet):
    headers = auth(client)
    plan = client.get(
        f"/api/v1/projects/{booklet['id']}/plan", headers=headers
    ).json()
    cover = plan["nodes"][0]
    url = preview_url(booklet["id"], cover["id"])
    bare = client.get(url, headers=headers).content

    uploaded = client.post(
        "/api/v1/company/logo",
        headers=headers,
        files={"file": ("mark.png", png(), "image/png")},
    )
    assert uploaded.status_code == 200, uploaded.text
    assert uploaded.json()["logo_filename"]

    served = client.get("/api/v1/company/logo", headers=headers)
    assert served.status_code == 200
    assert served.content[:4] == b"\x89PNG"

    assert client.get(url, headers=headers).content != bare, "the mark is not there"

    removed = client.delete("/api/v1/company/logo", headers=headers)
    assert removed.status_code == 200, removed.text
    assert removed.json()["logo_filename"] is None
    assert client.get(url, headers=headers).content == bare


def test_a_generated_booklet_carries_the_company_name(client, booklet):
    """Not just the preview — the PDF the client actually receives."""
    headers = auth(client)
    client.patch("/api/v1/company", headers=headers, json={"name": "شركة الاختبار"})
    plan = client.get(
        f"/api/v1/projects/{booklet['id']}/plan", headers=headers
    ).json()
    for lot in (n for n in plan["nodes"] if n["kind"] == "lot"):
        client.patch(
            f"/api/v1/projects/{booklet['id']}/plan/nodes/{lot['id']}/values",
            headers=headers,
            json={"values": {"deed_number": "442108021300", "property_type": "فيلا"}},
        )

    queued = client.post(
        f"/api/v1/projects/{booklet['id']}/generate", headers=headers
    )
    assert queued.status_code == 202, queued.text
    job_id = queued.json()["id"]
    for _ in range(120):
        state = client.get(f"/api/v1/jobs/{job_id}", headers=headers).json()
        if state["status"] in ("succeeded", "failed", "cancelled"):
            break
    assert state["status"] == "succeeded", state.get("error_summary")

    download = client.get(f"/api/v1/jobs/{job_id}/download", headers=headers)
    with fitz.open("pdf", download.content) as pdf:
        # Illustrator bakes Arabic into presentation forms, so read it back the
        # way every other printed-text assertion here does.
        printed = fold("".join(pdf[i].get_text() for i in range(pdf.page_count)))
    assert fold("شركة الاختبار") in printed
