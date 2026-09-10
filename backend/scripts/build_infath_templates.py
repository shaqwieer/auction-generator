"""Build the three Infath auction-booklet templates from the designer's exports.

    python scripts/build_infath_templates.py            # all three
    python scripts/build_infath_templates.py --slug auction_infath_hybrid

Replaces the first build script, which inferred the booklet's structure
from its page count and derived fields on two hardcoded pages. Everything else
it pruned -- and because baking only clears what a field will later draw over,
every page it pruned kept the designer's sample data printed into the
background: the agent's phone number, the sample auction dates, a nineteen-row
property table. Keeping a page and clearing a page are the same act.

Here the structure is declared instead (``scripts/pagemaps/auction_infath.py``),
and every page the map keeps gets a rule set that names what on it is data. The
rule sets are keyed by page *kind*, not page index, so one entry serves the
same layout wherever it appears and in whichever export.

Order of operations, and why:

    assert the map     a silently wrong cut is worse than a failed build
    select + reorder   page indices move once, here, and never again
    append the covers  six brand-guide designs plus a blank carrier
    derive             geometry from the artwork, never from the sample string
    rules + tables     what on each page is data
    save source.pdf    unbaked, so publish and suggestions keep working
    bake               clear exactly the regions a field will draw over
    save background    plus the manifest

Everything it produces is still a proposal; the template editor is where an
admin renames a key or adds a region the rules could not name.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
import unicodedata
from collections import Counter, defaultdict
from copy import deepcopy
from itertools import pairwise
from pathlib import Path
from typing import Any

import fitz

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.rendering.autokey import VALUE_COLORS, normalise, suggest
from app.rendering.bake import bake_document
from app.rendering.base import (
    ChipPart,
    FieldSpec,
    FieldType,
    FrameItem,
    FramePath,
    NormRect,
    SectionKind,
    TableColumn,
    TableFrame,
    TableSpec,
)
from app.rendering.compose import Section
from app.rendering.derive import DerivedField, derive_document, derive_page
from app.rendering.fonts import brand_registry
from app.rendering.pagemap import (
    PER_LOT_ROLES,
    MapError,
    PageRole,
    SourceMap,
    SourcePage,
    assert_map,
)
from app.rendering.shaping import Align, Fit, VAlign, calibrated_htmlbox
from app.rendering.tables import derive_tables, to_norm
from scripts.pagemaps.auction_infath import ELECTRONIC, IN_PERSON_EXPORT, MAPS

BACKEND = Path(__file__).resolve().parent.parent
REFERENCES = BACKEND.parent / "references"

# Body copy the designer set in the light navy. Free-text blocks, not labelled
# values, so they are named by position rather than by vocabulary.
BODY = "#001447"
# The teal the designer uses for the auction's own when/where chips.
CHIP = "#3ABDBA"
CHIP_ALT = "#159D9D"
# Headings set in the same navy as the body copy. They are design, not data, and
# must never be swept into a merged text field: doing so both deletes the
# heading and stretches the field box over neighbouring artwork.
STATIC_HEADINGS = {
    "ملاحظات",
    "وصف العقار",
    "معلومات اضافية",
    "معلومات إضافية",
    "الحدود",
    "الأطوال",
    "بيان العقارات",
    "بيان عقود الإيجار",
    "مميزات العقار",
    "للتواصل والاستفسار",
    "يقام المزاد",
    # The electronic export's wording of the same heading. It is true of every
    # electronic auction, so nobody edits it and it is not a field -- but it is
    # navy, the same navy as the telephone number below it, and left claimable
    # it was taken as the first run of that colour: the heading was cleared and
    # a phone number drawn where it had been.
    "يقام المزاد إلكترونيا",
    "خطوات المشاركة",
    "شروط الدخول بالمزاد",
    # The white captions on the lot pages' link chips. They read like values
    # because they are set in white on teal, and on the برج layout -- where the
    # lot badge is outlined and so invisible to derivation -- the first of them
    # was picked up as the lot number and redacted out of the design.
    "الرفع المساحي",
    "معلومات الإيجار",
    "صور إضافية",
    "أضغط هنا للوصول للرابط",
    "الحدود الأطوال",
    "الحدودالأطوال",
    # The closing-time chip's own caption, on the electronic lot pages. White on
    # teal like the values beside it, and cleared with them until now -- so the
    # chip printed a date and a time under no heading at all.
    "تغلق المزايدة",
    "على العقار",
}

# Required on a lot page: without them a booklet page is unusable rather than
# merely incomplete.
REQUIRED_LOT_KEYS = {"deed_number", "property_type"}


def _is_heading(f: DerivedField) -> bool:
    return normalise(f.sample_text) in STATIC_HEADINGS


def _colour_matches(colour: str, match: Any) -> bool:
    """Whether a run's colour is the one a rule is looking for.

    Usually one colour. A rule may name several, because a line the designer
    set as one thing is not always one colour in the file: the electronic
    export's auction name is #13375C on its first line and #1F2243 on its
    second. Matching one of them took half the title and left «أصالة حفر البا»
    printed on the page behind whatever the client typed.
    """
    if isinstance(match, tuple | list | set | frozenset):
        return colour in match
    return colour == match


# --------------------------------------------------------------- rule sets

# Each entry names what on a page is data. ``match`` is either "image", "box"
# (the largest empty container the designer drew) or a colour; the remaining
# keys pick which run and how it behaves.
RULES: dict[str, list[dict[str, Any]]] = {
    "cover": [
        # Required: a cover design built around a photograph is broken without
        # one. The flat covers carry no image at all, so they carry no field
        # either and a booklet using one is unaffected.
        {"key": "cover_photo", "label": "صورة الغلاف", "match": "image",
         "required": True},
        # The booklet is named once and printed wherever the design names it.
        # The cover and معلومات المزاد both carry this key, and asking for it on
        # each was asking twice for one fact -- and letting the two disagree.
        # Whichever is left empty prints what the other was given; untouched,
        # both fall back to the name the project was created with, because a
        # cover with no title on it is worse than a working one.
        # Two lines, always. «يكون اسم المزاد على سطرين إذا تم إستخدام الأيقونة
        # يمين الاسم» -- and on every one of the seven covers the mark stands to
        # the right of the name, so on every one of them the name is set on two
        # lines. The break goes after the first word, which is how both of the
        # designer's own samples are set: «مزاد» over «أعيان حائل», «مـزاد» over
        # «درة البحر». Not a narrower box -- «مزاد أعيان حائل» fits one line in
        # all seven, and the widest of them gives it half the page again.
        {"key": "auction_title", "label": "اسم المزاد", "match": "#FFFFFF",
         "index": 0, "fit": Fit.WRAP, "two_lines": True,
         "default_value": "{auction_title}"},
        # The date only, never the caption above it. On four of the six covers
        # the designer set «تاريخ المزاد» as the first line of this same white
        # run, so a field taking the run whole took the caption with it -- and
        # baking, which clears exactly what a field will draw over, redacted a
        # printed caption off every cover. ``last_line`` keeps the field on the
        # line that is actually data.
        # Keeps its own key rather than sharing `auction_date` with the
        # information and contact pages: that key is a template static, and a
        # project-level value for it would print itself onto the cover.
        # Keeps its own key and inherits the auction's date. The key stays
        # separate because a project-level `auction_date` must not print itself
        # onto the cover; the fallback is what makes the date one fact all the
        # same, typed on معلومات المزاد and printed here without being asked
        # for twice.
        {"key": "auction_date_block", "label": "تاريخ المزاد",
         "match": "#FFFFFF", "index": 1, "last_line": True,
         "align": Align.CENTER, "fit": Fit.WRAP,
         "default_value": "{auction_date}"},
    ],
    "intro_agent": [
        # The title is the company's name, and the company's name is on the
        # account — the guide's own example prints «شركة ملهمة العقارية» here,
        # under that company's mark. Typing over it on the page still wins: a
        # node's value beats the project's.
        {"key": "company_name", "label": "اسم الشركة", "match": "#12395F",
         "index": 0},
        {"key": "agent_about", "label": "نبذة عن وكيل البيع", "match": BODY,
         "merge": True, "cluster": 0, "fit": Fit.WRAP},
        # Three chips, not one run: the designer draws a website, a telephone
        # and an X handle each under its own icon, and one field spanning all
        # three could only ever hold one of them.
        {"match": "#14385F", "columns": [
            ("agent_x", "حساب إكس"),
            ("agent_phone", "رقم التواصل"),
            ("agent_website", "الموقع الإلكتروني"),
        # Right-aligned and grown leftward: each value is printed hard against
        # its icon, and the space it has is whatever is to the left of it.
        # An address, a number and a handle are Latin, and laying them out
        # right-to-left puts the «@» on the wrong end of the name.
        ], "size": 10.2, "grow": True, "align": Align.RIGHT, "rtl": False},
    ],
    "auction_info": [
        # The other half of the pair the cover opens; see the note there.
        {"key": "auction_title", "label": "اسم المزاد", "match": "#11375C",
         "merge": True, "cluster": 0, "fit": Fit.WRAP,
         "default_value": "{auction_title}"},
        {"key": "announcement", "label": "نص الإعلان", "match": "#000000",
         "merge": True, "cluster": 0, "fit": Fit.WRAP},
        # Three chips in the in-person wording, four where a platform is named.
        # Listing them as one rule keeps both exports on the same entry.
        #
        # Started, not centred. The four sit in a column beside their icons and
        # their boxes end within four points of each other, so aligning to the
        # start puts every value on the same line down the page — which is how
        # the guide sets them. Centred, each one floated in a box the width of
        # whatever the designer happened to type, and «الرياض» began a hundred
        # points from «5 يوليو».
        # Each falls back to itself — that is, to wherever in the booklet it
        # was actually typed. معلومات التواصل prints the same four facts, and
        # asking for them on both pages was asking twice for one fact and
        # letting the two disagree. Whichever page it is typed on, both print
        # it; typing on this one still wins here.
        {"match": CHIP, "align": Align.RIGHT, "each": [
            {"key": "auction_time", "label": "وقت المزاد",
             "default_value": "{auction_time}"},
            {"key": "auction_date", "label": "تاريخ المزاد",
             "default_value": "{auction_date}"},
            {"key": "location", "label": "الموقع",
             "default_value": "{location}"},
            {"key": "platform_name", "label": "اسم المنصة",
             "default_value": "{platform_name}"},
        ]},
    ],
    # The same page from the electronic booklet's own export, which is a
    # finished auction rather than a blank template and a later revision of the
    # design: its navy is #13375C where the hybrid's is #11375C, its body is set
    # in rich black rather than flat, its teal is #01A4A2, and the type is a few
    # points larger throughout. Matching on the hybrid's palette found nothing
    # on it, so the page kept the real sale's data printed into the background.
    #
    # Three chips, and the third is the platform. This is the whole point of the
    # variant: an electronic auction is held nowhere, so «الموقع» is not one of
    # its facts and the guide's card does not draw it.
    "auction_info_electronic": [
        {"key": "auction_title", "label": "اسم المزاد",
         "match": ("#13375C", "#1F2243"),
         "merge": True, "cluster": 0, "fit": Fit.WRAP,
         "default_value": "{auction_title}"},
        {"key": "announcement", "label": "نص الإعلان", "match": "#231F20",
         "merge": True, "cluster": 0, "fit": Fit.WRAP},
        {"match": "#01A4A2", "align": Align.RIGHT, "each": [
            {"key": "auction_time", "label": "وقت المزاد",
             "default_value": "{auction_time}"},
            {"key": "auction_date", "label": "تاريخ المزاد",
             "default_value": "{auction_date}"},
            {"key": "platform_name", "label": "اسم المنصة",
             "default_value": "{platform_name}"},
        ]},
    ],
    "lot_standard": [
        # By size, not by run. MuPDF reads the number's badge, the closing
        # chip's caption and the closing date and time as one block spanning the
        # page, so a field taking that run whole cleared the caption with the
        # data and drew the number across all of it. Each is set at its own size,
        # and that is what tells them apart.
        {"key": "lot_number", "label": "رقم العقار", "match": "#FFFFFF",
         "columns": [("lot_number", "رقم العقار")], "sizes": (26.0, 40.0),
         "size": 0.0, "align": Align.CENTER},
        # Only the electronic lot pages carry a closing chip; on the others
        # these find nothing and no field is made.
        #
        # The band spans both drawings of the page: the printed one sets these
        # at 8.4-9.4pt and the screen one at 9.8-11.0. What keeps a band that
        # wide off the printed labels around them is the vocabulary rather than
        # its width -- «الحدود», «الأطوال», «معلومات اضافية» and the four chip
        # captions are all static headings, and a heading is skipped before its
        # size is looked at. Without that, the screen page's chip captions were
        # claimed as the closing date and time, cleared by the bake, and the
        # page came out with two blank bars.
        {"match": "#FFFFFF", "columns": [
            ("closing_date", "تاريخ إغلاق المزايدة"),
            ("closing_time", "وقت إغلاق المزايدة"),
        ], "sizes": (8.0, 11.5), "size": 0.0, "align": Align.CENTER,
         # Measured, and tighter than the default: the printed drawing leaves
         # 19.2pt between the date and the time, the screen one 8.8pt, and ten
         # would read the screen chip as a single value.
         "gap": 8.0},
        {"key": "main_photo", "label": "صورة العقار", "match": "image",
         "required": True, "frame": True},
        {"key": "description", "label": "وصف العقار", "match": BODY,
         "merge": True, "cluster": 0, "fit": Fit.WRAP},
        # The whole drawn box, not the sample paragraph inside it. The guide
        # writes this box as sections -- «مميزات العقار:» over its points, then
        # «الملاحظات:» over its own -- so the heading and the «-1»/«-2» markers
        # the export prints are somebody else's content, not a printed label.
        # Taking only the text cluster left them baked into the background and
        # every property opened with «ملاحظات :» already written in it.
        {"key": "notes", "label": "معلومات إضافية", "match": "box",
         "index": 1, "fit": Fit.WRAP, "valign": VAlign.TOP, "inset": True},
    ],
    "lot_tower": [
        {"key": "lot_number", "label": "رقم العقار", "match": "#FFFFFF",
         "columns": [("lot_number", "رقم العقار")], "sizes": (26.0, 40.0),
         "size": 0.0, "align": Align.CENTER},
        {"match": "#FFFFFF", "columns": [
            ("closing_date", "تاريخ إغلاق المزايدة"),
            ("closing_time", "وقت إغلاق المزايدة"),
        ], "sizes": (8.0, 11.5), "size": 0.0, "align": Align.CENTER,
         # Measured, and tighter than the default: the printed drawing leaves
         # 19.2pt between the date and the time, the screen one 8.8pt, and ten
         # would read the screen chip as a single value.
         "gap": 8.0},
        {"key": "main_photo", "label": "صورة العقار", "match": "image",
         "required": True, "frame": True},
        {"key": "description", "label": "وصف العقار", "match": BODY,
         "merge": True, "cluster": 0, "fit": Fit.WRAP},
        # The whole drawn box, not the sample paragraph inside it. The guide
        # writes this box as sections -- «مميزات العقار:» over its points, then
        # «الملاحظات:» over its own -- so the heading and the «-1»/«-2» markers
        # the export prints are somebody else's content, not a printed label.
        # Taking only the text cluster left them baked into the background and
        # every property opened with «ملاحظات :» already written in it.
        {"key": "notes", "label": "معلومات إضافية", "match": "box",
         "index": 1, "fit": Fit.WRAP, "valign": VAlign.TOP, "inset": True},
    ],
    "lot_features": [
        {"key": "lot_number", "label": "رقم العقار", "match": "#FFFFFF",
         "columns": [("lot_number", "رقم العقار")], "sizes": (26.0, 40.0),
         "size": 0.0, "align": Align.CENTER},
        {"key": "main_photo", "label": "الصورة الرئيسية", "match": "image",
         "frame": True},
        # The two frames beneath it. The guide's own layout for this page is one
        # large photograph over two smaller ones; the export draws all three and
        # only the first carried a sample, so only the first was ever a field.
        {"key": "feature_photo_2", "label": "صورة إضافية ١", "match": "box",
         "index": 1, "type": FieldType.IMAGE},
        {"key": "feature_photo_3", "label": "صورة إضافية ٢", "match": "box",
         "index": 2, "type": FieldType.IMAGE},
        # The sample lease breakdown, which is outlined. Redaction keeps line
        # art, so it used to survive the bake and the page was withheld from the
        # builder rather than ship somebody else's figures -- «تم تأجير العقار
        # بعقد واحد لمدة 20 سنة» and 1,000,000.00 four times over.
        #
        # Line art *can* be removed, in a region taken from the art itself. That
        # is how the agent's lockup and the sample codes came off; this is the
        # same act, and it gives the page back its empty box.
        {"key": "lot_features", "label": "مميزات العقار", "match": "outlined",
         "colours": ("#00385F", "#003760"), "band": (0.63, 0.90),
         "fit": Fit.WRAP},
    ],
    "extra_info": [
        {"key": "extra_info", "label": "معلومات إضافية", "match": "box",
         "index": 0, "fit": Fit.WRAP, "valign": VAlign.TOP, "inset": True},
    ],
    "boundaries": [
        {"key": "boundary_north", "label": "الحد الشمالي", "match": BODY,
         "merge": True, "cluster": 0, "fit": Fit.WRAP},
        {"key": "boundary_south", "label": "الحد الجنوبي", "match": BODY,
         "merge": True, "cluster": 1, "fit": Fit.WRAP},
        {"key": "boundary_east", "label": "الحد الشرقي", "match": BODY,
         "merge": True, "cluster": 2, "fit": Fit.WRAP},
        {"key": "boundary_west", "label": "الحد الغربي", "match": BODY,
         "merge": True, "cluster": 3, "fit": Fit.WRAP},
    ],
    "extra_photos": [
        {"key": "extra_photo_1", "label": "صورة إضافية ١", "match": "box",
         "index": 0, "type": FieldType.IMAGE},
        {"key": "extra_photo_2", "label": "صورة إضافية ٢", "match": "box",
         "index": 1, "type": FieldType.IMAGE},
        {"key": "extra_photo_3", "label": "صورة إضافية ٣", "match": "box",
         "index": 2, "type": FieldType.IMAGE},
    ],
    "contact": [
        # One MuPDF block holds every chip on this page, so it is split back
        # into its columns by the gaps the designer left between them.
        #
        # Four chips, and the page that draws four is the one this list belongs
        # to. A page drawing three is *not* these four minus the last -- see
        # ``contact_inperson``.
        {"match": CHIP_ALT, "columns": [
            {"key": "platform_name", "label": "اسم المنصة",
             "default_value": "{platform_name}"},
            {"key": "location", "label": "الموقع",
             "default_value": "{location}"},
            {"key": "auction_date", "label": "تاريخ المزاد",
             "default_value": "{auction_date}"},
            {"key": "auction_time", "label": "وقت المزاد",
             "default_value": "{auction_time}"},
        ], "size": 10.4},
        # واتساب first, because the splitter hands out keys right to left and
        # the right-hand chip is the WhatsApp one. Measured on the artwork
        # rather than assumed: each icon sits to the *right* of its own number,
        # so the handset at x=268 belongs to the number at 164 and the WhatsApp
        # bubble at x=422 to the number at 309. Listed the other way round, the
        # client's رقم التواصل printed under the WhatsApp mark and their
        # WhatsApp under the telephone — each chip labelled with its
        # neighbour's name, the same way «اسم المنصة» once was.
        {"match": CHIP_ALT, "columns": [
            ("contact_whatsapp", "واتساب"),
            ("contact_phone", "رقم التواصل"),
        ], "size": 14.6},
    ],
    # The same page in the حضوري export, which draws three chips rather than
    # four: there is no platform to name, so the row is الموقع، التاريخ، الوقت.
    #
    # It cannot share the four-chip list. The splitter hands out keys in order,
    # so three columns took the *first three* of them -- and every chip was
    # labelled with its neighbour's name. The client was asked for «اسم المنصة»
    # on a booklet with no platform, typed the venue into it, and «وقت المزاد»
    # was never asked for at all: the clock chip on the page was printing the
    # date. Guide, معلومات التواصل / حضوري.
    # The same page from the electronic export, which sets it differently: the
    # days on the right, the platform in the middle, and the hours on the left
    # as two lines — «يبدأ المزاد الساعة…» over «وينتهي من…». Four runs, three
    # facts, and no venue, which is the guide's electronic card.
    #
    # The hours are two runs and stay two fields rather than being merged into
    # one box: they are two printed lines with a line's worth of space between
    # them, and a single box would have to invent where the break goes.
    # The same page as ``contact``, on an auction that is held nowhere.
    #
    # The الموقع chip and the قاعة المزاد code are taken off the artwork
    # before anything is derived (``SourcePage.remove``), so the card is left
    # with التاريخ، اسم المنصة، الوقت and the two telephone numbers --
    # which is the guide's إلكتروني card. Three columns and no placeholder
    # among them: the chip is not merely unnamed here, it is off the page, so
    # the splitter has three groups to hand out and hands them out in the order
    # they are drawn -- اسم المنصة on the right, then التاريخ, then الوقت.
    "contact_electronic": [
        {"match": CHIP_ALT, "columns": [
            {"key": "platform_name", "label": "اسم المنصة",
             "default_value": "{platform_name}"},
            {"key": "auction_date", "label": "تاريخ المزاد",
             "default_value": "{auction_date}"},
            {"key": "auction_time", "label": "وقت المزاد",
             "default_value": "{auction_time}"},
        ], "size": 10.4},
        {"match": CHIP_ALT, "columns": [
            ("contact_whatsapp", "واتساب"),
            ("contact_phone", "رقم التواصل"),
        ], "size": 14.6},
    ],
    "contact_inperson": [
        {"match": CHIP_ALT, "columns": [
            {"key": "location", "label": "الموقع",
             "default_value": "{location}"},
            {"key": "auction_date", "label": "تاريخ المزاد",
             "default_value": "{auction_date}"},
            {"key": "auction_time", "label": "وقت المزاد",
             "default_value": "{auction_time}"},
        ], "size": 10.4},
        # واتساب first, because the splitter hands out keys right to left and
        # the right-hand chip is the WhatsApp one. Measured on the artwork
        # rather than assumed: each icon sits to the *right* of its own number,
        # so the handset at x=268 belongs to the number at 164 and the WhatsApp
        # bubble at x=422 to the number at 309. Listed the other way round, the
        # client's رقم التواصل printed under the WhatsApp mark and their
        # WhatsApp under the telephone — each chip labelled with its
        # neighbour's name, the same way «اسم المنصة» once was.
        {"match": CHIP_ALT, "columns": [
            ("contact_whatsapp", "واتساب"),
            ("contact_phone", "رقم التواصل"),
        ], "size": 14.6},
    ],
    "steps": [
        # The five captions are the guide's own sentences, and only three words
        # in them belong to this booklet: the platform it is held on and the
        # auction it is for, plus whether the deposit comes back. So the fixed
        # wording rides on the field (prefix/suffix) and the client is asked for
        # the phrase alone -- «اسم المنصة», «اسم المزاد», «قابلة للإسترداد» --
        # which they cannot mistype into the design.
        #
        # Steps 2 and 5 carry nothing that varies, so they are not fields at
        # all. Baking clears only what a field will draw over, so «إستعراض
        # المزادات» and «الفوز بالمزاد» stay exactly as the designer set them,
        # never redrawn and so unable to shift.
        #
        # Order is the sweep's: right to left, the top row of three and then the
        # bottom two -- which is the order the badges are numbered in, checked
        # against the drawn numbers rather than against extraction. Extraction
        # returns these scrambled: «الفوز بالمزاد» comes out third and is drawn
        # fifth, so a list built from reading order would print the client's
        # money back to them before they had bid.
        #
        # The newlines are the designer's line breaks, kept rather than measured
        # so the caption wraps where the artwork wraps.
        {"match": "#15385F", "columns": [
            {"key": "steps_platform", "label": "اسم المنصة",
             "prefix": "تسجيل الدخول في\n",
             "default_value": "{platform_name}"},
            None,                       # إستعراض المزادات — the designer's
            {"key": "steps_refundable", "label": "قابلة للاسترداد",
             "prefix": "سداد قيمة المشاركة في\nالمزاد (", "suffix": ")",
             "default_value": "قابلة للإسترداد"},
            # No brackets. The guide writes this caption «إختيار مزاد (إسم
            # المزاد) والدخول للمشاركه», and the export fills its own sample
            # in between them -- but those brackets are the guide marking a
            # place to be filled, exactly as «شعار وكيل البيع» marks one, and
            # printing them left every booklet reading «إختيار مزاد ( أعيان
            # حائل )». Step 3 keeps its brackets: «(قابلة للإسترداد)» is a
            # parenthetical the guide actually writes, not a place to fill.
            #
            # The no-break spaces went with them. They were there to stop a
            # bracket being pushed onto a line of its own by a name longer
            # than the sample; with no bracket to strand, the name breaks
            # between its own words, which is where a break belongs.
            {"key": "steps_auction_name", "label": "اسم المزاد",
             "prefix": "إختيار مزاد ",
             "suffix": "\nوالدخول للمشاركة",
             "default_value": "{auction_title}"},
            None,                       # الفوز بالمزاد — the designer's
        ], "size": 12.6, "gap": 26.0, "fit": Fit.WRAP,
           # The face and the leading the designer set these in. Medium would be
           # a heavier caption than the page is drawn with, and 1.0 would close
           # the two lines up tighter than the artwork sets them.
           "weight": "Light", "line_height": 1.18, "pad_x": 3.0,
           # The vertical twin of pad_x. A derived box starts at the *ink* of
           # the first line; the engine lays a line out from its ascender, so
           # the caption landed 1.44pt below the one the designer drew. Measured
           # against the export, not guessed -- the two untouched captions on
           # this page (steps 2 and 5) diff to zero, so any offset in the other
           # three is ours.
           "nudge_y": -1.44},
    ],
    "lot_table": [],   # handled by table recovery
    "rent_table": [],  # handled by table recovery
}

#: Pages whose sample copy the designer converted to outlines. Redaction cannot
#: clear a glyph that is line art -- removing it takes the design chips with it
#: and still leaves fragments -- so the page is built, flagged, and kept out of
#: the builder until a revised export arrives with live text.
NEEDS_LIVE_TEXT: dict[str, str] = {}


# ------------------------------------------------------------- geometry


def expand_rect(
    target: DerivedField,
    siblings: list[DerivedField],
    page_rect: fitz.Rect,
    *,
    pad_v: float = 1.5,
    min_gap: float = 3.0,
    max_grow: float = 4.0,
) -> fitz.Rect:
    """Grow a derived rect from the sample's ink extent out to its real cell.

    A derived rect hugs the glyphs of whatever the designer typed, so a field
    whose sample reads "875" is 17pt wide -- and any longer value would then be
    shrunk to fit. Real values need the cell, not the sample.

    Arabic values are right-anchored, so the box keeps its right edge and grows
    leftward until it nearly touches the nearest element on the same row.
    """
    rect = fitz.Rect(target.rect_pt)
    if target.rotation:
        return rect
    row_top, row_bottom = rect.y0 - pad_v, rect.y1 + pad_v
    limit = page_rect.x0
    for other in siblings:
        if other is target:
            continue
        r = other.rect_pt
        if r.y1 <= row_top or r.y0 >= row_bottom:
            continue
        if r.x1 <= rect.x0:
            limit = max(limit, r.x1 + min_gap)
    widest = rect.x1 - (rect.x1 - rect.x0) * max_grow
    rect.x0 = max(limit, widest, page_rect.x0)
    return rect


def _trim_against(
    box: fitz.Rect, others: list[DerivedField], *, gap: float = 1.0
) -> fitz.Rect:
    """Pull a merged box back off any text block that is not part of it.

    A cluster's bounding box can graze the heading above it -- the notes block
    overlapped ``ملاحظات :`` by 2pt -- which would redact design text.
    """
    cx, cy = (box.x0 + box.x1) / 2, (box.y0 + box.y1) / 2
    for other in others:
        r = other.rect_pt
        if not box.intersects(r):
            continue
        if r.y1 <= cy:
            box.y0 = max(box.y0, r.y1 + gap)
        elif r.y0 >= cy:
            box.y1 = min(box.y1, r.y0 - gap)
        elif r.x1 <= cx:
            box.x0 = max(box.x0, r.x1 + gap)
        else:
            box.x1 = min(box.x1, r.x0 - gap)
    return box


def _merge(fields: list[DerivedField]) -> fitz.Rect:
    box = fitz.Rect(fields[0].rect_pt)
    for f in fields[1:]:
        box |= f.rect_pt
    return box


def _clusters(
    fields: list[DerivedField], gap: float = 24.0
) -> list[list[DerivedField]]:
    """Group blocks into paragraphs by vertical proximity.

    The lot page sets both the property description and the notes in the same
    navy, so merging every run of that colour would fuse two unrelated fields
    into one box spanning half the page. The boundaries page sets all four
    directions in it, which is why the cluster index selects one of four.
    """
    ordered = sorted(fields, key=lambda f: f.rect_pt.y0)
    groups: list[list[DerivedField]] = []
    for f in ordered:
        if groups and f.rect_pt.y0 - max(g.rect_pt.y1 for g in groups[-1]) <= gap:
            groups[-1].append(f)
        else:
            groups.append([f])
    return groups


#: How finely a curve is chopped into straight segments. The frames are drawn
#: with a small radius on one corner, and eight steps is smooth at print size.
CURVE_STEPS = 8


#: How far two points have to be apart to count as a break in the path rather
#: than the next segment of it.
SUBPATH_BREAK = 0.5


def _flatten(drawing: dict) -> list[fitz.Point]:
    """A drawing's outline as one polygon, curves chopped into segments.

    The frame a photograph sits in is not a rectangle: the designer cuts a
    corner out of it for the property number, and one page cuts two. A
    photograph placed in the bounding box overhangs the cut, which is what put a
    square photo corner over the badge.

    A path can hold more than one shape, and the قياسي frame does: its fill also
    carries a traced outline of the sample property, floating in the middle.
    Threading that onto the same polygon punched a hole through the photograph,
    so the path is split where it jumps and the largest piece — the frame —
    is the one kept.
    """
    subpaths: list[list[fitz.Point]] = []

    def begin(point: fitz.Point) -> None:
        if (
            not subpaths
            or not subpaths[-1]
            or abs(point.x - subpaths[-1][-1].x) > SUBPATH_BREAK
            or abs(point.y - subpaths[-1][-1].y) > SUBPATH_BREAK
        ):
            subpaths.append([])
        add(point)

    def add(point: fitz.Point) -> None:
        current = subpaths[-1]
        if not current or abs(point.x - current[-1].x) > 0.01 or (
            abs(point.y - current[-1].y) > 0.01
        ):
            current.append(fitz.Point(point))

    for item in drawing.get("items", []):
        kind = item[0]
        if kind == "l":
            begin(item[1])
            add(item[2])
        elif kind == "c":
            start, one, two, end = item[1], item[2], item[3], item[4]
            begin(start)
            for step in range(1, CURVE_STEPS + 1):
                t = step / CURVE_STEPS
                u = 1 - t
                add(
                    fitz.Point(
                        u**3 * start.x + 3 * u * u * t * one.x
                        + 3 * u * t * t * two.x + t**3 * end.x,
                        u**3 * start.y + 3 * u * u * t * one.y
                        + 3 * u * t * t * two.y + t**3 * end.y,
                    )
                )
        elif kind == "re":
            rect = fitz.Rect(item[1])
            subpaths.append([])
            for corner in (
                (rect.x0, rect.y0), (rect.x1, rect.y0),
                (rect.x1, rect.y1), (rect.x0, rect.y1),
            ):
                add(fitz.Point(*corner))
        elif kind == "qu":
            quad = fitz.Quad(item[1])
            subpaths.append([])
            for corner in (quad.ul, quad.ur, quad.lr, quad.ll):
                add(corner)

    def extent(points: list[fitz.Point]) -> float:
        # Measured by hand rather than by unioning rects: a rect built from one
        # point is empty, and PyMuPDF's union ignores an empty rect, so every
        # subpath measured zero and the first one — the traced property, not the
        # frame — won.
        if len(points) < 3:
            return 0.0
        xs = [point.x for point in points]
        ys = [point.y for point in points]
        return (max(xs) - min(xs)) * (max(ys) - min(ys))

    return max(subpaths, key=extent) if subpaths else []


#: A shape overlapping a photo frame and smaller than this fraction of it is
#: something the designer drew *on top* — the property number's badge, the
#: closing-time chip. Anything near the frame's own size is the frame.
OVERLAY_SHARE = 0.25

#: How far inside a drawn container its text begins.
BOX_INSET = 6.0


def _drawn_over(
    page: fitz.Page, frame: fitz.Rect, outline: list[fitz.Point]
) -> list[list[fitz.Point]]:
    """The shapes the designer prints over a photograph.

    The number's badge and the closing-time chip sit across the bottom corners
    of the frame. A photograph is placed on top of the baked artwork, so unless
    it is masked out of them it covers the very things printed over it — which
    is how «تغلق المزايدة على العقار» came to be half a photograph.
    """
    del outline  # the frame's own path is matched by size, not by shape
    over: list[list[fitz.Point]] = []
    for drawing in page.get_drawings():
        box = fitz.Rect(drawing["rect"])
        box.normalize()
        if box.is_infinite or not box.intersects(frame):
            continue
        area = box.get_area()
        if area < 400 or area > frame.get_area() * OVERLAY_SHARE:
            continue
        shape = _flatten(drawing)
        if len(shape) >= 3:
            over.append(shape)
    return over


def _outline_in(rect: fitz.Rect, points: list[fitz.Point]) -> list[list[float]]:
    """A polygon expressed inside its own box, so it moves and scales with it."""
    if len(points) < 3 or not rect.width or not rect.height:
        return []
    return [
        [
            round(min(1.0, max(0.0, (point.x - rect.x0) / rect.width)), 5),
            round(min(1.0, max(0.0, (point.y - rect.y0) / rect.height)), 5),
        ]
        for point in points
    ]


def _containers(
    page: fitz.Page, *, min_area: float = 8000.0
) -> list[tuple[fitz.Rect, list[fitz.Point]]]:
    """The empty boxes the designer drew, largest first, each with its shape.

    Some pages -- معلومات إضافية, صور إضافية -- carry no sample text at all, so
    there is no ink to derive a field from. Their content area is nonetheless
    drawn: it is the container the designer left blank. Taking geometry from
    that path is still taking it from the artwork -- and the path is more than
    its bounding box, so the outline comes back with it.
    """
    page_area = page.rect.get_area()
    boxes: list[tuple[fitz.Rect, list[fitz.Point]]] = []
    for drawing in page.get_drawings():
        rect = fitz.Rect(drawing["rect"])
        area = rect.get_area()
        if area < min_area or area > page_area * 0.92:
            continue
        boxes.append((rect, _flatten(drawing)))
    boxes.sort(key=lambda item: item[0].get_area(), reverse=True)

    # A container drawn as an outline plus a fill shows up twice; keep one.
    kept: list[tuple[fitz.Rect, list[fitz.Point]]] = []
    for rect, outline in boxes:
        if any(abs(rect.x0 - k.x0) < 4 and abs(rect.y0 - k.y0) < 4
               and abs(rect.x1 - k.x1) < 4 and abs(rect.y1 - k.y1) < 4
               for k, _ in kept):
            continue
        kept.append((rect, outline))
    return kept


#: How much room to leave for the icon a chip is printed beside, when a chip is
#: grown out of its sample's ink extent into the space around it.
CHIP_ICON_ROOM = 16.0


def _grown_chips(groups: list[fitz.Rect], page_rect: fitz.Rect) -> list[fitz.Rect]:
    """Give each chip the space the designer left around it.

    A derived box hugs the glyphs of whatever the designer typed, so the box for
    ``www.aayan.sa`` is exactly that wide and a real address two characters
    longer is shrunk to fit inside it. The row is mostly empty: each chip grows
    leftward until it nears the icon of the chip beyond it.

    Widening is safe for the artwork -- baking clears text and leaves line art
    and images, which is all the icons are.
    """
    grown: list[fitz.Rect] = []
    for index, box in enumerate(groups):
        limit = (
            groups[index + 1].x1 + CHIP_ICON_ROOM
            if index + 1 < len(groups)
            else page_rect.x0
        )
        wider = fitz.Rect(box)
        wider.x0 = max(limit, box.x0 - box.width)
        grown.append(wider)
    return grown


def _span_columns(
    page: fitz.Page,
    colour: str,
    size: float | tuple[float, float],
    *,
    gap: float = 10.0,
) -> list[fitz.Rect]:
    """Split one row of same-coloured spans into the chips it is drawn as.

    The contact page sets its date, time, location and platform chips as a
    single MuPDF block, so deriving it yields one box spanning the whole row.
    Drawn, they are four groups separated by the icons between them; the widest
    gap inside a group is 5pt and the narrowest between two is 16pt.

    Returns the groups right to left, the order they read in.
    """
    want = int(colour[1:], 16)
    spans: list[fitz.Rect] = []
    for block in page.get_text("dict")["blocks"]:
        if block.get("type") != 0:
            continue
        for line in block["lines"]:
            for span in line["spans"]:
                if not span["text"].strip():
                    continue
                if span.get("color") != want:
                    continue
                # A printed label is design however it is coloured. The chip
                # captions on a lot page are white on teal, which is what a
                # value looks like here, and on the screen drawing they are set
                # at 9.8pt -- inside the band the closing chip's own parts are
                # matched by. Claimed, they were named «تاريخ إغلاق المزايدة»,
                # cleared by the bake, and the page came out with two blank
                # bars where «الرفع المساحي» and «صور إضافية» had been. The
                # colour-and-size pool has to respect the same vocabulary the
                # rest of derivation does.
                if normalise(span["text"]) in STATIC_HEADINGS:
                    continue
                if isinstance(size, tuple):
                    # A range, for a chip whose parts are set at four sizes
                    # within a point of each other and whose caption is set
                    # above them all.
                    if not size[0] <= span["size"] <= size[1]:
                        continue
                elif abs(span["size"] - size) > 0.3:
                    continue
                spans.append(fitz.Rect(span["bbox"]))
    if not spans:
        return []

    # Rows first, top to bottom. The contact page draws its chips on one row;
    # the participation steps run three across and then two.
    rows: list[list[fitz.Rect]] = []
    for rect in sorted(spans, key=lambda r: r.y0):
        if rows and rect.y0 < max(r.y1 for r in rows[-1]) - 1:
            rows[-1].append(rect)
        else:
            rows.append([rect])

    groups: list[fitz.Rect] = []
    for row in rows:
        row.sort(key=lambda r: -r.x1)
        current = fitz.Rect(row[0])
        for rect in row[1:]:
            if current.x0 - rect.x1 <= gap:
                current |= rect
            else:
                groups.append(current)
                current = fitz.Rect(rect)
        groups.append(current)
    return groups


#: Names for what the sweep finds, in the order it finds them — top to bottom,
#: right to left. Declared because these runs have no readable label: the برج
#: page outlines its الحدود captions, and both lot pages outline «الأطوال». A
#: value with no name is a value the client is asked for as «unnamed_6_3».
SWEEP_NAMES: dict[str, list[tuple[str, str]]] = {
    "lot_standard": [
        ("lengths_1", "الأطوال — السطر الأول"),
        ("lengths_2", "الأطوال — السطر الثاني"),
    ],
    "lot_tower": [
        ("boundary_north", "الحد الشمالي"),
        ("boundary_south", "الحد الجنوبي"),
        ("boundary_east", "الحد الشرقي"),
        ("boundary_west", "الحد الغربي"),
        ("lengths_1", "الأطوال — السطر الأول"),
        ("lengths_2", "الأطوال — السطر الثاني"),
    ],
}


def _sweep_unclaimed(
    candidates: list[DerivedField],
    claimed: list[FieldSpec],
    page_rect: fitz.Rect,
    page_index: int,
    names: list[tuple[str, str]] | None = None,
) -> list[FieldSpec]:
    """Claim every value-coloured run the rules and the vocabulary both missed.

    A run left unclaimed is a run the bake will not clear, and on a lot page
    every value-coloured run is somebody's data. The الأطوال cell is the case
    that forced this: its label is a single rotated white run reading
    ``الحدودالأطوال``, so ``autokey`` has nothing to pair the four measurements
    with and they printed on every booklet.

    The keys are deliberately anonymous. Guessing a name from the sample string
    is the one thing derivation must never do; the template editor is where an
    admin gives these their real names.
    """
    boxes = [c.rect.to_points(page_rect) for c in claimed]
    out: list[FieldSpec] = []
    for field in candidates:
        if field.type is not FieldType.TEXT or field.color not in VALUE_COLORS:
            continue
        if _is_heading(field):
            continue
        rect = field.rect_pt
        area = rect.get_area()
        if any((rect & box).get_area() > area * 0.5 for box in boxes):
            continue
        position = len(out)
        named = names[position] if names and position < len(names) else None
        out.append(
            _spec_from(
                field, page_rect,
                named[0] if named else f"unnamed_{page_index}_{position + 1}",
                siblings=candidates,
                label=named[1] if named else "",
                origin=(
                    f"sweep:value-colour/{named[0]}" if named
                    else "sweep:value-colour"
                ),
            )
        )
    return out


def _spec_from(
    derived: DerivedField,
    page_rect: fitz.Rect,
    key: str,
    siblings: list[DerivedField] | None = None,
    **overrides: Any,
) -> FieldSpec:
    box = (
        expand_rect(derived, siblings, page_rect)
        if siblings is not None and derived.type is FieldType.TEXT
        else derived.rect_pt
    )
    spec = FieldSpec(
        key=key,
        page_index=derived.page_index,
        rect=NormRect.from_points(box, page_rect),
        type=derived.type,
        align=derived.align,
        rotation=derived.rotation,
        font_family=derived.font_family,
        font_weight=derived.font_weight,
        font_size_pt=derived.font_size_pt,
        color=derived.color,
        fit=Fit.SHRINK,
        line_height=1.15 if derived.line_count > 1 else 1.0,
    )
    for name, value in overrides.items():
        setattr(spec, name, value)
    return spec


# ------------------------------------------------------- rule application


def _apply_rules(
    name: str,
    page: fitz.Page,
    page_index: int,
    candidates: list[DerivedField],
    page_rect: fitz.Rect,
) -> list[FieldSpec]:
    """Turn one rule set into field specs for one page."""
    specs: list[FieldSpec] = []
    for rule in RULES.get(name, []):
        match = rule["match"]

        if match == "image":
            pool = [f for f in candidates if f.type is FieldType.IMAGE]
            if not pool:
                continue
            # The hero photograph is the one with real camera resolution, not
            # merely the largest placement rect -- the survey diagram is placed
            # larger but is a low-resolution graphic.
            pick = max(pool, key=lambda f: (f.src_pixels, f.rect_pt.get_area()))
            spec = _spec_from(
                pick, page_rect, rule["key"],
                type=FieldType.IMAGE,
                label=rule.get("label", ""),
                is_required=bool(rule.get("required")),
                origin=f"rule:{rule['key']}/largest-source-image",
            )
            if rule.get("frame"):
                # A placed photo is clipped by the frame the designer drew, and
                # MuPDF reports the placement, not the clip. On the برج layout
                # the same image is placed twice and each placement runs from
                # x=-462 to x=1431, so the unclipped rect covers the whole page:
                # the replacement photo would be drawn across it, and every run
                # underneath would look already claimed. The drawn frame is the
                # visible photo. Deleting the sample still fires -- bake removes
                # an image whose placement merely intersects a region.
                frames = [
                    found
                    for found in _containers(page)
                    if found[0].y1 <= page_rect.height * 0.8
                ]
                if frames:
                    box, outline = frames[0]
                    spec.rect = NormRect.from_points(box, page_rect)
                    spec.clip = _outline_in(box, outline)
                    spec.clip_holes = [
                        _outline_in(box, shape)
                        for shape in _drawn_over(page, box, outline)
                    ]
                    spec.origin = f"rule:{rule['key']}/drawn-frame"
            specs.append(spec)
            continue

        if match == "outlined":
            wanted = {c.upper() for c in rule["colours"]}
            low, high = rule["band"]
            found = [
                box
                for box, _, colour in _art_clusters(page, gap=10.0)
                if colour.upper() in wanted
                and low * page_rect.height <= box.y0
                and box.y1 <= high * page_rect.height
            ]
            if not found:
                continue
            block = found[0]
            for box in found[1:]:
                block |= box
            _erase_blocks(
                page,
                [
                    fitz.Rect(
                        box.x0 - BRAND_ERASE_PAD, box.y0 - BRAND_ERASE_PAD,
                        box.x1 + BRAND_ERASE_PAD, box.y1 + BRAND_ERASE_PAD,
                    )
                    for box in found
                ],
            )
            specs.append(
                FieldSpec(
                    key=rule["key"],
                    page_index=page_index,
                    rect=NormRect.from_points(block, page_rect),
                    type=FieldType.TEXT,
                    label=rule.get("label", ""),
                    align=Align.RIGHT,
                    valign=VAlign.TOP,
                    font_size_pt=10.5,
                    color=BODY,
                    line_height=1.5,
                    fit=rule.get("fit", Fit.WRAP),
                    origin=f"rule:{rule['key']}/outlined-block",
                )
            )
            continue

        if match == "box":
            boxes = _containers(page)
            index = rule.get("index", 0)
            if index >= len(boxes):
                continue
            drawn, outline = boxes[index]
            if rule.get("inset"):
                # Text starts inside the box, and below whatever the designer
                # laid over its top edge -- the معلومات إضافية chip sits across
                # the corner, and a first line pinned to the very top ran under
                # it.
                drawn = fitz.Rect(drawn)
                drawn += (BOX_INSET, BOX_INSET, -BOX_INSET, -BOX_INSET)
                for over in _drawn_over(page, drawn, outline):
                    lid = max(point.y for point in over)
                    if lid < drawn.y0 + drawn.height * 0.25:
                        drawn.y0 = max(drawn.y0, lid + BOX_INSET)
            specs.append(
                FieldSpec(
                    key=rule["key"],
                    page_index=page_index,
                    rect=NormRect.from_points(drawn, page_rect),
                    clip=_outline_in(drawn, outline),
                    type=rule.get("type", FieldType.TEXT),
                    label=rule.get("label", ""),
                    align=Align.RIGHT,
                    valign=rule.get("valign"),
                    font_size_pt=10.0,
                    color=BODY,
                    line_height=1.4,
                    fit=rule.get("fit", Fit.SHRINK),
                    origin=f"rule:{rule['key']}/container={index}",
                )
            )
            continue

        if "columns" in rule:
            groups = _span_columns(
                page,
                match,
                rule.get("sizes") or rule["size"],
                gap=rule.get("gap", 10.0),
            )
            if rule.get("grow"):
                groups = _grown_chips(groups, page_rect)
            # Ragged on purpose: a page carries as many chips as it carries.
            for column, box in zip(rule["columns"], groups, strict=False):
                # ``None`` claims its place in the sweep without making a field:
                # the chip is the designer's and nothing about it varies, so it
                # is left alone -- and, being no field, it is never cleared.
                if column is None:
                    continue
                # A plain pair is a chip that holds only its value. A mapping
                # can also carry the wording printed around it and what shows
                # when nothing has been typed.
                if isinstance(column, tuple):
                    column = {"key": column[0], "label": column[1]}
                # A derived box is the *ink* of the designer's line, and a line
                # needs its side bearings too -- measured at 3pt for every
                # caption on this page, in both directions. Without them the
                # engine wraps a line the designer set as one, and the caption
                # grows a third row it was never drawn with. Padded evenly, so
                # a centred line stays on the centre it was drawn on.
                pad = rule.get("pad_x", 0.0)
                if pad:
                    box = fitz.Rect(box.x0 - pad, box.y0, box.x1 + pad, box.y1)
                specs.append(
                    FieldSpec(
                        key=column["key"],
                        page_index=page_index,
                        rect=NormRect.from_points(box, page_rect),
                        type=FieldType.TEXT,
                        label=column.get("label", ""),
                        align=rule.get("align", Align.CENTER),
                        font_weight=rule.get("weight", "Medium"),
                        font_size_pt=(
                            sum(rule["sizes"]) / 2
                            if rule.get("sizes")
                            else rule["size"]
                        ),
                        color=match,
                        line_height=rule.get("line_height", 1.0),
                        calibration_dy=rule.get("nudge_y", 0.0),
                        fit=rule.get("fit", Fit.SHRINK),
                        rtl=rule.get("rtl", True),
                        prefix=column.get("prefix", ""),
                        suffix=column.get("suffix", ""),
                        default_value=column.get("default_value", ""),
                        origin=f"rule:{column['key']}/chip-column",
                    )
                )
            continue

        pool = [
            f
            for f in candidates
            if f.type is FieldType.TEXT
            and _colour_matches(f.color, match)
            and not _is_heading(f)
        ]
        if not pool:
            continue

        if "each" in rule:
            # As many fields as the page actually carries: the in-person
            # wording has three of these chips, the others four.
            # Ragged on purpose: three chips in one wording, four in another.
            for entry, field in zip(rule["each"], pool, strict=False):
                # ``None`` claims a chip's place in the row without making a
                # field of it, the way it does in ``columns``: the keys are
                # handed out in order, so a page that draws a chip this variant
                # has no fact for would otherwise give every chip after it its
                # neighbour's name.
                if entry is None:
                    continue
                # A pair is a chip that only holds its value; a mapping can
                # also say what it falls back to, which is how a fact named on
                # two pages is asked for once. Same shape as ``columns``.
                if isinstance(entry, tuple):
                    entry = {"key": entry[0], "label": entry[1]}
                specs.append(
                    _spec_from(
                        field, page_rect, entry["key"],
                        siblings=candidates,
                        label=entry.get("label", ""),
                        align=rule.get("align", Align.CENTER),
                        default_value=entry.get("default_value", ""),
                        origin=f"rule:{entry['key']}/colour={match}/each",
                    )
                )
            continue

        if rule.get("merge"):
            groups = _clusters(pool)
            which = rule.get("cluster", 0)
            if which >= len(groups):
                continue
            chosen = groups[which]
            box = _merge(chosen)
            outsiders = [
                f for f in candidates if f.type is FieldType.TEXT and f not in chosen
            ]
            box = _trim_against(box, outsiders)
            base = max(chosen, key=lambda f: f.rect_pt.get_area())
            spec = _spec_from(base, page_rect, rule["key"],
                              fit=rule.get("fit", Fit.SHRINK))
            spec.rect = NormRect.from_points(box, page_rect)
            spec.valign = VAlign.TOP
            spec.line_height = 1.4
            spec.label = rule.get("label", "")
            spec.default_value = rule.get("default_value", "")
            spec.origin = f"rule:{rule['key']}/colour={match}/cluster={which}"
            specs.append(spec)
            continue

        index = rule.get("index", 0)
        if index >= len(pool):
            continue
        extras = {
            k: v
            for k, v in rule.items()
            if k in {"align", "fit", "valign", "default_value", "two_lines"}
        }
        spec = _spec_from(
            pool[index], page_rect, rule["key"],
            siblings=candidates,
            label=rule.get("label", ""),
            origin=f"rule:{rule['key']}/colour={match}/index={index}",
            **extras,
        )
        if rule.get("last_line"):
            spec.rect = NormRect.from_points(
                _last_line_box(
                    pool[index], spec.rect.to_points(page_rect), page_rect
                ),
                page_rect,
            )
            spec.line_height = 1.0
            spec.origin += "/last-line"
        specs.append(spec)
    return specs


#: How far a redaction has to stay below the caption above it. A glyph whose
#: box merely grazes a redaction rect is removed whole, and Arabic line boxes
#: overlap by a couple of points because they carry descender room -- which is
#: how the cover caption came to be cleared by the field beneath it.
CAPTION_CLEARANCE = 0.5


def _text_rows(derived: DerivedField) -> list[fitz.Rect]:
    """A run's lines as the rows they are *printed* as, top to bottom.

    Neither of the obvious shortcuts works on this export. MuPDF's line order is
    the order Illustrator wrote the runs, which on the covers puts the date
    before the caption above it; and its idea of a line splits the date into two
    where the designer nudged one chip three points. So rows are grouped by how
    far apart their middles are -- two boxes belong to the same printed row when
    their centres are closer than half a line -- and then sorted down the page.

    Line boxes carry descender room, so the caption's box and the date's box
    overlap by three points even though nothing about them touches on paper.
    Testing overlap would fuse them; testing centres does not.
    """
    lines = [fitz.Rect(line) for line in derived.lines_pt if not line.is_empty]
    if not lines:
        return [fitz.Rect(derived.rect_pt)]
    lines.sort(key=lambda r: r.y0 + r.height / 2)

    rows: list[fitz.Rect] = [fitz.Rect(lines[0])]
    for line in lines[1:]:
        current = rows[-1]
        apart = abs(
            (line.y0 + line.height / 2) - (current.y0 + current.height / 2)
        )
        if apart < min(line.height, current.height) / 2:
            rows[-1] = current | line
        else:
            rows.append(fitz.Rect(line))
    return rows


#: How much wider than its sample a centred value may be. The date reads
#: «27-29 يوليو 2026 م» in the artwork and a real one is about as long, so twice
#: the sample is room to spare without reaching the logo beside it.
CENTRED_ROOM = 2.0


def _centred_on(row: fitz.Rect, page_rect: fitz.Rect) -> tuple[float, float]:
    """A box centred on a printed row, with room to grow either way.

    Growing leftward is right for a value pinned to a printed label on its
    right. It is wrong for one printed *under* a caption: the caption is centred
    over it, so the value has to stay centred there too, and a box grown only
    leftward slides the date out from under its own heading.
    """
    middle = (row.x0 + row.x1) / 2
    half = min(
        row.width * CENTRED_ROOM / 2,
        middle - page_rect.x0,
        page_rect.x1 - middle,
    )
    return middle - half, middle + half


def _last_line_box(
    derived: DerivedField, expanded: fitz.Rect, page_rect: fitz.Rect
) -> fitz.Rect:
    """The bottom printed row of a run, centred where it is printed.

    Only the bottom row is data; anything above it is the caption the designer
    printed over it, and clearing that with the value is what took «تاريخ
    المزاد» off every cover.
    """
    rows = _text_rows(derived)
    box = fitz.Rect(expanded)
    box.x0, box.x1 = _centred_on(rows[-1], page_rect)
    if len(rows) < 2:
        return box
    box.y0 = max(box.y0, rows[-2].y1 + CAPTION_CLEARANCE)
    box.y1 = max(box.y0 + 1.0, rows[-1].y1)
    return box


# ------------------------------------------------------------ the lot links

#: The four codes the designer prints on a property page, and what each is for.
#: Read top to bottom and right to left, the order the page reads in.
#:
#: Two of the four captions are live text and two are outlined, so the names are
#: declared here and the two that can be read are checked against them --
#: ``assert_lot_links`` is the tripwire for an export that reorders them.
LOT_LINKS: tuple[tuple[str, str], ...] = (
    ("link_survey", "الرفع المساحي"),
    # An address like the other three, and a code printed like the other three:
    # the designer draws four codes on this block and this is the fourth. It
    # also leads to a page of the booklet, and on screen that is where it goes
    # -- a jump beats an address, because nobody should have to look up a URL
    # for a page they are holding. On paper a code cannot jump, so it carries
    # the address the client gave for the property's lease information.
    ("link_lease", "معلومات الإيجار"),
    ("link_photos", "صور إضافية"),
    ("link_map", "أضغط هنا للوصول للرابط"),
)

#: The booklet's own two codes, one per page, belonging to the auction rather
#: than to any property: the platform to bid on, and where the auction is held.
STEPS_LINKS: tuple[tuple[str, str], ...] = (
    ("platform_link", "امسح او اضغط للدخول على المنصة الالكترونية"),
)
CONTACT_LINKS: tuple[tuple[str, str], ...] = (("venue_link", "قاعة المزاد"),)

#: The same four chips in the order the *column* stacks them.
#:
#: Not the order the printed block uses. The 2x2 block reads survey, lease,
#: photos, map -- right to left, top row then bottom -- and the column reads
#: survey, photos, lease, map, top to bottom. Both are measured off the artwork
#: rather than assumed from the other, and the build checks each: the قياسي
#: column sets its captions as live text and they are compared name by name,
#: while the برج column outlines its own, so there the ink widths are ranked
#: against the widths the brand font gives these four strings.
LOT_LINKS_COLUMN: tuple[tuple[str, str], ...] = (
    ("link_survey", "الرفع المساحي"),
    ("link_photos", "صور إضافية"),
    ("link_lease", "معلومات الإيجار"),
    ("link_map", "أضغط هنا للوصول للرابط"),
)

#: Which pages print codes, and what each of theirs is for.
LINK_PAGES: dict[PageRole, tuple[tuple[str, str], ...]] = {
    PageRole.LOT: LOT_LINKS,
    PageRole.STEPS: STEPS_LINKS,
    PageRole.CONTACT: CONTACT_LINKS,
}

#: The prefix that keeps a field out of the builder. The code itself is not
#: something a client types: they give the address it should lead to, and the
#: system mints the permanent one that is actually printed.
QR_PREFIX = "__qr_"

#: A code is a dense square of small teal paths. Nothing else on a lot page is.
QR_MIN_PATHS = 15
QR_ASPECT_TOLERANCE = 0.1
QR_MIN_SIDE = 25.0
QR_MAX_SIDE = 60.0


def _qr_slots(page: fitz.Page) -> list[tuple[fitz.Rect, str]]:
    """Where the page prints its codes, in reading order, and in what colour.

    The colour comes back because the replacement has to be printed in it. The
    booklet sets its codes in the brand teal and its contact code in the brand
    navy; a black one would be the only black thing on the page.
    """
    found: list[tuple[fitz.Rect, str]] = []
    for box, paths, colour in _art_clusters(page, gap=4.0):
        if paths < QR_MIN_PATHS or not box.height:
            continue
        if abs(box.width / box.height - 1.0) > QR_ASPECT_TOLERANCE:
            continue
        if not QR_MIN_SIDE < box.width < QR_MAX_SIDE:
            continue
        found.append((box, colour))
    found.sort(key=lambda item: (round(item[0].y0, 1), -item[0].x1))
    return found


#: How far a caption may be from the code it names before the pairing is a
#: coincidence rather than a fact about the page.
CAPTION_REACH = 90.0


def assert_link_captions(
    page: fitz.Page,
    slots: list[fitz.Rect],
    named: tuple[tuple[str, str], ...],
) -> None:
    """Check every caption that can be read says what the map claims.

    Some of them are outlined, which is why the names are declared at all — but
    the ones that survive as text are checked, and that is enough to catch a
    revised export that reorders the block rather than four booklets going out
    with the lease link under «صور إضافية».
    """
    # A list, not a lookup: the same words can be printed more than once on a
    # page, and «الرفع المساحي» is — once as the caption over a code, once
    # inside the sentence «وهي مبينة في الرفع المساحي المرفق» halfway across the
    # page. Keeping only one of them checked the wrong one.
    printed = [
        (normalise(span["text"]), fitz.Rect(span["bbox"]))
        for block in page.get_text("dict")["blocks"]
        if block.get("type") == 0
        for line in block["lines"]
        for span in line["spans"]
        if span["text"].strip()
    ]
    for slot, (key, caption) in zip(slots, named, strict=True):
        wanted = normalise(caption)
        found = [box for text, box in printed if wanted in text]
        if not found:
            continue  # outlined, so it cannot be checked -- see the docstring
        near = fitz.Rect(
            slot.x0 - CAPTION_REACH,
            slot.y0 - CAPTION_REACH,
            slot.x1 + CAPTION_REACH,
            slot.y1 + CAPTION_REACH,
        )
        if not any(near.intersects(box) for box in found):
            raise MapError(
                f"page {page.number}: «{caption}» is nowhere near the code the "
                f"map gives to {key} -- the export has reordered its links"
            )


#: How far from a code to look for the caption that belongs to it, as a
#: multiple of the code's own side. The property page prints a bar directly
#: above; the steps and contact pages print a sentence beside it that runs two
#: and a half times its width, which is what sets this. Looking further costs
#: nothing: the caption has to *start* within a fraction of the code's width
#: (``approach``), and the search stops at the next code either way.
CLICK_REACH = 2.8
#: Slack around what is found, so the click target does not stop on the ink.
CLICK_PAD = 2.0
#: How different from the paper a pixel has to be to count as printed.
CLICK_INK = 60


def _caption_near(
    page: fitz.Page, slot: fitz.Rect, others: list[fitz.Rect]
) -> fitz.Rect | None:
    """The caption printed with a code, read off the page.

    Not from ``get_drawings``: the property page's caption bars are not in it at
    all, whatever they are drawn as. They are unmistakable on the page itself,
    which is where this looks.

    A whole sector at a time rather than a probe along one line. The contact
    page sets its caption in two lines with a gap between them, and a single row
    of pixels through the middle of a code goes straight through that gap and
    reports nothing there. A sector also takes a caption entire — the property
    page's bar, and the sentence beside the other two — where following one run
    of ink stops at the first space between words.

    Above first, because that is where the property page puts its bar; then to
    either side, which is where the steps and contact pages put their sentence.
    """
    reach = slot.width * CLICK_REACH
    window = fitz.Rect(
        slot.x0 - reach, slot.y0 - reach, slot.x1 + reach, slot.y1 + reach
    ) & page.rect
    # Never look past another code. The property page stacks two rows of them
    # five points apart, which is closer than the gap between the two lines of
    # one caption -- so nothing measured in blank space alone can tell the
    # difference, and this does not have to.
    for other in others:
        if other.x1 <= slot.x0 or other.x0 >= slot.x1:
            continue
        if other.y1 <= slot.y0:
            window.y0 = max(window.y0, other.y1 + CLICK_PAD)
        elif other.y0 >= slot.y1:
            window.y1 = min(window.y1, other.y0 - CLICK_PAD)
    for other in others:
        if other.y1 <= slot.y0 or other.y0 >= slot.y1:
            continue
        if other.x1 <= slot.x0:
            window.x0 = max(window.x0, other.x1 + CLICK_PAD)
        elif other.x0 >= slot.x1:
            window.x1 = min(window.x1, other.x0 - CLICK_PAD)
    if window.is_empty:
        return None
    pixels = page.get_pixmap(clip=window, dpi=72)
    wide, high, depth = pixels.width, pixels.height, pixels.n
    if not wide or not high:
        return None
    samples = pixels.samples

    def dot(x: int, y: int) -> bytes:
        start = (y * wide + x) * depth
        return samples[start : start + depth]

    edges = (
        [dot(x, 0) for x in range(wide)]
        + [dot(x, high - 1) for x in range(wide)]
        + [dot(0, y) for y in range(high)]
        + [dot(wide - 1, y) for y in range(high)]
    )
    paper = max(set(edges), key=edges.count)

    def ink(x: int, y: int) -> bool:
        here = dot(x, y)
        return sum(abs(here[c] - paper[c]) for c in range(3)) > CLICK_INK

    left = max(0, round(slot.x0 - window.x0))
    right = min(wide - 1, round(slot.x1 - window.x0))
    top = max(0, round(slot.y0 - window.y0))
    bottom = min(high - 1, round(slot.y1 - window.y0))
    #: A caption is allowed to be a little wider than the code it names, but
    #: not to wander. Tied to the code and not to the reach: the reach is wide
    #: so a sentence beside a code can be followed to its end, and a sector that
    #: wide above a code on the property page would take in the next chip's bar
    #: and hand two chips overlapping click targets.
    spread = round(slot.width * 0.6)
    #: A caption may be two lines, so a couple of blank points inside it is
    #: still the same caption. More than that and whatever comes next belongs
    #: to the page, not to this code.
    line_gap = 8
    #: Sideways the same run has to cross the spaces between words, which are
    #: wider than the space between two lines and wider still where the line is
    #: justified.
    word_gap = 18
    #: And a caption is printed *with* its code. Anything further off than this
    #: is something else on the page -- the steps page has a sentence forty
    #: points above its code that belongs to the step above.
    approach = max(6, round(slot.width * 0.45))

    def band(order: list[int], inked, across: int) -> list[int]:
        """Outward from the code to the first printed thing, and across it."""
        run: list[int] = []
        blanks = 0
        for step in order:
            if inked(step):
                run.append(step)
                blanks = 0
                continue
            blanks += 1
            if blanks > (across if run else approach):
                break
        return run

    def boxed(xs: list[int], ys: list[int]) -> fitz.Rect | None:
        found = [(x, y) for y in ys for x in xs if ink(x, y)]
        if not found:
            return None
        return fitz.Rect(
            window.x0 + min(x for x, _ in found) - CLICK_PAD,
            window.y0 + min(y for _, y in found) - CLICK_PAD,
            window.x0 + max(x for x, _ in found) + 1 + CLICK_PAD,
            window.y0 + max(y for _, y in found) + 1 + CLICK_PAD,
        )

    wider = list(range(max(0, left - spread), min(wide, right + spread + 1)))
    taller = list(range(max(0, top - spread), min(high, bottom + spread + 1)))

    above = band(
        list(range(top - 2, -1, -1)),
        lambda y: any(ink(x, y) for x in wider),
        line_gap,
    )
    if above:
        return boxed(wider, above)
    right_of = band(
        list(range(right + 2, wide)),
        lambda x: any(ink(x, y) for y in taller),
        word_gap,
    )
    if right_of:
        return boxed(right_of, taller)
    left_of = band(
        list(range(left - 2, -1, -1)),
        lambda x: any(ink(x, y) for y in taller),
        word_gap,
    )
    return boxed(left_of, taller) if left_of else None


def _link_fields(
    page: fitz.Page,
    page_index: int,
    page_rect: fitz.Rect,
    slots_named: tuple[tuple[str, str], ...] = LOT_LINKS,
) -> list[FieldSpec]:
    """Two fields per code: the address, and the code that leads to it.

    The address is what a client supplies and what an electronic booklet links
    to. The code printed beside it never carries that address directly -- it
    carries a permanent one this system owns and redirects, so a destination can
    change without the paper being reprinted.
    """
    found = _qr_slots(page)
    slots = [box for box, _ in found]
    colours = [colour for _, colour in found]
    if len(slots) != len(slots_named):
        return []
    assert_link_captions(page, slots, slots_named)
    # Found before the codes are erased: a caption is located by looking out
    # from the code, and there has to be a code there to look out from.
    targets = [
        _caption_near(page, slot, [o for o in slots if o is not slot])
        for slot in slots
    ]

    # The designer's own four codes come off the page. Baking clears text and
    # images and keeps line art, and a code is line art -- so until now every
    # booklet went out with four scannable codes leading to the sample auction.
    _erase_blocks(
        page,
        [
            fitz.Rect(
                slot.x0 - BRAND_ERASE_PAD,
                slot.y0 - BRAND_ERASE_PAD,
                slot.x1 + BRAND_ERASE_PAD,
                slot.y1 + BRAND_ERASE_PAD,
            )
            for slot in slots
        ],
    )

    specs: list[FieldSpec] = []
    for slot, colour, target, (key, caption) in zip(
        slots, colours, targets, slots_named, strict=True
    ):
        rect = NormRect.from_points(slot, page_rect)
        # A code is what a scanner needs; a caption is what a reader clicks. On
        # screen the whole chip is the target, not the empty square where the
        # code would have been.
        clickable = fitz.Rect(slot) | target if target else fitz.Rect(slot)
        specs.append(
            FieldSpec(
                key=key,
                page_index=page_index,
                rect=NormRect.from_points(clickable & page_rect, page_rect),
                type=FieldType.LINK,
                label=caption,
                rtl=False,
                origin=f"rule:{key}/link-chip",
            )
        )
        if key.startswith("__"):
            continue  # leads inside the booklet; a printed code cannot
        specs.append(
            FieldSpec(
                key=f"{QR_PREFIX}{key}",
                page_index=page_index,
                rect=rect,
                type=FieldType.QR,
                label=caption,
                color=colour,
                origin=f"rule:{key}/link-code",
            )
        )
    return specs


#: A chip on the screen drawing: a rounded bar with its caption reversed out of
#: it, placed as a small image. Both columns' bars sit inside these bounds --
#: 100x19 on قياسي, 86x18 on برج -- and nothing else on a lot page is a wide
#: flat image in the lower-left corner.
CHIP_BAR_WIDTH = (60.0, 140.0)
CHIP_BAR_HEIGHT = (12.0, 26.0)

#: How far two bars' left edges may differ and still be one column.
COLUMN_TOLERANCE = 1.5


def _chip_column(page: fitz.Page) -> list[fitz.Rect]:
    """The stack of link chips on a page drawn for a screen, top to bottom.

    A printed lot page pairs each chip with a code, and ``_qr_slots`` finds the
    codes. There are no codes here -- a chip on a screen is clicked -- so the
    chips are found as what they are: identical bars down the left of the page,
    evenly spaced.
    """
    bars = [
        rect
        for info in page.get_image_info(xrefs=True)
        if (rect := fitz.Rect(info["bbox"]))
        and CHIP_BAR_WIDTH[0] <= rect.width <= CHIP_BAR_WIDTH[1]
        and CHIP_BAR_HEIGHT[0] <= rect.height <= CHIP_BAR_HEIGHT[1]
        and rect.x1 < page.rect.width * 0.55
        and rect.y0 > page.rect.height * 0.65
    ]
    if len(bars) < 3:
        return []
    bars.sort(key=lambda r: r.y0)
    left = bars[0].x0
    if any(abs(r.x0 - left) > COLUMN_TOLERANCE for r in bars):
        return []
    steps = [b.y0 - a.y0 for a, b in pairwise(bars)]
    if max(steps) - min(steps) > 2.0:
        return []
    return bars


def _column_captions(page: fitz.Page, bars: list[fitz.Rect]) -> list[str]:
    """Each bar's printed caption, where the export set it as live text."""
    out: list[str] = []
    for bar in bars:
        words = [
            span["text"]
            for block in page.get_text("dict")["blocks"]
            if block["type"] == 0
            for line in block["lines"]
            for span in line["spans"]
            if span["text"].strip() and bar.intersects(fitz.Rect(span["bbox"]))
        ]
        out.append(normalise("".join(words)))
    return out


