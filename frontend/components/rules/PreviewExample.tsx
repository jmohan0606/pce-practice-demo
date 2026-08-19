"use client";

/** Round 7 task 9 — Preview Example.
 *
 * Compiles a statement (or a stored draft rule via ruleKey) and RUNS the
 * resulting query against current data, showing what actually comes back:
 * the compiled plan, the match count, a sample, and the proposed scope.
 * Persists NOTHING — the backend asserts the rule count is unchanged and this
 * panel shows it.
 *
 * The compile call costs real money, so it only runs on an explicit click
 * (the click IS "the statement has stopped changing") and the button carries
 * the measured average compile cost from /api/trace/summary.
 */

import { useEffect, useState } from "react";
import { type PreviewResult, RulesApiError, previewRule } from "@/lib/rulesApi";
import PlanView from "@/components/rules/PlanView";

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE || process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8002";

let cachedCostHint: string | null = null;

function useCompileCostHint(): string {
  const [hint, setHint] = useState<string>(cachedCostHint ?? "cost unknown — no compile history yet");
  useEffect(() => {
    if (cachedCostHint !== null) return;
    fetch(`${API_BASE}/api/trace/summary`, { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then((s) => {
        const avg = s?.rule_compile?.avg_cost_usd;
        cachedCostHint =
          avg != null
            ? `approx $${Number(avg).toFixed(3)} per compile (measured over ${s.rule_compile.run_count} previous compiles)`
            : "cost unknown — no compile history yet";
        setHint(cachedCostHint);
      })
      .catch(() => {
        /* the hint is display sugar */
      });
  }, []);
  return hint;
}

export default function PreviewExample({
  statement,
  ruleName,
  appliesTo,
  severity,
  ruleKey,
  disabled,
}: {
  /** Write-a-Rule mode: the statement being drafted. */
  statement?: string;
  ruleName?: string;
  appliesTo?: string;
  severity?: string;
  /** Extracted-rule mode: preview a stored draft before approval. */
  ruleKey?: string;
  disabled?: boolean;
}) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<PreviewResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const costHint = useCompileCostHint();

  const canPreview = !busy && !disabled && (ruleKey ? true : Boolean(statement?.trim()));

  const run = async () => {
    if (!canPreview) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const res = await previewRule(
        ruleKey
          ? { rule_key: ruleKey }
          : {
              statement: statement?.trim(),
              rule_name: ruleName || "",
              applies_to: appliesTo || "ALL",
              severity: severity || undefined,
            },
      );
      setResult(res);
    } catch (e) {
      setError(
        e instanceof RulesApiError
          ? e.status === 0
            ? "The rules service is not reachable."
            : e.message
          : String((e as Error)?.message || e),
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ marginTop: 6 }}>
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <button
          type="button"
          className="btn"
          disabled={!canPreview}
          onClick={run}
          title={`Compiles the statement and runs the query against current data. Nothing is saved — no rule, no version. Costs one compile call: ${costHint}`}
        >
          {busy ? "Previewing…" : "Preview Example"}
        </button>
        <span style={{ fontSize: 11.5, color: "var(--slate)" }}>
          runs the compiled query against current data · saves nothing · {costHint}
        </span>
      </div>
      {error ? (
        <div style={{ color: "var(--neg, #B3261E)", fontSize: 12.5, marginTop: 6 }}>{error}</div>
      ) : null}
      {result ? (
        <div
          style={{
            marginTop: 8,
            border: "1px solid var(--rule)",
            borderRadius: 5,
            padding: "10px 12px",
            fontSize: 12.5,
          }}
        >
          {result.outcome === "COMPILED" ? (
            <>
              <div>
                <b>Matches:</b> {result.matched_count?.toLocaleString()} of{" "}
                {result.evaluated_rows?.toLocaleString()} rows evaluated
                {result.matched_count === 0 ? (
                  <span style={{ color: "var(--neg, #B3261E)" }}>
                    {" "}
                    — matches nothing{result.empty_reason ? ` (${result.empty_reason})` : " — a threshold or field may not behave as expected"}
                  </span>
                ) : result.evaluated_rows && result.matched_count === result.evaluated_rows ? (
                  <span style={{ color: "var(--neg, #B3261E)" }}>
                    {" "}
                    — matches everything evaluated: the filter is not filtering
                  </span>
                ) : null}
              </div>
              {result.sample?.length ? (
                <div style={{ marginTop: 4 }}>
                  <b>Sample:</b>{" "}
                  {result.sample
                    .map((s) => `${s.key}${s.value != null ? ` (${Number(s.value).toLocaleString()})` : ""}`)
                    .join(" · ")}
                </div>
              ) : null}
              <div style={{ marginTop: 4 }}>
                <b>Previewed with:</b>{" "}
                {Object.entries(result.params_used ?? {})
                  .map(([k, v]) => `${k}=${String(v)}`)
                  .join(" · ") || "(no parameters)"}
              </div>
              {result.scope_challenge ? (
                <div style={{ marginTop: 4 }}>
                  <b>Scope:</b> proposed {result.scope_challenge.proposed_applies_to} —{" "}
                  {result.scope_challenge.reason}
                </div>
              ) : null}
              {result.severity ? (
                <div style={{ marginTop: 4 }}>
                  <b>Severity:</b> proposed {result.severity}
                </div>
              ) : null}
              <PlanView plan={result.plan} explanation={result.explanation} />
            </>
          ) : result.outcome === "UNSUPPORTED" ? (
            <div>
              <b>Unsupported</b> — the schema cannot express this rule: {result.reason}
            </div>
          ) : (
            <div>
              <b>Compile failed honestly</b> — {result.reason}
            </div>
          )}
          <div style={{ marginTop: 6, color: "var(--slate)", fontSize: 11.5 }}>
            Nothing was saved — the rule set still holds {result.rule_count} rules.
          </div>
        </div>
      ) : null}
    </div>
  );
}
