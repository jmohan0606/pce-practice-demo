/** Round A2B task 6 — advisor-page API client (Subagent C's surface; lib/api.ts
 * is owned elsewhere and never edited from here). */

import { ApiError } from "@/lib/api";

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ||
  process.env.NEXT_PUBLIC_API_BASE_URL ||
  "http://localhost:8002";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, { cache: "no-store", ...init });
  } catch {
    throw new ApiError(0, `API unreachable at ${API_BASE}`);
  }
  if (!response.ok) {
    let detail = `${response.status} for ${path}`;
    try {
      const body = await response.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      /* keep default */
    }
    throw new ApiError(response.status, detail);
  }
  return (await response.json()) as T;
}

// ---------------------------------------------------------------- advisors

export interface AdvisorListRow {
  advisor_sid: string;
  advisor_name: string;
  rep_code: string;
  in_cohort: boolean;
  /** Round 7 task 10 — the cascading filter's data (client req of 17 Aug).
   * job_display_name is the client mapping's name; blank stays blank. */
  job_code?: string;
  job_display_name?: string;
  work_state?: string;
  work_city?: string;
  is_synthetic?: boolean;
}
export function getAdvisorList(): Promise<{ advisors: AdvisorListRow[]; cohort_count: number }> {
  return request("/api/advisor/list");
}

// ----------------------------------------------------------------- summary

export interface AdvisorTeam {
  is_team: boolean;
  team_rep_cd: string | null;
  agreements: { agreement_id: string; share_pct: number; status: string }[];
}
/** Legacy A2B flows-based NNM block — replaced by GET /{sid}/nnm (Round F2);
 * kept optional so an older backend payload still type-checks. */
export interface NnmBlock {
  ytd: { amount: number; first_month: string | null; label: string };
  in_scope: { amount: number; from: string; to: string; label: string };
  by_product: { flow_product_cd: string; flow_product_desc: string; net_flows: number }[];
  categories_note: string;
  qualification_note: string;
}
export interface AdvisorSummary {
  advisor: AdvisorListRow;
  team: AdvisorTeam;
  from: string;
  to: string;
  /** month_id -> AUM; null when the advisor holds no account rows that month. */
  aum_by_month: Record<string, number | null>;
  metrics: {
    lifecycle: { new_count: number; lost_count: number; retained_count: number; notes: string };
    aum: { total_balance: number; prior_balance: number | null; change_amt: number | null } | null;
    /** Round 3 review B1/D2 — AUM scoped to Managed Accounts only (null when
     * the advisor holds no managed account rows). The tile renders THIS. */
    aum_managed?: {
      total_balance: number;
      prior_balance: number | null;
      change_amt: number | null;
    } | null;
    ncf: { net_flows: number; inflows: number; outflows: number; credited_flows: number } | null;
    nnm?: NnmBlock;
    trades: { from_count: number; to_count: number; delta: number };
  };
}
export function getAdvisorSummary(sid: string, from: string, to: string): Promise<AdvisorSummary> {
  return request(`/api/advisor/${encodeURIComponent(sid)}/summary?from=${from}&to=${to}`);
}

// ------------------------------------------------------------ peer ranking

export interface RankBlock {
  rank: number | null;
  cohort_size: number;
  value: number | null;
  cohort_median: number | null;
  note?: string;
}
export interface AdvisorPeerRanking {
  advisor_sid: string;
  from: string;
  to: string;
  revenue: RankBlock;
  growth: RankBlock;
  discount_rate: RankBlock;
}
export function getAdvisorPeerRanking(
  sid: string,
  from: string,
  to: string,
): Promise<AdvisorPeerRanking> {
  return request(`/api/advisor/${encodeURIComponent(sid)}/peer-ranking?from=${from}&to=${to}`);
}

// ---------------------------------------------------------------- coaching