def _caption_ink(page: fitz.Page, bar: fitz.Rect) -> float:
    """How wide the caption inside a bar is drawn, outlines included.

    The برج column converts its captions to outlines, so there is no string to
    compare. There is still a width, and four strings of different lengths rank
    by width in one order only -- which is enough to say the column is stacked
    the way it is declared, and to refuse the page if a revision reorders it.
    """
    spans = [
        fitz.Rect(drawing["rect"])
        for drawing in page.get_drawings()
        if bar.contains(fitz.Rect(drawing["rect"]).normalize() & bar)
        and bar.intersects(fitz.Rect(drawing["rect"]))
        and _ink(drawing.get("fill")) == [1.0, 1.0, 1.0]
    ]
    if not spans:
        return 0.0
    return max(s.x1 for s in spans) - min(s.x0 for s in spans)


def _assert_column_order(
    page: fitz.Page, bars: list[fitz.Rect], named: tuple[tuple[str, str], ...]
) -> None:
    """Refuse a column whose chips are not in the order that was declared."""
    captions = _column_captions(page, bars)
    if all(captions):
        for got, (key, want) in zip(captions, named, strict=True):
            if normalise(want) not in got and got not in normalise(want):
                raise MapError(
                    f"page {page.number}: the chip column reads {captions!r}, "
                    f"which is not the declared order "
                    f"{[c for _, c in named]!r} -- {key!r} is in the wrong place"
                )
        return

    # Outlined: rank the drawn widths against the widths the brand font gives
    # these strings. Absolute widths would depend on the face and the size the
    # designer set; the order they come in does not.
    face = brand_registry().face("RuaqArabic", "Medium")
    font = fitz.Font(fontbuffer=brand_registry().data(face))
    drawn = [_caption_ink(page, bar) for bar in bars]
    if not all(drawn):
        raise MapError(
            f"page {page.number}: a chip in the column has no caption in it"
        )
    wanted = [font.text_length(caption, fontsize=10) for _, caption in named]
    if _ranking(drawn) != _ranking(wanted):
        raise MapError(
            f"page {page.number}: the outlined chip captions are drawn "
            f"{[round(w, 1) for w in drawn]} wide, which does not rank like "
            f"{[c for _, c in named]!r} ({[round(w, 1) for w in wanted]}) -- "
            f"the column is not stacked in the declared order"
        )


