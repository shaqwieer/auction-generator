"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

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
  shortDate,
} from "@/components/ui";
import { api } from "@/lib/api";
import type { CategoryOut, ProjectOut, ProjectStatus } from "@/types/api";

const COLUMNS = "1.6fr 1fr 90px 130px 110px";

const STATUSES: { value: ProjectStatus | "all"; label: string }[] = [
  { value: "all", label: "الكل" },
  { value: "draft", label: "مسودة" },
  { value: "queued", label: "قيد التوليد" },
  { value: "ready", label: "جاهز" },
  { value: "failed", label: "به أخطاء" },
];

export default function ProjectsPage() {
  return (
    <RequireAuth>
      <Projects />
    </RequireAuth>
  );
}

function Projects() {
  const router = useRouter();
  const [projects, setProjects] = useState<ProjectOut[] | null>(null);
  const [categories, setCategories] = useState<CategoryOut[]>([]);
  const [status, setStatus] = useState<ProjectStatus | "all">("all");
  const [category, setCategory] = useState<string>("all");

  useEffect(() => {
    void api.categories().then(setCategories).catch(() => setCategories([]));
  }, []);

  useEffect(() => {
    const params: Record<string, string> = {};
    if (status !== "all") params.status = status;
    if (category !== "all") params.category_id = category;
    setProjects(null);
    void api
      .projects(params)
      .then(setProjects)
      .catch(() => setProjects([]));
  }, [status, category]);

  const summary = useMemo(
    () => (projects ? `${projects.length} OF ${projects.length} PROJECTS` : ""),
    [projects],
  );

  return (
    <AppShell
      breadcrumb="لوحة العميل / مشاريعي"
      action={
        <Link href="/projects/new" className="btn-primary">
          مشروع جديد <span aria-hidden>←</span>
        </Link>
      }
    >
      <div className="flex flex-wrap items-center gap-x-6 gap-y-3 pb-5">
        <Filter
          label="التصنيف"
          value={category}
          onChange={setCategory}
          options={[
            { value: "all", label: "الكل" },
            ...categories.map((item) => ({ value: item.id, label: item.name })),
          ]}
        />
        <Filter
          label="الحالة"
          value={status}
          onChange={(value) => setStatus(value as ProjectStatus | "all")}
          options={STATUSES}
        />
      </div>

      <Panel>
        <PanelHeader title="المشاريع" meta={summary} />
        {projects === null ? (
          <Spinner />
        ) : projects.length === 0 ? (
          <Empty
            title="لا توجد مشاريع مطابقة"
            hint="جرّب تغيير عوامل التصفية، أو ابدأ مشروعًا جديدًا."
          />
        ) : (
          <Table
            columns={COLUMNS}
            head={[
              "المشروع",
              "القالب",
              <Mono key="r">ROWS</Mono>,
              "آخر تحديث",
              "الحالة",
            ]}
          >
            {projects.map((project) => (
              <Row
                key={project.id}
                columns={COLUMNS}
                onClick={() => router.push(hrefFor(project))}
              >
                <div className="min-w-0">
                  <div className="truncate font-medium">{project.name}</div>
                  <div className="mono truncate text-xs text-muted-soft">
                    {project.category_name ?? "—"}
                  </div>
                </div>
                <span className="truncate text-muted">
                  {project.template_name ?? "—"}
                </span>
                <Mono>{project.record_count}</Mono>
                <span className="text-muted">{shortDate(project.updated_at)}</span>
                <StatusPill status={project.status} />
              </Row>
            ))}
          </Table>
        )}
      </Panel>
    </AppShell>
  );
}

function Filter<T extends string>({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: T;
  onChange: (value: T) => void;
  options: { value: string; label: string }[];
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-sm text-muted-soft">{label}:</span>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          onClick={() => onChange(option.value as T)}
          className={`rounded border px-2.5 py-1 text-sm transition-colors ${
            value === option.value
              ? "border-ink bg-ink text-white"
              : "border-line bg-surface text-muted hover:border-edge"
          }`}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

function hrefFor(project: ProjectOut): string {
  if (project.has_plan) return `/projects/${project.id}/build`;
  if (project.status === "draft") return `/projects/${project.id}/data`;
  if (project.status === "mapping") return `/projects/${project.id}/mapping`;
  return `/projects/${project.id}/status`;
}
