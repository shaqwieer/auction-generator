/**
 * The template editor: draw field regions over the designer's own artwork.
 *
 * The page raster comes from the server, and every box is stored in normalised
 * coordinates, so dragging works at whatever size the canvas happens to be and
 * a re-export at another trim size keeps the mapping.
 */
"use client";

import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { AppShell, RequireAuth, useAuth } from "@/components/shell";
import { PageCanvas, PageRail } from "@/components/pagecanvas";
import {
  Banner,
  Labelled,
  Mono,
  Panel,
  PanelHeader,
  Spinner,
} from "@/components/ui";
import { API_URL, ApiError, api } from "@/lib/api";
import type {
  SuggestionOut,
  TemplateDetail,
  TemplateFieldUpdate,
  TemplateSectionUpdate,
} from "@/types/api";

const TYPE_COLORS: Record<string, string> = {
  text: "#D6006F",
  image: "#1F7A6B",
  qr: "#0E2A3A",
  barcode: "#0E2A3A",
  link: "#45606E",
  table: "#C2410C",
};

const SECTION_KINDS: { value: TemplateSectionUpdate["kind"]; label: string }[] = [
  { value: "fixed", label: "ثابت" },
  { value: "per_record", label: "يتكرّر لكل سجلّ" },
  { value: "table", label: "جدول" },
];

/** Marks a draft the editor made itself, which has no stored row behind it. */
const NEW_FIELD_PREFIX = "new-";

const FIELD_TYPES = ["text", "image", "qr", "barcode", "link", "table"] as const;
const ALIGNS = ["right", "center", "left"] as const;
const FITS = ["shrink", "clip", "wrap"] as const;

type Draft = TemplateFieldUpdate & { uid: string };

function toDraft(field: TemplateDetail["fields"][number]): Draft {
  return {
    uid: field.id,
    key: field.key,
    label: field.label,
    page_index: field.page_index,
    type: field.type,
    x: field.x,
    y: field.y,
    w: field.w,
    h: field.h,
    align: field.align,
    valign: field.valign,
    rotation: field.rotation,
    font_family: field.font_family,
    font_weight: field.font_weight,
    font_size_pt: field.font_size_pt,
    color: field.color,
    line_height: field.line_height,
    fit: field.fit,
    min_scale: field.min_scale,
    calibration_dx: field.calibration_dx,
    calibration_dy: field.calibration_dy,
    is_required: field.is_required,
    rtl: field.rtl,
    // Carried through, not defaulted: saving is a full replace, so a column the
    // editor reads but does not write back is a column it quietly empties. The
    // steps page's captions are almost entirely prefix — dropping them here
    // would leave the booklet five numbered icons and no instructions.
    prefix: field.prefix,
    suffix: field.suffix,
    default_value: field.default_value,
    table_spec: field.table_spec,
  };
}

export default function TemplateEditorPage() {
  return (
    <RequireAuth staffOnly>
      <TemplateEditor />
    </RequireAuth>
  );
}