def _ranking(values: list[float]) -> list[int]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    rank = [0] * len(values)
    for place, index in enumerate(order):
        rank[index] = place
    return rank


def _column_link_fields(
    page: fitz.Page, page_index: int, page_rect: fitz.Rect
) -> list[FieldSpec]:
    """The link chips on a lot page drawn for a screen.

    One field per chip and no code beside it: the whole bar is the click
    target, which is what «أضغط هنا للوصول للرابط» asks a reader to do. The
    printed drawing of the same page keeps its 2x2 block and its four codes;
    this is the other drawing, not a replacement for it.

    A column of three is the designer's own page for a property with no lease
    contracts -- the قياسي screen page is drawn that way -- so the lease chip is
    dropped from the naming rather than the column being called wrong.
    """
    bars = _chip_column(page)
    if not bars:
        return []
    named = LOT_LINKS_COLUMN
    if len(bars) == len(named) - 1:
        named = tuple(n for n in named if n[0] != "link_lease")
    if len(bars) != len(named):
        raise MapError(
            f"page {page.number}: {len(bars)} chips in the column, and the "
            f"map knows of {len(LOT_LINKS_COLUMN)}"
        )
    _assert_column_order(page, bars, named)
    return [
        FieldSpec(
            key=key,
            page_index=page_index,
            rect=NormRect.from_points(bar & page_rect, page_rect),
            type=FieldType.LINK,
            label=caption,
            rtl=False,
            origin=f"rule:{key}/link-chip/column",
        )
        for bar, (key, caption) in zip(bars, named, strict=True)
    ]


