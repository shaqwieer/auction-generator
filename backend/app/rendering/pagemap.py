"""Which page of the designer's export is which, declared rather than guessed.

The first build script inferred the booklet's structure from its page count and
derived fields on two hardcoded pages. Everything else was pruned, and because
baking only clears what a field will draw over, every page it pruned kept the
designer's sample data -- the agent's phone number, the sample auction date, a
whole nineteen-row property table -- printed into the background.

A page map fixes both halves at once. It says what each source page *is*, so the
build knows which field rules to run on it and therefore what to clear, and it
says which pages a variant keeps. Roles are reviewed data, confirmed against
renders of the artwork, not the output of a heuristic.

``assert_map`` is the tripwire for the day a revised export arrives with its
pages in a different order. It can only check what MuPDF can read back, which is
less than you would hope: Illustrator outlines some headings, so the chip that
visually separates the electronic lot pages from the in-person ones extracts on
three of the four pages that carry it. Markers are therefore declared only where
they genuinely extract, and they bracket the pages where they do not.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

import fitz

from .autokey import normalise


class PageRole(StrEnum):
    """What a source page is for.

    ``LOT`` pages repeat once per property. The five roles between
    ``LOT_FEATURES`` and ``RENT_TABLE`` are the optional per-property pages the
    brand guide describes (guide pages 16, 17, 20, 21 and 22); each is offered
    per lot and switched on or off in the builder.
    """

    COVER = "cover"
    INTRO = "intro"
    AUCTION_INFO = "auction_info"
    LOT_TABLE = "lot_table"
    LOT = "lot"
    LOT_FEATURES = "lot_features"
    EXTRA_INFO = "extra_info"
    BOUNDARIES = "boundaries"
    EXTRA_PHOTOS = "extra_photos"
    RENT_TABLE = "rent_table"
    TERMS = "terms"
    STEPS = "steps"
    CONTACT = "contact"


#: Roles whose pages repeat per property rather than appearing once.
PER_LOT_ROLES = frozenset(
    {
        PageRole.LOT,
        PageRole.LOT_FEATURES,
        PageRole.EXTRA_INFO,
        PageRole.BOUNDARIES,
        PageRole.EXTRA_PHOTOS,
        PageRole.RENT_TABLE,
    }
)


class MapError(RuntimeError):
    """The export does not match the map that claims to describe it."""


@dataclass(frozen=True)
class SourcePage:
    """One page of the designer's export, and what the build should do with it."""

    index: int
    role: PageRole
    name: str
    #: Pages sharing a slot are alternatives the builder offers as a choice.
    #: The cover slot holds the six brand-guide covers plus the blank carrier.
    slot: str = ""
    #: For LOT pages: "standard" (قياسي) or "tower" (برج/عمارة).
    layout: str = ""
    optional: bool = False
    default_on: bool = True
    #: Which entry of the build script's RULES table applies to this page.
    rules: str = ""
    #: Normalised substrings that must be present / absent. Empty means the page
    #: carries no text MuPDF can read back, so position is all we can check.
    expect: tuple[str, ...] = ()
    forbid: tuple[str, ...] = ()
    #: Set where a variant reuses another variant's artwork because its own has
    #: not been supplied. Recorded so the swap is a one-line map edit.
    needs_artwork: str = ""
    #: Where this page's export draws the selling agent's lockup, in 0..1 of the
    #: page, as regions of (x0, y0, x1, y1). A page may carry more than one --
    #: the contact page prints the agent's mark large at the top, where the guide
    #: puts شعار وكيل البيع, as well as small in the footer.
    #:
    #: Normally nothing: the build finds the mark by the silhouette that recurs
    #: across the booklet, which is what makes it the agent's rather than a
    #: heading. That test needs a booklet. A page grafted out of another export
    #: is two or three pages, and the electronic export's lockup is not a
    #: candidate either sweep returns — so on those pages the region is stated
    #: instead, and the build takes the *ink actually inside it* rather than the
    #: band itself. Measured, not guessed, and deliberately nowhere near the
    #: Infath mark on the opposite side of the same footer.
    agent_mark: tuple[tuple[float, float, float, float], ...] = ()
    #: Regions of this page that this variant does not have, in 0..1 of the
    #: page, as (x0, y0, x1, y1).
    #:
    #: One template's artwork can carry a fact another's auction does not. The
    #: إلكتروني booklet is drawn on the هجين معلومات التواصل page, which names a
    #: venue and prints a code to it — and an electronic auction is held
    #: nowhere. The guide agrees: its إلكتروني card draws التاريخ، اسم المنصة،
    #: الوقت and no قاعة المزاد at all.
    #:
    #: Removing is not the same as leaving a field empty. Nothing draws over
    #: these, so the bake would not clear them and the page would print a
    #: location pin over nothing and a code leading to a hall that does not
    #: exist. Measured off the artwork and stated here, the way ``agent_mark``
    #: is, because no test can find a thing by its absence.
    remove: tuple[tuple[float, float, float, float], ...] = ()
    #: Which output this page is drawn for, where the designer drew two.
    #:
    #: The lot pages are drawn twice: once for print, with a QR code under each
    #: link chip and the four chips in a 2x2 block, and once for a screen, where
    #: a chip is clicked rather than scanned so it needs no code and the four
    #: stand in a single column. Guide pages 14 and 18 are «تفاصيل العقار (نسخة
    #: إلكترونية)» and page 19 «(نسخة الطباعة)»; the exports carry both.
    #:
    #: "" is the printed drawing, which is what a booklet uses unless its output
    #: says otherwise. A page marked "electronic" is not a page of the booklet
    #: in its own right -- it never appears in the builder and is not a layout
    #: anyone chooses. It replaces the page of the same role and layout at
    #: render time, when the output is a screen PDF.
    flavour: str = ""
    #: Which export this page is cut from, when it is not the map's own.
    #:
    #: A template is normally one export, and this is empty. It is not always:
    #: the electronic booklet arrived as a finished auction rather than a blank
    #: template, so it carries its own معلومات المزاد and شروط الدخول — the two
    #: pages that were being borrowed — but no برج layout and none of three
    #: optional pages. Grafting the two it has beats rebuilding from it and
    #: losing the four it has not. The value is a `SourceMap.source` stem.
    source: str = ""

    @property
    def is_lot(self) -> bool:
        return self.role is PageRole.LOT


