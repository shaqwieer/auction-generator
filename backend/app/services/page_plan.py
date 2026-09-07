"""The booklet a client assembles, and the operations the builder performs on it.

A project's ``page_plan`` is an ordered list of nodes. Each is one output page,
one property's pages, or the summary table:

    {"id": "n5", "kind": "lot", "row": 0, "layout": "tower",
     "pages": [6, 11], "options": ["boundaries"], "values": {}}

Three rules hold the whole thing together.

**A lot node names its property by row index, not by position.** Moving a page
must move the page, never repoint it at a different property.

**A lot node stores its resolved pages.** They are derived from the template's
page rows when the layout is set, and then frozen. A template revision must not
silently reshuffle a booklet somebody is halfway through assembling.

**The summary table is one node that expands at render time.** It is the only
node that is not one-to-one with an output page, which is also why it cannot be
duplicated, moved or deleted: its row numbering runs across every property in
the booklet, and nothing downstream would notice it being wrong.

Every mutation reassigns ``page_plan`` wholesale and bumps ``revision``.
SQLAlchemy does not track an in-place edit of a JSONB column, and a page move
landing while a debounced value patch is in flight would otherwise lose one of
them silently.
"""

from __future__ import annotations

import uuid
from typing import Any

from app.models import DataRecord, Project, Template, TemplatePage
from app.rendering.base import FieldType, PageInstance
from app.rendering.compose import (
    LOT,
    OFF,
    PAGE,
    TABLE,
    compose_plan,
    compose_plan_indexed,
    page_count_plan,
)

PLAN_VERSION = 1

#: Roles that repeat once per property. The first is the property page itself;
#: the rest are the optional pages the guide adds حسب الحاجة.
LOT_ROLE = "lot"
OPTIONAL_ROLES = (
    "lot_features",
    "extra_info",
    "boundaries",
    "extra_photos",
    "rent_table",
)

#: The slot the summary page's two colourways share, the way the covers share
#: theirs. The brand guide draws «بيان العقارات» in teal and in navy; they are
#: the same ten-row table in two colours, not twenty rows in two halves.
TABLE_SLOT = "lot_table"
TABLE_ROLE = "lot_table"


class PlanError(ValueError):
    """The plan cannot be changed that way. Carries an Arabic message."""


def _node_id() -> str:
    return uuid.uuid4().hex[:12]


def _pages(template: Template) -> list[TemplatePage]:
    return sorted(template.pages, key=lambda p: p.position)


def supports_plan(template: Template) -> bool:
    """Whether this template was built with page roles.

    Templates built before the builder have none, and their projects keep
    composing through the section plan.
    """
    return bool(template.pages)


def table_rows_per_page(template: Template, page_index: int) -> int:
    """How many rows the summary table holds on one page.

    Across every block on it, which on the summary page is one: its two blocks
    are the teal and navy colourways of the same ten rows and are built as two
    pages. A wrong number here silently drops the rows past the first page.
    """
    total = 0
    for field in template.fields:
        if field.page_index != page_index or field.type != FieldType.TABLE:
            continue
        spec = field.table_spec or {}
        total += int(spec.get("rows", 0))
    return total or 1


def covers(template: Template) -> list[TemplatePage]:
    """Every page that can serve as the booklet's cover, in order."""
    return [p for p in _pages(template) if p.slot == "cover"]


def cover_designs(template: Template) -> list[TemplatePage]:
    """The covers a client may actually choose: the six the guide draws.

    The export's own cover page holds the cover slot so the booklet's cover
    lands where the designer put it, but it is غلاف 1 drawn a second time and is
    not offered as a seventh tile.
    """
    return [
        page
        for page in covers(template)
        if not page.options.get("source_cover")
        and not page.options.get("own_artwork")
    ]


def default_cover(template: Template) -> int | None:
    """Which cover a booklet starts wearing."""
    offered = cover_designs(template) or covers(template)
    return offered[0].page_index if offered else None


def table_colourways(template: Template) -> list[TemplatePage]:
    """The summary page in each colour the designer drew it in."""
    return [p for p in _pages(template) if p.slot == TABLE_SLOT]


