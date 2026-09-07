"use client";

import { useCallback, useEffect, useState } from "react";

import { AppShell, RequireAuth } from "@/components/shell";
import {
  Empty,
  Mono,
  Panel,
  PanelHeader,
  Row,
  Spinner,
  StatusPill,
  Table,
  duration,
} from "@/components/ui";
import { api } from "@/lib/api";
import type { JobDetail } from "@/types/api";

const COLUMNS = "90px 1.6fr 1fr 80px 110px";

const FILTERS = [
  { value: "", label: "الكل" },
  { value: "failed", label: "فاشلة" },
  { value: "running", label: "قيد التنفيذ" },
  { value: "succeeded", label: "مكتملة" },
];

export default function OpsPage() {
  return (
    <RequireAuth staffOnly>
      <Ops />
    </RequireAuth>
  );
}

function Ops() {
  const [jobs, setJobs] = useState<JobDetail[] | null>(null);
  const [summary, setSummary] = useState<Record<string, number> | null>(null);
  const [filter, setFilter] = useState("");
  const [selected, setSelected] = useState<JobDetail | null>(null);

  const load = useCallback(async () => {
    const params: Record<string, string> = { limit: "60" };
    if (filter) params.status = filter;
    const [list, ops] = await Promise.all([
      api.jobs(params),
      api.opsSummary().catch(() => null),
    ]);
    setJobs(list);
    setSummary(ops);
    setSelected((current) =>
      current ? (list.find((job) => job.id === current.id) ?? current) : null,
    );
  }, [filter]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    const timer = setInterval(() => void load(), 5000);
    return () => clearInterval(timer);
  }, [load]);

  return (
    <AppShell
      breadcrumb="لوحة المشرف / مراقب العمليات"
      action={
        <span className="mono text-xs text-muted-soft">
          {summary
            ? `ENGINES ${summary.engines_up}/${summary.engines_total} · LAST 24H ${summary.jobs_24h} JOBS · ${summary.failed_24h} FAILED`
            : ""}
        </span>
      }
    >
      <div className="flex flex-wrap items-center gap-2 pb-5">
        {FILTERS.map((item) => (
          <button
            key={item.value || "all"}
            type="button"
            onClick={() => setFilter(item.value)}
            className={`rounded border px-2.5 py-1 text-sm ${
              filter === item.value
                ? "border-ink bg-ink text-white"
                : "border-line bg-surface text-muted hover:border-edge"
            }`}
          >
            {item.label}
          </button>
        ))}
      </div>

      <div className="grid gap-6 lg:grid-cols-[1.5fr_1fr]">
        <Panel>
          <PanelHeader
            title="المهام"
            meta={jobs ? `${jobs.length} JOBS` : undefined}
          />
          {jobs === null ? (
            <Spinner />
          ) : jobs.length === 0 ? (
            <Empty title="لا توجد مهام مطابقة" />
          ) : (
            <Table
              columns={COLUMNS}
              head={[
                <Mono key="j">JOB</Mono>,
                "المهمة والعميل",
                <Mono key="e">ENGINE</Mono>,
                <Mono key="d">DUR</Mono>,
                "الحالة",
              ]}
            >
              {jobs.map((job) => (
                <Row
                  key={job.id}
                  columns={COLUMNS}
                  tone={job.status === "failed" ? "bad" : undefined}
                  onClick={() => setSelected(job)}
                >
                  <Mono>J-{job.id.slice(0, 4).toUpperCase()}</Mono>
                  <div className="min-w-0">
                    <div className="truncate">{job.project_name ?? "—"}</div>
                    <div className="truncate text-xs text-muted-soft">
                      {job.client_name ?? "—"}
                    </div>
                  </div>
                  <Mono>{job.engine || "—"}</Mono>
                  <Mono>{duration(job.started_at, job.finished_at)}</Mono>
                  <StatusPill status={job.status} />
                </Row>
              ))}
            </Table>
          )}
        </Panel>

        <Panel className="h-fit">
          <PanelHeader
            title={selected ? "تفاصيل المهمّة" : "اختر مهمّة"}
            meta={selected ? `J-${selected.id.slice(0, 4).toUpperCase()}` : undefined}
          />
          {selected === null ? (
            <Empty title="اختر مهمّة من القائمة لعرض سجلّها" />
          ) : (
            <div className="p-5">
              {selected.error_summary ? (
                <p className="border border-[#F3D6C6] bg-[#FDF2EC] px-3 py-2 text-sm text-bad">
                  {selected.error_summary}
                </p>
              ) : null}

              <dl className="mt-4 divide-y divide-line text-sm">
                {[
                  ["المشروع", selected.project_name ?? "—"],
                  ["العميل", selected.client_name ?? "—"],
                  ["المحرّك", selected.engine || "—"],
                  ["السجلات", `${selected.completed_records}/${selected.total_records}`],
                  ["الصفحات", String(selected.page_count)],
                ].map(([label, value]) => (
                  <div key={label} className="flex justify-between gap-3 py-2">
                    <dt className="text-muted">{label}</dt>
                    <dd className="font-medium">{value}</dd>
                  </div>
                ))}
              </dl>

              {selected.log.length > 0 ? (
                <div className="mono mt-4 space-y-1 border-t border-line pt-4 text-xs text-muted">
                  {selected.log.slice(-14).map((entry, index) => (
                    <div key={index}>
                      {entry.at} {entry.level} {entry.message}
                    </div>
                  ))}
                </div>
              ) : null}

              {selected.status === "failed" ? (
                <button
                  type="button"
                  className="btn-secondary mt-4"
                  onClick={async () => {
                    await api.retryJob(selected.id);
                    void load();
                  }}
                >
                  إعادة التشغيل
                </button>
              ) : null}
            </div>
          )}
        </Panel>
      </div>
    </AppShell>
  );
}
