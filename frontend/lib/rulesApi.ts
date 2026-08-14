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
