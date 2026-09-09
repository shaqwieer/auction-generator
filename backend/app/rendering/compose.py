"""Turn a plan plus N data records into a page sequence.

There are two plans, and both end in the same list of :class:`PageInstance`.

``compose`` walks a template's *section* plan: fixed runs, a summary table that
paginates, and a repeating block per lot. The repeating unit is a page *range*
with ``pages_per_item``, not a page, because the auction booklet gives each lot
more than one page.

``compose_plan`` walks a *project's* page plan instead -- the booklet a client
assembled in the builder, where one property takes the برج layout and its
neighbour قياسي, where the lease table is on for one and off for the next, and
where pages have been duplicated, moved and deleted. A section plan cannot
express any of that. A project without a page plan still goes through
``compose``, unchanged.

Both take plain dictionaries; nothing in this package touches the database.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from .base import PageInstance, SectionKind


@dataclass
class Section:
    """A contiguous run of template pages and how it repeats."""

    kind: SectionKind
    first_page: int
    last_page: int
    name: str = ""
    pages_per_item: int = 1
    rows_per_page: int = 1
    variant: str | None = None  # e.g. "hybrid" -- skipped for other variants

    def __post_init__(self) -> None:
        if self.last_page < self.first_page:
            raise ValueError(
                f"section {self.name!r}: last_page {self.last_page} precedes "
                f"first_page {self.first_page}"
            )
        span = self.last_page - self.first_page + 1
        if self.kind is SectionKind.PER_RECORD and self.pages_per_item != span:
            raise ValueError(
                f"section {self.name!r}: pages_per_item={self.pages_per_item} "
                f"does not match its {span}-page range"
            )

    @property
    def pages(self) -> list[int]:
        return list(range(self.first_page, self.last_page + 1))


def compose(
    sections: list[Section],
    records: list[dict[str, Any]],
    *,
    static_values: dict[str, Any] | None = None,
    variant: str | None = None,
) -> list[PageInstance]:
    """Expand the plan into one :class:`PageInstance` per output page.

    ``static_values`` are the project-level fields the manual-entry screen calls
    "بيانات ثابتة تظهر على كل صفحة" -- they are merged into every page, and a
    record's own values win on conflict.
    """
    static = dict(static_values or {})
    out: list[PageInstance] = []

    for section in sections:
        if section.variant and section.variant != variant:
            continue

        if section.kind is SectionKind.FIXED:
            for page in section.pages:
                out.append(PageInstance(template_page_index=page, values=dict(static)))

        elif section.kind is SectionKind.PER_RECORD:
            for index, record in enumerate(records):
                values = {**static, **record}
                for page in section.pages:
                    out.append(
                        PageInstance(
                            template_page_index=page,
                            values=values,
                            record_index=index,
                        )
                    )

        elif section.kind is SectionKind.TABLE:
            per_page = max(1, section.rows_per_page)
            page_count = max(1, math.ceil(len(records) / per_page))
            template_pages = section.pages
            for chunk in range(page_count):
                rows = records[chunk * per_page : (chunk + 1) * per_page]
                # A table longer than its designed run reuses the last page's art.
                page = template_pages[min(chunk, len(template_pages) - 1)]
                out.append(
                    PageInstance(
                        template_page_index=page,
                        values={
                            **static,
                            "__rows__": rows,
                            "__row_offset__": chunk * per_page,
                        },
                    )
                )

    return out


def page_count(
    sections: list[Section], record_count: int, *, variant: str | None = None
) -> int:
    """Predicted page count -- the wizard shows this before generating."""
    total = 0
    for section in sections:
        if section.variant and section.variant != variant:
            continue
        span = section.last_page - section.first_page + 1
        if section.kind is SectionKind.FIXED:
            total += span
        elif section.kind is SectionKind.PER_RECORD:
            total += span * record_count
        elif section.kind is SectionKind.TABLE:
            total += max(1, math.ceil(record_count / max(1, section.rows_per_page)))
    return total


# --------------------------------------------------------------- page plans

# A plan node's ``kind``. Plain strings, because the plan is JSONB the API hands
# straight to the browser and takes back again.
PAGE = "page"
LOT = "lot"
TABLE = "table"

#: A node the client has switched off. It stays in the plan, keeping its values,
#: its layout and its place in the order, and prints nothing until it is
#: switched back on. Deleting a page a client spent ten minutes filling in
#: because they wanted it out of *this* issue is a loss they cannot undo.
OFF = "off"

#: The lease chip on a property page leads to that property's بيان عقود الإيجار,
#: and the guide only uses that page «في حال وجود عقود إيجارية للأصل». A code
#: leading to a page the booklet does not contain is worse than no code, so the
#: chip is drawn only where the page is.
RENT_LINK_KEY = "__lease_link"
RENT_ROLE = "rent_table"

#: A property's lease contracts, typed row by row on its own lease page. Unlike
#: بيان العقارات — which builds itself from the booklet's properties — nothing
#: else in the system knows what leases an asset carries, so they are entered
#: and they are kept on the property that has them.
LEASE_ROWS_KEY = "__lease__"


def enabled(node: dict[str, Any]) -> bool:
    return not node.get(OFF)


def _merged(
    static: dict[str, Any],
    node: dict[str, Any],
    record: dict[str, Any] | None,
) -> dict[str, Any]:
    """Project values, then the page's own, then the record's.

    A node's own values are how the optional pages get filled at all: the lease
    table, the boundaries page and the contact page carry values belonging
    neither to one property nor to the project as a whole. A record still wins,
    so importing a spreadsheet overrides what was typed onto the page.
    """
    values = {**static, **(node.get("values") or {})}
    if record:
        values.update(record)
    return values


#: Written into every page's values; see ``overlay.DEFAULTS_KEY``.
DEFAULTS_KEY = "__booklet__"

#: Facts that belong to the issue rather than to any one page. They are typed
#: once -- on the auction-info page -- and other pages print them again; the
#: steps page names both, and asking for them a third time there would be
#: asking twice for one fact.
BOOKLET_KEYS: tuple[str, ...] = ("auction_title", "platform_name")


def booklet_facts(
    static: dict[str, Any],
    nodes: list[dict[str, Any]],
    project_name: str = "",
) -> dict[str, str]:
    """What the booklet knows about itself, for a field that defaults from it.

    Which node carries a fact is not fixed -- ``auction_title`` is drawn on the
    cover *and* on the auction-info page, and the two can disagree while
    somebody is halfway through correcting one of them. The first non-empty
    value in booklet order wins, which is the one nearest the front and so the
    one the client has been reading from.

    ``auction_title`` always resolves to something: a booklet whose printed
    title has not been given yet still has the name the project was created
    with, and «إختيار مزاد (  )» is worse on paper than a working title.
    """
    facts: dict[str, str] = {"project_name": project_name.strip()}
    for key in BOOKLET_KEYS:
        value = str(static.get(key) or "").strip()
        if not value:
            for node in nodes:
                candidate = str((node.get("values") or {}).get(key) or "").strip()
                if candidate:
                    value = candidate
                    break
        facts[key] = value
    if not facts["auction_title"]:
        facts["auction_title"] = facts["project_name"]
    return facts


def compose_plan(
    nodes: list[dict[str, Any]],
    records: dict[int, dict[str, Any]],
    *,
    static_values: dict[str, Any] | None = None,
    lease_pages: dict[int, int] | None = None,
    project_name: str = "",
) -> list[PageInstance]:
    """The pages a plan produces, in booklet order."""
    return [
        page
        for _, page in compose_plan_indexed(
            nodes,
            records,
            static_values=static_values,
            lease_pages=lease_pages,
            project_name=project_name,
        )
    ]


def compose_plan_indexed(
    nodes: list[dict[str, Any]],
    records: dict[int, dict[str, Any]],
    *,
    static_values: dict[str, Any] | None = None,
    only: str | None = None,
    lease_pages: dict[int, int] | None = None,
    project_name: str = "",
) -> list[tuple[str, PageInstance]]:
    """Expand a project's page plan into one :class:`PageInstance` per page.

    Each page comes back paired with the id of the node that produced it, so
    the builder can preview one node without re-deriving where its pages
    landed. The summary table's rows and offsets depend on every property in
    the booklet, so a node's pages can only be found by composing the whole
    plan and then picking them out.

    ``records`` is keyed by row index rather than ordered, because a plan refers
    to a property by the row it came from: reordering the booklet must move the
    pages, not repoint them at a different property.

    The summary table stays one node and expands here, so its rows come out in
    the order the properties are actually in, and the page repeats for each
    further ten -- «فيتم تكرار الصفحة», which is what the guide says to do with a
    list too long for one. ``rows_per_page`` rides on the node, and a wrong
    value silently drops every row past the first page.
    """
    static = dict(static_values or {})
    # A property that is switched off leaves the summary table as well as the
    # booklet. Skipping only its pages would print a row for a property whose
    # page is not in the booklet.
    ordered_rows = [
        records[node["row"]]
        for node in nodes
        if node.get("kind") == LOT
        and enabled(node)
        and node.get("row") in records
    ]

    out: list[tuple[str, PageInstance]] = []
    for node in nodes:
        kind = node.get("kind", PAGE)
        owner = str(node.get("id", ""))
        # ``only`` draws one node whatever its state, so the builder can still
        # show a switched-off page to whoever is deciding to switch it back on.
        if not enabled(node) and owner != only:
            continue

        if kind == PAGE:
            out.append((
                owner,
                PageInstance(
                    template_page_index=int(node["page"]),
                    values=_merged(static, node, None),
                ),
            ))

        elif kind == LOT:
            record = records.get(node.get("row"))
            if record is None:
                # A lot whose row was deleted leaves its pages out rather than
                # printing an empty property.
                continue
            values = _merged(static, node, record)
            leases = node.get("values", {}).get(LEASE_ROWS_KEY) or []
            if RENT_ROLE not in (node.get("options") or []):
                # No lease page for this property, so nothing for its lease chip
                # to lead to. An empty value draws neither the code nor the link.
                values = {k: v for k, v in values.items() if k != RENT_LINK_KEY}
            for page in node.get("pages", []):
                per_page = (lease_pages or {}).get(int(page))
                if per_page:
                    # The lease page draws this property's contracts, not the
                    # booklet's properties, so it carries its own rows -- and it
                    # repeats for each further blockful, the way the summary
                    # page does for each further ten properties. «فيتم تكرار
                    # الصفحة» is the guide's answer to a list longer than a
                    # page, and it is the same answer here: the same artwork
                    # again, numbering carrying on where it left off, and the
                    # last of them ruled only for the leases it actually has.
                    per_page = max(1, int(per_page))
                    # One page even with nothing on it: the operator has
                    # switched the page on and needs somewhere to type.
                    sheets = max(1, math.ceil(len(leases) / per_page))
                    for sheet in range(sheets):
                        out.append((
                            owner,
                            PageInstance(
                                template_page_index=int(page),
                                values={
                                    **values,
                                    "__rows__": leases[
                                        sheet * per_page : (sheet + 1) * per_page
                                    ],
                                    "__row_offset__": sheet * per_page,
                                },
                                record_index=node["row"],
                            ),
                        ))
                    continue
                out.append((
                    owner,
                    PageInstance(
                        template_page_index=int(page),
                        values=values,
                        record_index=node["row"],
                    ),
                ))

        elif kind == TABLE:
            per_page = max(1, int(node.get("rows_per_page", 1)))
            chunks = max(1, math.ceil(len(ordered_rows) / per_page))
            base = _merged(static, node, None)
            for chunk in range(chunks):
                out.append((
                    owner,
                    PageInstance(
                        template_page_index=int(node["page"]),
                        values={
                            **base,
                            "__rows__": ordered_rows[
                                chunk * per_page : (chunk + 1) * per_page
                            ],
                            "__row_offset__": chunk * per_page,
                        },
                    ),
                ))

    _point_lease_chips_at_their_page(out, lease_pages)
    # Every page carries the booklet's own facts, under a reserved key so that
    # knowing a name never causes a page to print it -- only a field whose
    # ``default_value`` asks for it does.
    facts = booklet_facts(static, nodes, project_name)
    for _, page in out:
        page.values[DEFAULTS_KEY] = facts
    return out


#: Written beside a link's own value; see ``overlay.GOTO_PREFIX``.
GOTO_PREFIX = "__goto_"


def _point_lease_chips_at_their_page(
    pages: list[tuple[str, PageInstance]], lease_pages: dict[int, int] | None
) -> None:
    """Send each property's lease chip to that property's lease page.

    Only composing can work this out: the destination is an output page number,
    and output page numbers are what composing produces. Which template page is
    the lease one comes from the caller, because the template is the only thing
    that knows.

    On paper the chip still prints a code carrying the permanent address — a
    printed code cannot jump to a page.
    """
    if not lease_pages:
        return
    landing: dict[int, int] = {}
    for number, (_, page) in enumerate(pages):
        if page.record_index is None:
            continue
        if page.template_page_index not in lease_pages:
            continue
        # The first of them. A property with more leases than one page holds now
        # has several, and the chip leads to where its table starts.
        landing.setdefault(page.record_index, number)
    for _, page in pages:
        destination = landing.get(page.record_index)
        if destination is not None:
            # Set whether or not an address was typed. The chip's job is to lead
            # to that property's lease page, and the booklet knows where that is
            # — nobody should have to look up a URL for a page they are holding.
            # An address, where one is given, is what the printed code carries.
            page.values[f"{GOTO_PREFIX}{RENT_LINK_KEY}"] = destination


def page_count_plan(
    nodes: list[dict[str, Any]],
    record_rows: set[int],
    lease_pages: dict[int, int] | None = None,
) -> int:
    """Predicted page count for a plan -- the review step shows this.

    ``lease_pages`` says how many contracts each lease page holds, so a property
    with more of them than one page fits is counted for all the pages it takes.
    Without it every property counts for one, which is what the plan says and
    not what the booklet does.
    """
    lots = sum(
        1
        for n in nodes
        if n.get("kind") == LOT and enabled(n) and n.get("row") in record_rows
    )
    total = 0
    for node in nodes:
        if not enabled(node):
            continue
        kind = node.get("kind", PAGE)
        if kind == PAGE:
            total += 1
        elif kind == LOT:
            if node.get("row") in record_rows:
                leases = len(
                    (node.get("values") or {}).get(LEASE_ROWS_KEY) or []
                )
                for page in node.get("pages", []):
                    per_page = (lease_pages or {}).get(int(page))
                    total += (
                        max(1, math.ceil(leases / max(1, int(per_page))))
                        if per_page
                        else 1
                    )
        elif kind == TABLE:
            per_page = max(1, int(node.get("rows_per_page", 1)))
            total += max(1, math.ceil(lots / per_page))
    return total
