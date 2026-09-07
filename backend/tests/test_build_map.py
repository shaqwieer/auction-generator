"""The page map, and what the build script makes of it.

The test that matters most here is
:func:`test_background_carries_no_sample_data`. Baking clears only the regions a
confirmed field will draw over, so a page the build keeps but does not describe
keeps the designer's sample content printed into the background -- which is how
every booklet came to carry the selling agent's phone number, the sample auction
dates and a nineteen-row property table belonging to somebody else.

Its counterweight is :func:`test_printed_headings_survive_baking`: clearing
harder is not the answer, because the printed labels beside those values are
design. Both must pass at once.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

import fitz
import pytest

from app.rendering.autokey import normalise
from app.rendering.pagemap import MapError, PageRole, assert_map
from scripts.pagemaps.auction_infath import BY_SLUG, MAPS

BACKEND = Path(__file__).resolve().parent.parent
BUILT = BACKEND / "var" / "templates"

#: Values that belong to the designer's sample auction, not to any client.
SAMPLE_DATA = [
    "1,000.000.00",     # the sample lease amounts
    "0555405658",       # the selling agent's phone number
    "542104012563",     # a sample deed number
    "www.aayan.sa",
    "@aayan_re",
    "أعيان حائل",       # the sample auction's name
    "يوليو",            # the sample auction's month
    "منصة مباشر",       # the sample platform
    "الموقع",           # the venue placeholder on the chips
    "إسم المنصة",
]

#: Printed labels that are design. Redacting these leaves values floating beside
#: empty cells, which is worse than leaving a sample value in place.
PRINTED_LABELS = [
    "رقم طلب التنفيذ",
    "رقم الصك",
    "شيك الدخول",
    "الحدود",
    "الأطوال",
    # NOT «ملاحظات»: the only place it is printed is inside the معلومات إضافية
    # box, where the guide has the client write their own section titles.
    "معلومات اضافية",
    "وصف العقار",
    "بيان العقارات",
    "للتواصل والاستفسار",
    "مركز الإسناد",
    "الرفع المساحي",
    "معلومات الإيجار",
    "صور إضافية",
    "أضغط هنا للوصول للرابط",
]


def _source_for(pages: int) -> Path | None:
    for root in (BACKEND.parent / "references", BACKEND.parent):
        for candidate in sorted(root.glob("*.pdf")):
            try:
                with fitz.open(candidate) as doc:
                    if doc.page_count == pages:
                        return candidate
            except Exception:
                continue
    return None


@pytest.fixture(scope="module", params=[m.slug for m in MAPS])
def built(request) -> dict:
    directory = BUILT / request.param
    if not (directory / "template.json").exists():
        pytest.skip(
            f"{request.param} not built; run scripts/build_infath_templates.py"
        )
    manifest = json.loads((directory / "template.json").read_text(encoding="utf-8"))
    manifest["_dir"] = directory
    return manifest


def fold(text: str) -> str:
    folded = unicodedata.normalize("NFKC", text)
    return "".join(c for c in folded if not unicodedata.combining(c))


# ------------------------------------------------------------------- the map


def test_pagemap_markers_match_the_export():
    """Every map is checked against the file it claims to describe.

    A wrong cut is silently wrong: the electronic booklet would carry the
    in-person lot pages and nothing downstream would notice.
    """
    checked = 0
    for source_map in MAPS:
        source = _source_for(source_map.source_pages)
        if source is None:
            continue
        with fitz.open(source) as doc:
            assert_map(doc, source_map)
        checked += 1
    if not checked:
        pytest.skip("designer's exports not available")


def test_a_shifted_map_is_rejected():
    """assert_map is the tripwire for a re-export that renumbers its pages."""
    source_map = MAPS[0]
    source = _source_for(source_map.source_pages)
    if source is None:
        pytest.skip("designer's exports not available")
    with fitz.open(source) as doc:
        doc.select(list(range(1, doc.page_count)))  # drop the cover
        with pytest.raises(MapError):
            assert_map(doc, source_map)


def test_each_variant_offers_both_lot_layouts():
    for source_map in MAPS:
        layouts = source_map.lot_layouts()
        assert set(layouts) == {"standard", "tower"}, source_map.slug


def test_the_electronic_cut_is_the_one_with_the_closing_chip():
    """The three variants must not collapse into each other.

    The hybrid export carries both halves. Electronic takes the lot pages that
    print a closing time; hybrid takes the ones that do not, because its bidding
    closes live in the hall.
    """
    electronic = BY_SLUG["auction_infath_electronic"].lot_layouts()
    hybrid = BY_SLUG["auction_infath_hybrid"].lot_layouts()
    assert electronic["standard"].index != hybrid["standard"].index
    assert electronic["tower"].index != hybrid["tower"].index
    assert all("تغلق المزايدة" in p.expect for p in electronic.values())
    assert all("تغلق المزايدة" in p.forbid for p in hybrid.values())


def test_borrowed_pages_are_recorded_not_hidden():
    """The two pages the electronic booklet has no artwork for are flagged."""
    borrowed = [
        p for p in BY_SLUG["auction_infath_electronic"].pages if p.needs_artwork
    ]
    assert {p.role for p in borrowed} == {PageRole.AUCTION_INFO, PageRole.TERMS}
    assert not [p for p in BY_SLUG["auction_infath_hybrid"].pages if p.needs_artwork]


# ----------------------------------------------------------------- the build


def test_background_carries_no_sample_data(built):
    """No page may print the designer's sample auction.

    The intro page is the one exception the brand guide names: تعريف بإنفاذ is
    Infath's own boilerplate, fixed, and its call-centre number belongs there.
    """
    roles = {p["page_index"]: p["role"] for p in built["pages"]}
    offenders: list[str] = []
    with fitz.open(built["_dir"] / "background.pdf") as doc:
        for index, page in enumerate(doc):
            if roles.get(index) == PageRole.INTRO.value:
                continue
            text = normalise(page.get_text())
            found = [s for s in SAMPLE_DATA if normalise(s) in text]
            if found:
                offenders.append(f"page {index} ({roles.get(index)}): {found}")
    assert not offenders, "sample data survived the bake:\n" + "\n".join(offenders)


def test_no_stray_numbers_survive_on_a_lot_page(built):
    """A lot page's every value is somebody's data.

    The الأطوال cell is why this exists: its label is one rotated white run
    reading الحدودالأطوال, so the vocabulary had nothing to pair the four
    measurements with and they printed on every booklet.
    """
    lot_pages = [
        p["page_index"] for p in built["pages"] if p["role"] == PageRole.LOT.value
    ]
    assert lot_pages, "every booklet has lot pages"
    with fitz.open(built["_dir"] / "background.pdf") as doc:
        for index in lot_pages:
            text = fold(doc[index].get_text())
            numbers = re.findall(r"\d[\d,.٫]{2,}", text)
            assert not numbers, f"page {index} still prints {numbers}"


def test_printed_headings_survive_baking(built):
    """Clearing harder is not the answer; the labels are design."""
    with fitz.open(built["_dir"] / "background.pdf") as doc:
        printed = normalise(" ".join(page.get_text() for page in doc))
    missing = [label for label in PRINTED_LABELS if normalise(label) not in printed]
    assert not missing, f"baking removed printed labels: {missing}"


def test_every_content_page_has_fields(built):
    """A page with no field is a page the bake could not clear.

    ``terms`` and ``steps`` are the deliberate exceptions -- fixed copy in the
    first case, and in the second the five captions are split out by rule while
    the heading stays put.
    """
    by_page: dict[int, int] = {}
    for field in built["fields"]:
        by_page[field["page_index"]] = by_page.get(field["page_index"], 0) + 1
    silent = {PageRole.INTRO.value, PageRole.TERMS.value}
    for page in built["pages"]:
        if page["role"] in silent or page["options"].get("own_artwork"):
            continue
        assert by_page.get(page["page_index"]), (
            f"{built['slug']} page {page['page_index']} ({page['role']}) "
            f"has no fields, so nothing on it can be cleared or filled"
        )


def test_cover_slot_offers_exactly_the_six_designs(built):
    """Six covers, and no way to make a seventh.

    A booklet wears one of the designs the brand guide draws or it is off-brand,
    so there is no blank carrier to upload onto. The export's own cover page
    stays in the slot -- it is where the cover belongs in the booklet -- but it
    is غلاف 1 drawn a second time and is flagged so it is not offered.
    """
    covers = [p for p in built["pages"] if p["slot"] == "cover"]
    offered = [c for c in covers if not c["options"].get("source_cover")]
    assert [c["name"] for c in offered] == [f"غلاف {n}" for n in range(1, 7)]
    assert sum(1 for c in covers if c["options"].get("source_cover")) == 1
    assert not any(c["options"].get("own_artwork") for c in covers)
    assert not any(f["key"] == "cover_image" for f in built["fields"])


def test_every_cover_prints_the_date_caption(built):
    """«تاريخ المزاد» above the date, on all six.

    Two of the covers were exported without the caption and four had it set as
    the first line of the same white run as the date -- so a field taking that
    run whole redacted a printed caption off the artwork. Both are fixed here,
    and the fix is only worth anything if it holds on every cover.
    """
    with fitz.open(BUILT / built["slug"] / "background.pdf") as doc:
        for page in built["pages"]:
            if page["slot"] != "cover":
                continue
            lines = doc[page["page_index"]].get_text().splitlines()
            printed = {normalise(line) for line in lines}
            assert normalise("تاريخ المزاد") in printed, (
                f"{built['slug']} {page['name']} prints no date caption"
            )


def test_the_summary_page_is_offered_in_both_colourways(built):
    """Teal and navy, one ten-row table each.

    The guide's blank specimen numbers both blocks 01-08 and its instruction for
    a long list is to repeat the page, so the two blocks are colours of one
    table -- not twenty rows in two halves, which is what the booklet used to
    print.
    """
    tables = [p for p in built["pages"] if p["role"] == PageRole.LOT_TABLE.value]
    assert {p["layout"] for p in tables} == {"green", "blue"}
    assert {p["slot"] for p in tables} == {"lot_table"}
    for page in tables:
        blocks = [
            f for f in built["fields"]
            if f["page_index"] == page["page_index"] and f["type"] == "table"
        ]
        assert len(blocks) == 1, f"{page['name']} draws {len(blocks)} blocks"
        assert blocks[0]["table"]["rows"] == 10
        assert blocks[0]["table"]["row_offset"] == 0


def test_the_navy_summary_page_is_not_a_blank_page(built):
    """The colourway is the designer's own block, placed -- not a white gap."""
    navy = next(
        p for p in built["pages"]
        if p["role"] == PageRole.LOT_TABLE.value and p["layout"] == "blue"
    )
    with fitz.open(BUILT / built["slug"] / "background.pdf") as doc:
        page = doc[navy["page_index"]]
        drawn = [
            fitz.Rect(d["rect"]) for d in page.get_drawings()
            if fitz.Rect(d["rect"]).y0 > page.rect.height * 0.2
            and fitz.Rect(d["rect"]).y1 < page.rect.height * 0.75
        ]
        assert len(drawn) > 4, "the navy block did not land on the page"


