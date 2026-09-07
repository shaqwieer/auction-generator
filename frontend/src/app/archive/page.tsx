"use client";

import { useEffect, useState } from "react";

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
  bytes,
  shortDate,
} from "@/components/ui";
import { api, tryDownload } from "@/lib/api";
import type { JobDetail } from "@/types/api";

const COLUMNS = "1.6fr 1.2fr 80px 100px 120px 110px";

export default function ArchivePage() {
  return (
    <RequireAuth>
      <Archive />
    </RequireAuth>
  );
}

function Archive() {
  const [jobs, setJobs] = useState<JobDetail[] | null>(null);
  const [downloadError, setDownloadError] = useState<string | null>(null);

  useEffect(() => {
    void api
      .jobs({ limit: "100" })
      .then((all) => setJobs(all.filter((job) => job.output_filename)))
      .catch(() => setJobs([]));
  }, []);

  const totalBytes = (jobs ?? []).reduce((sum, job) => sum + job.output_bytes, 0);

  return (
    <AppShell breadcrumb="لوحة العميل / أرشيف المخرجات">
      {downloadError ? (
        <div className="mb-5">
          <Banner tone="error" title={downloadError}>
            الملف لم يعد متاحًا على هذا الخادم — أعِد التوليد للحصول على نسخة جديدة.
          </Banner>
        </div>
      ) : null}
      <Panel>
        <PanelHeader
          title="المخرجات"
          meta={
            jobs ? `${jobs.length} FILES · ${bytes(totalBytes)}` : undefined
          }
        />
        {jobs === null ? (
          <Spinner />
        ) : jobs.length === 0 ? (
          <Empty
            title="لا توجد مخرجات محفوظة"
            hint="ستظهر هنا كل الملفات التي وُلّدت بنجاح."
          />
        ) : (
          <Table
            columns={COLUMNS}
            head={[
              "اسم الملف",
              "المشروع",
              <Mono key="p">PAGES</Mono>,
              <Mono key="s">SIZE</Mono>,
              "التاريخ",
              "الإجراءات",
            ]}
          >
            {jobs.map((job) => (
              <Row key={job.id} columns={COLUMNS}>
                <span className="mono truncate">{job.output_filename}</span>
                <span className="truncate text-muted">
                  {job.project_name ?? "—"}
                </span>
                <Mono>{job.page_count}</Mono>
                <Mono>{bytes(job.output_bytes)}</Mono>
                <span className="text-muted">{shortDate(job.created_at)}</span>
                <div className="flex items-center gap-3">
                  {job.status === "succeeded" ? (
                    <button
                      type="button"
                      className="text-sm text-accent hover:text-ink"
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
