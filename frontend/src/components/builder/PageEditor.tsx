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

/** Fields that can be typed *on the page*. Tables draw themselves from the data. */
export function fillable(fields: TemplateFieldOut[]): TemplateFieldOut[] {
  return fields.filter(
    (field) => field.type === "text" && !field.key.startsWith("__"),
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
      !SECTIONED.has(field.key),
  );
}

export function photoFields(fields: TemplateFieldOut[]): TemplateFieldOut[] {
  return fields.filter((field) => field.type === "image");
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
}: {
  fields: TemplateFieldOut[];
  values: Record<string, string>;
  onChange: (key: string, value: string) => void;
  focused: string | null;
  onFocusField: (key: string | null) => void;
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
    <div className="grid gap-3 p-5">
      {editable.map((field) => (
        <Labelled key={field.id} label={field.label || field.key}>
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
              onFocus={() => onFocusField(field.key)}
              onBlur={() => onFocusField(null)}
              onChange={(event) => onChange(field.key, event.target.value)}
              className={focused === field.key ? "border-accent" : ""}
            />
          ) : (
            <input
              value={values[field.key] ?? ""}
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
