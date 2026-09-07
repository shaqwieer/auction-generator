/** Response shapes mirrored from `backend/app/schemas`. */

export type Role = "admin" | "operator" | "client";

export type ProjectStatus =
  | "draft"
  | "mapping"
  | "queued"
  | "generating"
  | "ready"
  | "failed";

export type JobStatus =
  | "queued"
  | "running"
  | "paused"
  | "succeeded"
  | "failed"
  | "cancelled";

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: "bearer";
  expires_in: number;
}

/** The company a client prints for — its name and mark go on every booklet. */
export interface CompanyOut {
  id: string;
  name: string;
  code: string;
  logo_filename: string | null;
}

export interface UserOut {
  id: string;
  email: string;
  name: string;
  role: Role;
  is_active: boolean;
  client_id: string | null;
  company: CompanyOut | null;
}

export interface CategoryOut {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  template_count: number;
}

export interface ClientOut {
  id: string;
  name: string;
  code: string;
  contact_email: string | null;
  contact_phone: string | null;
  is_active: boolean;
  project_count: number;
  user_count: number;
}

export interface ClientUserCreate {
  name: string;
  email: string;
  password: string;
  role?: "client" | "operator";
}

export interface TemplateOut {
  id: string;
  slug: string;
  name: string;
  code: string;
  status: string;
  version: number;
  page_width: number;
  page_height: number;
  page_count: number;
  category_id: string | null;
  fonts: string[];
  field_count: number;
}

export interface TableColumnSpec {
  key: string;
  label: string;
  rect: { x: number; y: number; w: number; h: number };
  align: string;
  font_family: string;
  font_weight: string;
  font_size_pt: number;
  color: string;
  fit: string;
  source: string;
}

export interface TableSpec {
  rows: number;
  row_pitch: number;
  row_offset: number;
  columns: TableColumnSpec[];
}

/**
 * Saving fields is a full replace, so every property the editor writes back
 * through TemplateFieldUpdate has to be readable here too -- otherwise the
 * editor invents a default for it and the next save quietly discards what the
 * build measured (valign, line height, calibration offsets).
 */
export interface TemplateFieldOut {
  id: string;
  key: string;
  label: string;
  page_index: number;
  type: "text" | "image" | "qr" | "barcode" | "link" | "table";
  x: number;
  y: number;
  w: number;
  h: number;
  align: string;
  valign: string | null;
  rotation: number;
  font_family: string;
  font_weight: string;
  font_size_pt: number;
  color: string;
  line_height: number;
  fit: string;
  min_scale: number;
  calibration_dx: number;
  calibration_dy: number;
  is_required: boolean;
  rtl: boolean;
  origin: string;
  table_spec: TableSpec | null;
}

export interface TemplateSectionOut {
  id: string;
  name: string;
  kind: "fixed" | "per_record" | "table";
  first_page: number;
  last_page: number;
  pages_per_item: number;
  rows_per_page: number;
  variant: string | null;
}

/**
 * What one page of the template is, so the builder can offer it.
 *
 * `slot` groups alternatives — the eight cover designs, the two lot layouts —
 * so a chooser can be rendered without knowing anything about this booklet.
 */
export interface TemplatePageOut {
  id: string;
  page_index: number;
  role: string;
  slot: string;
  layout: string;
  name: string;
  is_optional: boolean;
  default_on: boolean;
  options: Record<string, unknown>;
  position: number;
}

/** One node of a booklet plan: an output page, a property's pages, or the table. */
export interface PagePlanNode {
  id: string;
  kind: "page" | "lot" | "table";
  page?: number | null;
  row?: number | null;
  layout?: string | null;
  pages: number[];
  options: string[];
  slot?: string | null;
  rows_per_page?: number | null;
  /** Switched out of this issue. Keeps its place and everything typed on it. */
  off?: boolean;
  values: Record<string, unknown>;
}

export interface PagePlanOut {
  revision: number;
  nodes: PagePlanNode[];
  pages: TemplatePageOut[];
  fields_by_page: Record<string, TemplateFieldOut[]>;
  record_keys: string[];
  predicted_pages: number;
}

export interface TemplateDetail extends TemplateOut {
  sections: TemplateSectionOut[];
  pages: TemplatePageOut[];
  fields: TemplateFieldOut[];
  record_keys: string[];
  static_keys: string[];
  required_keys: string[];
}

export interface TemplateSectionUpdate {
  name: string;
  kind: "fixed" | "per_record" | "table";
  first_page: number;
  last_page: number;
  pages_per_item: number;
  rows_per_page: number;
  variant: string | null;
}

