"use client";

/** Round A2B 4.1 — the dashboard's AI Insights card.
 *
 * Self-contained: fetches the stored practice-level run for the selected
 * transition on mount / prop change and renders its own empty state — a slow
 * fetch here never blocks any other section.
 *
 * Props (the common section contract — the main thread composes this into
 * `app/page.tsx`):
 *   - `fromMonth: string`  — from-month id, e.g. "202604"
 *   - `toMonth: string`    — to-month id, e.g. "202605"
 *   - `monthName: (id: string) => string` — month id -> display name
 *
 * Behaviour:
 *   - Narrative + finding bullets ranked by |impact_amt|; every movable figure
 *     goes through `<NarrativeText>` / `<Delta>` (Task 1.2).
 *   - Every bullet with a rule carries a `.rulecite` line (`<RuleCitation>`) —
 *     the client's central ask: insight -> rule -> document passage. Findings
 *     with no rule keep their driver chip and show no rule line.
 *   - Generate / Re-Generate is per-transition ONLY (no batch anywhere): shows
 *     the projection estimate from `/api/trace/summary`; with no run history it
 *     says "no history yet — first run cost unknown", never an invented number.
 *   - A run that hit a limit renders the amber `.limit-note` sentence.
 */

import { useEffect, useState } from "react";
import {
  type TraceSummary,
  generateInsights,
  getAdvisors,
  getInsightStatus,
  getTraceSummary,
} from "@/lib/api";
import Chip from "@/components/Chip";
import EmptyState from "@/components/EmptyState";
import { LimitNotice } from "@/components/InsightPanel";
import { Delta, NarrativeText } from "@/components/Num";
import RuleCitationLine from "@/components/RuleCitation";
import { useTerm } from "@/components/Term";
import { Prose, driverCode, rankFindings, ruleSetLabel, useInsightRun } from "@/components/insights/shared";

export interface InsightsSectionProps {
  fromMonth: string;
  toMonth: string;
  monthName: (id: string) => string;
}

/** "$0.18 and ~2 min for N runs", or the honest no-history sentence. */
function projectionText(summary: TraceSummary | null, runCount: number): string {
  const avg = summary?.projection.avg_run_cost_usd;
  if (avg == null) return "no history yet — first run cost unknown";
  const wallMs = summary?.projection.avg_run_wall_ms ?? 0;
  const minutes = Math.max(1, Math.round((wallMs * runCount) / 60000));
  return `approx $${(avg * runCount).toFixed(2)} · approx ${minutes} min · ${runCount} runs (book + each advisor)`;
}

