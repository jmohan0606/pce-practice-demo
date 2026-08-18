/** Round C (docs/rules) — typed clients for the round's NEW rule/document
 * endpoints. Read/edit/compile/approve/publish live in lib/api.ts (unchanged).
 *
 * OWNED BY THE MAIN THREAD — subagents consume, never edit. The request/response
 * shapes here are the contract the backend implements.
 */
import type { RuleDetail, RuleVersion } from "@/lib/api";

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ||
  process.env.NEXT_PUBLIC_API_BASE_URL ||
  "http://localhost:8002";

export class RulesApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = "RulesApiError";
  }
}

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method,
      cache: "no-store",
      headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new RulesApiError(0, `API unreachable at ${API_BASE}`);
  }
  if (!response.ok) {
    let detail = `${response.status} for ${path}`;
    try {
      const parsed = await response.json();
      if (parsed?.detail) detail = String(parsed.detail);
    } catch {
      /* keep the status message */
    }
    throw new RulesApiError(response.status, detail);
  }
  return (await response.json()) as T;
}

// ---------- Task 2 — active flag + delete ----------

/** Deactivate/reactivate. Reason is REQUIRED (400 without one). Version-bound
 * rules mint a new version; draft-pool rules return version:null. */
export function setRuleActive(
  ruleKey: string,
  active: boolean,
  reason: string,
  approvedBy: string = "operator",
): Promise<{ rule: RuleDetail; version: RuleVersion | null; note?: string | null }> {
  return req("PATCH", `/api/rules/${encodeURIComponent(ruleKey)}/active`, {
    active,
    reason,
    approved_by: approvedBy,
  });
}

/** Delete UNAPPROVED rules only — the STORE refuses approved rules with a 400;
 * all-or-nothing (a mixed selection deletes nothing). */
export function deleteRules(
  ruleKeys: string[],
): Promise<{ deleted: { rule_key: string; rule_code?: string; status?: string }[]; deleted_count: number }> {
  return req("POST", "/api/rules/delete", { rule_keys: ruleKeys });
}

// ---------- Task 5 — manual rule authoring (backend: Subagent B) ----------

export interface ManualRuleRequest {
  rule_name: string;
  statement: string;
  /** MANUALLY_WRITTEN_PRACTICE | MANUALLY_WRITTEN_TECH */
  provenance: string;
  /** PRACTICE | ADVISOR | PRODUCT | ALL */
  applies_to: string;
  applies_to_key?: string | null;
  severity: string;
  driver_label: string;
  driver_definition?: string;
  /** true → the Rule Compiler generates a plan (reviewable before approval);
   * false → natural_language_only guidance, injected into the Miner context. */
  generate_query: boolean;
}
/** POST /api/rules/manual — creates a draft-pool rule. When generate_query is
 * true the compiler runs and the response carries the compiled (or honestly
 * failed) rule; when false status is COMPILED-equivalent guidance with no plan. */
export function createManualRule(body: ManualRuleRequest): Promise<{ rule: RuleDetail }> {
  return req("POST", "/api/rules/manual", body);
}

/** POST /api/rules/{key}/promote — compile a natural-language-only rule into a
 * computed rule (version-minting; reason required). */
export function promoteRule(
  ruleKey: string,
  reason: string,
): Promise<{ rule: RuleDetail; version: RuleVersion | null }> {
  return req("POST", `/api/rules/${encodeURIComponent(ruleKey)}/promote`, { reason });
}

/** POST /api/rules/{key}/demote — remove a rule's plan, back to guidance-only
 * (version-minting; reason required). */
export function demoteRule(
  ruleKey: string,
  reason: string,
): Promise<{ rule: RuleDetail; version: RuleVersion | null }> {
  return req("POST", `/api/rules/${encodeURIComponent(ruleKey)}/demote`, { reason });
}

// ---------- Task 6 — retry query generation (backend: Subagent B) ----------

export interface CompileAttempt {
  attempt_no: number;
  note?: string | null;
  plan?: unknown;
  explanation?: string | null;
  status?: string;
  compile_error?: string | null;
  created_at?: string;
}
/** POST /api/rules/{key}/recompile — asks the Rule Compiler for another plan.
 * Every attempt is KEPT (compile_attempts on the rule); the user picks which
 * attempt to approve via pickAttempt. */
export function recompileRule(
  ruleKey: string,
  note: string = "",
): Promise<{ rule: RuleDetail; attempts: CompileAttempt[] }> {
  return req("POST", `/api/rules/${encodeURIComponent(ruleKey)}/recompile`, { note });
}