def test_lot_layouts_are_reachable_from_the_manifest(built):
    layouts = {
        p["layout"] for p in built["pages"] if p["role"] == PageRole.LOT.value
    }
    assert layouts == {"standard", "tower"}


def test_optional_pages_are_offered_per_lot(built):
    """The five per-property pages the guide adds حسب الحاجة, all default off."""
    optional = [p for p in built["pages"] if p["is_optional"]]
    assert {p["role"] for p in optional} == {
        PageRole.LOT_FEATURES.value,
        PageRole.EXTRA_INFO.value,
        PageRole.BOUNDARIES.value,
        PageRole.EXTRA_PHOTOS.value,
        PageRole.RENT_TABLE.value,
    }
    assert not any(p["default_on"] for p in optional)


def test_the_outlined_sample_copy_is_cleared(built):
    """مميزات العقار has its lease copy converted to outlines.

    Redaction keeps line art, so the phrases survived the bake and the page was
    withheld from the builder rather than ship somebody else's figures. Line art
    *can* be removed in a region taken from the art itself -- which is how the
    agent's lockup and the sample codes came off -- so the page is cleared and
    offered instead, with its own field over the space.
    """
    features = [
        p for p in built["pages"] if p["role"] == PageRole.LOT_FEATURES.value
    ]
    assert features, "every variant carries the features page"
    for page in features:
        assert not page["options"].get("needs_artwork"), page["name"]
        assert any(
            f["key"] == "lot_features" and f["page_index"] == page["page_index"]
            for f in built["fields"]
        ), "the cleared space has to be fillable"

    with fitz.open(BUILT / built["slug"] / "background.pdf") as doc:
        for page in features:
            printed = {
                normalise(line)
                for line in doc[page["page_index"]].get_text().splitlines()
            }
            for sample in ("تم تأجير العقار", "الخمس السنوات الإيجارية"):
                assert not any(normalise(sample) in line for line in printed), (
                    f"{page['name']} still prints the designer's lease sample"
                )
            drawn = doc[page["page_index"]].get_pixmap(
                dpi=72,
                clip=fitz.Rect(40, 550, 555, 730),
            )
            depth = drawn.n
            shades = {
                bytes(drawn.samples[i : i + depth])
                for i in range(0, len(drawn.samples), depth)
            }
            assert len(shades) == 1, "the space should be empty, not outlined"


