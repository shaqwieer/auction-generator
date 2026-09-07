"""The step-by-step booklet builder, over HTTP.

The builder replaces the four-step wizard, so these cover the whole path a
client takes: pick a cover, add properties, give one the برج layout, turn an
optional page on, type onto a page, look at it, and generate.
"""

from __future__ import annotations

import fitz
import pytest

from tests.conftest import PNG_MAGIC, auth, workbook_bytes


@pytest.fixture(scope="module")
def template(client) -> dict:
    body = client.get("/api/v1/templates", headers=auth(client)).json()
    assert body, "the seeded template should be visible to a client"
    return client.get(
        f"/api/v1/templates/{body[0]['id']}", headers=auth(client)
    ).json()


@pytest.fixture
def booklet(client, template) -> dict:
    """A fresh project with three properties laid out."""
    created = client.post(
        "/api/v1/projects",
        headers=auth(client),
        json={
            "name": "مزاد الاختبار",
            "template_id": template["id"],
            "lot_count": 3,
        },
    )
    assert created.status_code == 201, created.text
    return created.json()


def plan_of(client, project_id: str) -> dict:
    response = client.get(f"/api/v1/projects/{project_id}/plan", headers=auth(client))
    assert response.status_code == 200, response.text
    return response.json()


# --------------------------------------------------------------- the template


def test_template_reports_what_each_page_is(template):
    """Without page roles the builder has nothing to offer."""
    assert template["pages"], "the built template should carry page roles"
    roles = {p["role"] for p in template["pages"]}
    assert {"cover", "lot", "lot_table", "contact"} <= roles


def test_the_cover_slot_offers_the_six_designs_and_nothing_else(template):
    """Six covers. A client picks one of them; they cannot supply a seventh."""
    covers = [p for p in template["pages"] if p["slot"] == "cover"]
    offered = [c for c in covers if not c["options"].get("source_cover")]
    assert [c["name"] for c in offered] == [f"غلاف {n}" for n in range(1, 7)]
    assert not any(c["options"].get("own_artwork") for c in covers)


def test_the_summary_table_is_offered_in_two_colours(template):
    tables = [p for p in template["pages"] if p["slot"] == "lot_table"]
    assert {p["layout"] for p in tables} == {"green", "blue"}


def test_both_lot_layouts_are_offered(template):
    layouts = {p["layout"] for p in template["pages"] if p["role"] == "lot"}
    assert layouts == {"standard", "tower"}


def test_every_optional_page_is_offered_and_none_defaults_on(template):
    """The guide adds these حسب الحاجة, so a booklet starts with none of them.

    مميزات العقار used to be withheld as well: its lease copy is outlined and
    survived the bake, so the page would have shipped somebody else's figures.
    That copy is removed now and the page is a choice like the rest.
    """
    optional = [p for p in template["pages"] if p["is_optional"]]
    # Six pages, five choices: بيان عقود الإيجار is drawn in two colours and the
    # booklet picks one, so the builder offers it once.
    assert len({p["role"] for p in optional}) == 5, [p["name"] for p in optional]
    assert not any(p["default_on"] for p in optional)
    assert not any(p["options"].get("needs_artwork") for p in optional), (
        "an optional page nobody can use is not a choice"
    )


# ------------------------------------------------------------------ the plan


def test_a_new_project_is_laid_out_ready_to_fill(client, booklet):
    plan = plan_of(client, booklet["id"])
    kinds = [n["kind"] for n in plan["nodes"]]
    assert kinds.count("lot") == 3
    assert kinds.count("table") == 1
    assert kinds[0] == "page", "the cover comes first"
    # Every node is one page to start with: the three properties take their
    # default قياسي layout and none of the optional pages.
    assert plan["predicted_pages"] == len(plan["nodes"])
    assert all(len(n["pages"]) == 1 for n in plan["nodes"] if n["kind"] == "lot")
    assert booklet["has_plan"] is True


