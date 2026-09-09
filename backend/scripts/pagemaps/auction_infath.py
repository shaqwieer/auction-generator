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
    هجين       hybrid export, WITH the chip too. A hybrid auction accepts online
               bids, so its bidders need the closing time exactly as an
               electronic bidder does. (This reverses an earlier reading, which
               gave hybrid the half without the chip on the grounds that bidding
               closes live in the hall. True of the hall, not of the platform
               the same auction also runs on.)

Pages 7 and 8 of the in-person export, and 7, 8, 10 and 12 of the hybrid, are
the designer's duplicate samples of layouts already claimed above. They carry no
role and are pruned.

A fourth export arrived later: a finished electronic auction, sixteen pages. It
is not a template -- its sample data is a real sale -- but three of its pages are
drawn for an electronic auction where the hybrid's are not, and those three are
grafted onto the electronic map (``graft``). It carries no برج layout and none of
the optional per-property pages, so everything else still comes from the hybrid
export. Its markers are the printed copy's, not the blank template's: «إسم
المنصة» and the other placeholder strings are filled in and no longer match.
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

# Markers for the electronic export. It is a finished auction, so its pages say
# what this sale is rather than what the field is for, and the headings a blank
# template would be recognised by are filled in or outlined. These three survive
# extraction — Illustrator stretches much of the body copy with tatweel, which
# ``normalise`` does not fold, so anything justified is unusable as a marker.
E_PLATFORM = "منصة"                              # an online auction names one
E_TERMS = "التسجيل في منصة المزاد الإلكتروني"    # first bullet of the copy
E_ONLINE = "يقام المزاد إلكترونيا"               # the contact page's own line

#: Where the electronic export draws شركة يازي's lockup, in 0..1 of the page.
#:
#: Stated rather than found. The lockup is not a candidate either brand sweep
#: returns — not a raster the image pass sees, not a shape the vector pass
#: offers — so «whichever silhouette recurs» has nothing to weigh, on this
#: export or on the two or three pages grafted out of it.
#:
#: Measured across the three grafted pages, the footer mark occupies
#: x 15.7–102.0, y 782.0–818.2 of a 595.28×841.89 page. The band below is that
#: with room for the few points it shifts between pages, and stops at 0.22 of
#: the width — Infath's own mark begins at 0.877 on the same footer and must not
#: be touched. The build erases the ink it finds inside the band, never the band.
E_FOOTER_MARK = (0.0, 0.91, 0.22, 0.99)

#: معلومات التواصل prints the agent a second time, large, at the top — which is
#: where the guide puts شعار وكيل البيع, so the company's own mark belongs there
#: too. Measured at x 202.5–405.9, y 147.5–234.0; the band is that with margin,
#: and nothing else is drawn in the upper third of the page.
E_CONTACT_MARK = (0.30, 0.15, 0.72, 0.30)

#: Recorded on a page a variant borrows from another variant's artwork.
#: Nothing carries it now: the electronic booklet's own export arrived and
#: supplies all three of the pages that used to be the hybrid's. Kept because
#: the next variant to be short of artwork will need it again.
BORROWED = "الهجين — بانتظار كتيب إلكتروني"