#: The key of the one chip a booklet does not always print.
LEASE_CHIP_KEY = "link_lease"

#: How far beside a chip's bar its arrow may sit and still be part of it.
#: Measured: the printed drawing leaves 5.4pt between the bar and the arrow,
#: the screen one 6.0pt, and the next chip is a whole row away.
CHIP_ARROW_REACH = 14.0


def _chip_bar(page: fitz.Page, near: fitz.Rect) -> fitz.Rect | None:
    """The bar a caption is reversed out of, given roughly where the chip is."""
    found = [
        rect
        for info in page.get_image_info(xrefs=True)
        if (rect := fitz.Rect(info["bbox"]))
        and CHIP_BAR_WIDTH[0] <= rect.width <= CHIP_BAR_WIDTH[1]
        and CHIP_BAR_HEIGHT[0] <= rect.height <= CHIP_BAR_HEIGHT[1]
        and rect.intersects(near)
    ]
    if not found:
        return None
    return max(found, key=lambda r: (r & near).get_area())


def _chip_region(page: fitz.Page, bar: fitz.Rect) -> fitz.Rect:
    """The whole chip: its bar, the caption inside it and the arrow beside it.

    The arrow is a separate shape a few points away and it belongs to the chip
    -- left behind, it would point at nothing.
    """
    region = fitz.Rect(bar)
    band = fitz.Rect(
        bar.x0 - CHIP_ARROW_REACH, bar.y0 - 2.0,
        bar.x1 + CHIP_ARROW_REACH, bar.y1 + 2.0,
    )
    for drawing in page.get_drawings():
        rect = fitz.Rect(drawing["rect"])
        rect.normalize()
        if rect.is_empty or rect.width > CHIP_ARROW_REACH:
            continue
        if band.contains(rect):
            region |= rect
    return region + (-1.0, -1.0, 1.0, 1.0)


#: How much of the ring around a chip has to be one colour before that colour
#: can be called the page's ground there. The rest is the ink of whatever the
#: chip stands next to -- its own arrow, the code below it -- which is outside
#: the cutting and stays exactly where it is. Measured at 94% on the printed
#: drawing and 99% on the screen one.
GROUND_SHARE = 0.90


def _chip_ground(page: fitz.Page, region: fitz.Rect) -> tuple[float, ...] | None:
    """The colour the page is behind a chip, or ``None`` if it is not one.

    A chip's bar is a raster the export inlines, and MuPDF's redaction removes
    images by xref -- an inlined one has none, so it survives every mode. What
    does take it off is the redaction's own fill, and a fill is a patch unless
    it is the colour that was already there.

    So the ring around the chip is sampled and has to agree. It does: these
    chips sit on the page's plain white, which the designer's own drawing
    confirms -- the قياسي screen page carries three chips and nothing at all
    where the fourth would be.

    The build refuses to cut a chip whose ground it cannot name, because on a
    coloured page a patch would be a patch.
    """
    pad = 3.0
    outer = (region + (-pad, -pad, pad, pad)) & page.rect
    pix = page.get_pixmap(dpi=150, clip=outer)
    scale = pix.width / outer.width if outer.width else 0
    if not scale:
        return None
    inside = (
        (region.x0 - outer.x0) * scale, (region.y0 - outer.y0) * scale,
        (region.x1 - outer.x0) * scale, (region.y1 - outer.y0) * scale,
    )
    counted: Counter = Counter()
    for y in range(pix.height):
        for x in range(pix.width):
            if inside[0] <= x <= inside[2] and inside[1] <= y <= inside[3]:
                continue
            counted[pix.pixel(x, y)] += 1
    if not counted:
        return None
    (colour, votes), = counted.most_common(1)
    if votes < sum(counted.values()) * GROUND_SHARE:
        return None
    return tuple(channel / 255 for channel in colour)


def _cut_out_chip(
    doc: fitz.Document, page_index: int, spec: FieldSpec, page_rect: fitz.Rect
) -> bool:
    """Take one chip off the artwork and keep it, so it can be put back.

    The cutting goes on a page of its own at the end of the background PDF and
    the region is redacted out of the artwork -- bar, caption and arrow
    together, which needs images and line art removed as well as text. Putting
    it back is ``show_pdf_page``, which reproduces all three exactly; measured
    against the artwork it replaced, nothing differs.

    ``False`` where the chip cannot be found, and the page keeps it printed --
    which is what it did before, so the booklet is never worse for this failing.
    """
    page = doc[page_index]
    bar = _chip_bar(page, spec.rect.to_points(page_rect))
    if bar is None:
        return False
    region = _chip_region(page, bar) & page_rect
    if region.is_empty:
        return False

    # Copied before the page is cut, and through a scratch document because
    # MuPDF refuses to place a page of a document onto a page of the same one.
    # The redaction goes first: adding a page invalidates the handles already
    # taken on this one.
    scratch = fitz.open()
    scratch.insert_pdf(doc, from_page=page_index, to_page=page_index)

    ground = _chip_ground(page, region)
    if ground is None:
        scratch.close()
        return False
    # Filled with the page's own colour, not merely cleared: the bar is an
    # inlined raster and no redaction mode removes one.
    page.add_redact_annot(region, fill=ground)
    page.apply_redactions(
        images=fitz.PDF_REDACT_IMAGE_REMOVE,
        graphics=fitz.PDF_REDACT_LINE_ART_REMOVE_IF_COVERED,
    )

    cutting = doc.new_page(width=region.width, height=region.height)
    cutting.show_pdf_page(cutting.rect, scratch, 0, clip=region)
    scratch.close()
    spec.part = ChipPart(
        page=doc.page_count - 1,
        rect=NormRect.from_points(region, page_rect),
    )
    return True


# ------------------------------------------------------------- the branding

#: The selling agent's lockup, as the designer draws it on nearly every page:
#: a wordmark beside a building mark, outlined so there is no text to read and
#: no name to match. What identifies it is its shape — twenty-three paths in a
#: fixed proportion, at whatever size the page uses. A page that carries it
#: twice (the features page draws it over itself) is still one mark.
BRAND_ASPECT = 3.37
BRAND_ASPECT_TOLERANCE = 0.25
BRAND_MIN_PATHS = 15

#: A path bigger than this is page furniture -- a table rule, a banner, a
#: background panel -- and clustering the mark together with one swallows it.
#: Every path in the lockup is a letter or a roof line.
BRAND_MAX_PATH_W = 0.35
BRAND_MAX_PATH_H = 0.15

#: Clustering distance is the one thing that cannot be fixed: the lockup is
#: drawn at 75pt wide in a footer and at 195pt on the contact page, and the gaps
#: inside it scale with it. Tried smallest first, so the tightest grouping that
#: makes the shape wins.
BRAND_GAPS = (1.0, 2.0, 3.0, 5.0, 7.0, 10.0, 14.0, 20.0, 28.0)

#: Shape, at last. Proportion alone is not enough: the booklet also outlines its
#: headings and the QR caption, and «إمسح على الباركود / للوصول للموقع» is two
#: lines of small paths in very nearly the lockup's proportion. Erasing it took
#: the caption off the contact page.
#:
#: So a candidate is compared with the others by silhouette, and the mark is
#: whichever shape *recurs*: it is on most pages of the booklet, and no heading
#: is. Nothing is declared -- there is no reference bitmap to keep in step with
#: a revised export -- and the numbers are wide apart. Measured on the hybrid
#: export: every one of the sixteen real marks has fifteen matches within 0.25,
#: and each of the three false positives has none, its nearest neighbour being
#: 0.357 away.
BRAND_SIGNATURE = (96, 28)
BRAND_INK_THRESHOLD = 90
BRAND_SAME_SHAPE = 0.25
BRAND_MIN_AGREEING = 3
#: The features page draws the lockup twice, slightly offset, so it reads a
#: little heavier than the rest. It is still the mark, and 0.30 admits it while
#: staying clear of the nearest thing that is not one.
BRAND_NEAR_SHAPE = 0.30

#: Slack around the mark when erasing it. The extent is grown from the mark's
#: own paths, so the space just outside it is the margin the designer left.
BRAND_ERASE_PAD = 2.0

#: Where the company's mark goes: the place the designer drew the selling
#: agent's lockup. The mark and nothing else — the guide's pages carry a logo
#: there, never a name set in type, so a company with no logo leaves it empty.
#:
#: The company's *name* has its own place in the design: the title on
#: تعريف وكيل البيع, which is where the guide prints it.
BRAND_LOGO_KEY = "company_logo"
BRAND_NAME_KEY = "company_name"


def _art_clusters(page: fitz.Page, gap: float = 6.0) -> list[tuple[fitz.Rect, int, str]]:
    """Small vector art on a page, grouped into the marks it is drawn as.

    Returns ``(box, paths, colour)`` per cluster, the colour being the fill of
    its largest path — which for a lockup is the colour its name is set in, and
    therefore the colour a name replacing it has to be.
    """
    limit_w = page.rect.width * BRAND_MAX_PATH_W
    limit_h = page.rect.height * BRAND_MAX_PATH_H
    items: list[tuple[fitz.Rect, str]] = []
    for drawing in page.get_drawings():
        rect = fitz.Rect(drawing["rect"])
        rect.normalize()
        if rect.is_infinite or rect.width > limit_w or rect.height > limit_h:
            continue
        paint = drawing.get("fill") or drawing.get("color")
        colour = (
            "#" + "".join(f"{round(c * 255):02X}" for c in paint[:3])
            if paint
            else "#000000"
        )
        items.append((rect, colour))

    groups: list[dict[str, Any]] = []
    for rect, colour in items:
        reach = fitz.Rect(rect.x0 - gap, rect.y0 - gap, rect.x1 + gap, rect.y1 + gap)
        touching = [g for g in groups if reach.intersects(g["box"])]
        if not touching:
            groups.append({"box": fitz.Rect(rect), "n": 1,
                           "paint": [(rect.get_area(), colour)]})
            continue
        first = touching[0]
        first["box"] |= rect
        first["n"] += 1
        first["paint"].append((rect.get_area(), colour))
        for other in touching[1:]:
            first["box"] |= other["box"]
            first["n"] += other["n"]
            first["paint"].extend(other["paint"])
            groups.remove(other)

    return [
        (g["box"], g["n"], max(g["paint"])[1])
        for g in groups
    ]