def test_choosing_a_cover_picks_that_page(client, template):
    covers = [p for p in template["pages"] if p["slot"] == "cover"]
    chosen = covers[3]
    created = client.post(
        "/api/v1/projects",
        headers=auth(client),
        json={
            "name": "غلاف آخر",
            "template_id": template["id"],
            "cover_page": chosen["page_index"],
            "lot_count": 1,
        },
    ).json()
    plan = plan_of(client, created["id"])
    assert plan["nodes"][0]["page"] == chosen["page_index"]


def test_the_cover_can_be_changed_again_and_again(client, booklet, template):
    """Swapping the cover keeps the node, so the chooser is still there after.

    It used to add a page and delete the old one, and the added node carried no
    cover slot — so the second choice had nothing to offer, and whatever had
    been typed onto the cover went with the deleted node.
    """
    offered = [
        p for p in template["pages"]
        if p["slot"] == "cover" and not p["options"].get("source_cover")
    ]
    plan = plan_of(client, booklet["id"])
    cover = plan["nodes"][0]
    client.patch(
        f"/api/v1/projects/{booklet['id']}/plan/nodes/{cover['id']}/values",
        headers=auth(client),
        json={"values": {"auction_title": "مزاد الرياض"}},
    )

    for design in offered[:3]:
        response = client.post(
            f"/api/v1/projects/{booklet['id']}/plan/nodes/{cover['id']}/layout",
            headers=auth(client),
            json={"page": design["page_index"]},
        )
        assert response.status_code == 200, response.text
        node = response.json()["nodes"][0]
        assert node["id"] == cover["id"], "the cover keeps its node"
        assert node["page"] == design["page_index"]
        assert node["slot"] == "cover", "still a cover, so still choosable"
        assert node["values"]["auction_title"] == "مزاد الرياض"


def test_a_booklet_starts_with_no_properties_and_grows(client, template):
    """Nobody knows the count up front, so nothing asks for it.

    A property added from wherever the client happens to be — the cover, as
    often as not — still has to land where properties go.
    """
    created = client.post(
        "/api/v1/projects",
        headers=auth(client),
        json={"name": "يبدأ فارغًا", "template_id": template["id"]},
    ).json()
    plan = plan_of(client, created["id"])
    assert not [n for n in plan["nodes"] if n["kind"] == "lot"]

    added = client.post(
        f"/api/v1/projects/{created['id']}/plan/nodes",
        headers=auth(client),
        json={"kind": "lot", "revision": plan["revision"]},
    )
    assert added.status_code == 200, added.text
    nodes = added.json()["nodes"]
    kinds = [n["kind"] for n in nodes]
    assert kinds.count("lot") == 1
    assert kinds.index("lot") > kinds.index("table"), (
        "a property belongs after the summary table, not straight after the cover"
    )


def test_a_page_is_switched_off_rather_than_thrown_away(client, booklet):
    """«إيقاف» takes it out of this issue; «استعادة» brings it back intact."""
    plan = plan_of(client, booklet["id"])
    lots = [n for n in plan["nodes"] if n["kind"] == "lot"]
    victim = lots[1]
    client.patch(
        f"/api/v1/projects/{booklet['id']}/plan/nodes/{victim['id']}/values",
        headers=auth(client),
        json={"values": {"deed_number": "442108021305"}},
    )
    before = plan_of(client, booklet["id"])["predicted_pages"]

    off = client.post(
        f"/api/v1/projects/{booklet['id']}/plan/nodes/{victim['id']}/enabled",
        headers=auth(client),
        json={"on": False},
    )
    assert off.status_code == 200, off.text
    body = off.json()
    still = next(n for n in body["nodes"] if n["id"] == victim["id"])
    assert still["off"] is True, "it stays in the plan"
    assert len(body["nodes"]) == len(plan["nodes"]), "nothing was removed"
    assert body["predicted_pages"] == before - 1

    on = client.post(
        f"/api/v1/projects/{booklet['id']}/plan/nodes/{victim['id']}/enabled",
        headers=auth(client),
        json={"on": True},
    ).json()
    restored = next(n for n in on["nodes"] if n["id"] == victim["id"])
    assert not restored["off"]
    assert on["predicted_pages"] == before


