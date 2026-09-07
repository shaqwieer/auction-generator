"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { AppShell, RequireAuth } from "@/components/shell";
import {
  Banner,
  Empty,
  Mono,
  Panel,
  PanelHeader,
  Row,
  Spinner,
  StatusPill,
  Table,
} from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import type { CategoryOut, TemplateIngestOut, TemplateOut } from "@/types/api";

const COLUMNS = "1.6fr 1fr 110px 80px 100px 90px";

export default function AdminTemplatesPage() {
  return (
    <RequireAuth staffOnly>
      <AdminTemplates />
    </RequireAuth>
  );
}

function AdminTemplates() {
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);

  const [templates, setTemplates] = useState<TemplateOut[] | null>(null);
  const [categories, setCategories] = useState<CategoryOut[]>([]);
  const [name, setName] = useState("");
  const [categoryId, setCategoryId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [report, setReport] = useState<TemplateIngestOut | null>(null);

  const load = useCallback(async () => {
    const [list, cats] = await Promise.all([
      api.templates().catch(() => []),
      api.categories().catch(() => []),
    ]);
    setTemplates(list);
    setCategories(cats);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function upload(file: File) {
    setBusy(true);
    setError(null);
    setReport(null);
    try {
      const result = await api.uploadTemplate(
        file,
        name.trim() || file.name.replace(/\.[^.]+$/, ""),
        categoryId || undefined,
      );
      setReport(result);
      setName("");
      await load();
    } catch (caught) {
      setError(
        caught instanceof ApiError ? caught.message : "تعذّر رفع ملف التصميم.",
      );
    } finally {
      setBusy(false);
    }
  }

  const drafts = (templates ?? []).filter((t) => t.status !== "published").length;
  const categoryName = (id: string | null) =>
    categories.find((c) => c.id === id)?.name ?? "—";

  return (
    <AppShell
      breadcrumb="لوحة المشرف / القوالب"
      action={
        <button
          type="button"
          className="btn-primary"
          disabled={busy}
          onClick={() => inputRef.current?.click()}
        >
          {busy ? "جارٍ التحليل…" : "رفع قالب جديد"} <span aria-hidden>←</span>
        </button>
      }
    >
      {error ? <Banner tone="error" title={error} /> : null}

      {report ? (
        <div className="mb-5">
          <Banner tone="info" title={`رُفع «${report.template.name}» كمسودة`}>
            <Mono>{report.pages}</Mono> صفحة ·{" "}
            <Mono>{report.proposed_fields}</Mono> حقلًا مقترحًا، منها{" "}
            <Mono>{report.auto_named}</Mono> سُمّيت تلقائيًا من التسميات المطبوعة
            و<Mono>{report.tables}</Mono> جدولًا. افتح المحرّر لمراجعتها ثم انشر.
          </Banner>
        </div>
      ) : null}

      <Panel className="mb-6 p-5">
        <div className="grid items-end gap-4 sm:grid-cols-[1.5fr_1fr_auto]">
          <div>
            <label className="field-label" htmlFor="tname">
              اسم القالب
            </label>
            <input
              id="tname"
              value={name}
              placeholder="مثال: كتيّب المزاد — حضوري"
              onChange={(e) => setName(e.target.value)}
            />
          </div>
          <div>
            <label className="field-label" htmlFor="tcat">
              التصنيف
            </label>
            <select
              id="tcat"
              value={categoryId}
              onChange={(e) => setCategoryId(e.target.value)}
            >
              <option value="">— بلا تصنيف —</option>
              {categories.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </div>
          <button
            type="button"
            className="btn-secondary"
            disabled={busy}
            onClick={() => inputRef.current?.click()}
          >
            اختر ملف التصميم
          </button>
        </div>
        <p className="mt-3 text-sm text-muted">
          ارفع ملف المصمّم كما هو — <Mono>.ai</Mono> أو <Mono>.pdf</Mono>. نقرأ
          مواضع النصوص والصور منه ونقترح الحقول. لا يُعدَّل الأصل: تُنظَّف الخلفية
          عند النشر فقط.
        </p>
        <input
          ref={inputRef}
          type="file"
          accept=".ai,.pdf,application/pdf"
          hidden
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) void upload(file);
            e.target.value = "";
          }}
        />
      </Panel>

      <Panel>
        <PanelHeader
          title="القوالب"
          meta={
            templates
              ? `${templates.length} TEMPLATES · ${drafts} DRAFTS`
              : undefined
          }
        />
        {templates === null ? (
          <Spinner />
        ) : templates.length === 0 ? (
          <Empty
            title="لا توجد قوالب"
            hint="ارفع ملف تصميم من المصمّم للبدء."
          />
        ) : (
          <Table
            columns={COLUMNS}
            head={[
              "القالب",
              "التصنيف",
              <Mono key="s">SIZE</Mono>,
              <Mono key="f">FIELDS</Mono>,
              "النشر",
              "",
            ]}
          >
            {templates.map((template) => (
              <Row key={template.id} columns={COLUMNS}>
                <button
                  type="button"
                  className="min-w-0 text-right"
                  onClick={() => router.push(`/admin/templates/${template.id}`)}
                >
                  <div className="truncate font-medium hover:text-accent">
                    {template.name}
                  </div>
                  <div className="mono truncate text-xs text-muted-soft">
                    {template.code} · v{template.version} · {template.page_count} pp
                  </div>
                </button>
                <span className="truncate text-muted">
                  {categoryName(template.category_id)}
                </span>
                <Mono>
                  {Math.round(template.page_width)}×
                  {Math.round(template.page_height)}
                </Mono>
                <Mono>{template.field_count}</Mono>
                <StatusPill
                  status={template.status === "published" ? "ready" : "draft"}
                />
                <button
                  type="button"
                  className="text-xs text-muted-soft hover:text-bad"
                  onClick={async () => {
                    setError(null);
                    try {
                      await api.deleteTemplate(template.id);
                      await load();
                    } catch (caught) {
                      setError(
                        caught instanceof ApiError
                          ? caught.message
                          : "تعذّر الحذف.",
                      );
                    }
                  }}
                >
                  حذف
                </button>
              </Row>
            ))}
          </Table>
        )}
      </Panel>
    </AppShell>
  );
}
