/**
 * Attach a photograph to each record, or to the project as a whole.
 *
 * Two ways in, because both happen in practice: pick something already in the
 * asset library, or upload a file right here when the spreadsheet had no photo
 * column — or had one that was empty for this row. Uploading assigns in the same
 * action, so the operator never has to visit the library and come back.
 */
"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { API_URL, ApiError, api } from "@/lib/api";
import type { AssetOut, ImageFieldOut, RecordPhotosOut } from "@/types/api";

import { AuthImage, Banner, Empty, Mono, Panel, PanelHeader, Spinner } from "./ui";

interface Props {
  projectId: string;
  /** Called after any change, so the caller can refresh its preflight. */
  onChange?: () => void;
}

export function RecordPhotos({ projectId, onChange }: Props) {
  const [data, setData] = useState<RecordPhotosOut | null>(null);
  const [assets, setAssets] = useState<AssetOut[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busyKey, setBusyKey] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [photos, library] = await Promise.all([
        api.photos(projectId),
        api.assets(),
      ]);
      setData(photos);
      setAssets(library);
    } catch {
      setError("تعذّر تحميل صور السجلات.");
    }
  }, [projectId]);

  useEffect(() => {
    void load();
  }, [load]);

  const byName = useMemo(
    () => new Map(assets.map((asset) => [asset.filename, asset])),
    [assets],
  );

  const recordFields = data?.fields.filter((f) => f.scope === "record") ?? [];
  const projectFields = data?.fields.filter((f) => f.scope === "project") ?? [];

  async function assign(
    scope: "record" | "project",
    rowIndex: number,
    key: string,
    filename: string,
  ) {
    const cell = `${scope}:${rowIndex}:${key}`;
    setBusyKey(cell);
    setError(null);
    try {
      if (scope === "project") {
        await api.updateProject(projectId, {
          static_values: { ...(data?.static_values ?? {}), [key]: filename },
        });
      } else {
        await api.patchRecord(projectId, rowIndex, { [key]: filename });
      }
      await load();
      onChange?.();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "تعذّر الحفظ.");
    } finally {
      setBusyKey(null);
    }
  }

  async function uploadAndAssign(
    scope: "record" | "project",
    rowIndex: number,
    key: string,
    file: File,
  ) {
    const cell = `${scope}:${rowIndex}:${key}`;
    setBusyKey(cell);
    setError(null);
    try {
      const role = scope === "project" ? "cover" : "main";
      const asset = await api.uploadAsset(file, role);
      await assign(scope, rowIndex, key, asset.filename);
      setAssets((current) => [asset, ...current]);
    } catch (caught) {
      // A duplicate filename is the common case: reuse the existing asset.
      if (caught instanceof ApiError && caught.status === 409) {
        await assign(scope, rowIndex, key, file.name);
        return;
      }
      setError(caught instanceof ApiError ? caught.message : "تعذّر رفع الصورة.");
      setBusyKey(null);
    }
  }

  if (data === null) {
    return (
      <Panel>
        <PanelHeader title="صور السجلات" />
        {error ? <Banner tone="error" title={error} /> : <Spinner />}
      </Panel>
    );
  }

  if (data.fields.length === 0) {
    return null; // this template asks for no photographs at all
  }

  const missing =
    recordFields.filter((f) => f.is_required).length > 0
      ? data.records.filter((record) =>
          recordFields.some(
            (f) => f.is_required && !String(record.values[f.key] ?? "").trim(),
          ),
        ).length
      : 0;

  return (
    <Panel>
      <PanelHeader
        title="صور السجلات"
        meta={`${data.records.length} ROWS · ${data.fields.length} IMAGE FIELDS`}
        action={
          missing > 0 ? (
            <span className="text-sm text-bad">{missing} سجلًّا بلا صورة</span>
          ) : (
            <span className="text-sm text-ok">كل السجلات لها صور</span>
          )
        }
      />

      {error ? (
        <div className="p-5 pb-0">
          <Banner tone="error" title={error} />
        </div>
      ) : null}

      <p className="border-b border-line px-5 py-3 text-sm text-muted">
        اختر صورة من مكتبة الأصول، أو ارفع ملفًا مباشرة — سيُضاف إلى المكتبة
        ويُسند إلى هذا الحقل في خطوة واحدة.
      </p>

      {projectFields.length > 0 ? (
        <div className="border-b border-line bg-paper px-5 py-4">
          <div className="mb-3 text-sm font-medium">صور المشروع</div>
          <div className="flex flex-wrap gap-4">
            {projectFields.map((field) => (
              <PhotoCell
                key={field.key}
                field={field}
                value={String(data.static_values[field.key] ?? "")}
                asset={byName.get(String(data.static_values[field.key] ?? ""))}
                assets={assets}
                busy={busyKey === `project:0:${field.key}`}
                onPick={(name) => void assign("project", 0, field.key, name)}
                onUpload={(file) =>
                  void uploadAndAssign("project", 0, field.key, file)
                }
              />
            ))}
          </div>
        </div>
      ) : null}

      {recordFields.length === 0 ? null : data.records.length === 0 ? (
        <Empty title="لا توجد سجلات بعد" hint="ارفع ملف بيانات أو أدخِل العناصر يدويًا." />
      ) : (
        data.records.map((record) => (
          <div
            key={record.id}
            className="flex flex-wrap items-start gap-4 border-b border-line px-5 py-4 last:border-b-0"
          >
            <div className="w-40 shrink-0">
              <div className="mono text-xs text-muted-soft">
                ROW {String(record.row_index + 1).padStart(3, "0")}
              </div>
              <div className="mt-1 truncate text-sm font-medium">
                {String(record.values.deed_number ?? "") || "—"}
              </div>
              <div className="truncate text-xs text-muted-soft">
                {String(record.values.district ?? "")}
              </div>
            </div>
            <div className="flex min-w-0 flex-1 flex-wrap gap-4">
              {recordFields.map((field) => (
                <PhotoCell
                  key={field.key}
                  field={field}
                  value={String(record.values[field.key] ?? "")}
                  asset={byName.get(String(record.values[field.key] ?? ""))}
                  assets={assets}
                  busy={busyKey === `record:${record.row_index}:${field.key}`}
                  onPick={(name) =>
                    void assign("record", record.row_index, field.key, name)
                  }
                  onUpload={(file) =>
                    void uploadAndAssign("record", record.row_index, field.key, file)
                  }
                />
              ))}
            </div>
          </div>
        ))
      )}
    </Panel>
  );
}

