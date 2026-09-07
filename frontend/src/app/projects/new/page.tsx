"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { AppShell, RequireAuth, useAuth } from "@/components/shell";
import { Empty, Mono, Panel, Spinner, Steps } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { WIZARD_STEPS } from "@/lib/wizard";
import type { CategoryOut, ClientOut, TemplateOut } from "@/types/api";

export default function NewProjectPage() {
  return (
    <RequireAuth>
      <NewProject />
    </RequireAuth>
  );
}

function NewProject() {
  const router = useRouter();
  const { user } = useAuth();
  const isStaff = user?.role === "admin" || user?.role === "operator";

  const [categories, setCategories] = useState<CategoryOut[]>([]);
  const [templates, setTemplates] = useState<TemplateOut[] | null>(null);
  const [clients, setClients] = useState<ClientOut[]>([]);
  const [clientId, setClientId] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void Promise.all([api.categories(), api.templates()])
      .then(([cats, temps]) => {
        setCategories(cats);
        setTemplates(temps);
      })
      .catch(() => setTemplates([]));
  }, []);

  // Staff create projects on a client's behalf, so they have to say which one.
  // A client user's own organisation is implied and the field is not shown.
  useEffect(() => {
    if (!isStaff) return;
    void api
      .clients()
      .then((list) => {
        setClients(list);
        if (list.length === 1 && list[0]) setClientId(list[0].id);
      })
      .catch(() => setClients([]));
  }, [isStaff]);

  async function create() {
    if (!selected) return;
    setBusy(true);
    setError(null);
    try {
      const project = await api.createProject({
        name: name.trim() || "مشروع بلا اسم",
        template_id: selected,
        ...(isStaff && clientId ? { client_id: clientId } : {}),
      });
      // A template that knows its pages goes to the builder; an older one keeps
      // the spreadsheet screens.
      router.push(
        project.has_plan
          ? `/projects/${project.id}/build`
          : `/projects/${project.id}/data`,
      );
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "تعذّر إنشاء المشروع.");
      setBusy(false);
    }
  }

  const byCategory = categories
    .map((category) => ({
      category,
      items: (templates ?? []).filter((t) => t.category_id === category.id),
    }))
    .filter((group) => group.items.length > 0);

  const orphans = (templates ?? []).filter((t) => !t.category_id);
  if (orphans.length > 0) {
    byCategory.push({
      category: {
        id: "none",
        name: "بلا تصنيف",
        slug: "none",
        description: null,
        template_count: orphans.length,
      },
      items: orphans,
    });
  }

  return (
    <AppShell
      breadcrumb="مشروع جديد · الخطوة 1 من 3"
      action={
        <button
          type="button"
          className="btn-primary"
          disabled={!selected || busy || (isStaff && !clientId)}
          onClick={() => void create()}
        >
          {busy ? "جارٍ الإنشاء…" : "التالي: بناء الكتيّب"}
          <span aria-hidden>←</span>
        </button>
      }
    >
      <Steps steps={WIZARD_STEPS} current={0} />

      <h1 className="mt-6 text-2xl font-semibold">اختر القالب</h1>

      <div className="mt-5 grid max-w-3xl gap-4 sm:grid-cols-2">
        <div>
          <label className="field-label" htmlFor="name">
            اسم المشروع
          </label>
          <input
            id="name"
            value={name}
            placeholder="مثال: مزاد أعيان حائل — يوليو 2026"
            onChange={(event) => setName(event.target.value)}
          />
        </div>

        {isStaff ? (
          <div>
            <label className="field-label" htmlFor="client">
              العميل *
            </label>
            <select
              id="client"
              value={clientId}
              onChange={(event) => setClientId(event.target.value)}
              className={clientId ? undefined : "border-edge"}
            >
              <option value="">— اختر العميل —</option>
              {clients.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name} ({item.code})
                </option>
              ))}
            </select>
            <p className="mt-1.5 text-xs text-muted-soft">
              أنت تنشئ المشروع نيابة عن عميل — اختر صاحبه.
            </p>
          </div>
        ) : null}
      </div>

      {error ? <p className="mt-4 text-sm text-bad">{error}</p> : null}

      {templates === null ? (
        <Panel className="mt-6">
          <Spinner />
        </Panel>
      ) : byCategory.length === 0 ? (
        <Panel className="mt-6">
          <Empty
            title="لا توجد قوالب متاحة"
            hint="تواصل مع فريق مطبعة لإتاحة قالب لحسابك."
          />
        </Panel>
      ) : (
        byCategory.map((group) => (
          <section key={group.category.id} className="mt-8">
            <div className="mb-3 flex items-baseline gap-3">
              <h2 className="text-lg font-semibold">{group.category.name}</h2>
              <Mono>
                <span className="text-xs text-muted-soft">
                  {group.items.length}
                </span>
              </Mono>
            </div>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {group.items.map((template) => (
                <button
                  key={template.id}
                  type="button"
                  onClick={() => setSelected(template.id)}
                  className={`panel p-0 text-right transition-colors ${
                    selected === template.id
                      ? "border-accent ring-1 ring-accent"
                      : "hover:border-edge"
                  }`}
                >
                  {/* A page-proportioned placeholder keeps the print metaphor. */}
                  <div className="relative flex aspect-[210/297] max-h-44 items-center justify-center border-b border-line bg-paper">
                    <span className="absolute right-2 top-2 h-3 w-px bg-edge" />
                    <span className="absolute right-2 top-2 h-px w-3 bg-edge" />
                    <span className="absolute bottom-2 left-2 h-3 w-px bg-edge" />
                    <span className="absolute bottom-2 left-2 h-px w-3 bg-edge" />
                    <span className="mono text-xs text-muted-soft">
                      {Math.round(template.page_width)}×
                      {Math.round(template.page_height)}pt
                    </span>
                    {selected === template.id ? (
                      <span className="absolute left-2 top-2 flex h-5 w-5 items-center justify-center rounded-full bg-accent text-xs text-white">
                        ✓
                      </span>
                    ) : null}
                  </div>
                  <div className="p-4">
                    <div className="font-medium">{template.name}</div>
                    <div className="mono mt-1 text-xs text-muted-soft">
                      {template.code} · {template.page_count} pp ·{" "}
                      {template.field_count} fields
                    </div>
                  </div>
                </button>
              ))}
            </div>
          </section>
        ))
      )}
    </AppShell>
  );
}
