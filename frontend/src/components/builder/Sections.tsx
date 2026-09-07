"use client";

/**
 * معلومات إضافية written as the guide writes it: titles with points under them.
 *
 * The page is one box of free text, so the value stays one string — a title
 * line ending in a colon, its points beneath, a blank line, the next title.
 * That is exactly what somebody typing by hand would write, and the renderer
 * sets a line like that in bold, so the structure survives whichever way it was
 * entered. The editor here is for people who would rather fill in boxes than
 * remember a convention.
 */

import { useEffect, useRef, useState } from "react";

export interface Section {
  title: string;
  body: string;
}

export function toText(sections: Section[]): string {
  return sections
    .map((section) => {
      const title = section.title.trim();
      const heading = title ? (title.endsWith(":") ? title : `${title}:`) : "";
      return [heading, section.body.trimEnd()].filter(Boolean).join("\n");
    })
    .filter(Boolean)
    .join("\n\n");
}

export function fromText(value: string): Section[] {
  if (!value.trim()) return [];
  return value
    .split(/\n{2,}/)
    .map((block) => {
      const lines = block.split("\n");
      const first = (lines[0] ?? "").trim();
      // A first line ending in a colon is this block's title; anything else is
      // a block of points that never had one.
      return first.endsWith(":")
        ? { title: first.slice(0, -1).trim(), body: lines.slice(1).join("\n") }
        : { title: "", body: block };
    })
    .filter((section) => section.title || section.body.trim());
}

export function Sections({
  value,
  disabled,
  onChange,
}: {
  value: string;
  disabled?: boolean;
  onChange: (value: string) => void;
}) {
  const [draft, setDraft] = useState<Section[]>(() => fromText(value));
  const typing = useRef(false);

  useEffect(() => {
    if (typing.current) return;
    setDraft(fromText(value));
  }, [value]);

  const commit = (next: Section[]) => {
    setDraft(next);
    typing.current = false;
    onChange(toText(next));
  };

  const edit = (index: number, patch: Partial<Section>) => {
    typing.current = true;
    setDraft(draft.map((s, at) => (at === index ? { ...s, ...patch } : s)));
  };

  const move = (index: number, delta: number) => {
    const next = [...draft];
    const target = index + delta;
    if (target < 0 || target >= next.length) return;
    [next[index], next[target]] = [next[target]!, next[index]!];
    commit(next);
  };

  return (
    <div className="grid gap-3 p-4">
      {draft.length === 0 ? (
        <p className="text-sm text-muted">
          لا توجد أقسام بعد. أضف قسمًا بعنوان ونقاط تحته.
        </p>
      ) : null}

      {draft.map((section, index) => (
        <div key={index} className="border border-line">
          <div className="flex items-center gap-2 border-b border-line bg-paper px-3 py-2">
            <span className="mono text-xs text-muted-soft">
              {String(index + 1).padStart(2, "0")}
            </span>
            <span className="flex-1 truncate text-xs text-muted">
              {section.title || "قسم بلا عنوان"}
            </span>
            <Small
              label="تقديم"
              disabled={disabled || index === 0}
              onClick={() => move(index, -1)}
            />
            <Small
              label="تأخير"
              disabled={disabled || index === draft.length - 1}
              onClick={() => move(index, 1)}
            />
            <Small
              label="حذف"
              tone="bad"
              disabled={disabled}
              onClick={() => commit(draft.filter((_, at) => at !== index))}
            />
          </div>
          <div className="grid gap-2 p-3">
            <label className="block">
              <span className="field-label">العنوان — يُطبع عريضًا</span>
              <input
                value={section.title}
                disabled={disabled}
                placeholder="مثال: مميزات العقار"
                onChange={(event) => edit(index, { title: event.target.value })}
                onBlur={() => commit(draft)}
              />
            </label>
            <label className="block">
              <span className="field-label">النقاط — سطر لكل نقطة</span>
              <textarea
                rows={4}
                value={section.body}
                disabled={disabled}
                placeholder={"- بالقرب من طريق الملك فهد\n- بالقرب من مستشفى حائل العام"}
                onChange={(event) => edit(index, { body: event.target.value })}
                onBlur={() => commit(draft)}
              />
            </label>
          </div>
        </div>
      ))}

      <button
        type="button"
        className="btn btn-secondary w-full"
        disabled={disabled}
        onClick={() => commit([...draft, { title: "", body: "" }])}
      >
        + إضافة قسم
      </button>
    </div>
  );
}

function Small({
  label,
  onClick,
  disabled,
  tone,
}: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  tone?: "bad";
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={`border px-2 py-0.5 text-[11px] transition-colors disabled:opacity-40 ${
        tone === "bad"
          ? "border-line text-bad hover:border-bad"
          : "border-line text-muted hover:border-edge hover:text-ink"
      }`}
    >
      {label}
    </button>
  );
}
