"use client";

/**
 * The first thing a client picks: which cover the booklet wears.
 *
 * Six tiles, and only six — the alternatives the brand guide draws, rastered by
 * the server from the designer's own artwork. A cover is not something a client
 * makes here: the booklet wears one of the six or it is off-brand, so there is
 * no upload and no seventh tile.
 */

import { AuthImage } from "@/components/ui";
import { templatePageUrl } from "@/lib/api";
import type { TemplatePageOut } from "@/types/api";

export function CoverChooser({
  templateId,
  pageWidth,
  pageHeight,
  covers,
  chosen,
  onChoose,
}: {
  templateId: string;
  pageWidth: number;
  pageHeight: number;
  covers: TemplatePageOut[];
  chosen: number | null;
  onChoose: (pageIndex: number) => void;
}) {
  if (!covers.length) return null;
  return (
    <div className="grid grid-cols-2 gap-4 sm:grid-cols-4 xl:grid-cols-4">
      {covers.map((cover) => (
        <CoverTile
          key={cover.id}
          templateId={templateId}
          pageWidth={pageWidth}
          pageHeight={pageHeight}
          cover={cover}
          selected={chosen === cover.page_index}
          onChoose={() => onChoose(cover.page_index)}
        />
      ))}
    </div>
  );
}

function CoverTile({
  templateId,
  pageWidth,
  pageHeight,
  cover,
  selected,
  onChoose,
}: {
  templateId: string;
  pageWidth: number;
  pageHeight: number;
  cover: TemplatePageOut;
  selected: boolean;
  onChoose: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onChoose}
      aria-pressed={selected}
      className={`group block border p-2 text-start transition-colors ${
        selected
          ? "border-accent ring-1 ring-accent"
          : "border-line hover:border-edge"
      }`}
    >
      <div
        className="relative w-full bg-paper"
        style={{ aspectRatio: `${pageWidth} / ${pageHeight}` }}
      >
        <AuthImage
          src={templatePageUrl(templateId, cover.page_index, 70)}
          alt={cover.name}
          className="absolute inset-0 h-full w-full object-contain"
        />
      </div>
      <span className="mt-2 block truncate text-xs">{cover.name}</span>
    </button>
  );
}
