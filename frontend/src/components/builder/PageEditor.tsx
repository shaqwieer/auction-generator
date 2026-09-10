"use client";

/**
 * One page of the booklet, with its fields typed into on top of it.
 *
 * The page underneath is a server raster of the real baked artwork, rendered
 * through the same engine that will print it. The inputs over it are ordinary
 * `<input>` and `<textarea>` elements placed from each field's normalised rect,
 * which is the same geometry the renderer uses — so a box is where its value
 * will land.
 *
 * They are an editing affordance, not a preview. No attempt is made to match
 * the brand font in the browser: the authoritative rendering is underneath, and
 * a near-miss in a substituted font is more misleading than an honest input.
 *
 * So only one of the two ever paints a given value. At rest the page does: the
 * box is empty, invisible, and the client is looking at their booklet. While a
 * box has focus the page is asked for again *without* that field — the renderer
 * leaves the hole — and the box paints into it. Nothing is ever drawn twice.
 *
 * At rest there are no boxes to see, either. A page ruled into rectangles is not
 * a page a designer can judge, and the fields are listed beside it in الحقول
 * anyway; hovering brings the one under the pointer up, and that is enough to
 * find them.
 *
 * There is no dragging here on purpose. A client fills the designer's layout
 * in; moving a field off the artwork the brand guide fixed is not theirs to do.
 */

import { useRef, useState } from "react";

import { PageCanvas, placement } from "@/components/pagecanvas";
import { Labelled } from "@/components/ui";
import type { TemplateFieldOut } from "@/types/api";

/**
 * The company's own mark and name, which the booklet fills in by itself.
 *
 * The designer drew the selling agent's lockup on seventeen pages, and the
 * build puts `company_logo` there and `company_name` on تعريف وكيل البيع. Both
 * are resolved from the signed-in account at compose time — `page_plan.branding`
 * — never from the project, so a logo uploaded this afternoon appears on the
 * booklet started this morning.
 *
 * So neither belongs in the builder. Offered per page they were asked for on
 * every page that carries a mark, and because a node's values beat the
 * project's, uploading on one page would have overridden the account's logo on
 * that page alone — a booklet branded two ways. They are changed once, in
 * إعدادات الشركة.
 */
const BRANDING = new Set(["company_logo", "company_name"]);

/**
 * The fields of one page in the order a reader meets them.
 *
 * The API hands them over ordered by page alone (`TemplateField.page_index`),
 * which leaves the order within a page to however the derive sweep happened to
 * emit them — so الحقول listed a page's boxes in an order with no relation to
 * the page beside it, and filling a form meant hunting for the next box.
 *
 * Arabic reads top to bottom, right to left, so that is the order: down by `y`,
 * then right to left by `x`. `x` is the distance from the **left** edge, so
 * right-to-left is *descending* x.
 *
 * Rows are grouped before sorting. Boxes a designer set on one visual line
 * differ in `y` by a hair — on the property page النوع, المساحة and شمالا sit
 * within 0.005 of each other — and a raw `y` sort reads those as three rows and
 * interleaves the columns.
 *
 * The grouping walks the fields in `y` order and starts a new row when one
 * opens further than `ROW_TOLERANCE` below the row's first box. It is not a
 * fixed band: bands are cut at absolute positions, so a row that happens to
 * straddle a boundary is split no matter how wide the band is, and a band wide
 * enough to be safe swallows the next row whole. Measured on the property page,
 * a row spans 0.005 and the pitch between rows is 0.021 — the tolerance sits
 * between the two.
 */
const ROW_TOLERANCE = 0.012;

export function inReadingOrder(fields: TemplateFieldOut[]): TemplateFieldOut[] {
  const byY = [...fields].sort((a, b) => a.y - b.y);
  const rows: TemplateFieldOut[][] = [];
  for (const field of byY) {
    const row = rows[rows.length - 1];
    const first = row?.[0];
    if (row && first && field.y - first.y <= ROW_TOLERANCE) row.push(field);
    else rows.push([field]);
  }
  // Right to left within the row: `x` is the distance from the left edge.
  return rows.flatMap((row) => row.sort((a, b) => b.x - a.x));
}

