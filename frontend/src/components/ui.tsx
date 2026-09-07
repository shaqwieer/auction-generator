/**
 * Primitives from `Matbaa Design Plan.dc.html`.
 *
 * Two rules hold throughout: technical values (filenames, counters, row numbers,
 * durations) are Latin numerals in an isolated LTR run, and progress fills and
 * arrows point leftward because the page reads right to left.
 */
"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";

import { tokens } from "@/lib/api";
import type { JobStatus, ProjectStatus } from "@/types/api";

export function Mono({ children }: { children: ReactNode }) {
  return <span className="mono">{children}</span>;
}

/**
 * An image behind a bearer-token endpoint.
 *
 * A plain `<img src>` cannot carry an Authorization header, so pointing one at
 * an authenticated route yields a 401 and a broken-image icon. Fetch the bytes
 * with the token instead and hand the tag an object URL, revoking it on unmount
 * so the blobs do not accumulate.
 */
/**
 * Blobs already fetched, by URL.
 *
 * The sidebar's company mark is the same image on every screen, and the sidebar
 * unmounts and remounts on every navigation — so without this it was refetched
 * each time and the mark blinked white between pages. Bounded, because the
 * builder asks for a different page raster on every keystroke and an unbounded
 * cache of those is a leak; the oldest is revoked when the cap is passed.
 */
const IMAGE_CACHE = new Map<string, string>();
const IMAGE_CACHE_MAX = 24;

function remember(src: string, objectUrl: string): void {
  IMAGE_CACHE.set(src, objectUrl);
  while (IMAGE_CACHE.size > IMAGE_CACHE_MAX) {
    const oldest = IMAGE_CACHE.keys().next().value;
    if (oldest === undefined) break;
    const stale = IMAGE_CACHE.get(oldest);
    IMAGE_CACHE.delete(oldest);
    if (stale) URL.revokeObjectURL(stale);
  }
}

