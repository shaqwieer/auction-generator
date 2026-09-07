"use client";

import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { AppShell, RequireAuth } from "@/components/shell";
import {
  Banner,
  Empty,
  Mono,
  Panel,
  PanelHeader,
  Progress,
  Row,
  Spinner,
  StatusPill,
  Table,
  bytes,
  duration,
} from "@/components/ui";
import { api, tryDownload } from "@/lib/api";
import type { JobDetail, ResultOut } from "@/types/api";

const COLUMNS = "70px 1fr 2.2fr";
const ACTIVE = ["queued", "running", "paused"];

export default function StatusPage() {
  return (
    <RequireAuth>
      <Status />
    </RequireAuth>
  );
}

function Status() {
  const { id } = useParams<{ id: string }>();
  const params = useSearchParams();
  const router = useRouter();

  const [job, setJob] = useState<JobDetail | null>(null);
  const [results, setResults] = useState<ResultOut[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [downloadError, setDownloadError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      let jobId = params.get("job");
      if (!jobId) {
        const project = await api.project(id);
        const all = await api.jobs();
        jobId =
          all.find((candidate) => candidate.project_id === project.id)?.id ?? null;
      }
      if (!jobId) {
        setError("لا توجد عملية توليد لهذا المشروع بعد.");
        return;
      }
      const detail = await api.job(jobId);
      setJob(detail);
      setResults(await api.jobResults(jobId, "rejected"));
    } catch {
      setError("تعذّر تحميل حالة التوليد.");
    }
  }, [id, params]);

  useEffect(() => {
    void load();
  }, [load]);

  // Poll while the job is live; stop the moment it settles.
  useEffect(() => {
    if (!job || !ACTIVE.includes(job.status)) return;
    const timer = setInterval(() => void load(), 1500);
    return () => clearInterval(timer);
  }, [job, load]);

  const running = job ? ACTIVE.includes(job.status) : false;
  const waiting = job
    ? Math.max(0, job.total_records - job.completed_records - job.rejected_records)
    : 0;

  return (
    <AppShell
      breadcrumb={`حالة التوليد · ${job?.project_name ?? ""}`}
      action={
        job?.status === "succeeded" ? (
          <div className="flex gap-2">
            <button
              type="button"
              className="btn-secondary"
              onClick={() => router.push(`/projects/${id}/preview?job=${job.id}`)}
            >
              معاينة الصفحات
            </button>
            <button
              type="button"
              className="btn-secondary"
              onClick={() => router.push(`/projects/${id}/review`)}
            >
              إعادة التوليد
            </button>
            <button
              type="button"
              className="btn-primary"
              onClick={async () =>
                setDownloadError(
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
        ) : running && job ? (
          <div className="flex gap-2">
            <button
              type="button"
              className="btn-secondary"
              onClick={async () => {
                await (job.status === "paused"
                  ? api.resumeJob(job.id)
                  : api.pauseJob(job.id));
                void load();
              }}
            >
              {job.status === "paused" ? "استئناف" : "إيقاف مؤقّت"}
            </button>
            <button
              type="button"
              className="btn-ghost"
              onClick={async () => {
                await api.cancelJob(job.id);
                void load();
              }}
            >
              إلغاء العملية
            </button>
          </div>
        ) : undefined
      }
    >
      {error ? <Banner tone="error" title={error} /> : null}
      {downloadError ? (
        <div className="mb-5">
          <Banner tone="error" title={downloadError}>
            أعِد التوليد للحصول على نسخة جديدة من الملف.
          </Banner>
        </div>
      ) : null}

      {job === null ? (
        <Panel>
          <Spinner />
        </Panel>
      ) : (
        <>
          <div className="flex flex-wrap items-baseline justify-between gap-3">
            <h1 className="text-2xl font-semibold">
              {running
                ? "جارٍ توليد ملفّك — يمكنك مغادرة الصفحة"
                : job.status === "succeeded"
                  ? "اكتمل التوليد"
                  : "توقّفت العملية"}
            </h1>
            <StatusPill status={job.status} />
          </div>

          <div className="mono mt-2 text-sm text-muted">
            {job.completed_records} من {job.total_records} سجلًّا ·{" "}
            {job.page_count} صفحة · ELAPSED{" "}
            {duration(job.started_at, job.finished_at)} · {job.engine || "—"}
          </div>

          <div className="mt-4">
            <Progress value={job.progress} />
          </div>

          <div className="mt-6 grid gap-px border border-line bg-line sm:grid-cols-3">
            <Metric label="مكتملة" value={job.completed_records} tone="ok" />
            <Metric label="مرفوضة" value={job.rejected_records} tone="bad" />
            <Metric label="في الانتظار" value={waiting} />
          </div>

          {job.error_summary ? (
            <div className="mt-6">
              <Banner tone="error" title="توقّف المحرّك">
                {job.error_summary}
              </Banner>
            </div>
          ) : null}

          {job.status === "succeeded" && job.output_filename ? (
            <Panel className="mt-6 flex flex-wrap items-center justify-between gap-3 p-5">
              <div>
                <div className="mono text-md">{job.output_filename}</div>
                <div className="mono mt-1 text-xs text-muted-soft">
                  {job.page_count} pp · {bytes(job.output_bytes)}
                </div>
              </div>
              <button
                type="button"
                className="btn-primary"
                onClick={async () =>
                  setDownloadError(
                    await tryDownload(
                      `/api/v1/jobs/${job.id}/download`,
                      job.output_filename ?? "output.pdf",
                    ),
                  )
                }
              >
                تنزيل
              </button>
            </Panel>
          ) : null}

          <Panel className="mt-6">
            <PanelHeader
              title="الصفوف المرفوضة"
              meta={results.length ? `${results.length} ROWS` : undefined}
              action={
                results.length > 0 ? (
                  <div className="flex gap-2">
                    {/* A plain href would 401: the export needs a bearer
                        token, so the download goes through fetch. */}
                    <button
                      type="button"
                      className="btn-secondary"
                      onClick={async () =>
                        setDownloadError(
                          await tryDownload(
                            `/api/v1/jobs/${job.id}/errors.xlsx`,
                            "errors.xlsx",
                          ),
                        )
                      }
                    >
                      تصدير قائمة الأخطاء
                    </button>
                    <button
                      type="button"
                      className="btn-primary"
                      onClick={async () => {
                        const next = await api.retryJob(job.id);
                        router.replace(
                          `/projects/${id}/status?job=${next.id}`,
                        );
                        void load();
                      }}
                    >
                      إعادة المحاولة على {results.length} صفوف
                    </button>
                  </div>
                ) : undefined
              }
            />
            {results.length === 0 ? (
              <Empty title="لا توجد صفوف مرفوضة" />
            ) : (
              <Table
                columns={COLUMNS}
                head={[<Mono key="r">ROW</Mono>, "الحقل", "السبب"]}
              >
                {results.map((result, index) => (
                  <Row key={index} columns={COLUMNS} tone="bad">
                    <Mono>{String(result.row_index + 1).padStart(3, "0")}</Mono>
                    <span className="mono truncate text-xs">
                      {result.field_key ?? "—"}
                    </span>
                    <span className="text-bad">{result.cause}</span>
                  </Row>
                ))}
              </Table>
            )}
          </Panel>

          {job.log.length > 0 ? (
            <Panel className="mt-6">
              <PanelHeader title="سجلّ التنفيذ" meta="LOG" />
              <div className="mono space-y-1 p-5 text-xs text-muted">
                {job.log.slice(-12).map((entry, index) => (
                  <div key={index}>
                    {entry.at} {entry.level} {entry.message}
                  </div>
                ))}
              </div>
            </Panel>
          ) : null}
        </>
      )}
    </AppShell>
  );
}

function Metric({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone?: "ok" | "bad";
}) {
  const color = tone === "ok" ? "text-ok" : tone === "bad" ? "text-bad" : "text-ink";
  return (
    <div className="bg-surface px-6 py-5">
      <div className="text-sm text-muted">{label}</div>
      <div className={`mono mt-1.5 text-2xl font-semibold ${color}`}>{value}</div>
    </div>
  );
}
