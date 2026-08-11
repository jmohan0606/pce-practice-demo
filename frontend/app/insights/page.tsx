"use client";

import { useCallback, useEffect, useState } from "react";
import {
  type InsightRun,
  type MonthRow,
  type RuleVersion,
  type Transition,
  generateInsights,
  getInsightStatus,
  getInsights,
  getMonths,
  getRuleVersions,
  getTransitions,
} from "@/lib/api";
import EmptyState from "@/components/EmptyState";
import PageHeader from "@/components/PageHeader";
import { NarrativeBlock, TransitionCard } from "@/components/InsightPanel";

/** C5 — AI Insights: whole-book narrative (advisor scope "all") plus one card
 * per month-over-month move. Pivot regroups the SAME findings — no refetch. */
export default function InsightsPage() {
  const [versions, setVersions] = useState<RuleVersion[]>([]);
  const [version, setVersion] = useState("latest");
  const [months, setMonths] = useState<MonthRow[]>([]);
  const [transitions, setTransitions] = useState<Transition[]>([]);
  const [runs, setRuns] = useState<Record<string, InsightRun>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [pivot, setPivot] = useState<"driver" | "product" | "none">("none");
  const [error, setError] = useState<string | null>(null);

  const monthLabel = useCallback(
    (id: string) => months.find((m) => m.month_id === id)?.month_name ?? id,
    [months],
  );

  const loadRuns = useCallback(
    (trans: Transition[], ver: string) => {
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
    },
    [],
  );

  useEffect(() => {
    getRuleVersions().then((r) => setVersions(r.versions ?? [])).catch(() => setVersions([]));
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

  const regenerate = async () => {
    setBusy("starting…");
    setError(null);
    try {
      // one aggregate ("all"-scope) run per transition — the batch endpoint's
      // advisor="all" fan-out is driven from the Advisor page / e2e instead
      for (const t of transitions) {
        const { job_id } = await generateInsights("all", t.from_month_id, t.to_month_id);
        let status = await getInsightStatus(job_id);
        while (status.status === "running") {
          setBusy(`generating ${t.from_month_id} → ${t.to_month_id}…`);
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
    <section>
      <PageHeader title="AI Insights" meta="All Advisors · All Products · scope follows the Dashboard selection" />
      <div className="card">
        <div className="card-h">
          <div>
            <h2>What Is Driving the Changes in Month-over-Month Credited Revenue?</h2>
            <p>
              One card per month-over-month move · findings ranked by impact · every figure computed
              from graph data
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
            <button className="btn" onClick={regenerate} disabled={busy !== null}>
              {busy ? busy : "↻ Regenerate"}
            </button>
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
    </section>
  );
}
