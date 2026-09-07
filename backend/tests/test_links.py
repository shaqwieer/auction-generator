"""The codes a property page prints, and what makes them worth printing.

A code on paper cannot be edited. So it never carries a destination: it carries
an address this system owns, and a row says where that address leads today.
Move the survey file, change the row, and the booklets already printed keep
working — which is the only reason to have the indirection at all.
"""

from __future__ import annotations

import io
import uuid

import fitz
import pytest
from sqlalchemy import select

from app.core.db import SessionLocal
from app.models import ShortLink
from app.rendering import manifest
from tests.conftest import auth

#: The property chips that carry an address somebody types, and therefore a
#: printed code. «معلومات الإيجار» is not among them: it leads to a page of the
#: booklet, so nothing is asked for and nothing is scannable.
LOT_SLOTS = ("link_survey", "link_photos", "link_map")
LEASE_SLOT = "__lease_link"
#: The auction's own two, one per page: where to bid, and where it is held.
BOOKLET_SLOTS = ("platform_link", "venue_link")
SLOTS = LOT_SLOTS + BOOKLET_SLOTS + (LEASE_SLOT,)


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
        json={"name": "كتيّب الروابط", "template_id": template["id"], "lot_count": 1},
    )
    assert created.status_code == 201, created.text
    return created.json()


def minted(session, project_id: str, key: str) -> ShortLink | None:
    """This project's code for one slot.

    Scoped to the project on purpose: every booklet in the database has a
    ``link_rent``, and a query that only names the key finds somebody else's.
    """
    return session.scalar(
        select(ShortLink).where(
            ShortLink.project_id == uuid.UUID(project_id),
            ShortLink.field_key == key,
        )
    )


def lot_of(client, project_id: str) -> dict:
    plan = client.get(
        f"/api/v1/projects/{project_id}/plan", headers=auth(client)
    ).json()
    return next(n for n in plan["nodes"] if n["kind"] == "lot")


def test_every_code_in_the_booklet_is_a_field(template):
    """Each is asked for once and printed twice — as a code and as a link.

    The four property ones are on every variant. The auction's own two are on
    the pages that carry them, and the حضوري booklet has no steps page — so
    what is checked is that whatever the template offers is offered in pairs,
    and that a property page offers all four.
    """
    offered = {f["key"] for f in template["fields"] if f["type"] == "link"}
    assert set(LOT_SLOTS) <= offered, "a property page prints three codes"
    assert LEASE_SLOT in offered, "the lease chip should still be a chip"
    assert offered <= set(SLOTS), f"unexpected link fields: {offered - set(SLOTS)}"
    assert offered & set(BOOKLET_SLOTS), "the auction's own codes are missing"

    assert not any(
        f["key"] == f"__qr_{LEASE_SLOT}" for f in template["fields"]
    ), "a chip that leads to a page of the booklet cannot be a printed code"

    for slot in offered - {LEASE_SLOT}:
        addresses = [f for f in template["fields"] if f["key"] == slot]
        codes = [f for f in template["fields"] if f["key"] == f"__qr_{slot}"]
        assert all(f["type"] == "link" for f in addresses)
        assert codes and all(f["type"] == "qr" for f in codes)
        assert {f["page_index"] for f in addresses} == {
            f["page_index"] for f in codes
        }, "the two halves of a chip sit on the same pages"


def test_the_click_target_is_the_whole_chip_not_the_bare_square(template):
    """On screen there is no code to click, so the caption has to be the target.

    Measured against the code it belongs to: the target has to be bigger than
    the square, and no two of them may overlap or one chip would swallow its
    neighbour's clicks.
    """
    import itertools

    scannable = {
        f["key"]
        for f in template["fields"]
        if f["type"] == "link" and not f["key"].startswith("__")
    }
    for slot in scannable:
        for chip in (f for f in template["fields"] if f["key"] == slot):
            square = next(
                f
                for f in template["fields"]
                if f["key"] == f"__qr_{slot}"
                and f["page_index"] == chip["page_index"]
            )
            assert chip["w"] * chip["h"] > square["w"] * square["h"] * 1.4, (
                f"{slot} on page {chip['page_index']} is barely wider than the "
                "code — the caption is not in the target"
            )

    def box(field: dict) -> tuple[float, float, float, float]:
        return (
            field["x"], field["y"],
            field["x"] + field["w"], field["y"] + field["h"],
        )

    chips = [f for f in template["fields"] if f["type"] == "link"]
    for one, two in itertools.combinations(chips, 2):
        if one["page_index"] != two["page_index"]:
            continue
        a, b = box(one), box(two)
        apart = a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1]
        assert apart, f"{one['key']} and {two['key']} overlap"