def lot_layouts(template: Template) -> dict[str, TemplatePage]:
    return {p.layout: p for p in _pages(template) if p.role == LOT_ROLE and p.layout}


LEASE_SLOT = "rent_table"
LEASE_ROWS_KEY = "__lease__"


def optional_pages(template: Template) -> list[TemplatePage]:
    """The per-property pages the builder can switch on, one per role.

    One per role because a page drawn in two colours is still one page of the
    booklet: بيان عقود الإيجار comes in navy and teal, and offering both would
    put both into every property that turns the lease page on.
    """
    seen: set[str] = set()
    out: list[TemplatePage] = []
    for page in _pages(template):
        if not page.is_optional or page.options.get("needs_artwork"):
            continue
        if page.role in seen:
            continue
        seen.add(page.role)
        out.append(page)
    return out


def lease_pages(template: Template) -> list[TemplatePage]:
    """بيان عقود الإيجار in each colour the booklet offers it in."""
    return [p for p in _pages(template) if p.role == LEASE_SLOT]


def lease_page_for(template: Template, colourway: str) -> int | None:
    """Which lease page a booklet in this colour uses."""
    pages = lease_pages(template)
    for page in pages:
        if page.layout == colourway:
            return page.page_index
    return pages[0].page_index if pages else None


def default_layout(template: Template) -> str:
    layouts = lot_layouts(template)
    return "standard" if "standard" in layouts else next(iter(layouts), "")


def resolve_lot_pages(
    template: Template,
    layout: str,
    options: list[str],
    lease_page: int | None = None,
) -> list[int]:
    """The template pages one property occupies, in booklet order."""
    layouts = lot_layouts(template)
    chosen = layouts.get(layout)
    if chosen is None:
        raise PlanError(f"لا يوجد تخطيط باسم «{layout}» في هذا القالب.")
    wanted = set(options)
    pages = [chosen.page_index]
    for page in optional_pages(template):
        if page.role not in wanted:
            continue
        # The lease page comes in two colours and the booklet picks one.
        if page.role == LEASE_SLOT and lease_page is not None:
            pages.append(lease_page)
        else:
            pages.append(page.page_index)
    return pages


def _lot_node(
    template: Template,
    row: int,
    layout: str,
    options: list[str],
    lease_page: int | None = None,
) -> dict:
    return {
        "id": _node_id(),
        "kind": LOT,
        "row": row,
        "layout": layout,
        "options": list(options),
        "pages": resolve_lot_pages(template, layout, options, lease_page),
        "values": {},
    }


def set_lease_colourway(project: Project, template: Template, colourway: str) -> dict:
    """Print every lease page in this booklet in the other colour.

    One choice for the booklet rather than one per property: two lease pages in
    two colours in the same document is not a preference, it is a mistake. The
    pages a property occupies are frozen on its node, so they are re-resolved
    here rather than left to drift.
    """
    if colourway not in ("blue", "green"):
        raise PlanError("لون الجدول غير معروف.")
    project.lease_colourway = colourway
    chosen = lease_page_for(template, colourway)
    plan = project.page_plan
    if not plan or chosen is None:
        return plan or {}
    offered = {p.page_index for p in lease_pages(template)}
    nodes = []
    for node in plan["nodes"]:
        if node.get("kind") != LOT:
            nodes.append(node)
            continue
        nodes.append({
            **node,
            "pages": [
                chosen if page in offered else page
                for page in node.get("pages", [])
            ],
        })
    return _commit(project, nodes, int(plan.get("revision", 0)))