export interface TemplateFieldUpdate {
  key: string;
  label: string;
  page_index: number;
  type: TemplateFieldOut["type"];
  x: number;
  y: number;
  w: number;
  h: number;
  align: string;
  valign: string | null;
  rotation: number;
  font_family: string;
  font_weight: string;
  font_size_pt: number;
  color: string;
  line_height: number;
  fit: string;
  min_scale: number;
  calibration_dx: number;
  calibration_dy: number;
  is_required: boolean;
  rtl: boolean;
  table_spec: TableSpec | null;
}

export interface TemplateIngestOut {
  template: TemplateDetail;
  pages: number;
  proposed_fields: number;
  auto_named: number;
  tables: number;
}

export interface SuggestionOut {
  page_index: number;
  type: TemplateFieldOut["type"];
  x: number;
  y: number;
  w: number;
  h: number;
  align: string;
  rotation: number;
  font_family: string;
  font_weight: string;
  font_size_pt: number;
  color: string;
  sample_text: string;
}

export interface ProjectOut {
  id: string;
  name: string;
  status: ProjectStatus;
  client_id: string;
  template_id: string;
  variant: string | null;
  static_values: Record<string, unknown>;
  output_mode: "merged" | "per_record";
  add_bleed: boolean;
  convert_cmyk: boolean;
  record_count: number;
  /** "print" — link chips print a code; "electronic" — they are clickable. */
  output_flavour: "print" | "electronic";
  /** Which colour the booklet's lease tables print in. */
  lease_colourway: "blue" | "green";
  updated_at: string;
  template_name: string | null;
  category_name: string | null;
  has_plan: boolean;
}

export interface ColumnOut {
  index: number;
  name: string;
  letter: string;
  sample: string;
  kind: string;
  tag: string;
  non_empty: number;
}

export interface DataSourceOut {
  id: string;
  kind: string;
  filename: string;
  sheet: string;
  row_count: number;
  columns: ColumnOut[];
  warnings: string[];
}

export interface UploadResult {
  data_source: DataSourceOut;
  preview: Record<string, string>[];
  suggested_mapping: Record<string, string | null>;
}

export interface MappingEntry {
  field_key: string;
  column: string | null;
  static_value: string | null;
}

export interface MappingProblem {
  field_key: string;
  message: string;
  severity: "error" | "warning";
}

export interface MappingOut {
  entries: MappingEntry[];
  problems: MappingProblem[];
  record_keys: string[];
  required_keys: string[];
}

export interface MappingSave {
  entries: MappingEntry[];
}

export interface RecordOut {
  id: string;
  row_index: number;
  values: Record<string, unknown>;
  source: string;
}

export interface ImageFieldOut {
  key: string;
  label: string;
  scope: "record" | "project";
  is_required: boolean;
}

export interface RecordPhotosOut {
  fields: ImageFieldOut[];
  records: RecordOut[];
  static_values: Record<string, unknown>;
}

export interface PreflightOut {
  record_count: number;
  /** "print" — link chips print a code; "electronic" — they are clickable. */
  output_flavour: "print" | "electronic";
  /** Which colour the booklet's lease tables print in. */
  lease_colourway: "blue" | "green";
  generatable: number;
  predicted_pages: number;
  rejected: Record<string, string[]>;
  missing_assets: string[];
}

export interface JobOut {
  id: string;
  project_id: string;
  status: JobStatus;
  engine: string;
  total_records: number;
  completed_records: number;
  rejected_records: number;
  page_count: number;
  progress: number;
  started_at: string | null;
  finished_at: string | null;
  error_summary: string | null;
  output_filename: string | null;
  output_bytes: number;
  created_at: string;
}

export interface JobDetail extends JobOut {
  log: { at: string; level: string; message: string }[];
  project_name: string | null;
  client_name: string | null;
}

export interface ResultOut {
  row_index: number;
  status: string;
  field_key: string | null;
  cause: string | null;
  severity: "error" | "warning";
}

export interface AssetOut {
  id: string;
  filename: string;
  content_type: string;
  width: number;
  height: number;
  size_bytes: number;
  role: string;
  created_at: string;
  print_dpi_a4: number;
  below_min_dpi: boolean;
}

export interface StatOut {
  label: string;
  value: string;
  delta: string | null;
}

export interface DashboardOut {
  stats: StatOut[];
  running_jobs: JobOut[];
  recent_jobs: JobOut[];
  usage: { day: string; pages: number }[];
}