def test_source_is_kept_and_page_aligned(built):
    """Publishing re-bakes the original, so it has to still be there.

    And its pages have to line up with the fields, or a republish would bake
    the wrong regions.
    """
    source = built["_dir"] / "source.pdf"
    assert source.exists(), "publish and the suggestion overlay both read this"
    with fitz.open(source) as doc:
        assert doc.page_count == built["page_count"]


def test_background_bytes_stay_within_budget(built):
    """Two of the six covers are 11MB photographs.

    They only shrink if the cover rule creates the image field that lets the
    bake strip them; forget it and the background grows by 22MB.
    """
    assert built["bake"]["background_bytes"] < 20_000_000, (
        f"{built['slug']} background is "
        f"{built['bake']['background_bytes'] / 1e6:.1f}MB"
    )


def test_every_field_the_client_is_asked_for_has_a_name(built):
    """No «unnamed_6_3» ever reaches the form.

    Most values are named from the label printed beside them. Two blocks cannot
    be: the برج page outlines its الحدود captions and both lot pages outline
    «الأطوال», so there is no text to read. Those are named by declaration —
    see SWEEP_NAMES — and this is the net under that.
    """
    anonymous = [f["key"] for f in built["fields"] if f["key"].startswith("unnamed")]
    assert not anonymous, f"{built['slug']}: {anonymous} would print as-is"
    assert all(f["label"] for f in built["fields"] if f["type"] == "text")