def test_a_switched_off_property_leaves_the_summary_table_too(client, booklet):
    """Otherwise it is listed in بيان العقارات with no page to point at."""
    plan = plan_of(client, booklet["id"])
    lots = [n for n in plan["nodes"] if n["kind"] == "lot"]
    for index, lot in enumerate(lots):
        client.patch(
            f"/api/v1/projects/{booklet['id']}/plan/nodes/{lot['id']}/values",
            headers=auth(client),
            json={"values": {"deed_number": f"44210802130{index}"}},
        )
    client.post(
        f"/api/v1/projects/{booklet['id']}/plan/nodes/{lots[1]['id']}/enabled",
        headers=auth(client),
        json={"on": False},
    )

    table = next(n for n in plan["nodes"] if n["kind"] == "table")
    response = client.get(
        f"/api/v1/projects/{booklet['id']}/plan/nodes/{table['id']}/preview.png?dpi=110",
        headers=auth(client),
    )
    assert response.status_code == 200, response.text

    # And the switched-off page still draws, so it can be looked at before it is
    # brought back.
    still = client.get(
        f"/api/v1/projects/{booklet['id']}/plan/nodes/{lots[1]['id']}/preview.png?dpi=60",
        headers=auth(client),
    )
    assert still.status_code == 200, still.text
    assert still.content.startswith(PNG_MAGIC)


def test_the_summary_table_cannot_be_switched_off(client, booklet):
    plan = plan_of(client, booklet["id"])
    table = next(n for n in plan["nodes"] if n["kind"] == "table")
    response = client.post(
        f"/api/v1/projects/{booklet['id']}/plan/nodes/{table['id']}/enabled",
        headers=auth(client),
        json={"on": False},
    )
    assert response.status_code == 409, response.text


def test_a_property_can_take_the_tower_layout(client, booklet, template):
    plan = plan_of(client, booklet["id"])
    lot = next(n for n in plan["nodes"] if n["kind"] == "lot")
    assert lot["layout"] == "standard"

    tower = next(
        p for p in template["pages"] if p["role"] == "lot" and p["layout"] == "tower"
    )
    updated = client.post(
        f"/api/v1/projects/{booklet['id']}/plan/nodes/{lot['id']}/layout",
        headers=auth(client),
        json={"layout": "tower", "revision": plan["revision"]},
    )
    assert updated.status_code == 200, updated.text
    changed = next(
        n for n in updated.json()["nodes"] if n["id"] == lot["id"]
    )
    assert changed["layout"] == "tower"
    assert changed["pages"] == [tower["page_index"]]


def test_turning_on_an_optional_page_adds_it_to_that_property_only(
    client, booklet, template
):
    plan = plan_of(client, booklet["id"])
    lots = [n for n in plan["nodes"] if n["kind"] == "lot"]
    boundaries = next(
        p for p in template["pages"] if p["role"] == "boundaries"
    )

    updated = client.post(
        f"/api/v1/projects/{booklet['id']}/plan/nodes/{lots[1]['id']}/layout",
        headers=auth(client),
        json={"options": ["boundaries"], "revision": plan["revision"]},
    ).json()

    by_id = {n["id"]: n for n in updated["nodes"]}
    assert boundaries["page_index"] in by_id[lots[1]["id"]]["pages"]
    assert boundaries["page_index"] not in by_id[lots[0]["id"]]["pages"]
    assert updated["predicted_pages"] == plan["predicted_pages"] + 1


def test_pages_can_be_duplicated_moved_and_deleted(client, booklet):
    plan = plan_of(client, booklet["id"])
    lots = [n for n in plan["nodes"] if n["kind"] == "lot"]
    target = lots[0]["id"]
    before = [n["id"] for n in plan["nodes"]]

    after_copy = client.post(
        f"/api/v1/projects/{booklet['id']}/plan/nodes/{target}/duplicate",
        headers=auth(client),
        json={"revision": plan["revision"]},
    ).json()
    assert len(after_copy["nodes"]) == len(before) + 1

    copy_id = after_copy["nodes"][before.index(target) + 1]["id"]
    assert copy_id != target

    moved = client.post(
        f"/api/v1/projects/{booklet['id']}/plan/nodes/{copy_id}/move",
        headers=auth(client),
        json={"delta": 1, "revision": after_copy["revision"]},
    ).json()
    assert [n["id"] for n in moved["nodes"]].index(copy_id) == (
        [n["id"] for n in after_copy["nodes"]].index(copy_id) + 1
    )

    removed = client.delete(
        f"/api/v1/projects/{booklet['id']}/plan/nodes/{copy_id}",
        headers=auth(client),
    ).json()
    assert copy_id not in [n["id"] for n in removed["nodes"]]


