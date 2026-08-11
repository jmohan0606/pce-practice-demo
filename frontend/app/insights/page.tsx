"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  type Advisor,
  type InsightRun,
  type MonthRow,
  type RuleVersion,
  type Transition,
  type TraceSummary,
  generateInsights,
  getAdvisors,
  getInsightStatus,
  getInsights,
  getMonths,
  getPeerRank,
  getRuleVersions,
  getTraceSummary,
  getTransitions,
} from "@/lib/api";
import EmptyState from "@/components/EmptyState";
import PageHeader from "@/components/PageHeader";
import { NarrativeBlock, TransitionCard } from "@/components/InsightPanel";
import { arrow, money, percent } from "@/lib/format";

/** AI Insights — one page, two views (cost-fix 4.1):
 *  Practice — the whole book (advisor scope "all"), no selector; the
 *             all-advisors batch lives ONLY here, behind an explicit confirm
 *             that shows the cost projection (4.2).
 *  Advisor  — advisor dropdown + Generate for exactly that advisor and
 *             transition. Never fans out. */
export default function InsightsPage() {
  const [view, setView] = useState<"practice" | "advisor">("practice");
  const [traceSummary, setTraceSummary] = useState<TraceSummary | null>(null);

  useEffect(() => {
    getTraceSummary().then(setTraceSummary).catch(() => setTraceSummary(null));
  }, [view]);

  return (
    <section>
      <PageHeader title="AI Insights" meta="Practice-wide narrative or a single advisor — both generated from graph data">
        <div className="pivot">
          <button aria-selected={view === "practice"} onClick={() => setView("practice")}>
            Practice
          </button>
          <button aria-selected={view === "advisor"} onClick={() => setView("advisor")}>
            Advisor
          </button>
        </div>
      </PageHeader>
      {view === "practice" ? (
        <PracticeView traceSummary={traceSummary} />
      ) : (
        <AdvisorView traceSummary={traceSummary} />
      )}
    </section>
  );
}

function projectionLine(
  traceSummary: TraceSummary | null,
  runCount: number,
  label: string,
): { text: string; hasHistory: boolean } {
  const avg = traceSummary?.projection.avg_run_cost_usd;
  const wallMs = traceSummary?.projection.avg_run_wall_ms ?? 0;
  if (avg == null) return { text: `${label} · no run history for a projection`, hasHistory: false };
  const minutes = Math.max(1, Math.round((wallMs * runCount) / 60000));
  return {
    text: `${label} · approx $${(avg * runCount).toFixed(2)}, approx ${minutes} min`,
    hasHistory: true,
  };
}

// --------------------------------------------------------------------------
// Practice view — all advisors, no selector
// --------------------------------------------------------------------------

