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

import itertools
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


def _source_for(pages: int, name: str = "") -> Path | None:
    """The export a map describes: named, then confirmed by page count.

    Two of the three exports have sixteen pages now, so counting alone matched
    whichever sorted first and checked a map against the wrong booklet.
    """
    from tests.conftest import _plain

    wanted = _plain(name)
    for root in (BACKEND.parent / "references", BACKEND.parent):
        for candidate in sorted(root.glob("*.pdf")):
            if wanted and wanted not in _plain(candidate.stem):
                continue
            try:
                with fitz.open(candidate) as doc:
                    if doc.page_count == pages:
                        return candidate
            except Exception:
                continue
    return None


def _any_named(name: str) -> Path | None:
    """An export by name alone, for one a map grafts but does not size."""
    from tests.conftest import _plain

    wanted = _plain(name)
    for root in (BACKEND.parent / "references", BACKEND.parent):
        for candidate in sorted(root.glob("*.pdf")):
            if wanted and wanted in _plain(candidate.stem):
                return candidate
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
        source = _source_for(source_map.source_pages, source_map.source)
        if source is None:
            continue
        # A map that grafts pages is checked against every export it draws on:
        # the grafted page's markers belong to the file it actually comes from.
        extra = {}
        for name in source_map.extra_sources:
            path = _source_for(0, name) or _any_named(name)
            if path is None:
                pytest.skip(f"export {name!r} not available")
            extra[name] = fitz.open(path)
        try:
            with fitz.open(source) as doc:
                assert_map(doc, source_map, extra)
        finally:
            for book in extra.values():
                book.close()
        checked += 1
    if not checked:
        pytest.skip("designer's exports not available")


def test_a_shifted_map_is_rejected():
    """assert_map is the tripwire for a re-export that renumbers its pages."""
    source_map = MAPS[0]
    source = _source_for(source_map.source_pages, source_map.source)
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


def test_the_closing_chip_follows_electronic_bidding():
    """Whoever can bid online is told when bidding closes.

    The hybrid export carries both halves of the property page: one drawn with
    «تغلق المزايدة على العقار» and its time and date, one drawn without. The
    electronic booklet takes the first. So does the hybrid booklet, and that is
    the point of the pair — a hybrid auction accepts online bids, so a bidder
    reading it needs the closing time exactly as an electronic bidder does.

    This reverses the earlier reading, which gave hybrid the half without the
    chip on the grounds that its bidding closes live in the hall. That is true
    of the hall; it is not true of the platform the same auction is also run on,
    and the booklet is read by both. Only the حضوري export, which never draws
    the chip at all, is without it.
    """
    electronic = BY_SLUG["auction_infath_electronic"].lot_layouts()
    hybrid = BY_SLUG["auction_infath_hybrid"].lot_layouts()
    inperson = BY_SLUG["auction_infath_inperson"].lot_layouts()

    assert all("تغلق المزايدة" in p.expect for p in electronic.values())
    assert all("تغلق المزايدة" in p.expect for p in hybrid.values())
    assert all("تغلق المزايدة" in p.forbid for p in inperson.values())

    # The two that share a source share its pages; the حضوري export is its own.
    assert electronic["standard"].index == hybrid["standard"].index
    assert electronic["tower"].index == hybrid["tower"].index


def test_nothing_is_borrowed_now_that_the_electronic_export_exists():
    """The three pages that were the hybrid's are cut from their own file.

    ``needs_artwork`` was on معلومات المزاد and شروط الدخول while the electronic
    booklet had no export of its own; معلومات التواصل was the hybrid's without
    even being flagged. All three now come from the electronic export, so no
    page of any map is borrowed, and the flag is free to mean what it says the
    next time a variant is short of artwork.
    """
    for source_map in MAPS:
        borrowed = [p for p in source_map.pages if p.needs_artwork]
        assert not borrowed, (
            f"{source_map.slug} still borrows "
            f"{[p.role.value for p in borrowed]}"
        )


def test_the_electronic_pages_come_from_the_electronic_export():
    """And the rest of it still comes from the hybrid: it has no برج layout."""
    electronic = BY_SLUG["auction_infath_electronic"]
    grafted = {p.role for p in electronic.pages if p.source}
    assert grafted == {PageRole.AUCTION_INFO, PageRole.TERMS, PageRole.CONTACT}
    assert electronic.extra_sources == ("مزاد الكتروني",)
    # Every grafted page states where that export prints the agent's lockup;
    # nothing else finds it, so a page without one would print يازي's mark.
    for page in electronic.pages:
        if page.source:
            assert page.agent_mark, f"{page.role.value} states no agent mark"


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


