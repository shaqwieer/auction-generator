"""Saving a template must not quietly cost it anything.

The editor sends the whole field set and the server replaced it wholesale, so
every column the editor did not think to send back came out at its default. That
is invisible: the screen still shows what the operator typed, and the damage is
to columns the editor never displays -- `preserve_aspect`, `clip`, `clip_holes`.
Those are how a photograph is masked to the frame the designer drew and kept off
the number badge sitting on top of it, so an operator renaming one field turned
every photo frame in the booklet back into a rectangle.

The rule these tests hold: **a save changes what it was asked to change, and
nothing else.** Not "the editor remembers to send everything" -- that is a
promise a future column breaks silently -- but that an omitted column keeps
whatever it already had.
"""

from __future__ import annotations

import pytest

from tests.conftest import auth


@pytest.fixture
def staff(client) -> dict[str, str]:
    return auth(client, "sara@matbaa.sa", "secret12")


@pytest.fixture
def template(client, staff) -> dict:
    return client.get("/api/v1/templates", headers=staff).json()[0]


@pytest.fixture(autouse=True)
def restore_fields(client, staff, template):
    """Put the field set back after each test.

    The app fixture is shared across the module, so one test's save is the next
    test's starting point. Restoring is itself a save through the same endpoint,
    which only works because the endpoint keeps what it is not told to change --
    the property under test, used as the test harness.
    """
    before = _detail(client, staff, template["id"])["fields"]
    yield
    client.put(
        f"/api/v1/templates/{template['id']}/fields",
        headers=staff,
        json=[_as_editor_sends(f) for f in before],
    )


def _detail(client, staff, template_id: str) -> dict:
    response = client.get(f"/api/v1/templates/{template_id}", headers=staff)
    assert response.status_code == 200, response.text
    return response.json()


def _masked(fields: list[dict]) -> list[dict]:
    return [f for f in fields if f.get("clip") or f.get("clip_holes")]


def _as_editor_sends(field: dict, *, drop: tuple[str, ...] = ()) -> dict:
    """One field the way the editor's own draft is shaped.

    The editor builds its draft column by column, so a column it does not name
    simply is not in the payload. ``drop`` reproduces that.
    """
    out = {k: v for k, v in field.items() if k not in {"origin"}}
    for key in drop:
        out.pop(key, None)
    return out


MASK_COLUMNS = ("preserve_aspect", "clip", "clip_holes")


def test_the_built_template_has_masks_to_lose(client, staff, template):
    """Guard on the fixture: without these the rest proves nothing."""
    fields = _detail(client, staff, template["id"])["fields"]
    assert _masked(fields), "no masked fields; this suite cannot see the bug"


def test_a_save_that_never_mentions_masks_keeps_them(client, staff, template):
    """The bug, stated as a rule.

    The editor has no control for a clip path and never sends one back. That
    must mean "leave it alone", not "there isn't one".
    """
    before = _detail(client, staff, template["id"])["fields"]
    masked = {f["key"]: f for f in _masked(before)}

    payload = [_as_editor_sends(f, drop=MASK_COLUMNS) for f in before]
    response = client.put(
        f"/api/v1/templates/{template['id']}/fields", headers=staff, json=payload
    )
    assert response.status_code == 200, response.text

    after = {(f["page_index"], f["key"]): f for f in response.json()["fields"]}
    for key, was in masked.items():
        now = after[(was["page_index"], key)]
        assert now["clip"] == was["clip"], f"{key} lost its frame outline"
        assert now["clip_holes"] == was["clip_holes"], f"{key} lost its holes"
        assert now["preserve_aspect"] == was["preserve_aspect"]