function PracticeView({ traceSummary }: { traceSummary: TraceSummary | null }) {
  const [versions, setVersions] = useState<RuleVersion[]>([]);
  const [version, setVersion] = useState("latest");
  const [months, setMonths] = useState<MonthRow[]>([]);
  const [transitions, setTransitions] = useState<Transition[]>([]);
  const [runs, setRuns] = useState<Record<string, InsightRun>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [pivot, setPivot] = useState<"driver" | "product" | "none">("none");
  const [error, setError] = useState<string | null>(null);
  const [cohortSize, setCohortSize] = useState<number | null>(null);

  const monthLabel = useCallback(
    (id: string) => months.find((m) => m.month_id === id)?.month_name ?? id,
    [months],
  );

  const loadRuns = useCallback((trans: Transition[], ver: string) => {
    trans.forEach((t) => {
      getInsights("all", t.from_month_id, t.to_month_id, ver)
        .then((run) =>
          setRuns((prev) => ({ ...prev, [`${t.from_month_id}|${t.to_month_id}`]: run })),
        )
        .catch(() => {
          setRuns((prev) => {
            const next = { ...prev };
            delete next[`${t.from_month_id}|${t.to_month_id}`];
            return next;
          });
        });
    });
  }, []);

  useEffect(() => {
    getRuleVersions().then((r) => setVersions(r.versions ?? [])).catch(() => setVersions([]));
    getAdvisors()
      .then((r) => setCohortSize(r.cohort_count))
      .catch(() => setCohortSize(null));
    Promise.all([getMonths("all"), getTransitions("all")])
      .then(([m, t]) => {
        setMonths(m.months);
        setTransitions(t.transitions);
        loadRuns(t.transitions, "latest");
      })
      .catch((e) => setError(String(e?.message || e)));
  }, [loadRuns]);

  useEffect(() => {
    if (transitions.length) loadRuns(transitions, version);
  }, [version, transitions, loadRuns]);

  // 4.2: the all-advisors batch belongs ONLY here, behind an explicit confirm
  // that shows the projection (advisor="all" = aggregate book + every advisor).
  const batchRunCount = (cohortSize ?? 0) + 1;
  const projection = projectionLine(
    traceSummary,
    batchRunCount * Math.max(transitions.length, 1),
    `${cohortSize ?? "?"} advisors + book x ${transitions.length} transitions`,
  );

  const regenerate = async () => {
    const confirmed = window.confirm(
      `Run the all-advisors batch?\n\n${projection.text}\n\nThis starts ` +
        `${batchRunCount} runs per transition (aggregate book + each advisor).`,
    );
    if (!confirmed) return;
    setBusy("starting…");
    setError(null);
    try {
      for (const t of transitions) {
        const { job_id } = await generateInsights("all", t.from_month_id, t.to_month_id);
        let status = await getInsightStatus(job_id);
        while (status.status === "running") {
          setBusy(`generating ${t.from_month_id} → ${t.to_month_id} (${status.completed}/${status.total})…`);
          await new Promise((resolve) => setTimeout(resolve, 1500));
          status = await getInsightStatus(job_id);
        }
      }
      loadRuns(transitions, version);
    } catch (e) {
      setError(String((e as Error)?.message || e));
    } finally {
      setBusy(null);
    }
  };

  const exportJson = () => {
    const blob = new Blob([JSON.stringify(Object.values(runs), null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "insights.json";
    a.click();
    URL.revokeObjectURL(url);
  };

  const anyRun = transitions
    .map((t) => runs[`${t.from_month_id}|${t.to_month_id}`])
    .find((r) => r && r.status === "COMPLETE");
  const findingCount = Object.values(runs).reduce((n, r) => n + (r?.findings.length ?? 0), 0);

  return (
    <div className="card">
      <div className="card-h">
        <div>
          <h2>What Is Driving the Changes in Month-over-Month Credited Revenue?</h2>
          <p>
            Whole practice · one card per month-over-month move · findings ranked by impact ·
            every figure computed from graph data
          </p>
        </div>
        <div className="ctl">
          <span style={{ fontSize: "12.5px", color: "var(--slate)" }}>Rule Set</span>
          <select value={version} onChange={(e) => setVersion(e.target.value)}>
            <option value="latest">Latest</option>
            {versions.map((v) => (
              <option key={v.version_id ?? v.version_no} value={v.version_id ?? String(v.version_no)}>
                v{v.version_no}
                {v.published_at ? ` · ${v.published_at}` : ""}
              </option>
            ))}
          </select>
          <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 3 }}>
            <button className="btn" onClick={regenerate} disabled={busy !== null}>
              {busy ? busy : "↻ Generate (all advisors)"}
            </button>
            <span
              style={{
                fontSize: "11px",
                color: projection.hasHistory ? "var(--slate)" : "var(--rule)",
              }}
            >
              {projection.text}
            </span>
          </div>
          <button className="btn" onClick={exportJson} disabled={!anyRun}>
            Export
          </button>
        </div>
      </div>
      <div className="card-b">
        {error ? <EmptyState title="Generation Failed" message={error} /> : null}
        {anyRun ? (
          <>
            <NarrativeBlock run={anyRun} />
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                marginBottom: 14,
                gap: 14,
                flexWrap: "wrap",
              }}
            >
              <div className="pivot">
                <button aria-selected={pivot === "none"} onClick={() => setPivot("none")}>
                  Ranked
                </button>
                <button aria-selected={pivot === "driver"} onClick={() => setPivot("driver")}>
                  By Driver
                </button>
                <button aria-selected={pivot === "product"} onClick={() => setPivot("product")}>
                  By Product
                </button>
              </div>
              <span style={{ fontSize: "12.5px", color: "var(--slate)" }}>
                {findingCount} findings across {Object.keys(runs).length} transitions
              </span>
            </div>
            <div className="tcards">
              {transitions.map((t) => {
                const run = runs[`${t.from_month_id}|${t.to_month_id}`];
                return run ? (
                  <TransitionCard
                    key={run.run_id}
                    run={run}
                    transition={t}
                    monthLabel={monthLabel}
                    groupBy={pivot === "none" ? undefined : pivot}
                  />
                ) : (
                  <div key={`${t.from_month_id}|${t.to_month_id}`} className="tcard">
                    <div className="tcard-h">
                      <div className="mm">
                        {monthLabel(t.from_month_id)} → {monthLabel(t.to_month_id)}
                      </div>
                    </div>
                    <div style={{ padding: "14px 15px", color: "var(--slate)", fontSize: "12.5px" }}>
                      No run for this transition yet.
                    </div>
                  </div>
                );
              })}
            </div>
            <div
              className="note"
              style={{ marginTop: 16, border: "1px solid var(--rule)", borderRadius: 5 }}
            >
              Findings are independent observations, not a decomposition — they are not expected
              to sum to the total change. Every figure shown is a stored query result.
            </div>
          </>
        ) : !error ? (
          <EmptyState
            title="No insights generated yet"
            message="Generate runs the Insights Miner against the graph for each month-over-month move, then writes the summary you see here."
          />
        ) : null}
      </div>
    </div>
  );
}