function TemplateEditor() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const canvasRef = useRef<HTMLDivElement>(null);
  // An operator prepares a template and an admin signs it off, so the publish
  // action is not theirs. The API refuses it either way; showing the button
  // would only trade a working screen for a 403.
  const { user } = useAuth();
  const mayPublish = user?.role === "admin";

  const [template, setTemplate] = useState<TemplateDetail | null>(null);
  const [fields, setFields] = useState<Draft[]>([]);
  const [sections, setSections] = useState<TemplateSectionUpdate[]>([]);
  const [suggestions, setSuggestions] = useState<SuggestionOut[]>([]);
  const [page, setPage] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const detail = await api.template(id);
      setTemplate(detail);
      setFields(detail.fields.map(toDraft));
      setSections(
        detail.sections.map((s) => ({
          name: s.name,
          kind: s.kind,
          first_page: s.first_page,
          last_page: s.last_page,
          pages_per_item: s.pages_per_item,
          rows_per_page: s.rows_per_page,
          variant: s.variant,
        })),
      );
      setDirty(false);
    } catch {
      setError("تعذّر تحميل القالب.");
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!showSuggestions || suggestions.length > 0) return;
    void api
      .templateSuggestions(id)
      .then(setSuggestions)
      .catch(() => setSuggestions([]));
  }, [showSuggestions, suggestions.length, id]);

  const onPage = useMemo(
    () => fields.filter((f) => f.page_index === page),
    [fields, page],
  );
  const active = onPage.find((f) => f.uid === selected) ?? null;
  const pageSuggestions = suggestions.filter((s) => s.page_index === page);

  const sectionFor = (index: number) =>
    sections.find((s) => index >= s.first_page && index <= s.last_page);

  function update(uid: string, patch: Partial<Draft>) {
    setFields((current) =>
      current.map((f) => (f.uid === uid ? { ...f, ...patch } : f)),
    );
    setDirty(true);
  }

  function addField(seed?: Partial<Draft>) {
    const uid = `${NEW_FIELD_PREFIX}${Date.now()}-${Math.random()
      .toString(36)
      .slice(2, 7)}`;
    const draft: Draft = {
      uid,
      key: `field_${fields.length + 1}`,
      label: "",
      page_index: page,
      type: "text",
      x: 0.35,
      y: 0.45,
      w: 0.3,
      h: 0.03,
      align: "right",
      valign: null,
      rotation: 0,
      font_family: "RuaqArabic",
      font_weight: "Medium",
      font_size_pt: 10,
      color: "#0D3759",
      line_height: 1,
      fit: "shrink",
      min_scale: 0.5,
      calibration_dx: 0,
      calibration_dy: 0,
      is_required: false,
      rtl: true,
      prefix: "",
      suffix: "",
      default_value: "",
      table_spec: null,
      ...seed,
    };
    setFields((current) => [...current, draft]);
    setSelected(uid);
    setDirty(true);
  }

  function removeField(uid: string) {
    setFields((current) => current.filter((f) => f.uid !== uid));
    if (selected === uid) setSelected(null);
    setDirty(true);
  }

  /** Drag or resize a box, in normalised units so the canvas size is irrelevant. */
  function beginDrag(
    event: React.PointerEvent,
    uid: string,
    mode: "move" | "resize",
  ) {
    event.preventDefault();
    event.stopPropagation();
    const box = canvasRef.current?.getBoundingClientRect();
    const field = fields.find((f) => f.uid === uid);
    if (!box || !field) return;

    setSelected(uid);
    const startX = event.clientX;
    const startY = event.clientY;
    const origin = { x: field.x, y: field.y, w: field.w, h: field.h };

    function onMove(move: PointerEvent) {
      const dx = (move.clientX - startX) / box!.width;
      const dy = (move.clientY - startY) / box!.height;
      if (mode === "move") {
        update(uid, {
          x: clamp(origin.x + dx, 0, 1 - origin.w),
          y: clamp(origin.y + dy, 0, 1 - origin.h),
        });
      } else {
        // The stored x always means "distance from the left edge", and the box
        // is placed with a physical `left`, so the handle on the visual left
        // moves x and w together.
        update(uid, {
          x: clamp(origin.x + dx, 0, origin.x + origin.w - 0.01),
          w: clamp(origin.w - dx, 0.005, 1),
          h: clamp(origin.h + dy, 0.004, 1 - origin.y),
        });
      }
    }
    function onUp() {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    }
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  }

  async function save() {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      await api.saveSections(id, sections);
      const detail = await api.saveFields(
        id,
        // The uid is the stored row's id for a field that already exists, and a
        // local placeholder for one just drawn. Sent as `id`, it is what lets a
        // renamed key keep its row — and with it the columns this screen has no
        // control for, the photo-frame masks among them. A drawn field sends no
        // id and the server makes a new row.
        fields.map(({ uid, ...rest }) => ({
          ...rest,
          ...(uid.startsWith(NEW_FIELD_PREFIX) ? {} : { id: uid }),
        })),
      );
      setTemplate(detail);
      setFields(detail.fields.map(toDraft));
      setDirty(false);
      setSuggestions([]);
      setMessage("حُفظت الحقول والأقسام.");
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "تعذّر الحفظ.");
    } finally {
      setBusy(false);
    }
  }

  async function unpublish() {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      await api.unpublishTemplate(id);
      setMessage(
        "سُحب القالب من الكتالوج. الخلفية المنشورة باقية، والمشاريع القائمة " +
          "تُولَّد كما هي.",
      );
      await load();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "تعذّر سحب القالب.");
    } finally {
      setBusy(false);
    }
  }

  async function publish() {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      if (dirty) await save();
      const published = await api.publishTemplate(id);
      setMessage(
        `نُشر القالب — v${published.version}. حُفظت الخلفية بعد إزالة القيم النموذجية.`,
      );
      await load();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "تعذّر النشر.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AppShell
      breadcrumb={`القوالب / ${template?.name ?? ""}`}
      action={
        <div className="flex items-center gap-2">
          <span className="mono text-xs text-muted-soft">
            {template ? `${template.code} · v${template.version}` : ""}
          </span>
          <button
            type="button"
            className="btn-secondary"
            disabled={busy || !dirty}
            onClick={() => void save()}
          >
            {busy ? "…" : dirty ? "حفظ التغييرات" : "محفوظ"}
          </button>
          {mayPublish && template?.status === "published" ? (
            <button
              type="button"
              className="btn-secondary"
              disabled={busy}
              onClick={() => void unpublish()}
            >
              إلغاء النشر
            </button>
          ) : null}
          {mayPublish ? (
            <button
              type="button"
              className="btn-primary"
              disabled={busy || !template}
              onClick={() => void publish()}
            >
              {template?.status === "published" ? "إعادة النشر" : "نشر القالب"}{" "}
              <span aria-hidden>←</span>
            </button>
          ) : null}
        </div>
      }
    >
      {message ? <Banner tone="info" title={message} /> : null}
      {error ? <Banner tone="error" title={error} /> : null}
      {template?.status === "draft" ? (
        <Banner tone="warn" title="مسودة غير منشورة">
          الخلفية لم تُنظَّف بعد — النشر يزيل القيم النموذجية من التصميم مع
          الإبقاء على التسميات المطبوعة.
          {mayPublish ? null : " النشر متاح لمدير النظام فقط."}
        </Banner>
      ) : null}

      {template === null ? (
        <Panel className="mt-4">
          <Spinner />
        </Panel>
      ) : (
        <div className="mt-4 grid gap-6 xl:grid-cols-[1fr_340px]">
          <div className="space-y-4">
            <Panel className="p-3">
              <PageRail
                items={Array.from({ length: template.page_count }, (_, index) => {
                  const kind = sectionFor(index)?.kind;
                  return {
                    key: String(index),
                    label: String(index + 1).padStart(2, "0"),
                    meta: `${fields.filter((f) => f.page_index === index).length} F`,
                    tone:
                      kind === "per_record"
                        ? ("accent" as const)
                        : kind === "table"
                          ? ("bad" as const)
                          : undefined,
                  };
                })}
                active={String(page)}
                onSelect={(key) => {
                  setPage(Number(key));
                  setSelected(null);
                }}
              />
            </Panel>

            <Panel className="p-5">
              <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
                <span className="text-sm text-muted">
                  {sectionFor(page)?.name ?? "خارج الأقسام"}
                </span>
                <div className="flex items-center gap-3">
                  <label className="flex items-center gap-1.5 text-xs text-muted">
                    <input
                      type="checkbox"
                      className="h-3.5 w-3.5"
                      checked={showSuggestions}
                      onChange={(e) => setShowSuggestions(e.target.checked)}
                    />
                    اقتراحات ({pageSuggestions.length})
                  </label>
                  <button
                    type="button"
                    className="text-xs text-accent"
                    onClick={() => addField()}
                  >
                    + حقل جديد
                  </button>
                  <span className="mono text-xs text-muted-soft">
                    {Math.round(template.page_width)}×
                    {Math.round(template.page_height)}pt
                  </span>
                </div>
              </div>

              <div ref={canvasRef} className="mx-auto w-full max-w-lg">
                <PageCanvas
                  src={`${API_URL}/api/v1/templates/${id}/pages/${page}.png?dpi=110`}
                  alt={`صفحة ${page + 1}`}
                  width={template.page_width}
                  height={template.page_height}
                  onBackgroundPointerDown={() => setSelected(null)}
                >

                {showSuggestions
                  ? pageSuggestions.map((s, index) => (
                      <button
                        key={`s-${index}`}
                        type="button"
                        title={`${s.sample_text} — انقر للإضافة`}
                        onPointerDown={(e) => e.stopPropagation()}
                        onClick={() =>
                          addField({
                            x: s.x, y: s.y, w: s.w, h: s.h,
                            type: s.type, align: s.align, rotation: s.rotation,
                            font_family: s.font_family, font_weight: s.font_weight,
                            font_size_pt: s.font_size_pt, color: s.color,
                          })
                        }
                        className="absolute border border-dashed border-muted-soft/70 bg-white/30 hover:border-accent hover:bg-[#FCE8F2]/60"
                        style={{
                          left: `${s.x * 100}%`,
                          top: `${s.y * 100}%`,
                          width: `${s.w * 100}%`,
                          height: `${Math.max(s.h, 0.006) * 100}%`,
                        }}
                      />
                    ))
                  : null}

                {onPage.map((field) => {
                  const isActive = selected === field.uid;
                  const colour = TYPE_COLORS[field.type] ?? "#D6006F";
                  return (
                    <div
                      key={field.uid}
                      onPointerDown={(e) => beginDrag(e, field.uid, "move")}
                      className="absolute cursor-move"
                      style={{
                        left: `${field.x * 100}%`,
                        top: `${field.y * 100}%`,
                        width: `${field.w * 100}%`,
                        height: `${Math.max(field.h, 0.006) * 100}%`,
                        border: `1px solid ${colour}`,
                        background: isActive
                          ? "rgba(214,0,111,0.22)"
                          : "rgba(214,0,111,0.08)",
                        outline: isActive ? `1px solid ${colour}` : undefined,
                      }}
                    >
                      {isActive ? (
                        <span
                          onPointerDown={(e) => beginDrag(e, field.uid, "resize")}
                          className="absolute bottom-0 left-0 h-2.5 w-2.5 cursor-nwse-resize"
                          style={{ background: colour }}
                        />
                      ) : null}
                    </div>
                  );
                })}
                </PageCanvas>
              </div>

              <p className="mt-3 text-center text-xs text-muted-soft">
                اسحب المربّع لتحريكه، واسحب الزاوية لتغيير مقاسه. القيم محفوظة
                بإحداثيات نسبية.
              </p>
            </Panel>

            <SectionEditor
              sections={sections}
              pageCount={template.page_count}
              onChange={(next) => {
                setSections(next);
                setDirty(true);
              }}
            />
          </div>

          <div className="space-y-4">
            <Panel>
              <PanelHeader
                title="حقول الصفحة"
                meta={`${onPage.length} / ${fields.length}`}
              />
              <div className="max-h-56 overflow-y-auto">
                {onPage.length === 0 ? (
                  <p className="px-5 py-4 text-sm text-muted-soft">
                    لا توجد حقول على هذه الصفحة.
                  </p>
                ) : (
                  onPage.map((field) => (
                    <button
                      key={field.uid}
                      type="button"
                      onClick={() => setSelected(field.uid)}
                      className={`flex w-full items-center justify-between gap-2 border-b border-line px-5 py-2 text-right text-sm last:border-b-0 ${
                        selected === field.uid ? "bg-[#FCE8F2]" : "hover:bg-paper"
                      }`}
                    >
                      <span className="truncate">{field.label || field.key}</span>
                      <span
                        className="mono shrink-0 text-[10px]"
                        style={{ color: TYPE_COLORS[field.type] }}
                      >
                        {field.type.toUpperCase()}
                      </span>
                    </button>
                  ))
                )}
              </div>
            </Panel>

            {active ? (
              <FieldProperties
                field={active}
                pageWidth={template.page_width}
                pageHeight={template.page_height}
                fonts={template.fonts}
                onChange={(patch) => update(active.uid, patch)}
                onDelete={() => removeField(active.uid)}
              />
            ) : (
              <Panel className="p-5 text-sm text-muted-soft">
                اختر حقلًا من القائمة أو من الصفحة لعرض خصائصه.
              </Panel>
            )}
          </div>
        </div>
      )}

      <button
        type="button"
        className="btn-ghost mt-6"
        onClick={() => router.push("/admin/templates")}
      >
        <span aria-hidden>→</span> رجوع للقوالب
      </button>
    </AppShell>
  );
}