@dataclass(frozen=True)
class SourceMap:
    """One template, cut from one export."""

    slug: str
    name: str
    variant: str
    #: Page count of the export this map describes -- the cheapest way to notice
    #: that a revision renumbered everything.
    source_pages: int
    pages: tuple[SourcePage, ...] = ()
    #: The same pages drawn for a screen, where the designer drew them twice.
    #:
    #: Kept apart from ``pages`` rather than listed among them, and appended to
    #: the built document last, so that adding them moves no page index a
    #: booklet already points at -- the same reason the navy summary and the six
    #: covers are appended rather than inserted. A project freezes the pages a
    #: property occupies on its node; renumbering them would repoint every
    #: booklet ever built at the wrong artwork.
    flavours: tuple[SourcePage, ...] = ()
    covers: tuple[Path, ...] = field(default=())
    #: A distinctive part of the export's filename.
    #:
    #: Page count alone stopped identifying an export the moment a second
    #: 16-page booklet arrived: the حضوري export and the electronic one both
    #: have sixteen, and a search by count returns whichever the filesystem
    #: happens to sort first. One of the two templates would then have been
    #: built, silently, from the other's artwork.
    source: str = ""

    def twin_of(self) -> dict[int, int]:
        """Which page each flavour twin stands in for.

        Maps the twin's offset in ``flavours`` to the *position* of the page it
        replaces. A twin is paired by role and layout, which is the pair that
        names a lot page: «صفحة العقار — قياسي» drawn for print and the same
        page drawn for a screen.

        Where the twin actually lands in the document is the build's business:
        it appends them last, after the covers, so the answer is an offset here
        rather than an index.
        """
        default = {
            (p.role, p.layout): position
            for position, p in enumerate(self.pages)
            if not p.flavour
        }
        out: dict[int, int] = {}
        for offset, twin in enumerate(self.flavours):
            at = default.get((twin.role, twin.layout))
            if at is None:
                raise MapError(
                    f"{self.slug}: {twin.name!r} is drawn for {twin.flavour!r} "
                    f"but no page of role {twin.role.value!r} and layout "
                    f"{twin.layout!r} is drawn for print"
                )
            out[offset] = at
        return out

    def __post_init__(self) -> None:
        # An index only means anything against the export it indexes, so two
        # pages may share a number as long as they come from different ones.
        seen: set[tuple[str, int]] = set()
        for page in (*self.pages, *self.flavours):
            at = (page.source, page.index)
            if at in seen:
                where = f" of {page.source}" if page.source else ""
                raise MapError(
                    f"{self.slug}: source page {page.index}{where} listed twice"
                )
            seen.add(at)
        if not any(p.role is PageRole.LOT for p in self.pages):
            raise MapError(f"{self.slug}: a booklet needs at least one lot page")

    @property
    def extra_sources(self) -> tuple[str, ...]:
        """Exports other than this map's own that its pages are cut from."""
        return tuple(sorted({p.source for p in self.pages if p.source}))

    @property
    def indices(self) -> list[int]:
        """Source pages this template keeps, in booklet order."""
        return [p.index for p in self.pages]

    def by_role(self, role: PageRole) -> list[SourcePage]:
        return [p for p in self.pages if p.role is role]

    def lot_layouts(self) -> dict[str, SourcePage]:
        return {p.layout: p for p in self.pages if p.is_lot}


def assert_map(
    doc: fitz.Document,
    source_map: SourceMap,
    extra: dict[str, fitz.Document] | None = None,
) -> None:
    """Fail loudly if the export is not the one the map describes.

    Called before anything is derived. A silently wrong cut is far more
    expensive than a failed build: the electronic booklet would print the
    in-person lot pages and nobody downstream would notice.

    ``extra`` holds the other exports a map's pages are cut from, by name. A
    grafted page is checked against the export it actually comes from — checking
    it against the map's own would read a different page entirely.
    """
    if doc.page_count != source_map.source_pages:
        raise MapError(
            f"{source_map.slug}: map describes a {source_map.source_pages}-page "
            f"export, this one has {doc.page_count}"
        )

    others = extra or {}
    missing = [name for name in source_map.extra_sources if name not in others]
    if missing:
        raise MapError(f"{source_map.slug}: no export supplied for {missing}")

    for page in (*source_map.pages, *source_map.flavours):
        book = others[page.source] if page.source else doc
        if page.index >= book.page_count:
            raise MapError(
                f"{source_map.slug}: source page {page.index} is past the end "
                f"of {page.source or 'its export'}"
            )
        text = normalise(book[page.index].get_text())
        for marker in page.expect:
            if normalise(marker) not in text:
                raise MapError(
                    f"{source_map.slug}: source page {page.index} should be "
                    f"{page.role.value} ({page.name}) but does not carry "
                    f"{marker!r}"
                )
        for marker in page.forbid:
            if normalise(marker) in text:
                raise MapError(
                    f"{source_map.slug}: source page {page.index} should be "
                    f"{page.role.value} ({page.name}) but carries {marker!r}"
                )
