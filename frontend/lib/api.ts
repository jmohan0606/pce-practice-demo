/** Typed fetch wrappers for the PCE backend (FastAPI, default http://localhost:8001).
 *
 * B2/B3 endpoints (documents, rules) are built in parallel — callers must treat
 * ApiError (incl. 404 while those land) as an empty/graceful state, never a crash.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8001";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

async function get<T>(path: string): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
  } catch {
    throw new ApiError(0, `API unreachable at ${API_BASE}`);
  }
  if (!response.ok) throw new ApiError(response.status, `${response.status} for ${path}`);
  return (await response.json()) as T;
}

// ---------- B1 dashboard ----------

export interface Advisor {
  advisor_sid: string;
  advisor_name: string; // may be "" — show the SID, never invent a name
  in_cohort: boolean;
}
export interface AdvisorsResponse {
  advisors: Advisor[];
  cohort_count: number;
}

export interface MonthRow {
  month_id: string;
  month_name: string;
  credited_amt: number;
  recurring_amt: number;
  non_recurring_amt: number;
  txn_count: number;
  trading_days: number;
  is_baseline: boolean;
  is_partial: boolean;
}
export interface MonthsResponse {
  months: MonthRow[];
}

export interface Transition {
  from_month_id: string;
  to_month_id: string;
  from_amt: number;
  to_amt: number;
  change_amt: number;
  change_pct: number | null;
  direction: "up" | "down";
  txn_count: number;
}
export interface TransitionsResponse {
  transitions: Transition[];
}

export interface ContributionRow {
  group_id: string;
  group_name: string;
  display_prefix: string;
  from_amt: number;
  to_amt: number;
  change_amt: number;
  change_pct: number | null;
  share_pct: number;
  direction: "up" | "down";
}
export interface ContributionTotal {
  from_amt: number;
  to_amt: number;
  change_amt: number;
  change_pct: number | null;
  share_pct: number;
}
export interface ContributionSection {
  class_id: string;
  class_name: string;
  rows: ContributionRow[];
  subtotal: ContributionTotal;
}
export interface ProductContribution {
  from_month_id: string;
  to_month_id: string;
  sections: ContributionSection[];
  total: ContributionTotal;
}

export type ClassFilter = "all" | "RECURRING" | "NON_RECURRING";

export function getAdvisors(): Promise<AdvisorsResponse> {
  return get("/api/advisors");
}
export function getMonths(advisor: string = "all"): Promise<MonthsResponse> {
  return get(`/api/months?advisor=${encodeURIComponent(advisor)}`);
}
export function getTransitions(advisor: string = "all"): Promise<TransitionsResponse> {
  return get(`/api/transitions?advisor=${encodeURIComponent(advisor)}`);
}
export function getProductContribution(
  from: string,
  to: string,
  advisor: string = "all",
  classFilter: ClassFilter = "all",
): Promise<ProductContribution> {
  const params = new URLSearchParams({ from, to, advisor, class: classFilter });
  return get(`/api/product-contribution?${params.toString()}`);
}

// ---------- health (top-bar pill) ----------

export interface HealthResponse {
  healthy: boolean;
  graph?: { mode?: string; tier?: number | null; healthy?: boolean };
}
export function getHealth(): Promise<HealthResponse> {
  return get("/api/health");
}

// ---------- B2 documents (built in parallel — shapes per ROUND_B_SPEC B2.4) ----------

export interface DocumentInfo {
  document_id: string;
  document_name: string;
  page_count?: number;
  chunk_count?: number;
  table_chunk_count?: number;
  status?: string; // uploaded | parsed | chunked | embedded | indexed | failed
  rule_count?: number;
}
export interface DocumentsResponse {
  documents: DocumentInfo[];
}
export function getDocuments(): Promise<DocumentsResponse> {
  return get("/api/documents");
}

export async function uploadDocuments(files: File[]): Promise<DocumentsResponse> {
  const form = new FormData();
  for (const file of files) form.append("files", file);
  let response: Response;
  try {
    response = await fetch(`${API_BASE}/api/documents/upload`, { method: "POST", body: form });
  } catch {
    throw new ApiError(0, `API unreachable at ${API_BASE}`);
  }
  if (!response.ok) throw new ApiError(response.status, `${response.status} for /api/documents/upload`);
  return (await response.json()) as DocumentsResponse;
}

// ---------- B3 rules (built in parallel — shapes per ROUND_B_SPEC B3) ----------

export interface RuleCitation {
  chunk_id?: string;
  page_no?: number;
  section_path?: string;
  excerpt?: string;
  document_name?: string;
}
export interface Rule {
  rule_code: string;
  rule_name: string;
  plain_description?: string;
  worked_example?: string | null;
  grain?: string;
  population?: string;
  compute?: string;
  trigger?: string;
  attribute?: string;
  driver_tag?: string;
  provenance?: string; // DOCUMENT_DERIVED | OPERATOR_SPECIFIED
  confidence?: number;
  citations?: RuleCitation[];
  status?: string; // DRAFT | PUBLISHED | SUPERSEDED | NEEDS_INPUT | REJECTED
  unclear_notes?: string | null;
}
export interface RulesResponse {
  rules: Rule[];
  version?: RuleVersion;
}
export interface RuleVersion {
  version_id?: string;
  version_no: number;
  status?: string; // PUBLISHED | SUPERSEDED
  published_at?: string;
  created_at?: string;
  rule_count?: number;
  document_count?: number;
  approved_by?: string;
  notes?: string;
  insight_count?: number;
}
export interface RuleVersionsResponse {
  versions: RuleVersion[];
}
export function getRules(version: string = "latest"): Promise<RulesResponse> {
  return get(`/api/rules?version=${encodeURIComponent(version)}`);
}
export function getRuleVersions(): Promise<RuleVersionsResponse> {
  return get("/api/rules/versions");
}