def test_the_declared_names_land_on_the_runs_they_describe(built):
    """The sweep names by position, so a shifted export could mis-assign them.

    Checked against the geometry, which is the only independent evidence there
    is: the four boundaries run down the page in the order the design lists
    them, and الأطوال sits below الحدود on both lot layouts.
    """
    pages = {p["page_index"]: p for p in built["pages"]}
    for page_index in [p["page_index"] for p in built["pages"] if p["role"] == "lot"]:
        on_page = {
            f["key"]: f for f in built["fields"] if f["page_index"] == page_index
        }
        sides = ["boundary_north", "boundary_south", "boundary_east", "boundary_west"]
        assert set(sides) <= set(on_page), (
            f"page {page_index} ({pages[page_index].get('layout')}) is missing a boundary"
        )
        tops = [on_page[key]["rect"]["y"] for key in sides]
        assert tops == sorted(tops), "the boundaries read top to bottom"

        lengths = [on_page[k] for k in ("lengths_1", "lengths_2") if k in on_page]
        assert len(lengths) == 2, f"page {page_index} should offer both length rows"
        assert lengths[0]["rect"]["y"] < lengths[1]["rect"]["y"]
        assert lengths[0]["rect"]["y"] > on_page["boundary_west"]["rect"]["y"], (
            "الأطوال is printed below الحدود on both layouts"
        )


