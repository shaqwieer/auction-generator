/**
 * Typed client for the Matbaa API.
 *
 * Tokens live in localStorage because the API is a separate origin and the
 * browser will not send a cookie to it without CORS credentials plumbing that
 * buys us nothing here. A 401 triggers one refresh attempt before giving up.
 */
import type {
  AssetOut,
  CategoryOut,
  ClientOut,
  CompanyOut,
  ClientUserCreate,
  DashboardOut,
  DataSourceOut,
  JobDetail,
  JobOut,
  MappingOut,
  MappingSave,
  PreflightOut,
  PagePlanOut,
  ProjectOut,
  RecordOut,
  RecordPhotosOut,
  ResultOut,
  SuggestionOut,
  TemplateDetail,
  TemplateFieldUpdate,
  TemplateIngestOut,
  TemplateOut,
  TemplateSectionUpdate,
  TokenPair,
  UploadResult,
  UserOut,
} from "@/types/api";

export const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const ACCESS = "matbaa.access";
const REFRESH = "matbaa.refresh";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export const tokens = {
  access: (): string | null =>
    typeof window === "undefined" ? null : window.localStorage.getItem(ACCESS),
  refresh: (): string | null =>
    typeof window === "undefined" ? null : window.localStorage.getItem(REFRESH),
  set(pair: TokenPair): void {
    window.localStorage.setItem(ACCESS, pair.access_token);
    window.localStorage.setItem(REFRESH, pair.refresh_token);
  },
  clear(): void {
    window.localStorage.removeItem(ACCESS);
    window.localStorage.removeItem(REFRESH);
  },
};

async function readError(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail) && body.detail.length > 0) {
      const first = body.detail[0] as { msg?: string };
      if (first?.msg) return first.msg;
    }
  } catch {
    /* fall through to the generic message */
  }
  return response.status === 401
    ? "انتهت الجلسة — سجّل الدخول من جديد."
    : "تعذّر إتمام الطلب.";
}