def _has_ink(page: fitz.Page, box: fitz.Rect) -> bool:
    """Whether anything is actually drawn there.

    ``get_drawings`` reports the paths inside a placed page as well, in the
    coordinates they had before it was placed — so the navy summary page, which
    carries the teal page's block as a form, reports a lockup in the middle of
    itself that nothing renders. Putting a company's logo on that ghost would
    print it in the middle of the table.
    """
    pixels = page.get_pixmap(clip=box, dpi=36)
    if not pixels.samples:
        return False
    first = pixels.samples[: pixels.n]
    return any(
        pixels.samples[i : i + pixels.n] != first
        for i in range(0, len(pixels.samples), pixels.n)
    )


def _brand_marks(page: fitz.Page) -> list[tuple[fitz.Rect, str]]:
    """Every place the selling agent's lockup sits on this page, and its colour.

    The contact page carries it twice — once in the masthead and once in the
    footer — so this returns a list rather than the first hit.
    """
    found: list[tuple[fitz.Rect, str]] = []
    for gap in BRAND_GAPS:
        for box, paths, colour in _art_clusters(page, gap=gap):
            if paths < BRAND_MIN_PATHS or not box.height:
                continue
            if abs(box.width / box.height - BRAND_ASPECT) > BRAND_ASPECT_TOLERANCE:
                continue
            if any(abs(box.x0 - b.x0) < 3 and abs(box.y0 - b.y0) < 3 for b, _ in found):
                continue
            if not _has_ink(page, box):
                continue
            found.append((box, colour))
    return found


def _silhouette(page: fitz.Page, box: fitz.Rect) -> list[int]:
    """A candidate mark reduced to ink or not-ink on a fixed grid.

    Normalised to one size, so the same lockup at 75pt and at 195pt compares
    equal; and to ink against whatever the local background is, so the white
    mark on a navy cover compares equal to the dark one on a white page.
    """
    width, height = BRAND_SIGNATURE
    matrix = fitz.Matrix(width / box.width, height / box.height)
    pixels = page.get_pixmap(clip=box, matrix=matrix)
    depth = pixels.n
    dots = [
        bytes(pixels.samples[i : i + depth])
        for i in range(0, len(pixels.samples), depth)
    ]
    if not dots:
        return []
    background = max(set(dots), key=dots.count)
    return [
        1
        if sum(abs(dot[c] - background[c]) for c in range(3)) > BRAND_INK_THRESHOLD
        else 0
        for dot in dots
    ]


def _shape_distance(a: list[int], b: list[int]) -> float:
    if not a or len(a) != len(b):
        return 1.0
    return sum(1 for x, y in zip(a, b, strict=True) if x != y) / len(a)


def _recurring(shapes: list[list[int]]) -> list[bool]:
    """Which candidates are the shape that keeps coming back.

    Two passes. The first keeps whatever agrees with several others -- that is
    the mark, because it is printed on most pages of the booklet. The second
    lets in a candidate that is close to one of those without having a crowd of
    its own, which is the page that draws the mark twice over itself.
    """
    agreed = [
        sum(
            1
            for j, other in enumerate(shapes)
            if j != i and _shape_distance(shape, other) < BRAND_SAME_SHAPE
        )
        >= BRAND_MIN_AGREEING
        for i, shape in enumerate(shapes)
    ]
    if not any(agreed):
        return agreed
    return [
        yes
        or any(
            _shape_distance(shape, shapes[j]) < BRAND_NEAR_SHAPE
            for j, other_yes in enumerate(agreed)
            if other_yes
        )
        for shape, yes in zip(shapes, agreed, strict=True)
    ]


def agent_silhouettes(doc: fitz.Document) -> list[list[int]]:
    """The shapes that recur across a whole export: its selling agent's mark.

    Read from the export itself rather than from the pages a template keeps, so
    that a page grafted out of it can still be told what its own lockup looks
    like.
    """
    candidates = [
        (index, box)
        for index in range(doc.page_count)
        for box, _ in _brand_marks(doc[index])
    ]
    if not candidates:
        return []
    shapes = [_silhouette(doc[i], box) for i, box in candidates]
    return [s for s, yes in zip(shapes, _recurring(shapes), strict=True) if yes]


def _rebrand(
    doc: fitz.Document,
    page_rect: fitz.Rect,
    page_source: list[str] | None = None,
    known_marks: dict[str, list[list[int]]] | None = None,
    bands: dict[int, tuple[tuple[float, float, float, float], ...]] | None = None,
) -> list[FieldSpec]:
    """Take the agent's fixed branding off every page and make it a field.

    The booklet is printed for whichever company is selling, so a mark belonging
    to one of them cannot be part of the artwork. It comes off — properly off,
    line art and all, which is the one place this build removes vector art and
    the reason the extent is taken from the mark's own paths — and its place
    becomes two fields at the same rect. There is no fallback to the old mark:
    a company with no logo prints its name, and a booklet with neither prints
    nothing there.

    ``page_source`` names the export each page came from, and the mark is looked
    for *within* each export rather than across the booklet. A template cut from
    one file does not notice the difference. One that grafts a few pages from
    another does: those pages carry a different agent's lockup, three of them
    against seventeen, and «the shape that recurs» is a test three pages cannot
    pass. Judged against its own export — where it is on every page — it is
    plainly the mark, and comes off like any other.
    """
    stated = bands or {}
    candidates: list[tuple[int, fitz.Rect, str]] = []
    for index in range(doc.page_count):
        if index in stated:
            # Declared pages are not searched: whatever is in the stated region
            # is the mark, and the automatic test has already been established
            # not to find it.
            continue
        for box, colour in _brand_marks(doc[index]):
            candidates.append((index, box, colour))

    declared: list[tuple[int, fitz.Rect, str]] = []
    for index, regions in stated.items():
        page = doc[index]
        for band in regions:
            region = fitz.Rect(
                band[0] * page_rect.width,
                band[1] * page_rect.height,
                band[2] * page_rect.width,
                band[3] * page_rect.height,
            )
            ink = fitz.Rect()
            for drawing in page.get_drawings():
                box = drawing["rect"]
                if box.is_empty:
                    continue
                # Mostly inside, not wholly inside. A path's reported extent
                # shifts by a few points between the export and the composed
                # document -- one letter of the wordmark reads x0=202.5 in the
                # file and 198.2 once placed -- so demanding containment left
                # it a fraction outside the region, out of the union, and
                # printed on the page as a grey speck. Requiring most of the
                # box instead still excludes anything that merely passes
                # through, such as a full-width rule sharing the footer.
                caught = box & region
                if caught.is_empty or caught.get_area() < box.get_area() * 0.6:
                    continue
                # ``Rect.__or__`` ignores an empty rect, so the extent is grown
                # by hand rather than unioned from nothing.
                ink = box if ink.is_empty else ink | box
            if ink.is_empty:
                raise MapError(
                    f"page {index}: nothing drawn inside the stated agent-mark "
                    f"region {tuple(round(v, 4) for v in band)} — the export "
                    f"has changed and the region has to be measured again"
                )
            # Erased by the region, placed by the ink.
            #
            # Redaction removes a path only when the rect covers it outright,
            # and it judges that against its own idea of the path's bounds,
            # which is not always the one ``get_drawings`` reports -- a letter
            # of the wordmark reported 4pt narrower than it was redacted as, so
            # the union built from those bounds did not quite cover it and it
            # survived as a grey speck. The region is declared, measured, and
            # contains nothing but the mark, so it is safe to clear whole. The
            # field still goes where the mark actually was.
            _erase_blocks(page, [region])
            declared.append((index, ink, ""))

    if not candidates and not declared:
        return []

    sources = page_source or [""] * doc.page_count
    known = known_marks or {}
    keep = [False] * len(candidates)
    for origin in {sources[i] if i < len(sources) else "" for i, _, _ in candidates}:
        group = [
            n
            for n, (i, _, _) in enumerate(candidates)
            if (sources[i] if i < len(sources) else "") == origin
        ]
        shapes = [_silhouette(doc[candidates[n][0]], candidates[n][1]) for n in group]
        if origin in known:
            # A grafted page is a handful out of a booklet, and «recurs» is a
            # test a handful cannot pass however plainly the mark is a mark. Its
            # own export settles it instead: the shape is looked up there, where
            # it is on every page, and matched here.
            verdicts = [
                any(
                    _shape_distance(shape, seen) < BRAND_SAME_SHAPE
                    for seen in known[origin]
                )
                for shape in shapes
            ]
        else:
            verdicts = _recurring(shapes)
        for n, yes in zip(group, verdicts, strict=True):
            keep[n] = yes
    marks = [c for c, yes in zip(candidates, keep, strict=True) if yes] + declared

    # Padded, because "covered" is judged strictly: the hamza of the wordmark
    # begins on the extent's own top edge, so it was left behind as a speck in
    # the middle of an otherwise empty footer.
    by_page: dict[int, list[fitz.Rect]] = defaultdict(list)
    for index, box, _ in marks:
        by_page[index].append(
            fitz.Rect(
                box.x0 - BRAND_ERASE_PAD,
                box.y0 - BRAND_ERASE_PAD,
                box.x1 + BRAND_ERASE_PAD,
                box.y1 + BRAND_ERASE_PAD,
            )
        )
    for index, boxes in by_page.items():
        _erase_blocks(doc[index], boxes)

    specs: list[FieldSpec] = []
    for index, box, colour in marks:
        specs.extend(_brand_fields(index, box, colour, page_rect))
    return specs


def _brand_fields(
    index: int, box: fitz.Rect, colour: str, page_rect: fitz.Rect
) -> list[FieldSpec]:
    """The company's mark, where the agent's used to be."""
    del colour  # the mark carries its own; only a name would need the page's
    return [
        FieldSpec(
            key=BRAND_LOGO_KEY,
            page_index=index,
            rect=NormRect.from_points(box, page_rect),
            type=FieldType.IMAGE,
            label="شعار الشركة",
            preserve_aspect=True,
            origin="rule:company_logo/brand-mark",
        )
    ]


# --------------------------------------------------------- cover captions

#: The caption the brand guide prints above the date on the cover. Written out
#: here only so it can be *redrawn* where the designer left it out; nothing
#: reads a printed string to decide anything.
DATE_CAPTION = "تاريخ المزاد"


def _white_runs(candidates: list[DerivedField]) -> list[DerivedField]:
    """The cover's white text runs, in the order the cover rules index them."""
    return [
        f
        for f in candidates
        if f.type is FieldType.TEXT and f.color == "#FFFFFF" and not _is_heading(f)
    ]


def _draw_date_captions(
    doc: fitz.Document,
    positions: list[int],
    derived: dict[int, list[DerivedField]],
    specs: list[FieldSpec],
    page_rect: fitz.Rect,
) -> list[int]:
    """Give every cover the printed «تاريخ المزاد» the guide shows above the date.

    Four of the six covers carry it; غلاف 4 and غلاف 5 were exported without it,
    so the same booklet printed on two covers of the same family read
    differently. The four that have it supply the geometry for the two that do
    not -- the caption's offset above the date line, its height, and the size,
    weight and colour the designer set it in -- so what is drawn is measured off
    the artwork rather than chosen.

    Drawn before ``source.pdf`` is written, so a later re-publish from the
    unbaked original keeps it, and above the date field's box, so baking does
    not clear it again. Returns the pages it had to draw on.
    """
    runs: dict[int, list[fitz.Rect]] = {}
    donors: list[tuple[DerivedField, list[fitz.Rect]]] = []
    for position in positions:
        white = _white_runs(derived.get(position, []))
        if len(white) < 2:
            continue
        rows = _text_rows(white[1])
        runs[position] = rows
        if len(rows) > 1:
            donors.append((white[1], rows))

    if not donors:
        return []
    donor, donor_rows = donors[0]
    caption, date_line = donor_rows[-2], donor_rows[-1]
    lift = caption.y0 - date_line.y0
    height = caption.height

    registry = brand_registry()
    drawn: list[int] = []
    for position, rows in runs.items():
        if len(rows) > 1:
            continue
        line = rows[-1]
        box = fitz.Rect(line.x0, line.y0 + lift, line.x1, line.y0 + lift + height)
        calibrated_htmlbox(
            doc[position], box, DATE_CAPTION,
            registry=registry,
            family=donor.font_family,
            weight=donor.font_weight,
            size_pt=donor.font_size_pt,
            color=donor.color,
            align=Align.CENTER,
            fit=Fit.SHRINK,
        )
        drawn.append(position)

        # The date field now has a caption above it on this cover too, so its
        # box has to clear the caption the way it does on the four that were
        # exported with one.
        for spec in specs:
            if spec.page_index != position or spec.key != "auction_date_block":
                continue
            rect = spec.rect.to_points(page_rect)
            rect.y0 = max(rect.y0, box.y1 + CAPTION_CLEARANCE)
            rect.y1 = max(rect.y0 + 1.0, line.y1)
            spec.rect = NormRect.from_points(rect, page_rect)
            spec.origin += "/caption-drawn"
    return drawn


# ------------------------------------------------------------ table pages


def _table_specs(
    doc: fitz.Document,
    page_index: int,
    page_rect: fitz.Rect,
    label: str,
    *,
    blocks: list | None = None,
    continuous: bool = True,
) -> tuple[list[FieldSpec], list[fitz.Rect]]:
    """Recover a page's repeating table as one field per block.

    A table is one field per block, never one per printed cell: the renderer
    walks the rows itself.

    ``continuous`` says whether a second block carries on where the first left
    off. It does on the lease table, which is one table drawn in two halves. It
    does *not* on the summary page, whose two blocks are the same ten rows drawn
    twice in two colourways -- see ``_colourways``.
    """
    specs: list[FieldSpec] = []
    cells: list[fitz.Rect] = []
    offset = 0
    for block_no, block in enumerate(
        derive_tables(doc, page_index) if blocks is None else blocks
    ):
        payload = to_norm(block, page_rect)
        body = block.first_row_pt | block.row_rect(block.rows - 1)
        specs.append(
            FieldSpec(
                key=f"__table__{page_index}_{block_no}",
                page_index=page_index,
                rect=NormRect.from_points(body, page_rect),
                type=FieldType.TABLE,
                label=label,
                origin=f"table:block={block_no}/rows={block.rows}",
                table=TableSpec(
                    columns=[
                        TableColumn(
                            key=c["key"],
                            rect=NormRect(**c["rect"]),
                            label=c["label"],
                            align=Align(c["align"]),
                            font_family=c["font_family"],
                            font_weight=c["font_weight"],
                            font_size_pt=c["font_size_pt"],
                            color=c["color"],
                            fit=Fit(c["fit"]),
                            source=c["source"],
                        )
                        for c in payload["columns"]
                    ],
                    rows=payload["rows"],
                    row_pitch=payload["row_pitch"],
                    row_offset=offset,
                ),
            )
        )
        cells.extend(block.cell_rects())
        if continuous:
            offset += block.rows
    return specs, cells


#: What the lease table's nine columns hold, right to left, as the guide prints
#: them. Declared because the printed headers are outlined -- there is no text
#: to read them from, which is the same reason the page needed rebuilding at
#: all. Getting the order wrong puts the rent under «حالة العقد», so the order
#: is the order the sample row's own cells sit in.
LEASE_COLUMNS: tuple[tuple[str, str], ...] = (
    ("lease_property_type", "نوع العقار"),
    ("lease_unit_number", "رقم الوحدة"),
    ("lease_status", "حالة العقد"),
    ("lease_start", "تاريخ بداية العقد"),
    ("lease_end", "تاريخ نهاية العقد"),
    ("lease_annual_rent", "إجمالي قيمة الإيجار السنوي"),
    ("lease_term", "مدة العقد"),
    ("lease_paid_term", "المدة الايجارية المسددة للمالك الحالي"),
    ("lease_next_due", "الاستحقاق القادم لمبلغ الايجار"),
)


#: The two colours this brand sets a table in, as the page writes them. The
#: lease page is drawn in the navy only, and the summary page proves both are
#: the brand's -- so the other one is offered by rewriting the colour the page
#: itself asks for, not by drawing anything new. Every rule, bar and tab moves
#: together, and the outlined headers printed over them are untouched.
LEASE_NAVY = ("0", ".212", ".365")
LEASE_TEAL = (".235", ".745", ".733")


def _recoloured_lease_page(doc: fitz.Document, position: int) -> int | None:
    """The lease page again, in the other brand colour.

    A copy whose content stream asks for teal wherever it asked for navy. The
    headers printed on the bar are outlined art sitting *over* it, and a
    substitution leaves them exactly where they are -- which is the whole reason
    for doing it this way rather than erasing the bar and drawing a new one.
    """
    doc.fullcopy_page(position)
    index = doc.page_count - 1
    page = doc[index]
    page.clean_contents()
    streams = page.get_contents()
    if not streams:
        return None

    navy = " ".join(LEASE_NAVY).encode("latin-1")
    teal = " ".join(LEASE_TEAL).encode("latin-1")
    touched = 0
    for xref in streams:
        data = doc.xref_stream(xref)
        if navy not in data:
            continue
        doc.update_stream(xref, data.replace(navy, teal))
        touched += 1
    if not touched:
        raise MapError(
            f"page {position}: the lease table is not drawn in the colour the "
            f"map expects, so the other colourway cannot be offered"
        )
    return index


#: The three things the lease page names above its table, right to left. Their
#: labels are outlined, so they are found as art rather than read; each value
#: goes in the gap to the *left* of its own label, which is where the printed
#: slash points.
LEASE_HEADINGS: tuple[tuple[str, str], ...] = (
    ("lease_book_number", "رقم العقار في كتيب المزاد"),
    ("lease_deed_number", "الصك رقم"),
    ("lease_property_name", "إسم العقار"),
)
LEASE_HEADING_BAND = (0.09, 0.15)
LEASE_HEADING_GAP = 6.0


def _lease_headings(
    page: fitz.Page, page_rect: fitz.Rect
) -> list[FieldSpec]:
    """Somewhere to write the three things named above the table."""
    labels = sorted(
        (
            box
            for box, _, _ in _art_clusters(page, gap=6.0)
            if LEASE_HEADING_BAND[0] * page_rect.height <= box.y0
            and box.y1 <= LEASE_HEADING_BAND[1] * page_rect.height
        ),
        key=lambda box: -box.x1,
    )
    if len(labels) != len(LEASE_HEADINGS):
        return []

    specs: list[FieldSpec] = []
    for index, (label, (key, name)) in enumerate(
        zip(labels, LEASE_HEADINGS, strict=True)
    ):
        # As far left as the label beyond it, or the page's own margin.
        limit = (
            labels[index + 1].x1 + LEASE_HEADING_GAP
            if index + 1 < len(labels)
            else labels[-1].x0 - (labels[0].x1 - labels[0].x0) * 3
        )
        box = fitz.Rect(
            max(page_rect.x0, limit),
            label.y0 - 2.0,
            label.x0 - LEASE_HEADING_GAP,
            label.y1 + 2.0,
        )
        if box.width < 20:
            continue
        specs.append(
            FieldSpec(
                key=key,
                page_index=page.number,
                rect=NormRect.from_points(box, page_rect),
                type=FieldType.TEXT,
                label=name,
                align=Align.RIGHT,
                font_size_pt=8.5,
                color=BODY,
                fit=Fit.SHRINK,
                origin=f"rule:{key}/lease-heading",
            )
        )
    return specs