/** Fields that can be typed *on the page*. Tables draw themselves from the data. */
export function fillable(fields: TemplateFieldOut[]): TemplateFieldOut[] {
  return fields.filter(
    (field) =>
      field.type === "text" &&
      !field.key.startsWith("__") &&
      !BRANDING.has(field.key),
  );
}

/**
 * The boxes the guide writes as sections: a bold title over its points.
 *
 * Three of them, and they are the same box in three places -- معلومات إضافية
 * on the property page and on its own continuation page, and مميزات العقار on
 * the features page. Each gets the sections editor instead of a bare textarea,
 * so it is left out of الحقول rather than asked for twice.
 */
const SECTIONED = new Set(["notes", "extra_info", "lot_features"]);

export function sectioned(fields: TemplateFieldOut[]): TemplateFieldOut[] {
  return fields.filter((field) => SECTIONED.has(field.key));
}

/**
 * Fields the form asks for, which is more than the page can show.
 *
 * A link is one: the address a code leads to is never printed, so there is
 * nothing on the page to type it onto — but it is still something the client
 * has to give, and the chip it belongs to is named right there in the list.
 */
export function askable(fields: TemplateFieldOut[]): TemplateFieldOut[] {
  return fields.filter(
    (field) =>
      (field.type === "text" || field.type === "link") &&
      !field.key.startsWith("__") &&
      !BRANDING.has(field.key) &&
      !SECTIONED.has(field.key),
  );
}

/**
 * What a field prints when nothing has been typed into it.
 *
 * Shown as the box's placeholder, so a field that is already filling itself in
 * does not read as empty. `{key}` names one of the booklet's own facts — the
 * auction is named once, on the auction-info page, and the steps page prints
 * that name rather than asking for it again. Which value wins is the server's
 * rule, resolved in `plan.booklet`; all that happens here is the substitution.
 */
export function resolvedDefault(
  field: TemplateFieldOut,
  booklet: Record<string, string>,
): string {
  if (!field.default_value) return "";
  return field.default_value.replace(
    /\{([a-z0-9_]+)\}/g,
    (_, key: string) => booklet[key] ?? "",
  );
}

export function photoFields(fields: TemplateFieldOut[]): TemplateFieldOut[] {
  return fields.filter(
    (field) => field.type === "image" && !BRANDING.has(field.key),
  );
}

export function PageEditor({
  src,
  alt,
  pageWidth,
  pageHeight,
  fields,
  values,
  onChange,
  onFocusField,
  focused,
}: {
  src: string;
  alt: string;
  pageWidth: number;
  pageHeight: number;
  fields: TemplateFieldOut[];
  values: Record<string, string>;
  onChange: (key: string, value: string) => void;
  onFocusField: (key: string | null) => void;
  focused: string | null;
}) {
  return (
    <PageCanvas
      src={src}
      alt={alt}
      width={pageWidth}
      height={pageHeight}
      className="mx-auto w-full"
      sizeContainer
    >
      {fillable(fields).map((field) => {
        const active = focused === field.key;
        const multiline = field.fit === "wrap";
        const style = {
          ...placement(field, 0.012),
          fontSize: `${(field.font_size_pt / pageHeight) * 100}cqh`,
          textAlign: field.align as "right" | "left" | "center",
          // Only the focused box paints its value; the page paints the rest.
          color: active ? field.color : "transparent",
          caretColor: field.color,
          // The rule sits under the text rather than boxing it in, so a page at
          // rest is a page and not a grid of rectangles.
          boxShadow: active ? `inset 0 -1px 0 0 ${field.color}` : undefined,
        };
        const shared = {
          value: values[field.key] ?? "",
          title: field.label || field.key,
          dir: field.rtl ? ("rtl" as const) : ("ltr" as const),
          onFocus: () => onFocusField(field.key),
          onBlur: () => onFocusField(null),
          onChange: (
            event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>,
          ) => onChange(field.key, event.target.value),
          className:
            "absolute resize-none overflow-hidden border-0 bg-transparent p-0 " +
            "leading-tight outline-none transition-shadow " +
            (active ? "" : "hover:bg-accent/10"),
          style,
        };
        return multiline ? (
          <textarea key={field.id} {...shared} />
        ) : (
          <input key={field.id} type="text" {...shared} />
        );
      })}
    </PageCanvas>
  );
}

