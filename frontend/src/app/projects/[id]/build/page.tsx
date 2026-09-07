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
  photoFields,
  sectioned,
} from "@/components/builder/PageEditor";
import { PageStrip, describe } from "@/components/builder/PageStrip";
import { AppShell, RequireAuth } from "@/components/shell";
import {
  Banner,
  Empty,
  Foldable,
  Labelled,
  Mono,
  Panel,
  PanelHeader,
  Spinner,
  Steps,
} from "@/components/ui";
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
  /** Set while the page holds keystrokes the server has not been told about. */
  const dirty = useRef(false);
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

  const setPlan = useCallback((next: PagePlanOut) => {
    revision.current = next.revision;
    setPlanState(next);
  }, []);
  // Folded away by default. A cover is chosen once and then in the way.
  const [coversOpen, setCoversOpen] = useState(false);

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
    dirty.current = false;
  }, [node?.id, showing]); // eslint-disable-line react-hooks/exhaustive-deps

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

  // Adopt what the server has, but never over the top of unsent keystrokes:
  // a save returns a plan built from the values it was given, and typing
  // carries on while it is in flight. Taking that answer as the truth put the
  // caret back a word or two, which is what "I have to click again and keep
  // typing" was.
  useEffect(() => {
    if (dirty.current) return;
    setDraft(stored);
  }, [stored]);

  // Send once typing stops: every save returns a new plan and a new preview
  // URL, so sending per keystroke would redraw the page mid-word.
  useEffect(() => {
    if (!dirty.current || !node) return;
    const timer = setTimeout(() => {
      const changed: Record<string, string> = {};
      for (const [key, value] of Object.entries(draft)) {
        if ((stored[key] ?? "") !== value) changed[key] = value;
      }
      dirty.current = false;
      if (!Object.keys(changed).length) return;
      void run(async () => {
        setPlan(
          await api.patchNodeValues(id, node.id, changed, revision.current),
        );
        setRecords(await api.records(id));
      });
    }, 450);
    return () => clearTimeout(timer);
  }, [draft]); // eslint-disable-line react-hooks/exhaustive-deps

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (caught) {
      setError(
        caught instanceof ApiError ? caught.message : "تعذّر تنفيذ العملية.",
      );
      // A refused change means the screen is behind; reload rather than guess.
      await load().catch(() => undefined);
    } finally {
      setBusy(false);
    }
  }

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

      <div className="mt-5 grid gap-5 xl:grid-cols-[260px_1fr_320px]">
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
                  onChange={(key, value) => {
                    dirty.current = true;
                    setDraft((was) => ({ ...was, [key]: value }));
                  }}
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

        {/* What this page needs. */}
        <aside className="space-y-4">
          {node?.slot === "cover" ? (
            <Foldable
              title="الغلاف"
              meta={`${covers.length} أغلفة`}
              open={coversOpen}
              onToggle={setCoversOpen}
            >
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
                          revision: plan.revision,
                        }),
                      );
                    })
                  }
                />
              </div>
            </Foldable>
          ) : null}

          {onLeasePage && leaseTable?.table_spec ? (
            <>
              {leaseColours.length > 1 ? (
                <Panel>
                  <PanelHeader title="لون الجدول" />
                  <div className="grid gap-2 p-4">
                    {leaseColours.map((page) => (
                      <button
                        key={page.id}
                        type="button"
                        disabled={busy}
                        onClick={() =>
                          void run(async () => {
                            await api.updateProject(id, {
                              lease_colourway: page.layout,
                            });
                            await load();
                          })
                        }
                        className={`border p-3 text-start text-sm transition-colors ${
                          project.lease_colourway === page.layout
                            ? "border-accent bg-[#FCE8F2]"
                            : "border-line hover:border-edge"
                        }`}
                      >
                        {COLOUR_NAMES[page.layout ?? ""] ?? page.name}
                      </button>
                    ))}
                  </div>
                  <p className="border-t border-line px-4 py-3 text-xs text-muted-soft">
                    اللون يسري على كل صفحات عقود الإيجار في هذا الكتيّب.
                  </p>
                </Panel>
              ) : null}

              <Panel>
                <PanelHeader
                  title="عقود الإيجار"
                  meta={`${leaseRows.length} من ${leaseTable.table_spec.rows}`}
                />
                <LeaseRows
                  columns={leaseTable.table_spec.columns}
                  rows={leaseRows}
                  disabled={busy}
                  onChange={async (rows) => {
                    // Saved without `run`: a failure there reloads the whole
                    // booklet, and reloading is precisely what must not happen
                    // to a row somebody is halfway through typing.
                    setError(null);
                    try {
                      setPlan(
                        await api.setLeaseRows(
                          id,
                          node!.id,
                          rows,
                          revision.current,
                        ),
                      );
                    } catch (caught) {
                      setError(
                        caught instanceof ApiError
                          ? caught.message
                          : "تعذّر حفظ عقود الإيجار.",
                      );
                    }
                  }}
                />
                <p className="border-t border-line px-4 py-3 text-xs text-muted-soft">
                  تُطبع بالترتيب الظاهر هنا، وتُحذف الصفوف الإضافية غير
                  المستخدمة.
                </p>
              </Panel>
            </>
          ) : null}

          {node?.kind === "table" && colourways.length > 1 ? (
            <Panel>
              <PanelHeader title="لون الجدول" />
              <div className="grid gap-2 p-4">
                {colourways.map((page) => (
                  <button
                    key={page.id}
                    type="button"
                    disabled={busy}
                    onClick={() =>
                      void run(async () => {
                        setPlan(
                          await api.setNodeLayout(id, node.id, {
                            page: page.page_index,
                            revision: plan.revision,
                          }),
                        );
                      })
                    }
                    className={`border p-3 text-start text-sm transition-colors ${
                      node.page === page.page_index
                        ? "border-accent bg-[#FCE8F2]"
                        : "border-line hover:border-edge"
                    }`}
                  >
                    {COLOUR_NAMES[page.layout ?? ""] ?? page.name}
                  </button>
                ))}
              </div>
              <p className="border-t border-line px-4 py-3 text-xs text-muted-soft">
                نفس الجدول بلونَي الهوية. الصفحة تتكرّر إذا زادت العقارات عن
                سعتها.
              </p>
            </Panel>
          ) : null}

          {node?.kind === "lot" ? (
            <Panel>
              <PanelHeader title="خيارات الصفحة" />
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
                                revision: plan.revision,
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
                                    revision: plan.revision,
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
            </Panel>
          ) : null}

          {node && photoFields(fields).length ? (
            <Panel>
              <PanelHeader title="الصور" />
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
            </Panel>
          ) : null}

          {sectionBoxes.map((box) => (
            <Panel key={box.key}>
              <PanelHeader title={box.label || "معلومات إضافية"} />
              <Sections
                value={draft[box.key] ?? ""}
                disabled={busy}
                onChange={(value) => {
                  dirty.current = true;
                  setDraft((was) => ({ ...was, [box.key]: value }));
                }}
              />
              <p className="border-t border-line px-4 py-3 text-xs text-muted-soft">
                العنوان يُطبع عريضًا فوق نقاطه، كما في الدليل.
              </p>
            </Panel>
          ))}

          {node && node.kind !== "table" ? (
            <Panel>
              <PanelHeader title="الحقول" />
              <FieldList
                fields={fields}
                values={draft}
                focused={focused}
                onFocusField={setFocused}
                onChange={(key, value) => {
                  dirty.current = true;
                  setDraft((was) => ({ ...was, [key]: value }));
                }}
              />
            </Panel>
          ) : null}
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