def default_plan(
    template: Template, *, rows: list[int], cover_page: int | None = None
) -> dict[str, Any]:
    """The booklet a client starts from: every fixed page, in the designer's order.

    The lot nodes go where the first lot page sits in the template, which is
    also where the alternatives and the optional per-property pages sit -- all
    of those are skipped here, because which of them a property uses is the
    plan's business, not the template's.
    """
    layout = default_layout(template)
    turned_on = [p.role for p in optional_pages(template) if p.default_on]

    nodes: list[dict[str, Any]] = []
    lots_placed = False
    cover_done = False
    table_done = False
    cover_default = default_cover(template)

    for page in _pages(template):
        if page.slot == "cover":
            if cover_done:
                continue
            chosen = cover_page
            if chosen is None:
                chosen = cover_default if cover_default is not None else page.page_index
            nodes.append(
                {"id": _node_id(), "kind": PAGE, "page": int(chosen),
                 "slot": "cover", "values": {}}
            )
            cover_done = True
            continue

        if page.role == LOT_ROLE or page.is_optional:
            if not lots_placed and layout:
                nodes.extend(
                    _lot_node(template, row, layout, turned_on) for row in rows
                )
                lots_placed = True
            continue

        if page.role == TABLE_ROLE:
            # Both colourways are pages with this role. One summary table.
            if table_done:
                continue
            colourways = table_colourways(template)
            chosen_page = (
                colourways[0].page_index if colourways else page.page_index
            )
            nodes.append({
                "id": _node_id(),
                "kind": TABLE,
                "page": chosen_page,
                "slot": TABLE_SLOT,
                "rows_per_page": table_rows_per_page(template, chosen_page),
                "values": {},
            })
            table_done = True
            continue

        nodes.append(
            {"id": _node_id(), "kind": PAGE, "page": page.page_index, "values": {}}
        )

    if not lots_placed and layout:
        nodes.extend(_lot_node(template, row, layout, turned_on) for row in rows)

    return {"version": PLAN_VERSION, "revision": 1, "nodes": nodes}


# --------------------------------------------------------------- mutations


def _plan(project: Project) -> dict[str, Any]:
    plan = project.page_plan
    if not plan:
        raise PlanError("هذا المشروع لا يستخدم الباني.")
    return plan


def _find(plan: dict[str, Any], node_id: str) -> tuple[int, dict[str, Any]]:
    for position, node in enumerate(plan["nodes"]):
        if node["id"] == node_id:
            return position, node
    raise PlanError("الصفحة غير موجودة في الكتيّب.")


def _guard_table(node: dict[str, Any]) -> None:
    if node.get("kind") == TABLE:
        raise PlanError(
            "جدول العقارات يُحسب تلقائيًا — لا يمكن نسخه أو نقله أو حذفه."
        )


def _commit(project: Project, nodes: list[dict[str, Any]], revision: int) -> dict:
    # Reassigned rather than mutated: SQLAlchemy does not see an in-place edit
    # of a JSONB column, so an in-place change would simply not be saved.
    project.page_plan = {
        "version": PLAN_VERSION,
        "revision": revision + 1,
        "nodes": nodes,
    }
    return project.page_plan


def check_revision(project: Project, revision: int | None) -> None:
    """Refuse a change built on a plan somebody else has already moved on from.

    The builder patches values on a debounce while the page rail can be
    reordering. Without this the later write wins and the reorder disappears
    with no error anywhere.
    """
    if revision is None:
        return
    current = int(_plan(project).get("revision", 0))
    if revision != current:
        raise PlanError("تم تعديل الكتيّب من مكان آخر — أعد تحميل الصفحة.")


def add_node(
    project: Project,
    template: Template,
    *,
    kind: str,
    after: str | None = None,
    page: int | None = None,
    row: int | None = None,
    layout: str | None = None,
) -> dict:
    plan = _plan(project)
    nodes = list(plan["nodes"])

    if kind == LOT:
        if row is None:
            raise PlanError("إضافة عقار تحتاج إلى صفّ بيانات.")
        chosen = layout or default_layout(template)
        turned_on = [p.role for p in optional_pages(template) if p.default_on]
        node = _lot_node(
            template, row, chosen, turned_on,
            lease_page_for(template, project.lease_colourway),
        )
    elif kind == PAGE:
        if page is None:
            raise PlanError("إضافة صفحة تحتاج إلى تحديد الصفحة.")
        node = {"id": _node_id(), "kind": PAGE, "page": int(page), "values": {}}
        # The slot comes with the page. Without it a swapped-in cover stopped
        # being a cover to everything downstream, and the chooser vanished after
        # the first choice.
        chosen = next(
            (p for p in _pages(template) if p.page_index == int(page)), None
        )
        if chosen is not None and chosen.slot:
            node["slot"] = chosen.slot
    else:
        raise PlanError("نوع الصفحة غير معروف.")

    if after is not None:
        at = _find(plan, after)[0] + 1
    elif kind == LOT:
        # A booklet starts with no properties and grows, so the first one is
        # usually added from whatever page is open -- the cover, as often as
        # not. It still belongs where the designer puts properties.
        at = _lot_anchor(nodes)
    else:
        at = len(nodes)
    nodes.insert(at, node)
    return _commit(project, nodes, int(plan.get("revision", 0)))