/**
 * The same fields as a plain form.
 *
 * Kept beside the page because some fields cannot be reached on it — a rotated
 * one, a zero-height one, one sitting under another — and because typing into
 * a list is simply easier for anyone entering a lot of values.
 *
 * Never disabled while a save is in flight. Values are saved on a debounce, so
 * disabling the control mid-sentence takes the caret out of the box the user is
 * still typing into and drops whatever they type next.
 */
export function FieldList({
  fields,
  values,
  onChange,
  focused,
  onFocusField,
  booklet = {},
}: {
  fields: TemplateFieldOut[];
  values: Record<string, string>;
  onChange: (key: string, value: string) => void;
  focused: string | null;
  onFocusField: (key: string | null) => void;
  booklet?: Record<string, string>;
}) {
  const editable = askable(fields);
  if (!editable.length) {
    return (
      <p className="p-5 text-sm text-muted">
        لا توجد حقول قابلة للتعبئة في هذه الصفحة.
      </p>
    );
  }
  return (
    // Two columns where there is room. A property page asks for twenty-two
    // values, and in one column that is a screen and a half of scrolling to
    // reach the last of them — the short ones (a deed number, an area, a
    // boundary) sit side by side without crowding.
    <div className="grid gap-3 p-5 [@media(min-width:1600px)]:grid-cols-2">
      {editable.map((field) => (
        <Labelled
          key={field.id}
          label={field.label || field.key}
          // A paragraph does not belong in half a column; the short values do.
          className={field.fit === "wrap" ? "[@media(min-width:1600px)]:col-span-2" : ""}
        >
          {field.type === "link" ? (
            <input
              value={values[field.key] ?? ""}
              dir="ltr"
              inputMode="url"
              placeholder="https://"
              onFocus={() => onFocusField(field.key)}
              onBlur={() => onFocusField(null)}
              onChange={(event) => onChange(field.key, event.target.value)}
              className={`mono ${focused === field.key ? "border-accent" : ""}`}
            />
          ) : field.fit === "wrap" ? (
            <textarea
              rows={3}
              value={values[field.key] ?? ""}
              placeholder={resolvedDefault(field, booklet)}
              onFocus={() => onFocusField(field.key)}
              onBlur={() => onFocusField(null)}
              onChange={(event) => onChange(field.key, event.target.value)}
              className={focused === field.key ? "border-accent" : ""}
            />
          ) : (
            <input
              value={values[field.key] ?? ""}
              placeholder={resolvedDefault(field, booklet)}
              onFocus={() => onFocusField(field.key)}
              onBlur={() => onFocusField(null)}
              onChange={(event) => onChange(field.key, event.target.value)}
              className={focused === field.key ? "border-accent" : ""}
            />
          )}
        </Labelled>
      ))}
    </div>
  );
}

