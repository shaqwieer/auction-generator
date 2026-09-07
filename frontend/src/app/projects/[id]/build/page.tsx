"use client";

/**
 * The builder: the booklet assembled page by page.
 *
 * Three columns, reading right to left. The page list is the booklet in order,
 * with what can be done to each page. The middle is the page itself — a server
 * raster of the real artwork with its fields typed into on top. The left panel
 * is whatever the selected page needs: a cover choice, a layout choice, the
 * optional pages, photographs, and the same fields as a plain form.
 *
 * There is no client-side model of the booklet. Every mutation returns the whole
 * plan and that is what gets rendered, so the screen can never drift from what
 * the server would generate.
 */

import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { CoverChooser } from "@/components/builder/CoverChooser";
import { LeaseRows } from "@/components/builder/LeaseRows";
import { Sections } from "@/components/builder/Sections";
import {
  FieldList,
  PageEditor,
  PhotoSlot,
  askable,
  photoFields,
  sectioned,
} from "@/components/builder/PageEditor";
import { PageStrip, describe } from "@/components/builder/PageStrip";
import { AppShell, RequireAuth } from "@/components/shell";
import {
  Banner,
  Empty,
  Labelled,
  Mono,
  Panel,
  PanelHeader,
  Spinner,
  Steps,
  Tabbed,
} from "@/components/ui";
import type { TabSpec } from "@/components/ui";
import { ApiError, api, nodePreviewUrl } from "@/lib/api";
import { WIZARD_STEPS } from "@/lib/wizard";
import type {
  PagePlanOut,
  ProjectOut,
  RecordOut,
  TemplateDetail,
  TemplatePageOut,
} from "@/types/api";

/** The two identity colours a table page is printed in. */
const COLOUR_NAMES: Record<string, string> = { green: "أخضر", blue: "أزرق" };

export default function BuildPage() {
  return (
    <RequireAuth>
      <Build />
    </RequireAuth>
  );
}