def _lot_anchor(nodes: list[dict[str, Any]]) -> int:
    """Where a new property belongs: after the last one, else after the summary
    table, else at the end."""
    anchor = len(nodes)
    for position, node in enumerate(nodes):
        if node.get("kind") in (LOT, TABLE):
            anchor = position + 1
    return anchor


def duplicate_node(
    project: Project, node_id: str, *, new_row: int | None = None
) -> dict:
    """Copy one entry of the booklet, immediately after itself.

    A duplicated property has to point at a *new* row. Two lot nodes sharing
    one record look right on the page rail but print that property twice in the
    summary table, once per node, because the table is built from the lots in
    plan order. The caller creates the record; this only repoints the copy.
    """
    plan = _plan(project)
    position, node = _find(plan, node_id)
    _guard_table(node)
    copy = {**node, "id": _node_id()}
    copy["values"] = dict(node.get("values") or {})
    if "pages" in node:
        copy["pages"] = list(node["pages"])
    if "options" in node:
        copy["options"] = list(node["options"])
    if node.get("kind") == LOT:
        if new_row is None:
            raise PlanError("نسخ العقار يحتاج إلى صفّ بيانات جديد.")
        copy["row"] = new_row
    nodes = list(plan["nodes"])
    nodes.insert(position + 1, copy)
    return _commit(project, nodes, int(plan.get("revision", 0)))


def move_node(project: Project, node_id: str, delta: int) -> dict:
    plan = _plan(project)
    position, node = _find(plan, node_id)
    _guard_table(node)
    target = position + (1 if delta > 0 else -1)
    nodes = list(plan["nodes"])
    if not 0 <= target < len(nodes):
        raise PlanError("الصفحة في طرف الكتيّب بالفعل.")
    if nodes[target].get("kind") == TABLE:
        raise PlanError(
            "جدول العقارات يُحسب تلقائيًا — لا يمكن نقل صفحة عبره."
        )
    nodes[position], nodes[target] = nodes[target], nodes[position]
    return _commit(project, nodes, int(plan.get("revision", 0)))


def delete_node(project: Project, node_id: str) -> dict:
    plan = _plan(project)
    position, node = _find(plan, node_id)
    _guard_table(node)
    nodes = list(plan["nodes"])
    del nodes[position]
    return _commit(project, nodes, int(plan.get("revision", 0)))


def set_enabled(project: Project, node_id: str, *, on: bool) -> dict:
    """Switch a page out of the booklet, or back into it.

    What a client means by removing a page is almost never "throw away what I
    typed onto it" -- it is "not this issue". So the node stays where it is with
    everything on it, prints nothing, and comes back the way it went.

    The summary table is the exception, for the reason it cannot be moved or
    deleted either: its rows are built from the booklet, and nothing downstream
    would notice it missing.
    """
    plan = _plan(project)
    position, node = _find(plan, node_id)
    _guard_table(node)
    nodes = list(plan["nodes"])
    updated = {key: value for key, value in node.items() if key != OFF}
    if not on:
        updated[OFF] = True
    nodes[position] = updated
    return _commit(project, nodes, int(plan.get("revision", 0)))


