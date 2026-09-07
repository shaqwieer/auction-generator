"use client";

import { useParams, useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { AppShell, RequireAuth } from "@/components/shell";
import {
  Banner,
  Empty,
  Mono,
  Panel,
  PanelHeader,
  Spinner,
  Steps,
} from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { LEGACY_WIZARD_STEPS } from "@/lib/wizard";
import type {
  ColumnOut,
  DataSourceOut,
  MappingEntry,
  MappingOut,
  ProjectOut,
  RecordOut,
  TemplateDetail,
} from "@/types/api";

export default function MappingPage() {
  return (
    <RequireAuth>
      <Mapping />
    </RequireAuth>
  );
}

function Mapping() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();

  const [project, setProject] = useState<ProjectOut | null>(null);
  const [template, setTemplate] = useState<TemplateDetail | null>(null);
  const [mapping, setMapping] = useState<MappingOut | null>(null);
  const [columns, setColumns] = useState<ColumnOut[]>([]);
  const [dataSource, setDataSource] = useState<DataSourceOut | null>(null);
  const [preview, setPreview] = useState<RecordOut[]>([]);
  const [entries, setEntries] = useState<MappingEntry[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void (async () => {
      try {
        const loaded = await api.project(id);
        setProject(loaded);
        const [detail, current, records, source] = await Promise.all([
          api.template(loaded.template_id),
          api.mapping(id),
          api.records(id),
          api.datasource(id),
        ]);
        setTemplate(detail);
        setMapping(current);
        setEntries(current.entries);
        setPreview(records.slice(0, 5));
        // Columns come from the stored data source so their letters and order
        // are the spreadsheet's, not whatever order the record keys iterate in.
        setDataSource(source);
        setColumns(source?.columns ?? []);
      } catch {
        setError("تعذّر تحميل بيانات الربط.");
      }
    })();
  }, [id]);

  const labels = useMemo(() => {
    const out = new Map<string, string>();
    for (const field of template?.fields ?? []) {
      if (field.label) out.set(field.key, field.label);
      for (const column of field.table_spec?.columns ?? []) {
        if (column.label && column.key !== "__index__") {
          out.set(column.key, column.label);
        }
      }
    }
    return out;
  }, [template]);

  const mappedCount = entries.filter((entry) => entry.column || entry.static_value).length;
  const errors = (mapping?.problems ?? []).filter((p) => p.severity === "error");

  function setColumn(fieldKey: string, column: string | null) {
    setEntries((current) =>
      current.map((entry) =>
        entry.field_key === fieldKey
          ? { ...entry, column, static_value: null }
          : entry,
      ),
    );
  }

  async function save(then: "stay" | "next") {
    setBusy(true);
    setError(null);
    try {
      const saved = await api.saveMapping(id, { entries });
      setMapping(saved);
      setEntries(saved.entries);
      setPreview((await api.records(id)).slice(0, 5));
      if (then === "next" && !saved.problems.some((p) => p.severity === "error")) {
        router.push(`/projects/${id}/review`);
      }
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "تعذّر حفظ الربط.");
    } finally {
      setBusy(false);
    }
  }

  const required = new Set(mapping?.required_keys ?? []);

  return (
    <AppShell
      breadcrumb={`مشروع جديد · الخطوة 3 من 4 · ${project?.name ?? ""}`}
      action={
        <div className="flex gap-2">
          <button
            type="button"
            className="btn-secondary"
            onClick={() => router.push(`/projects/${id}/data`)}
          >
            <span aria-hidden>→</span> رجوع
          </button>
          <button
            type="button"
            className="btn-primary"
            disabled={busy}
            onClick={() => void save("next")}
          >
            {busy ? "جارٍ الحفظ…" : "المراجعة والتوليد"} <span aria-hidden>←</span>
          </button>
        </div>
      }
    >
      <Steps steps={LEGACY_WIZARD_STEPS} current={2} />

      {errors.length > 0 ? (
        <div className="mt-5">
          <Banner
            tone="warn"
            title={`${errors.length} حقل إلزامي بلا عمود — لن يبدأ التوليد قبل ربطه.`}
          >
            {errors.map((problem) => problem.message).join(" · ")}
          </Banner>
        </div>
      ) : null}
      {error ? (
        <div className="mt-5">
          <Banner tone="error" title={error} />
        </div>
      ) : null}

      {/* Two facing columns: the file on one side, the template on the other. */}
      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <Panel>
          <PanelHeader
            title="أعمدة ملف Excel"
            meta={
              dataSource
                ? `${columns.length} COLS · ${dataSource.row_count} ROWS · ${dataSource.filename}`
                : undefined
            }
          />
          {columns.length === 0 ? (
            dataSource === null ? (
              <Empty
                title="لا يوجد ملف مرفوع"
                hint="هذا المشروع يستخدم الإدخال اليدوي — لا حاجة لربط الأعمدة."
              />
            ) : (
              <Spinner />
            )
          ) : (
            columns.map((column) => (
              <div
                key={column.name}
                className="flex items-center justify-between gap-3 border-b border-line px-5 py-3 text-sm last:border-b-0"
              >
                <div className="flex min-w-0 items-baseline gap-3">
                  <Mono>
                    <span className="text-xs text-muted-soft">{column.letter}</span>
                  </Mono>
                  <span className="truncate font-medium">{column.name}</span>
                </div>
                <span className="mono truncate text-xs text-muted-soft">
                  {column.sample}
                </span>
              </div>
            ))
          )}
        </Panel>

        <Panel>
          <PanelHeader
            title="حقول القالب"
            meta={`${mappedCount} من ${entries.length} مرتبطة`}
          />
          {mapping === null ? (
            <Spinner />
          ) : (
            entries.map((entry) => {
              const isRequired = required.has(entry.field_key);
              const unmapped = !entry.column && !entry.static_value;
              return (
                <div
                  key={entry.field_key}
                  className={`grid items-center gap-3 border-b border-line px-5 py-3 last:border-b-0 sm:grid-cols-[1fr_1.2fr] ${
                    isRequired && unmapped ? "bg-[#FDF7F4]" : ""
                  }`}
                >
                  <div className="min-w-0">
                    <div className="truncate text-sm font-medium">
                      {labels.get(entry.field_key) ?? entry.field_key}
                    </div>
                    <div className="mono truncate text-xs text-muted-soft">
                      {entry.field_key}
                      {isRequired ? " · إلزامي" : ""}
                    </div>
                  </div>
                  <select
                    value={entry.column ?? ""}
                    onChange={(event) =>
                      setColumn(entry.field_key, event.target.value || null)
                    }
                    className={
                      isRequired && unmapped ? "border-bad text-bad" : undefined
                    }
                  >
                    <option value="">— بلا ربط —</option>
                    {columns.map((column) => (
                      <option key={column.name} value={column.name}>
                        {column.letter} — {column.name}
                      </option>
                    ))}
                  </select>
                </div>
              );
            })
          )}
        </Panel>
      </div>

      <Panel className="mt-6">
        <PanelHeader
          title="معاينة أول الصفوف كما ستُطبع"
          meta={`ROWS 1–${preview.length}`}
          action={
            <button
              type="button"
              className="btn-ghost"
              disabled={busy}
              onClick={() => void save("stay")}
            >
              تحديث المعاينة
            </button>
          }
        />
        {preview.length === 0 ? (
          <Spinner />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] text-sm">
              <thead>
                <tr className="border-b border-line bg-paper text-xs text-muted">
                  <th className="px-4 py-2 text-right font-normal">
                    <Mono>ROW</Mono>
                  </th>
                  {entries.map((entry) => (
                    <th
                      key={entry.field_key}
                      className="px-4 py-2 text-right font-normal"
                    >
                      {labels.get(entry.field_key) ?? entry.field_key}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {preview.map((record) => (
                  <tr key={record.id} className="border-b border-line last:border-b-0">
                    <td className="px-4 py-2.5">
                      <Mono>{String(record.row_index + 1).padStart(3, "0")}</Mono>
                    </td>
                    {entries.map((entry) => (
                      <td key={entry.field_key} className="px-4 py-2.5">
                        {String(record.values[entry.field_key] ?? "") || (
                          <span className="text-muted-soft">—</span>
                        )}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </AppShell>
  );
}