function Build() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();

  const [project, setProject] = useState<ProjectOut | null>(null);
  const [template, setTemplate] = useState<TemplateDetail | null>(null);
  const [plan, setPlanState] = useState<PagePlanOut | null>(null);
  const [records, setRecords] = useState<RecordOut[]>([]);
  const [active, setActive] = useState<string | null>(null);
  const [focused, setFocused] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [importing, setImporting] = useState(false);
  const excel = useRef<HTMLInputElement>(null);
  /**
   * What the client has typed and the server has not yet acknowledged, by key.
   *
   * A single "dirty" flag cannot express this. It has to be cleared when a save
   * is sent, and a save is sent while typing carries on — so between the send
   * and the answer the page believed it held nothing unsaved, and the answer,
   * built from the values the *send* carried, was adopted over the letters
   * typed since. That is «اكتب كلمة تختفي»: the word goes, then comes back when
   * the next save lands. Held per key and cleared only on acknowledgement, a
   * letter cannot be lost — whatever the server says, what is still unsent is
   * laid back over the top of it.
   */
  const pending = useRef(new Map<string, string>());
  /**
   * The revision the server last handed back.
   *
   * Kept beside the state because the debounced save reads it from inside a
   * timer. A timer closes over the render that scheduled it, so a save landing
   * while somebody keeps typing would send the revision from before that save —
   * the server refuses it, correctly, and the screen reloads mid-sentence. The
   * ref is current whenever the timer wakes up.
   */
  const revision = useRef(0);
  /**
   * The tail of the save chain. Every change that bumps the revision joins it.
   *
   * The server refuses a change built on a revision it has already replaced,
   * and it is right to: that guard is what stops a debounced value save from
   * silently undoing a reorder. But two of *our own* saves in flight at once
   * trip it against ourselves — the second was built while the first was still
   * flying, so it carries the revision the first has just superseded. The
   * refusal reloads the builder, and the sentence being typed goes with it.
   *
   * Chaining means a save is built only once the one before it has landed, so
   * it reads the revision that one left behind and the guard never fires on us.
   * Every caller goes through here — values, lease rows, layout, photographs —
   * because it is the *mixture* that raced, not any one of them alone.
   */
  const queue = useRef<Promise<unknown>>(Promise.resolve());

  const enqueue = useCallback(<T,>(action: () => Promise<T>): Promise<T> => {
    // `then(action, action)` rather than `finally`: one save failing must not
    // strand every save behind it.
    const next = queue.current.then(action, action);
    queue.current = next.then(
      () => undefined,
      () => undefined,
    );
    return next;
  }, []);

  const setPlan = useCallback((next: PagePlanOut) => {
    revision.current = next.revision;
    setPlanState(next);
  }, []);
  /**
   * Which section of the side panel is open.
   *
   * Held by name rather than by index: the tabs a page offers depend on what it
   * is, and an index would land on whatever happened to be in that position on
   * the next page. A name that the new page does not offer falls back to its
   * first tab, and one it does offer is kept — so moving between properties
   * stays on الحقول, and does not throw the client back a tab each time.
   */
  const [tab, setTab] = useState("fields");

  const load = useCallback(async () => {
    const loaded = await api.project(id);
    setProject(loaded);
    if (!loaded.has_plan) {
      // Created before the builder, or from a template that has no page roles.
      router.replace(`/projects/${id}/data`);
      return;
    }
    const [full, current, rows] = await Promise.all([
      api.template(loaded.template_id),
      api.plan(id),
      api.records(id),
    ]);
    setTemplate(full);
    setPlan(current);
    setRecords(rows);
    setActive((was) =>
      was && current.nodes.some((n) => n.id === was)
        ? was
        : (current.nodes[0]?.id ?? null),
    );
  }, [id, router, setPlan]);

  useEffect(() => {
    void load().catch((caught) =>
      setError(
        caught instanceof ApiError ? caught.message : "تعذّر فتح الكتيّب.",
      ),
    );
  }, [load]);

  const pagesByIndex = useMemo(() => {
    const map = new Map<number, TemplatePageOut>();
    for (const page of plan?.pages ?? []) map.set(page.page_index, page);
    return map;
  }, [plan]);

  const entries = useMemo(() => {
    // Switched-off properties are not numbered: العقار 02 has to be the second
    // property in the booklet, not the second one ever created.
    let lot = 0;
    return (plan?.nodes ?? []).map((node) => {
      if (node.kind === "lot" && !node.off) lot += 1;
      return describe(node, pagesByIndex, node.kind === "lot" ? lot : null);
    });
  }, [plan, pagesByIndex]);

  const node = plan?.nodes.find((n) => n.id === active) ?? null;
  const recordByRow = useMemo(() => {
    const map = new Map<number, RecordOut>();
    for (const row of records) map.set(row.row_index, row);
    return map;
  }, [records]);

  // Which template page the selected node is showing, and the fields on it.
  const [shownPage, setShownPage] = useState<number | null>(null);
  // Keyed on the pages the node draws, not on the node: swapping the cover now
  // keeps the node and changes its page, and a `shownPage` left on the old one
  // put the previous cover's field boxes over the new cover's artwork.
  const showing = node ? (node.pages.join(",") || String(node.page ?? "")) : "";
  // Held by *position* in the node, not by page index. Recolouring the lease
  // table swaps page 11 for page 21 underneath the same node, and resetting to
  // the first page threw the designer back to the property's opening page
  // every time they tried a colour.
  const slot = useRef(0);
  useEffect(() => {
    slot.current = 0;
  }, [node?.id]);
  useEffect(() => {
    const pages = node?.pages ?? [];
    setShownPage(pages[slot.current] ?? pages[0] ?? node?.page ?? null);
    setFocused(null);
  }, [node?.id, showing]); // eslint-disable-line react-hooks/exhaustive-deps

  /**
   * Send what is unsent for one node, now.
   *
   * The keys are cleared only when the server has answered *and* nothing has
   * been typed over them since — the value that was sent is compared against
   * the value still held, so a letter typed while the save was flying keeps its
   * key pending and goes with the next one.
   */
  const send = useCallback(
    (nodeId: string) => {
      const sending = new Map(pending.current);
      if (!sending.size) return;
      void enqueue(async () => {
        try {
          setPlan(
            await api.patchNodeValues(
              id,
              nodeId,
              Object.fromEntries(sending),
              revision.current,
            ),
          );
          setRecords(await api.records(id));
          setError(null);
          for (const [key, value] of sending) {
            if (pending.current.get(key) === value) pending.current.delete(key);
          }
        } catch (caught) {
          // Say so, but change nothing on screen. The values stay pending, so
          // they stay visible and go again with the next keystroke — reloading
          // here is what used to throw away the paragraph being written.
          setError(
            caught instanceof ApiError
              ? caught.message
              : "تعذّر حفظ ما كُتب — سيُعاد الحفظ تلقائيًا.",
          );
        }
      });
    },
    [enqueue, id, setPlan],
  );

  /**
   * Leaving a page sends what it still holds, rather than dropping it.
   *
   * Values are keyed to the node they were typed on, so they cannot be carried
   * across — but there is a 450ms window in which somebody can type a word and
   * click the next page, and the word belongs to the page they left. Clearing
   * the pending map without sending it is how that word used to be lost.
   */
  const leaving = useRef<string | null>(null);
  useEffect(() => {
    const was = leaving.current;
    if (was && was !== node?.id) {
      send(was);
      pending.current.clear();
    }
    leaving.current = node?.id ?? null;
  }, [node?.id, send]);

  const fields = shownPage === null ? [] : (plan?.fields_by_page[String(shownPage)] ?? []);

  // Values for the selected page: a property's live on its record, everything
  // else on the node it was typed onto.
  const stored = useMemo<Record<string, string>>(() => {
    if (!node) return {};
    const source =
      node.kind === "lot"
        ? (recordByRow.get(node.row ?? -1)?.values ?? {})
        : node.values;
    const out: Record<string, string> = {};
    for (const [key, value] of Object.entries(source)) {
      out[key] = value === null || value === undefined ? "" : String(value);
    }
    return out;
  }, [node, recordByRow]);

  // Adopt what the server has, and lay anything still unsent back over it.
  //
  // A save returns a plan built from the values that save carried, and typing
  // carries on while it is in flight — so the answer is always a little behind
  // the box it is being written into. Taking it whole put the caret back a word
  // or two; taking it whole at the wrong moment took the word away entirely.
  // The unsent keystrokes go back on top, so the answer can be as stale as the
  // network makes it without ever being visible.
  useEffect(() => {
    setDraft(
      pending.current.size
        ? { ...stored, ...Object.fromEntries(pending.current) }
        : stored,
    );
  }, [stored]);

  // Send once typing stops: every save returns a new plan and a new preview
  // URL, so sending per keystroke would redraw the page mid-word.
  useEffect(() => {
    if (!pending.current.size || !node) return;
    const nodeId = node.id;
    const timer = setTimeout(() => send(nodeId), 450);
    return () => clearTimeout(timer);
  }, [draft, node?.id, send]); // eslint-disable-line react-hooks/exhaustive-deps

  /** Record a keystroke: on screen at once, on its way 450ms after the last. */
  const edit = useCallback((key: string, value: string) => {
    pending.current.set(key, value);
    setDraft((was) => ({ ...was, [key]: value }));
  }, []);

  /**
   * A change the client asked for and is waiting on: spinner, and a reload if
   * it is refused, because a refusal means the screen is behind.
   *
   * Queued with the value saves rather than beside them — a layout swap landing
   * between a save and its answer is exactly the collision the revision guard
   * exists to catch, and catching our own traffic with it helped nobody.
   */
  const run = useCallback(
    (action: () => Promise<void>) =>
      enqueue(async () => {
        setBusy(true);
        setError(null);
        try {
          await action();
        } catch (caught) {
          setError(
            caught instanceof ApiError ? caught.message : "تعذّر تنفيذ العملية.",
          );
          // A refused change means the screen is behind; reload rather than
          // guess. Unsent keystrokes survive it — they are laid back on top.
          await load().catch(() => undefined);
        } finally {
          setBusy(false);
        }
      }),
    [enqueue, load],
  );

  if (error && !plan) {
    return (
      <AppShell breadcrumb="بناء الكتيّب">
        <Banner tone="error" title="تعذّر فتح الكتيّب">
          {error}
        </Banner>
      </AppShell>
    );
  }
  if (!project || !template || !plan) {
    return (
      <AppShell breadcrumb="بناء الكتيّب">
        <Panel>
          <Spinner />
        </Panel>
      </AppShell>
    );
  }

  // The six the brand guide draws. The export's own cover page holds the slot
  // so the cover lands where the designer put it, but it is غلاف 1 again and is
  // not offered as a seventh choice.
  const covers = plan.pages.filter(
    (page) =>
      page.slot === "cover" &&
      !page.options?.source_cover &&
      !page.options?.own_artwork,
  );
  const layouts = plan.pages.filter((page) => page.role === "lot");
  // The summary page as the designer drew it, in each of its two colours.
  const colourways = plan.pages.filter((page) => page.slot === "lot_table");
  // Which page is on screen, and — if it is a lease page — the table it draws.
  const leaseColours = plan.pages.filter((page) => page.role === "rent_table");
  const onLeasePage =
    shownPage !== null &&
    leaseColours.some((page) => page.page_index === shownPage);
  const leaseTable = onLeasePage
    ? fields.find((field) => field.type === "table" && field.table_spec)
    : undefined;
  const leaseRows =
    (node?.values?.__lease__ as Record<string, string>[] | undefined) ?? [];
  // The boxes written as titles with points under them. Each gets an editor of
  // its own rather than a bare textarea.
  const sectionBoxes = sectioned(fields);
  // One entry per role. بيان عقود الإيجار is drawn in two colours and the
  // booklet picks one on its own panel, so listing both here offered a choice
  // that was really a colour as though it were two different pages.
  const optional = plan.pages.filter(
    (page, index, all) =>
      page.is_optional &&
      !page.options?.needs_artwork &&
      all.findIndex((other) => other.role === page.role) === index,
  );
  const lotCount = plan.nodes.filter((n) => n.kind === "lot" && !n.off).length;

  /*
    The sections this page offers. Which ones exist depends on what the node is
    — a property has a layout and optional pages, a cover has six designs, the
    lease page has its rows — so the bar is rebuilt per node and `Tabbed` falls
    back to the first when the one that was open is not on the new page.

    الحقول leads, and is the default: the builder's own promise is that a page
    is filled in from the list beside it, and arriving on a tab that is not that
    list would break the pairing with the boxes on the page.
  */
  const panels: TabSpec[] = [];

  if (node && node.kind !== "table") {
    panels.push({
      id: "fields",
      label: "الحقول",
      meta: askable(fields).length || undefined,
      body: (
        <FieldList
          fields={fields}
          values={draft}
          focused={focused}
          onFocusField={setFocused}
          onChange={edit}
          booklet={plan.booklet}
        />
      ),
    });
  }

  if (node && photoFields(fields).length) {
    panels.push({
      id: "photos",
      label: "الصور",
      meta: photoFields(fields).length,
      body: (
        <div className="grid gap-2 p-4">
          {photoFields(fields).map((field) => (
            <PhotoSlot
              key={field.id}
              field={field}
              current={stored[field.key] ?? ""}
              disabled={busy}
              onUpload={async (fieldKey, file) => {
                await run(async () => {
                  await api.uploadNodePhoto(id, node.id, fieldKey, file);
                  await load();
                });
              }}
              onClear={async (fieldKey) => {
                // The picture comes off the page; the file stays in the
                // library, so putting it back is a re-pick, not a re-upload.
                await run(async () => {
                  setPlan(
                    await api.patchNodeValues(
                      id,
                      node.id,
                      { [fieldKey]: "" },
                      revision.current,
                    ),
                  );
                  setRecords(await api.records(id));
                });
              }}
            />
          ))}
        </div>
      ),
    });
  }

  for (const box of sectionBoxes) {
    panels.push({
      id: `section:${box.key}`,
      label: box.label || "معلومات إضافية",
      body: (
        <>
          <Sections
            value={draft[box.key] ?? ""}
            disabled={busy}
            onChange={(value) => edit(box.key, value)}
          />
          <p className="border-t border-line px-4 py-3 text-xs text-muted-soft">
            العنوان يُطبع عريضًا فوق نقاطه، كما في الدليل.
          </p>
        </>
      ),
    });
  }

  if (onLeasePage && leaseTable?.table_spec) {
    const spec = leaseTable.table_spec;
    panels.push({
      id: "lease",
      label: "عقود الإيجار",
      meta: `${leaseRows.length}/${spec.rows}`,
      body: (
        <>
          <LeaseRows
            columns={spec.columns}
            rows={leaseRows}
            disabled={busy}
            onChange={async (rows) => {
              // Still not `run`: a failure there reloads the whole booklet, and
              // reloading is precisely what must not happen to a row somebody
              // is halfway through typing. But it does go through the queue — a
              // lease save and a value save in flight together were two changes
              // built on one revision, and the second was refused.
              const nodeId = node!.id;
              setError(null);
              await enqueue(async () => {
                try {
                  setPlan(
                    await api.setLeaseRows(id, nodeId, rows, revision.current),
                  );
                } catch (caught) {
                  setError(
                    caught instanceof ApiError
                      ? caught.message
                      : "تعذّر حفظ عقود الإيجار.",
                  );
                }
              });
            }}
          />
          <p className="border-t border-line px-4 py-3 text-xs text-muted-soft">
            تُطبع بالترتيب الظاهر هنا، وتُحذف الصفوف الإضافية غير المستخدمة.
          </p>
        </>
      ),
    });
  }

  if (node?.kind === "lot") {
    panels.push({
      id: "options",
      label: "خيارات الصفحة",
      body: (
        <div className="grid gap-4 p-4">
          <Labelled label="تخطيط الصفحة">
            <div className="grid gap-2">
              {layouts.map((layout) => (
                <button
                  key={layout.id}
                  type="button"
                  disabled={busy}
                  onClick={() =>
                    void run(async () => {
                      setPlan(
                        await api.setNodeLayout(id, node.id, {
                          layout: layout.layout,
                          revision: revision.current,
                        }),
                      );
                    })
                  }
                  className={`border p-3 text-start text-sm transition-colors ${
                    node.layout === layout.layout
                      ? "border-accent bg-[#FCE8F2]"
                      : "border-line hover:border-edge"
                  }`}
                >
                  {layout.name}
                </button>
              ))}
            </div>
          </Labelled>

          <Labelled label="صفحات إضافية لهذا العقار">
            <div className="grid gap-2">
              {optional.map((page) => {
                const on = node.options.includes(page.role);
                return (
                  <label
                    key={page.id}
                    className={`flex cursor-pointer items-center gap-3 border p-3 text-sm transition-colors ${
                      on ? "border-accent bg-[#FCE8F2]" : "border-line"
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={on}
                      disabled={busy}
                      className="h-4 w-4"
                      onChange={() =>
                        void run(async () => {
                          const options = on
                            ? node.options.filter((r) => r !== page.role)
                            : [...node.options, page.role];
                          setPlan(
                            await api.setNodeLayout(id, node.id, {
                              options,
                              revision: revision.current,
                            }),
                          );
                        })
                      }
                    />
                    <span>{page.name}</span>
                  </label>
                );
              })}
            </div>
          </Labelled>
        </div>
      ),
    });
  }

  if (node?.slot === "cover") {
    panels.push({
      id: "cover",
      label: "الغلاف",
      meta: covers.length,
      body: (
        <div className="p-4">
          <CoverChooser
            templateId={template.id}
            pageWidth={template.page_width}
            pageHeight={template.page_height}
            covers={covers}
            chosen={node.page ?? null}
            onChoose={(pageIndex) =>
              void run(async () => {
                setPlan(
                  await api.setNodeLayout(id, node.id, {
                    page: pageIndex,
                    revision: revision.current,
                  }),
                );
              })
            }
          />
        </div>
      ),
    });
  }

  // The identity colour, wherever a page is drawn in both. One control, whether
  // it is the summary table's own node or the lease page inside a property.
  const colourChoices = node?.kind === "table" ? colourways : leaseColours;
  if ((node?.kind === "table" || onLeasePage) && colourChoices.length > 1) {
    const isLease = node?.kind !== "table";
    panels.push({
      id: "colour",
      label: "لون الجدول",
      body: (
        <>
          <div className="grid gap-2 p-4">
            {colourChoices.map((page) => {
              const on = isLease
                ? project.lease_colourway === page.layout
                : node?.page === page.page_index;
              return (
                <button
                  key={page.id}
                  type="button"
                  disabled={busy}
                  onClick={() =>
                    void run(async () => {
                      if (isLease) {
                        await api.updateProject(id, {
                          lease_colourway: page.layout,
                        });
                        await load();
                      } else {
                        setPlan(
                          await api.setNodeLayout(id, node!.id, {
                            page: page.page_index,
                            revision: revision.current,
                          }),
                        );
                      }
                    })
                  }
                  className={`border p-3 text-start text-sm transition-colors ${
                    on
                      ? "border-accent bg-[#FCE8F2]"
                      : "border-line hover:border-edge"
                  }`}
                >
                  {COLOUR_NAMES[page.layout ?? ""] ?? page.name}
                </button>
              );
            })}
          </div>
          <p className="border-t border-line px-4 py-3 text-xs text-muted-soft">
            {isLease
              ? "اللون يسري على كل صفحات عقود الإيجار في هذا الكتيّب."
              : "نفس الجدول بلونَي الهوية. الصفحة تتكرّر إذا زادت العقارات عن سعتها."}
          </p>
        </>
      ),
    });
  }

  return (
    <AppShell
      breadcrumb={`${project.name} · الخطوة 2 من 3`}
      action={
        <div className="flex items-center gap-2">
          <button
            type="button"
            className="btn btn-secondary"
            disabled={busy}
            onClick={() => excel.current?.click()}
          >
            {importing ? "جارٍ الاستيراد…" : "استيراد من Excel"}
          </button>
          <input
            ref={excel}
            type="file"
            accept=".xlsx,.xlsm,.csv"
            className="hidden"
            onChange={(event) => {
              const file = event.target.files?.[0];
              event.target.value = "";
              if (!file) return;
              setImporting(true);
              void run(async () => {
                await api.uploadDataSource(id, file);
                await load();
              }).finally(() => setImporting(false));
            }}
          />
          <button
            type="button"
            className="btn-primary"
            onClick={() => router.push(`/projects/${id}/review`)}
          >
            التالي: المراجعة والتوليد
            <span aria-hidden>←</span>
          </button>
        </div>
      }
    >
      <Steps steps={WIZARD_STEPS} current={1} />

      {error ? (
        <div className="mt-4">
          <Banner tone="warn" title="لم تُحفَظ آخر عملية">
            {error}
          </Banner>
        </div>
      ) : null}

      <div className="mt-5 grid gap-5 xl:grid-cols-[260px_1fr_320px] [@media(min-width:1600px)]:grid-cols-[260px_1fr_440px]">
        {/* The booklet, in order. */}
        <section className="space-y-3">
          <PanelHeader
            title="صفحات الكتيّب"
            meta={`${plan.predicted_pages} صفحة`}
          />
          <PageStrip
            entries={entries}
            active={active}
            busy={busy}
            onSelect={setActive}
            onDuplicate={(nodeId) =>
              void run(async () => {
                setPlan(await api.duplicateNode(id, nodeId, plan.revision));
              })
            }
            onMove={(nodeId, delta) =>
              void run(async () => {
                setPlan(await api.moveNode(id, nodeId, delta, plan.revision));
              })
            }
            onSetEnabled={(nodeId, on) =>
              void run(async () => {
                setPlan(
                  await api.setNodeEnabled(id, nodeId, {
                    on,
                    revision: plan.revision,
                  }),
                );
              })
            }
          />
          <button
            type="button"
            // The first property is the whole job on an empty booklet, so it
            // gets the accent; after that it is one action among several.
            className={`w-full ${lotCount ? "btn btn-secondary" : "btn-primary"}`}
            disabled={busy || !layouts.length}
            onClick={() =>
              void run(async () => {
                const next = await api.addNode(id, {
                  kind: "lot",
                  // Only chain onto another property. From anywhere else the
                  // server puts it where properties go, not after the cover.
                  ...(node?.kind === "lot" ? { after: node.id } : {}),
                  revision: plan.revision,
                });
                setPlan(next);
                setRecords(await api.records(id));
                setActive(
                  next.nodes.find(
                    (candidate) =>
                      candidate.kind === "lot" &&
                      !plan.nodes.some((was) => was.id === candidate.id),
                  )?.id ?? active,
                );
              })
            }
          >
            + إضافة عقار
          </button>
        </section>

        {/* The page itself. */}
        <section>
          {node ? (
            <>
              {node.pages.length > 1 ? (
                <div className="mb-3 flex flex-wrap gap-2">
                  {node.pages.map((pageIndex, position) => (
                    <button
                      key={pageIndex}
                      type="button"
                      onClick={() => {
                        slot.current = position;
                        setShownPage(pageIndex);
                      }}
                      className={`border px-3 py-1 text-xs transition-colors ${
                        shownPage === pageIndex
                          ? "border-accent bg-[#FCE8F2]"
                          : "border-line hover:border-edge"
                      }`}
                    >
                      {pagesByIndex.get(pageIndex)?.name ?? `صفحة ${pageIndex + 1}`}
                    </button>
                  ))}
                </div>
              ) : null}

              {node.kind === "table" ? (
                <Panel className="p-0">
                  <TablePreview
                    projectId={id}
                    nodeId={node.id}
                    revision={plan.revision}
                    width={template.page_width}
                    height={template.page_height}
                    version={template.version}
                    lots={lotCount}
                  />
                </Panel>
              ) : (
                <PageEditor
                  src={nodePreviewUrl(id, node.id, {
                    dpi: 110,
                    page: shownPage ?? undefined,
                    stamp: plan.revision,
                    version: template.version,
                    // The field being typed into is left off the page, so the
                    // box on top is the only place its value appears.
                    omit: focused ?? undefined,
                  })}
                  alt={entries.find((e) => e.node.id === node.id)?.title ?? ""}
                  pageWidth={template.page_width}
                  pageHeight={template.page_height}
                  fields={fields}
                  values={draft}
                  focused={focused}
                  onFocusField={setFocused}
                  onChange={edit}
                />
              )}
              <p className="mt-3 text-center text-xs text-muted-soft">
                اكتب مباشرة على الصفحة — ما تراه هو ما سيُطبع.
              </p>
            </>
          ) : (
            <Panel>
              <Empty title="لا توجد صفحات" hint="أضف عقارًا للبدء." />
            </Panel>
          )}
        </section>

        {/*
          What this page needs — one section at a time.

          Stacked down the side, these ran to several screenfuls on a property
          page, and reaching الحقول meant scrolling past the layout, five
          optional pages, the photographs and the section boxes. They are never
          read together, so they are not shown together: the bar puts each one
          click away and the page stays in view while any of them is open.
        */}
        <aside className="xl:sticky xl:top-5 xl:self-start">
          <Tabbed tabs={panels} active={tab} onSelect={setTab} />
        </aside>
      </div>
    </AppShell>
  );
}

/**
 * The summary table draws itself from the properties, so there is nothing to
 * type here — only a note saying so, and the page as it will print.
 */
function TablePreview({
  projectId,
  nodeId,
  revision,
  width,
  height,
  version,
  lots,
}: {
  projectId: string;
  nodeId: string;
  revision: number;
  width: number;
  height: number;
  version: number;
  lots: number;
}) {
  return (
    <>
      <div className="border-b border-line p-4 text-sm text-muted">
        يُبنى هذا الجدول تلقائيًا من العقارات — {" "}
        <Mono>
          <span>{lots}</span>
        </Mono>{" "}
        حتى الآن. رتّب العقارات ليتغيّر ترتيبه.
      </div>
      <div className="p-4">
        <PageEditor
          src={nodePreviewUrl(projectId, nodeId, {
            dpi: 110,
            stamp: revision,
            version,
          })}
          alt="بيان العقارات"
          pageWidth={width}
          pageHeight={height}
          fields={[]}
          values={{}}
          focused={null}
          onFocusField={() => undefined}
          onChange={() => undefined}
        />
      </div>
    </>
  );
}