def test_a_save_that_never_mentions_the_table_keeps_its_ruling(
    client, staff, template
):
    """The same rule, for the column that decides how tall a table is drawn.

    `table_spec` carries the ruling «بيان العقارات» is redrawn from, and the
    editor has no control for it either. Dropped on a save, the summary page
    goes quietly back to ten ruled rows however many properties the auction
    has -- and the screen would still show exactly what the operator expected.
    """
    before = _detail(client, staff, template["id"])["fields"]
    ruled = {
        f["key"]: f
        for f in before
        if (f.get("table_spec") or {}).get("frame")
    }
    assert ruled, "no table carries a frame; this test cannot see the bug"

    payload = [_as_editor_sends(f, drop=("table_spec",)) for f in before]
    response = client.put(
        f"/api/v1/templates/{template['id']}/fields", headers=staff, json=payload
    )
    assert response.status_code == 200, response.text

    after = {(f["page_index"], f["key"]): f for f in response.json()["fields"]}
    for key, was in ruled.items():
        now = after[(was["page_index"], key)]
        assert now["table_spec"] == was["table_spec"], (
            f"{key} lost the ruling it is drawn from"
        )


def test_the_ruling_survives_the_database(client, staff, template):
    """Read back as a spec, not just as JSON.

    Every other test of the frame loads it from the built manifest on disk.
    That is not the route a booklet is printed through: the API serves from
    `TemplateField.table_spec`, and a parser that stopped at `row_pitch` would
    leave the manifest tests green and the printed page ruled for ten.
    """
    from app.core.db import SessionLocal
    from app.models import TemplateField
    from app.rendering.base import FieldType
    from app.services.templates import field_to_spec

    session = SessionLocal()
    try:
        rows = [
            r
            for r in session.query(TemplateField).all()
            if r.type == FieldType.TABLE.value and (r.table_spec or {}).get("frame")
        ]
        assert rows, "no table field in the database carries a frame"
        for row in rows:
            spec = field_to_spec(row)
            frame = spec.table.frame
            assert frame is not None, f"{row.key} lost its ruling on the way out"
            assert len(frame.rules) == spec.table.rows
            assert frame.paths and all(p.items for p in frame.paths)
            assert any(p.fill for p in frame.paths), "the numbered tab is filled"
            assert any(p.stroke for p in frame.paths), "the rules are stroked"
    finally:
        session.close()


def test_a_save_still_applies_what_it_does_carry(client, staff, template):
    """The counterweight: preserving must not become ignoring."""
    before = _detail(client, staff, template["id"])["fields"]
    target = _masked(before)[0]

    payload = []
    for field in before:
        sent = _as_editor_sends(field, drop=MASK_COLUMNS)
        if field["id"] == target["id"]:
            sent["label"] = "اسم جديد"
            sent["font_size_pt"] = 21.5
        payload.append(sent)

    response = client.put(
        f"/api/v1/templates/{template['id']}/fields", headers=staff, json=payload
    )
    assert response.status_code == 200, response.text
    after = {f["id"]: f for f in response.json()["fields"]}
    assert after[target["id"]]["label"] == "اسم جديد"
    assert after[target["id"]]["font_size_pt"] == pytest.approx(21.5)
    # ...and the mask it never mentioned is still there.
    assert after[target["id"]]["clip"] == target["clip"]


def test_a_mask_can_still_be_cleared_on_purpose(client, staff, template):
    """Omitting is not the same as sending null.

    An operator who redraws a frame must be able to take the old one off, or
    "never strip" would mean "never change".
    """
    before = _detail(client, staff, template["id"])["fields"]
    target = _masked(before)[0]

    payload = []
    for field in before:
        sent = _as_editor_sends(field, drop=MASK_COLUMNS)
        if field["id"] == target["id"]:
            sent["clip"] = None
            sent["clip_holes"] = None
        payload.append(sent)

    response = client.put(
        f"/api/v1/templates/{template['id']}/fields", headers=staff, json=payload
    )
    assert response.status_code == 200, response.text
    after = {f["id"]: f for f in response.json()["fields"]}
    assert not after[target["id"]]["clip"]
    assert not after[target["id"]]["clip_holes"]


def test_renaming_a_field_does_not_cost_it_its_mask(client, staff, template):
    """A field is the row, not its name.

    Matching a saved field to its stored row by (page, key) loses everything the
    moment somebody corrects a key -- which is precisely what the editor is for.
    """
    before = _detail(client, staff, template["id"])["fields"]
    target = _masked(before)[0]

    payload = []
    for field in before:
        sent = _as_editor_sends(field, drop=MASK_COLUMNS)
        if field["id"] == target["id"]:
            sent["key"] = f"{field['key']}_renamed"
        payload.append(sent)

    response = client.put(
        f"/api/v1/templates/{template['id']}/fields", headers=staff, json=payload
    )
    assert response.status_code == 200, response.text
    after = {f["id"]: f for f in response.json()["fields"]}
    assert after[target["id"]]["key"] == f"{target['key']}_renamed"
    assert after[target["id"]]["clip"] == target["clip"], "rename dropped the mask"