#: Which export each map is cut from — a distinctive part of the filename, not
#: the whole of it: the names carry stray bidi marks and bytes that do not
#: survive a filesystem round trip, and two of the three exports now have
#: sixteen pages, so a page count no longer identifies one.
IN_PERSON_EXPORT = "كتيب-حضوري"
HYBRID_EXPORT = "الهجين"
ELECTRONIC_EXPORT = "مزاد الكتروني"


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
        source=IN_PERSON_EXPORT,
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
            SourcePage(15, R.CONTACT, "معلومات التواصل",
                       rules="contact_inperson",
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
    graft: tuple[SourcePage, ...] = (),
) -> SourceMap:
    """The electronic and hybrid templates: one export, different lot halves.

    ``graft`` replaces a page of the same role with one cut from another export.
    The electronic booklet's own file arrived as a finished auction: it carries
    its معلومات المزاد, شروط الدخول and معلومات التواصل — all three drawn for an
    electronic auction rather than a hybrid one — but only the قياسي lot layout
    and none of three optional pages. So the pages it has are taken from it and
    the rest still come from the hybrid export, which is what «wherever the
    correct artwork exists» amounts to in practice.
    """
    lot_expect = (CHIP,) if chip else ()
    lot_forbid = () if chip else (CHIP,)
    grafted = {p.role: p for p in graft}

    def own(page: SourcePage) -> SourcePage:
        """This map's page, unless another export supplies that role."""
        return grafted.get(page.role, page)

    return SourceMap(
        slug=slug,
        name=name,
        variant=variant,
        source_pages=21,
        source=HYBRID_EXPORT,
        covers=cover_designs(),
        pages=(
            SourcePage(0, R.COVER, "الغلاف", slot="cover", rules="cover",
                       forbid=(EXECUTION,)),
            SourcePage(1, R.INTRO, "تعريف بإنفاذ", expect=(INFATH,)),
            SourcePage(2, R.INTRO, "تعريف وكيل البيع", rules="intro_agent",
                       expect=(AGENT,), forbid=(LOCATION,)),
            own(SourcePage(3, R.AUCTION_INFO, "معلومات المزاد",
                           rules="auction_info",
                           expect=(LOCATION, PLATFORM), needs_artwork=borrowed)),
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
            own(SourcePage(18, R.TERMS, "شروط الدخول بالمزاد",
                           needs_artwork=borrowed)),
            SourcePage(19, R.STEPS, "خطوات المشاركة في المزاد الإلكتروني",
                       rules="steps", expect=(STEPS,)),
            own(SourcePage(20, R.CONTACT, "معلومات التواصل", rules="contact",
                           expect=(CONTACT, PLATFORM))),
        ),
    )


#: The three templates, in the order the catalogue should list them.
MAPS: tuple[SourceMap, ...] = (
    _in_person(),
    # Three pages now come from the electronic booklet's own export. It is a
    # finished auction rather than a blank template, so its markers are the
    # printed copy's — «مركز الإسناد» in the legal text, «للتواصل والاستفسار»
    # on the contact page — and «الموقع» is forbidden on both pages that would
    # name a venue, which is the whole point of the variant.
    _from_hybrid(
        slug="auction_infath_electronic",
        name="كتيّب المزاد — إلكتروني",
        variant="electronic",
        standard=9,
        tower=11,
        chip=True,
        borrowed=BORROWED,
        # Three pages come from the electronic export, which is a finished sale
        # rather than a blank template. Each states where its agent's lockup is,
        # because no automatic test can find it; the build erases the ink inside
        # that region and puts the signed-in company's mark there like anywhere
        # else. The pages keep their own palette and type — this export is a
        # later revision of the design, and recolouring it to match the hybrid
        # would invent a page the designer never drew.
        graft=(
            SourcePage(3, R.AUCTION_INFO, "معلومات المزاد",
                       rules="auction_info_electronic",
                       source=ELECTRONIC_EXPORT, agent_mark=(E_FOOTER_MARK,),
                       expect=(E_PLATFORM,), forbid=(LOCATION,)),
            SourcePage(13, R.TERMS, "شروط الدخول بالمزاد",
                       source=ELECTRONIC_EXPORT, agent_mark=(E_FOOTER_MARK,),
                       expect=(E_TERMS,)),
            # Its own layout, not the hybrid's. The page reads as four runs but
            # is three facts: the days on the right, the platform in the middle,
            # and the hours on the left set as two lines. That is the guide's
            # electronic card — التاريخ، اسم المنصة، الوقت — and no venue.
            SourcePage(15, R.CONTACT, "معلومات التواصل",
                       rules="contact_electronic",
                       source=ELECTRONIC_EXPORT, agent_mark=(E_FOOTER_MARK, E_CONTACT_MARK),
                       expect=(CONTACT, E_ONLINE), forbid=(LOCATION,)),
        ),
    ),
    # A hybrid auction accepts electronic bids, so its property pages carry the
    # closing strip — «تغلق المزايدة على العقار» with its time and date — the
    # same half of the export the electronic booklet takes. It was built from
    # the other half, which is the حضوري drawing of the page and says nothing
    # about when bidding closes; on a booklet whose whole point is that bidding
    # is open online, that is the one fact a bidder needs. The two halves differ
    # by exactly ``closing_time`` and ``closing_date`` and nothing else.
    _from_hybrid(
        slug="auction_infath_hybrid",
        name="كتيّب المزاد — هجين",
        variant="hybrid",
        standard=9,
        tower=11,
        chip=True,
    ),
)

BY_SLUG = {m.slug: m for m in MAPS}
