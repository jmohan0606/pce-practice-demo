"use client";

import { useCallback, useEffect, useState } from "react";
import {
  type TraceRun,
  type TraceRunDetail,
  type TraceSummary,
  getTraceRunDetail,
  getTraceRuns,
  getTraceSummary,
} from "@/lib/api";
import EmptyState from "@/components/EmptyState";
import PageHeader from "@/components/PageHeader";

const cost = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : `$${v.toFixed(4)}`;
const tokens = (v: number) => v.toLocaleString("en-US");
const wall = (ms: number) => (ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`);

/** Cost & Trace: what every run cost, per turn — a runaway turn must be
 * visible at a glance. All figures come from logged response.usage counts. */
export default function TracePage() {
  const [runs, setRuns] = useState<TraceRun[]>([]);
  const [summary, setSummary] = useState<TraceSummary | null>(null);
  const [detail, setDetail] = useState<TraceRunDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(() => {
    getTraceRuns().then((r) => setRuns(r.runs)).catch((e) => setError(String(e?.message || e)));
    getTraceSummary().then(setSummary).catch(() => setSummary(null));
  }, []);

  useEffect(reload, [reload]);

  const open = (runId: string) => {
    getTraceRunDetail(runId).then(setDetail).catch(() => setDetail(null));
  };

  const maxTurnTokens = detail
    ? Math.max(1, ...detail.turn_rows.map((t) => t.input_tokens + t.cache_read_tokens + t.cache_write_tokens))
    : 1;

  return (
    <section>
      <PageHeader title="Cost &amp; Trace" meta="Token spend per run and per turn · figures from provider usage counts, never estimated" />

      {summary ? (
        <div className="card" style={{ marginBottom: 16 }}>
          <div className="card-h">
            <div>
              <h2>Totals</h2>
              <p>Cost per advisor, per document extraction, per full refresh.</p>
            </div>
            <div className="ctl">
              <button className="btn" onClick={reload}>↻ Refresh</button>
            </div>
          </div>
          <div className="card-b">
            <div className="kpi">
              <div>
                <div className="k">DOCUMENT EXTRACTION</div>
                <div className="v">{cost(summary.document_extraction.est_cost_usd)}</div>
              </div>
              <div>
                <div className="k">CONFLICT AUDIT</div>
                <div className="v">{cost(summary.conflict_audit.est_cost_usd)}</div>
              </div>
              <div>
                <div className="k">FULL REFRESH (PROJECTED)</div>
                <div className="v">
                  {summary.full_refresh.est_cost_usd !== null
                    ? `${cost(summary.full_refresh.est_cost_usd)} · ~${summary.full_refresh.est_minutes} min`
                    : "no run history"}
                </div>
              </div>
              <div>
                <div className="k">AVG COST / RUN ({summary.projection.history_runs} RUNS)</div>
                <div className="v">{cost(summary.projection.avg_run_cost_usd)}</div>
              </div>
            </div>
            {summary.per_advisor.length ? (
              <table>
                <thead>
                  <tr>
                    <th>Advisor</th><th>Turns</th><th>Input</th><th>Output</th>
                    <th>Cache read</th><th>Cache hit %</th><th>Est cost</th>
                  </tr>
                </thead>
                <tbody>
                  {summary.per_advisor.map((a) => (
                    <tr key={a.advisor_sid}>
                      <td>{a.advisor_sid}</td>
                      <td>{a.turns}</td>
                      <td>{tokens(a.input_tokens)}</td>
                      <td>{tokens(a.output_tokens)}</td>
                      <td>{tokens(a.cache_read_tokens)}</td>
                      <td>{a.cache_hit_pct}%</td>
                      <td>{cost(a.est_cost_usd)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : null}
          </div>
        </div>
      ) : null}

      <div className="card" style={{ marginBottom: 16 }}>
        <div className="card-h">
          <div>
            <h2>Runs</h2>
            <p>Every turn-logged scope — insight runs, document extractions, conflict audits.</p>
          </div>
        </div>
        <div className="card-b">
          {error ? <EmptyState title="Trace unavailable" message={error} /> : null}
          {runs.length ? (
            <div style={{ overflowX: "auto" }}>
              <table>
                <thead>
                  <tr>
                    <th>Run</th><th>Advisor</th><th>Transition</th><th>Rule set</th>
                    <th>Turns</th><th>Queries</th><th>Input</th><th>Output</th>
                    <th>Cache read</th><th>Cache hit %</th><th>Est cost</th>
                    <th>Wall</th><th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {runs.map((r) => (
                    <tr key={r.run_id} onClick={() => open(r.run_id)} style={{ cursor: "pointer" }}>
                      <td style={{ maxWidth: 240, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={r.run_id}>
                        {r.run_id}
                      </td>
                      <td>{r.advisor_sid ?? "—"}</td>
                      <td>{r.transition ?? r.kind.replace("_", " ")}</td>
                      <td>{r.version_id ?? "—"}</td>
                      <td>{r.turns}</td>
                      <td>{r.query_count}</td>
                      <td>{tokens(r.input_tokens)}</td>
                      <td>{tokens(r.output_tokens)}</td>
                      <td>{tokens(r.cache_read_tokens)}</td>
                      <td>{r.cache_hit_pct}%</td>
                      <td>{cost(r.est_cost_usd)}</td>
                      <td>{wall(r.wall_ms)}</td>
                      <td>
                        {r.status}
                        {r.budget_hit_tokens ? " · token budget hit" : ""}
                        {r.budget_hit ? " · query budget hit" : ""}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : !error ? (
            <EmptyState
              title="No runs traced yet"
              message="Turn logging starts with the first LLM call (insight run, document extraction or conflict audit) after this build."
            />
          ) : null}
        </div>
      </div>

      {detail ? (
        <div className="card">
          <div className="card-h">
            <div>
              <h2>Run detail — {detail.run_id}</h2>
              <p>
                {detail.turns} turns · {tokens(detail.input_tokens)} in / {tokens(detail.output_tokens)} out ·{" "}
                {detail.cache_hit_pct}% cache hit · {cost(detail.est_cost_usd)} · {wall(detail.wall_ms)}
              </p>
            </div>
            <div className="ctl">
              <button className="btn" onClick={() => setDetail(null)}>Close</button>
            </div>
          </div>
          <div className="card-b" style={{ overflowX: "auto" }}>
            <table>
              <thead>
                <tr>
                  <th>Seq</th><th>Agent</th><th>Action</th><th>Query</th>
                  <th>In</th><th>Out</th><th>Cached</th><th>Cache write</th>
                  <th>Latency</th><th>Est cost</th><th>Prompt size</th>
                </tr>
              </thead>
              <tbody>
                {detail.turn_rows.map((t) => {
                  const promptTokens = t.input_tokens + t.cache_read_tokens + t.cache_write_tokens;
                  return (
                    <tr key={t.seq_no}>
                      <td>{t.seq_no}</td>
                      <td>{t.agent_name}</td>
                      <td>{t.action_kind || "—"}</td>
                      <td>{t.query_name || "—"}</td>
                      <td>{tokens(t.input_tokens)}</td>
                      <td>{tokens(t.output_tokens)}</td>
                      <td>{tokens(t.cache_read_tokens)}</td>
                      <td>{tokens(t.cache_write_tokens)}</td>
                      <td>{wall(t.latency_ms)}</td>
                      <td>{cost(t.est_cost_usd)}</td>
                      <td>
                        {/* a runaway turn shows as the longest bar at a glance */}
                        <div style={{ background: "var(--rule)", borderRadius: 3, width: 120 }}>
                          <div
                            style={{
                              width: `${Math.round((promptTokens / maxTurnTokens) * 100)}%`,
                              background: promptTokens === maxTurnTokens ? "var(--neg, #b3363b)" : "var(--slate)",
                              height: 8,
                              borderRadius: 3,
                            }}
                            title={`${tokens(promptTokens)} prompt tokens`}
                          />
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}
    </section>
  );
}