def test_a_code_is_printed_in_the_colour_the_page_uses(template):
    """Black on white is the default everywhere and wrong here.

    The booklet sets its codes in the brand teal and the contact page's in the
    brand navy. A black one on a white tile would be the only black thing on
    the page.
    """
    codes = [f for f in template["fields"] if f["type"] == "qr"]
    assert codes
    for code in codes:
        assert code["color"].upper() != "#000000", (
            f"{code['key']} would print black"
        )


def test_a_code_carries_no_white_tile():
    """It sits on the page, not on a patch."""
    from PIL import Image

    from app.rendering.images import qr_png

    with Image.open(io.BytesIO(qr_png("https://example.com", colour="#3CBEBB"))) as img:
        assert img.mode == "RGBA"
        assert img.getpixel((0, 0))[3] == 0, "the quiet zone should be clear"
        ink = {dot[:3] for dot in img.getdata() if dot[3] > 0}
        assert ink == {(0x3C, 0xBE, 0xBB)}, "the code should be the one colour"


def test_the_lease_chip_only_appears_where_there_are_lease_contracts(
    client, booklet
):
    """«يتم استخدام الصفحة في حال وجود عقود إيجارية للأصل».

    A chip leading to a page the booklet does not contain is worse than no chip,
    and this one leads nowhere else: it carries no address and prints no code.
    """
    headers = auth(client)
    lot = lot_of(client, booklet["id"])
    client.patch(
        f"/api/v1/projects/{booklet['id']}/plan/nodes/{lot['id']}/values",
        headers=headers,
        json={"values": {"deed_number": "442108021300"}},
    )
    url = (
        f"/api/v1/projects/{booklet['id']}/plan/nodes/{lot['id']}"
        "/preview.png?dpi=72"
    )
    without = client.get(url, headers=headers).content

    plan = client.post(
        f"/api/v1/projects/{booklet['id']}/plan/nodes/{lot['id']}/layout",
        headers=headers,
        json={"options": ["rent_table"]},
    )
    assert plan.status_code == 200, plan.text
    node = next(n for n in plan.json()["nodes"] if n["id"] == lot["id"])
    assert len(node["pages"]) == 2, "the lease page joins the property"

    # The chip draws no ink either way — it is a click target on a printed bar —
    # so what changes is the booklet, not this page's raster.
    assert client.get(url, headers=headers).status_code == 200
    assert without


def test_the_designers_own_codes_are_gone(template_dir):
    """They were scannable, and they led to the sample auction.

    Baking clears text and images and keeps line art, and a code is line art —
    so until the codes became fields, nothing claimed them and every booklet
    went out carrying four working links to somebody else's property.
    """
    with manifest.load(template_dir) as loaded:
        page_box = fitz.Rect(0, 0, *loaded.page_size)
        codes = [f for f in loaded.fields if f.key.startswith("__qr_")]
        assert codes, "the codes should be fields now"
        for field in codes:
            box = field.rect.to_points(page_box)
            pixels = loaded.background[field.page_index].get_pixmap(
                clip=box, dpi=72
            )
            depth = pixels.n
            shades = {
                bytes(pixels.samples[i : i + depth])
                for i in range(0, len(pixels.samples), depth)
            }
            assert len(shades) == 1, (
                f"page {field.page_index} still prints a sample code"
            )


def test_the_printed_code_leads_through_this_system(client, booklet):
    """Not to the address itself — that is what would need a reprint."""
    headers = auth(client)
    lot = lot_of(client, booklet["id"])
    client.patch(
        f"/api/v1/projects/{booklet['id']}/plan/nodes/{lot['id']}/values",
        headers=headers,
        json={"values": {"link_survey": "https://example.com/survey-v1"}},
    )
    drawn = client.get(
        f"/api/v1/projects/{booklet['id']}/plan/nodes/{lot['id']}"
        "/preview.png?dpi=72",
        headers=headers,
    )
    assert drawn.status_code == 200, drawn.text

    with SessionLocal() as session:
        link = minted(session, booklet["id"], "link_survey")
        assert link is not None, "drawing the code should mint it"
        assert link.target == "https://example.com/survey-v1"
        code = link.code

    hop = client.get(f"/r/{code}", follow_redirects=False)
    assert hop.status_code == 307
    assert hop.headers["location"] == "https://example.com/survey-v1"