def _uniform_table(
    page: fitz.Page,
    page_rect: fitz.Rect,
    label: str,
    names: tuple[tuple[str, str], ...] = (),
) -> tuple[FieldSpec | None, list[fitz.Rect]]:
    """Recover a table whose printed headers were converted to outlines.

    ``derive_tables`` recognises a table by reading its header row. The lease
    table has no readable headers, so it is not recognised -- and a page that is
    not recognised is a page the bake cannot clear and the builder cannot fill.

    Its geometry is nonetheless completely regular: a white row number down one
    edge at an even pitch, and a sample row whose cells mark the columns. That
    is enough to rebuild the block from the artwork alone.

    The columns are left unnamed on purpose. Their headers are unreadable, and
    guessing names from a sample value is the one thing derivation must never
    do; the template editor is where an admin names them.
    """
    numbers: list[fitz.Rect] = []
    cells: list[tuple[fitz.Rect, dict]] = []
    for block in page.get_text("dict")["blocks"]:
        if block.get("type") != 0:
            continue
        for line in block["lines"]:
            for span in line["spans"]:
                text = span["text"].strip()
                if not text:
                    continue
                rect = fitz.Rect(span["bbox"])
                if span.get("color") == 0xFFFFFF and text.isdigit():
                    numbers.append(rect)
                elif span.get("color") != 0xFFFFFF and span["size"] < 9.5:
                    cells.append((rect, span))

    if len(numbers) < 6 or not cells:
        return None, []

    numbers.sort(key=lambda r: r.y0)
    pitches = [b.y0 - a.y0 for a, b in pairwise(numbers)]
    pitches.sort()
    pitch = pitches[len(pitches) // 2]
    if pitch <= 0:
        return None, []

    first_top = numbers[0].y0
    row_band = (first_top - pitch * 0.25, first_top + pitch * 0.9)
    row_one = [
        (rect, span) for rect, span in cells if row_band[0] <= rect.y0 <= row_band[1]
    ]
    if len(row_one) < 3:
        return None, []

    row_one.sort(key=lambda item: -item[0].x1)
    centres = [numbers[0].x0 + numbers[0].width / 2] + [
        r.x0 + r.width / 2 for r, _ in row_one
    ]
    edges = [(a + b) / 2 for a, b in pairwise(centres)]
    height = max(r.height for r, _ in row_one) * 1.6
    top = first_top - (height - numbers[0].height) / 2

    columns: list[TableColumn] = []
    column_rects: list[fitz.Rect] = []
    for position, centre in enumerate(centres):
        right = edges[position - 1] if position else centre + (centre - edges[0])
        left = edges[position] if position < len(edges) else centre - (
            centres[-2] - centre if len(centres) > 1 else 20.0
        )
        box = fitz.Rect(min(left, right), top, max(left, right), top + height)
        column_rects.append(box)
        sample = row_one[position - 1][1] if position else None
        columns.append(
            TableColumn(
                key=(
                    "__index__" if position == 0
                    else names[position - 1][0] if position - 1 < len(names)
                    else f"rent_{position}"
                ),
                rect=NormRect.from_points(box, page_rect),
                label=(
                    "#" if position == 0
                    else names[position - 1][1] if position - 1 < len(names)
                    else ""
                ),
                align=Align.CENTER,
                font_family="LamaSans" if position == 0 else "RuaqArabic",
                font_weight="Regular" if position == 0 else "Medium",
                font_size_pt=(
                    round(numbers[0].height * 0.9, 2) if sample is None
                    else round(sample["size"], 2)
                ),
                color="#FFFFFF" if position == 0 else BODY,
                fit=Fit.SHRINK,
                source="__index__" if position == 0 else "",
            )
        )

    body = column_rects[0] | column_rects[-1]
    body.y1 = top + height + pitch * (len(numbers) - 1)
    # «بيان عقود الإيجار» shrinks to its leases the same way «بيان العقارات»
    # shrinks to its properties. It reaches this function rather than the
    # derived path only because its column headers are outlined, which changes
    # how the block is *found*, not what it is: nineteen ruled rows, eight
    # dividers and a numbered tab, all of it the designer's line art and all of
    # it lifted onto the field so the block can end at the last lease.
    frame = _lift_frame(
        page, page_rect, body, pitch=pitch, rows=len(numbers)
    )
    spec = FieldSpec(
        key=f"__table__{page.number}_0",
        page_index=page.number,
        rect=NormRect.from_points(body, page_rect),
        type=FieldType.TABLE,
        label=label,
        origin=f"table:uniform/rows={len(numbers)}",
        table=TableSpec(
            columns=columns,
            rows=len(numbers),
            row_pitch=pitch / page_rect.height,
            row_offset=0,
            frame=frame,
        ),
    )

    clear: list[fitz.Rect] = []
    for row in range(len(numbers)):
        shift = pitch * row
        for box in column_rects:
            clear.append(box + (0, shift, 0, shift))
    return spec, clear


#: The slot the two summary-page colourways share, the way the six covers share
#: theirs and the two lot layouts share theirs.
TABLE_SLOT = "lot_table"

#: The slot the lease page's two colourways share.
LEASE_SLOT = "rent_table"

#: Where «بيان العقارات» sits in both exports. Declared, like every other page
#: role, rather than searched for.
LOT_TABLE_SOURCE_PAGE = 4

#: A drawing bigger than this fraction of the page is the page's own background,
#: not part of a table block, and must not be swept into a block's extent.
BACKDROP_AREA = 0.55


#: How far above the first row the header bar sits, and how far below the last
#: the numbered tab runs, both in row pitches. Two and one clear the designer's
#: own margins on every export, and stop short of the next block's header.
BLOCK_HEAD_PITCHES = 2.0
BLOCK_FOOT_PITCHES = 1.0


def _block_extents(page: fitz.Page, blocks: list, page_rect: fitz.Rect) -> list[fitz.Rect]:
    """Everything the designer drew for each table block.

    The field rect is the body -- the rows a value lands in. The *block* is more
    than that: the coloured header bar above it, the numbered tab down its edge,
    and the hairlines ruling the rows. Removing a colourway, or placing one, is
    all of that or none of it.

    Hairlines are why this cannot simply grow from the body outward by contact:
    a rule drawn as a stroke has a zero-width rect, an empty ``fitz.Rect``, and
    the header bar sits ten points clear of the tab below it, so nothing touches
    anything. The band around each block is taken from its own row pitch
    instead, which the artwork gives exactly.
    """
    extents: list[fitz.Rect] = []
    for block in blocks:
        body = fitz.Rect(block.first_row_pt)
        for row in range(block.rows):
            body |= block.row_rect(row)
        extents.append(_extent_around(page, body, block.row_pitch, page_rect))
    return extents


def _extent_around(
    page: fitz.Page, body: fitz.Rect, pitch: float, page_rect: fitz.Rect
) -> fitz.Rect:
    """Everything the designer drew around one block of rows.

    Split out of ``_block_extents`` because «بيان عقود الإيجار» needs one too
    and has no derived block to ask: its column headers are outlined, so
    ``derive_tables`` never sees it and the build measures it from its printed
    row numbers instead. The band is the same either way -- two pitches above
    the first row for the header bar, one below the last for the numbered tab.
    """
    ceiling = body.y0 - pitch * BLOCK_HEAD_PITCHES
    floor = body.y1 + pitch * BLOCK_FOOT_PITCHES
    box = fitz.Rect(body)
    for drawing in page.get_drawings():
        rect = fitz.Rect(drawing["rect"])
        rect.normalize()
        if rect.get_area() > page_rect.get_area() * BACKDROP_AREA:
            continue
        if rect.y0 < ceiling or rect.y1 > floor:
            continue
        if rect.x1 < body.x0 - 2 or rect.x0 > body.x1 + 2:
            continue
        box |= rect
    return box


#: The two colours the summary table is drawn in, sampled from the fill behind
#: each block's header row. Teal first, navy second, which is how the guide lays
#: the specimen out.
COLOURWAY_TEAL = (0x37, 0xBE, 0xBC)
COLOURWAY_NAVY = (0x00, 0x17, 0x47)
#: Wide enough for a rasteriser's rounding, far narrower than the 167 that
#: separates the two, so a swap cannot pass as a match.
COLOURWAY_TOLERANCE = 60


def _header_colour(page: fitz.Page, block) -> tuple[int, int, int]:
    """The colour of the bar above a block, read off the page.

    Sampled rather than declared: the bar is the one thing that tells the two
    blocks apart, and reading it is the same act as reading the geometry.
    """
    body = fitz.Rect(block.first_row_pt)
    bar = fitz.Rect(
        body.x0 + body.width * 0.4,
        body.y0 - block.row_pitch * 1.4,
        body.x0 + body.width * 0.4 + 4,
        body.y0 - block.row_pitch * 0.9,
    )
    pixels = page.get_pixmap(clip=bar, dpi=72)
    return tuple(pixels.pixel(pixels.width // 2, pixels.height // 2)[:3])


def _colourways(doc: fitz.Document, page_index: int, page_rect: fitz.Rect) -> list:
    """The summary table's blocks, which are colourways rather than a sequence.

    The brand guide's blank specimen numbers the teal block 01-08 and the navy
    block 01-08 -- both restart -- and the worked example repeats the same ten
    sample rows in both. Its own instruction for a long list is «فيتم تكرار
    الصفحة»: repeat the page. So a page holds ten rows in one of two colours,
    not twenty in two halves, and the earlier build printed rows 11-20 into a
    block the design never meant to carry them.

    Returned teal first, navy second, and *checked* -- ``derive_tables`` bands
    its header spans in the order the export wrote them, which happens to be top
    to bottom today. A revision that reorders them would otherwise build a page
    labelled أزرق out of the teal block, and nothing downstream would notice.
    """
    blocks = derive_tables(doc, page_index)
    page = doc[page_index]
    expected = (COLOURWAY_TEAL, COLOURWAY_NAVY)
    for index, block in enumerate(blocks[: len(expected)]):
        found = _header_colour(page, block)
        want = expected[index]
        if max(abs(a - b) for a, b in zip(found, want, strict=True)) > (
            COLOURWAY_TOLERANCE
        ):
            raise MapError(
                f"summary block {index} on page {page_index} has a "
                f"{found} header bar, expected {want}: the export has "
                f"reordered its colourways"
            )
    return blocks


def _navy_colourway(page_rect: fitz.Rect) -> tuple[fitz.Document, fitz.Rect] | None:
    """The navy summary block, sample rows cleared, ready to be placed.

    Only the حضوري export draws both colourways; the إلكتروني/هجين export ships
    the teal one alone. Rather than recolour teal artwork into navy -- inventing
    a design the designer did not draw -- the navy block is lifted from the
    export that has it. Same page size, same nine columns at the same x, same
    brand: it is the designer's block either way.

    Its sample rows are cleared here, before it is placed. Not because they
    could not be reached afterwards -- redaction does reach into a placed form,
    which is how ``_erase_frame`` takes the ruling off this very page -- but
    because clearing them at the source is one pass over a page whose
    coordinates are its own, rather than a second pass over a form's.

    Named, not counted. The electronic booklet is also sixteen pages, and asking
    for "the sixteen-page export" fetched it instead — it draws the teal block
    alone, so the pair silently became a single page and بيان العقارات lost the
    slot that makes the two colourways a choice.
    """
    source = _find_source(16, IN_PERSON_EXPORT)
    if source is None:
        return None
    with fitz.open(source) as export:
        blocks = derive_tables(export, LOT_TABLE_SOURCE_PAGE)
        if len(blocks) < 2:
            return None
        extent = _block_extents(
            export[LOT_TABLE_SOURCE_PAGE], blocks, export[0].rect
        )[1]
        scratch = fitz.open()
        scratch.insert_pdf(
            export,
            from_page=LOT_TABLE_SOURCE_PAGE,
            to_page=LOT_TABLE_SOURCE_PAGE,
        )
    page = scratch[0]
    for cell in blocks[1].cell_rects():
        page.add_redact_annot(cell)
    page.apply_redactions(
        images=fitz.PDF_REDACT_IMAGE_NONE,
        graphics=fitz.PDF_REDACT_LINE_ART_NONE,
    )
    return scratch, extent


#: A drawn shape flatter than this is one of the rules closing a row, not a
#: divider running down the block. The rules are hairlines a fraction of a point
#: thick and the shortest divider is two hundred and sixty points tall, so
#: nothing sits anywhere near the boundary.
RULE_MAX_HEIGHT = 1.0


def _ink(colour: Any) -> list[float] | None:
    """A drawing's colour as the PDF states it, or ``None`` for no colour.

    Kept in the file's own components rather than folded to a hex triple. The
    tab's teal is 0.749 green -- 190.995 of 255 -- and a table redrawn from the
    byte that survives the trip comes out a step lighter than the artwork it
    sits in.
    """
    if not colour:
        return None
    return [float(c) for c in colour[:3]]


def _frame_paths(
    page: fitz.Page,
    page_rect: fitz.Rect,
    extent: fitz.Rect,
    *,
    top: float,
    pitch: float,
    rows: int,
) -> tuple[list[dict], fitz.Rect] | None:
    """The line art a table block is ruled with, and the region it occupies.

    The frame is everything the designer drew from the top of the first row
    downward: the rules closing each row, the dividers between the columns, and
    the numbered tab down the edge. What sits above that line is the block's
    header bar, with the column titles outlined into it -- design that does not
    move when the table gets shorter, and is left exactly where it is.

    The block extent bounds the search, which is what keeps the navy page
    honest. Its artwork is placed as a form carrying the whole of the page it
    was lifted from, so ``get_drawings`` reports a second, clipped-away copy of
    every shape 340.91pt above the visible one. Those fall outside the extent
    and are neither captured nor erased -- they are invisible, and taking them
    off would be a change to a page nobody asked us to touch.

    ``None`` where the block does not look like the one that was measured, which
    leaves the table the fixed height it has always been rather than redrawing
    it from a guess.
    """
    grown = extent + (-1, -1, 1, 1)
    found: list[dict] = []
    for drawing in page.get_drawings():
        rect = fitz.Rect(drawing["rect"])
        rect.normalize()
        if rect.get_area() > page_rect.get_area() * BACKDROP_AREA:
            continue
        if rect.x0 < grown.x0 or rect.x1 > grown.x1:
            continue
        if rect.y0 < grown.y0 or rect.y1 > grown.y1:
            continue
        if rect.y1 <= top:
            continue  # the header bar and its titles: above the first row
        found.append(drawing)
    if not found:
        return None

    rules = sorted(
        (d for d in found if fitz.Rect(d["rect"]).height <= RULE_MAX_HEIGHT),
        key=lambda d: fitz.Rect(d["rect"]).y0,
    )
    # A rule per row, and at most one more. «بيان العقارات» rules ten bands for
    # its ten rows; «بيان عقود الإيجار» rules twenty and numbers nineteen, and
    # that twentieth is the block's bottom edge rather than a row anyone can
    # fill. Any other count means this is not the block the geometry was read
    # from, and a table redrawn from a misread frame is worse than one that
    # never shrinks.
    if not rows <= len(rules) <= rows + 1:
        return None
    # Each rule has to fall in the band of the row it is taken to close, or the
    # reading is off by one somewhere and every short table would be ruled in
    # the wrong places.
    for row, rule in enumerate(rules[:rows]):
        want = top + (row + 1) * pitch
        if abs(fitz.Rect(rule["rect"]).y0 - want) > pitch / 2:
            return None

    # Measured by hand rather than by unioning the rects. A rule is a stroke,
    # and a stroke's rect is degenerate -- zero wide down a column divider, zero
    # high along a row rule -- which makes it an empty ``fitz.Rect``, and
    # ``Rect.__or__`` ignores an empty rect. Unioned, the region came out as the
    # numbered tab alone: the tab was lifted off the artwork and all seventeen
    # rules stayed exactly where they were, so the redraw landed on top of them
    # and the lines printed a third too dark.
    boxes = [fitz.Rect(d["rect"]) for d in found]
    region = fitz.Rect(
        min(min(b.x0, b.x1) for b in boxes),
        min(min(b.y0, b.y1) for b in boxes),
        max(max(b.x0, b.x1) for b in boxes),
        max(max(b.y0, b.y1) for b in boxes),
    )
    return found, region


def _capture_frame(
    page: fitz.Page,
    page_rect: fitz.Rect,
    extent: fitz.Rect,
    *,
    top: float,
    pitch: float,
    rows: int,
) -> TableFrame | None:
    """Lift a block's ruling off the page, so the renderer can put back as much
    of it as the auction has rows to fill.

    Recorded as the designer's own segments -- lines and bezier curves, in the
    order they were drawn, in the colour and stroke width they were drawn in.
    The numbered tab is a notched shape with rounded corners, and a table that
    shrank by redrawing it as a rectangle would be a different design.
    """
    caught = _frame_paths(
        page, page_rect, extent, top=top, pitch=pitch, rows=rows
    )
    if caught is None:
        return None
    found, _ = caught

    def norm_x(value: float) -> float:
        return (value - page_rect.x0) / page_rect.width

    def norm_y(value: float) -> float:
        return (value - page_rect.y0) / page_rect.height

    rule_order = sorted(
        (
            index
            for index, d in enumerate(found)
            if fitz.Rect(d["rect"]).height <= RULE_MAX_HEIGHT
        ),
        key=lambda index: fitz.Rect(found[index]["rect"]).y0,
    )
    # Rule k closes row k, read in the rules' own order down the page rather
    # than matched against a pitch: the designer's steps are not all equal, and
    # only the sequence says which rule belongs to which row. ``_frame_paths``
    # has already checked that each one lands in its row's band.
    row_of = {index: row for row, index in enumerate(rule_order[:rows])}
    rules = [
        norm_y(fitz.Rect(found[index]["rect"]).y0) for index in rule_order[:rows]
    ]
    # The block's drawn bottom edge: the last rule on the page, which is the
    # last row's on «بيان العقارات» and one unnumbered band lower on the lease
    # page. The dividers and the tab are drawn to this line, so it is what
    # shortening measures from -- and where it is not a row's rule it is not
    # redrawn at all, because an unnumbered band is an empty row.
    bottom = norm_y(fitz.Rect(found[rule_order[-1]]["rect"]).y0)
    trailing = set(rule_order[rows:])

    paths: list[FramePath] = []
    for index, drawing in enumerate(found):
        if index in trailing:
            continue
        path = _frame_path_from(drawing, page_rect, row=row_of.get(index))
        if path is None:
            # A quad, or anything else the designer did not use here. Leaving
            # the block alone beats redrawing it with a piece missing.
            return None
        paths.append(path)
    return TableFrame(rules=rules, paths=paths, bottom=bottom)


def _frame_path_from(
    drawing: dict, page_rect: fitz.Rect, *, row: int | None = None
) -> FramePath | None:
    """One drawn shape as the segments and the ink the file states it in.

    Shared by the table frames and by the marks lifted off a chip: both are
    recordings of the designer's own drawing, to be put back where they were,
    and a second reading of the same thing would be a second way of drawing it.

    ``None`` where the shape uses a segment this cannot record, so the caller
    can leave the artwork alone rather than redraw it with a piece missing.
    """
    def norm_x(value: float) -> float:
        return (value - page_rect.x0) / page_rect.width

    def norm_y(value: float) -> float:
        return (value - page_rect.y0) / page_rect.height

    items: list[FrameItem] = []
    for item in drawing["items"]:
        kind = item[0]
        if kind == "l":
            corners = [item[1], item[2]]
        elif kind == "c":
            corners = [item[1], item[2], item[3], item[4]]
        elif kind == "re":
            box = fitz.Rect(item[1])
            corners = [
                fitz.Point(box.x0, box.y0), fitz.Point(box.x1, box.y0),
                fitz.Point(box.x1, box.y1), fitz.Point(box.x0, box.y1),
                fitz.Point(box.x0, box.y0),
            ]
            kind = "l"
        else:
            return None
        flat: list[float] = []
        for point in corners:
            flat.extend((norm_x(point.x), norm_y(point.y)))
        if kind == "l":
            for start in range(0, len(flat) - 2, 2):
                items.append(FrameItem("l", flat[start : start + 4]))
        else:
            items.append(FrameItem(kind, flat))
    return FramePath(
        items=items,
        stroke=_ink(drawing.get("color")),
        fill=_ink(drawing.get("fill")),
        width=float(drawing.get("width") or 0.0),
        closed=bool(drawing.get("closePath")),
        row=row,
    )


#: A mark belongs to the value it stands beside, and no further away than this.
#:
#: Measured on معلومات التواصل, where the gap between a number's last digit and
#: its icon is 14pt on one chip and 23pt on the other. Forty leaves room for the
#: designer's own variation and stops well short of the next chip, whose value
#: begins 55pt further along.
MARK_REACH = 40.0

#: The marks the designer draws beside a value, which have to come and go with
#: it. ``group`` names the centred row the values sit in.
#:
#: Only معلومات التواصل, and only its two telephone numbers. «إذا واتساب not
#: exist رقم التواصل align center and icon of واتساب disappear» is the whole
#: requirement, and it cannot be met while the icon is ink on the page: the
#: number was a field and the mark above it was not, so a seller with no
#: WhatsApp printed a WhatsApp mark with nothing beside it.
#: How far above a value the designer sets the mark that names it.
#:
#: معلومات التواصل stands each of its facts under an icon rather than beside
#: one: measured on the artwork, the icons occupy y 351.8-370.8 and the values
#: begin at 380.4, so the gap is under ten points. Forty leaves room for the
#: designer's variation and stops well short of «يقام المزاد» above the row.
MARK_RISE = 40.0

#: A mark may overhang its value by this much and still belong to it. The
#: platform's value is the narrowest chip on the page at 56pt and its icon is
#: 20pt, so nothing here needs the slack; it is there so a client's short value
#: does not orphan an icon the designer centred on a longer sample.
MARK_DRIFT = 12.0

#: How much room a mark's region is given when it is taken off the artwork.
#:
#: Not a tolerance on where the mark is -- a measure of what «covered» means to
#: a stroke. MuPDF will only remove line art a redaction covers whole, and it
#: measures a stroked path by more than the rectangle ``get_drawings`` reports:
#: the mitred joins of the platform icon's 0.5pt strokes reach beyond their own
#: bounds, and three of its shapes survived every redaction drawn a point
#: around them. Measured on that icon: all of it comes away at five points,
#: nothing more comes away at seven.
MARK_BLEED = 6.0

#: The marks the designer draws beside a value, which have to come and go with
#: it. ``group`` names the centred row the values sit in; ``where`` is which
#: side of the value the designer put the mark on, and ``spread`` says the row
#: is to be spaced evenly across what it was drawn across.
#:
#: The two telephone numbers, on all three cards. «إذا واتساب not exist رقم
#: التواصل align center and icon of واتساب disappear» is the whole requirement,
#: and it cannot be met while the icon is ink on the page: the number was a
#: field and the mark above it was not, so a seller with no WhatsApp printed a
#: WhatsApp mark with nothing beside it.
#:
#: And the fact chips, on the electronic card only. That card is the هجين
#: drawing with «الموقع» taken off it, which left three chips standing at four
#: chips' spacing and a hole in the middle of the row. الهجين draws four and
#: حضوري draws three and both are the designer's own rows, spaced as they were
#: drawn -- so neither is touched here, and only the card we cut a chip out of
#: is spaced again.
MARKED_CHIPS: dict[str, tuple[dict[str, Any], ...]] = {
    "contact": (
        {
            "group": "contact_numbers",
            "keys": ("contact_whatsapp", "contact_phone"),
        },
    ),
    "contact_electronic": (
        {
            "group": "contact_numbers",
            "keys": ("contact_whatsapp", "contact_phone"),
        },
        {
            "group": "contact_facts",
            "keys": ("platform_name", "auction_date", "auction_time"),
            "where": "above",
            "spread": True,
        },
    ),
    "contact_inperson": (
        {
            "group": "contact_numbers",
            "keys": ("contact_whatsapp", "contact_phone"),
        },
    ),
}


def _mark_beside(page: fitz.Page, box: fitz.Rect) -> list[dict]:
    """The shapes the designer set immediately to the right of a value.

    Each of these icons sits to the right of its own number — the handset at
    x=268 belongs to the number ending at 254, the WhatsApp bubble at 422 to
    the number ending at 399 — which is where a mark goes in a right-to-left
    line. Bounded by ``MARK_REACH`` so a chip can never claim its neighbour's.
    """
    window = fitz.Rect(box.x1, box.y0 - 6.0, box.x1 + MARK_REACH, box.y1 + 6.0)
    return _shapes_in(page, window, MARK_REACH)


def _mark_above(page: fitz.Page, box: fitz.Rect) -> list[dict]:
    """The shapes the designer set immediately above a value.

    معلومات التواصل names its four facts this way rather than the way it names
    its telephone numbers: a clock over the hours, a calendar over the date, a
    pin over the venue, a laptop over the platform. The window is the value's
    own column, widened by ``MARK_DRIFT`` so a mark centred on a longer sample
    still belongs to the value beneath it, and reaching no further up than
    ``MARK_RISE`` so it can never claim the heading above the row.
    """
    window = fitz.Rect(
        box.x0 - MARK_DRIFT,
        box.y0 - MARK_RISE,
        box.x1 + MARK_DRIFT,
        box.y0,
    )
    return _shapes_in(page, window, MARK_REACH)


def _shapes_in(page: fitz.Page, window: fitz.Rect, limit: float) -> list[dict]:
    """Every drawn shape wholly inside ``window`` and no wider than ``limit``.

    The size bound is what stops a mark's window from swallowing a rule or a
    panel that happens to pass through it.
    """
    found = []
    for drawing in page.get_drawings():
        rect = fitz.Rect(drawing["rect"])
        rect.normalize()
        if rect.is_empty or rect.width > limit:
            continue
        if window.contains(rect):
            found.append(drawing)
    return found


def _lift_marks(
    page: fitz.Page,
    page_rect: fitz.Rect,
    specs: list[FieldSpec],
    plan: dict[str, Any],
) -> None:
    """Take each chip's mark off the artwork and hang it on its own field.

    The same act as ``_erase_frame`` and for the same reason: the drawing is
    going to be put back, by the renderer, when there is something for it to
    stand beside. Verified the same way too — the redaction has to take exactly
    the shapes that were captured and nothing else, which is what makes it safe
    to do to every booklet.

    A page named here and unable to give up its marks stops the build rather
    than quietly keeping them. Silence would be the old behaviour back — both
    icons printed, one of them over nothing — and it would arrive as a report
    from the client rather than as a failure here. If a revised export moves an
    icon further from its number than ``MARK_REACH``, widen the reach after
    measuring; do not let the page through.
    """
    by_key = {s.key: s for s in specs}
    caught: list[tuple[FieldSpec, list[dict]]] = []
    for key in plan["keys"]:
        spec = by_key.get(key)
        if spec is None:
            raise MapError(
                f"page {page.number}: {key!r} carries a mark to lift and no "
                f"rule made the field -- found {sorted(by_key)!r}"
            )
        above = plan.get("where") == "above"
        box = spec.rect.to_points(page_rect)
        marks = _mark_above(page, box) if above else _mark_beside(page, box)
        if not marks:
            where = (
                f"within {MARK_RISE:.0f}pt above"
                if above
                else f"within {MARK_REACH:.0f}pt to the right of"
            )
            raise MapError(
                f"page {page.number}: no mark {where} {key!r}. If the export "
                f"moved it, measure the gap and widen MARK_RISE/MARK_REACH; "
                f"the icon must not be left baked."
            )
        caught.append((spec, marks))

    recorded: list[tuple[FieldSpec, list[FramePath]]] = []
    for spec, marks in caught:
        paths = [_frame_path_from(d, page_rect) for d in marks]
        if any(path is None for path in paths):
            raise MapError(
                f"page {page.number}: {spec.key!r}'s mark uses a segment this "
                f"cannot record, so it could not be put back after erasing"
            )
        recorded.append((spec, [p for p in paths if p is not None]))

    wanted = [d for _, marks in caught for d in marks]
    before = {_shape_id(d) for d in page.get_drawings()}
    # One region per mark, not one per shape, and given real room.
    #
    # ``REMOVE_IF_COVERED`` measures a stroke by more than the rectangle
    # ``get_drawings`` reports: the platform's laptop is drawn in 0.5pt strokes
    # whose mitred joins reach past their own bounds, and three of its seven
    # shapes sat out every redaction drawn a point around them -- the icon was
    # recorded, half erased, and drawn again over what was left. Measured on
    # that icon, the whole of it comes away from five points and no more comes
    # away from seven; six is the middle of that. The mark's own shapes are
    # unioned first because a region has to cover a shape whole to take it, and
    # the marks stand a hundred points apart, so nothing else is within reach.
    #
    # ``REMOVE_IF_TOUCHED`` would take all seven at a single point of margin,
    # and would also take anything that merely crossed the region. The check
    # below is what makes either safe, and this is the one that cannot reach
    # past a neighbour to begin with.
    for _, marks in caught:
        region = fitz.Rect(marks[0]["rect"])
        region.normalize()
        for drawing in marks[1:]:
            rect = fitz.Rect(drawing["rect"])
            rect.normalize()
            region = fitz.Rect(
                min(region.x0, rect.x0), min(region.y0, rect.y0),
                max(region.x1, rect.x1), max(region.y1, rect.y1),
            )
        page.add_redact_annot(
            region + (-MARK_BLEED, -MARK_BLEED, MARK_BLEED, MARK_BLEED)
        )
    page.apply_redactions(
        images=fitz.PDF_REDACT_IMAGE_NONE,
        graphics=fitz.PDF_REDACT_LINE_ART_REMOVE_IF_COVERED,
    )
    gone = before - {_shape_id(d) for d in page.get_drawings()}
    should_go = {_shape_id(d) for d in wanted}
    if gone != should_go:
        raise MapError(
            f"page {page.number}: lifting the chip marks took {len(gone)} "
            f"shapes off the artwork, not the {len(should_go)} captured -- "
            f"{sorted(gone - should_go)!r} should have stayed and "
            f"{sorted(should_go - gone)!r} should have gone"
        )

    for spec, paths in recorded:
        spec.ornament = paths
        spec.row_group = plan["group"]


def _row_extent(spec: FieldSpec, page_rect: fitz.Rect) -> fitz.Rect:
    """The room a chip takes: its value's box and the mark that names it.

    The same measure the renderer takes when it re-centres a row, so a chip
    moved here and a chip moved there are moved by the same reckoning.
    """
    box = spec.rect.to_points(page_rect)
    xs = [
        page_rect.x0 + x * page_rect.width
        for path in spec.ornament
        for item in path.items
        for x in item.points[::2]
    ]
    ys = [
        page_rect.y0 + y * page_rect.height
        for path in spec.ornament
        for item in path.items
        for y in item.points[1::2]
    ]
    if not xs or not ys:
        return box
    # By hand rather than by unioning point-rects: a rect with no width is
    # empty and ``Rect.__or__`` ignores an empty rect.
    return fitz.Rect(
        min(box.x0, *xs), min(box.y0, *ys), max(box.x1, *xs), max(box.y1, *ys)
    )


def _shift_chip(spec: FieldSpec, dx: float, page_rect: fitz.Rect) -> None:
    """Move a chip sideways -- its value's box and its mark together."""
    step = dx / page_rect.width
    spec.rect = NormRect(
        x=spec.rect.x + step, y=spec.rect.y, w=spec.rect.w, h=spec.rect.h
    )
    for path in spec.ornament:
        for item in path.items:
            item.points = [
                value + step if index % 2 == 0 else value
                for index, value in enumerate(item.points)
            ]


def _spread_row(
    page: fitz.Page,
    page_rect: fitz.Rect,
    specs: list[FieldSpec],
    plan: dict[str, Any],
    gone: list[fitz.Rect],
) -> list[fitz.Rect]:
    """Space what is left of a row evenly across what the row was drawn across.

    معلومات التواصل is one drawing serving all three auctions, and an
    electronic one is held nowhere -- so «الموقع» comes off the page before
    anything is derived from it. That left the other three chips standing where
    four chips stood, with the venue's gap still in the middle of the row and
    the platform hard against the right margin. «الموقع» is not missing from
    this card; it was never one of this auction's facts, and a row with a hole
    in it reads as one that failed to print.

    Evenly by the chips' *centres*, which is how the row reads: each chip is a
    mark with its value centred under it, and the eye measures the marks. The
    two outermost keep the edges the designer gave the row -- the first chip's
    left and the last chip's right do not move -- so the row still occupies the
    band it was drawn in and only the space inside it is shared out.

    Nothing happens unless something was actually taken off this row. A card
    that lost no chip is the designer's own spacing and is left exactly as
    drawn, which is why الهجين and حضوري are untouched by this.

    Returns the boxes the chips have just left, which have to be cleared as
    well as the ones they moved into. Baking clears the region a field will
    draw over and nothing else, so a chip that moved leaves the designer's own
    sample standing where it used to be -- «الخميس 11 مارس 2024» printed at the
    new place and «وليو 2026» left behind at the old one.
    """
    by_key = {s.key: s for s in specs}
    members = [by_key[k] for k in plan["keys"] if k in by_key]
    if len(members) < 2:
        return []
    boxes = {s.key: _row_extent(s, page_rect) for s in members}
    members.sort(key=lambda s: boxes[s.key].x0)
    band = fitz.Rect(
        min(b.x0 for b in boxes.values()), min(b.y0 for b in boxes.values()),
        max(b.x1 for b in boxes.values()), max(b.y1 for b in boxes.values()),
    )
    # Only what was cut out of this row -- the page also loses a code far below
    # it, and that is not this row's space to take back.
    lost = [r for r in gone if r.y0 < band.y1 and r.y1 > band.y0]
    if not lost:
        return []
    left = min(band.x0, *[r.x0 for r in lost])
    right = max(band.x1, *[r.x1 for r in lost])
    first = boxes[members[0].key].width / 2
    last = boxes[members[-1].key].width / 2
    start, end = left + first, right - last
    if end <= start:
        raise MapError(
            f"page {page.number}: the row {plan['group']!r} is wider than the "
            f"space it was drawn in, so it cannot be spaced evenly"
        )
    steps = len(members) - 1
    vacated: list[fitz.Rect] = []
    for index, spec in enumerate(members):
        box = boxes[spec.key]
        target = start + (end - start) * index / steps
        step = target - (box.x0 + box.x1) / 2
        if abs(step) < 0.01:
            continue
        vacated.append(spec.rect.to_points(page_rect))
        _shift_chip(spec, step, page_rect)
    return vacated


def _erase_frame(
    page: fitz.Page,
    page_rect: fitz.Rect,
    extent: fitz.Rect,
    *,
    top: float,
    pitch: float,
    rows: int,
) -> bool:
    """Take a block's ruling off the artwork, leaving its header bar alone.

    The bake keeps line art everywhere else, because everywhere else the line
    art is the design. Here the ruling is being replaced by the same ruling
    drawn to the length the auction needs, so it comes off -- and only it: the
    region is the union of the shapes captured, which begins below the header
    bar and ends at the foot of the tab.
    """
    caught = _frame_paths(
        page, page_rect, extent, top=top, pitch=pitch, rows=rows
    )
    if caught is None:
        return False
    wanted, region = caught
    # Read before the annotation goes on: a redaction annotation is itself a
    # drawing -- a red box the width of a point -- and counting it as artwork
    # made the check below report the frame as one shape too many.
    before = {_shape_id(d) for d in page.get_drawings()}
    page.add_redact_annot(region + (-1, -1, 1, 1))
    page.apply_redactions(
        images=fitz.PDF_REDACT_IMAGE_NONE,
        graphics=fitz.PDF_REDACT_LINE_ART_REMOVE_IF_COVERED,
    )
    after = {_shape_id(d) for d in page.get_drawings()}
    gone = before - after
    should_go = {_shape_id(d) for d in wanted}
    if gone != should_go:
        raise MapError(
            f"page {page.number}: erasing the table frame took "
            f"{len(gone)} shapes off the artwork, not the {len(should_go)} "
            f"captured -- {sorted(gone - should_go)!r} should have stayed and "
            f"{sorted(should_go - gone)!r} should have gone"
        )
    return True


def _shape_id(drawing: dict) -> tuple:
    """A drawing named by where it is and what it is drawn in.

    Its position in ``get_drawings`` is not a name: removing one renumbers the
    rest, which is exactly the comparison this has to survive.
    """
    rect = fitz.Rect(drawing["rect"])
    rect.normalize()
    return (
        tuple(round(v, 2) for v in rect),
        round(float(drawing.get("width") or 0.0), 3),
        _ink(drawing.get("color")) and tuple(_ink(drawing["color"])),
        _ink(drawing.get("fill")) and tuple(_ink(drawing["fill"])),
    )


def _lease_frame(
    page: fitz.Page, page_rect: fitz.Rect, spec: FieldSpec
) -> TableFrame | None:
    """The lease block's ruling on a page the build made a copy of.

    The copy is taken before any of this, so it still wears the ruling its
    original has had lifted off. Its geometry is the original's -- the copy is
    the same page in another colour -- so the block is described from the field
    already built for it rather than measured a second time.
    """
    table = spec.table
    if table is None:
        return None
    body = spec.rect.to_points(page_rect)
    return _lift_frame(
        page, page_rect, body,
        pitch=table.row_pitch * page_rect.height, rows=table.rows,
    )


def _lift_frame(
    page: fitz.Page,
    page_rect: fitz.Rect,
    body: fitz.Rect,
    *,
    pitch: float,
    rows: int,
) -> TableFrame | None:
    """Capture a block's ruling and take it off the artwork, or do neither.

    The two halves are one call because either alone prints wrong. Captured but
    not erased, the redraw lands on top of the original and every line comes out
    a third too dark; erased but not captured, the page loses its table.
    """
    extent = _extent_around(page, body, pitch, page_rect)
    frame = _capture_frame(
        page, page_rect, extent, top=body.y0, pitch=pitch, rows=rows
    )
    if frame is None:
        return None
    if not _erase_frame(
        page, page_rect, extent, top=body.y0, pitch=pitch, rows=rows
    ):
        return None
    return frame


def _erase_blocks(page: fitz.Page, extents: list[fitz.Rect]) -> None:
    """Take whole table blocks off a page, artwork and all.

    The usual bake keeps line art, because on every other page the line art *is*
    the design. Here the block being removed is the design being replaced, so
    this is the one place that clears it -- and it clears nothing else: the
    extents come from the blocks themselves.
    """
    if not extents:
        return
    for extent in extents:
        page.add_redact_annot(extent)
    # ``IF_COVERED`` rather than ``IF_TOUCHED``: the extent is grown from the
    # block's own drawings, so everything belonging to it is inside, and
    # anything only grazing the edge belongs to the page, not the block.
    page.apply_redactions(
        images=fitz.PDF_REDACT_IMAGE_NONE,
        graphics=fitz.PDF_REDACT_LINE_ART_REMOVE_IF_COVERED,
    )


def _add_navy_page(
    doc: fitz.Document, position: int, blocks: list, page_rect: fitz.Rect
) -> int | None:
    """Append the navy colourway of the summary page.

    A full copy of the teal page, so its heading, its footer and its logos stay
    the designer's own and stay real content rather than a placed form; then
    every table block off it, and the navy block into the place the teal one
    held. The table sits under the heading in both colours -- choosing a colour
    must not move the table half a page down.
    """
    navy = _navy_colourway(page_rect)
    if navy is None:
        return None
    art, clip = navy
    target = _block_extents(doc[position], blocks, page_rect)[0]

    doc.fullcopy_page(position)
    index = doc.page_count - 1
    page = doc[index]
    _erase_blocks(page, _block_extents(page, blocks, page_rect))
    page.show_pdf_page(target, art, 0, clip=clip)
    art.close()
    return index


def _sample_cells(page: fitz.Page, colour: str, size: float) -> list[fitz.Rect]:
    """Every sample value a table printed, so the bake can clear them.

    ``derive_tables`` recognises a table by its printed headers. The lease table
    has its headers converted to outlines, so it is not recognised -- but its
    sample rows are ordinary text, and leaving them would print another
    client's lease data. Clearing them needs no table structure, only their
    rects, so they are collected directly.
    """
    want = int(colour[1:], 16)
    out: list[fitz.Rect] = []
    for block in page.get_text("dict")["blocks"]:
        if block.get("type") != 0:
            continue
        for line in block["lines"]:
            for span in line["spans"]:
                if not span["text"].strip():
                    continue
                if span.get("color") != want or abs(span["size"] - size) > 0.4:
                    continue
                out.append(fitz.Rect(span["bbox"]))
    return out


# ------------------------------------------------------------------ build


def _sections_from(source_map: SourceMap, capacity: dict[int, int]) -> list[Section]:
    """A compatibility section plan: contiguous runs of the same kind.

    The page plan on a project is the real structure now. These sections exist
    so a project created before the builder -- or one whose template has no page
    rows yet -- still composes into the booklet it always did. Only the default
    lot layout goes into the per-record run: ``Section`` refuses a range whose
    span does not match ``pages_per_item``, and the alternatives are the plan's
    business, not the section plan's.
    """
    sections: list[Section] = []
    for position, page in enumerate(source_map.pages):
        if page.role is PageRole.LOT_TABLE:
            kind = SectionKind.TABLE
        elif page.role is PageRole.LOT and page.layout == "standard":
            kind = SectionKind.PER_RECORD
        elif page.role in PER_LOT_ROLES:
            continue  # optional and per-lot; the plan decides, not the section
        else:
            kind = SectionKind.FIXED

        if sections and sections[-1].kind is kind and (
            sections[-1].last_page == position - 1
        ) and kind is SectionKind.FIXED:
            sections[-1].last_page = position
            continue
        sections.append(
            Section(
                kind=kind,
                first_page=position,
                last_page=position,
                name=page.name,
                pages_per_item=1,
                rows_per_page=capacity.get(position, 1),
            )
        )
    return sections


def build(source_map: SourceMap, source: Path, out_dir: Path) -> dict:
    doc = fitz.open(source)
    extra = {
        name: fitz.open(_require_source(name)) for name in source_map.extra_sources
    }
    assert_map(doc, source_map, extra)

    # Pruning happens once, up front: after this, page N of the document is
    # entry N of the map, and no index has to be remapped later.
    #
    # A map cut from one export keeps ``select``, which is what it has always
    # done and what the built manifests reproduce byte for byte. A map that
    # grafts a page from another export cannot: ``select`` can only keep pages
    # the document already has. That one is assembled a page at a time instead.
    known_marks: dict[str, list[list[int]]] = {}
    if extra:
        # Learned from each whole export before its pages are taken out of it.
        for name, book in extra.items():
            known_marks[name] = agent_silhouettes(book)
        composed = fitz.open()
        for mapped in source_map.pages:
            book = extra[mapped.source] if mapped.source else doc
            composed.insert_pdf(book, from_page=mapped.index, to_page=mapped.index)
        doc.close()
        doc = composed
    else:
        doc.select(source_map.indices)
    for book in extra.values():
        book.close()
    kept = len(source_map.pages)
    page_rect = doc[0].rect

    # The six brand-guide covers, and only six. A cover is one of the designs
    # the guide draws or it is off-brand, so there is no blank carrier here for
    # a client to upload their own onto.
    cover_pages: list[dict[str, Any]] = []
    for number, design in enumerate(source_map.covers, start=1):
        with fitz.open(design, filetype="pdf") as art:
            doc.insert_pdf(art, from_page=0, to_page=0)
        cover_pages.append({"name": f"غلاف {number}", "rules": "cover"})

    # The summary page in both colours. The navy one is appended after the
    # covers so that adding it moves no index a booklet may already point at,
    # and ordered back into place by ``position`` when the pages are written.
    table_position = next(
        (i for i, m in enumerate(source_map.pages) if m.role is PageRole.LOT_TABLE),
        None,
    )
    table_blocks = (
        _colourways(doc, table_position, page_rect)
        if table_position is not None
        else []
    )
    navy_index = (
        _add_navy_page(doc, table_position, table_blocks, page_rect)
        if table_blocks
        else None
    )
    # The lease page in the brand's other colour, appended like the covers so
    # that adding it moves no index a booklet may already point at.
    lease_position = next(
        (i for i, m in enumerate(source_map.pages) if m.role is PageRole.RENT_TABLE),
        None,
    )
    lease_teal_index = (
        _recoloured_lease_page(doc, lease_position)
        if lease_position is not None
        else None
    )

    if len(table_blocks) > 1:
        _erase_blocks(
            doc[table_position],
            _block_extents(doc[table_position], table_blocks, page_rect)[1:],
        )
        table_blocks = table_blocks[:1]

    # The summary table's ruling, off the artwork and onto the field, so the
    # block ends at the last property rather than at the tenth row the designer
    # had to draw it to. Both colourways: same geometry, and the teal one's
    # lines are teal where the navy one's are navy, so each is read off its own
    # page. Done here, with the pages in their final form and before anything is
    # derived or baked, because from here on the frame is the field's.
    frames: dict[int, TableFrame] = {}
    if table_blocks and table_position is not None:
        block = table_blocks[0]
        body = fitz.Rect(block.first_row_pt)
        for row in range(block.rows):
            body |= block.row_rect(row)
        for index in (table_position, navy_index):
            if index is None:
                continue
            frame = _lift_frame(
                doc[index], page_rect, body,
                pitch=block.row_pitch, rows=block.rows,
            )
            if frame is not None:
                frames[index] = frame

    # The screen drawings of the lot pages, appended after everything else so
    # that adding them moves no page index a booklet already points at. They
    # are pages of the document and fields are derived on them like any other,
    # but they are not pages of the *booklet*: nothing lists them, and the only
    # thing that ever asks for one is a render whose output is a screen.
    screen_of: dict[int, int] = {}
    if source_map.flavours:
        stands_for = source_map.twin_of()
        with fitz.open(source) as export:
            for offset, twin in enumerate(source_map.flavours):
                doc.insert_pdf(export, from_page=twin.index, to_page=twin.index)
                screen_of[stands_for[offset]] = doc.page_count - 1

    derived = derive_document(doc)

    # The mapped pages, then the screen twins at wherever they landed. Both go
    # through the same derivation, the same rules and the same bake: a twin is
    # a page of artwork like any other, and a page the build did not describe
    # keeps the designer's sample data printed into it.
    to_build: list[tuple[int, SourcePage]] = list(enumerate(source_map.pages))
    to_build += [
        (screen_of[stands_for[offset]], twin)
        for offset, twin in enumerate(source_map.flavours)
    ]

    specs: list[FieldSpec] = []
    table_cells: dict[int, list[fitz.Rect]] = defaultdict(list)

    for position, mapped in to_build:
        page = doc[position]
        # What this variant's auction does not have, off the page before
        # anything is derived from it: a region nothing draws over is a region
        # the bake will not clear, so it has to go now or it prints for ever.
        removed: list[fitz.Rect] = []
        if mapped.remove:
            removed = [
                fitz.Rect(x0 * page_rect.width, y0 * page_rect.height,
                          x1 * page_rect.width, y1 * page_rect.height)
                for x0, y0, x1, y1 in mapped.remove
            ]
            _erase_blocks(page, removed)
            candidates = derive_page(doc, position)
            derived[position] = candidates
        candidates = derived.get(position, [])

        if mapped.role in (PageRole.LOT_TABLE, PageRole.RENT_TABLE):
            # The summary page holds one colourway of one ten-row table; the
            # lease table is one table drawn in two halves and does carry on.
            summary = mapped.role is PageRole.LOT_TABLE
            found, cells = _table_specs(
                doc, position, page_rect, mapped.name,
                blocks=table_blocks if summary else None,
                continuous=not summary,
            )
            for spec in found:
                if spec.table is not None and position in frames:
                    spec.table.frame = frames[position]
            specs.extend(found)
            table_cells[position].extend(cells)
            if not found:
                # Headers converted to outlines, so derive_tables sees nothing.
                # The block is still perfectly regular; rebuild it from the row
                # numbers and the sample row.
                spec, cells = _uniform_table(
                    page,
                    page_rect,
                    mapped.name,
                    LEASE_COLUMNS if mapped.role is PageRole.RENT_TABLE else (),
                )
                if mapped.role is PageRole.RENT_TABLE:
                    specs.extend(_lease_headings(page, page_rect))
                if spec is not None:
                    specs.append(spec)
                    table_cells[position].extend(cells)
                else:
                    table_cells[position].extend(_sample_cells(page, BODY, 8.1))
                    table_cells[position].extend(_sample_cells(page, "#FFFFFF", 13.0))
            continue

        # Every code the booklet prints, and the address each leads to. Also
        # why the sample codes stop printing: baking clears what a field draws
        # over, and until now nothing claimed them -- so every booklet went out
        # carrying the designer's own destinations, scannable.
        if mapped.flavour == ELECTRONIC and mapped.role is PageRole.LOT:
            # No codes on this drawing: the chips are clicked, and they stand
            # in a column rather than a block.
            specs.extend(_column_link_fields(page, position, page_rect))
        else:
            named = LINK_PAGES.get(mapped.role)
            if named:
                specs.extend(_link_fields(page, position, page_rect, named))

        if mapped.role is PageRole.LOT:
            for hint in suggest(candidates):
                if hint.role != "value":
                    continue
                specs.append(
                    _spec_from(
                        hint.field, page_rect, hint.key,
                        siblings=candidates,
                        label=hint.label,
                        origin=f"autokey:{hint.label}",
                        is_required=hint.key in REQUIRED_LOT_KEYS,
                    )
                )

        if mapped.rules:
            specs.extend(
                _apply_rules(mapped.rules, page, position, candidates, page_rect)
            )
            # The marks the designer drew beside the two telephone numbers,
            # lifted off the page so that a seller with no WhatsApp does not
            # print a WhatsApp icon with nothing beside it. Done here, after
            # the rules, because the marks are found from where the values are.
            for marked in MARKED_CHIPS.get(mapped.rules, ()):
                on_page = [s for s in specs if s.page_index == position]
                _lift_marks(page, page_rect, on_page, marked)
                # Spaced only after the marks are off the page, because a chip
                # moves with the mark that names it and the mark is not the
                # chip's until it has been lifted.
                if marked.get("spread"):
                    table_cells[position].extend(
                        _spread_row(page, page_rect, on_page, marked, removed)
                    )

        if mapped.role in (PageRole.LOT, PageRole.LOT_FEATURES, PageRole.BOUNDARIES):
            on_page = [s for s in specs if s.page_index == position]
            specs.extend(
                _sweep_unclaimed(
                    candidates, on_page, page_rect, position,
                    SWEEP_NAMES.get(mapped.rules),
                )
            )

    for offset, cover in enumerate(cover_pages):
        position = kept + offset
        if not cover["rules"]:
            continue
        specs.extend(
            _apply_rules(
                cover["rules"], doc[position], position,
                derived.get(position, []), page_rect,
            )
        )

    # The teal lease page is the navy one recoloured, so it carries the same
    # fields at the same rects.
    if lease_teal_index is not None and lease_position is not None:
        # And its sample rows have to be cleared too. The copy was taken before
        # the bake, which clears by page, so without this the teal page printed
        # the designer's «00»s under whatever the client typed.
        table_cells[lease_teal_index].extend(table_cells[lease_position])
        for spec in list(specs):
            if spec.page_index != lease_position:
                continue
            twin = deepcopy(spec)
            twin.page_index = lease_teal_index
            if twin.type is FieldType.TABLE:
                twin.key = spec.key.replace(
                    f"__table__{lease_position}_", f"__table__{lease_teal_index}_"
                )
                # Same rows in the same places, ruled in the other identity
                # colour. Read off its own page rather than copied: the teal
                # page is made by rewriting the colour its content stream asks
                # for, so the geometry is the navy page's and the ink is not.
                if twin.table is not None:
                    twin.table.frame = _lease_frame(
                        doc[lease_teal_index], page_rect, spec
                    )
            twin.origin = f"{spec.origin}/colourway=teal"
            specs.append(twin)

    captioned = _draw_date_captions(
        doc, [kept + i for i in range(len(cover_pages))], derived, specs, page_rect,
    )

    # Last, so it sees every page this build makes: the mapped pages, the six
    # covers and the navy summary page.
    # Pages appended after the map's own -- the covers, the navy summary, the
    # recoloured lease page -- are this map's own export by construction.
    page_source = [m.source for m in source_map.pages]
    page_source += [""] * max(0, doc.page_count - len(page_source))
    bands = {
        position: m.agent_mark
        for position, m in enumerate(source_map.pages)
        if m.agent_mark
    }
    branded = _rebrand(doc, page_rect, page_source, known_marks, bands)
    specs.extend(branded)

    # The navy colourway is the teal block's artwork in another colour at the
    # same coordinates, so it is the same field on another page.
    if navy_index is not None and table_position is not None:
        for spec in list(specs):
            if spec.page_index != table_position or spec.type is not FieldType.TABLE:
                continue
            twin = deepcopy(spec)
            twin.key = spec.key.replace(
                f"__table__{table_position}_", f"__table__{navy_index}_"
            )
            twin.page_index = navy_index
            twin.origin = f"{spec.origin}/colourway=navy"
            # Same rows in the same places, drawn in the other identity colour.
            if twin.table is not None:
                twin.table.frame = frames.get(navy_index)
            specs.append(twin)

    # The unbaked artwork, already pruned and reordered, so its page indices
    # line up with every field. Publishing and the suggestion overlay both read
    # it; without it neither works on a script-built template.
    out_dir.mkdir(parents=True, exist_ok=True)
    doc.save(str(out_dir / "source.pdf"), garbage=4, deflate=True)

    # Bake -- clearing only what a field will draw over. Printed labels and chip
    # captions are design, not data, and must survive.
    regions: dict[int, list[tuple[fitz.Rect, FieldType]]] = defaultdict(list)
    for spec in specs:
        if spec.type is FieldType.TABLE:
            continue  # cleared cell by cell below, not as one block
        rect = spec.rect.to_points(doc[spec.page_index].rect)
        regions[spec.page_index].append((rect, spec.type))
    for page_index, cells in table_cells.items():
        regions[page_index].extend((cell, FieldType.TEXT) for cell in cells)
    # A twin is only usable if it asks for exactly what the page it replaces
    # asks for. The booklet points at the printed page and its values are keyed
    # by field, so a twin that named one of them differently would print that
    # value somewhere else -- or, worse, not at all.
    #
    # The برج drawings pass. The قياسي one does not: it is a later revision
    # whose الأطوال block is four labelled rows where the printed page has two
    # combined runs, so «شرقاً» and «غرباً» are read twice and the vocabulary
    # pairs المساحة and الاستخدام with the الحدود column beside them. Rather
    # than swap a page that would print the area where the north boundary goes,
    # the twin is dropped and the printed drawing is used for both outputs.
    refused: list[tuple[int, int, str]] = []
    for at, index in sorted(screen_of.items()):
        def named(page_index: int) -> list[str]:
            return sorted(
                s.key for s in specs
                if s.page_index == page_index and s.type is FieldType.TEXT
            )
        mine, theirs = named(at), named(index)
        if mine != theirs:
            only_print = sorted(set(mine) - set(theirs))
            only_screen = sorted(set(theirs) - set(mine))
            repeated = sorted({k for k in theirs if theirs.count(k) > 1})
            refused.append((at, index, (
                f"asks for {only_screen or 'nothing'} that page {at} does not, "
                f"is missing {only_print or 'nothing'}, and repeats {repeated}"
            )))
    for at, index, why in refused:
        screen_of.pop(at, None)
        # And its fields go with it. Nothing will ever draw that page, and a
        # field on it is a field the editor has to reckon with -- two of them
        # share a key, which is a thing a page is not allowed to do.
        specs = [s for s in specs if s.page_index != index]
        print(
            f"  ! {source_map.slug}: the screen drawing on page {index} cannot "
            f"stand in for page {at} -- it {why}. The printed drawing will be "
            f"used for both outputs."
        )

    artwork_pages = doc.page_count
    report = bake_document(doc, dict(regions))

    # The one chip a booklet does not always carry, cut off every drawing that
    # has one. After the bake, so the cutting is taken from a page whose sample
    # photograph has already gone: lifted before it, a chip 95pt wide dragged a
    # 4032x2268 frame along with it and the cuttings came to 22MB apiece.
    for spec in specs:
        if spec.key != LEASE_CHIP_KEY or spec.type is not FieldType.LINK:
            continue
        if not _cut_out_chip(doc, spec.page_index, spec, page_rect):
            raise MapError(
                f"page {spec.page_index}: the {LEASE_CHIP_KEY!r} chip could "
                f"not be found to cut out, so a property with no lease page "
                f"would print a chip leading nowhere"
            )

    capacity: dict[int, int] = defaultdict(int)
    for spec in specs:
        if spec.type is FieldType.TABLE and spec.table is not None:
            capacity[spec.page_index] += spec.table.rows
    sections = _sections_from(source_map, dict(capacity))

    background = out_dir / "background.pdf"
    doc.save(str(background), garbage=4, deflate=True, clean=True)

    # Written in booklet order: ``position`` is what the builder reads the plan
    # in, and the navy summary page belongs beside the teal one however far down
    # the file it was appended.
    pages: list[dict[str, Any]] = []
    for position, mapped in enumerate(source_map.pages):
        needs = mapped.needs_artwork or NEEDS_LIVE_TEXT.get(mapped.rules, "")
        options: dict[str, Any] = {"needs_artwork": needs} if needs else {}
        slot, layout, name = mapped.slot, mapped.layout, mapped.name
        # Where the same page is drawn for a screen. Carried on the page it
        # replaces rather than as a page of its own, because that is what it
        # is: one page of the booklet with two drawings.
        if position in screen_of:
            options[f"page_for_{ELECTRONIC}"] = screen_of[position]
        if mapped.role is PageRole.COVER and mapped.slot == "cover":
            # The export's own cover. It holds the cover slot, so a booklet's
            # cover lands where the designer put it, but it is غلاف 1 drawn a
            # second time and is not offered as a seventh choice.
            options["source_cover"] = True
        # The colour is a property of the page, not part of its name: a booklet
        # has one «بيان عقود الإيجار», printed in one of two colours, and naming
        # the variants offered a colour as though it were a different page.
        if mapped.role is PageRole.LOT_TABLE and navy_index is not None:
            slot, layout = TABLE_SLOT, "green"
        if mapped.role is PageRole.RENT_TABLE and lease_teal_index is not None:
            slot, layout = LEASE_SLOT, "blue"
        pages.append({
            "page_index": position,
            "role": mapped.role.value,
            "slot": slot,
            "layout": layout,
            "name": name,
            "is_optional": mapped.optional,
            "default_on": mapped.default_on and not needs,
            "options": options,
            "position": len(pages),
        })
        if mapped.role is PageRole.RENT_TABLE and lease_teal_index is not None:
            pages.append({
                "page_index": lease_teal_index,
                "role": mapped.role.value,
                "slot": LEASE_SLOT,
                "layout": "green",
                "name": mapped.name,
                "is_optional": True,
                "default_on": False,
                "options": {},
                "position": len(pages),
            })
        if mapped.role is PageRole.LOT_TABLE and navy_index is not None:
            pages.append({
                "page_index": navy_index,
                "role": mapped.role.value,
                "slot": TABLE_SLOT,
                "layout": "blue",
                "name": mapped.name,
                "is_optional": False,
                "default_on": False,
                "options": {},
                "position": len(pages),
            })
    for offset, cover in enumerate(cover_pages):
        pages.append({
            "page_index": kept + offset,
            "role": PageRole.COVER.value,
            "slot": "cover",
            "layout": "",
            "name": cover["name"],
            "is_optional": False,
            "default_on": False,
            "options": (
                {"drawn_caption": DATE_CAPTION}
                if kept + offset in captioned
                else {}
            ),
            "position": len(pages),
        })

    manifest = {
        "slug": source_map.slug,
        "name": source_map.name,
        "variant": source_map.variant,
        "source": source.name,
        "page_size": [round(page_rect.width, 2), round(page_rect.height, 2)],
        "design_page_height": round(page_rect.height, 2),
        "page_count": doc.page_count,
        # How many of those are artwork. The rest are cuttings -- pieces of a
        # page the renderer places back when the chip they came from is in the
        # booklet -- and nothing is derived from one or points at one.
        "artwork_pages": artwork_pages,
        "kept_source_pages": source_map.indices,
        "sections": [dataclasses.asdict(s) | {"kind": s.kind.value} for s in sections],
        "pages": pages,
        # Which page stands in for which when the booklet is read rather than
        # printed. Keyed by the page a booklet actually points at, so a project
        # built before this existed keeps pointing where it always did and the
        # substitution happens at render time or not at all.
        "flavours": {
            ELECTRONIC: {str(at): index for at, index in sorted(screen_of.items())}
        },
        "fields": [_field_json(s) for s in specs],
        "bake": {
            "pages": report.pages,
            "text_rects_cleared": report.text_rects_cleared,
            "images_removed": report.images_removed,
            "background_bytes": background.stat().st_size,
        },
    }
    (out_dir / "template.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    doc.close()
    return manifest


def _field_json(spec: FieldSpec) -> dict[str, Any]:
    data = dataclasses.asdict(spec)
    data["type"] = spec.type.value
    data["align"] = spec.align.value
    data["valign"] = spec.valign.value if spec.valign else None
    data["fit"] = spec.fit.value
    if spec.table is not None:
        table = data["table"]
        table["columns"] = [
            c | {"align": spec.table.columns[i].align.value,
                 "valign": (spec.table.columns[i].valign.value
                            if spec.table.columns[i].valign else None),
                 "fit": spec.table.columns[i].fit.value}
            for i, c in enumerate(table["columns"])
        ]
    return data


def _find_source(pages: int, name: str = "") -> Path | None:
    """The designer's export this map describes, wherever it is on disk.

    ``name`` is a distinctive part of the filename and is what actually
    identifies the export; ``pages`` then confirms it is the revision the map
    was written against. Page count alone stopped being an identifier when a
    second sixteen-page booklet arrived — the electronic one — and a search by
    count would have handed one of the two templates the other's artwork.

    The filenames round-trip badly (Arabic, and some carry stray bidi marks), so
    the match is a substring of the stem with those marks stripped rather than
    an equality test on a name anyone has to type exactly.
    """
    wanted = _plain(name)
    for root in (REFERENCES, BACKEND.parent):
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


def _require_source(name: str) -> Path:
    """An export named by a page that is grafted from it.

    Unlike a map's own export there is no page count to confirm it against, so
    the name has to be distinctive enough on its own — and the build stops
    rather than quietly falling back to the map's own artwork, which is the
    borrowing this is here to end.
    """
    wanted = _plain(name)
    for root in (REFERENCES, BACKEND.parent):
        for candidate in sorted(root.glob("*.pdf")):
            if wanted and wanted in _plain(candidate.stem):
                return candidate
    raise MapError(f"no export matching {name!r} found under {REFERENCES}")


#: Marks a filename may carry that nobody means to type: bidi controls, the
#: BOM, and the tatweel some exporters put in Arabic filenames.
_FILENAME_NOISE = dict.fromkeys(
    [0xFEFF, 0x200E, 0x200F, 0x202A, 0x202B, 0x202C, 0x202D, 0x202E, 0x0640]
)


def _plain(text: str) -> str:
    return unicodedata.normalize("NFKC", text).translate(_FILENAME_NOISE).strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slug", help="build only this template")
    parser.add_argument(
        "--out", type=Path, default=BACKEND / "var" / "templates",
        help="where the built templates go",
    )
    args = parser.parse_args()

    wanted = [m for m in MAPS if not args.slug or m.slug == args.slug]
    if not wanted:
        parser.error(f"no page map named {args.slug!r}")

    for source_map in wanted:
        source = _find_source(source_map.source_pages, source_map.source)
        if source is None:
            print(f"  ! {source_map.slug}: no {source_map.source_pages}-page "
                  f"export matching {source_map.source!r} found under "
                  f"{REFERENCES}")
            continue
        if not source_map.covers:
            print(f"  ! {source_map.slug}: cover designs not found; "
                  f"building without the cover choices")
        manifest = build(source_map, source, args.out / source_map.slug)
        size = manifest["bake"]["background_bytes"] / 1e6
        covers = sum(1 for p in manifest["pages"] if p["slot"] == "cover")
        print(
            f"  {source_map.slug:28s} {manifest['page_count']:3d} pages "
            f"({covers} covers)  {len(manifest['fields']):3d} fields  "
            f"{manifest['bake']['text_rects_cleared']:4d} cleared  "
            f"{size:6.1f} MB"
        )


if __name__ == "__main__":
    main()