def test_a_table_page_is_named_for_itself_not_for_its_colour(built):
    """Both colourways are the same page of the booklet.

    Naming them «بيان عقود الإيجار — أزرق» and «— أخضر» put two entries in the
    optional-pages list and read as a choice between two documents. The colour
    belongs to the page — it is carried in `layout` — and the picker is the one
    place it is the point.
    """
    for role in ("lot_table", "rent_table"):
        variants = [p for p in built["pages"] if p["role"] == role]
        if len(variants) < 2:
            continue
        assert len({p["name"] for p in variants}) == 1, (
            f"{role} is one page: {[p['name'] for p in variants]}"
        )
        assert {p["layout"] for p in variants} == {"green", "blue"}
        assert not any("أزرق" in p["name"] or "أخضر" in p["name"] for p in variants)


#: The boxes the guide writes as sections -- a bold title over its points.
#: All three are one box each, and every word inside one is the client's.
SECTION_BOXES = {"notes", "extra_info", "lot_features"}


def test_a_section_box_opens_empty(built):
    """Nothing of the designer's sample survives inside one.

    The property page's box took only the paragraph in it, which left «ملاحظات
    :» and the «-1» «-2» markers baked into the background — so every property
    opened with a heading already written in it that no field could remove. The
    field is the drawn box now, and the box is the client's to fill.
    """
    directory = built["_dir"]
    with fitz.open(directory / "background.pdf") as baked:
        for field in built["fields"]:
            if field["key"] not in SECTION_BOXES:
                continue
            page = baked[field["page_index"]]
            box = fitz.Rect(
                field["rect"]["x"] * page.rect.width,
                field["rect"]["y"] * page.rect.height,
                (field["rect"]["x"] + field["rect"]["w"]) * page.rect.width,
                (field["rect"]["y"] + field["rect"]["h"]) * page.rect.height,
            )
            printed = [
                line.strip()
                for line in page.get_text("text", clip=box).splitlines()
                if line.strip()
            ]
            assert not printed, (
                f"{built['slug']} page {field['page_index']} "
                f"({field['key']}) still prints {printed}"
            )


def test_a_section_box_is_the_drawn_box_not_the_words_in_it(built):
    """Sized from the rectangle the designer drew, so it can be filled.

    Taken from the sample paragraph instead, the field was two thirds the
    height and started below the heading — a client writing two sections had
    nowhere for the second to go.

    مميزات العقار is left out: the designer drew no rectangle there, and its
    extent is taken from the outlined sample that was lifted off the page.
    """
    with fitz.open(built["_dir"] / "source.pdf") as source:
        for field in built["fields"]:
            if field["key"] not in ("notes", "extra_info"):
                continue
            page = source[field["page_index"]]
            drawn = [
                fitz.Rect(d["rect"])
                for d in page.get_drawings()
                if fitz.Rect(d["rect"]).width > 80 and fitz.Rect(d["rect"]).height > 60
            ]
            box = fitz.Rect(
                field["rect"]["x"] * page.rect.width,
                field["rect"]["y"] * page.rect.height,
                (field["rect"]["x"] + field["rect"]["w"]) * page.rect.width,
                (field["rect"]["y"] + field["rect"]["h"]) * page.rect.height,
            )
            assert any(
                rect.contains(box) and box.get_area() > rect.get_area() * 0.75
                for rect in drawn
            ), (
                f"{built['slug']} page {field['page_index']} ({field['key']}): "
                f"{box} does not fill any box the designer drew"
            )