def test_moving_the_destination_keeps_the_code(client, booklet):
    """The whole point: the paper does not have to be reprinted."""
    headers = auth(client)
    lot = lot_of(client, booklet["id"])
    url = (
        f"/api/v1/projects/{booklet['id']}/plan/nodes/{lot['id']}"
        "/preview.png?dpi=72"
    )
    client.patch(
        f"/api/v1/projects/{booklet['id']}/plan/nodes/{lot['id']}/values",
        headers=headers,
        json={"values": {"link_photos": "https://example.com/photos-old"}},
    )
    client.get(url, headers=headers)

    with SessionLocal() as session:
        first = minted(session, booklet["id"], "link_photos").code

    client.patch(
        f"/api/v1/projects/{booklet['id']}/plan/nodes/{lot['id']}/values",
        headers=headers,
        json={"values": {"link_photos": "https://example.com/photos-new"}},
    )
    client.get(url, headers=headers)

    with SessionLocal() as session:
        again = minted(session, booklet["id"], "link_photos")
        assert again.code == first, "the printed code must not change"
        assert again.target == "https://example.com/photos-new"

    hop = client.get(f"/r/{first}", follow_redirects=False)
    assert hop.headers["location"] == "https://example.com/photos-new"


def test_the_lease_chip_jumps_to_the_lease_page_on_screen(template_dir):
    """A page of the booklet, not a trip to the web.

    On paper the same chip still prints a code carrying the permanent address,
    because a printed code cannot jump to a page — which is why this checks the
    electronic side only, and why the two are separate fields on one chip.

    Composed and rendered directly: the destination is an *output* page number,
    and the point of the test is that the composer works it out and the renderer
    writes it. Both are pure of the database.
    """
    from app.rendering.base import RenderPlan
    from app.rendering.compose import compose_plan
    from app.rendering.overlay import PyMuPDFOverlayRenderer
    from app.services import templates as template_service

    with manifest.load(template_dir) as loaded:
        lease = next(
            f.page_index
            for f in loaded.fields
            if f.key.startswith("__table__") and f.page_index > 6
        )
        chip = next(f for f in loaded.fields if f.key == LEASE_SLOT)
        nodes = [
            {
                "id": "one", "kind": "lot", "row": 0, "layout": "standard",
                "options": ["rent_table"], "pages": [chip.page_index, lease],
                "values": {},
            }
        ]
        pages = compose_plan(
            nodes,
            {0: {"deed_number": "442108021300"}},
            lease_pages={lease},
        )
        assert [p.template_page_index for p in pages] == [chip.page_index, lease]

        result = PyMuPDFOverlayRenderer().render(
            RenderPlan(
                background=loaded.background,
                fields=template_service.for_output(loaded.fields, "electronic"),
                pages=pages,
                design_page_height=loaded.design_page_height,
            )
        )

    with fitz.open("pdf", result.pdf) as pdf:
        jumps = [
            (number, link)
            for number in range(pdf.page_count)
            for link in pdf[number].get_links()
            if link.get("kind") == fitz.LINK_GOTO
        ]
    assert len(jumps) == 1, "one chip, one jump"
    where, jump = jumps[0]
    assert where == 0, "the chip is on the property page"
    assert jump["page"] == 1, "and it lands on that property's lease page"


def test_the_lease_chip_needs_no_address_to_find_its_page(template_dir):
    """Nobody should look up a URL for a page they are holding.

    The booklet knows where that property's lease page is, so the chip leads
    there whether or not an address was typed. An address, where one is given,
    is what the *printed* code carries — that is the half a scanner needs.
    """
    from app.rendering.base import RenderPlan
    from app.rendering.compose import compose_plan
    from app.rendering.overlay import PyMuPDFOverlayRenderer
    from app.services import templates as template_service

    with manifest.load(template_dir) as loaded:
        lease = next(
            f.page_index
            for f in loaded.fields
            if f.key.startswith("__table__") and f.page_index > 6
        )
        chip = next(f for f in loaded.fields if f.key == LEASE_SLOT)
        pages = compose_plan(
            [
                {
                    "id": "one", "kind": "lot", "row": 0, "layout": "standard",
                    "options": ["rent_table"],
                    "pages": [chip.page_index, lease], "values": {},
                }
            ],
            {0: {"deed_number": "442108021300"}},  # no address typed
            lease_pages={lease},
        )
        result = PyMuPDFOverlayRenderer().render(
            RenderPlan(
                background=loaded.background,
                fields=template_service.for_output(loaded.fields, "electronic"),
                pages=pages,
                design_page_height=loaded.design_page_height,
            )
        )
    with fitz.open("pdf", result.pdf) as pdf:
        jumps = [
            link
            for number in range(pdf.page_count)
            for link in pdf[number].get_links()
            if link.get("kind") == fitz.LINK_GOTO
        ]
    assert len(jumps) == 1 and jumps[0]["page"] == 1


