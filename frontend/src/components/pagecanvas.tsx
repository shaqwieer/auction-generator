"use client";

/**
 * A page of a template, at whatever size it happens to be drawn, with things
 * positioned over it in normalised coordinates.
 *
 * The page raster comes from the server, so what is underneath is the real
 * artwork rather than a browser's idea of it. Everything drawn on top is placed
 * from a 0..1 rect, which is how field geometry is stored — so the same
 * component works in the admin editor at 512px and in the builder at whatever
 * width the panel gives it.
 *
 * Note what is deliberately absent: dragging. The admin editor moves and
 * resizes field boxes and keeps that code to itself. The builder fills fields
 * in; it must not be able to move them off the artwork the designer approved.
 */

import type { CSSProperties, ReactNode } from "react";
import { AuthImage } from "@/components/ui";

/** A rect in normalised page coordinates, the way fields are stored. */
export interface NormRect {
  x: number;
  y: number;
  w: number;
  h: number;
}

/**
 * Where to put something on the page.
 *
 * A stored `x` always means "distance from the left edge" — `NormRect` is
 * built by dividing a fitz rect's `x0` by the page width. The canvas inherits
 * `dir="rtl"` from the document, where `insetInlineStart` resolves to `right`,
 * so using it here drew every box at `1 - x - w`: mirrored. A field whose value
 * the renderer puts on the left of the page got its input box on the right, and
 * the page appeared to carry the same value twice.
 *
 * `left` is physical and stays physical under either direction. Keep it that
 * way; the admin editor's drag math adds its delta straight onto `x`, so a
 * logical property there disagrees with the editor's own arithmetic.
 */
export function placement(rect: NormRect, minHeight = 0.006): CSSProperties {
  return {
    left: `${rect.x * 100}%`,
    top: `${rect.y * 100}%`,
    width: `${rect.w * 100}%`,
    height: `${Math.max(rect.h, minHeight) * 100}%`,
  };
}

export function PageCanvas({
  src,
  alt,
  width,
  height,
  className = "",
  sizeContainer = false,
  onBackgroundPointerDown,
  children,
}: {
  src: string;
  alt: string;
  width: number;
  height: number;
  className?: string;
  /**
   * Make the canvas a size container, so children can set a font size as a
   * fraction of the page rather than in pixels. The builder needs it: a value
   * set at 10pt on a 842pt page has to look like 10pt at whatever width the
   * canvas happens to be drawn.
   */
  sizeContainer?: boolean;
  onBackgroundPointerDown?: () => void;
  children?: ReactNode;
}) {
  return (
    <div
      className={`relative select-none border border-edge bg-paper ${className}`}
      style={{
        aspectRatio: `${width} / ${height}`,
        ...(sizeContainer ? { containerType: "size" as const } : {}),
      }}
      onPointerDown={onBackgroundPointerDown}
    >
      <AuthImage
        src={src}
        alt={alt}
        className="absolute inset-0 h-full w-full object-contain"
      />
      {children}
    </div>
  );
}

export interface RailItem {
  key: string;
  label: string;
  meta?: string;
  /** A hairline along the bottom edge, for whatever the caller groups by. */
  tone?: "accent" | "bad" | "ok";
}

const TONES: Record<string, string> = {
  accent: "bg-accent",
  bad: "bg-bad",
  ok: "bg-ok",
};

/** The horizontal strip of pages above a canvas. */
export function PageRail({
  items,
  active,
  onSelect,
}: {
  items: RailItem[];
  active: string;
  onSelect: (key: string) => void;
}) {
  return (
    <div className="flex gap-2 overflow-x-auto">
      {items.map((item) => (
        <button
          key={item.key}
          type="button"
          onClick={() => onSelect(item.key)}
          className={`relative shrink-0 border px-3 py-2 text-center transition-colors ${
            active === item.key
              ? "border-accent bg-[#FCE8F2]"
              : "border-line bg-surface hover:border-edge"
          }`}
        >
          <span className="mono block text-xs">{item.label}</span>
          {item.meta ? (
            <span className="mono block text-[10px] text-muted-soft">
              {item.meta}
            </span>
          ) : null}
          {item.tone ? (
            <span
              className={`absolute inset-x-0 bottom-0 h-0.5 ${TONES[item.tone]}`}
            />
          ) : null}
        </button>
      ))}
    </div>
  );
}