def set_layout(
    project: Project,
    template: Template,
    node_id: str,
    *,
    layout: str | None = None,
    options: list[str] | None = None,
    page: int | None = None,
) -> dict:
    """Switch a property between قياسي and برج, or toggle its optional pages.

    Also how the cover changes, and how the summary table changes colour. All
    three are the same act -- picking between pages the designer drew as
    alternatives for one place in the booklet -- so all three keep the node they
    are on, and with it everything typed onto that page.
    """
    plan = _plan(project)
    position, node = _find(plan, node_id)
    if node.get("kind") == PAGE and node.get("slot") == "cover":
        # Not add-then-delete: the booklet's cover is one page throughout, and
        # replacing the node lost whatever had been typed onto it, moved it in
        # the rail, and dropped the slot that made it a cover at all.
        offered = {p.page_index for p in cover_designs(template)}
        if page is None or int(page) not in offered:
            raise PlanError("هذا الغلاف غير متاح في هذا القالب.")
        nodes = list(plan["nodes"])
        nodes[position] = {**node, "page": int(page), "slot": "cover"}
        return _commit(project, nodes, int(plan.get("revision", 0)))
    if node.get("kind") == TABLE:
        offered = {p.page_index for p in table_colourways(template)}
        if page is None or int(page) not in offered:
            raise PlanError("هذا اللون غير متاح لجدول العقارات في هذا القالب.")
        nodes = list(plan["nodes"])
        nodes[position] = {
            **node,
            "page": int(page),
            "slot": TABLE_SLOT,
            "rows_per_page": table_rows_per_page(template, int(page)),
        }
        return _commit(project, nodes, int(plan.get("revision", 0)))
    if node.get("kind") != LOT:
        raise PlanError("التخطيط يخصّ صفحات العقار فقط.")
    chosen = layout or node.get("layout") or default_layout(template)
    turned_on = node.get("options", []) if options is None else options
    available = {p.role for p in optional_pages(template)}
    unknown = [role for role in turned_on if role not in available]
    if unknown:
        raise PlanError("صفحة اختيارية غير متاحة في هذا القالب.")
    updated = {
        **node,
        "layout": chosen,
        "options": list(turned_on),
        "pages": resolve_lot_pages(
            template, chosen, list(turned_on),
            lease_page_for(template, project.lease_colourway),
        ),
    }
    nodes = list(plan["nodes"])
    nodes[position] = updated
    return _commit(project, nodes, int(plan.get("revision", 0)))


def set_lease_rows(
    project: Project, node_id: str, rows: list[dict[str, Any]]
) -> dict:
    """The lease contracts a property carries, in the order they print.

    Kept on the property rather than derived from anything: nothing else in the
    system knows what leases an asset has. The order is the order given, so
    reordering here reorders the printed table.
    """
    plan = _plan(project)
    position, node = _find(plan, node_id)
    if node.get("kind") != LOT:
        raise PlanError("عقود الإيجار تخصّ صفحات العقار فقط.")
    cleaned = [
        {str(k): ("" if v is None else str(v)) for k, v in row.items()}
        for row in rows
    ]
    nodes = list(plan["nodes"])
    nodes[position] = {
        **node,
        "values": {**(node.get("values") or {}), LEASE_ROWS_KEY: cleaned},
    }
    return _commit(project, nodes, int(plan.get("revision", 0)))


def lease_rows(project: Project, node_id: str) -> list[dict[str, Any]]:
    plan = _plan(project)
    _, node = _find(plan, node_id)
    return list((node.get("values") or {}).get(LEASE_ROWS_KEY) or [])


def set_values(project: Project, node_id: str, values: dict[str, Any]) -> dict:
    """Merge values into one node, the way the record patch merges into a row."""
    plan = _plan(project)
    position, node = _find(plan, node_id)
    merged = {**(node.get("values") or {}), **values}
    nodes = list(plan["nodes"])
    nodes[position] = {**node, "values": merged}
    return _commit(project, nodes, int(plan.get("revision", 0)))


# ------------------------------------------------------------- composition


#: Where the booklet's branding lands, on every page the designer put a mark on.
BRAND_LOGO_KEY = "company_logo"
BRAND_NAME_KEY = "company_name"