export interface CoachCitation {
  document_id: string | null;
  document_name: string | null;
  chunk_id: string | null;
  page_no: number | null;
  section_path: string | null;
  excerpt: string | null;
}
export interface CoachingPoint {
  text: string;
  fact: string;
  implication: string;
  citation: CoachCitation;
  facts: Record<string, unknown>;
  /** Round 3 review B7 — same severity model as rules/exceptions; the list
   * arrives sorted Critical → Info. Older stored runs may lack these. */
  severity?: string | null;
  severity_basis?: string | null;
}
export interface CoachingResult {
  generated?: boolean;
  advisor_sid: string;
  from_month: string;
  to_month: string;
  run_id?: string;
  generated_at?: string;
  points: CoachingPoint[];
  dropped?: { point: string; reason: string }[];
  limits?: { limit_name: string; limit_value: number | null; limit_effect: string }[];
  opportunities_guidance?: CoachCitation | null;
  note?: string | null;
}
export function getCoaching(sid: string, from: string, to: string): Promise<CoachingResult> {
  return request(`/api/advisor/${encodeURIComponent(sid)}/coaching?from=${from}&to=${to}`);
}
export function generateCoaching(sid: string, from: string, to: string): Promise<CoachingResult> {
  return request(`/api/advisor/${encodeURIComponent(sid)}/coaching/generate?from=${from}&to=${to}`, {
    method: "POST",
  });
}

// ------------------------------------------------------------- NNM (Round F2)

export interface NnmCategory {
  category: "EC" | "NB" | "YI" | "FS" | string;
  label: string;
  /** Raw source-file prefix, e.g. "ECNNM" — only EC is plan-confirmed. */
  category_source: string;
  confirmed: boolean;
  latest_month: string;
  mtd_nnm: number;
  ytd_nnm: number;
}
export interface NnmThreshold {
  available: boolean;
  /** Resolved from the EXTRACTED plan rule at read time — never a constant. */
  threshold_amt: number | null;
  rule_key: string | null;
  measured_category: string;
  assumed: boolean;
  assumed_note: string;
  ytd_nnm: number | null;
  gap: number | null;
  qualifies: boolean | null;
  as_of_month: string | null;
  note: string | null;
}
export interface NnmResponse {
  advisor_sid: string;
  as_of_month: string;
  as_of_label: string;
  as_of_dt: string;
  categories: NnmCategory[];
  total: { mtd_nnm: number; ytd_nnm: number };
  threshold: NnmThreshold;
  note?: string | null;
}
export function getAdvisorNnm(sid: string): Promise<NnmResponse> {
  return request(`/api/advisor/${encodeURIComponent(sid)}/nnm`);
}

// ----------------------------------------------- opportunities (Round F2 CRM)

export interface OpportunityStageGroupRow {
  stage_group: "EARLY" | "MID" | "LATE" | "CLOSING" | string;
  opportunity_count: number;
  forecast_amount: number;
  actual_assets: number;
  stalled_count: number;
}
export interface OpportunityDetailRow {
  opportunity_id: string;
  eci_id: string;
  stage_name: string;
  stage_group: string;
  /** Forecast pipeline value (working interpretation — see assumption_note). */
  amount: number;
  /** Assets that landed (working interpretation — never summed with amount). */
  actual_assets: number;
  days_to_close: number | null;
  is_stalled: boolean;
  date_of_last_contact: string | null;
  comments: string;
  /** AI interpretation of comments — descriptive ONLY, never drives a figure. */
  ai_read: string;
  ai_read_confidence: number | null;
  ai_read_evidence: string;
  advisor_valid: boolean;
  account_record_type: string;
  data_source: string;
}
export interface OpportunitiesResponse {
  advisor_sid: string;
  by_stage_group: OpportunityStageGroupRow[];
  opportunities: OpportunityDetailRow[];
  data_quality: { invalid_advisor_rows: number; note?: string | null };
  assumption_note: string;
  won_lost_note: string;
  opportunities_guidance?: CoachCitation | null;
  guidance?: CoachCitation | null;
}
export function getOpportunities(
  sid: string,
  from?: string,
  to?: string,
): Promise<OpportunitiesResponse> {
  const suffix = from && to ? `?from=${from}&to=${to}` : "";
  return request(`/api/advisor/${encodeURIComponent(sid)}/opportunities${suffix}`);
}
