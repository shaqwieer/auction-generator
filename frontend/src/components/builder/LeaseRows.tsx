"use client";

/**
 * A property's lease contracts, typed row by row.
 *
 * بيان العقارات builds itself from the booklet's properties, so nothing is
 * entered for it. This table cannot: nothing in the system knows what leases an
 * asset carries, so they are given here — and the order they are given in is
 * the order they print, which is why the rows move rather than sort.
 *
 * The columns are the template's own, read off the page's table field, so a
 * revised export changes the form without changing this file.
 */

import { useEffect, useRef, useState } from "react";

import type { TableColumnSpec } from "@/types/api";

export interface LeaseRow {
  [key: string]: string;
}

export function LeaseRows({
  columns,
  rows,
  disabled,
  onChange,
}: {
  columns: TableColumnSpec[];
  rows: LeaseRow[];
  disabled?: boolean;
  onChange: (rows: LeaseRow[]) => void | Promise<void>;
}) {
  // Edited locally and sent on blur: every save redraws the page, and sending
  // per keystroke would redraw it mid-word.
  const [draft, setDraft] = useState<LeaseRow[]>(rows);
  // Adopted from the server, but never over the top of a row being typed: the
  // save returns the plan it was given, and typing carries on while it flies.
  const typing = useRef(false);
  useEffect(() => {
    if (typing.current) return;
    setDraft(rows);
  }, [rows]);

  const fields = columns.filter((column) => !column.source);
  if (!fields.length) return null;

  const commit = (next: LeaseRow[]) => {
    setDraft(next);
    typing.current = false;
    void onChange(next);
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
          لا توجد عقود إيجار بعد. أضف عقدًا ليظهر في الجدول.
        </p>
      ) : null}

      {draft.map((row, index) => (
        <div key={index} className="border border-line">
          <div className="flex items-center gap-2 border-b border-line bg-paper px-3 py-2">
            <span className="mono text-xs text-muted-soft">
              {String(index + 1).padStart(2, "0")}
            </span>
            <span className="flex-1 truncate text-xs text-muted">
              {row[fields[0]!.key] || "عقد بلا نوع"}
            </span>
            <RowAction
              label="تقديم"
              disabled={disabled || index === 0}
              onClick={() => move(index, -1)}
            />
            <RowAction
              label="تأخير"
              disabled={disabled || index === draft.length - 1}
              onClick={() => move(index, 1)}
            />
            <RowAction
              label="حذف"
              tone="bad"
              disabled={disabled}
              onClick={() => commit(draft.filter((_, at) => at !== index))}
            />
          </div>
          <div className="grid gap-2 p-3 sm:grid-cols-2">
            {fields.map((column) => (
              <label key={column.key} className="block">
                <span className="field-label">{column.label || column.key}</span>
                <input
                  value={row[column.key] ?? ""}
                  disabled={disabled}
                  onChange={(event) => {
                    typing.current = true;
                    const next = [...draft];
                    next[index] = { ...row, [column.key]: event.target.value };
                    setDraft(next);
                  }}
                  onBlur={() => commit(draft)}
                />
              </label>
            ))}
          </div>
        </div>
      ))}

      <button
        type="button"
        className="btn btn-secondary w-full"
        disabled={disabled}
        onClick={() =>
          commit([
            ...draft,
            Object.fromEntries(fields.map((column) => [column.key, ""])),
          ])
        }
      >
        + إضافة عقد إيجار
      </button>
    </div>
  );
}

function RowAction({
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
