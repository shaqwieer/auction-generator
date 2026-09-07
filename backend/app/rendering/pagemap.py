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
    covers: tuple[Path, ...] = field(default=())

    def __post_init__(self) -> None:
        seen: set[int] = set()
        for page in self.pages:
            if page.index in seen:
                raise MapError(f"{self.slug}: source page {page.index} listed twice")
            seen.add(page.index)
        if not any(p.role is PageRole.LOT for p in self.pages):
            raise MapError(f"{self.slug}: a booklet needs at least one lot page")

    @property
    def indices(self) -> list[int]:
        """Source pages this template keeps, in booklet order."""
        return [p.index for p in self.pages]

    def by_role(self, role: PageRole) -> list[SourcePage]:
        return [p for p in self.pages if p.role is role]

    def lot_layouts(self) -> dict[str, SourcePage]:
        return {p.layout: p for p in self.pages if p.is_lot}


def assert_map(doc: fitz.Document, source_map: SourceMap) -> None:
    """Fail loudly if the export is not the one the map describes.

    Called before anything is derived. A silently wrong cut is far more
    expensive than a failed build: the electronic booklet would print the
    in-person lot pages and nobody downstream would notice.
    """
    if doc.page_count != source_map.source_pages:
        raise MapError(
            f"{source_map.slug}: map describes a {source_map.source_pages}-page "
            f"export, this one has {doc.page_count}"
        )

    for page in source_map.pages:
        text = normalise(doc[page.index].get_text())
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
