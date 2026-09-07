"use client";

import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { AppShell, RequireAuth } from "@/components/shell";
import { Banner, Mono, Panel, PanelHeader, Spinner, Steps } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { LEGACY_WIZARD_STEPS } from "@/lib/wizard";
import type { ProjectOut, TemplateDetail, UploadResult } from "@/types/api";

const TYPE_LABELS: Record<string, string> = {
  text: "نص",
  image: "صورة",
  qr: "QR",
  barcode: "باركود",
  link: "رابط",
  table: "جدول",
};

export default function DataSourcePage() {
  return (
    <RequireAuth>
      <DataSource />
    </RequireAuth>
  );
}

function DataSource() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);

  const [project, setProject] = useState<ProjectOut | null>(null);
  const [template, setTemplate] = useState<TemplateDetail | null>(null);
  const [result, setResult] = useState<UploadResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);

  useEffect(() => {
    void (async () => {
      try {
        const loaded = await api.project(id);
        setProject(loaded);
        setTemplate(await api.template(loaded.template_id));
      } catch {
        setError("تعذّر تحميل المشروع.");
      }
    })();
  }, [id]);

  const upload = useCallback(
    async (file: File) => {
      setBusy(true);
      setError(null);
      try {
        setResult(await api.uploadDataSource(id, file));
      } catch (caught) {
        setError(caught instanceof ApiError ? caught.message : "تعذّر رفع الملف.");
      } finally {
        setBusy(false);
      }
    },
    [id],
  );

  const expected = (template?.fields ?? []).filter(
    (field) =>
      field.type !== "table" && template?.record_keys.includes(field.key),
  );
  const seen = new Set<string>();
  const uniqueExpected = expected.filter((field) => {
    if (seen.has(field.key)) return false;
    seen.add(field.key);
    return true;
  });

  return (
    <AppShell
      breadcrumb={`مشروع جديد · الخطوة 2 من 4 · ${project?.name ?? ""}`}
      action={
        <div className="flex gap-2">
          <button
            type="button"
            className="btn-secondary"
            onClick={() => router.push("/projects/new")}
          >
            <span aria-hidden>→</span> رجوع
          </button>
          <button
            type="button"
            className="btn-primary"
            disabled={!result}
            onClick={() => router.push(`/projects/${id}/mapping`)}
          >
            التالي: ربط الأعمدة <span aria-hidden>←</span>
          </button>
        </div>
      }
    >
      <Steps steps={LEGACY_WIZARD_STEPS} current={1} />
      <h1 className="mt-6 text-2xl font-semibold">من أين تأتي البيانات؟</h1>
      <p className="mt-2 text-md text-muted">
        طريقتان: ارفع ملف Excel، أو أدخِل العناصر يدويًا. الصور تُضاف في خطوة
        المراجعة أيًّا كانت الطريقة.
      </p>

      <div className="mt-6 grid gap-6 lg:grid-cols-[1.2fr_1fr]">
        <div className="space-y-4">
          <Panel className="p-6">
            <h2 className="text-lg font-semibold">ارفع ملف Excel</h2>

            <div
              onDragOver={(event) => {
                event.preventDefault();
                setDragging(true);
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={(event) => {
                event.preventDefault();
                setDragging(false);
                const file = event.dataTransfer.files[0];
                if (file) void upload(file);
              }}
              className={`mt-4 border border-dashed px-6 py-10 text-center transition-colors ${
                dragging ? "border-accent bg-[#FCE8F2]" : "border-edge bg-paper"
              }`}
            >
              {busy ? (
                <Spinner label="جارٍ قراءة الملف…" />
              ) : result ? (
                <div>
                  <div className="text-md font-medium text-ok">
                    ✓ {result.data_source.filename}
                  </div>
                  <div className="mono mt-2 text-sm text-muted">
                    {result.data_source.row_count} ROWS ·{" "}
                    {result.data_source.columns.length} COLS ·{" "}
                    {result.data_source.sheet}
                  </div>
                  <button
                    type="button"
                    className="btn-ghost mt-2"
                    onClick={() => {
                      setResult(null);
                      inputRef.current?.click();
                    }}
                  >
                    تغيير الملف
                  </button>
                </div>
              ) : (
                <>
                  <p className="text-md">اسحب ملف Excel وأفلته هنا</p>
                  <button
                    type="button"
                    className="btn-secondary mt-3"
                    onClick={() => inputRef.current?.click()}
                  >
                    أو اختر ملفًا من جهازك
                  </button>
                  <p className="mono mt-3 text-xs text-muted-soft">
                    .xlsx .csv — حتى 25 MB
                  </p>
                </>
              )}
              <input
                ref={inputRef}
                type="file"
                accept=".xlsx,.xlsm,.csv"
                hidden
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  if (file) void upload(file);
                }}
              />
            </div>

            {error ? (
              <div className="mt-4">
                <Banner tone="error" title={error} />
              </div>
            ) : null}

            {result?.data_source.warnings.length ? (
              <div className="mt-4 space-y-2">
                {result.data_source.warnings.map((warning) => (
                  <Banner key={warning} title={warning} />
                ))}
              </div>
            ) : null}
          </Panel>

          <Panel className="border-r-2 border-r-accent p-6">
            <h2 className="text-lg font-semibold">أو أدخِل البيانات يدويًا</h2>
            <p className="mt-2 text-sm leading-relaxed text-muted">
              بلا ملف Excel — أضِف كل عقار بنفسك في نموذج عربي، مع صورة لكل عنصر.
              مناسب للمزادات الصغيرة وللافتة أو نموذج واحد.
            </p>
            <button
              type="button"
              className="btn-primary mt-4"
              onClick={() => router.push(`/projects/${id}/manual`)}
            >
              ابدأ الإدخال اليدوي <span aria-hidden>←</span>
            </button>
          </Panel>
        </div>

        <Panel>
          <PanelHeader
            title="القالب يتوقّع هذه الأعمدة"
            meta={template ? `${uniqueExpected.length} FIELDS` : undefined}
          />
          <p className="border-b border-line px-5 py-3 text-sm text-muted">
            أسماء الأعمدة لا يجب أن تتطابق حرفيًا — سنقترح الربط في الخطوة التالية.
          </p>
          {template === null ? (
            <Spinner />
          ) : (
            uniqueExpected.map((field) => (
              <div
                key={field.key}
                className="flex items-center justify-between gap-3 border-b border-line px-5 py-2.5 text-sm last:border-b-0"
              >
                <span>{field.label || field.key}</span>
                <span className="text-muted-soft">
                  {TYPE_LABELS[field.type] ?? field.type} ·{" "}
                  {field.is_required ? "إلزامي" : "اختياري"}
                </span>
              </div>
            ))
          )}
        </Panel>
      </div>

      {result ? (
        <Panel className="mt-6">
          <PanelHeader
            title="معاينة أول الصفوف"
            meta={`ROWS 1–${result.preview.length} OF ${result.data_source.row_count}`}
          />
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] text-sm">
              <thead>
                <tr className="border-b border-line bg-paper text-xs text-muted">
                  {result.data_source.columns.map((column) => (
                    <th key={column.name} className="px-4 py-2 text-right font-normal">
                      <Mono>{column.letter}</Mono> {column.name}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {result.preview.map((row, index) => (
                  <tr key={index} className="border-b border-line last:border-b-0">
                    {result.data_source.columns.map((column) => (
                      <td key={column.name} className="px-4 py-2.5">
                        {row[column.name] ?? ""}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      ) : null}
    </AppShell>
  );
}