def test_duplicating_a_property_gives_it_its_own_row(client, booklet):
    """A copy is a second property, not a second view of the first.

    Two lot nodes sharing one record look right on the page rail and then print
    that property twice in the summary table, because the table is built from
    the lots in plan order.
    """
    plan = plan_of(client, booklet["id"])
    lot = next(n for n in plan["nodes"] if n["kind"] == "lot")
    client.patch(
        f"/api/v1/projects/{booklet['id']}/plan/nodes/{lot['id']}/values",
        headers=auth(client),
        json={"values": {"deed_number": "111", "property_type": "فيلا"}},
    )
    before = plan_of(client, booklet["id"])

    after = client.post(
        f"/api/v1/projects/{booklet['id']}/plan/nodes/{lot['id']}/duplicate",
        headers=auth(client),
        json={"revision": before["revision"]},
    ).json()

    lots = [n for n in after["nodes"] if n["kind"] == "lot"]
    rows = [n["row"] for n in lots]
    assert len(rows) == len(set(rows)), f"each property needs its own row: {rows}"
    assert after["predicted_pages"] == before["predicted_pages"] + 1

    records = client.get(
        f"/api/v1/projects/{booklet['id']}/records", headers=auth(client)
    ).json()
    copied = [r for r in records if r["values"].get("deed_number") == "111"]
    assert len(copied) == 2, "the copy carries the values it was made from"


def test_a_new_booklet_wears_an_offered_cover(client, booklet, template):
    """Not the export's own cover page, which the chooser does not show.

    Landing on a cover no tile is highlighted for reads as nothing selected,
    and the first thing a client does is wonder what they are looking at.
    """
    plan = plan_of(client, booklet["id"])
    cover = next(n for n in plan["nodes"] if n.get("slot") == "cover")
    offered = {
        p["page_index"]
        for p in template["pages"]
        if p["slot"] == "cover" and not p["options"].get("source_cover")
    }
    assert cover["page"] in offered


def test_the_summary_table_changes_colour(client, booklet, template):
    """The two colourways are one choice between pages, like the covers.

    Switching also has to carry ``rows_per_page`` with it, because that is what
    decides when the page repeats -- a value frozen at creation would paginate
    the new page by the old one's capacity.
    """
    plan = plan_of(client, booklet["id"])
    table = next(n for n in plan["nodes"] if n["kind"] == "table")
    blue = next(
        p for p in template["pages"]
        if p["slot"] == "lot_table" and p["layout"] == "blue"
    )

    response = client.post(
        f"/api/v1/projects/{booklet['id']}/plan/nodes/{table['id']}/layout",
        headers=auth(client),
        json={"page": blue["page_index"], "revision": plan["revision"]},
    )
    assert response.status_code == 200, response.text
    switched = next(n for n in response.json()["nodes"] if n["kind"] == "table")
    assert switched["page"] == blue["page_index"]
    assert switched["rows_per_page"] == 10

    refused = client.post(
        f"/api/v1/projects/{booklet['id']}/plan/nodes/{table['id']}/layout",
        headers=auth(client),
        json={"page": 999},
    )
    assert refused.status_code == 409, refused.text


def test_the_summary_table_cannot_be_moved_or_deleted(client, booklet):
    """Its row numbering runs across the booklet; nothing would catch it broken."""
    plan = plan_of(client, booklet["id"])
    table = next(n for n in plan["nodes"] if n["kind"] == "table")

    for path, payload in (
        (f"/plan/nodes/{table['id']}/move", {"delta": 1}),
        (f"/plan/nodes/{table['id']}/duplicate", {}),
    ):
        response = client.post(
            f"/api/v1/projects/{booklet['id']}{path}",
            headers=auth(client),
            json=payload,
        )
        assert response.status_code == 409, response.text
        assert "تلقائ" in response.json()["detail"]

    assert (
        client.delete(
            f"/api/v1/projects/{booklet['id']}/plan/nodes/{table['id']}",
            headers=auth(client),
        ).status_code
        == 409
    )