def test_a_client_too_old_to_send_ids_still_keeps_masks(client, staff, template):
    """The guarantee cannot depend on the client being current.

    A deployment mid-rollout has the old bundle in somebody's tab. Matching
    falls back to the name the field goes by, which the duplicate guard above
    has already established is unique on its page.
    """
    before = _detail(client, staff, template["id"])["fields"]
    target = _masked(before)[0]

    payload = [
        _as_editor_sends(f, drop=(*MASK_COLUMNS, "id")) for f in before
    ]
    response = client.put(
        f"/api/v1/templates/{template['id']}/fields", headers=staff, json=payload
    )
    assert response.status_code == 200, response.text
    after = {(f["page_index"], f["key"]): f for f in response.json()["fields"]}
    assert after[(target["page_index"], target["key"])]["clip"] == target["clip"]


def test_an_id_that_no_longer_exists_falls_back_to_the_name(
    client, staff, template
):
    """A rebuilt template has new row ids; a stale tab still must not strip."""
    import uuid as _uuid

    before = _detail(client, staff, template["id"])["fields"]
    target = _masked(before)[0]

    payload = []
    for field in before:
        sent = _as_editor_sends(field, drop=MASK_COLUMNS)
        if field["id"] == target["id"]:
            sent["id"] = str(_uuid.uuid4())
        payload.append(sent)

    response = client.put(
        f"/api/v1/templates/{template['id']}/fields", headers=staff, json=payload
    )
    assert response.status_code == 200, response.text
    after = {(f["page_index"], f["key"]): f for f in response.json()["fields"]}
    now = after[(target["page_index"], target["key"])]
    assert now["clip"] == target["clip"]
    # Matched, not duplicated.
    assert len(response.json()["fields"]) == len(before)


def test_a_field_left_out_of_the_payload_is_still_deleted(client, staff, template):
    """Preserving columns must not turn into preserving fields."""
    before = _detail(client, staff, template["id"])["fields"]
    doomed = before[0]

    payload = [
        _as_editor_sends(f, drop=MASK_COLUMNS)
        for f in before
        if f["id"] != doomed["id"]
    ]
    response = client.put(
        f"/api/v1/templates/{template['id']}/fields", headers=staff, json=payload
    )
    assert response.status_code == 200, response.text
    assert doomed["id"] not in {f["id"] for f in response.json()["fields"]}


def test_a_new_field_arrives_with_the_defaults_it_was_given(client, staff, template):
    before = _detail(client, staff, template["id"])["fields"]
    fresh = {
        "key": "brand_new_field",
        "label": "حقل جديد",
        "page_index": before[0]["page_index"],
        "type": "text",
        "x": 0.1,
        "y": 0.1,
        "w": 0.2,
        "h": 0.02,
    }
    payload = [_as_editor_sends(f, drop=MASK_COLUMNS) for f in before] + [fresh]
    response = client.put(
        f"/api/v1/templates/{template['id']}/fields", headers=staff, json=payload
    )
    assert response.status_code == 200, response.text
    made = next(
        f for f in response.json()["fields"] if f["key"] == "brand_new_field"
    )
    assert made["font_family"] == "RuaqArabic"
    assert not made["clip"]


def test_two_fields_with_one_key_on_one_page_are_still_refused(
    client, staff, template
):
    before = _detail(client, staff, template["id"])["fields"]
    twin = _as_editor_sends(before[0], drop=MASK_COLUMNS)
    twin.pop("id", None)
    payload = [_as_editor_sends(f, drop=MASK_COLUMNS) for f in before] + [twin]
    response = client.put(
        f"/api/v1/templates/{template['id']}/fields", headers=staff, json=payload
    )
    assert response.status_code == 400
