"use client";

import { useCallback, useEffect, useState } from "react";

import { AppShell, RequireAuth } from "@/components/shell";
import { Banner, Empty, Mono, Panel, PanelHeader, Spinner } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import type { CategoryOut } from "@/types/api";

export default function CategoriesPage() {
  return (
    <RequireAuth staffOnly>
      <Categories />
    </RequireAuth>
  );
}

function Categories() {
  const [categories, setCategories] = useState<CategoryOut[] | null>(null);
  const [editing, setEditing] = useState<CategoryOut | null>(null);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setCategories(await api.categories());
    } catch {
      setCategories([]);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <AppShell
      breadcrumb="لوحة المشرف / التصنيفات"
      action={
        <button
          type="button"
          className="btn-primary"
          onClick={() => {
            setEditing(null);
            setCreating(true);
          }}
        >
          تصنيف جديد <span aria-hidden>←</span>
        </button>
      }
    >
      {error ? <Banner tone="error" title={error} /> : null}

      {creating || editing ? (
        <CategoryForm
          category={editing}
          onCancel={() => {
            setCreating(false);
            setEditing(null);
          }}
          onSaved={async () => {
            setCreating(false);
            setEditing(null);
            setError(null);
            await load();
          }}
          onError={setError}
        />
      ) : null}

      <div className="mt-5">
        {categories === null ? (
          <Panel>
            <Spinner />
          </Panel>
        ) : categories.length === 0 ? (
          <Panel>
            <Empty
              title="لا توجد تصنيفات"
              hint="التصنيف يجمع القوالب المتشابهة: كتيّبات، نماذج، لافتات…"
            />
          </Panel>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {categories.map((category) => (
              <Panel key={category.id} className="flex flex-col p-5">
                <div className="flex items-baseline justify-between gap-2">
                  <span className="text-lg font-semibold">{category.name}</span>
                  <Mono>
                    <span className="text-xs text-muted-soft">
                      {category.slug}
                    </span>
                  </Mono>
                </div>
                <p className="mt-2 flex-1 text-sm leading-relaxed text-muted">
                  {category.description || "بلا وصف"}
                </p>
                <div className="mt-4 flex items-center justify-between border-t border-line pt-3">
                  <span className="mono text-xs text-muted-soft">
                    {category.template_count} TEMPLATES
                  </span>
                  <div className="flex gap-3 text-xs">
                    <button
                      type="button"
                      className="text-accent hover:text-ink"
                      onClick={() => {
                        setCreating(false);
                        setEditing(category);
                      }}
                    >
                      تحرير
                    </button>
                    <button
                      type="button"
                      className="text-muted-soft hover:text-bad"
                      onClick={async () => {
                        setError(null);
                        try {
                          await api.deleteCategory(category.id);
                          await load();
                        } catch (caught) {
                          setError(
                            caught instanceof ApiError
                              ? caught.message
                              : "تعذّر الحذف.",
                          );
                        }
                      }}
                    >
                      حذف
                    </button>
                  </div>
                </div>
              </Panel>
            ))}
          </div>
        )}
      </div>
    </AppShell>
  );
}

function CategoryForm({
  category,
  onCancel,
  onSaved,
  onError,
}: {
  category: CategoryOut | null;
  onCancel: () => void;
  onSaved: () => void | Promise<void>;
  onError: (message: string) => void;
}) {
  const [name, setName] = useState(category?.name ?? "");
  const [slug, setSlug] = useState(category?.slug ?? "");
  const [description, setDescription] = useState(category?.description ?? "");
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      if (category) {
        await api.updateCategory(category.id, {
          name: name.trim(),
          description: description.trim() || null,
        });
      } else {
        await api.createCategory({
          name: name.trim(),
          slug: slug.trim().toLowerCase(),
          description: description.trim() || null,
        });
      }
      await onSaved();
    } catch (caught) {
      onError(caught instanceof ApiError ? caught.message : "تعذّر الحفظ.");
      setBusy(false);
    }
  }

  return (
    <Panel>
      <PanelHeader title={category ? `تحرير: ${category.name}` : "تصنيف جديد"} />
      <form onSubmit={submit} className="grid gap-4 p-5 sm:grid-cols-2">
        <div>
          <label className="field-label" htmlFor="catname">
            الاسم *
          </label>
          <input
            id="catname"
            required
            placeholder="مثال: أكياس وتغليف"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </div>
        <div>
          <label className="field-label" htmlFor="catslug">
            المعرّف *
          </label>
          <input
            id="catslug"
            dir="ltr"
            required
            className="mono"
            placeholder="bags"
            value={slug}
            disabled={Boolean(category)}
            onChange={(e) => setSlug(e.target.value)}
          />
          {category ? (
            <p className="mt-1 text-xs text-muted-soft">
              المعرّف هوية ثابتة — لا يتغيّر بعد الإنشاء.
            </p>
          ) : null}
        </div>
        <div className="sm:col-span-2">
          <label className="field-label" htmlFor="catdesc">
            الوصف
          </label>
          <textarea
            id="catdesc"
            rows={2}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </div>
        <div className="flex gap-2 sm:col-span-2">
          <button type="submit" className="btn-primary" disabled={busy}>
            {busy ? "جارٍ الحفظ…" : "حفظ"}
          </button>
          <button type="button" className="btn-ghost" onClick={onCancel}>
            إلغاء
          </button>
        </div>
      </form>
    </Panel>
  );
}