function clamp(value: number, low: number, high: number): number {
  return Math.min(high, Math.max(low, value));
}

function FieldProperties({
  field,
  pageWidth,
  pageHeight,
  fonts,
  onChange,
  onDelete,
}: {
  field: Draft;
  pageWidth: number;
  pageHeight: number;
  fonts: string[];
  onChange: (patch: Partial<Draft>) => void;
  onDelete: () => void;
}) {
  const families = Array.from(
    new Set([...fonts.map((f) => f.split("-")[0] ?? f), field.font_family]),
  );
  const weights = ["Light", "Regular", "Medium", "Bold"];

  return (
    <Panel>
      <PanelHeader title="خصائص الحقل" meta={field.type.toUpperCase()} />
      <div className="space-y-3 p-5">
        <Labelled label="اسم الحقل (المفتاح)">
          <input
            dir="ltr"
            className="mono text-xs"
            value={field.key}
            onChange={(e) => onChange({ key: e.target.value.trim() })}
          />
        </Labelled>
        <Labelled label="التسمية الظاهرة">
          <input
            value={field.label}
            placeholder="مثال: رقم الصك"
            onChange={(e) => onChange({ label: e.target.value })}
          />
        </Labelled>

        <div className="grid grid-cols-2 gap-3">
          <Labelled label="النوع">
            <select
              value={field.type}
              onChange={(e) =>
                onChange({ type: e.target.value as Draft["type"] })
              }
            >
              {FIELD_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </Labelled>
          <Labelled label="المحاذاة">
            <select
              value={field.align}
              onChange={(e) => onChange({ align: e.target.value })}
            >
              {ALIGNS.map((a) => (
                <option key={a} value={a}>
                  {a}
                </option>
              ))}
            </select>
          </Labelled>
        </div>

        {field.type === "text" ? (
          <>
            <div className="grid grid-cols-2 gap-3">
              <Labelled label="الخط">
                <select
                  value={field.font_family}
                  onChange={(e) => onChange({ font_family: e.target.value })}
                >
                  {families.map((f) => (
                    <option key={f} value={f}>
                      {f}
                    </option>
                  ))}
                </select>
              </Labelled>
              <Labelled label="الوزن">
                <select
                  value={field.font_weight}
                  onChange={(e) => onChange({ font_weight: e.target.value })}
                >
                  {weights.map((w) => (
                    <option key={w} value={w}>
                      {w}
                    </option>
                  ))}
                </select>
              </Labelled>
            </div>
            <div className="grid grid-cols-3 gap-3">
              <Labelled label="الحجم pt">
                <input
                  type="number"
                  step="0.5"
                  value={field.font_size_pt}
                  onChange={(e) =>
                    onChange({ font_size_pt: Number(e.target.value) })
                  }
                />
              </Labelled>
              <Labelled label="اللون">
                <input
                  type="color"
                  className="h-9 p-1"
                  value={field.color}
                  onChange={(e) => onChange({ color: e.target.value.toUpperCase() })}
                />
              </Labelled>
              <Labelled label="الدوران">
                <select
                  value={field.rotation}
                  onChange={(e) => onChange({ rotation: Number(e.target.value) })}
                >
                  {[0, 90, 180, 270].map((r) => (
                    <option key={r} value={r}>
                      {r}°
                    </option>
                  ))}
                </select>
              </Labelled>
            </div>
            <Labelled label="سلوك النص الطويل">
              <select
                value={field.fit}
                onChange={(e) => onChange({ fit: e.target.value })}
              >
                <option value="shrink">تصغير تلقائي</option>
                <option value="clip">قصّ ما لا يتّسع</option>
                <option value="wrap">التفاف وتمدّد لأسفل</option>
              </select>
            </Labelled>
          </>
        ) : null}

        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            className="h-4 w-4"
            checked={field.is_required}
            onChange={(e) => onChange({ is_required: e.target.checked })}
          />
          حقل إلزامي — يُرفض الصفّ إن كان فارغًا
        </label>

        <div>
          <div className="mb-1.5 text-sm text-muted">الموضع والمقاس (نقطة)</div>
          <div className="mono grid grid-cols-4 gap-2 text-center text-xs">
            {(
              [
                ["X", field.x * pageWidth],
                ["Y", field.y * pageHeight],
                ["W", field.w * pageWidth],
                ["H", field.h * pageHeight],
              ] as const
            ).map(([label, value]) => (
              <div key={label} className="border border-line py-2">
                <div className="text-[10px] text-muted-soft">{label}</div>
                <div>{Math.round(value)}</div>
              </div>
            ))}
          </div>
        </div>

        {field.table_spec ? (
          <p className="text-xs text-muted-soft">
            جدول: <Mono>{field.table_spec.rows}</Mono> صفوف ·{" "}
            <Mono>{field.table_spec.columns.length}</Mono> أعمدة — تُحرَّر من ملف
            التصميم، لا من هنا.
          </p>
        ) : null}

        <button type="button" className="btn-ghost text-bad" onClick={onDelete}>
          حذف الحقل
        </button>
      </div>
    </Panel>
  );
}

function SectionEditor({
  sections,
  pageCount,
  onChange,
}: {
  sections: TemplateSectionUpdate[];
  pageCount: number;
  onChange: (next: TemplateSectionUpdate[]) => void;
}) {
  function patch(index: number, changes: Partial<TemplateSectionUpdate>) {
    onChange(
      sections.map((s, i) => {
        if (i !== index) return s;
        const next = { ...s, ...changes };
        // A repeating block's page count *is* its pages-per-item; keeping them
        // in step here avoids a server rejection the admin cannot interpret.
        if (next.kind === "per_record") {
          next.pages_per_item = next.last_page - next.first_page + 1;
        }
        return next;
      }),
    );
  }

  return (
    <Panel>
      <PanelHeader
        title="الأقسام"
        meta={`${pageCount} PAGES`}
        action={
          <button
            type="button"
            className="text-xs text-accent"
            onClick={() =>
              onChange([
                ...sections,
                {
                  name: "قسم جديد",
                  kind: "fixed",
                  first_page: 0,
                  last_page: 0,
                  pages_per_item: 1,
                  rows_per_page: 1,
                  variant: null,
                },
              ])
            }
          >
            + قسم
          </button>
        }
      />
      <p className="border-b border-line px-5 py-2.5 text-xs text-muted">
        القسم «يتكرّر لكل سجلّ» هو ما يجعل نطاق الصفحات يتكرّر لكل عقار.
      </p>
      {sections.map((section, index) => (
        <div
          key={index}
          className="grid items-end gap-3 border-b border-line px-5 py-3 last:border-b-0 sm:grid-cols-[1.4fr_1fr_70px_70px_80px_40px]"
        >
          <div>
            <span className="field-label">الاسم</span>
            <input
              value={section.name}
              onChange={(e) => patch(index, { name: e.target.value })}
            />
          </div>
          <div>
            <span className="field-label">النوع</span>
            <select
              value={section.kind}
              onChange={(e) =>
                patch(index, {
                  kind: e.target.value as TemplateSectionUpdate["kind"],
                })
              }
            >
              {SECTION_KINDS.map((k) => (
                <option key={k.value} value={k.value}>
                  {k.label}
                </option>
              ))}
            </select>
          </div>
          <div>
            <span className="field-label">من</span>
            <input
              type="number"
              min={1}
              max={pageCount}
              value={section.first_page + 1}
              onChange={(e) =>
                patch(index, { first_page: Number(e.target.value) - 1 })
              }
            />
          </div>
          <div>
            <span className="field-label">إلى</span>
            <input
              type="number"
              min={1}
              max={pageCount}
              value={section.last_page + 1}
              onChange={(e) =>
                patch(index, { last_page: Number(e.target.value) - 1 })
              }
            />
          </div>
          <div>
            <span className="field-label">
              {section.kind === "table" ? "صفوف/صفحة" : "صفحات/سجلّ"}
            </span>
            {section.kind === "table" ? (
              <input
                type="number"
                min={1}
                value={section.rows_per_page}
                onChange={(e) =>
                  patch(index, { rows_per_page: Number(e.target.value) })
                }
              />
            ) : (
              <input
                readOnly
                className="bg-paper"
                value={
                  section.kind === "per_record"
                    ? section.last_page - section.first_page + 1
                    : "—"
                }
              />
            )}
          </div>
          <button
            type="button"
            className="pb-2 text-sm text-muted-soft hover:text-bad"
            onClick={() => onChange(sections.filter((_, i) => i !== index))}
          >
            حذف
          </button>
        </div>
      ))}
    </Panel>
  );
}