// --------------------------------------------------------------------------
// Advisor view — dropdown + Generate for exactly that advisor (never fans out)
// --------------------------------------------------------------------------

function AdvisorView({ traceSummary }: { traceSummary: TraceSummary | null }) {
  const [advisors, setAdvisors] = useState<Advisor[]>([]);
  const [sid, setSid] = useState<string>("");
  const [months, setMonths] = useState<MonthRow[]>([]);
  const [transitions, setTransitions] = useState<Transition[]>([]);
  const [cohortRank, setCohortRank] = useState<string | null>(null);
  const [run, setRun] = useState<InsightRun | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getAdvisors()
      .then((res) => {
        const cohort = res.advisors.filter((a) => a.in_cohort);
        setAdvisors(cohort);
        if (cohort.length) setSid((current) => current || cohort[0].advisor_sid);
      })
      .catch((e) => setError(String(e?.message || e)));
  }, []);

  // KPI transition: the first between two FULL months, else the first
  const kpiTransition = useMemo(() => {
    return (
      transitions.find((t) => {
        const to = months.find((m) => m.month_id === t.to_month_id);
        return to && !to.is_partial;
      }) ?? transitions[0] ?? null
    );
  }, [transitions, months]);

  const loadRun = useCallback((advisorSid: string, t: Transition | null) => {
    if (!t) return;
    getInsights(advisorSid, t.from_month_id, t.to_month_id)
      .then(setRun)
      .catch(() => setRun(null)); // no run yet — the empty state, never a spinner
  }, []);

  useEffect(() => {
    if (!sid) return;
    let cancelled = false;
    setError(null);
    setRun(null);
    Promise.all([getMonths(sid), getTransitions(sid)])
      .then(([m, t]) => {
        if (cancelled) return;
        setMonths(m.months);
        setTransitions(t.transitions);
      })
      .catch((e) => {
        if (!cancelled) setError(String(e?.message || e));
      });
    return () => {
      cancelled = true;
    };
  }, [sid]);

  useEffect(() => {
    if (sid && kpiTransition) loadRun(sid, kpiTransition);
    if (sid && kpiTransition) {
      getPeerRank(sid, kpiTransition.to_month_id)
        .then((r) => setCohortRank(r.rank ? `${r.rank} of ${r.cohort_size}` : null))
        .catch(() => setCohortRank(null));
    }
  }, [sid, kpiTransition, loadRun]);

  const projection = projectionLine(traceSummary, 1, "1 run");

  // 4.2: runs EXACTLY this advisor and this transition — no fan-out.
  const generate = async () => {
    if (!kpiTransition) return;
    setBusy("generating…");
    setError(null);
    try {
      const { job_id } = await generateInsights(sid, kpiTransition.from_month_id, kpiTransition.to_month_id);
      let status = await getInsightStatus(job_id);
      while (status.status === "running") {
        await new Promise((resolve) => setTimeout(resolve, 1500));
        status = await getInsightStatus(job_id);
      }
      const failed = status.runs.find((r) => r.status === "failed");
      if (failed?.error) setError(failed.error);
      loadRun(sid, kpiTransition);
    } catch (e) {
      setError(String((e as Error)?.message || e));
    } finally {
      setBusy(null);
    }
  };

  const advisor = useMemo(() => advisors.find((a) => a.advisor_sid === sid), [advisors, sid]);
  const monthLabel = useCallback(
    (id: string) => months.find((m) => m.month_id === id)?.month_name ?? id,
    [months],
  );
  const fullMonths = months.filter((m) => !m.is_partial);

  return (
    <div className="card">
      <div className="card-h">
        <div>
          <h2>{advisor ? `${advisor.advisor_sid} · ${advisor.advisor_name || advisor.advisor_sid}` : "Advisor"}</h2>
          <p>Per-advisor credited revenue and generated insights.</p>
        </div>
        <div className="ctl">
          <select value={sid} onChange={(e) => setSid(e.target.value)}>
            {advisors.map((a) => (
              <option key={a.advisor_sid} value={a.advisor_sid}>
                {a.advisor_sid} · {a.advisor_name || a.advisor_sid}
              </option>
            ))}
          </select>
          <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 3 }}>
            <button className="btn primary" onClick={generate} disabled={busy !== null || !kpiTransition}>
              {busy ? busy : "Generate Insights (this advisor only)"}
            </button>
            <span
              style={{
                fontSize: "11px",
                color: projection.hasHistory ? "var(--slate)" : "var(--rule)",
              }}
            >
              {projection.text}
            </span>
          </div>
        </div>
      </div>
      <div className="card-b">
        {error ? <EmptyState title="Problem" message={error} /> : null}
        <div className="kpi">
          {fullMonths.map((m) => (
            <div key={m.month_id}>
              <div className="k">{m.month_name.toUpperCase()}</div>
              <div className="v">{money(m.credited_amt)}</div>
            </div>
          ))}
          {kpiTransition ? (
            <div>
              <div className="k">CHANGE</div>
              <div className={`v ${kpiTransition.change_amt < 0 ? "dn" : "up"}`}>
                {arrow(kpiTransition.change_amt)} {money(kpiTransition.change_amt)}{" "}
                {percent(kpiTransition.change_pct)}
              </div>
            </div>
          ) : null}
          {cohortRank ? (
            <div>
              <div className="k">RANK IN COHORT</div>
              <div className="v">{cohortRank}</div>
            </div>
          ) : null}
          {run ? (
            <div>
              <div className="k">LAST GENERATED</div>
              <div className="v" style={{ fontSize: 15, fontWeight: 500 }}>
                {run.generated_at}
              </div>
            </div>
          ) : null}
        </div>

        {run && run.status === "COMPLETE" ? (
          <>
            <NarrativeBlock run={run} />
            <TransitionCard run={run} transition={kpiTransition} monthLabel={monthLabel} />
          </>
        ) : run && run.status === "FAILED" ? (
          <EmptyState title="Last run failed" message={run.error ?? "See the server log."} />
        ) : !busy ? (
          <EmptyState
            title="No insights generated yet"
            message="Generate Insights runs the Miner for this advisor's latest full-month transition — one run, this advisor only."
          />
        ) : (
          <EmptyState
            title="Generating…"
            message={`The Insights Miner is querying the graph for ${sid} (${kpiTransition?.from_month_id} → ${kpiTransition?.to_month_id}). This page updates when the run completes.`}
          />
        )}
      </div>
    </div>
  );
}