export default function InsightsSection({ fromMonth, toMonth, monthName }: InsightsSectionProps) {
  const { run, notGenerated, error, loading, refetch } = useInsightRun(fromMonth, toMonth);
  const [traceSummary, setTraceSummary] = useState<TraceSummary | null>(null);
  const [cohortSize, setCohortSize] = useState<number | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [genError, setGenError] = useState<string | null>(null);

  useEffect(() => {
    getTraceSummary().then(setTraceSummary).catch(() => setTraceSummary(null));
    getAdvisors().then((r) => setCohortSize(r.cohort_count)).catch(() => setCohortSize(null));
  }, []);

  const runCount = (cohortSize ?? 0) + 1;
  const estimate = projectionText(traceSummary, runCount);

  // Per-transition ONLY: generate this transition's runs, poll, refetch.
  const generate = async () => {
    setBusy("starting…");
    setGenError(null);
    try {
      const { job_id } = await generateInsights("all", fromMonth, toMonth);
      let status = await getInsightStatus(job_id);
      while (status.status === "running") {
        setBusy(`generating (${status.completed}/${status.total})…`);
        await new Promise((resolve) => setTimeout(resolve, 1500));
        status = await getInsightStatus(job_id);
      }
      const failed = status.runs.find((r) => r.status === "failed");
      if (failed?.error) setGenError(failed.error);
      refetch();
    } catch (e) {
      setGenError(String((e as Error)?.message || e));
    } finally {
      setBusy(null);
    }
  };

  const complete = run && run.status === "COMPLETE" ? run : null;
  const findings = complete ? rankFindings(complete.findings) : [];

  return (
    <div className="card">
      <div className="card-h">
        <div>
          <h2>
            AI Insights — {monthName(fromMonth)} → {monthName(toMonth)}
          </h2>
          <p>
            {complete
              ? `Generated ${complete.generated_at} · rule set ${ruleSetLabel(complete.version_id)} · stored and shared by everyone`
              : "Stored per transition and rule set version — shared by everyone once generated"}
          </p>
        </div>
        <div className="ctl">
          <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 3 }}>
            <button
              className={complete ? "btn" : "btn primary"}
              onClick={generate}
              disabled={busy !== null}
              title={`Generates insights for this transition only. ${estimate}`}
            >
              {busy ?? (complete ? "↻ Re-Generate" : "Generate Insights")}
            </button>
            <span style={{ fontSize: 11, color: "var(--slate)" }}>{estimate}</span>
          </div>
        </div>
      </div>
      <div className="card-b">
        {genError ? <EmptyState title="Generation failed" message={genError} /> : null}
        {error ? <EmptyState title="AI Insights failed to load" message={error} /> : null}
        {loading && !busy ? (
          <p style={{ color: "var(--slate)", fontSize: "12.5px", margin: 0 }}>Loading…</p>
        ) : null}
        {notGenerated && !busy && !genError ? (
          <EmptyState
            title="AI Insights not generated yet"
            message={`Generate Insights runs the Miner for ${monthName(fromMonth)} → ${monthName(toMonth)} — this transition only. ${estimate}.`}
          />
        ) : null}
        {complete ? (
          <>
            <LimitNotice limits={complete.limit_hit ? complete.limits_hit : null} />
            <div className="narr">
              <Chip variant="aigen">◆ AI Generated</Chip>
              {complete.narrative
                .split(/\n\n+/)
                .filter((p) => p.trim())
                .map((p, i) => (
                  <p key={i} style={i === 0 ? { marginTop: 10 } : undefined}>
                    <Prose text={p} />
                  </p>
                ))}
              {findings.length ? (
                <ul>
                  {findings.map((f, i) => (
                    <li key={f.finding_id ?? i}>
                      <b>
                        {f.title} <Delta value={f.impact_amt} />
                      </b>{" "}
                      <FindingDriverChip
                        code={driverCode(f)}
                        label={f.driver_tag}
                        statement={f.rule_citation?.statement ?? null}
                      />{" "}
                      <NarrativeText text={f.summary} />
                      {f.rule_citation ? (
                        <span style={{ display: "inline-flex", alignItems: "baseline", gap: 4 }}>
                          {/* Review F8 — links prefixed "Source / Citation" */}
                          <span style={{ fontSize: "11.5px", color: "var(--slate)" }}>
                            Source / Citation:
                          </span>
                          <RuleCitationLine
                            ruleKey={f.rule_citation.rule_key}
                            ruleName={f.rule_citation.rule_name || f.rule_citation.rule_code}
                            citation={f.rule_citation.citation}
                          />
                        </span>
                      ) : null}
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
          </>
        ) : null}
      </div>
    </div>
  );
}

/** Driver chip whose definition resolves from the matched rule's statement
 * first, else the glossary (`driver.<CODE>`) — never a hardcoded string.
 * Review F9 — the driver tag renders bold and never wraps. */
export function FindingDriverChip({
  code,
  label,
  statement,
}: {
  code: string;
  label?: string | null;
  statement?: string | null;
}) {
  const term = useTerm(`driver.${code}`);
  return (
    <Chip variant="tag" title={statement || term?.definition || undefined}>
      <span style={{ whiteSpace: "nowrap", fontWeight: 700 }}>
        {label && label.trim() ? label : code}
      </span>
    </Chip>
  );
}
