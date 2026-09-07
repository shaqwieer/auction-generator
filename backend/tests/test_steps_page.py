"""خطوات المشاركة: the guide's sentence with this booklet's words in it.

The page is mostly design and slightly data. «إستعراض المزادات» and «الفوز
بالمزاد» are true of every auction ever held; «تسجيل الدخول في منصة مباشر
للمزادات» names a platform, «إختيار مزاد ( أعيان حائل )» names an auction, and
«قابلة للإسترداد» is a term of that auction's sale.

So three of the five captions carry a field and two do not, and the two that do
not are never cleared -- which is the only way to be sure they still read the
way the designer set them. The tests below hold both halves at once: that the
fixed captions survive untouched, and that the three that are fields print their
fixed wording *and* the booklet's own words.
"""

from __future__ import annotations

import json
import unicodedata
from pathlib import Path

import fitz
import pytest

from app.rendering import manifest
from app.rendering.base import Fit, PageInstance, RenderPlan
from app.rendering.compose import DEFAULTS_KEY, booklet_facts
from app.rendering.overlay import PyMuPDFOverlayRenderer
from app.rendering.pagemap import PageRole
from scripts.pagemaps.auction_infath import MAPS

BACKEND = Path(__file__).resolve().parent.parent
BUILT = BACKEND / "var" / "templates"

#: The wording the designer set that no client is asked for.
FIXED_CAPTIONS = ("إستعراض المزادات", "الفوز بالمزاد")

#: The three the client is asked for, and the wording each is wrapped in.
SLOTS = {
    "steps_platform": ("تسجيل الدخول في", ""),
    "steps_refundable": ("سداد قيمة المشاركة في", ")"),
    "steps_auction_name": ("إختيار مزاد", "والدخول للمشاركة"),
}


def _slugs_with_steps() -> list[str]:
    return [
        m.slug
        for m in MAPS
        if any(p.role is PageRole.STEPS for p in m.pages)
    ]


@pytest.fixture(scope="module", params=_slugs_with_steps())
def built(request) -> dict:
    directory = BUILT / request.param
    if not (directory / "template.json").exists():
        pytest.skip(f"{request.param} not built; run build_infath_templates.py")
    data = json.loads((directory / "template.json").read_text(encoding="utf-8"))
    data["_dir"] = directory
    return data


def fold(text: str) -> str:
    """Letters alone, in logical order.

    Both the export and our own render extract as presentation forms -- ﻡ, ﺸ,
    ﺎ rather than م, ش, ا -- so nothing matches until they are folded back. This
    is the same trap that makes derive.py take geometry and never strings.
    """
    return "".join(unicodedata.normalize("NFKC", text).split())


def _steps_page(built: dict) -> int:
    pages = [p for p in built["pages"] if p["role"] == PageRole.STEPS.value]
    assert len(pages) == 1, "one steps page per booklet"
    return pages[0]["page_index"]


def _steps_fields(built: dict) -> dict[str, dict]:
    index = _steps_page(built)
    return {
        f["key"]: f
        for f in built["fields"]
        if f["page_index"] == index and f["key"].startswith("steps_")
    }


# ----------------------------------------------------- what is asked for


def test_the_client_is_asked_for_three_phrases_not_five_sentences(built):
    """Only the words that change are a field.

    Asking for the whole caption invited a client to retype the guide at us,
    and asking for nothing left the page blank, because baking clears whatever
    a field will draw over.
    """
    assert set(_steps_fields(built)) == set(SLOTS)


def test_each_slot_carries_the_wording_printed_around_it(built):
    for key, (opening, closing) in SLOTS.items():
        field = _steps_fields(built)[key]
        assert opening in field["prefix"], f"{key} lost its opening wording"
        if closing:
            assert closing in field["suffix"], f"{key} lost its closing wording"
        assert field["fit"] == Fit.WRAP.value
        # The face and leading the page is drawn in, not the field defaults.
        assert field["font_weight"] == "Light"
        assert field["line_height"] == pytest.approx(1.18)


