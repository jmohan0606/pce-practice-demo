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
    ncf: { net_flows: number; inflows: number; outflows: number; credited_flows: number } | null;
    nnm: NnmBlock;
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

// ----------------------------------------------------------- opportunities

export interface OpportunityRow {
  advisor_sid: string;
  stage: string;
  status: string;
  total_amount: number;
  opportunity_count: number;
  data_source: string; // 'DUMMY' until the CRM feed arrives
}
export interface OpportunitiesResponse {
  advisor_sid: string;
  by_status: Record<string, OpportunityRow[]>;
  other: OpportunityRow[];
  total_count: number;
  data_source: string;
  guidance: CoachCitation | null;
}
export function getOpportunities(
  sid: string,
  from?: string,
  to?: string,
): Promise<OpportunitiesResponse> {
  const suffix = from && to ? `?from=${from}&to=${to}` : "";
  return request(`/api/advisor/${encodeURIComponent(sid)}/opportunities${suffix}`);
}
