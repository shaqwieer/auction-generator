"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { AppShell, RequireAuth, useAuth } from "@/components/shell";
import {
  Banner,
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
  bytes,
  duration,
} from "@/components/ui";
import { api, tryDownload } from "@/lib/api";
import type { DashboardOut, ProjectOut } from "@/types/api";

const JOB_COLUMNS = "1fr 120px 90px 110px";

export default function HomePage() {
  return (
    <RequireAuth>
      <Home />
    </RequireAuth>
  );
}

function Home() {
  const { user } = useAuth();
  const [data, setData] = useState<DashboardOut | null>(null);
  const [projects, setProjects] = useState<ProjectOut[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [downloadError, setDownloadError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [dashboard, list] = await Promise.all([
        api.dashboard(),
        api.projects({ limit: "5" }),
      ]);
      setData(dashboard);
      setProjects(list);
    } catch {
      setError("تعذّر تحميل اللوحة.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // Poll only while something is actually running.
  useEffect(() => {
    if (!data?.running_jobs.length) return;
    const timer = setInterval(() => void load(), 3000);
    return () => clearInterval(timer);
  }, [data?.running_jobs.length, load]);

  const ready = data?.recent_jobs.filter((job) => job.status === "succeeded") ?? [];

  return (
    <AppShell
      breadcrumb="لوحة العميل"
      action={
        <Link href="/projects/new" className="btn-primary">
          مشروع جديد <span aria-hidden>←</span>
        </Link>
      }
    >
      <h1 className="text-2xl font-semibold">
        {greeting()} {user?.name?.split(" ")[0] ?? ""} —{" "}
        {ready.length > 0
          ? `لديك ${ready.length} ${ready.length === 1 ? "ملف جاهز" : "ملفات جاهزة"} للتنزيل`
          : "لا توجد ملفات جاهزة بعد"}
      </h1>

      {error ? <p className="mt-4 text-sm text-bad">{error}</p> : null}
      {downloadError ? (
        <div className="mt-4">
          <Banner tone="error" title={downloadError}>
            الملف لم يعد متاحًا — أعِد التوليد للحصول على نسخة جديدة.
          </Banner>
        </div>
      ) : null}

      <div className="mt-6">
        {data ? (
          <Tiles>
            {data.stats.map((stat) => (
              <Stat
                key={stat.label}
                label={stat.label}
                value={stat.value}
                delta={stat.delta}
              />
            ))}
          </Tiles>
        ) : (
          <Panel>
            <Spinner />
          </Panel>
        )}
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-[1.4fr_1fr]">
        <Panel>
          <PanelHeader
            title="مشاريع قيد العمل"
            action={
              <Link href="/projects" className="text-sm text-accent">
                كل المشاريع ←
              </Link>
            }
          />
          {projects.length === 0 ? (
            <Empty
              title="لا توجد مشاريع بعد"
              hint="ابدأ بمشروع جديد لاختيار قالب ورفع بياناتك."
            />
          ) : (
            projects.map((project) => (
              <Link key={project.id} href={hrefFor(project)}>
                <div className="flex items-center justify-between gap-4 border-b border-line px-5 py-3.5 last:border-b-0 hover:bg-paper">
                  <div className="min-w-0">
                    <div className="truncate text-md font-medium">
                      {project.name}
                    </div>
                    <div className="mono mt-1 text-xs text-muted-soft">
                      {project.record_count} ROWS · {project.template_name ?? "—"}
                    </div>
                  </div>
                  <StatusPill status={project.status} />
                </div>
              </Link>
            ))
          )}
        </Panel>

        <Panel>
          <PanelHeader title="ملفّك جاهز للتنزيل" />
          {ready.length === 0 ? (
            <Empty title="لا توجد مخرجات بعد" />
          ) : (
            ready.slice(0, 4).map((job) => (
              <div
                key={job.id}
                className="flex items-center justify-between gap-3 border-b border-line px-5 py-3.5 last:border-b-0"
              >
                <div className="min-w-0">
                  <div className="mono truncate text-sm">
                    {job.output_filename}
                  </div>
                  <div className="mono mt-1 text-xs text-muted-soft">
                    {job.page_count} pp · {bytes(job.output_bytes)}
                  </div>
                </div>
                <button
                  type="button"
                  className="btn-secondary shrink-0"
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
              </div>
            ))
          )}
        </Panel>
      </div>

      <Panel className="mt-6">
        <PanelHeader
          title="آخر عمليات التوليد"
          meta={data ? `${data.recent_jobs.length} JOBS` : undefined}
        />
        {!data ? (
          <Spinner />
        ) : data.recent_jobs.length === 0 ? (
          <Empty title="لم تُنفّذ أي عملية توليد بعد" />
        ) : (
          <Table
            columns={JOB_COLUMNS}
            head={["الملف", <Mono key="p">PAGES</Mono>, <Mono key="t">TIME</Mono>, "الحالة"]}
          >
            {data.recent_jobs.map((job) => (
              <Row key={job.id} columns={JOB_COLUMNS}>
                <span className="mono truncate">
                  {job.output_filename ?? "—"}
                </span>
                <Mono>{job.page_count}</Mono>
                <Mono>{duration(job.started_at, job.finished_at)}</Mono>
                <div>
                  {job.status === "running" || job.status === "queued" ? (
                    <div className="w-24">
                      <Progress value={job.progress} />
                    </div>
                  ) : (
                    <StatusPill status={job.status} />
                  )}
                </div>
              </Row>
            ))}
          </Table>
        )}
      </Panel>
    </AppShell>
  );
}

function greeting(): string {
  const hour = new Date().getHours();
  if (hour < 12) return "صباح الخير";
  return "مساء الخير";
}

function hrefFor(project: ProjectOut): string {
  if (project.has_plan) return `/projects/${project.id}/build`;
  if (project.status === "draft") return `/projects/${project.id}/data`;
  if (project.status === "mapping") return `/projects/${project.id}/mapping`;
  return `/projects/${project.id}/status`;
}