function PhotoCell({
  field,
  value,
  asset,
  assets,
  busy,
  onPick,
  onUpload,
}: {
  field: ImageFieldOut;
  value: string;
  asset: AssetOut | undefined;
  assets: AssetOut[];
  busy: boolean;
  onPick: (filename: string) => void;
  onUpload: (file: File) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const unresolved = value !== "" && asset === undefined;

  return (
    <div className="w-[190px] shrink-0">
      <div className="mb-1.5 flex items-baseline justify-between gap-2">
        <span className="text-xs text-muted">
          {field.label}
          {field.is_required ? " *" : ""}
        </span>
        {asset?.below_min_dpi ? (
          <span className="mono text-[10px] text-bad">
            {Math.round(asset.print_dpi_a4)} DPI
          </span>
        ) : null}
      </div>

      <div
        className={`relative aspect-[4/3] overflow-hidden border bg-paper ${
          !value && field.is_required ? "border-bad" : "border-line"
        }`}
      >
        {busy ? (
          <div className="grid h-full place-items-center text-xs text-muted-soft">
            جارٍ الحفظ…
          </div>
        ) : asset ? (
          <AuthImage
            src={`${API_URL}/api/v1/assets/${asset.id}/file`}
            alt={asset.filename}
            className="h-full w-full object-cover"
          />
        ) : unresolved ? (
          <div className="grid h-full place-items-center px-2 text-center text-[11px] text-bad">
            <span>
              <Mono>{value}</Mono>
              <br />
              غير موجود في المكتبة
            </span>
          </div>
        ) : (
          <button
            type="button"
            className="grid h-full w-full place-items-center text-xs text-muted-soft hover:text-accent"
            onClick={() => inputRef.current?.click()}
          >
            + ارفع صورة
          </button>
        )}
      </div>

      <div className="mt-2 flex items-center gap-2">
        <select
          value={asset ? value : ""}
          disabled={busy}
          onChange={(event) => onPick(event.target.value)}
          className="min-w-0 flex-1 px-2 py-1 text-xs"
        >
          <option value="">— من المكتبة —</option>
          {assets.map((item) => (
            <option key={item.id} value={item.filename}>
              {item.filename}
            </option>
          ))}
        </select>
        <button
          type="button"
          disabled={busy}
          className="shrink-0 text-xs text-accent hover:text-ink disabled:opacity-50"
          onClick={() => inputRef.current?.click()}
        >
          رفع
        </button>
        <input
          ref={inputRef}
          type="file"
          accept="image/*"
          hidden
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) onUpload(file);
            event.target.value = "";
          }}
        />
      </div>
    </div>
  );
}
