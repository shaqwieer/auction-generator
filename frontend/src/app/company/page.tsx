"use client";

/**
 * The company these booklets are printed for.
 *
 * The name and the mark on this screen are not decoration: they are what the
 * booklet carries. The designer's artwork used to have one selling agent's
 * logo baked into it on seventeen pages; that mark is out of the artwork now,
 * and this is what goes in its place — the company's own logo where they have
 * one, their name set in the same colour and position where they have not.
 *
 * So there is no preview of "the branding" separate from the booklet. The
 * booklet is the preview, and it updates the moment this does.
 */

import { useEffect, useRef, useState } from "react";

import { AppShell, RequireAuth, useAuth } from "@/components/shell";
import {
  AuthImage,
  Banner,
  Labelled,
  Mono,
  Panel,
  PanelHeader,
  Spinner,
} from "@/components/ui";
import { API_URL, ApiError, api } from "@/lib/api";
import type { CompanyOut } from "@/types/api";

export default function CompanyPage() {
  return (
    <RequireAuth>
      <Company />
    </RequireAuth>
  );
}

function Company() {
  const { refresh } = useAuth();
  const [company, setCompany] = useState<CompanyOut | null>(null);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const file = useRef<HTMLInputElement>(null);
  // Bumped after every logo change: the mark is served from one URL per
  // company, so nothing else would tell the browser it has changed.
  const [stamp, setStamp] = useState(0);

  useEffect(() => {
    void api
      .company()
      .then((loaded) => {
        setCompany(loaded);
        setName(loaded.name);
      })
      .catch((caught) =>
        setError(
          caught instanceof ApiError
            ? caught.message
            : "تعذّر تحميل بيانات الشركة.",
        ),
      );
  }, []);

  async function run(action: () => Promise<CompanyOut>) {
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      const next = await action();
      setCompany(next);
      setName(next.name);
      setStamp((was) => was + 1);
      setSaved(true);
      // The sidebar carries the company too, and it is read from the session.
      await refresh();
    } catch (caught) {
      setError(
        caught instanceof ApiError ? caught.message : "تعذّر حفظ التغييرات.",
      );
    } finally {
      setBusy(false);
    }
  }

  if (!company && !error) {
    return (
      <AppShell breadcrumb="بيانات الشركة">
        <Panel>
          <Spinner />
        </Panel>
      </AppShell>
    );
  }

  const trimmed = name.trim();

  return (
    <AppShell breadcrumb="بيانات الشركة">
      <h1 className="mt-6 text-2xl font-semibold">بيانات الشركة</h1>
      <p className="mt-2 max-w-2xl text-sm text-muted">
        اسم الشركة وشعارها هما ما يُطبع على كل صفحة من الكتيّب. إن رفعت شعارًا
        طُبع الشعار، وإن لم ترفع طُبع الاسم في مكانه ولونه.
      </p>

      {error ? (
        <div className="mt-5">
          <Banner tone="error" title="تعذّرت العملية">
            {error}
          </Banner>
        </div>
      ) : null}
      {saved && !error ? (
        <div className="mt-5">
          <Banner tone="info" title="حُفظت البيانات">
            ستظهر على المعاينات والكتيّبات فورًا، بما فيها المشاريع المفتوحة.
          </Banner>
        </div>
      ) : null}

      <div className="mt-6 grid max-w-4xl gap-6 lg:grid-cols-2">
        <Panel>
          <PanelHeader title="الاسم" meta={<Mono>{company?.code ?? ""}</Mono>} />
          <div className="p-5">
            <Labelled label="اسم الشركة *">
              <input
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="مثال: شركة أعيان العقارية"
              />
            </Labelled>
            <p className="mt-2 text-xs text-muted-soft">
              يُطبع على الكتيّب حيث لا يوجد شعار. لا يمكن تركه فارغًا.
            </p>
            <button
              type="button"
              className="btn-primary mt-4"
              disabled={busy || !trimmed || trimmed === company?.name}
              onClick={() => void run(() => api.updateCompany(trimmed))}
            >
              {busy ? "جارٍ الحفظ…" : "حفظ الاسم"}
            </button>
          </div>
        </Panel>

        <Panel>
          <PanelHeader title="الشعار" meta="اختياري" />
          <div className="p-5">
            <div className="grid h-32 place-items-center border border-dashed border-edge bg-paper">
              {company?.logo_filename ? (
                <AuthImage
                  key={stamp}
                  src={`${API_URL}/api/v1/company/logo?v=${stamp}`}
                  alt={company.name}
                  className="max-h-28 max-w-full object-contain"
                />
              ) : (
                <span className="px-4 text-center text-sm text-muted-soft">
                  لا يوجد شعار — يُطبع اسم الشركة في مكانه.
                </span>
              )}
            </div>
            <p className="mt-3 text-xs text-muted-soft">
              PNG بخلفية شفافة هو الأنسب: الشعار يُطبع على خلفيات فاتحة وداكنة.
            </p>
            <div className="mt-4 flex gap-2">
              <button
                type="button"
                className="btn btn-secondary"
                disabled={busy}
                onClick={() => file.current?.click()}
              >
                {company?.logo_filename ? "استبدال الشعار" : "رفع شعار"}
              </button>
              {company?.logo_filename ? (
                <button
                  type="button"
                  className="border border-line px-3 py-1.5 text-sm text-bad transition-colors hover:border-bad"
                  disabled={busy}
                  onClick={() => void run(() => api.removeCompanyLogo())}
                >
                  إزالة
                </button>
              ) : null}
            </div>
            <input
              ref={file}
              type="file"
              accept="image/png,image/jpeg,image/webp"
              className="hidden"
              onChange={(event) => {
                const picked = event.target.files?.[0];
                event.target.value = "";
                if (picked) void run(() => api.uploadCompanyLogo(picked));
              }}
            />
          </div>
        </Panel>
      </div>
    </AppShell>
  );
}
