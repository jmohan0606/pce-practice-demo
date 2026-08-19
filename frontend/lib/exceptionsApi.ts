/** Round 3 Task 10 (review batch 1 §H + spec Task 3.2) — API clients for the
 * dashboard Exceptions section.
 *
 * lib/api.ts does not export its base URL or `get` helper (and is not owned
 * by this round's dashboard subagent), so the base-URL logic is mirrored
 * here — same env vars, same default.
 *
 * Clients:
 *   - getExceptionsWorklist  — GET /api/insights/exceptions (severity +
 *     advisor filters; H2/H3: the default one-advisor view passes `advisor`
 *     so the expensive full query runs only on demand)
 *   - getExceptionAdvisors   — GET /api/insights/exceptions/advisors (H4:
 *     only advisors that actually HAVE exceptions on the transition)
 *   - getFirmExceptions      — GET /api/exceptions/firm (Task 3.2: one row
 *     per RULE — the firm altitude)
 *   - getRuleExceptions      — GET /api/exceptions/rule/{rule_key} (the
 *     advisor ranking for one rule, ranked by RATE)
 */

import { ApiError, type ExceptionsResponse, type ExceptionRow } from "@/lib/api";

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ||
  process.env.NEXT_PUBLIC_API_BASE_URL ||
  "http://localhost:8002";

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

// ---------------------------------------------------------------- worklist

export type Severity = "CRITICAL" | "HIGH" | "MODERATE" | "LOW" | "INFO";

/** The row the backend actually serves (ExceptionRow + Round A1 fields). */
export interface ExceptionRowFull extends ExceptionRow {
  severity: Severity;
  source_kind: "rule" | "observation";
}
export interface ExceptionsResponseFull extends ExceptionsResponse {
  exceptions: ExceptionRowFull[];
}

export function getExceptionsWorklist(
  fromMonth: string,
  toMonth: string,
  options: { severity?: string; advisor?: string } = {},
): Promise<ExceptionsResponseFull> {
  const params = new URLSearchParams({ from_month: fromMonth, to_month: toMonth });
  if (options.severity) params.set("severity", options.severity);
  if (options.advisor) params.set("advisor", options.advisor);
  return get(`/api/insights/exceptions?${params.toString()}`);
}

// ---------------------------------------------------------------- advisors with exceptions (H4)

export interface ExceptionAdvisor {
  advisor_sid: string;
  advisor_name: string;
  exception_count: number;
}
export interface ExceptionAdvisorsResponse {
  from_month_id: string;
  to_month_id: string;
  advisors: ExceptionAdvisor[];
}

export function getExceptionAdvisors(
  fromMonth: string,
  toMonth: string,
): Promise<ExceptionAdvisorsResponse> {
  return get(`/api/insights/exceptions/advisors?from_month=${fromMonth}&to_month=${toMonth}`);
}

// ---------------------------------------------------------------- firm altitude (Task 3.2)

export interface FirmExceptionConfig {
  exception_denominator?: string | null;
  denominator_label: string;
  denominator_kind?: string;
  product_scope?: string | null;
  product_scope_applied: string;
  exception_floor?: number | string | null;
  exception_floor_unit?: string | null;
  exception_sensitivity?: number | null;
  sensitivity_applied?: number;
  sensitivity_default_used?: boolean;
}
export interface FirmExceptionCohort {
  median_pct: number | null;
  stdev_pct?: number;
  flag_threshold_pct: number | null;
  in_scope_advisors: number;
}
export interface FirmExceptionRollup {
  affected: number;
  denominator: number;
  rate_pct: number | null;
  advisors_in_scope?: number;
  advisors_flagged: number;
  advisors_with_exceptions: number;
  impact_amt: number | null;
}
export interface FirmExceptionRule {
  rule_key: string;
  rule_code: string;
  rule_name: string;
  severity: string | null;
  config: FirmExceptionConfig & {
    /** Round 8 — absolute-threshold rules only */
    threshold?: number | null;
    threshold_op?: string | null;
  };
  cohort: FirmExceptionCohort;
  firm: FirmExceptionRollup & {
    /** Round 8 — absolute-threshold rules only */
    observed_value?: number | null;
    threshold?: number | null;
    fired?: boolean;
    is_monetary?: boolean;
    error?: string | null;
  };
  /** "rate" (the cohort model) or "absolute_threshold" (firm-level) */
  model?: string;
}
export interface FirmExceptionsResponse {
  month: string;
  rules: FirmExceptionRule[];
  rule_count: number;
  /** Round 8 tasks 2/3 — which empty is which */
  published_version?: string | null;
  published_rule_count?: number;
}

export function getFirmExceptions(month: string): Promise<FirmExceptionsResponse> {
  return get(`/api/exceptions/firm?month=${encodeURIComponent(month)}`);
}

// ---------------------------------------------------------------- per-rule advisor ranking

export interface RuleExceptionAdvisorRow {
  advisor_sid: string;
  advisor_name: string;
  affected: number;
  affected_count: number;
  affected_amt: number;
  denominator: number;
  rate_pct: number;
  cohort_median_pct: number | null;
  flagged: boolean;
  suppressed_reason: string | null;
}
export interface RuleExceptionsResponse extends FirmExceptionRule {
  advisors: RuleExceptionAdvisorRow[];
  month: string;
}

export function getRuleExceptions(
  ruleKey: string,
  month: string,
): Promise<RuleExceptionsResponse> {
  return get(
    `/api/exceptions/rule/${encodeURIComponent(ruleKey)}?month=${encodeURIComponent(month)}`,
  );
}
