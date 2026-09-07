"use client";

import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { RecordPhotos } from "@/components/photos";
import { AppShell, RequireAuth } from "@/components/shell";
import { Banner, Mono, Panel, PanelHeader, Spinner, Steps } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { WIZARD_STEPS } from "@/lib/wizard";
import type { PreflightOut, ProjectOut, TemplateDetail } from "@/types/api";

export default function ReviewPage() {
  return (
    <RequireAuth>
      <Review />
    </RequireAuth>
  );
}

function Review() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();

  const [project, setProject] = useState<ProjectOut | null>(null);
  const [template, setTemplate] = useState<TemplateDetail | null>(null);
  const [check, setCheck] = useState<PreflightOut | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void (async () => {
      try {
        const loaded = await api.project(id);
        setProject(loaded);
        const [detail, preflight] = await Promise.all([
          api.template(loaded.template_id),
          api.preflight(id),
        ]);
        setTemplate(detail);
        setCheck(preflight);
      } catch {
        setError("تعذّر تحميل المراجعة.");
      }
    })();
  }, [id]);

  async function patch(body: Record<string, unknown>) {
    setProject(await api.updateProject(id, body));
  }

  async function start() {
    setBusy(true);
    setError(null);
    try {
      const job = await api.generate(id);
      router.push(`/projects/${id}/status?job=${job.id}`);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "تعذّر بدء التوليد.");
      setBusy(false);
    }
  }

  const rejected = Object.entries(check?.rejected ?? {});

  return (
    <AppShell
      breadcrumb={
        project?.has_plan
          ? `${project.name} · الخطوة 3 من 3`
          : `مشروع جديد · الخطوة 4 من 4 · ${project?.name ?? ""}`
      }
      action={
        <div className="flex gap-2">
          <button
            type="button"
            className="btn-secondary"
            onClick={() =>
              router.push(
                project?.has_plan
                  ? `/projects/${id}/build`
                  : `/projects/${id}/mapping`,
              )
            }
          >
            <span aria-hidden>→</span>{" "}
            {project?.has_plan ? "رجوع للباني" : "رجوع للربط"}
          </button>
          <button
            type="button"
            className="btn-primary"
            disabled={busy || !check || check.generatable === 0}
            onClick={() => void start()}
          >
            {busy ? "جارٍ البدء…" : "ابدأ التوليد"} <span aria-hidden>←</span>
          </button>
        </div>
      }
    >
      <Steps steps={WIZARD_STEPS} current={2} />
      <h1 className="mt-6 text-2xl font-semibold">راجِع ثم ابدأ التوليد</h1>

      {error ? (
        <div className="mt-5">
          <Banner tone="error" title={error} />
        </div>
      ) : null}

      {rejected.length > 0 ? (
        <div className="mt-5">
          <Banner
            tone="warn"
            title={`${rejected.length} ${rejected.length === 1 ? "صفّ سيُستبعد" : "صفوف ستُستبعد"} قبل البدء`}
          >
            الصفوف{" "}
            <Mono>{rejected.map(([row]) => Number(row) + 1).join(", ")}</Mono> —
            قيم إلزامية فارغة. يمكنك المتابعة وتوليد {check?.generatable} سجلًّا، أو
            تعديل الملف وإعادة رفعه.
          </Banner>
        </div>
      ) : null}

      {check?.missing_assets.length ? (
        <div className="mt-3">
          <Banner
            tone="warn"
            title={`${check.missing_assets.length} صورة مشار إليها وغير مرفوعة`}
          >
            <Mono>{check.missing_assets.join("، ")}</Mono> — ارفعها من مكتبة
            الأصول لتظهر في الملف.
          </Banner>
        </div>
      ) : null}

      {/*
        Photographs belong on the page they print on, and in the builder that is
        where they are attached — one الصور panel per page, beside the page
        itself. A second grid of every image in the booklet at the very end
        asked a client to place pictures they can no longer see the pages for.

        Projects made before the builder have no such page to attach them to, so
        for those this is still the only way in.
      */}
      {project && !project.has_plan ? (
        <div className="mt-6">
          <RecordPhotos
            projectId={id}
            onChange={() => void api.preflight(id).then(setCheck)}
          />
        </div>
      ) : null}

      {/*
        Paper or screen. The pages are the same either way — only the link chips
        differ, and they differ because a code nobody can scan is no use on a
        screen and a link nobody can click is no use on paper.
      */}
      {project?.has_plan ? (
        <Panel className="mt-6">
          <PanelHeader title="صيغة المخرجات" />
          <div className="grid gap-2 p-5 sm:grid-cols-2">
            {(
              [
                {
                  value: "print",
                  title: "للطباعة",
                  hint: "روابط العقار تُطبع رموز QR تُمسح بالجوال.",
                },
                {
                  value: "electronic",
                  title: "إلكتروني",
                  hint: "روابط العقار قابلة للنقر داخل ملف PDF.",
                },
              ] as const
            ).map((choice) => (
              <button
                key={choice.value}
                type="button"
                disabled={busy}
                onClick={() =>
                  void patch({ output_flavour: choice.value }).catch(() =>
                    setError("تعذّر تغيير صيغة المخرجات."),
                  )
                }
                className={`border p-4 text-start transition-colors ${
                  project.output_flavour === choice.value
                    ? "border-accent bg-[#FCE8F2]"
                    : "border-line hover:border-edge"
                }`}
              >
                <span className="block text-sm font-medium">{choice.title}</span>
                <span className="mt-1 block text-xs text-muted-soft">
                  {choice.hint}
                </span>
              </button>
            ))}
          </div>
          <p className="border-t border-line px-5 py-3 text-xs text-muted-soft">
            رمز QR يشير إلى عنوان ثابت من نظامك، لا إلى الرابط نفسه — فتغيير
            الوجهة لاحقًا لا يستدعي إعادة الطباعة.
          </p>
        </Panel>
      ) : null}

      <div className="mt-6 grid gap-6 lg:grid-cols-[1.2fr_1fr]">
        <Panel>
          <PanelHeader title="ملخّص المشروع" />
          {check === null ? (
            <Spinner />
          ) : (
            <dl className="divide-y divide-line">
              <Line label="القالب" value={project?.template_name ?? "—"} />
              <Line
                label="رمز القالب"
                value={<Mono>{template?.code ?? "—"}</Mono>}
              />
              <Line
                label="عدد السجلات"
                value={<Mono>{check.record_count}</Mono>}
              />
              <Line
                label="السجلات القابلة للتوليد"
                value={<Mono>{check.generatable}</Mono>}
              />
              <Line
                label="الصفحات المتوقّعة"
                value={
                  <span>
                    <Mono>{check.predicted_pages}</Mono>{" "}
                    <span className="text-xs text-muted-soft">
                      أقسام ثابتة + صفحتان لكل سجلّ
                    </span>
                  </span>
                }
              />
            </dl>
          )}
        </Panel>

        <Panel>
          <PanelHeader title="إعدادات المخرجات" />
          <div className="space-y-1 p-5">
            <Choice
              checked={project?.output_mode === "merged"}
              onChange={() => void patch({ output_mode: "merged" })}
              title="ملف PDF واحد مجمّع"
              hint="كل السجلات في كتيّب واحد."
            />
            <Choice
              checked={project?.output_mode === "per_record"}
              onChange={() => void patch({ output_mode: "per_record" })}
              title="ملف لكل سجلّ داخل ZIP"
              hint="مناسب للتوزيع الفردي."
            />

            <div className="pt-3">
              <Toggle
                checked={project?.add_bleed ?? false}
                onChange={(value) => void patch({ add_bleed: value })}
                title="علامات قصّ وحدّ اقتصاص 3mm"
                hint="ملفات التصميم الحالية بلا حدّ اقتصاص — فعّلها فقط بطلب المطبعة."
              />
              <Toggle
                checked={project?.convert_cmyk ?? false}
                onChange={(value) => void patch({ convert_cmyk: value })}
                title="تحويل الألوان إلى CMYK"
                hint="التصميم المعتمد بنظام RGB — التحويل سيغيّر الألوان المعتمدة."
              />
            </div>
          </div>
        </Panel>
      </div>
    </AppShell>
  );
}

