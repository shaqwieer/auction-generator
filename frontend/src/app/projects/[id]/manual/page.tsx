"use client";

import { useParams, useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { AppShell, RequireAuth } from "@/components/shell";
import { Banner, Mono, Panel, PanelHeader, Spinner } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import type { AssetOut, ProjectOut, TemplateDetail } from "@/types/api";

const MAX_ITEMS = 40;

interface Item {
  values: Record<string, string>;
}

export default function ManualEntryPage() {
  return (
    <RequireAuth>
      <ManualEntry />
    </RequireAuth>
  );
}

function ManualEntry() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();

  const [project, setProject] = useState<ProjectOut | null>(null);
  const [template, setTemplate] = useState<TemplateDetail | null>(null);
  const [assets, setAssets] = useState<AssetOut[]>([]);
  const [statics, setStatics] = useState<Record<string, string>>({});
  const [items, setItems] = useState<Item[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void (async () => {
      try {
        const loaded = await api.project(id);
        setProject(loaded);
        const [detail, records, library] = await Promise.all([
          api.template(loaded.template_id),
          api.records(id),
          api.assets().catch(() => []),
        ]);
        setTemplate(detail);
        setAssets(library);
        setStatics(
          Object.fromEntries(
            Object.entries(loaded.static_values).map(([key, value]) => [
              key,
              String(value ?? ""),
            ]),
          ),
        );
        setItems(
          records.length > 0
            ? records.map((record) => ({
                values: Object.fromEntries(
                  Object.entries(record.values)
                    .filter(([key]) => key !== "__raw__")
                    .map(([key, value]) => [key, String(value ?? "")]),
                ),
              }))
            : [{ values: {} }],
        );
      } catch {
        setError("تعذّر تحميل المشروع.");
      }
    })();
  }, [id]);

  /** Per-record fields, de-duplicated: a lot key appears on both of its pages. */
  const recordFields = useMemo(() => {
    if (!template) return [];
    const seen = new Set<string>();
    return template.fields.filter((field) => {
      if (field.type === "table") return false;
      if (!template.record_keys.includes(field.key)) return false;
      if (seen.has(field.key)) return false;
      seen.add(field.key);
      return true;
    });
  }, [template]);

  const staticFields = useMemo(() => {
    if (!template) return [];
    const seen = new Set<string>();
    return template.fields.filter((field) => {
      if (field.type === "table") return false;
      if (!template.static_keys.includes(field.key)) return false;
      if (seen.has(field.key)) return false;
      seen.add(field.key);
      return true;
    });
  }, [template]);

  function update(index: number, key: string, value: string) {
    setItems((current) =>
      current.map((item, position) =>
        position === index
          ? { values: { ...item.values, [key]: value } }
          : item,
      ),
    );
  }

  function move(index: number, delta: number) {
    setItems((current) => {
      const next = [...current];
      const target = index + delta;
      if (target < 0 || target >= next.length) return current;
      const moved = next[index];
      const other = next[target];
      if (!moved || !other) return current;
      next[index] = other;
      next[target] = moved;
      return next;
    });
  }

  async function save(then: "stay" | "review") {
    setBusy(true);
    setError(null);
    try {
      await api.updateProject(id, { static_values: statics });
      await api.saveRecords(
        id,
        items.filter((item) => Object.values(item.values).some(Boolean)),
      );
      if (then === "review") router.push(`/projects/${id}/review`);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "تعذّر الحفظ.");
    } finally {
      setBusy(false);
    }
  }

  const pages = template
    ? template.sections.reduce((total, section) => {
        const span = section.last_page - section.first_page + 1;
        if (section.kind === "per_record") return total + span * items.length;
        if (section.kind === "table")
          return total + Math.max(1, Math.ceil(items.length / section.rows_per_page));
        return total + span;
      }, 0)
    : 0;

  return (
    <AppShell
      breadcrumb={`إدخال يدوي · ${project?.name ?? ""}`}
      action={
        <div className="flex gap-2">
          <button
            type="button"
            className="btn-secondary"
            disabled={busy}
            onClick={() => void save("stay")}
          >
            حفظ كمسودة
          </button>
          <button
            type="button"
            className="btn-primary"
            disabled={busy}
            onClick={() => void save("review")}
          >
            المراجعة والتوليد <span aria-hidden>←</span>
          </button>
        </div>
      }
    >
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h1 className="text-2xl font-semibold">أدخِل عناصر الكتيّب</h1>
        <span className="mono text-sm text-muted-soft">
          {items.length} ITEMS → {pages} PAGES
        </span>
      </div>

      {error ? (
        <div className="mt-5">
          <Banner tone="error" title={error} />
        </div>
      ) : null}

      {template === null ? (
        <Panel className="mt-6">
          <Spinner />
        </Panel>
      ) : (
        <>
          <Panel className="mt-6">
            <PanelHeader title="بيانات ثابتة تظهر على كل صفحة" />
            <div className="grid gap-4 p-5 sm:grid-cols-2 lg:grid-cols-3">
              {staticFields.map((field) => (
                <div key={field.key}>
                  <label className="field-label" htmlFor={`s-${field.key}`}>
                    {field.label || field.key}
                    {field.is_required ? " *" : ""}
                  </label>
                  {field.type === "image" ? (
                    <select
                      id={`s-${field.key}`}
                      value={statics[field.key] ?? ""}
                      onChange={(event) =>
                        setStatics({ ...statics, [field.key]: event.target.value })
                      }
                    >
                      <option value="">— بلا صورة —</option>
                      {assets.map((asset) => (
                        <option key={asset.id} value={asset.filename}>
                          {asset.filename}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <textarea
                      id={`s-${field.key}`}
                      rows={field.h > 0.05 ? 3 : 1}
                      value={statics[field.key] ?? ""}
                      onChange={(event) =>
                        setStatics({ ...statics, [field.key]: event.target.value })
                      }
                    />
                  )}
                </div>
              ))}
            </div>
          </Panel>

          <Panel className="mt-6">
            <PanelHeader
              title="العناصر"
              meta={`${items.length} / ${MAX_ITEMS}`}
              action={
                <span className="text-sm text-muted-soft">
                  كل عنصر = صفحات في الملف النهائي
                </span>
              }
            />
            {items.map((item, index) => (
              <div key={index} className="border-b border-line last:border-b-0">
                <div className="flex items-center justify-between gap-3 bg-paper px-5 py-2.5">
                  <div className="flex items-baseline gap-3">
                    <Mono>
                      <span className="text-sm text-muted-soft">
                        {String(index + 1).padStart(2, "0")}
                      </span>
                    </Mono>
                    <span className="text-sm font-medium">
                      {item.values.deed_number || `عنصر ${index + 1}`}
                    </span>
                  </div>
                  <div className="flex items-center gap-2 text-sm">
                    <button
                      type="button"
                      className="text-muted-soft hover:text-ink"
                      onClick={() => move(index, -1)}
                      aria-label="تحريك لأعلى"
                    >
                      ↑
                    </button>
                    <button
                      type="button"
                      className="text-muted-soft hover:text-ink"
                      onClick={() => move(index, 1)}
                      aria-label="تحريك لأسفل"
                    >
                      ↓
                    </button>
                    <button
                      type="button"
                      className="text-muted-soft hover:text-bad"
                      onClick={() =>
                        setItems((current) =>
                          current.filter((_, position) => position !== index),
                        )
                      }
                    >
                      حذف
                    </button>
                  </div>
                </div>
                <div className="grid gap-4 p-5 sm:grid-cols-2 lg:grid-cols-3">
                  {recordFields.map((field) => (
                    <div key={field.key}>
                      <label
                        className="field-label"
                        htmlFor={`i-${index}-${field.key}`}
                      >
                        {field.label || field.key}
                        {field.is_required ? " *" : ""}
                      </label>
                      {field.type === "image" ? (
                        <select
                          id={`i-${index}-${field.key}`}
                          value={item.values[field.key] ?? ""}
                          onChange={(event) =>
                            update(index, field.key, event.target.value)
                          }
                        >
                          <option value="">— بلا صورة —</option>
                          {assets.map((asset) => (
                            <option key={asset.id} value={asset.filename}>
                              {asset.filename}
                            </option>
                          ))}
                        </select>
                      ) : (
                        <textarea
                          id={`i-${index}-${field.key}`}
                          rows={field.h > 0.05 ? 3 : 1}
                          value={item.values[field.key] ?? ""}
                          onChange={(event) =>
                            update(index, field.key, event.target.value)
                          }
                        />
                      )}
                    </div>
                  ))}
                </div>
              </div>
            ))}

            <div className="p-5">
              <button
                type="button"
                className="btn-secondary"
                disabled={items.length >= MAX_ITEMS}
                onClick={() => setItems((current) => [...current, { values: {} }])}
              >
                + أضف عنصرًا — سيضيف صفحات جديدة
              </button>
            </div>
          </Panel>
        </>
      )}
    </AppShell>
  );
}