/** POST /api/rules/{key}/attempts/{n}/pick — make attempt n the rule's active plan. */
export function pickAttempt(
  ruleKey: string,
  attemptNo: number,
): Promise<{ rule: RuleDetail }> {
  return req("POST", `/api/rules/${encodeURIComponent(ruleKey)}/attempts/${attemptNo}/pick`, {});
}

// ---------- Round 3 Task 3 — exception configuration ----------

/** The eight Round-1 exception-configuration fields plus the audit pair.
 * Send only the fields being changed; an explicit null clears a field
 * (honest-null — "the document states nothing"). */
export interface ExceptionConfigChanges {
  driver_enabled?: boolean;
  exception_enabled?: boolean;
  exception_denominator?: string | null;
  exception_floor?: number | null;
  /** "accounts" | "dollars" */
  exception_floor_unit?: string | null;
  exception_sensitivity?: number | null;
  product_scope?: string | null;
  product_scope_source?: string | null;
  reason?: string;
  approved_by?: string;
}

/** PATCH /api/rules/{key}/exception-config — edits a rule's exception
 * configuration. Version-bound rules mint AND publish a new version in one
 * call (rule_keys change per mint — refetch the list after a save); draft-pool
 * rules just get the fields updated (version: null). */
export function setExceptionConfig(
  ruleKey: string,
  changes: ExceptionConfigChanges,
): Promise<{ rule: RuleDetail; version: RuleVersion | null; note?: string | null }> {
  return req("PATCH", `/api/rules/${encodeURIComponent(ruleKey)}/exception-config`, changes);
}

// ---------- Round 5 task 13.1 — extraction job progress ----------

/** A phx_dm_pce_job row (Round 1). `stages` is the ordered stage list;
 * `stage_index` is 1-based into it. */
export interface IngestJob {
  job_id: string;
  kind: string;
  scope_key?: string;
  stages?: string[];
  stage?: string;
  stage_index?: number;
  stage_total?: number;
  items_done?: number;
  items_total?: number;
  /** RUNNING | INTERRUPTED | COMPLETE | FAILED */
  status?: string;
  error?: string;
  started_at?: string;
  updated_at?: string;
}

/** Latest document_ingest job for one document (jobs list is newest-first). */
export async function getLatestIngestJob(documentId: string): Promise<IngestJob | null> {
  const res = await req<{ total: number; jobs: IngestJob[] }>(
    "GET",
    `/api/jobs?kind=document_ingest&scope_key=${encodeURIComponent(documentId)}`,
  );
  return res.jobs?.[0] ?? null;
}

/** POST /api/jobs/{id}/resume — EXPLICIT resume of an INTERRUPTED extraction.
 * Never called automatically on page load (auto-resume could double-spend). */
export function resumeJob(
  jobId: string,
): Promise<{ document_id: string; job: IngestJob; resumed_rules: number }> {
  return req("POST", `/api/jobs/${encodeURIComponent(jobId)}/resume`);
}

// ---------- Round 5 task 13.4 — batch approval ----------

export interface BatchApproveResult {
  document_id: string;
  document_name?: string | null;
  approved_count: number;
  approved: { rule_key: string; rule_code?: string; rule_name?: string }[];
  failures: { rule_key: string; rule_code?: string; reason: string }[];
  skipped: { rule_key: string; rule_code?: string; status?: string; reason?: string | null }[];
  version: RuleVersion | null;
}

/** POST /api/rules/batch-approve — approves every COMPILED draft from the
 * document, then publishes ONCE (one new rule-set version for the batch).
 * NEEDS_INPUT / NEEDS_DATA / DRAFT rules are refused server-side (skipped). */
export function batchApproveDocument(
  documentId: string,
  approvedBy: string = "operator",
): Promise<BatchApproveResult> {
  return req("POST", "/api/rules/batch-approve", {
    document_id: documentId,
    approved_by: approvedBy,
  });
}

// ---------- Task 3 — document category (backend: Subagent A) ----------

export const DOCUMENT_CATEGORIES = [
  "PLAN",
  "GUIDANCE",
  "PLAYBOOK",
  "TRAINING",
  "FAQ",
  "OTHER",
] as const;
export type DocumentCategory = (typeof DOCUMENT_CATEGORIES)[number];
/** Only these categories feed the Rule Extractor. */
export const EXTRACTING_CATEGORIES: DocumentCategory[] = ["PLAN", "FAQ"];

/** PATCH /api/documents/{id}/category — change a document's category after
 * upload. extraction_offered=true when the new category is PLAN or FAQ (the UI
 * then offers to run extraction). */
export function setDocumentCategory(
  documentId: string,
  category: DocumentCategory,
): Promise<{ document: Record<string, unknown>; extraction_offered: boolean }> {
  return req("PATCH", `/api/documents/${encodeURIComponent(documentId)}/category`, { category });
}
