"""The three Infath auction-booklet templates, cut from the designer's exports.

Roles were confirmed against renders of every page of both files, then checked
against text MuPDF can extract. Two discriminators survive extraction, and
between them they settle every decision that matters:

    "وصف العقار"      the قياسي heading. Present on a standard lot page,
                      outlined away on the برج/عمارة one, so its absence names
                      the layout.
    "تغلق المزايدة"   the closing-time chip. Present only on the electronic lot
                      pages, so its presence names the flavour.

Everything else -- the optional per-property pages -- carries no readable text
at all, so the marked pages bracket them instead. Do not add markers by guessing
from the guide: Illustrator outlines headings unpredictably, and the chip that
is visually on four hybrid pages extracts on only three of them.

The hybrid export is literally "حضوري و الكتروني معا": source pages 5-8 are the
in-person half and 9-12 the electronic half, and both halves carry the same two
layouts. So:

    حضوري      in-person export, no closing chip
    إلكتروني   hybrid export, WITH the chip -- an online-only auction prints a
               hard closing time
    هجين       hybrid export, no chip -- bidding closes live in the hall

Pages 7 and 8 of the in-person export, and 7, 8, 10 and 12 of the hybrid, are
the designer's duplicate samples of layouts already claimed above. They carry no
role and are pruned.
"""

from __future__ import annotations

from pathlib import Path

from app.rendering.pagemap import PageRole as R
from app.rendering.pagemap import SourceMap, SourcePage

PROJECT = Path(__file__).resolve().parents[3]

# Markers, spelled once.
INFATH = "مركز الإسناد"
AGENT = "شركة أعيان"
LOCATION = "الموقع"
PLATFORM = "إسم المنصة"        # only the electronic and hybrid wordings carry it
LOTS_TABLE = "بيان العقارات"
EXECUTION = "رقم طلب التنفيذ"  # on every lot page and nowhere else
STANDARD = "وصف العقار"        # the قياسي heading; outlined on the برج page
CHIP = "تغلق المزايدة"         # the electronic closing-time chip
CONTACT = "للتواصل والاستفسار"
STEPS = "خطوات المشاركة"

#: Recorded on the two pages the electronic booklet borrows from the hybrid,
#: so swapping them is a one-line edit once its own export arrives.
BORROWED = "الهجين — بانتظار كتيب إلكتروني"


def cover_designs() -> tuple[Path, ...]:
    """The six alternative covers from the brand guide, if they are on disk.

    Found by shape rather than by name: the folder is Arabic and does not
    survive every filesystem round trip intact.
    """
    for directory in sorted((PROJECT / "references").glob("*")):
        ai = directory / "Ai"
        designs = sorted(ai.glob("*.ai")) if ai.is_dir() else []
        if len(designs) >= 6:
            return tuple(designs[:6])
    return ()


def _optional(index: int, role: R, name: str, rules: str) -> SourcePage:
    """One of the per-property pages the builder offers per lot.

    All five default off. The guide adds them حسب الحاجة, and a lot with no
    lease contracts should not carry an empty lease table.
    """
    return SourcePage(
        index=index,
        role=role,
        name=name,
        rules=rules,
        optional=True,
        default_on=False,
    )


def _in_person() -> SourceMap:
    return SourceMap(
        slug="auction_infath_inperson",
        name="كتيّب المزاد — حضوري",
        variant="inperson",
        source_pages=16,
        covers=cover_designs(),
        pages=(
            SourcePage(0, R.COVER, "الغلاف", slot="cover", rules="cover",
                       forbid=(EXECUTION,)),
            SourcePage(1, R.INTRO, "تعريف بإنفاذ", expect=(INFATH,)),
            SourcePage(2, R.INTRO, "تعريف وكيل البيع", rules="intro_agent",
                       expect=(AGENT,), forbid=(LOCATION,)),
            SourcePage(3, R.AUCTION_INFO, "معلومات المزاد", rules="auction_info",
                       expect=(LOCATION, AGENT), forbid=(PLATFORM,)),
            SourcePage(4, R.LOT_TABLE, "بيان العقارات", rules="lot_table",
                       expect=(LOTS_TABLE,)),
            SourcePage(5, R.LOT, "صفحة العقار — قياسي", layout="standard",
                       slot="lot", rules="lot_standard",
                       expect=(EXECUTION, STANDARD), forbid=(CHIP,)),
            SourcePage(6, R.LOT, "صفحة العقار — برج/عمارة", layout="tower",
                       slot="lot", rules="lot_tower",
                       expect=(EXECUTION,), forbid=(STANDARD, CHIP)),
            _optional(9, R.LOT_FEATURES, "مميزات العقار", "lot_features"),
            _optional(10, R.EXTRA_INFO, "معلومات إضافية", "extra_info"),
            _optional(11, R.BOUNDARIES, "الحدود والأطوال", "boundaries"),
            _optional(12, R.EXTRA_PHOTOS, "صور إضافية", "extra_photos"),
            _optional(13, R.RENT_TABLE, "بيان عقود الإيجار", "rent_table"),
            SourcePage(14, R.TERMS, "شروط الدخول بالمزاد", forbid=(PLATFORM,)),
            SourcePage(15, R.CONTACT, "معلومات التواصل", rules="contact",
                       expect=(CONTACT,), forbid=(PLATFORM,)),
        ),
    )