function Line({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4 px-5 py-3 text-sm">
      <dt className="text-muted">{label}</dt>
      <dd className="font-medium">{value}</dd>
    </div>
  );
}

function Choice({
  checked,
  onChange,
  title,
  hint,
}: {
  checked: boolean;
  onChange: () => void;
  title: string;
  hint: string;
}) {
  return (
    <label className="flex cursor-pointer items-start gap-3 rounded px-2 py-2 hover:bg-paper">
      <input
        type="radio"
        checked={checked}
        onChange={onChange}
        className="mt-1 h-4 w-4 shrink-0"
      />
      <span>
        <span className="block text-sm font-medium">{title}</span>
        <span className="block text-xs text-muted-soft">{hint}</span>
      </span>
    </label>
  );
}

function Toggle({
  checked,
  onChange,
  title,
  hint,
}: {
  checked: boolean;
  onChange: (value: boolean) => void;
  title: string;
  hint: string;
}) {
  return (
    <label className="flex cursor-pointer items-start gap-3 rounded px-2 py-2 hover:bg-paper">
      <input
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        className="mt-1 h-4 w-4 shrink-0"
      />
      <span>
        <span className="block text-sm font-medium">{title}</span>
        <span className="block text-xs text-muted-soft">{hint}</span>
      </span>
    </label>
  );
}
