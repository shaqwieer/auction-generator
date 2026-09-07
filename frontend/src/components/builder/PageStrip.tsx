"use client";

/**
 * The booklet as a list of pages, down the side, with what you can do to each.
 *
 * A property is one entry however many pages it takes, because that is how the
 * client thinks about it — moving "the third property" should move its
 * boundaries page with it.
 *
 * The summary table is drawn as one locked entry. Its row numbering runs
 * across every property in the booklet, so duplicating or reordering it would
 * break the numbering in a way nothing downstream would catch; the server
 * refuses those anyway, and showing them greyed is more honest than letting the
 * click fail.
 *
 * Nothing here removes a page. «إيقاف» takes it out of this issue and «استعادة»
 * puts it back, with everything typed on it still there — a client saying "not
 * this one" is not asking to lose the half hour they spent filling it in.
 */

import type { PagePlanNode, TemplatePageOut } from "@/types/api";

export interface StripEntry {
  node: PagePlanNode;
  title: string;
  subtitle: string;
  locked: boolean;
}

export function describe(
  node: PagePlanNode,
  pages: Map<number, TemplatePageOut>,
  lotNumber: number | null,
): StripEntry {
  if (node.kind === "table") {
    return {
      node,
      title: pages.get(node.page ?? -1)?.name ?? "جدول العقارات",
      subtitle: "تُحسب تلقائيًا",
      locked: true,
    };
  }
  if (node.kind === "lot") {
    const layout = pages.get(node.pages[0] ?? -1);
    const extra = node.pages.length - 1;
    return {
      node,
      title: `العقار ${String(lotNumber ?? 0).padStart(2, "0")}`,
      subtitle: extra
        ? `${layout?.name ?? ""} · +${extra} صفحة`
        : (layout?.name ?? ""),
      locked: false,
    };
  }
  const page = pages.get(node.page ?? -1);
  return {
    node,
    title: page?.name ?? `صفحة ${(node.page ?? 0) + 1}`,
    subtitle: node.slot === "cover" ? "الغلاف" : "",
    locked: false,
  };
}

export function PageStrip({
  entries,
  active,
  busy,
  onSelect,
  onDuplicate,
  onMove,
  onSetEnabled,
}: {
  entries: StripEntry[];
  active: string | null;
  busy: boolean;
  onSelect: (nodeId: string) => void;
  onDuplicate: (nodeId: string) => void;
  onMove: (nodeId: string, delta: number) => void;
  onSetEnabled: (nodeId: string, on: boolean) => void;
}) {
  // Switched-off pages keep their place in the list but are not counted, so the
  // numbers down the side stay the page numbers the booklet will actually have.
  let printed = 0;
  return (
    <ol className="divide-y divide-line border border-line bg-surface">
      {entries.map((entry, index) => {
        const selected = active === entry.node.id;
        const off = Boolean(entry.node.off);
        if (!off) printed += 1;
        return (
          <li
            key={entry.node.id}
            className={selected ? "bg-[#FCE8F2]" : "bg-surface"}
          >
            <div className="flex items-center gap-2 px-3 py-2">
              <button
                type="button"
                onClick={() => onSelect(entry.node.id)}
                className={`min-w-0 flex-1 text-start ${off ? "opacity-45" : ""}`}
              >
                <span
                  className={`block truncate text-sm ${off ? "line-through" : ""}`}
                >
                  {entry.title}
                </span>
                <span className="block truncate text-xs text-muted-soft">
                  {off ? "موقوفة — لن تُطبع" : entry.subtitle}
                </span>
              </button>
              <span className="mono shrink-0 text-[10px] text-muted-soft">
                {off ? "—" : String(printed).padStart(2, "0")}
              </span>
            </div>

            {selected && !entry.locked ? (
              <div className="flex flex-wrap gap-1 px-3 pb-2">
                {off ? (
                  <Action
                    label="استعادة"
                    disabled={busy}
                    onClick={() => onSetEnabled(entry.node.id, true)}
                  />
                ) : (
                  <>
                    <Action
                      label="تكرار"
                      disabled={busy}
                      onClick={() => onDuplicate(entry.node.id)}
                    />
                    <Action
                      label="تقديم"
                      disabled={busy || index === 0}
                      onClick={() => onMove(entry.node.id, -1)}
                    />
                    <Action
                      label="تأخير"
                      disabled={busy || index === entries.length - 1}
                      onClick={() => onMove(entry.node.id, 1)}
                    />
                    <Action
                      label="إيقاف"
                      tone="bad"
                      disabled={busy}
                      onClick={() => onSetEnabled(entry.node.id, false)}
                    />
                  </>
                )}
              </div>
            ) : null}
          </li>
        );
      })}
    </ol>
  );
}

function Action({
  label,
  onClick,
  disabled,
  tone,
}: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  tone?: "bad";
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={`border px-2 py-1 text-xs transition-colors disabled:opacity-40 ${
        tone === "bad"
          ? "border-line text-bad hover:border-bad"
          : "border-line text-muted hover:border-edge hover:text-ink"
      }`}
    >
      {label}
    </button>
  );
}