def test_a_stale_revision_is_refused_rather_than_clobbering(client, booklet):
    """A debounced value patch must not overwrite a reorder that landed first."""
    plan = plan_of(client, booklet["id"])
    lot = next(n for n in plan["nodes"] if n["kind"] == "lot")
    stale = plan["revision"]

    client.post(
        f"/api/v1/projects/{booklet['id']}/plan/nodes/{lot['id']}/layout",
        headers=auth(client),
        json={"layout": "tower", "revision": stale},
    )
    late = client.post(
        f"/api/v1/projects/{booklet['id']}/plan/nodes/{lot['id']}/values",
        headers=auth(client),
        json={"values": {"deed_number": "1"}, "revision": stale},
    )
    assert late.status_code == 409, late.text


# ---------------------------------------------------------------- filling in


def test_typing_on_a_property_page_writes_to_its_record(client, booklet):
    plan = plan_of(client, booklet["id"])
    lot = next(n for n in plan["nodes"] if n["kind"] == "lot")
    response = client.patch(
        f"/api/v1/projects/{booklet['id']}/plan/nodes/{lot['id']}/values",
        headers=auth(client),
        json={"values": {"deed_number": "442108021305", "property_type": "فيلا"}},
    )
    assert response.status_code == 200, response.text

    records = client.get(
        f"/api/v1/projects/{booklet['id']}/records", headers=auth(client)
    ).json()
    assert records[0]["values"]["deed_number"] == "442108021305"


def test_typing_on_a_fixed_page_stays_on_that_page(client, booklet):
    """The contact page's values belong to no property, so they live on it."""
    plan = plan_of(client, booklet["id"])
    page = [n for n in plan["nodes"] if n["kind"] == "page"][-1]
    updated = client.patch(
        f"/api/v1/projects/{booklet['id']}/plan/nodes/{page['id']}/values",
        headers=auth(client),
        json={"values": {"contact_phone": "0555000000"}},
    ).json()
    node = next(n for n in updated["nodes"] if n["id"] == page["id"])
    assert node["values"]["contact_phone"] == "0555000000"


def test_importing_a_spreadsheet_lays_its_rows_out_as_pages(client, template):
    """Excel is an action inside the builder now, not a step before it."""
    created = client.post(
        "/api/v1/projects",
        headers=auth(client),
        json={"name": "استيراد", "template_id": template["id"]},
    ).json()
    assert not [n for n in plan_of(client, created["id"])["nodes"] if n["kind"] == "lot"]

    client.post(
        f"/api/v1/projects/{created['id']}/datasource",
        headers=auth(client),
        files={"file": ("lots.xlsx", workbook_bytes(), "application/vnd.ms-excel")},
    )
    plan = plan_of(client, created["id"])
    lots = [n for n in plan["nodes"] if n["kind"] == "lot"]
    assert len(lots) == 3
    # They land among the pages, not after the closing ones.
    kinds = [n["kind"] for n in plan["nodes"]]
    assert kinds.index("lot") < len(kinds) - 1


def test_reimporting_keeps_a_layout_already_chosen(client, template):
    created = client.post(
        "/api/v1/projects",
        headers=auth(client),
        json={"name": "إعادة استيراد", "template_id": template["id"], "lot_count": 3},
    ).json()
    plan = plan_of(client, created["id"])
    lot = [n for n in plan["nodes"] if n["kind"] == "lot"][1]
    client.post(
        f"/api/v1/projects/{created['id']}/plan/nodes/{lot['id']}/layout",
        headers=auth(client),
        json={"layout": "tower", "revision": plan["revision"]},
    )
    client.post(
        f"/api/v1/projects/{created['id']}/datasource",
        headers=auth(client),
        files={"file": ("lots.xlsx", workbook_bytes(), "application/vnd.ms-excel")},
    )
    after = plan_of(client, created["id"])
    kept = next(n for n in after["nodes"] if n["id"] == lot["id"])
    assert kept["layout"] == "tower", "a correction must not undo a choice"


