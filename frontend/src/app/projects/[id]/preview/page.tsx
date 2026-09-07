/**
 * Look at the generated booklet before sending it to print.
 *
 * Pages are rastered on demand by the API, and only the ones scrolled into view
 * are requested — a 120-page booklet would otherwise fire 120 renders at once.
 */
"use client";

import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { AppShell, RequireAuth } from "@/components/shell";
import {
  AuthImage,
  Banner,
  Empty,
  Mono,
  Panel,
  PanelHeader,
  Spinner,
  bytes,
} from "@/components/ui";
import { API_URL, api, tryDownload } from "@/lib/api";
import type { JobDetail, ResultOut } from "@/types/api";

export default function PreviewPage() {
  return (
    <RequireAuth>
      <Preview />
    </RequireAuth>
  );
}

function Preview() {
  const { id } = useParams<{ id: string }>();
  const params = useSearchParams();
  const router = useRouter();

  const [job, setJob] = useState<JobDetail | null>(null);
  const [issues, setIssues] = useState<ResultOut[]>([]);
  const [current, setCurrent] = useState(0);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void (async () => {
      try {
        let jobId = params.get("job");
        if (!jobId) {
          const dashboard = await api.dashboard();
          jobId =
            dashboard.recent_jobs.find(
              (j) => j.project_id === id && j.status === "succeeded",
            )?.id ?? null;
        }
        if (!jobId) {
          setError("لا يوجد ملف مولّد لهذا المشروع بعد.");
          return;
        }
        const detail = await api.job(jobId);
        setJob(detail);
        setIssues(await api.jobResults(jobId));
      } catch {
        setError("تعذّر تحميل المعاينة.");
      }
    })();
  }, [id, params]);

  const isZip = (job?.output_filename ?? "").endsWith(".zip");
  const pages = useMemo(
    () => Array.from({ length: job?.page_count ?? 0 }, (_, i) => i),
    [job?.page_count],
  );
  const pageIssues = issues.filter((i) => i.severity !== "error");
  const errors = issues.filter((i) => i.severity === "error");

  return (
    <AppShell
      breadcrumb={`معاينة · ${job?.project_name ?? ""}`}
      action={
        job?.status === "succeeded" ? (
          <div className="flex gap-2">
            <button
              type="button"
              className="btn-secondary"
              onClick={() => router.push(`/projects/${id}/status?job=${job.id}`)}
            >
              حالة التوليد
            </button>
            <button
              type="button"
              className="btn-primary"
              onClick={async () =>
                setError(
                  await tryDownload(
                    `/api/v1/jobs/${job.id}/download`,
                    job.output_filename ?? "output.pdf",
                  ),
                )
              }
            >
              تنزيل الملف <span aria-hidden>←</span>
            </button>
          </div>
        ) : undefined
      }
    >
      {error ? <Banner tone="error" title={error} /> : null}

      {job === null ? (
        <Panel>
          <Spinner />
        </Panel>
      ) : isZip ? (
        <Panel>
          <Empty
            title="المعاينة متاحة للملف المجمّع فقط"
            hint="هذا المشروع يُنتج ملفًا لكل سجلّ داخل ZIP — نزّل الحزمة لمراجعتها."
          />
        </Panel>
      ) : (
        <>
          <div className="flex flex-wrap items-baseline justify-between gap-3">
            <h1 className="text-2xl font-semibold">{job.project_name}</h1>
            <span className="mono text-sm text-muted">
              {job.output_filename} · {job.page_count} pp ·{" "}
              {bytes(job.output_bytes)}
            </span>
          </div>

          {errors.length > 0 ? (
            <div className="mt-4">
              <Banner
                tone="warn"
                title={`${errors.length} صفًّا استُبعد من هذا الملف`}
              >
                {errors
                  .slice(0, 3)
                  .map((e) => `الصفّ ${e.row_index + 1}: ${e.cause}`)
                  .join(" · ")}
              </Banner>
            </div>
          ) : null}

          <div className="mt-6 grid gap-6 lg:grid-cols-[260px_1fr]">
            <Panel className="h-fit">
              <PanelHeader title="الصفحات" meta={`${job.page_count}`} />
              <div className="grid max-h-[70vh] grid-cols-3 gap-3 overflow-y-auto p-4">
                {pages.map((index) => (
                  <Thumbnail
                    key={index}
                    jobId={job.id}
                    index={index}
                    active={current === index}
                    onSelect={() => setCurrent(index)}
                  />
                ))}
              </div>
            </Panel>

            <Panel className="p-5">
              <div className="mb-3 flex items-center justify-between">
                <button
                  type="button"
                  className="btn-secondary"
                  disabled={current === 0}
                  onClick={() => setCurrent((n) => Math.max(0, n - 1))}
                >
                  <span aria-hidden>→</span> السابقة
                </button>
                <span className="mono text-sm">
                  {String(current + 1).padStart(2, "0")}/{job.page_count}
                </span>
                <button
                  type="button"
                  className="btn-secondary"
                  disabled={current >= job.page_count - 1}
                  onClick={() =>
                    setCurrent((n) => Math.min(job.page_count - 1, n + 1))
                  }
                >
                  التالية <span aria-hidden>←</span>
                </button>
              </div>

              <div className="mx-auto max-w-2xl border border-line bg-paper">
                <AuthImage
                  src={`${API_URL}/api/v1/jobs/${job.id}/pages/${current}.png?dpi=130`}
                  alt={`صفحة ${current + 1}`}
                  className="block w-full"
                />
              </div>

              {pageIssues.length > 0 ? (
                <div className="mt-5">
                  <div className="mb-2 text-sm font-medium">
                    تحذيرات على هذا الملف
                  </div>
                  <ul className="space-y-1.5 text-sm text-muted">
                    {pageIssues.slice(0, 8).map((issue, n) => (
                      <li key={n} className="flex gap-2">
                        <Mono>
                          <span className="text-xs text-muted-soft">
                            {String(issue.row_index + 1).padStart(3, "0")}
                          </span>
                        </Mono>
                        <span>{issue.cause}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </Panel>
          </div>
        </>
      )}
    </AppShell>
  );
}

/** Requests its raster only once it has been scrolled into view. */
function Thumbnail({
  jobId,
  index,
  active,
  onSelect,
}: {
  jobId: string;
  index: number;
  active: boolean;
  onSelect: () => void;
}) {
  const ref = useRef<HTMLButtonElement>(null);
  const [visible, setVisible] = useState(index < 9);

  const observe = useCallback(() => {
    if (visible || !ref.current) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          setVisible(true);
          observer.disconnect();
        }
      },
      { rootMargin: "200px" },
    );
    observer.observe(ref.current);
    return () => observer.disconnect();
  }, [visible]);

  useEffect(() => observe(), [observe]);

  return (
    <button
      ref={ref}
      type="button"
      onClick={onSelect}
      className={`block border transition-colors ${
        active ? "border-accent ring-1 ring-accent" : "border-line hover:border-edge"
      }`}
    >
      <span className="block aspect-[210/297] w-full bg-paper">
        {visible ? (
          <AuthImage
            src={`${API_URL}/api/v1/jobs/${jobId}/pages/${index}.png?dpi=40`}
            alt={`صفحة ${index + 1}`}
            className="h-full w-full object-contain"
          />
        ) : null}
      </span>
      <span className="mono block py-1 text-center text-[10px] text-muted-soft">
        {String(index + 1).padStart(2, "0")}
      </span>
    </button>
  );
}