def branding(project: Project) -> dict[str, Any]:
    """The company this booklet is printed for, as values the pages can draw.

    Two places, not one. The mark goes where the designer drew the selling
    agent's lockup — seventeen pages of it — and nothing else goes there: the
    guide prints a logo in that spot, never a name set in type, so a company
    with no logo leaves it empty rather than filling it with something the
    design never had. The name goes where the design has a name: the title on
    تعريف وكيل البيع.

    Computed here rather than stored on the project, so a company that uploads a
    logo this afternoon sees it on the booklet they started this morning. A
    value typed onto a page still wins — a node's values beat the project's.
    """
    client = project.client
    return {
        BRAND_LOGO_KEY: (client.logo_filename or "") if client else "",
        BRAND_NAME_KEY: (client.name or "") if client else "",
    }


def lease_page_indices(template: Template) -> set[int]:
    """Every page that is بيان عقود الإيجار, in either colour.

    The lease chip on a property page leads there, and on screen that is a jump
    to a page of the booklet rather than a trip to the web.
    """
    return {p.page_index for p in lease_pages(template)}


def _static(project: Project) -> dict[str, Any]:
    return {**dict(project.static_values or {}), **branding(project)}


def record_map(records: list[DataRecord]) -> dict[int, dict[str, Any]]:
    return {record.row_index: dict(record.values or {}) for record in records}


def to_instances(
    project: Project, records: list[DataRecord]
) -> list[PageInstance]:
    """The pages this project's plan produces, ready for the renderer."""
    plan = _plan(project)
    return compose_plan(
        plan["nodes"],
        record_map(records),
        static_values=_static(project),
        lease_pages=lease_page_indices(project.template),
    )


def instances_for_node(
    project: Project, records: list[DataRecord], node_id: str
) -> list[PageInstance]:
    """The pages one node produces, composed in the context of the whole plan.

    Composed whole rather than in isolation: the summary table's rows and
    offsets depend on every property in the booklet, not just this one.
    """
    plan = _plan(project)
    pages = [
        page
        for owner, page in compose_plan_indexed(
            plan["nodes"],
            record_map(records),
            static_values=_static(project),
            only=node_id,
            lease_pages=lease_page_indices(project.template),
        )
        if owner == node_id
    ]
    if not pages:
        raise PlanError("لا توجد صفحة لعرضها.")
    return pages


def predicted_pages(project: Project, records: list[DataRecord]) -> int:
    plan = project.page_plan
    if not plan:
        return 0
    return page_count_plan(plan["nodes"], {r.row_index for r in records})


def referenced_values(project: Project) -> dict[str, Any]:
    """Every value typed onto a page rather than into a record.

    Preflight and asset loading both walk this: a photo uploaded onto the cover
    lives here, not on any row, and would otherwise be reported missing and then
    silently dropped.
    """
    plan = project.page_plan or {}
    out: dict[str, Any] = {}
    for node in plan.get("nodes", []):
        out.update(node.get("values") or {})
    return out

def sync_lots(project: Project, template: Template, rows: list[int]) -> dict[str, Any]:
    """Give every data row a place in the booklet, and drop the ones that left.

    Importing a spreadsheet is an action inside the builder rather than a
    separate flow, so it has to land as pages. Rows that already have a node
    keep it -- with its layout, its optional pages and anything typed onto it --
    because re-importing a corrected sheet must not throw away a برج choice made
    for the third property.

    New nodes go where the lots already are, so an import lands in the middle of
    the booklet rather than after the closing pages.
    """
    plan = project.page_plan
    if not plan:
        return {}

    wanted = list(dict.fromkeys(rows))
    nodes = list(plan["nodes"])
    layout = default_layout(template)
    turned_on = [p.role for p in optional_pages(template) if p.default_on]

    kept = [n for n in nodes if n.get("kind") != LOT or n.get("row") in wanted]
    have = {n["row"] for n in kept if n.get("kind") == LOT}

    anchor = _lot_anchor(kept)

    lease = lease_page_for(template, project.lease_colourway)
    fresh = [
        _lot_node(template, row, layout, turned_on, lease)
        for row in wanted
        if row not in have and layout
    ]
    kept[anchor:anchor] = fresh
    return _commit(project, kept, int(plan.get("revision", 0)))