# ------------------------------------------------------------------ preview


def test_a_page_previews_as_it_will_print(client, booklet):
    plan = plan_of(client, booklet["id"])
    lot = next(n for n in plan["nodes"] if n["kind"] == "lot")
    client.patch(
        f"/api/v1/projects/{booklet['id']}/plan/nodes/{lot['id']}/values",
        headers=auth(client),
        json={"values": {"deed_number": "442108021305"}},
    )
    response = client.get(
        f"/api/v1/projects/{booklet['id']}/plan/nodes/{lot['id']}/preview.png?dpi=72",
        headers=auth(client),
    )
    assert response.status_code == 200, response.text
    assert response.content.startswith(PNG_MAGIC)
    assert response.headers["etag"]


def test_the_preview_can_leave_out_the_field_being_typed_into(client, booklet):
    """The page under the box must not print the value the box is showing.

    Both drew it, in two different fonts a few points apart, and the page came
    out looking like it carried the value twice.
    """
    plan = plan_of(client, booklet["id"])
    cover = plan["nodes"][0]
    client.patch(
        f"/api/v1/projects/{booklet['id']}/plan/nodes/{cover['id']}/values",
        headers=auth(client),
        json={"values": {"auction_title": "مزاد الرياض"}},
    )
    base = f"/api/v1/projects/{booklet['id']}/plan/nodes/{cover['id']}/preview.png?dpi=90"
    whole = client.get(base, headers=auth(client))
    holed = client.get(f"{base}&omit=auction_title", headers=auth(client))

    assert whole.status_code == 200 and holed.status_code == 200
    assert holed.content.startswith(PNG_MAGIC)
    assert holed.content != whole.content, "the value is still on the page"
    # An unknown key changes nothing, so a stale focus cannot blank a page.
    same = client.get(f"{base}&omit=not_a_field", headers=auth(client))
    assert same.content == whole.content


def test_the_preview_is_cached_on_its_inputs(client, booklet):
    plan = plan_of(client, booklet["id"])
    node = plan["nodes"][0]["id"]
    url = f"/api/v1/projects/{booklet['id']}/plan/nodes/{node}/preview.png?dpi=60"
    first = client.get(url, headers=auth(client))
    second = client.get(url, headers=auth(client))
    assert first.headers["etag"] == second.headers["etag"]
    assert first.content == second.content


def test_another_client_cannot_read_the_plan(client, booklet):
    assert (
        client.get(f"/api/v1/projects/{booklet['id']}/plan").status_code == 401
    )


# ----------------------------------------------------------------- and print


def test_the_assembled_booklet_generates(client, booklet):
    """The whole point: what the builder assembled is what comes out."""
    headers = auth(client)
    plan = plan_of(client, booklet["id"])
    for index, lot in enumerate(n for n in plan["nodes"] if n["kind"] == "lot"):
        client.patch(
            f"/api/v1/projects/{booklet['id']}/plan/nodes/{lot['id']}/values",
            headers=headers,
            json={
                "values": {
                    "deed_number": f"44210802130{index}",
                    "property_type": "فيلا",
                }
            },
        )

    expected = plan_of(client, booklet["id"])["predicted_pages"]
    queued = client.post(
        f"/api/v1/projects/{booklet['id']}/generate", headers=headers
    )
    assert queued.status_code == 202, queued.text
    job_id = queued.json()["id"]

    for _ in range(120):
        body = client.get(f"/api/v1/jobs/{job_id}", headers=headers).json()
        if body["status"] in ("succeeded", "failed", "cancelled"):
            break
    assert body["status"] == "succeeded", body.get("error_summary")
    assert body["page_count"] == expected

    download = client.get(f"/api/v1/jobs/{job_id}/download", headers=headers)
    with fitz.open("pdf", download.content) as pdf:
        text = "".join(pdf[i].get_text() for i in range(pdf.page_count))
    assert "442108021300" in text, "the first property should be in the booklet"