/** Drop a photograph straight onto the field that will print it. */
export function PhotoSlot({
  field,
  current,
  disabled,
  onUpload,
  onClear,
}: {
  field: TemplateFieldOut;
  current: string;
  disabled?: boolean;
  onUpload: (fieldKey: string, file: File) => Promise<void>;
  onClear: (fieldKey: string) => Promise<void>;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);

  async function work(action: () => Promise<void>) {
    setBusy(true);
    try {
      await action();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex items-center gap-3 overflow-hidden border border-line p-3">
      {/*
        `min-w-0` on the flex child is what lets `truncate` work at all: a flex
        item's default minimum width is its content, so a long filename pushed
        the row wider than the panel instead of being cut. `break-all` catches
        the case where there is nothing to truncate at.
      */}
      <div className="min-w-0 flex-1">
        <span className="block truncate text-sm">
          {field.label || field.key}
        </span>
        <span
          className="mono block truncate break-all text-xs text-muted-soft"
          title={current || undefined}
          dir="ltr"
        >
          {current || "لا توجد صورة"}
        </span>
      </div>
      {current ? (
        <button
          type="button"
          className="shrink-0 border border-line px-2 py-1 text-xs text-bad transition-colors hover:border-bad"
          disabled={disabled || busy}
          onClick={() => void work(() => onClear(field.key))}
        >
          إزالة
        </button>
      ) : null}
      <button
        type="button"
        className="btn btn-secondary shrink-0"
        disabled={disabled || busy}
        onClick={() => input.current?.click()}
      >
        {busy ? "جارٍ الحفظ…" : current ? "استبدال" : "رفع صورة"}
      </button>
      <input
        ref={input}
        type="file"
        accept="image/png,image/jpeg,image/webp,image/tiff"
        className="hidden"
        onChange={(event) => {
          const file = event.target.files?.[0];
          event.target.value = "";
          if (file) void work(() => onUpload(field.key, file));
        }}
      />
    </div>
  );
}

/**
 * The marks a page carries, which the booklet fills in from the account.
 *
 * `photoFields` deliberately leaves them out: nobody uploads a company logo per
 * page, because it is set once in إعدادات الشركة. Its *size* is another matter
 * — the same lockup is drawn at eighteen sizes through the booklet, and a
 * company whose mark is squarer than the guide's sample wants room on the cover
 * that it does not want in a footer.
 */
export function markFields(fields: TemplateFieldOut[]): TemplateFieldOut[] {
  return fields.filter(
    (field) =>
      field.type === "image" && field.preserve_aspect && BRANDING.has(field.key),
  );
}

/**
 * Where a mark's size is stored.
 *
 * Named for the page as well as the field. A property's values are kept on its
 * record and every page of that property reads them, so a key without the page
 * in it would size the mark on صفحة العقار and on مميزات العقار together.
 */
export const SIZE_PREFIX = "__size_";

export function sizeKey(field: TemplateFieldOut): string {
  return `${SIZE_PREFIX}${field.page_index}_${field.key}`;
}

/** `"120x90"` -> `["120", "90"]`; anything unset reads as 100. */
export function readSize(value: string): [string, string] {
  const [width = "", height = ""] = (value || "").split("x");
  return [width.trim(), height.trim()];
}

/**
 * How big the mark is drawn on this page, as a percentage of the box the
 * designer drew for it.
 *
 * Two numbers, not one, because that is what was asked for — but they can only
 * ever change the *box*. The mark keeps its own proportions inside it, so
 * neither number can stretch a logo; a wider box simply gives it more room to
 * be as large as its height allows. Empty means untouched, which is what the
 * artwork does.
 */
export function LogoSize({
  field,
  value,
  disabled,
  onChange,
}: {
  field: TemplateFieldOut;
  value: string;
  disabled?: boolean;
  onChange: (value: string) => void;
}) {
  const [width, height] = readSize(value);
  const set = (next: [string, string]) => {
    const [w, h] = next.map((part) => part.trim());
    onChange(w || h ? `${w}x${h}` : "");
  };
  return (
    <div className="border border-line p-3">
      <span className="mb-2 block text-sm">{field.label || field.key}</span>
      <div className="grid grid-cols-2 gap-3">
        <Labelled label="العرض ٪">
          <input
            type="number"
            min={10}
            max={1000}
            step={5}
            placeholder="100"
            value={width}
            disabled={disabled}
            dir="ltr"
            className="mono"
            onChange={(event) => set([event.target.value, height])}
          />
        </Labelled>
        <Labelled label="الارتفاع ٪">
          <input
            type="number"
            min={10}
            max={1000}
            step={5}
            placeholder="100"
            value={height}
            disabled={disabled}
            dir="ltr"
            className="mono"
            onChange={(event) => set([width, event.target.value])}
          />
        </Labelled>
      </div>
    </div>
  );
}