async function tryRefresh(): Promise<boolean> {
  const token = tokens.refresh();
  if (!token) return false;
  const response = await fetch(`${API_URL}/api/v1/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: token }),
  });
  if (!response.ok) return false;
  tokens.set((await response.json()) as TokenPair);
  return true;
}

type Options = Omit<RequestInit, "body"> & { body?: unknown; raw?: boolean };

async function request<T>(path: string, options: Options = {}): Promise<T> {
  const { body, raw, headers, ...rest } = options;
  const send = async (): Promise<Response> => {
    const token = tokens.access();
    const isForm = body instanceof FormData;
    return fetch(`${API_URL}${path}`, {
      ...rest,
      headers: {
        ...(isForm ? {} : { "Content-Type": "application/json" }),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(headers as Record<string, string> | undefined),
      },
      body: isForm ? body : body === undefined ? undefined : JSON.stringify(body),
    });
  };

  let response = await send();
  if (response.status === 401 && tokens.refresh()) {
    if (await tryRefresh()) {
      response = await send();
    }
  }
  if (!response.ok) {
    if (response.status === 401) tokens.clear();
    throw new ApiError(response.status, await readError(response));
  }
  if (raw) return response as unknown as T;
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

/**
 * The URL of one page of the booklet as it will print, for `AuthImage`.
 *
 * `stamp` is the plan revision: the browser caches on the URL, so without
 * something that changes the page would not redraw after an edit.
 */
export function nodePreviewUrl(
  projectId: string,
  nodeId: string,
  {
    dpi = 96,
    page,
    stamp,
    omit,
    version,
  }: {
    dpi?: number;
    page?: number;
    stamp?: number;
    /** Leave this field off the page — it is being typed into on top of it. */
    omit?: string;
    /**
     * The template's version. Rasters are cached by URL, and a rebuilt template
     * changes what a page looks like without changing anything about the
     * booklet — so without this the builder keeps showing the old artwork.
     */
    version?: number;
  } = {},
): string {
  const query = new URLSearchParams({ dpi: String(dpi) });
  if (page !== undefined) query.set("page", String(page));
  if (stamp !== undefined) query.set("v", String(stamp));
  if (omit) query.set("omit", omit);
  if (version !== undefined) query.set("t", String(version));
  return `${API_URL}/api/v1/projects/${projectId}/plan/nodes/${nodeId}/preview.png?${query}`;
}

/** The URL of one page of a template, for the cover chooser. */
export function templatePageUrl(
  templateId: string,
  pageIndex: number,
  dpi = 90,
): string {
  return `${API_URL}/api/v1/templates/${templateId}/pages/${pageIndex}.png?dpi=${dpi}`;
}

export const api = {
  login: (email: string, password: string) =>
    request<TokenPair>("/api/v1/auth/login", {
      method: "POST",
      body: { email, password },
    }),
  me: () => request<UserOut>("/api/v1/auth/me"),

  categories: () => request<CategoryOut[]>("/api/v1/categories"),
  clients: () => request<ClientOut[]>("/api/v1/clients"),

  templates: (categoryId?: string) =>
    request<TemplateOut[]>(
      `/api/v1/templates${categoryId ? `?category_id=${categoryId}` : ""}`,
    ),
  template: (id: string) => request<TemplateDetail>(`/api/v1/templates/${id}`),
  publishTemplate: (id: string) =>
    request<TemplateOut>(`/api/v1/templates/${id}/publish`, { method: "POST" }),
  unpublishTemplate: (id: string) =>
    request<TemplateOut>(`/api/v1/templates/${id}/unpublish`, { method: "POST" }),
  uploadTemplate: (file: File, name: string, categoryId?: string) => {
    const form = new FormData();
    form.append("file", file);
    form.append("name", name);
    if (categoryId) form.append("category_id", categoryId);
    return request<TemplateIngestOut>("/api/v1/templates", {
      method: "POST",
      body: form,
    });
  },
  deleteTemplate: (id: string) =>
    request<void>(`/api/v1/templates/${id}`, { method: "DELETE" }),
  templateSuggestions: (id: string) =>
    request<SuggestionOut[]>(`/api/v1/templates/${id}/suggestions`),
  saveFields: (id: string, fields: TemplateFieldUpdate[]) =>
    request<TemplateDetail>(`/api/v1/templates/${id}/fields`, {
      method: "PUT",
      body: fields,
    }),
  saveSections: (id: string, sections: TemplateSectionUpdate[]) =>
    request<TemplateDetail>(`/api/v1/templates/${id}/sections`, {
      method: "PUT",
      body: sections,
    }),

  createClient: (body: {
    name: string;
    code: string;
    contact_email?: string | null;
    contact_phone?: string | null;
    user?: ClientUserCreate;
  }) => request<ClientOut>("/api/v1/clients", { method: "POST", body }),
  clientUsers: (id: string) =>
    request<UserOut[]>(`/api/v1/clients/${id}/users`),
  addClientUser: (id: string, body: ClientUserCreate) =>
    request<UserOut>(`/api/v1/clients/${id}/users`, { method: "POST", body }),
  resetPassword: (userId: string, password: string) =>
    request<UserOut>(`/api/v1/users/${userId}/password`, {
      method: "POST",
      body: { password },
    }),
  deleteUser: (userId: string) =>
    request<void>(`/api/v1/users/${userId}`, { method: "DELETE" }),
  updateClient: (id: string, body: Record<string, unknown>) =>
    request<ClientOut>(`/api/v1/clients/${id}`, { method: "POST", body }),
  deleteClient: (id: string) =>
    request<void>(`/api/v1/clients/${id}`, { method: "DELETE" }),

  createCategory: (body: {
    name: string;
    slug: string;
    description?: string | null;
  }) => request<CategoryOut>("/api/v1/categories", { method: "POST", body }),
  updateCategory: (id: string, body: Record<string, unknown>) =>
    request<CategoryOut>(`/api/v1/categories/${id}`, { method: "POST", body }),
  deleteCategory: (id: string) =>
    request<void>(`/api/v1/categories/${id}`, { method: "DELETE" }),

  projects: (params: Record<string, string> = {}) => {
    const query = new URLSearchParams(params).toString();
    return request<ProjectOut[]>(`/api/v1/projects${query ? `?${query}` : ""}`);
  },
  project: (id: string) => request<ProjectOut>(`/api/v1/projects/${id}`),
  createProject: (body: {
    name: string;
    template_id: string;
    client_id?: string;
    variant?: string;
    cover_page?: number;
    lot_count?: number;
  }) => request<ProjectOut>("/api/v1/projects", { method: "POST", body }),

  // ------------------------------------------------------------- the builder
  //
  // Every mutation returns the whole plan, so the builder never has to guess
  // what the server did — and carries the revision it was built on, so a
  // debounced value patch cannot quietly overwrite a reorder that landed first.
  plan: (id: string) => request<PagePlanOut>(`/api/v1/projects/${id}/plan`),
  addNode: (
    id: string,
    body: {
      kind: "page" | "lot";
      after?: string | null;
      page?: number;
      layout?: string;
      revision?: number;
    },
  ) =>
    request<PagePlanOut>(`/api/v1/projects/${id}/plan/nodes`, {
      method: "POST",
      body,
    }),
  duplicateNode: (id: string, node: string, revision: number) =>
    request<PagePlanOut>(
      `/api/v1/projects/${id}/plan/nodes/${node}/duplicate`,
      { method: "POST", body: { revision } },
    ),
  moveNode: (id: string, node: string, delta: number, revision: number) =>
    request<PagePlanOut>(`/api/v1/projects/${id}/plan/nodes/${node}/move`, {
      method: "POST",
      body: { delta, revision },
    }),
  deleteNode: (id: string, node: string) =>
    request<PagePlanOut>(`/api/v1/projects/${id}/plan/nodes/${node}`, {
      method: "DELETE",
    }),
  company: () => request<CompanyOut>("/api/v1/company"),
  // POST rather than PATCH, for the reason given on `updateProject` below.
  updateCompany: (name: string) =>
    request<CompanyOut>("/api/v1/company", { method: "POST", body: { name } }),
  uploadCompanyLogo: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<CompanyOut>("/api/v1/company/logo", {
      method: "POST",
      body: form,
    });
  },
  removeCompanyLogo: () =>
    request<CompanyOut>("/api/v1/company/logo", { method: "DELETE" }),
  setLeaseRows: (
    id: string,
    node: string,
    rows: Record<string, string>[],
    revision?: number,
  ) =>
    request<PagePlanOut>(`/api/v1/projects/${id}/plan/nodes/${node}/leases`, {
      method: "POST",
      body: { rows, revision },
    }),
  setNodeEnabled: (
    id: string,
    node: string,
    body: { on: boolean; revision?: number },
  ) =>
    request<PagePlanOut>(`/api/v1/projects/${id}/plan/nodes/${node}/enabled`, {
      method: "POST",
      body,
    }),
  setNodeLayout: (
    id: string,
    node: string,
    body: {
      layout?: string;
      options?: string[];
      /** Which alternative page — the summary table's colourway. */
      page?: number;
      revision?: number;
    },
  ) =>
    request<PagePlanOut>(`/api/v1/projects/${id}/plan/nodes/${node}/layout`, {
      method: "POST",
      body,
    }),
  patchNodeValues: (
    id: string,
    node: string,
    values: Record<string, unknown>,
    revision?: number,
  ) =>
    request<PagePlanOut>(`/api/v1/projects/${id}/plan/nodes/${node}/values`, {
      method: "POST",
      body: { values, revision },
    }),
  uploadNodePhoto: (id: string, node: string, fieldKey: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    form.append("field_key", fieldKey);
    return request<AssetOut>(
      `/api/v1/projects/${id}/plan/nodes/${node}/photo`,
      { method: "POST", body: form },
    );
  },
  // POST, not PATCH: some browsers refuse to send PATCH cross-origin even after
  // the preflight succeeds. The API accepts both on the same handler.
  updateProject: (id: string, body: Record<string, unknown>) =>
    request<ProjectOut>(`/api/v1/projects/${id}`, { method: "POST", body }),

  uploadDataSource: (id: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<UploadResult>(`/api/v1/projects/${id}/datasource`, {
      method: "POST",
      body: form,
    });
  },
  datasource: (id: string) =>
    request<DataSourceOut | null>(`/api/v1/projects/${id}/datasource`),
  mapping: (id: string) => request<MappingOut>(`/api/v1/projects/${id}/mapping`),
  saveMapping: (id: string, body: MappingSave) =>
    request<MappingOut>(`/api/v1/projects/${id}/mapping`, { method: "PUT", body }),

  records: (id: string) => request<RecordOut[]>(`/api/v1/projects/${id}/records`),
  saveRecords: (id: string, records: { values: Record<string, unknown> }[]) =>
    request<RecordOut[]>(`/api/v1/projects/${id}/records`, {
      method: "PUT",
      body: { records },
    }),

  photos: (id: string) =>
    request<RecordPhotosOut>(`/api/v1/projects/${id}/photos`),
  patchRecord: (id: string, rowIndex: number, values: Record<string, unknown>) =>
    request<RecordOut>(`/api/v1/projects/${id}/records/${rowIndex}`, {
      method: "POST",
      body: { values },
    }),

  preflight: (id: string) =>
    request<PreflightOut>(`/api/v1/projects/${id}/preflight`),
  generate: (id: string) =>
    request<JobOut>(`/api/v1/projects/${id}/generate`, { method: "POST" }),

  job: (id: string) => request<JobDetail>(`/api/v1/jobs/${id}`),
  jobs: (params: Record<string, string> = {}) => {
    const query = new URLSearchParams(params).toString();
    return request<JobDetail[]>(`/api/v1/jobs${query ? `?${query}` : ""}`);
  },
  jobResults: (id: string, only?: "rejected") =>
    request<ResultOut[]>(
      `/api/v1/jobs/${id}/results${only ? `?only=${only}` : ""}`,
    ),
  cancelJob: (id: string) =>
    request<JobOut>(`/api/v1/jobs/${id}/cancel`, { method: "POST" }),
  pauseJob: (id: string) =>
    request<JobOut>(`/api/v1/jobs/${id}/pause`, { method: "POST" }),
  resumeJob: (id: string) =>
    request<JobOut>(`/api/v1/jobs/${id}/resume`, { method: "POST" }),
  retryJob: (id: string, rows?: number[]) =>
    request<JobOut>(`/api/v1/jobs/${id}/retry`, {
      method: "POST",
      body: { rows: rows ?? null },
    }),

  assets: () => request<AssetOut[]>("/api/v1/assets"),
  uploadAsset: (file: File, role = "extra") => {
    const form = new FormData();
    form.append("file", file);
    form.append("role", role);
    return request<AssetOut>("/api/v1/assets", { method: "POST", body: form });
  },
  deleteAsset: (id: string) =>
    request<void>(`/api/v1/assets/${id}`, { method: "DELETE" }),

  dashboard: () => request<DashboardOut>("/api/v1/dashboard"),
  opsSummary: () => request<Record<string, number>>("/api/v1/ops/summary"),
};

/**
 * Authenticated download: fetch as a blob, then hand it to the browser.
 *
 * Throws {@link ApiError} on failure — a job whose output has been cleaned up
 * answers 410, and callers must show that rather than let it escape as an
 * unhandled rejection. Use {@link tryDownload} unless you handle it yourself.
 */
export async function download(path: string, fallbackName: string): Promise<void> {
  const response = await fetch(`${API_URL}${path}`, {
    headers: { Authorization: `Bearer ${tokens.access() ?? ""}` },
  });
  if (!response.ok) throw new ApiError(response.status, await readError(response));

  const disposition = response.headers.get("content-disposition") ?? "";
  const encoded = /filename\*=UTF-8''([^;]+)/i.exec(disposition)?.[1];
  const plain = /filename="([^"]+)"/i.exec(disposition)?.[1];
  const name = encoded ? decodeURIComponent(encoded) : (plain ?? fallbackName);

  const url = URL.createObjectURL(await response.blob());
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = name;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

/**
 * {@link download} with the failure turned into a message.
 *
 * Returns null on success, or the reason the file could not be fetched.
 */
export async function tryDownload(
  path: string,
  fallbackName: string,
): Promise<string | null> {
  try {
    await download(path, fallbackName);
    return null;
  } catch (caught) {
    if (caught instanceof ApiError) return caught.message;
    return "تعذّر الاتصال بالخادم أثناء التنزيل.";
  }
}