def _from_hybrid(
    *,
    slug: str,
    name: str,
    variant: str,
    standard: int,
    tower: int,
    chip: bool,
    borrowed: str = "",
) -> SourceMap:
    """The electronic and hybrid templates: one export, different lot halves."""
    lot_expect = (CHIP,) if chip else ()
    lot_forbid = () if chip else (CHIP,)
    return SourceMap(
        slug=slug,
        name=name,
        variant=variant,
        source_pages=21,
        covers=cover_designs(),
        pages=(
            SourcePage(0, R.COVER, "الغلاف", slot="cover", rules="cover",
                       forbid=(EXECUTION,)),
            SourcePage(1, R.INTRO, "تعريف بإنفاذ", expect=(INFATH,)),
            SourcePage(2, R.INTRO, "تعريف وكيل البيع", rules="intro_agent",
                       expect=(AGENT,), forbid=(LOCATION,)),
            SourcePage(3, R.AUCTION_INFO, "معلومات المزاد", rules="auction_info",
                       expect=(LOCATION, PLATFORM), needs_artwork=borrowed),
            SourcePage(4, R.LOT_TABLE, "بيان العقارات", rules="lot_table",
                       expect=(LOTS_TABLE,)),
            SourcePage(standard, R.LOT, "صفحة العقار — قياسي", layout="standard",
                       slot="lot", rules="lot_standard",
                       expect=(EXECUTION, STANDARD, *lot_expect),
                       forbid=lot_forbid),
            SourcePage(tower, R.LOT, "صفحة العقار — برج/عمارة", layout="tower",
                       slot="lot", rules="lot_tower",
                       expect=(EXECUTION, *lot_expect),
                       forbid=(STANDARD, *lot_forbid)),
            _optional(13, R.LOT_FEATURES, "مميزات العقار", "lot_features"),
            _optional(14, R.EXTRA_INFO, "معلومات إضافية", "extra_info"),
            _optional(15, R.BOUNDARIES, "الحدود والأطوال", "boundaries"),
            _optional(16, R.EXTRA_PHOTOS, "صور إضافية", "extra_photos"),
            _optional(17, R.RENT_TABLE, "بيان عقود الإيجار", "rent_table"),
            SourcePage(18, R.TERMS, "شروط الدخول بالمزاد", needs_artwork=borrowed),
            SourcePage(19, R.STEPS, "خطوات المشاركة في المزاد الإلكتروني",
                       rules="steps", expect=(STEPS,)),
            SourcePage(20, R.CONTACT, "معلومات التواصل", rules="contact",
                       expect=(CONTACT, PLATFORM)),
        ),
    )


#: The three templates, in the order the catalogue should list them.
MAPS: tuple[SourceMap, ...] = (
    _in_person(),
    _from_hybrid(
        slug="auction_infath_electronic",
        name="كتيّب المزاد — إلكتروني",
        variant="electronic",
        standard=9,
        tower=11,
        chip=True,
        borrowed=BORROWED,
    ),
    _from_hybrid(
        slug="auction_infath_hybrid",
        name="كتيّب المزاد — هجين",
        variant="hybrid",
        standard=5,
        tower=6,
        chip=False,
    ),
)

BY_SLUG = {m.slug: m for m in MAPS}