def test_every_table_is_ruled_by_the_field_not_the_artwork(built):
    """Every colourway of both tables carries its own ruling, and none wears it.

    A table that shrinks has to be drawn, not painted over: the guide's page is
    coloured, so a white patch over the surplus rows would be a patch. The build
    lifts the rules, the column dividers and the numbered tab off the artwork
    and hands them to the field, which redraws as many as the auction needs.

    Both halves are checked here because either alone is a booklet that prints
    wrong. Captured but not erased, the redraw lands on top of the original and
    every line comes out a third too dark; erased but not captured, the page
    loses its table altogether.
    """
    pages = {p["page_index"]: p for p in built["pages"]}
    tables = [
        f
        for f in built["fields"]
        if f.get("table")
        and pages.get(f["page_index"], {}).get("role") in ("lot_table", "rent_table")
    ]
    assert tables, "the booklet has a table page in at least one colour"
    # Both tables, in both colours: four blocks, none of them borrowing
    # another's geometry. «بيان عقود الإيجار» is nine columns wider than «بيان
    # العقارات» and nineteen rows deep to its ten, so a frame copied from one to
    # the other would rule the wrong page in the wrong places.
    seen = {
        (pages[f["page_index"]]["role"], pages[f["page_index"]]["layout"])
        for f in tables
    }
    assert len(seen) == len(tables), f"a colourway is described twice: {seen}"

    with fitz.open(built["_dir"] / "background.pdf") as doc:
        for field in tables:
            frame = field["table"]["frame"]
            assert frame, f"{field['key']} must carry the ruling it was drawn with"
            rules = frame["rules"]
            assert len(rules) == field["table"]["rows"], (
                "one rule closes each row the block can hold"
            )
            bottom = frame["bottom"]
            assert bottom >= rules[-1], "the block ends at or below its last row"
            if pages[field["page_index"]]["role"] == "rent_table":
                # The lease artwork rules twenty bands and numbers nineteen, so
                # its drawn bottom edge is a whole band below the last row a
                # client can fill. That band is not redrawn -- it is an empty
                # row, which is the thing this work exists to remove.
                pitch = field["table"]["row_pitch"]
                assert bottom - rules[-1] == pytest.approx(pitch, rel=0.1), (
                    "the lease block's bottom edge is one unnumbered band below "
                    "its last row"
                )
            assert rules == sorted(rules), "the rules are held in row order"
            # Held as measured, not as a pitch: the designer's steps are not all
            # the same, and a block rebuilt from an average rules the wrong
            # places.
            steps = {round(b - a, 4) for a, b in itertools.pairwise(rules)}
            assert len(steps) > 1, (
                "the measured rules are not evenly spaced; storing them "
                "individually is the point"
            )

            page = doc[field["page_index"]]
            height = page.rect.height
            top, bottom = rules[0] * height, frame["bottom"] * height
            left = min(
                v for path in frame["paths"] for item in path["items"]
                for v in item["points"][::2]
            ) * page.rect.width
            surviving = [
                fitz.Rect(d["rect"])
                for d in page.get_drawings()
                if fitz.Rect(d["rect"]).y0 >= top - 1
                and fitz.Rect(d["rect"]).y1 <= bottom + 20
                and fitz.Rect(d["rect"]).x1 >= left - 1
            ]
            assert not surviving, (
                f"page {field['page_index']} still has its table ruled into the "
                f"artwork: {[tuple(round(v, 2) for v in r) for r in surviving]}"
            )

            # The header bar carries the column titles as outlines and is not
            # part of what shrinks, so it must still be there.
            header = [
                d
                for d in page.get_drawings()
                if fitz.Rect(d["rect"]).y1 <= top
                and fitz.Rect(d["rect"]).y1 > top - 3 * height * field["table"]["row_pitch"]
                and fitz.Rect(d["rect"]).width > 300
            ]
            assert header, (
                f"page {field['page_index']} lost the bar above its table"
            )

    roles = {pages[f["page_index"]]["role"] for f in tables}
    assert roles == {"lot_table", "rent_table"}, (
        f"both tables shrink to their rows, not just one: {roles}"
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


# ------------------------------------------- the grafted electronic pages

#: Everything on the electronic export that belongs to شركة يازي's real sale
#: rather than to the template. None of it may survive into the built artwork.
YAZI_SALE = [
    "يازي",             # the selling agent, in Arabic
    "Yazi",             # and in Latin, as the lockup sets it
    "أصالة حفر الباطن",  # the auction's name
    "حفر الباطن",
    "الخفجي",           # the city its lots are in
    "منصة مباشر",       # the platform it was held on
    "0553157070",       # the agent's telephone number
    "732505003750",     # one of its deed numbers
]

#: Copy on those same pages that is the design and must be left alone.
ELECTRONIC_DESIGN = {
    PageRole.TERMS: ["التسجيل في منصة المزاد الإلكتروني", "مركز الإسناد"],
    PageRole.CONTACT: ["يقام المزاد إلكترونيا", "للتواصل والاستفسار"],
}


def _electronic_pages(manifest: dict, role: PageRole) -> list[int]:
    return [p["page_index"] for p in manifest["pages"] if p["role"] == role.value]


@pytest.fixture(scope="module")
def electronic() -> dict:
    directory = BUILT / "auction_infath_electronic"
    if not (directory / "template.json").exists():
        pytest.skip("electronic template not built")
    manifest = json.loads((directory / "template.json").read_text(encoding="utf-8"))
    manifest["_dir"] = directory
    return manifest


def test_no_yazi_branding_or_sample_sale_survives(electronic):
    """The electronic pages are cut from a finished auction, not a template.

    Its artwork is the design we want; everything printed on it belongs to
    somebody else's sale, including the selling agent's own lockup — which no
    automatic sweep finds, so the map states where it is and the build clears
    the stated region. A booklet carrying one client's mark onto another
    client's pages is the failure this guards.
    """
    offenders: list[str] = []
    with fitz.open(electronic["_dir"] / "background.pdf") as doc:
        for index, page in enumerate(doc):
            text = fold(normalise(page.get_text()))
            for phrase in YAZI_SALE:
                if fold(normalise(phrase)) in text:
                    offenders.append(f"page {index}: {phrase!r}")
    assert not offenders, "the real sale survived into the artwork: " + "; ".join(
        offenders
    )


def test_the_grafted_pages_keep_their_own_design(electronic):
    """Clearing harder is not the answer: the legal copy is the deliverable.

    شروط الدخول is fixed wording that differs per auction type, carries no
    field, and is the reason the electronic export was wanted at all. If a
    future widening of the bake removes it, the page comes out blank and the
    booklet loses its terms.
    """
    with fitz.open(electronic["_dir"] / "background.pdf") as doc:
        for role, phrases in ELECTRONIC_DESIGN.items():
            for index in _electronic_pages(electronic, role):
                text = fold(normalise(doc[index].get_text()))
                for phrase in phrases:
                    assert fold(normalise(phrase)) in text, (
                        f"{role.value} page {index} lost its own copy: {phrase!r}"
                    )


def test_the_electronic_variant_names_a_platform_and_no_venue(electronic):
    """An electronic auction is held nowhere, so it has no location to print."""
    keys = {
        (f["page_index"], f["key"])
        for f in electronic["fields"]
    }
    for role in (PageRole.AUCTION_INFO, PageRole.CONTACT):
        for index in _electronic_pages(electronic, role):
            on_page = {key for page, key in keys if page == index}
            assert "location" not in on_page, f"{role.value} still asks for a venue"
            assert "platform_name" in on_page, f"{role.value} names no platform"

    # And no code leading to a hall that does not exist.
    for index in _electronic_pages(electronic, PageRole.CONTACT):
        on_page = {key for page, key in keys if page == index}
        assert not [k for k in on_page if "venue" in k], "a hall code survived"


def test_grafted_pages_carry_the_company_mark(electronic):
    """Where the agent's lockup was, the signed-in company's goes.

    Removing it is only half the job: the page would otherwise print no mark at
    all where the design has one.
    """
    grafted = [
        p["page_index"]
        for p in electronic["pages"]
        if p["role"] in (PageRole.AUCTION_INFO.value, PageRole.TERMS.value,
                         PageRole.CONTACT.value)
    ]
    logos = {
        f["page_index"] for f in electronic["fields"] if f["key"] == "company_logo"
    }
    missing = [i for i in grafted if i not in logos]
    assert not missing, f"no company mark on grafted pages {missing}"
