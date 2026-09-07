"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { AppShell, RequireAuth } from "@/components/shell";
import {
  Empty,
  Mono,
  Panel,
  PanelHeader,
  Progress,
  Row,
  Spinner,
  Stat,
  StatusPill,
  Table,
  Tiles,
  duration,
} from "@/components/ui";
import { api } from "@/lib/api";
import type { DashboardOut, JobDetail } from "@/types/api";

const COLUMNS = "90px 1.6fr 1fr 90px 130px";

export default function AdminPage() {
  return (
    <RequireAuth staffOnly>
      <Admin />
    </RequireAuth>
  );
}

function Admin() {
  const [data, setData] = useState<DashboardOut | null>(null);
  const [jobs, setJobs] = useState<JobDetail[]>([]);
  const [ops, setOps] = useState<Record<string, number> | null>(null);

  const load = useCallback(async () => {
    const [dashboard, list, summary] = await Promise.all([
      api.dashboard(),
      api.jobs({ limit: "12" }),
      api.opsSummary().catch(() => null),
    ]);
    setData(dashboard);
    setJobs(list);
    setOps(summary);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    const timer = setInterval(() => void load(), 4000);
    return () => clearInterval(timer);
  }, [load]);

  const live = jobs.filter((job) =>
    ["queued", "running", "paused"].includes(job.status),
  );
  const failed = jobs.filter((job) => job.status === "failed");
  const maxPages = Math.max(1, ...(data?.usage ?? []).map((day) => day.pages));

  return (
    <AppShell
      breadcrumb="لوحة المشرف"
      action={
        <span className="mono text-xs text-muted-soft">
          {ops
            ? `ENGINES ${ops.engines_up}/${ops.engines_total} · QUEUE ${ops.queued}`
            : ""}
        </span>
      }
    >
      <h1 className="text-2xl font-semibold">
        {failed.length > 0
          ? `${failed.length} مهمّة متعثّرة تحتاج تدخّلك`
          : "خطّ الإنتاج يعمل"}
      </h1>

      <div className="mt-6">
        {data ? (
          <Tiles>
            {data.stats.map((stat) => (
              <Stat key={stat.label} label={stat.label} value={stat.value} />
            ))}
          </Tiles>
        ) : (
          <Panel>
            <Spinner />
          </Panel>
        )}
      </div>

      <Panel className="mt-6">
        <PanelHeader
          title="طابور التوليد المباشر"
          meta={`LIVE · ${live.length} ACTIVE`}
          action={
            <Link href="/admin/ops" className="text-sm text-accent">
              فتح مراقب العمليات ←
            </Link>
          }
        />
        {jobs.length === 0 ? (
          <Empty title="لا توجد مهام بعد" />
        ) : (
          <Table
            columns={COLUMNS}
            head={[
              <Mono key="j">JOB</Mono>,
              "العميل والمشروع",
              "التقدّم",
              <Mono key="t">TIME</Mono>,
              "الحالة",
            ]}
          >
            {jobs.map((job) => (
              <Row
                key={job.id}
                columns={COLUMNS}
                tone={job.status === "failed" ? "bad" : undefined}
              >
                <Mono>J-{job.id.slice(0, 4).toUpperCase()}</Mono>
                <div className="min-w-0">
                  <div className="truncate font-medium">
                    {job.project_name ?? "—"}
                  </div>
                  <div className="truncate text-xs text-muted-soft">
                    {job.client_name ?? "—"}
                  </div>
                </div>
                <div>
                  <Progress value={job.progress} />
                  <div className="mono mt-1 text-[11px] text-muted-soft">
                    {job.completed_records}/{job.total_records}
                  </div>
                </div>
                <Mono>{duration(job.started_at, job.finished_at)}</Mono>
                <StatusPill status={job.status} />
              </Row>
            ))}
          </Table>
        )}
      </Panel>

      <div className="mt-6 grid gap-6 lg:grid-cols-[1fr_1.3fr]">
        <Panel>
          <PanelHeader title="يحتاج مراجعة" />
          {failed.length === 0 ? (
            <Empty title="لا شيء يحتاج تدخّلك" />
          ) : (
            failed.map((job) => (
              <div
                key={job.id}
                className="border-b border-line px-5 py-3.5 last:border-b-0"
              >
                <div className="text-sm text-bad">
                  {job.error_summary ?? "توقّفت المهمّة"}
                </div>
                <div className="mono mt-1 text-xs text-muted-soft">
                  J-{job.id.slice(0, 4).toUpperCase()} · {job.project_name}
                </div>
              </div>
            ))
          )}
        </Panel>

        <Panel>
          <PanelHeader title="استهلاك خطّ الإنتاج" meta="7 DAYS" />
          <div className="flex h-40 items-end gap-2 p-5">
            {(data?.usage ?? []).map((day) => (
              <div key={day.day} className="flex flex-1 flex-col items-center gap-2">
                <div
                  className="w-full bg-accent/80"
                  style={{ height: `${(day.pages / maxPages) * 100}%` }}
                  title={`${day.pages} صفحة`}
                />
                <span className="mono text-[10px] text-muted-soft">
                  {day.day.slice(5)}
                </span>
              </div>
            ))}
          </div>
        </Panel>
      </div>
    </AppShell>
  );
}