export function AuthImage({
  src,
  alt,
  className = "",
}: {
  src: string;
  alt: string;
  className?: string;
}) {
  const [url, setUrl] = useState<string | null>(() => IMAGE_CACHE.get(src) ?? null);
  const [failed, setFailed] = useState(false);

  // The page a builder is typing on re-renders on every save, which changes
  // `src`. Blanking on the way to the new raster made the page flash grey
  // mid-sentence and read as a reload, so whatever is already on screen stays
  // there until its replacement has actually arrived.
  useEffect(() => {
    const cached = IMAGE_CACHE.get(src);
    if (cached) {
      setUrl(cached);
      setFailed(false);
      return;
    }

    let cancelled = false;
    setFailed(false);

    void (async () => {
      try {
        const response = await fetch(src, {
          headers: { Authorization: `Bearer ${tokens.access() ?? ""}` },
        });
        if (!response.ok) throw new Error(String(response.status));
        const blob = await response.blob();
        if (cancelled) return;
        const objectUrl = URL.createObjectURL(blob);
        remember(src, objectUrl);
        setUrl(objectUrl);
      } catch {
        if (!cancelled) setFailed(true);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [src]);

  if (failed) {
    return (
      <div className={`grid place-items-center bg-paper text-xs text-muted-soft ${className}`}>
        تعذّر عرض الصورة
      </div>
    );
  }
  if (!url) {
    return <div className={`animate-pulse bg-line ${className}`} />;
  }
  // eslint-disable-next-line @next/next/no-img-element
  return <img src={url} alt={alt} className={className} />;
}

/** A field label above whatever control it names. */
export function Labelled({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <div>
      <span className="field-label">{label}</span>
      {children}
    </div>
  );
}

export function Panel({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return <div className={`panel ${className}`}>{children}</div>;
}

export function PanelHeader({
  title,
  meta,
  action,
}: {
  title: string;
  meta?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-line px-5 py-3.5">
      <div className="flex items-baseline gap-3">
        <h2 className="text-lg font-semibold">{title}</h2>
        {meta ? (
          <span className="mono text-xs text-muted-soft">{meta}</span>
        ) : null}
      </div>
      {action}
    </div>
  );
}

/**
 * A panel whose body folds away.
 *
 * For a section that is settled most of the time and only occasionally
 * revisited — the cover, once it has been chosen — so it stops taking a
 * screenful away from the page being filled in. The header is the control:
 * the whole strip is the button, and the chevron points down when open. It
 * turns leftward when closed, the direction this page reads.
 */
export function Foldable({
  title,
  meta,
  open,
  onToggle,
  children,
  className = "",
}: {
  title: string;
  meta?: ReactNode;
  open: boolean;
  onToggle: (open: boolean) => void;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={`panel ${className}`}>
      <button
        type="button"
        aria-expanded={open}
        onClick={() => onToggle(!open)}
        className={`flex w-full items-baseline justify-between gap-4 px-5 py-3.5 text-start transition-colors hover:bg-paper ${
          open ? "border-b border-line" : ""
        }`}
      >
        <span className="flex items-baseline gap-3">
          <span className="text-lg font-semibold">{title}</span>
          {meta ? (
            <span className="mono text-xs text-muted-soft">{meta}</span>
          ) : null}
        </span>
        <span aria-hidden className="text-xs text-muted-soft">
          {open ? "▾" : "◂"}
        </span>
      </button>
      {open ? children : null}
    </div>
  );
}

const STATUS_STYLES: Record<string, { label: string; className: string }> = {
  draft: { label: "مسودة", className: "bg-surface text-muted border-line" },
  mapping: { label: "قيد الربط", className: "bg-surface text-muted border-line" },
  queued: {
    label: "في الانتظار",
    className: "bg-[#FCE8F2] text-accent border-[#F5CCE1]",
  },
  running: {
    label: "قيد التوليد",
    className: "bg-[#FCE8F2] text-accent border-[#F5CCE1]",
  },
  generating: {
    label: "قيد التوليد",
    className: "bg-[#FCE8F2] text-accent border-[#F5CCE1]",
  },
  paused: { label: "متوقّفة مؤقتًا", className: "bg-surface text-muted border-line" },
  ready: { label: "جاهز", className: "bg-[#F1F5F4] text-ok border-[#CFE3DF]" },
  succeeded: { label: "جاهز", className: "bg-[#F1F5F4] text-ok border-[#CFE3DF]" },
  failed: { label: "به أخطاء", className: "bg-[#FDF2EC] text-bad border-[#F3D6C6]" },
  cancelled: { label: "أُلغيت", className: "bg-surface text-muted border-line" },
};

export function StatusPill({ status }: { status: ProjectStatus | JobStatus | string }) {
  const style = STATUS_STYLES[status] ?? {
    label: status,
    className: "bg-surface text-muted border-line",
  };
  return (
    <span
      className={`inline-block rounded border px-2.5 py-1 text-sm ${style.className}`}
    >
      {style.label}
    </span>
  );
}

/**
 * Fills from the right, matching the reading direction. The track is a flex
 * row so the bar starts at the inline-start edge, which RTL puts on the right.
 */
export function Progress({ value }: { value: number }) {
  const percent = Math.max(0, Math.min(1, value)) * 100;
  return (
    <div className="flex h-1.5 w-full overflow-hidden rounded bg-line">
      <div
        className="h-full bg-accent transition-[width] duration-500"
        style={{ width: `${percent}%` }}
      />
    </div>
  );
}

export function Banner({
  tone = "warn",
  title,
  children,
}: {
  tone?: "warn" | "error" | "info";
  title: string;
  children?: ReactNode;
}) {
  const tones = {
    warn: "border-[#F3D6C6] bg-[#FDF7F4] text-bad",
    error: "border-[#F3D6C6] bg-[#FDF2EC] text-bad",
    info: "border-line bg-surface text-muted",
  } as const;
  return (
    <div className={`border px-4 py-3 text-base ${tones[tone]}`}>
      <div className="flex gap-2">
        <span aria-hidden>!</span>
        <div>
          <div className="font-medium">{title}</div>
          {children ? (
            <div className="mt-1 text-sm opacity-90">{children}</div>
          ) : null}
        </div>
      </div>
    </div>
  );
}

export function Empty({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="px-5 py-14 text-center">
      <div className="text-md text-muted">{title}</div>
      {hint ? <div className="mt-1.5 text-sm text-muted-soft">{hint}</div> : null}
    </div>
  );
}

export function Spinner({ label = "جارٍ التحميل…" }: { label?: string }) {
  return (
    <div className="px-5 py-14 text-center text-sm text-muted-soft">{label}</div>
  );
}

export function Stat({
  label,
  value,
  delta,
}: {
  label: string;
  value: string;
  delta?: string | null;
}) {
  return (
    <div className="bg-surface px-6 py-5">
      <div className="text-sm text-muted">{label}</div>
      <div className="mono mt-2 text-2xl font-semibold text-ink">{value}</div>
      {delta ? <div className="mt-1 text-xs text-muted-soft">{delta}</div> : null}
    </div>
  );
}

/** A hairline-ruled grid; the design uses 1px gaps over a line-coloured bed. */
export function Tiles({ children }: { children: ReactNode }) {
  return (
    <div className="grid gap-px border border-line bg-line sm:grid-cols-2 lg:grid-cols-4">
      {children}
    </div>
  );
}

export function Table({
  head,
  children,
  columns,
}: {
  head: ReactNode[];
  children: ReactNode;
  columns: string;
}) {
  return (
    <div className="overflow-x-auto">
      <div className="min-w-[720px]">
        <div
          className="grid gap-3 border-b border-line bg-paper px-5 py-2.5 text-xs text-muted"
          style={{ gridTemplateColumns: columns }}
        >
          {head.map((cell, index) => (
            <div key={index}>{cell}</div>
          ))}
        </div>
        {children}
      </div>
    </div>
  );
}

export function Row({
  children,
  columns,
  tone,
  onClick,
}: {
  children: ReactNode;
  columns: string;
  tone?: "bad";
  onClick?: () => void;
}) {
  return (
    <div
      onClick={onClick}
      role={onClick ? "button" : undefined}
      tabIndex={onClick ? 0 : undefined}
      onKeyDown={
        onClick
          ? (event) => {
              if (event.key === "Enter") onClick();
            }
          : undefined
      }
      className={`grid items-center gap-3 border-b border-line px-5 py-3 text-sm last:border-b-0 ${
        tone === "bad" ? "bg-[#FDF7F4]" : ""
      } ${onClick ? "cursor-pointer hover:bg-paper" : ""}`}
      style={{ gridTemplateColumns: columns }}
    >
      {children}
    </div>
  );
}

/** Progress in the wizard reads right to left; the arrow points left. */
export function Steps({
  steps,
  current,
}: {
  steps: readonly string[];
  current: number;
}) {
  return (
    <ol className="flex flex-wrap items-center gap-x-5 gap-y-2">
      {steps.map((label, index) => {
        const done = index < current;
        const active = index === current;
        return (
          <li key={label} className="flex items-center gap-2 text-base">
            <span
              className={`flex h-6 w-6 items-center justify-center rounded-full border text-xs ${
                done
                  ? "border-ok bg-ok text-white"
                  : active
                    ? "border-accent bg-accent text-white"
                    : "border-line text-muted-soft"
              }`}
            >
              {done ? "✓" : <span className="mono">{index + 1}</span>}
            </span>
            <span className={active ? "font-medium" : "text-muted"}>{label}</span>
          </li>
        );
      })}
    </ol>
  );
}

export function bytes(value: number): string {
  if (value <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const index = Math.min(units.length - 1, Math.floor(Math.log(value) / Math.log(1024)));
  return `${(value / 1024 ** index).toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

export function duration(from: string | null, to: string | null): string {
  if (!from) return "—";
  const start = new Date(from).getTime();
  const end = to ? new Date(to).getTime() : Date.now();
  const seconds = Math.max(0, Math.round((end - start) / 1000));
  return `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(
    seconds % 60,
  ).padStart(2, "0")}`;
}

export function shortDate(value: string): string {
  return new Date(value).toLocaleDateString("ar-SA-u-nu-latn", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}