def test_a_caption_nobody_edits_is_not_a_field_and_so_is_never_cleared(built):
    """Steps 2 and 5 stay in the artwork, which is why they cannot drift.

    A field would have them redrawn on every booklet; not being one, they are
    the designer's own pixels and are provably identical to the export.
    """
    index = _steps_page(built)
    with fitz.open(built["_dir"] / "background.pdf") as doc:
        printed = fold(doc[index].get_text())
    for caption in FIXED_CAPTIONS:
        assert fold(caption) in printed, (
            f"{caption} is no longer printed on the baked steps page"
        )


def test_the_sample_auction_is_not_baked_into_the_page(built):
    """«أعيان حائل» is the designer's auction, not the client's.

    The name is inside a field's rect, so the bake clears it and the render
    puts this booklet's own title there instead.
    """
    index = _steps_page(built)
    with fitz.open(built["_dir"] / "background.pdf") as doc:
        printed = fold(doc[index].get_text())
    assert fold("أعيان حائل") not in printed


# ------------------------------------------------- what the page prints


def _render(slug: str, values: dict) -> str:
    template = manifest.load(BUILT / slug)
    index = next(
        f["page_index"]
        for f in json.loads((BUILT / slug / "template.json").read_text("utf-8"))["pages"]
        if f["role"] == PageRole.STEPS.value
    )
    plan = RenderPlan(
        background=template.background,
        fields=template.fields,
        pages=[PageInstance(template_page_index=index, values=values)],
        design_page_height=template.design_page_height,
    )
    result = PyMuPDFOverlayRenderer().render(plan)
    with fitz.open(stream=result.pdf, filetype="pdf") as doc:
        return fold(doc[0].get_text())


def test_nothing_typed_still_prints_the_guides_sentence(built):
    """The page was cleared to make room for the caption; it must come back.

    A field that draws nothing when its value is empty would take the
    designer's wording down with it, and the page would print five numbers,
    five icons and no instructions at all.
    """
    printed = _render(
        built["slug"],
        {DEFAULTS_KEY: {"platform_name": "منصة مباشر", "auction_title": "أعيان حائل"}},
    )
    assert fold("سداد قيمة المشاركة") in printed
    assert fold("قابلة للإسترداد") in printed
    assert fold("أعيان حائل") in printed
    assert fold("منصة مباشر") in printed


def test_a_typed_phrase_replaces_only_itself(built):
    printed = _render(
        built["slug"],
        {
            DEFAULTS_KEY: {"platform_name": "منصة مباشر", "auction_title": "أعيان حائل"},
            "steps_refundable": "غير قابلة للإسترداد",
        },
    )
    assert fold("غير قابلة للإسترداد") in printed
    # The wording around it is not the client's to lose.
    assert fold("سداد قيمة المشاركة") in printed
    # And the caption they did not touch is untouched.
    assert fold("أعيان حائل") in printed


# --------------------------------------------------- where the words come from


def test_the_booklet_names_itself_once_and_the_steps_page_reads_it():
    """Typed on the auction-info page, printed again here.

    Asking for the platform and the auction a second time on this page would be
    asking twice for one fact, and the two answers would disagree.
    """
    nodes = [
        {"id": "a", "values": {}},
        {"id": "b", "values": {"auction_title": "مزاد أعيان حائل", "platform_name": "مباشر"}},
    ]
    facts = booklet_facts({}, nodes, project_name="ignored")
    assert facts["auction_title"] == "مزاد أعيان حائل"
    assert facts["platform_name"] == "مباشر"


def test_the_first_page_to_name_the_auction_wins():
    """The cover and the auction-info page both carry it, and can disagree
    while somebody is halfway through correcting one of them."""
    nodes = [
        {"id": "cover", "values": {"auction_title": "مزاد أعيان حائل"}},
        {"id": "info", "values": {"auction_title": "مزاد أعيان حائل القديم"}},
    ]
    assert booklet_facts({}, nodes)["auction_title"] == "مزاد أعيان حائل"


def test_an_unnamed_auction_falls_back_to_the_project_it_belongs_to():
    """«إختيار مزاد (  )» is worse on paper than a working title."""
    facts = booklet_facts({}, [{"id": "a", "values": {}}], project_name="مزاد سبتمبر")
    assert facts["auction_title"] == "مزاد سبتمبر"