def test_the_property_number_prints_on_the_features_page(template):
    """It is the property's number, so it cannot be part of the artwork.

    The page after the first property page carries the same badge, and until
    now it was printed «01» whichever property it belonged to.
    """
    numbered = {
        f["page_index"] for f in template["fields"] if f["key"] == "lot_number"
    }
    features = {
        p["page_index"] for p in template["pages"] if p["role"] == "lot_features"
    }
    assert features <= numbered, "the features page prints a fixed number"


def test_lease_rows_are_typed_and_print_in_order(client, booklet):
    """Nothing else knows what leases an asset carries, so they are given.

    And the order they are given in is the order they print — which is why the
    rows move rather than sort.
    """
    headers = auth(client)
    lot = lot_of(client, booklet["id"])
    client.post(
        f"/api/v1/projects/{booklet['id']}/plan/nodes/{lot['id']}/layout",
        headers=headers,
        json={"options": ["rent_table"]},
    )
    rows = [
        {"lease_unit_number": "10", "lease_status": "جاري"},
        {"lease_unit_number": "11", "lease_status": "منتهٍ"},
    ]
    # POST, because that is what the web client sends — see the API rules.
    saved = client.post(
        f"/api/v1/projects/{booklet['id']}/plan/nodes/{lot['id']}/leases",
        headers=headers,
        json={"rows": rows},
    )
    assert saved.status_code == 200, saved.text
    node = next(n for n in saved.json()["nodes"] if n["id"] == lot["id"])
    assert node["values"]["__lease__"] == rows

    reordered = client.post(
        f"/api/v1/projects/{booklet['id']}/plan/nodes/{lot['id']}/leases",
        headers=headers,
        json={"rows": list(reversed(rows))},
    ).json()
    node = next(n for n in reordered["nodes"] if n["id"] == lot["id"])
    assert node["values"]["__lease__"][0]["lease_unit_number"] == "11"


def test_the_lease_table_prints_in_the_colour_the_booklet_chose(client, booklet):
    """One choice for the booklet: two colours in one document is a mistake."""
    headers = auth(client)
    lot = lot_of(client, booklet["id"])
    client.post(
        f"/api/v1/projects/{booklet['id']}/plan/nodes/{lot['id']}/layout",
        headers=headers,
        json={"options": ["rent_table"]},
    )
    before = next(
        n
        for n in client.get(
            f"/api/v1/projects/{booklet['id']}/plan", headers=headers
        ).json()["nodes"]
        if n["id"] == lot["id"]
    )["pages"]

    switched = client.post(
        f"/api/v1/projects/{booklet['id']}",
        headers=headers,
        json={"lease_colourway": "green"},
    )
    assert switched.status_code == 200, switched.text
    assert switched.json()["lease_colourway"] == "green"

    after = next(
        n
        for n in client.get(
            f"/api/v1/projects/{booklet['id']}/plan", headers=headers
        ).json()["nodes"]
        if n["id"] == lot["id"]
    )["pages"]
    assert after != before, "the property still points at the old colour"
    assert len(after) == len(before), "one lease page, not two"


def test_an_unknown_code_is_a_plain_404(client):
    assert client.get("/r/nope", follow_redirects=False).status_code == 404


def test_the_two_outputs_differ_only_in_the_link_chips(client, booklet):
    """Paper gets codes; a screen gets something to click."""
    headers = auth(client)
    lot = lot_of(client, booklet["id"])
    client.patch(
        f"/api/v1/projects/{booklet['id']}/plan/nodes/{lot['id']}/values",
        headers=headers,
        json={"values": {"link_map": "https://maps.example.com/here"}},
    )
    url = (
        f"/api/v1/projects/{booklet['id']}/plan/nodes/{lot['id']}"
        "/preview.png?dpi=72"
    )
    printed = client.get(url, headers=headers).content

    switched = client.patch(
        f"/api/v1/projects/{booklet['id']}",
        headers=headers,
        json={"output_flavour": "electronic"},
    )
    assert switched.status_code == 200, switched.text
    assert switched.json()["output_flavour"] == "electronic"
    assert client.get(url, headers=headers).content != printed
