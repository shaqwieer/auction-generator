"use client";

import { useEffect, useState } from "react";

import { AppShell, RequireAuth, useAuth } from "@/components/shell";
import { Mono, Panel, PanelHeader } from "@/components/ui";
import { api } from "@/lib/api";

/** Mirrors the backend Settings object; read-only until an admin write endpoint exists. */
const PRODUCTION: [string, string][] = [
  ["حدّ التوليد المتزامن لكل عميل", "2"],
  ["أقصى عدد صفوف في الملف", "5,000"],
  ["الحدّ الأدنى لدقّة الصور", "300 dpi"],
  ["مدّة حفظ المخرجات", "180 days"],
];

const PERMISSIONS: [string, boolean, boolean, boolean][] = [
  ["رفع القوالب وتحريرها", true, true, false],
  ["نشر القوالب وسحبها", true, false, false],
  ["إدارة العملاء والحسابات", true, false, false],
  ["إنشاء المشاريع والتوليد", true, true, true],
  ["رفع الأصول", true, true, true],
  ["مراقبة العمليات وإعادة التشغيل", true, true, false],
];

export default function SettingsPage() {
  return (
    <RequireAuth staffOnly>
      <Settings />
    </RequireAuth>
  );
}

function Settings() {
  const { user } = useAuth();
  const [ops, setOps] = useState<Record<string, number> | null>(null);

  useEffect(() => {
    void api
      .opsSummary()
      .then(setOps)
      .catch(() => setOps(null));
  }, []);

  return (
    <AppShell breadcrumb="لوحة المشرف / الإعدادات والصلاحيات">
      <div className="grid gap-6 lg:grid-cols-[1.4fr_1fr]">
        <Panel>
          <PanelHeader title="مصفوفة الصلاحيات" />
          <div className="grid grid-cols-[1fr_90px_90px_90px] gap-3 border-b border-line bg-paper px-5 py-2.5 text-xs text-muted">
            <span>الصلاحية</span>
            <span>مدير النظام</span>
            <span>مشغّل</span>
            <span>عميل</span>
          </div>
          {PERMISSIONS.map(([label, admin, operator, forClient]) => (
            <div
              key={label}
              className="grid grid-cols-[1fr_90px_90px_90px] items-center gap-3 border-b border-line px-5 py-3 text-sm last:border-b-0"
            >
              <span>{label}</span>
              {[admin, operator, forClient].map((allowed, index) => (
                <span
                  key={index}
                  className={allowed ? "text-ok" : "text-muted-soft"}
                >
                  {allowed ? "✓" : "—"}
                </span>
              ))}
            </div>
          ))}
        </Panel>

        <div className="space-y-6">
          <Panel>
            <PanelHeader title="إعدادات الإنتاج" />
            <dl className="divide-y divide-line">
              {PRODUCTION.map(([label, value]) => (
                <div
                  key={label}
                  className="flex items-center justify-between gap-3 px-5 py-3 text-sm"
                >
                  <dt className="text-muted">{label}</dt>
                  <dd className="mono font-medium">{value}</dd>
                </div>
              ))}
              {ops ? (
                <div className="flex items-center justify-between gap-3 px-5 py-3 text-sm">
                  <dt className="text-muted">محرّكات التوليد</dt>
                  <dd className="mono font-medium">
                    {ops.engines_up}/{ops.engines_total}
                  </dd>
                </div>
              ) : null}
            </dl>
          </Panel>

          <Panel>
            <PanelHeader title="حسابك" />
            <dl className="divide-y divide-line text-sm">
              {[
                ["الاسم", user?.name ?? "—"],
                ["البريد", user?.email ?? "—"],
                ["الدور", user?.role ?? "—"],
              ].map(([label, value]) => (
                <div
                  key={label}
                  className="flex items-center justify-between gap-3 px-5 py-3"
                >
                  <dt className="text-muted">{label}</dt>
                  <dd className="font-medium">
                    <Mono>{value}</Mono>
                  </dd>
                </div>
              ))}
            </dl>
          </Panel>
        </div>
      </div>
    </AppShell>
  );
}
