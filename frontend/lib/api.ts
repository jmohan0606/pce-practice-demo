/** Typed fetch wrappers for the PCE backend (FastAPI, default http://localhost:8001).
 *
 * B2/B3 endpoints (documents, rules) are built in parallel — callers must treat
 * ApiError (incl. 404 while those land) as an empty/graceful state, never a crash.
 */

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ||
  process.env.NEXT_PUBLIC_API_BASE_URL ||
  "http://localhost:8001";

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

export async function uploadDocuments(
  files: File[],
  documentType: "PLAN" | "GUIDANCE" = "PLAN",
): Promise<DocumentsResponse> {
  const form = new FormData();
  for (const file of files) form.append("files", file);
  form.append("document_type", documentType);
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

// 4.6: rules are immutable — edit creates a new DRAFT row; approve + publish
// mint the next version. The original version is never mutated.
export interface RuleDetail extends Rule {
  rule_key?: string;
  compiled?: boolean;
  compile_error?: string | null;
  plan?: unknown;
  document_id?: string | null;
}
export function getRulesDetailed(version: string): Promise<{ version: RuleVersion | null; rules: RuleDetail[] }> {
  return get(`/api/rules?version=${encodeURIComponent(version)}`);
}
export function editRule(ruleKey: string, changes: Record<string, unknown>): Promise<{ rule: RuleDetail; note?: string }> {
  return post(`/api/rules/${encodeURIComponent(ruleKey)}/edit`, { changes });
}
export function approveRule(ruleKey: string, approvedBy: string = "operator"): Promise<{ rule: RuleDetail }> {
  return post(`/api/rules/${encodeURIComponent(ruleKey)}/approve`, { approved_by: approvedBy });
}
export function publishRules(approvedBy: string = "operator", notes: string = ""): Promise<{ version: RuleVersion }> {
  return post("/api/rules/publish", { approved_by: approvedBy, notes });
}

// ---------- C4 insights (shapes per ROUND_C_SPEC) ----------

export interface Finding {
  finding_id?: string;
  title: string;
  summary: string;
  impact_amt: number | null;
  driver_tag: string;
  group_id?: string | null;
  rule_key?: string | null;
  provenance: "REAL" | "DERIVED";
  confidence?: number;
  evidence_columns: string[];
  evidence_rows: Record<string, unknown>[];
  evidence_total: number;
  evidence_reason?: string | null;
  source_query?: { query_name: string; params: Record<string, unknown> } | null;
  rule_citation?: {
    rule_key: string;
    rule_code?: string;
    rule_name?: string;
    citation?: RuleCitation | null;
  } | null;
}
export interface InsightRun {
  run_id: string;
  advisor_sid: string;
  from_month_id: string;
  to_month_id: string;
  version_id: string;
  status: string; // RUNNING | COMPLETE | FAILED
  narrative: string;
  bullets: string[];
  findings: Finding[];
  generated_at: string;
  query_count: number;
  budget_hit: boolean;
  generation: number;
  error?: string | null;
}
export interface GenerateResponse {
  job_id: string;
  run_count: number;
}
export interface JobStatus {
  status: "running" | "complete" | "failed";
  completed: number;
  total: number;
  current: string | null;
  runs: { run_id: string | null; advisor_sid: string; status: string; finding_count: number; error?: string | null }[];
}

async function post<T>(path: string, body: unknown): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, `API unreachable at ${API_BASE}`);
  }
  if (!response.ok) throw new ApiError(response.status, `${response.status} for ${path}`);
  return (await response.json()) as T;
}

export function generateInsights(advisor: string, fromMonth: string, toMonth: string, versionId?: string): Promise<GenerateResponse> {
  return post("/api/insights/generate", {
    advisor,
    from_month: fromMonth,
    to_month: toMonth,
    version_id: versionId ?? null,
  });
}
export function getInsightStatus(jobId: string): Promise<JobStatus> {
  return get(`/api/insights/status/${encodeURIComponent(jobId)}`);
}
export function getInsights(advisor: string, fromMonth: string, toMonth: string, version: string = "latest"): Promise<InsightRun> {
  return get(`/api/insights/${encodeURIComponent(advisor)}/${fromMonth}/${toMonth}?version=${encodeURIComponent(version)}`);
}

export interface PeerRank {
  advisor_sid: string;
  month_id: string;
  metric: string;
  rank: number | null;
  cohort_size: number;
  cohort_median: number | null;
}
export function getPeerRank(advisor: string, monthId: string): Promise<PeerRank> {
  return get(`/api/insights/peer-rank?advisor=${encodeURIComponent(advisor)}&month_id=${monthId}`);
}

// ---------- Cost & Trace (cost-fix session task 3) ----------

export interface TraceTotals {
  turns: number;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  cache_write_tokens: number;
  cache_hit_pct: number;
  est_cost_usd: number;
}
export interface TraceRun extends TraceTotals {
  run_id: string;
  kind: string; // insight_run | document_extraction | conflict_audit | other
  advisor_sid: string | null;
  transition: string | null;
  version_id: string | null;
  status: string;
  query_count: number;
  wall_ms: number;
  budget_hit: boolean;
  budget_hit_tokens: boolean;
  started_at: string | null;
}
export interface TraceTurn {
  seq_no: number;
  agent_name: string;
  action_kind: string;
  query_name: string;
  model: string;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  cache_write_tokens: number;
  latency_ms: number;
  est_cost_usd: number;
}
export interface TraceRunDetail extends TraceRun {
  turn_rows: TraceTurn[];
}
export interface TraceSummary {
  per_advisor: ({ advisor_sid: string } & TraceTotals)[];
  document_extraction: TraceTotals;
  conflict_audit: TraceTotals;
  full_refresh: { run_count: number | null; est_cost_usd: number | null; est_minutes: number | null };
  projection: { history_runs: number; avg_run_cost_usd: number | null; avg_run_wall_ms: number | null };
}
export function getTraceRuns(): Promise<{ runs: TraceRun[] }> {
  return get("/api/trace/runs");
}
export function getTraceRunDetail(runId: string): Promise<TraceRunDetail> {
  return get(`/api/trace/runs/${encodeURIComponent(runId)}`);
}
export function getTraceSummary(): Promise<TraceSummary> {
  return get("/api/trace/summary");
}
